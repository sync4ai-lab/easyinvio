"""Unified private claim triage. Evidence completeness never proves liability."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ClaimIntake(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    request_id: UUID = Field(default_factory=uuid4)
    reference: str = Field(min_length=1, max_length=200)
    reason: Literal['LOST', 'DAMAGED']
    description: str = Field(default='', max_length=1800)
    item_value_gbp: Decimal | None = Field(default=None, gt=0, le=50000, decimal_places=2)


class ScanFact(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status: str
    occurred_at: str


class ClaimDossier(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    reason: Literal['LOST', 'DAMAGED']
    description: str = Field(default='', max_length=1800)
    item_value_gbp: Decimal | None = Field(default=None, gt=0, le=50000, decimal_places=2)
    photo_count: int = Field(default=0, ge=0, le=10)
    scan_status: str
    last_scan_at: str | None = None
    scan_history: list[ScanFact] = Field(default_factory=list,max_length=5)
    active_policy_id: str | None = None
    route: Literal['MERCHANT_CARRIER_REVIEW', 'INSURER_REVIEW'] = 'MERCHANT_CARRIER_REVIEW'
    evidence_status: Literal['INCOMPLETE', 'READY_FOR_REVIEW'] = 'INCOMPLETE'
    financial_action: Literal['NONE'] = 'NONE'
    photo_verification: Literal['FORMAT_ONLY_NOT_PROOF_OF_INCIDENT'] = 'FORMAT_ONLY_NOT_PROOF_OF_INCIDENT'

    def missing(self) -> list[str]:
        result = []
        if len(self.description.strip()) < 10:
            result.append('an incident description of at least 10 characters')
        if self.item_value_gbp is None:
            result.append('the item value in GBP')
        if self.reason == 'DAMAGED' and self.photo_count == 0:
            result.append('a JPEG/PNG photo of the damaged item and packaging (up to 5 MB)')
        return result


@dataclass(frozen=True)
class ClaimScope:
    tenant_id: UUID
    shipment_id: UUID
    actor_id: UUID | None = None
    capability_sha256: str | None = None


class ClaimTriageService:
    def __init__(self, state: Any) -> None:
        self.state = state
        self.pool = state.finance.pool

    async def merchant_scope(self, context: Any, reference: str) -> ClaimScope:
        from backend.shipment_protection import require_claim_role
        require_claim_role(context)
        async with self.pool.acquire() as c:
            rows = await c.fetch('''SELECT s.id FROM public.shipments s
                JOIN public.users u ON u.tenant_id=s.tenant_id AND u.auth_user_id=$2 AND u.is_active
                JOIN public.tenants t ON t.tenant_id=s.tenant_id AND t.workspace_status='ACTIVE'
                WHERE s.tenant_id=$1 AND (s.id::text=$3 OR s.customer_reference=$3 OR s.tracking_number=$3) LIMIT 2''',
                context.tenant_id, context.user_id, reference)
        if len(rows) != 1:
            raise HTTPException(404, 'No unique claim shipment exists in your workspace')
        return ClaimScope(context.tenant_id, rows[0]['id'], actor_id=context.user_id)

    async def validate_scope(self, c: Any, scope: ClaimScope) -> Any:
        if scope.actor_id is not None:
            permitted = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.users u JOIN public.tenants t USING(tenant_id)
                WHERE u.tenant_id=$1 AND u.auth_user_id=$2 AND u.is_active
                AND u.role IN ('OWNER','ADMIN','DISPATCHER','ACCOUNTANT') AND t.workspace_status='ACTIVE')''',
                scope.tenant_id, scope.actor_id)
        else:
            permitted = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.tracking_share_links l
                JOIN public.tenants t USING(tenant_id) WHERE l.tenant_id=$1 AND l.token_sha256=$2
                AND $3=ANY(l.shipment_ids) AND l.revoked_at IS NULL AND l.expires_at>now() AND t.workspace_status='ACTIVE')''',
                scope.tenant_id, scope.capability_sha256, scope.shipment_id)
        if not permitted:
            raise HTTPException(403, 'Claim access is unavailable or expired')
        row = await c.fetchrow('SELECT status,last_tracking_event_at,logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2 FOR SHARE', scope.tenant_id, scope.shipment_id)
        if row is None:
            raise HTTPException(404, 'Claim shipment is unavailable')
        return row

    async def create(self, scope: ClaimScope, body: ClaimIntake) -> dict[str, Any]:
        from backend.cx_support import SupportCase, record_case
        async with self.pool.acquire() as c:
            async with c.transaction():
                shipment = await self.validate_scope(c, scope)
                await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',str(body.request_id))
                existing = await c.fetchrow('SELECT * FROM public.cx_claim_dossiers WHERE id=$1 FOR UPDATE', body.request_id)
                if existing:
                    self.assert_owner(existing, scope)
                    if existing['input_sha256']!=hashlib.sha256(body.model_dump_json().encode()).hexdigest():
                        raise HTTPException(409,'Claim request ID already used with different details')
                    return self.result(existing['id'], self.decode(existing['dossier']))
                metadata=json.loads(shipment['logistics_metadata']) if isinstance(shipment['logistics_metadata'],str) else shipment['logistics_metadata'] or {}
                insurance=metadata.get('insurance') or {}
                insured=await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.insurance_purchases WHERE tenant_id=$1 AND shipment_id=$2 AND state='INSURED')",scope.tenant_id,scope.shipment_id)
                policy=insurance.get('policy_id') if insured and insurance.get('provider')=='XCOVER' and insurance.get('status')=='CONFIRMED' else None
                # A recorded policy is evidence of cover, not an instruction to submit/settle.
                claims = getattr(self.state, 'claims', None)
                usable = policy is not None and claims is not None and claims.client.unavailable_reason() is None
                scans=await c.fetch("SELECT status,occurred_at FROM public.tracking_events WHERE tenant_id=$1 AND shipment_id=$2 AND response->>'applied'='true' ORDER BY occurred_at DESC LIMIT 5",scope.tenant_id,scope.shipment_id)
                dossier = ClaimDossier(scan_history=[ScanFact(status=r['status'],occurred_at=r['occurred_at'].isoformat()) for r in scans],reason=body.reason, description=body.description, item_value_gbp=body.item_value_gbp,
                    scan_status=shipment['status'], last_scan_at=shipment['last_tracking_event_at'].isoformat() if shipment['last_tracking_event_at'] else None,
                    active_policy_id=str(policy) if policy else None, route='INSURER_REVIEW' if usable else 'MERCHANT_CARRIER_REVIEW')
                dossier.evidence_status = 'INCOMPLETE' if dossier.missing() else 'READY_FOR_REVIEW'
                ticket = await record_case(c, SupportCase(request_id=body.request_id, tenant_id=scope.tenant_id,
                    shipment_id=scope.shipment_id, kind='COMPLAINT', category='DAMAGED' if body.reason == 'DAMAGED' else 'MISSING_DELAYED',
                    summary='Claim triage only. No insurer submission, liability decision, payout or wallet credit has been authorized.'))
                await c.execute('''INSERT INTO public.cx_claim_dossiers(id,tenant_id,shipment_id,ticket_id,actor_id,capability_sha256,dossier,input_sha256)
                    VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8)''',body.request_id,scope.tenant_id,scope.shipment_id,ticket,scope.actor_id,scope.capability_sha256,dossier.model_dump_json(),hashlib.sha256(body.model_dump_json().encode()).hexdigest())
                await c.execute('UPDATE public.support_tickets SET claim_dossier=$3::jsonb WHERE tenant_id=$1 AND id=$2', scope.tenant_id,ticket,dossier.model_dump_json())
                await self.mirror_insurer_intake(c,scope,body.request_id,dossier)
        return self.result(body.request_id, dossier)

    async def mirror_insurer_intake(self,c: Any,scope: ClaimScope,identifier: UUID,dossier: ClaimDossier) -> None:
        # Existing XClaim intake table; never change to SUBMISSION_PENDING or credit money.
        if dossier.route!='INSURER_REVIEW' or dossier.evidence_status!='READY_FOR_REVIEW' or scope.actor_id is None:
            return
        await c.execute("""INSERT INTO public.insurance_claim_cases
            (id,tenant_id,shipment_id,policy_id,reason,state,submission_payload,notes,created_by,payload_sha256)
            VALUES($1,$2,$3,$4,$5,'CLAIM_INGESTED',$6::jsonb,$7,$8,$9)
            ON CONFLICT(tenant_id,id) DO UPDATE SET submission_payload=excluded.submission_payload,
                notes=excluded.notes,payload_sha256=excluded.payload_sha256
            WHERE insurance_claim_cases.state='CLAIM_INGESTED'""",identifier,scope.tenant_id,scope.shipment_id,dossier.active_policy_id,
            'PARCEL_DAMAGED' if dossier.reason=='DAMAGED' else 'PARCEL_LOST',
            json.dumps({'cx_dossier_id':str(identifier),'triage':dossier.model_dump(mode='json'),'human_review_required':True}),
            dossier.description,scope.actor_id,hashlib.sha256(dossier.model_dump_json().encode()).hexdigest())

    @staticmethod
    def decode(value: Any) -> ClaimDossier:
        return ClaimDossier.model_validate_json(value) if isinstance(value, str) else ClaimDossier.model_validate(value)

    @staticmethod
    def assert_owner(row: Any, scope: ClaimScope) -> None:
        if (row['tenant_id'],row['shipment_id'],row['actor_id'],row['capability_sha256']) != (scope.tenant_id,scope.shipment_id,scope.actor_id,scope.capability_sha256):
            raise HTTPException(404, 'Claim dossier unavailable')

    async def update(self, scope: ClaimScope, identifier: UUID, *, description: str | None = None,
                     value: Decimal | None = None, image: bytes | None = None, mime: str | None = None) -> dict[str, Any]:
        if image is not None:
            from backend.shipment_protection import validate_evidence
            validate_evidence(image, mime)
        async with self.pool.acquire() as c:
            async with c.transaction():
                current=await self.validate_scope(c, scope)
                row = await c.fetchrow('SELECT * FROM public.cx_claim_dossiers WHERE id=$1 FOR UPDATE', identifier)
                if row is None:
                    raise HTTPException(404, 'Claim dossier unavailable')
                self.assert_owner(row, scope)
                dossier = self.decode(row['dossier'])
                data = dossier.model_dump()
                data['scan_status']=current['status']
                data['last_scan_at']=current['last_tracking_event_at'].isoformat() if current['last_tracking_event_at'] else None
                if description is not None:
                    data['description'] = description
                if value is not None:
                    data['item_value_gbp'] = value
                try:
                    dossier = ClaimDossier.model_validate(data)
                except ValidationError:
                    raise HTTPException(422,'Use an incident description up to 1800 characters and an item value above GBP 0, up to GBP 50000 with at most two decimal places') from None
                if image is not None:
                    count = await c.fetchval('SELECT count(*) FROM public.cx_claim_evidence WHERE dossier_id=$1',identifier)
                    duplicate=await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.cx_claim_evidence WHERE dossier_id=$1 AND content_sha256=$2)',identifier,hashlib.sha256(image).hexdigest())
                    if count >= 10 and not duplicate:
                        raise HTTPException(422,'Maximum 10 claim photographs')
                    await c.execute('''INSERT INTO public.cx_claim_evidence(id,dossier_id,tenant_id,content_sha256,content,mime_type)
                        VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(dossier_id,content_sha256) DO NOTHING''',
                        uuid4(),identifier,scope.tenant_id,hashlib.sha256(image).hexdigest(),image,mime)
                dossier.photo_count = await c.fetchval('SELECT count(*) FROM public.cx_claim_evidence WHERE dossier_id=$1',identifier)
                dossier.evidence_status = 'INCOMPLETE' if dossier.missing() else 'READY_FOR_REVIEW'
                await c.execute('UPDATE public.cx_claim_dossiers SET dossier=$2::jsonb,version=version+1,updated_at=now() WHERE id=$1',identifier,dossier.model_dump_json())
                await c.execute('UPDATE public.support_tickets SET claim_dossier=$3::jsonb WHERE tenant_id=$1 AND id=$2',scope.tenant_id,row['ticket_id'],dossier.model_dump_json())
                await self.mirror_insurer_intake(c,scope,identifier,dossier)
        return self.result(identifier, dossier)

    @staticmethod
    def result(identifier: UUID, dossier: ClaimDossier) -> dict[str, Any]:
        missing = dossier.missing()
        text = ('Please send together: ' + '; '.join(missing) + '.' if missing else
                'Your evidence is ready for human review. No claim has been approved or paid.')
        text += (' Insurer review is available.' if dossier.route == 'INSURER_REVIEW' else
                 'Your merchant can review a carrier claim even while insurer automation is unavailable.')
        if missing:
            text+=f' Reply Claim update {identifier} followed by the missing description/value (GBP), then send your photo.'
        return {'dossier_id':str(identifier),'dossier':dossier.model_dump(mode='json'),
                'message':f'Claim case {identifier}. '+text,'financial_action':'NONE'}

    async def recent(self, scope: ClaimScope) -> UUID | None:
        async with self.pool.acquire() as c:
            await self.validate_scope(c,scope)
            return await c.fetchval('''SELECT id FROM public.cx_claim_dossiers WHERE tenant_id=$1 AND shipment_id=$2
                AND actor_id IS NOT DISTINCT FROM $3::uuid AND capability_sha256 IS NOT DISTINCT FROM $4::text
                AND updated_at>now()-interval '15 minutes' ORDER BY updated_at DESC LIMIT 1''',
                scope.tenant_id,scope.shipment_id,scope.actor_id,scope.capability_sha256)


async def fetch_claim_photo(state: Any, url: str) -> tuple[bytes,str]:
    """Only authenticated-provider media on explicitly configured HTTPS hosts."""
    try:
        parsed = urlsplit(url)
        port=parsed.port
    except ValueError:
        raise HTTPException(422,'Invalid photograph URL') from None
    allowed = getattr(state.settings, 'whatsapp_evidence_allowed_hosts', [])
    if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.password or port not in {None,443}:
        raise HTTPException(422,'Upload the photo through the secure claim form; this media host is not approved')
    async with state.rating.client.stream('GET',url,timeout=5,follow_redirects=False) as response:
        if response.status_code != 200:
            raise HTTPException(422,'The provider photograph could not be retrieved; use the secure upload form')
        mime=response.headers.get('content-type','').split(';')[0]
        if mime not in {'image/png','image/jpeg'}:
            raise HTTPException(422,'Use a JPEG or PNG photograph')
        data=bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data)>5_000_000:
                raise HTTPException(422,'Photograph exceeds 5 MB')
    return bytes(data),mime


def value_from_text(text: str) -> Decimal | None:
    match=re.search(r'(?:£|GBP\s*)(\d+(?:\.\d{1,2})?)(?![\d.])',text,re.I)
    if match is None:
        return None
    value=Decimal(match[1])
    if not Decimal('0')<value<=Decimal('50000'):
        raise HTTPException(422,'Send the item value above GBP 0 and up to GBP 50000')
    return value
