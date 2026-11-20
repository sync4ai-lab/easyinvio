"""Capability-scoped consumer CX; no consumer ever receives a TenantContext.

Return execution uses a separately persisted, explicitly authorized merchant
policy and a freshly resolved merchant actor. No model participates in spending.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, TYPE_CHECKING, Any, Mapping
from urllib.parse import urlsplit, parse_qs
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from asyncpg import Connection
from starlette.datastructures import FormData
from backend.agents.conversation_context import ConsumerDraft
from backend.cx_intents import cx_intent
from backend.cx_support import SupportCase, record_case
from backend.whatsapp_provider import account, number, provider
if TYPE_CHECKING:
    from backend.whatsapp_queue import OutboundPart
    from main import TenantContext

TOKEN = re.compile(r'(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{40,100})(?![A-Za-z0-9_-])')


def tracking_token(text: str, base: str) -> tuple[str | None, str]:
    """Extract a bearer from a command, plain text, or our own HTTPS URL."""
    direct = re.search(r'\btrack\s+link\s+([A-Za-z0-9_-]{40,100})(?![A-Za-z0-9_-])', text, re.I)
    if direct:
        return direct[1], (text[:direct.start()] + text[direct.end():]).strip()
    for match in re.finditer(r'https://[^\s]+', text):
        try:
            parsed = urlsplit(match[0].rstrip('.,'))
        except ValueError:
            continue
        expected = urlsplit(base)
        if parsed.netloc != expected.netloc or parsed.username or parsed.password:
            continue
        # Public tracking stores its bearer in the fragment, never a server log.
        for token in [parsed.fragment, *parse_qs(parsed.fragment).get('token', []),
                      *parse_qs(parsed.query).get('token', [])]:
            if TOKEN.fullmatch(token):
                return token, (text[:match.start()] + text[match.end():]).strip()
    if not re.search(r'https?://',text,re.I):
        candidates=list(TOKEN.finditer(text))
        if len(candidates)==1:
            match=candidates[0]
            return match[1],(text[:match.start()]+text[match.end():]).strip()
    return None, text


class ConsumerReturnPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = Field(default=False, strict=True)
    window_days: int = Field(default=30, ge=1, le=90)
    charge_bearer: Literal['RETAILER_PAY','CUSTOMER_PAY'] = 'RETAILER_PAY'
    maximum_price_gbp: Decimal = Field(default=Decimal('10'), gt=0, le=100, decimal_places=2)


class ConsumerCX:
    def __init__(self, request: Request):
        self.state = request.app.state
        self.settings = self.state.settings
        self.pool = self.state.tracking_workspace.pool
        self.queue = self.state.whatsapp_queue
        self.workspace = self.state.tracking_workspace

    async def scope(self, draft: ConsumerDraft) -> Mapping[str, Any]:
        """Every turn revalidates revocation, expiry, tenant and selected parcel."""
        if not draft.active():
            raise HTTPException(410,'Your secure WhatsApp session expired. Paste your merchant’s secure tracking link again.')
        await self.workspace.resolve(draft.token)
        async with self.pool.acquire() as c:
            link = await c.fetchrow('''SELECT * FROM public.tracking_share_links
              WHERE token_sha256=$1 AND revoked_at IS NULL AND expires_at>now()''',draft.token_sha256)
            if link:
                ordered = await c.fetch('''SELECT id FROM public.shipments WHERE tenant_id=$1 AND id=ANY($2::uuid[])
                  ORDER BY created_at,id''',link['tenant_id'],link['shipment_ids'])
                link = dict(link,shipment_ids=[row['id'] for row in ordered])
        if not link or link['tenant_id'] != draft.tenant_id or draft.shipment_id not in link['shipment_ids']:
            raise HTTPException(404,'This secure tracking link is no longer available.')
        return link

    async def load(self, sender: str, receiver: str) -> ConsumerDraft | None:
        async with self.pool.acquire() as c:
            row = await c.fetchrow('''SELECT * FROM public.whatsapp_consumer_sessions
              WHERE provider=$1 AND provider_account=$2 AND sender_e164=$3 AND receiver_e164=$4
                AND expires_at>now()''',provider(self.settings),account(self.settings),sender,receiver)
        if not row:
            return None
        draft = ConsumerDraft.model_validate_json(self.queue.ciphers[row['key_id']].decrypt(bytes(row['payload_ciphertext'])))
        if (draft.sender_e164,draft.receiver_e164,draft.token_sha256,draft.tenant_id,draft.shipment_id) != (
                sender,receiver,row['token_sha256'],row['tenant_id'],row['shipment_id']):
            raise HTTPException(403,'Consumer session identity mismatch')
        await self.scope(draft)
        return draft

    async def save(self, draft: ConsumerDraft, link: Mapping[str, Any]) -> None:
        await self.scope(draft)
        async with self.pool.acquire() as c:
            await c.execute('''INSERT INTO public.whatsapp_consumer_sessions
              (provider,provider_account,sender_e164,receiver_e164,token_sha256,tenant_id,share_link_id,shipment_id,payload_ciphertext,key_id,expires_at)
              VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
              ON CONFLICT(provider,provider_account,sender_e164,receiver_e164) DO UPDATE SET
              token_sha256=excluded.token_sha256,tenant_id=excluded.tenant_id,share_link_id=excluded.share_link_id,
              shipment_id=excluded.shipment_id,payload_ciphertext=excluded.payload_ciphertext,key_id=excluded.key_id,expires_at=excluded.expires_at''',
              provider(self.settings),account(self.settings),draft.sender_e164,draft.receiver_e164,draft.token_sha256,
              draft.tenant_id,link['id'],draft.shipment_id,self.queue.encrypt(draft.model_dump_json().encode()),self.queue.key_id,draft.expires_at)

    async def case(self, draft: ConsumerDraft, request_id: UUID, kind: str, category: str, summary: str) -> UUID:
        from backend.tracking_workspace import CustomerRequest
        await self.scope(draft)
        async with self.pool.acquire() as c:
            async with c.transaction():
                result = await self.workspace.customer_request(CustomerRequest(token=draft.token,request_id=request_id,note=summary),
                    connection=c,shipment_id=draft.shipment_id)
                return await record_case(c,SupportCase(request_id=request_id,tenant_id=draft.tenant_id,
                    shipment_id=draft.shipment_id,kind=kind,category=category,summary=summary,
                    customer_request_id=UUID(result['request_id'])))

    async def handle(self, form: FormData) -> list[OutboundPart]:
        from backend.whatsapp_queue import reply_parts
        from backend.agents.conversational_gateway import message_xml
        sender,receiver = (form[k].removeprefix('whatsapp:') for k in ('From','To'))
        identity = uuid5(NAMESPACE_URL,f'consumer:{provider(self.settings)}:{account(self.settings)}:{form["MessageSid"]}')
        digest = hashlib.sha256(json.dumps(dict(form),sort_keys=True).encode()).hexdigest()
        async with self.pool.acquire() as c:
            claimed = await c.fetchval('''INSERT INTO public.whatsapp_consumer_messages(id,input_sha256,state,key_id)
              VALUES($1,$2,'PROCESSING',$3) ON CONFLICT DO NOTHING RETURNING id''',identity,digest,self.queue.key_id)
            if not claimed:
                previous = await c.fetchrow('SELECT * FROM public.whatsapp_consumer_messages WHERE id=$1',identity)
        if not claimed:
            if previous['input_sha256'] != digest:
                raise HTTPException(409,'Consumer message identity conflict')
            if previous['state']=='COMPLETE':
                # Cached document links cannot bypass expiry or revocation.
                if previous['token_sha256']:
                    if previous['created_at']<datetime.now(timezone.utc)-timedelta(minutes=15):
                        raise HTTPException(410,'This conversation expired. Paste your secure tracking link again.')
                    current=await self.load(sender,receiver)
                    if current is None or current.token_sha256!=previous['token_sha256']:
                        raise HTTPException(410,'This request belongs to a different or expired tracking session.')
                from backend.whatsapp_queue import OutboundPart
                raw = self.queue.ciphers[previous['key_id']].decrypt(bytes(previous['response_ciphertext']))
                return [OutboundPart.model_validate(part) for part in json.loads(raw)]
            return reply_parts(message_xml('Your earlier request needs review. Please contact the retailer; do not repeat payment or return booking.'))
        try:
            parts = await self.process(form, identity, sender, receiver)
        except HTTPException as error:
            if error.status_code>=500:
                raise  # Preserve the uncertain action fence.
            detail = error.detail if isinstance(error.detail,str) else 'This request needs retailer review.'
            parts = reply_parts(message_xml(detail))
        async with self.pool.acquire() as c:
            scope_hash=await c.fetchval('''SELECT token_sha256 FROM public.whatsapp_consumer_sessions
              WHERE provider=$1 AND provider_account=$2 AND sender_e164=$3 AND receiver_e164=$4 AND expires_at>now()''',
              provider(self.settings),account(self.settings),sender,receiver)
            await c.execute("UPDATE public.whatsapp_consumer_messages SET state='COMPLETE',response_ciphertext=$2,token_sha256=$3 WHERE id=$1",
                identity,self.queue.encrypt(json.dumps([part.model_dump() for part in parts]).encode()),scope_hash)
        return parts

    async def process(self, form: FormData, identity: UUID, sender: str, receiver: str) -> list[OutboundPart]:
        from backend.whatsapp_queue import reply_parts
        from backend.agents.conversational_gateway import message_xml
        def reply(text: str) -> list[OutboundPart]:
            return reply_parts(message_xml(text))
        if receiver != number(self.settings) or form['AccountSid'] != account(self.settings):
            raise HTTPException(403,'WhatsApp account mismatch')
        token,text = tracking_token(form['Body'],self.settings.booking_page_url)
        draft = None
        if token:
            await self.workspace.resolve(token)
            async with self.pool.acquire() as c:
                link = await c.fetchrow('''SELECT * FROM public.tracking_share_links WHERE token_sha256=$1
                  AND revoked_at IS NULL AND expires_at>now()''',hashlib.sha256(token.encode()).hexdigest())
            if not link:
                raise HTTPException(404,'This secure tracking link is unavailable.')
            draft = ConsumerDraft(token=token,token_sha256=link['token_sha256'],sender_e164=sender,receiver_e164=receiver,
                tenant_id=link['tenant_id'],shipment_id=link['anchor_shipment_id'])
        else:
            draft = await self.load(sender,receiver)
        if draft is None:
            return reply('For tracking, returns or delivery help, paste the secure tracking link from your merchant, or send Track link followed by its token.')
        link = await self.scope(draft)
        if form.get('NumMedia')!='0':
            return reply('Please describe the issue in text. Send evidence through the retailer’s secure support channel.')
        if text.strip().lower() in {'cancel','start over'}:
            draft.pending_action=None
            await self.save(draft,link)
            return reply('Pending request cleared. Your secure tracking session remains active for its original 15-minute period.')
        choose = re.fullmatch(r'(?:use|select) parcel ([1-9][0-9]?)',text.strip(),re.I)
        if choose:
            index=int(choose[1])-1
            if index>=len(link['shipment_ids']):
                return reply('Choose a parcel number listed for your secure link.')
            draft.shipment_id=link['shipment_ids'][index]
            draft.pending_action=None
        await self.save(draft,link)
        intent = cx_intent(text)
        if draft.pending_action in {'COMPLAINT','SERVICE_REQUEST'}:
            if len(text.strip())<10:
                return reply('Please describe what happened in at least ten characters. You can say damaged, missing/delayed, address change or billing/other.')
            kind=draft.pending_action
            category=(intent.issue_category if intent else draft.pending_category) or 'BILLING_OTHER'
            ticket=await self.case(draft,identity,kind,category,text.strip()[:1000])
            draft.pending_action=None
            draft.pending_category=None
            await self.save(draft,link)
            return reply(f'Retailer support case {ticket} is recorded. Alerts follow the retailer’s configured support channel. No delivery change or refund has been made.')
        if re.search(r'\breturn\b',text,re.I) and not intent:
            if text.strip().lower()=='confirm return' and draft.pending_action=='RETURN_REQUEST':
                draft.pending_action=None
                await self.save(draft,link)
                return await self.return_parcel(draft,identity)
            draft.pending_action='RETURN_REQUEST'
            await self.save(draft,link)
            return reply('To request a return of the selected parcel, confirm you are its recipient and will use the original parcel contents, packed weight and dimensions. Reply Confirm return. Changed packaging or international returns need retailer review. No label has been bought.')
        if intent:
            if intent.intent=='REFUND_INQUIRY':
                return reply(await self.refund(draft,identity))
            summary=(intent.description_notes or '').strip()
            if len(summary)<10:
                draft.pending_action=intent.intent
                draft.pending_category=intent.issue_category
                await self.save(draft,link)
                return reply('Describe what happened in at least 10 characters, including damaged, delayed, address change or billing issue.')
            ticket=await self.case(draft,identity,intent.intent,intent.issue_category or 'BILLING_OTHER',summary)
            return reply(f'Your retailer support case is {ticket}. Alerts follow the retailer’s configured support channel. No delivery change or refund has been made.')
        public=await self.workspace.resolve(draft.token)
        lines=[]
        for index,item in enumerate(public['shipments'],1):
            event=item.get('latest_event') or {}
            lines.append(f"Parcel {index}: {item['order_reference']} — {item['status'].replace('_',' ').lower()}. Last recorded scan: {event.get('occurred_at') or 'not available'}. ETA: {item.get('estimated_delivery_at') or 'not supplied by carrier'}.")
        return reply('\n'.join(lines)+'\nFor multiple parcels, reply Use parcel N. You can request a return, describe a delivery complaint, or ask about a refund. Status reflects the latest received carrier data.')

    async def refund(self, draft: ConsumerDraft, identity: UUID) -> str:
        await self.scope(draft)
        async with self.pool.acquire() as c:
            rows=await c.fetch('''SELECT s.status::text AS status,s.last_tracking_event_at,
              (SELECT max(e.occurred_at) FROM public.tracking_events e WHERE e.tenant_id=s.tenant_id
                AND e.shipment_id=s.id AND e.status='DELIVERED') AS delivered_at
              FROM public.shipments s WHERE s.tenant_id=$1 AND s.return_of_shipment_id=$2
              ORDER BY s.created_at DESC LIMIT 2''',draft.tenant_id,draft.shipment_id)
        ticket=await self.case(draft,identity,'REFUND_INQUIRY','BILLING_OTHER','Customer requested a product refund update; no refund has been authorized or confirmed.')
        if len(rows)==1:
            row=rows[0]
            status=f"Return parcel: {row['status'].replace('_',' ').lower()}."
            if row['status']=='DELIVERED' and row['delivered_at']:
                status+=f" Carrier-reported return delivery: {row['delivered_at'].isoformat()}. This does not confirm merchant inspection or a product refund."
        else:
            status='No unique return parcel is recorded for this shipment.'
        return status+f' Your retailer has a refund inquiry case {ticket}. Product refund timing must be confirmed by the retailer.'

    async def return_parcel(self, draft: ConsumerDraft, identity: UUID) -> list[OutboundPart]:
        from backend.whatsapp_queue import reply_parts
        from backend.agents.conversational_gateway import message_xml
        from backend.consumer_returns import execute_return
        ticket=await self.case(draft,identity,'RETURN_REQUEST','BILLING_OTHER','Consumer confirmed return request using the original parcel contents, weight and dimensions.')
        return await execute_return(self,draft,identity,ticket,reply_parts,message_xml)


def build_router(authenticate) -> APIRouter:
    router=APIRouter(prefix='/api/v1/whatsapp',tags=['Consumer return policy'])

    async def owner(c: Connection, context: TenantContext) -> None:
        if getattr(context,'assistance_session_id',None):
            raise HTTPException(403,'Use your own merchant workspace to authorize consumer return spending')
        active=await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.users u JOIN public.tenants t USING(tenant_id)
          WHERE u.tenant_id=$1 AND u.auth_user_id=$2 AND u.is_active AND u.role IN ('OWNER','ADMIN')
          AND t.workspace_status='ACTIVE')''',context.tenant_id,context.user_id)
        if not active:
            raise HTTPException(403,'An active merchant owner or admin must authorize this policy')

    @router.get('/consumer-return-policy')
    async def get_policy(request:Request,context=Depends(authenticate)):
        if not request.app.state.settings.whatsapp_consumer_cx_enabled:
            raise HTTPException(503,'Apply migration 053 and enable WHATSAPP_CONSUMER_CX_ENABLED on web and worker first')
        async with request.app.state.tracking_workspace.pool.acquire() as c:
            await owner(c,context)
            row=await c.fetchrow('SELECT * FROM public.whatsapp_consumer_return_policies WHERE tenant_id=$1',context.tenant_id)
        return dict(row) if row else ConsumerReturnPolicy().model_dump(mode='json')

    @router.put('/consumer-return-policy')
    async def put_policy(body:ConsumerReturnPolicy,request:Request,context=Depends(authenticate)):
        if not request.app.state.settings.whatsapp_consumer_cx_enabled:
            raise HTTPException(503,'Apply migration 053 and enable WHATSAPP_CONSUMER_CX_ENABLED on web and worker first')
        async with request.app.state.tracking_workspace.pool.acquire() as c:
            async with c.transaction():
                await owner(c,context)
                row=await c.fetchrow('''INSERT INTO public.whatsapp_consumer_return_policies
                  (tenant_id,enabled,authorized_by,window_days,charge_bearer,maximum_price_gbp)
                  VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(tenant_id) DO UPDATE SET enabled=excluded.enabled,
                  authorized_by=excluded.authorized_by,window_days=excluded.window_days,charge_bearer=excluded.charge_bearer,
                  maximum_price_gbp=excluded.maximum_price_gbp,version=whatsapp_consumer_return_policies.version+1,updated_at=now() RETURNING *''',
                  context.tenant_id,body.enabled,context.user_id,body.window_days,body.charge_bearer,body.maximum_price_gbp)
        return dict(row)
    return router
