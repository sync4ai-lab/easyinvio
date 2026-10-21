"""Fenced carrier close-out and explicit internal driver handover documents."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from io import BytesIO
import json
import logging
import re
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode, urljoin, urlsplit
from uuid import UUID, uuid4
from xml.sax.saxutils import escape

import asyncpg
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.dispatch_workspace import decoded
from backend.carrier_consolidation import carrier_identity

if TYPE_CHECKING:
    from main import Settings, TenantContext, CarrierAccount

DISPATCH_ROLES={'OWNER','ADMIN','DISPATCHER'}
logger=logging.getLogger('easyinvio.manifests')


class ManifestShipment(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: UUID
    tracking_number: str = Field(min_length=1,max_length=100)
    upstream_ids: list[str] = Field(min_length=1,max_length=100)
    weight_kg: Decimal = Field(gt=0,max_digits=10,decimal_places=3,allow_inf_nan=False)
    origin: dict[str,str | None]
    destination_postcode: str
    carrier_code: str = Field(min_length=1,max_length=50)

    @field_validator('weight_kg',mode='before')
    @classmethod
    def exact_weight(cls,value):
        if isinstance(value,(float,bool)):raise ValueError('Exact packed weight required')
        return value


class ManifestCandidateSummary(BaseModel):
    carrier_account_id: UUID
    carrier_code: str
    total_shipments: int
    total_weight_kg: Decimal
    origin_postcode: str
    document_kind: Literal['CARRIER_MANIFEST','INTERNAL_HANDOVER']


class ManifestResult(BaseModel):
    id: UUID
    status: Literal['DRAFT','SUBMITTED','FAILED','COMPLETED']
    carrier_account_id: UUID
    carrier_code: str
    total_shipments: int
    total_weight_kg: Decimal
    master_tracking_id: str | None = None
    manifest_document_url: str | None = None
    document_kind: Literal['CARRIER_MANIFEST','INTERNAL_HANDOVER']
    carrier_closed: bool = False
    message: str


class PreviewManifest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    warehouse_id: UUID | None = None


class CloseManifest(PreviewManifest):
    request_id: UUID
    carrier_account_id: UUID
    carrier_code: str | None = Field(default=None,min_length=1,max_length=50)


def postal_origin(address: dict) -> dict[str,str | None]:
    """Ignore contacts while retaining the exact physical pickup premise."""
    return {key: str(address[key]).strip().upper() if address.get(key) else None
            for key in ('line1','line2','city','state','postal_code','country_code')}


def manifest_shipment(row) -> ManifestShipment:
    metadata=decoded(row['logistics_metadata']);order=metadata.get('automation_order') or {}
    label=metadata.get('automation_label') or {}
    packages=order.get('packages') or []
    weight=sum((Decimal(str(p['actual_weight_kg'])) for p in packages),Decimal(0)) if packages else row['parcel_weight_kg']
    pieces=label.get('package_labels') or []
    ids=[str(p.get('upstream_id','')) for p in pieces] if len(pieces)>1 else [str(label.get('upstream_id') or row.get('upstream_shipment_id') or '')]
    if not all(ids):raise HTTPException(409,'Shipment has no exact carrier purchase reference')
    origin=order.get('origin') or decoded(row.get('origin_address'))
    if not all(origin.get(k) for k in ('line1','city','postal_code','country_code')):
        raise HTTPException(409,'Shipment pickup snapshot is incomplete')
    return ManifestShipment(id=row['id'],tracking_number=row['tracking_number'],upstream_ids=ids,
        weight_kg=weight,origin=postal_origin(origin),destination_postcode=(order.get('destination') or {}).get('postal_code',''),
        carrier_code=carrier_identity(row['carrier_code']))


def driver_sheet(manifest_id: UUID,carrier: str,shipments: list[ManifestShipment],created_at: datetime) -> bytes:
    from reportlab.graphics.barcode import code128
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    output=BytesIO();styles=getSampleStyleSheet()
    master='EI-'+manifest_id.hex[:24].upper()
    story=[Paragraph('EasyInvio | Driver handover sheet',styles['Title']),
        Paragraph('INTERNAL HANDOVER RECORD - not a carrier-issued acceptance scan form',styles['Normal']),Spacer(1,12),
        Paragraph(escape(f'Carrier: {carrier} | Created: {created_at:%Y-%m-%d %H:%M} UTC'),styles['Normal']),
        Paragraph(escape('Pickup: '+', '.join(v for v in shipments[0].origin.values() if v)),styles['Normal']),Spacer(1,12),
        code128.Code128(master,barHeight=36,barWidth=.8),Spacer(1,8),Paragraph(master,styles['Normal']),Spacer(1,14)]
    rows=[['#','Tracking reference','Destination','Packed kg']]
    for index,item in enumerate(shipments,1):
        rows.append([str(index),Paragraph(escape(item.tracking_number),styles['Normal']),
                     Paragraph(escape(item.destination_postcode),styles['Normal']),format(item.weight_kg,'.3f')])
    table=Table(rows,colWidths=[30,255,120,75],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e2e8f0')),
        ('GRID',(0,0),(-1,-1),.4,colors.HexColor('#cbd5e1')),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('BOTTOMPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),8),('ALIGN',(-1,0),(-1,-1),'RIGHT')]))
    story += [table,Spacer(1,14),Paragraph(f'{len(shipments)} shipments | Total packed weight: {sum((s.weight_kg for s in shipments),Decimal(0)):.3f} kg',styles['Heading3']),
        Paragraph('Driver name/signature: _____________________    Collection date/time: _____________________',styles['Normal']),Spacer(1,12),
        Paragraph('This sheet records preparation for handover. It does not schedule a collection, prove pickup or replace carrier-required close-out paperwork.',styles['Normal'])]
    def footer(canvas,document):
        canvas.setFont('Helvetica',8);canvas.drawString(36,23,'EasyInvio | '+str(manifest_id));canvas.drawRightString(A4[0]-36,23,f'Page {document.page}')
    SimpleDocTemplate(output,pagesize=A4,leftMargin=36,rightMargin=36,topMargin=36,bottomMargin=44).build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()


class ManifestService:
    def __init__(self,pool: asyncpg.Pool,settings: Settings,http_client: httpx.AsyncClient,*,repository=None):
        self.pool,self.settings,self.client=pool,settings,http_client
        if repository is None:
            from main import SupabaseRepository
            repository=SupabaseRepository(http_client,settings)
        self.repository=repository

    async def actor(self,connection,tenant_id: UUID,user_id: UUID):
        from main import TenantContext
        row=await connection.fetchrow('''SELECT u.role,t.is_sandbox FROM public.users u JOIN public.tenants t ON t.tenant_id=u.tenant_id
          WHERE u.tenant_id=$1 AND u.auth_user_id=$2 AND u.is_active AND t.workspace_status='ACTIVE' FOR SHARE OF u,t''',tenant_id,user_id)
        if row is None:
            row=await connection.fetchrow('''SELECT 'OWNER' AS role,t.is_sandbox FROM public.admin_client_assistance_sessions a
              JOIN public.tenants t ON t.tenant_id=a.tenant_id WHERE a.tenant_id=$1 AND a.actor_auth_user_id=$2
              AND a.revoked_at IS NULL AND a.expires_at>now() AND t.workspace_status='ACTIVE' LIMIT 1 FOR SHARE OF a,t''',tenant_id,user_id)
        if not row or row['role'] not in DISPATCH_ROLES:raise HTTPException(403,'Active dispatch membership required')
        if bool(row['is_sandbox']) != (self.settings.provider_environment=='TEST'):
            raise HTTPException(403,'Manifest environment does not match this workspace')
        if ((self.settings.provider_environment=='TEST' and self.settings.database_environment!='SANDBOX')
            or (self.settings.provider_environment=='LIVE' and (self.settings.database_environment!='LIVE' or not self.settings.automation_purchase_enabled))):
            raise HTTPException(403,'Manifest provider mutations are disabled in this environment')
        return TenantContext(tenant_id,user_id,row['role'],'')

    async def warehouse(self,connection,tenant_id: UUID,warehouse_id: UUID | None) -> dict | None:
        if warehouse_id is None:return None
        row=await connection.fetchrow('''SELECT address FROM public.tenant_catalog_addresses
          WHERE tenant_id=$1 AND id=$2 AND archived_at IS NULL AND address_role IN ('PICKUP','SENDER')''',tenant_id,warehouse_id)
        if not row:raise HTTPException(404,'Active pickup warehouse not found in this workspace')
        return postal_origin(decoded(row['address']))

    def eligibility(self) -> str:
        return """ FROM public.shipments s
          JOIN public.carrier_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.carrier_account_id
          JOIN public.tenants t ON t.tenant_id=s.tenant_id
          WHERE s.tenant_id=$1 AND ($2::uuid IS NULL OR s.carrier_account_id=$2)
          AND s.status='BOOKED' AND s.manifest_id IS NULL AND t.workspace_status='ACTIVE'
          AND a.environment=$3 AND t.is_sandbox=$4
          AND ($5::text[] IS NULL OR regexp_replace(upper(s.carrier_code),'[^A-Z0-9]','','g')=ANY($5))
          AND ($6::jsonb IS NULL OR """+self.origin_sql()+"""=$6::jsonb)
          AND NOT EXISTS(SELECT 1 FROM public.partner_cancellations p WHERE p.tenant_id=s.tenant_id AND p.shipment_id=s.id) """

    @staticmethod
    def origin_sql() -> str:
        keys=('line1','line2','city','state','postal_code','country_code')
        return 'jsonb_build_object('+','.join("'"+k+"',upper(nullif(btrim(s.origin_address->>'"+k+"'),''))" for k in keys)+')'

    def selection_args(self,tenant_id,account_id,carrier,warehouse):
        from backend.carrier_consolidation import ALIASES
        aliases=([carrier_identity(carrier)]+[key for key,value in ALIASES.items() if value==carrier_identity(carrier)]) if carrier else None
        return (tenant_id,account_id,self.settings.provider_environment,self.settings.provider_environment=='TEST',aliases,json.dumps(warehouse) if warehouse else None)

    async def candidates(self,connection,tenant_id: UUID,account_id: UUID | None = None,*,carrier=None,warehouse=None):
        return await connection.fetch('SELECT s.*,a.api_base_url AS manifest_endpoint'+self.eligibility()+
            ' ORDER BY s.carrier_account_id,s.id LIMIT 1001',*self.selection_args(tenant_id,account_id,carrier,warehouse))

    async def get_manifestable_summary(self,tenant_id: UUID,warehouse_id: UUID | None = None) -> list[ManifestCandidateSummary]:
        async with self.pool.acquire() as connection:
            warehouse=await self.warehouse(connection,tenant_id,warehouse_id)
            rows=await connection.fetch("""SELECT s.carrier_account_id,s.carrier_code,a.api_base_url AS manifest_endpoint,
              """+self.origin_sql()+""" AS origin,count(*) AS total_shipments,
              sum(coalesce((SELECT sum((box->>'actual_weight_kg')::numeric)
                FROM jsonb_array_elements(coalesce(s.logistics_metadata->'automation_order'->'packages','[]'::jsonb)) box),s.parcel_weight_kg)) AS total_weight_kg
              """+self.eligibility()+ ' GROUP BY s.carrier_account_id,s.carrier_code,a.api_base_url,origin',
                *self.selection_args(tenant_id,None,None,warehouse))
        groups={}
        for row in rows:
            origin=decoded(row['origin']);carrier=carrier_identity(row['carrier_code'])
            kind='CARRIER_MANIFEST' if row['manifest_endpoint']=='https://api.easypost.com/v2' else 'INTERNAL_HANDOVER'
            key=(row['carrier_account_id'],carrier,json.dumps(origin,sort_keys=True))
            if key not in groups:
                groups[key]=ManifestCandidateSummary(carrier_account_id=row['carrier_account_id'],carrier_code=carrier,
                    total_shipments=0,total_weight_kg=Decimal(0),origin_postcode=origin['postal_code'],document_kind=kind)
            groups[key].total_shipments+=row['total_shipments'];groups[key].total_weight_kg+=row['total_weight_kg']
        return list(groups.values())

    def result(self,row) -> ManifestResult:
        complete=row['status']=='COMPLETED';native=row['document_kind']=='CARRIER_MANIFEST'
        return ManifestResult(id=row['id'],status=row['status'],carrier_account_id=row['carrier_account_id'],carrier_code=row['carrier_code'],
            total_shipments=row['total_shipments'],total_weight_kg=row['total_weight_kg'],master_tracking_id=row['master_tracking_id'],
            manifest_document_url=self.download_url(row['tenant_id'],row['id']) if complete else None,
            document_kind=row['document_kind'],carrier_closed=complete and native,
            message=(('Carrier manifest created. Print the document for the selected carrier.' if native else
                'Internal driver handover sheet prepared. Carrier-specific closure/collection is not confirmed.') if complete else
                'Manifest is pending carrier creation or reconciliation. Check status; do not submit these shipments again.'
                ) + (' Batch limit is 1000 shipments; preview any remaining bookings separately.' if row['total_shipments']==1000 else ''))

    def download_url(self,tenant_id: UUID,manifest_id: UUID) -> str | None:
        base=self.settings.booking_page_url or self.settings.auth_recovery_redirect_url
        parsed=urlsplit(base);secret=self.settings.quote_link_secret.get_secret_value()
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or len(secret)<32:return None
        now=datetime.now(timezone.utc)
        token=jwt.encode({'iss':'easyinvio-manifests','aud':'manifest-document','t':str(tenant_id),'m':str(manifest_id),
            'iat':int(now.timestamp()),'exp':int((now+timedelta(hours=24)).timestamp())},secret,algorithm='HS256')
        return urljoin(base,f'/api/v1/dispatch/manifests/{manifest_id}/download')+'?'+urlencode({'token':token})

    async def close_manifest(self,tenant_id: UUID,carrier_account_id: UUID,user_id: UUID,*,request_id: UUID | None = None,
                             carrier_code: str | None = None,warehouse_id: UUID | None = None) -> ManifestResult:
        try:
            return await self._close_manifest(tenant_id,carrier_account_id,user_id,request_id=request_id,
                carrier_code=carrier_code,warehouse_id=warehouse_id)
        except (asyncpg.UniqueViolationError,asyncpg.LockNotAvailableError,asyncpg.DeadlockDetectedError):
            raise HTTPException(409,'Manifest selection is being changed; refresh and reuse the same request key') from None
        except asyncpg.PostgresError:
            raise HTTPException(503,'Manifest storage unavailable; check the existing request before retrying') from None
        except ValueError:
            raise HTTPException(409,'Shipment snapshots require reconciliation before manifesting') from None

    async def _close_manifest(self,tenant_id: UUID,carrier_account_id: UUID,user_id: UUID,*,request_id: UUID | None = None,
                              carrier_code: str | None = None,warehouse_id: UUID | None = None) -> ManifestResult:
        request_id=request_id or uuid4()
        digest=hashlib.sha256(json.dumps([str(carrier_account_id),carrier_identity(carrier_code) if carrier_code else None,str(warehouse_id)],sort_keys=True).encode()).hexdigest()
        async with self.pool.acquire() as connection:
            async with connection.transaction():context=await self.actor(connection,tenant_id,user_id)
        accounts=await self.repository.accounts(context,historical_account_id=carrier_account_id)
        account=next((a for a in accounts if a.id==carrier_account_id and a.tenant_id==tenant_id),None)
        if account is None:raise HTTPException(404,'Carrier account not found in this workspace')
        native=account.base_url=='https://api.easypost.com/v2'
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.actor(connection,tenant_id,user_id)
                await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'manifest:{tenant_id}:{carrier_account_id}')
                previous=await connection.fetchrow('SELECT * FROM public.carrier_manifests WHERE tenant_id=$1 AND request_id=$2',tenant_id,request_id)
                if previous:
                    if previous['input_sha256']!=digest or previous['created_by']!=user_id:raise HTTPException(409,'Manifest request key belongs to different input or operator')
                    return self.result(previous)
                active=await connection.fetchval("SELECT id FROM public.carrier_manifests WHERE tenant_id=$1 AND carrier_account_id=$2 AND status IN ('DRAFT','SUBMITTED')",tenant_id,carrier_account_id)
                if active:raise HTTPException(409,'A carrier close-out is already submitted and requires reconciliation')
                warehouse=await self.warehouse(connection,tenant_id,warehouse_id)
                rows=await self.candidates(connection,tenant_id,carrier_account_id,carrier=carrier_code,warehouse=warehouse)
                items=[manifest_shipment(row) for row in rows[:1000]]
                items=[i for i in items if (not carrier_code or i.carrier_code==carrier_identity(carrier_code)) and (warehouse is None or i.origin==warehouse)]
                if not items:raise HTTPException(409,'No eligible booked shipments match this carrier/warehouse')
                if len({i.carrier_code for i in items})!=1 or len({json.dumps(i.origin,sort_keys=True) for i in items})!=1:
                    raise HTTPException(409,'Choose exactly one physical carrier and pickup warehouse per manifest')
                if native and (any(not re_id.startswith('shp_') for i in items for re_id in i.upstream_ids) or any(len(i.upstream_ids)!=1 for i in items)):
                    raise HTTPException(409,'Carrier ScanForm requires supported individual purchased shipment IDs')
                # Use the existing cancellation lock namespace before taking row locks.
                await connection.fetch('''SELECT pg_advisory_xact_lock(hashtextextended(key,0)) FROM unnest($1::text[]) AS key ORDER BY key''',
                    [f'partner-void:{tenant_id}:{i.id}' for i in sorted(items,key=lambda i:str(i.id))])
                locked=await connection.fetch('''SELECT id,status,manifest_id FROM public.shipments WHERE tenant_id=$1 AND id=ANY($2::uuid[]) ORDER BY id FOR UPDATE''',tenant_id,[i.id for i in items])
                if len(locked)!=len(items) or any(r['status']!='BOOKED' or r['manifest_id'] is not None for r in locked):
                    raise HTTPException(409,'Shipment state changed; refresh the manifest preview')
                cancelled=await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.partner_cancellations WHERE tenant_id=$1 AND shipment_id=ANY($2::uuid[]))',tenant_id,[i.id for i in items])
                if cancelled:raise HTTPException(409,'A selected shipment has a cancellation in progress')
                manifest_id=uuid4();weight=sum((i.weight_kg for i in items),Decimal(0))
                if weight>Decimal('9999999.999'):raise HTTPException(409,'Manifest total weight exceeds supported precision')
                snapshot=json.dumps([i.model_dump(mode='json') for i in items])
                await connection.execute('''INSERT INTO public.carrier_manifests(id,tenant_id,carrier_account_id,carrier_code,status,
                  total_shipments,total_weight_kg,created_by,request_id,input_sha256,document_kind,snapshot,environment)
                  VALUES($1,$2,$3,$4,'SUBMITTED',$5,$6,$7,$8,$9,$10,$11::jsonb,$12)''',manifest_id,tenant_id,carrier_account_id,
                    items[0].carrier_code,len(items),weight,user_id,request_id,digest,'CARRIER_MANIFEST' if native else 'INTERNAL_HANDOVER',snapshot,self.settings.provider_environment)
                await connection.execute('UPDATE public.shipments SET manifest_id=$3 WHERE tenant_id=$1 AND id=ANY($2::uuid[])',tenant_id,[i.id for i in items],manifest_id)
                await connection.execute("INSERT INTO public.carrier_manifest_events(tenant_id,manifest_id,actor_auth_user_id,event_type) VALUES($1,$2,$3,'SUBMITTED')",tenant_id,manifest_id,user_id)
        try:
            if native:
                from backend.automation_three_partners import create_adapter
                adapter=create_adapter(self.client,account,environment=self.settings.provider_environment)
                response=await adapter.request('POST','/scan_forms',{'shipments':[{'id':i.upstream_ids[0]} for i in items]})
                reference=response.get('id')
                if not isinstance(reference,str) or not re.fullmatch(r'sf_[A-Za-z0-9]{1,96}',reference):raise ValueError('Invalid carrier manifest identity')
                async with self.pool.acquire() as connection:
                    await connection.execute('UPDATE public.carrier_manifests SET provider_reference=$3,updated_at=now() WHERE tenant_id=$1 AND id=$2',tenant_id,manifest_id,reference)
                await self.finish_native(tenant_id,manifest_id,user_id,items,response,account)
            else:
                pdf=await asyncio.to_thread(driver_sheet,manifest_id,items[0].carrier_code,items,datetime.now(timezone.utc))
                await self.complete(tenant_id,manifest_id,user_id,pdf,'EI-'+manifest_id.hex[:24].upper(),None)
        except Exception as error:
            from backend.automation_freight_engine import PurchaseRejected
            if isinstance(error,PurchaseRejected):
                async with self.pool.acquire() as connection:
                    async with connection.transaction():
                        await connection.execute("UPDATE public.carrier_manifests SET status='FAILED',error_code='CARRIER_REJECTED',updated_at=now() WHERE tenant_id=$1 AND id=$2",tenant_id,manifest_id)
                        await connection.execute("INSERT INTO public.carrier_manifest_events(tenant_id,manifest_id,actor_auth_user_id,event_type) VALUES($1,$2,$3,'FAILED') ON CONFLICT DO NOTHING",tenant_id,manifest_id,user_id)
            else:
                logger.warning('Manifest outcome retained id=%s error_type=%s',manifest_id,type(error).__name__)
                async with self.pool.acquire() as connection:
                    await connection.execute("UPDATE public.carrier_manifests SET error_code='OUTCOME_UNCONFIRMED',updated_at=now() WHERE tenant_id=$1 AND id=$2 AND status='SUBMITTED'",tenant_id,manifest_id)
            # Unknown outcomes retain SUBMITTED and shipment claims. GET recovery only.
        return await self.status(tenant_id,manifest_id,user_id,recover=False)

    async def finish_native(self,tenant_id,manifest_id,user_id,items,response,account):
        if response.get('status')=='failed':
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute("UPDATE public.carrier_manifests SET status='FAILED',error_code='CARRIER_REJECTED',updated_at=now() WHERE tenant_id=$1 AND id=$2 AND status='SUBMITTED'",tenant_id,manifest_id)
                    await connection.execute("INSERT INTO public.carrier_manifest_events(tenant_id,manifest_id,actor_auth_user_id,event_type) VALUES($1,$2,$3,'FAILED') ON CONFLICT DO NOTHING",tenant_id,manifest_id,user_id)
            return
        if response.get('status')!='created':return
        if sorted(response.get('tracking_codes') or [])!=sorted(i.tracking_number for i in items):
            raise ValueError('Carrier manifest tracking membership mismatch')
        url=response.get('form_url');parsed=urlsplit(url or '')
        if parsed.scheme!='https' or parsed.hostname not in self.settings.partner_document_allowed_hosts or parsed.username or parsed.password:
            raise ValueError('Unapproved carrier manifest document')
        async with self.client.stream('GET',url,timeout=20,follow_redirects=False) as reply:
            if reply.status_code!=200:raise ValueError('Carrier manifest not ready')
            data=bytearray()
            async for chunk in reply.aiter_bytes():
                data.extend(chunk)
                if len(data)>10_000_000:raise ValueError('Manifest PDF exceeds limit')
        if not data.startswith(b'%PDF-'):raise ValueError('Carrier did not return PDF')
        from pypdf import PdfReader
        if not 1<=len(PdfReader(BytesIO(data)).pages)<=100:raise ValueError('Invalid carrier manifest PDF')
        confirmation=response.get('confirmation')
        await self.complete(tenant_id,manifest_id,user_id,bytes(data),confirmation if isinstance(confirmation,str) and len(confirmation)<=100 else None,url)

    async def complete(self,tenant_id,manifest_id,user_id,pdf,master,provider_url):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                row=await connection.fetchrow('SELECT status FROM public.carrier_manifests WHERE tenant_id=$1 AND id=$2 FOR UPDATE',tenant_id,manifest_id)
                if not row or row['status']!='SUBMITTED':return
                await connection.execute('''UPDATE public.carrier_manifests SET status='COMPLETED',document_pdf=$3,
                  master_tracking_id=$4,provider_document_url=$5,manifest_document_url=$6,updated_at=now() WHERE tenant_id=$1 AND id=$2''',
                    tenant_id,manifest_id,pdf,master,provider_url,f'/api/v1/dispatch/manifests/{manifest_id}/document')
                await connection.execute("UPDATE public.shipments SET status='MANIFESTED' WHERE tenant_id=$1 AND manifest_id=$2 AND status='BOOKED'",tenant_id,manifest_id)
                await connection.execute("INSERT INTO public.carrier_manifest_events(tenant_id,manifest_id,actor_auth_user_id,event_type) VALUES($1,$2,$3,'COMPLETED') ON CONFLICT DO NOTHING",tenant_id,manifest_id,user_id)

    async def status(self,tenant_id: UUID,manifest_id: UUID,user_id: UUID,*,recover=True) -> ManifestResult:
        async with self.pool.acquire() as connection:
            async with connection.transaction():await self.actor(connection,tenant_id,user_id)
            row=await connection.fetchrow('SELECT * FROM public.carrier_manifests WHERE tenant_id=$1 AND id=$2',tenant_id,manifest_id)
        if not row:raise HTTPException(404,'Manifest not found in this workspace')
        if recover and row['status']=='SUBMITTED' and row['provider_reference']:
            try:
                from main import TenantContext
                from backend.automation_three_partners import create_adapter
                accounts=await self.repository.accounts(TenantContext(tenant_id,user_id,'DISPATCHER',''),historical_account_id=row['carrier_account_id'])
                account=next(a for a in accounts if a.id==row['carrier_account_id'] and a.base_url=='https://api.easypost.com/v2')
                adapter=create_adapter(self.client,account,environment=row['environment'])
                response=await adapter.request('GET','/scan_forms/'+row['provider_reference'])
                if response.get('id')!=row['provider_reference']:raise ValueError('Manifest identity mismatch')
                await self.finish_native(tenant_id,manifest_id,user_id,[ManifestShipment.model_validate(i) for i in decoded(row['snapshot'])],response,account)
                async with self.pool.acquire() as connection:row=await connection.fetchrow('SELECT * FROM public.carrier_manifests WHERE tenant_id=$1 AND id=$2',tenant_id,manifest_id)
            except Exception as error:
                logger.warning('Manifest read recovery deferred id=%s error_type=%s',manifest_id,type(error).__name__)
        return self.result(row)

    async def document(self,tenant_id: UUID,manifest_id: UUID) -> Response:
        async with self.pool.acquire() as connection:
            row=await connection.fetchrow("SELECT document_pdf FROM public.carrier_manifests WHERE tenant_id=$1 AND id=$2 AND status='COMPLETED'",tenant_id,manifest_id)
        if not row:raise HTTPException(404,'Completed manifest document not found')
        return Response(bytes(row['document_pdf']),media_type='application/pdf',headers={'Cache-Control':'no-store',
            'Content-Disposition':f'attachment; filename="easyinvio-manifest-{manifest_id}.pdf"','X-Content-Type-Options':'nosniff'})


def build_router(authenticate):
    router=APIRouter(prefix='/api/v1/dispatch/manifests',tags=['Carrier manifests'])
    def service(request):return request.app.state.manifests
    def guard(request,context):
        from main import validate_tenant_query
        if context.role not in DISPATCH_ROLES:raise HTTPException(403,'Dispatch role required')
        validate_tenant_query(request,context.tenant_id)
    @router.post('/preview',response_model=list[ManifestCandidateSummary])
    async def preview(body: PreviewManifest,request: Request,context=Depends(authenticate)):
        guard(request,context)
        return await service(request).get_manifestable_summary(context.tenant_id,body.warehouse_id)
    @router.post('/close',response_model=ManifestResult)
    async def close(body: CloseManifest,request: Request,context=Depends(authenticate)):
        guard(request,context)
        return await service(request).close_manifest(context.tenant_id,body.carrier_account_id,context.user_id,
            request_id=body.request_id,carrier_code=body.carrier_code,warehouse_id=body.warehouse_id)
    @router.get('/{manifest_id}',response_model=ManifestResult)
    async def status(manifest_id: UUID,request: Request,context=Depends(authenticate)):
        guard(request,context);return await service(request).status(context.tenant_id,manifest_id,context.user_id)
    @router.get('/{manifest_id}/document')
    async def document(manifest_id: UUID,request: Request,context=Depends(authenticate)):
        guard(request,context);return await service(request).document(context.tenant_id,manifest_id)
    @router.get('/{manifest_id}/download')
    async def download(manifest_id: UUID,token: str,request: Request):
        try:
            if len(token)>2000:raise ValueError('Invalid token')
            claims=jwt.decode(token,request.app.state.settings.quote_link_secret.get_secret_value(),algorithms=['HS256'],
                issuer='easyinvio-manifests',audience='manifest-document',options={'require':['iss','aud','t','m','iat','exp']})
            if claims['m']!=str(manifest_id) or claims['exp']-claims['iat']>86400:raise ValueError('Invalid token scope')
            tenant_id=UUID(claims['t'])
        except (jwt.PyJWTError,ValueError,TypeError,KeyError):raise HTTPException(401,'Invalid or expired manifest download') from None
        return await service(request).document(tenant_id,manifest_id)
    return router
