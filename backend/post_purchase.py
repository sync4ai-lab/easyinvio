"""Scoped public tracking, recipient verification and merchant presentation settings."""
from __future__ import annotations
import hashlib
import base64
import hmac
import ipaddress
import json
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from fastapi.responses import HTMLResponse
from html import escape
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from backend.paf_lookup import uk_postcode
from backend.tracking_input import parse_tracking_input, trusted_tracking_origins
from backend.tracking_workspace import obj, shipment_projection, CustomerRequest

Category=Literal['IN_TRANSIT','OUT_FOR_DELIVERY','AVAILABLE_FOR_PICKUP','DELIVERED','EXCEPTION']
PUBLIC_STATES={'DRAFT','QUOTED','BOOKED','MANIFESTED','DISPATCHED','LABEL_CREATED','IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','CANCELLED','RETURNED','PENDING','COLLECTED','FAILED','PRE_TRANSIT','AVAILABLE_FOR_PICKUP','RETURNED_TO_SENDER','CUSTOMS_PROCESSING','DELIVERY_ATTEMPTED','UNKNOWN'}

class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,str_strip_whitespace=True)

def public_https(value: str | None) -> str | None:
    if not value:return None
    if any(ord(c)<33 for c in value) or '\\' in value:raise ValueError('Use a public HTTPS URL')
    url=urlsplit(value)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.port not in {None,443}:raise ValueError('Use a public HTTPS URL')
    if url.hostname=='localhost' or '.' not in url.hostname or url.hostname.endswith(('.local','.internal')):raise ValueError('Use a public HTTPS hostname')
    try:ipaddress.ip_address(url.hostname)
    except ValueError:
        host=url.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        if len(host)>253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in host.split('.')):raise ValueError('Use a public HTTPS hostname')
        return url._replace(scheme='https',netloc=host+(':443' if url.port==443 else '')).geturl()
    raise ValueError('IP-address URLs are not supported')

class BuyerPolicy(StrictModel):
    email: bool=False
    whatsapp: bool=False
    categories: list[Category]=Field(default_factory=lambda:['IN_TRANSIT','OUT_FOR_DELIVERY','AVAILABLE_FOR_PICKUP','DELIVERED','EXCEPTION'],max_length=5)

class StorePresentation(StrictModel):
    brand_display_name: str | None=Field(default=None,min_length=1,max_length=100)
    brand_logo_url: str | None=Field(default=None,max_length=2048)
    brand_accent_hex: str | None=Field(default=None,pattern=r'^#[0-9a-fA-F]{6}$')
    support_url: str | None=Field(default=None,max_length=2048)
    buyer_notification_policy: BuyerPolicy=Field(default_factory=BuyerPolicy)
    @field_validator('brand_display_name')
    @classmethod
    def readable_name(cls,value: str | None) -> str | None:
        if value and any(ord(c)<32 for c in value):raise ValueError('Use a readable store name')
        return value
    @field_validator('brand_logo_url','support_url')
    @classmethod
    def urls(cls,value: str | None) -> str | None:return public_https(value)

class TrackingLookup(StrictModel):
    text: str=Field(min_length=8,max_length=2048)

class RecipientVerification(StrictModel):
    tracking_number: str | None=Field(default=None,min_length=8,max_length=100)
    delivery_postcode: str | None=Field(default=None,min_length=2,max_length=20)
    token: str | None=Field(default=None,pattern=r'^[A-Za-z0-9_-]{40,100}$')
    @model_validator(mode='after')
    def scope(self) -> RecipientVerification:
        if self.token:
            if self.tracking_number or self.delivery_postcode:raise ValueError('Use a token or a tracking number and postcode')
        elif not self.tracking_number or not self.delivery_postcode:raise ValueError('Supply tracking number and delivery postcode')
        return self

class RecipientPermission(StrictModel):
    email: bool=False
    whatsapp: bool=False
    email_permission_confirmed: bool=False
    whatsapp_permission_confirmed: bool=False
    @model_validator(mode='after')
    def consent(self) -> RecipientPermission:
        if self.email and not self.email_permission_confirmed or self.whatsapp and not self.whatsapp_permission_confirmed:raise ValueError('Confirm recipient permission for each enabled channel')
        return self

class PublicPermission(RecipientPermission):
    token: str=Field(pattern=r'^[A-Za-z0-9_-]{40,100}$')

def normalize_postcode(value: str,country: str) -> str:
    if country.upper() in {'GB','UK'}:return uk_postcode(value)
    normalized=re.sub(r'[\s-]+','',value).upper()
    if not re.fullmatch(r'[A-Z0-9]{2,16}',normalized):raise ValueError('Invalid postcode')
    return normalized

def postcode_matches(row: Any,value: str) -> bool:
    address=obj(row['recipient_address']);country=address.get('country_code') or row.get('destination_country') or ''
    try:
        expected=normalize_postcode(str(address.get('postal_code') or ''),country)
        actual=normalize_postcode(value,country)
    except ValueError:return False
    return hmac.compare_digest(expected,actual)

def contact_digest(row: Any) -> str:
    address=obj(row['recipient_address'])
    return hashlib.sha256(json.dumps([str(address.get('email') or '').strip().casefold(),str(address.get('phone') or '').strip()],separators=(',',':')).encode()).hexdigest()

def branding(row: Any) -> dict[str,Any]:
    def url(name: str) -> str | None:
        try:return public_https(row.get(name))
        except ValueError:return None
    accent=row.get('brand_accent_hex') or ''
    name=row.get('brand_display_name') or row.get('display_name') or 'EasyInvio'
    return {'display_name':str(name)[:100],'logo_url':url('brand_logo_url'),'accent_hex':accent if re.fullmatch(r'#[0-9a-fA-F]{6}',accent) else '#059669','support_url':url('support_url')}

async def require_schema(connection: Any) -> None:
    if not await connection.fetchval("SELECT to_regclass('public.tracking_recipient_access') IS NOT NULL"):
        raise HTTPException(503,'Apply migration 058 to enable the post-purchase experience')

async def rate_limit(connection: Any,subject: str,limit: int,seconds: int) -> None:
    digest=hashlib.sha256(subject.encode()).hexdigest();bucket=int(time.time())//seconds
    admitted=await connection.fetchval('''INSERT INTO public.tracking_public_limits(subject_sha256,bucket,requests,expires_at)
        VALUES($1,$2::bigint,1,to_timestamp((($2::bigint+1)*$4::bigint)::double precision)) ON CONFLICT(subject_sha256,bucket) DO UPDATE
        SET requests=tracking_public_limits.requests+1 WHERE tracking_public_limits.requests<$3 RETURNING requests''',digest,bucket,limit,seconds)
    if admitted is None:raise HTTPException(429,'Too many tracking attempts. Please try later.',headers={'Retry-After':str(seconds)})
    await connection.execute('DELETE FROM public.tracking_public_limits WHERE ctid IN (SELECT ctid FROM public.tracking_public_limits WHERE expires_at<now() LIMIT 100)')

ROW_SQL='''SELECT s.*,s.status::text AS stored_status,t.public_status_lookup_enabled,t.workspace_status,
 st.display_name,st.brand_display_name,st.brand_logo_url,st.brand_accent_hex,st.support_url,st.store_slug,
 st.return_policy,st.return_policy_authorized_by,st.buyer_notification_policy
 FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
 LEFT JOIN public.ecommerce_stores st ON st.tenant_id=s.tenant_id AND st.id=s.ecommerce_store_id '''

async def find_reference(connection: Any,reference: str) -> Any:
    try:identifier=UUID(reference)
    except ValueError:identifier=None
    rows=await connection.fetch(ROW_SQL+''' WHERE t.workspace_status='ACTIVE' AND
        (s.tracking_number=$1 OR s.id=$2 OR s.logistics_metadata->'automation_label'->'package_labels'
        @> jsonb_build_array(jsonb_build_object('tracking_number',$1::text))) LIMIT 2''',reference,identifier)
    # Count collisions BEFORE applying merchant publication preference.
    if len(rows)!=1 or not rows[0]['public_status_lookup_enabled']:raise HTTPException(404,'No uniquely published parcel is available. Check your reference or use your retailer’s secure link.')
    return dict(rows[0])

async def public_projection(connection: Any,row: Any,reference: str) -> dict[str,Any]:
    events=await connection.fetch('''SELECT * FROM public.tracking_events WHERE tenant_id=$1 AND shipment_id=$2
       AND response->>'applied'='true' ORDER BY occurred_at DESC,id DESC LIMIT 100''',row['tenant_id'],row['id'])
    # Restrict a multipiece reference to its own scans. Aggregate DELIVERED remains authoritative.
    events=[event for event in events if not obj(obj(event.get('response')).get('tracking_detail')).get('tracking_number') or obj(obj(event.get('response')).get('tracking_detail')).get('tracking_number')==reference or reference==str(row['id'])]
    item=shipment_projection(row,events)
    timeline=[]
    for event in item['timeline']:
        if not event['applied']:continue
        original=next((e for e in events if str(e['id'])==event['id']),{})
        city=obj(obj(original.get('response')).get('tracking_detail')).get('hub_city')
        city=city if isinstance(city,str) and re.fullmatch(r"[^\W\d_][^\d\n\r<>@/]{0,79}",city) else None
        timeline.append({'status':event['status'] if event['status'] in PUBLIC_STATES else 'PENDING','occurred_at':event['occurred_at'],'location':city})
    return {'carrier':item['carrier'],'tracking_number':reference,'status':item['status'] if item['status'] in PUBLIC_STATES else 'PENDING',
        'timeline':timeline,'estimated_delivery_at':item['estimated_delivery_at'],'data_state':item['data_state']}

class PostPurchaseService:
    def __init__(self,workspace: Any):self.workspace=workspace;self.pool=workspace.pool;self.settings=workspace.settings

    async def lookup(self,text: str,client: str) -> dict[str,Any]:
        try:parsed=parse_tracking_input(text,trusted_tracking_origins(self.settings))
        except ValueError as exc:raise HTTPException(422,str(exc)) from None
        async with self.pool.acquire() as c:
            await require_schema(c);await rate_limit(c,'lookup:'+client,30,60)
        if parsed.kind=='CAPABILITY':return await self.resolve(parsed.value)
        async with self.pool.acquire() as c:
            row=await find_reference(c,parsed.value);item=await public_projection(c,row,parsed.value)
        return {'access':'PUBLIC','shipments':[item],'branding':branding(row),'message':item['status'].replace('_',' ').title()}

    async def access_row(self,connection: Any,token: str) -> Any:
        return await connection.fetchrow('''SELECT a.*,l.shipment_ids FROM public.tracking_recipient_access a
            JOIN public.tracking_share_links l ON l.tenant_id=a.tenant_id AND l.id=a.share_link_id
            LEFT JOIN public.tracking_share_links source ON source.id=a.source_share_link_id
            WHERE a.token_sha256=$1 AND a.expires_at>now() AND l.expires_at>now() AND l.revoked_at IS NULL
            AND (a.source_share_link_id IS NULL OR source.revoked_at IS NULL AND source.expires_at>now())''',hashlib.sha256(token.encode()).hexdigest())

    async def resolve(self,token: str) -> dict[str,Any]:
        async with self.pool.acquire() as c:
            installed=await c.fetchval("SELECT to_regclass('public.tracking_recipient_access') IS NOT NULL")
        if not installed:return await self.workspace.resolve(token)
        async with self.pool.acquire() as c:
            access=await self.access_row(c,token)
            was_access=await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.tracking_recipient_access WHERE token_sha256=$1)',hashlib.sha256(token.encode()).hexdigest())
            if was_access and not access:raise HTTPException(404,'Verified tracking access expired or was revoked')
            if access:
                row=await c.fetchrow(ROW_SQL+' WHERE s.tenant_id=$1 AND s.id=$2',access['tenant_id'],access['shipment_id'])
                if not row or row['workspace_status']!='ACTIVE':raise HTTPException(404,'Tracking is unavailable')
                item=await public_projection(c,dict(row),row['tracking_number'] or str(row['id']))
                address=obj(row['recipient_address'])
                item['delivery_address']={k:address[k] for k in ('name','company','line1','line2','city','region','postal_code','country_code') if address.get(k)}
                item['proof_of_delivery_url']=None
                if row['stored_status']=='DELIVERED':
                    try:item['proof_of_delivery_url']=public_https(row['proof_of_delivery_url'])
                    except ValueError:pass
                return_url=None
                if row.get('store_slug') and row['stored_status']=='DELIVERED':
                    from backend.store_returns_portal import check_eligibility,policy_for
                    try:
                        store=await c.fetchrow('''SELECT st.* FROM public.ecommerce_stores st
                            JOIN public.users u ON u.tenant_id=st.tenant_id AND u.auth_user_id=st.return_policy_authorized_by
                            JOIN public.tenants t ON t.tenant_id=st.tenant_id
                            WHERE st.tenant_id=$1 AND st.id=$2 AND st.is_active AND u.is_active AND u.role IN ('OWNER','ADMIN')
                            AND t.workspace_status='ACTIVE' AND t.billing_status='ACTIVE' ''',row['tenant_id'],row['ecommerce_store_id'])
                        if not store or (row.get('parcel_count') or 1)>1:raise HTTPException(409,'Merchant review required')
                        check_eligibility(row,policy_for(store));return_url='/returns/'+row['store_slug']
                    except (HTTPException,ValueError):pass
                item['return_url']=return_url
                preference=await c.fetchrow('SELECT email,whatsapp,contact_sha256 FROM public.shipment_recipient_preferences WHERE tenant_id=$1 AND shipment_id=$2',row['tenant_id'],row['id'])
                permission={'email':False,'whatsapp':False}
                if preference and preference['contact_sha256']==contact_digest(row):permission={k:preference[k] for k in permission}
                return {'access':'VERIFIED_RECIPIENT','shipments':[item],'branding':branding(row),'expires_at':access['expires_at'].isoformat(),'buyer_notification_policy':obj(row['buyer_notification_policy']),'recipient_preferences':permission}
        try:result=await self.workspace.resolve(token)
        except HTTPException as exc:
            if exc.status_code!=404:raise
            # Long carrier references can resemble opaque tokens. Only a safe,
            # uniquely published reference may be used as the fallback.
            async with self.pool.acquire() as c:
                row=await find_reference(c,token);item=await public_projection(c,row,token)
            return {'access':'PUBLIC','shipments':[item],'branding':branding(row),'message':item['status'].replace('_',' ').title()}

        async with self.pool.acquire() as c:
            link=await c.fetchrow('SELECT tenant_id,anchor_shipment_id FROM public.tracking_share_links WHERE token_sha256=$1 AND revoked_at IS NULL AND expires_at>now()',hashlib.sha256(token.encode()).hexdigest())
            if not link:raise HTTPException(404,'Tracking link expired')
            row=await c.fetchrow(ROW_SQL+' WHERE s.tenant_id=$1 AND s.id=$2',link['tenant_id'],link['anchor_shipment_id'])
        return {**result,'access':'CAPABILITY','branding':branding(row or {})}

    async def verify(self,body: RecipientVerification,client: str) -> dict[str,Any]:
        async with self.pool.acquire() as c:
            await require_schema(c)
            await rate_limit(c,'verify-ip:'+client,15,3600)
            identity=body.token or body.tracking_number or ''
            if not body.token:
                try:identity=str(UUID(identity))
                except ValueError:pass
            await rate_limit(c,'verify-ref:'+identity,10,3600)
            await rate_limit(c,'verify-pair:'+client+':'+identity,5,900)
            async with c.transaction():
                source=None
                if body.token:
                    # Existing capability possession is an alternative verification factor.
                    source=await c.fetchrow('SELECT * FROM public.tracking_share_links WHERE token_sha256=$1 AND revoked_at IS NULL AND expires_at>now() FOR UPDATE',hashlib.sha256(body.token.encode()).hexdigest())
                    if not source:raise HTTPException(404,'Tracking verification failed')
                    # Prevent re-extending a short-lived verified token as a new source.
                    if await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.tracking_recipient_access WHERE token_sha256=$1)',hashlib.sha256(body.token.encode()).hexdigest()):raise HTTPException(409,'Use your original tracking link or verify the delivery postcode again')
                    row=await c.fetchrow(ROW_SQL+' WHERE s.tenant_id=$1 AND s.id=$2',source['tenant_id'],source['anchor_shipment_id'])
                else:
                    try:row=await find_reference(c,body.tracking_number or '')
                    except HTTPException:raise HTTPException(404,'Tracking verification failed') from None
                    if not postcode_matches(row,body.delivery_postcode or ''):raise HTTPException(404,'Tracking verification failed')
                if not row or row['workspace_status']!='ACTIVE':raise HTTPException(404,'Tracking verification failed')
                owner=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND is_active AND role IN ('OWNER','ADMIN') ORDER BY (role='OWNER') DESC,id LIMIT 1",row['tenant_id'])
                if not owner:raise HTTPException(404,'Tracking verification failed')
                token=secrets.token_urlsafe(32);digest=hashlib.sha256(token.encode()).hexdigest()
                link=await c.fetchrow('''INSERT INTO public.tracking_share_links(tenant_id,anchor_shipment_id,shipment_ids,token_sha256,created_by,expires_at)
                    VALUES($1,$2,$3,$4,$5,now()+interval '30 minutes') RETURNING id,expires_at''',row['tenant_id'],row['id'],[row['id']],digest,owner)
                await c.execute('''INSERT INTO public.tracking_recipient_access(token_sha256,tenant_id,shipment_id,share_link_id,source_share_link_id,expires_at)
                    VALUES($1,$2,$3,$4,$5,$6)''',digest,row['tenant_id'],row['id'],link['id'],source['id'] if source else None,link['expires_at'])
        return {'tracking_access_token':token,**await self.resolve(token)}

    async def permission(self,token: str,body: RecipientPermission) -> None:
        async with self.pool.acquire() as c:
            await require_schema(c)
            async with c.transaction():
                access=await self.access_row(c,token)
                if not access:raise HTTPException(404,'Verified tracking access expired')
                row=await c.fetchrow('SELECT recipient_address FROM public.shipments WHERE tenant_id=$1 AND id=$2',access['tenant_id'],access['shipment_id'])
                await save_permission(c,access['tenant_id'],access['shipment_id'],row,body,capability=hashlib.sha256(token.encode()).hexdigest())

async def save_permission(c: Any,tenant: UUID,shipment: UUID,row: Any,body: RecipientPermission,*,actor: UUID | None=None,capability: str | None=None) -> None:
    await c.execute('''INSERT INTO public.shipment_recipient_preferences(tenant_id,shipment_id,email,whatsapp,contact_sha256,authorized_by,capability_sha256)
        VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(tenant_id,shipment_id) DO UPDATE SET email=excluded.email,whatsapp=excluded.whatsapp,
        contact_sha256=excluded.contact_sha256,authorized_by=excluded.authorized_by,capability_sha256=excluded.capability_sha256,updated_at=now()''',tenant,shipment,body.email,body.whatsapp,contact_digest(row),actor,capability)

def merchant_logo_response(approved: str) -> HTMLResponse:
    origin=urlsplit(approved)
    image_origin=origin.scheme+'://'+origin.netloc
    style='html,body{margin:0;background:transparent;width:160px;height:44px;overflow:hidden}body{display:flex;align-items:center;justify-content:flex-start}img{max-width:160px;max-height:44px;object-fit:contain}'
    style_hash=base64.b64encode(hashlib.sha256(style.encode()).digest()).decode('ascii')
    page='<html><head><meta name="referrer" content="no-referrer"><style>'+style+'</style></head><body><img src="'+escape(approved,quote=True)+'" alt="Merchant logo" referrerpolicy="no-referrer"></body></html>'
    return HTMLResponse(page,headers={'Cache-Control':'public, max-age=60','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"default-src 'none'; img-src "+image_origin+"; style-src 'sha256-"+style_hash+"'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'; sandbox"})


def build_router(authenticate: Any) -> APIRouter:
    class StorageRoute(APIRoute):
        def get_route_handler(self):
            original=super().get_route_handler()
            async def handler(request: Request):
                try:return await original(request)
                except asyncpg.PostgresError:raise HTTPException(503,'Tracking storage is temporarily unavailable') from None
            return handler
    router=APIRouter(tags=['Branded post-purchase experience'],route_class=StorageRoute)
    def service(request: Request) -> PostPurchaseService:
        workspace=getattr(request.app.state,'tracking_workspace',None)
        if workspace is None:raise HTTPException(503,'Tracking unavailable')
        return PostPurchaseService(workspace)
    def headers(response: Response) -> None:response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
    @router.get('/api/v1/public/tracking/brand-logo',response_class=HTMLResponse)
    async def logo_frame(request: Request,url: str=Query(min_length=8,max_length=2048)) -> HTMLResponse:
        try:approved=public_https(url)
        except ValueError:raise HTTPException(404,'Logo unavailable') from None
        engine=service(request)
        async with engine.pool.acquire() as c:
            await require_schema(c)
            allowed=await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.ecommerce_stores WHERE is_active AND brand_logo_url=$1)',approved)
        if not allowed:raise HTTPException(404,'Logo unavailable')
        return merchant_logo_response(approved)

    @router.post('/api/v1/public/tracking/status')
    async def status(body: TrackingLookup,request: Request,response: Response) -> dict[str,Any]:
        headers(response);return await service(request).lookup(body.text,request.client.host if request.client else 'unknown')
    @router.post('/api/v1/public/tracking/verify-recipient')
    async def verify(body: RecipientVerification,request: Request,response: Response) -> dict[str,Any]:
        headers(response);return await service(request).verify(body,request.client.host if request.client else 'unknown')
    @router.post('/api/v1/public/tracking/recipient-preferences')
    async def permission(body: PublicPermission,request: Request,response: Response) -> dict[str,str]:
        headers(response);engine=service(request)
        async with engine.pool.acquire() as c:await require_schema(c);await rate_limit(c,'preference:'+body.token,10,3600)
        await engine.permission(body.token,body);return {'status':'SAVED','message':'Preferences saved for future milestones. Merchant policy and configured channels also apply.'}
    @router.get('/api/v1/workspace/stores/{store_id}/post-purchase')
    async def get_settings(store_id: UUID,request: Request,context: Any=Depends(authenticate)) -> dict[str,Any]:
        from backend.store_connections import scoped_store
        await scoped_store(request,context,store_id)
        async with request.app.state.ecommerce.pool.acquire() as c:
            await require_schema(c)
            row=await c.fetchrow('SELECT brand_display_name,brand_logo_url,brand_accent_hex,support_url,buyer_notification_policy FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2',context.tenant_id,store_id)
        value=dict(row);value['buyer_notification_policy']=obj(value['buyer_notification_policy']);return value
    @router.put('/api/v1/workspace/stores/{store_id}/post-purchase')
    async def put_settings(store_id: UUID,body: StorePresentation,request: Request,context: Any=Depends(authenticate)) -> dict[str,str]:
        from backend.store_connections import scoped_store
        if context.role not in {'OWNER','ADMIN'}:raise HTTPException(403,'Merchant administrator required')
        await scoped_store(request,context,store_id)
        async with request.app.state.ecommerce.pool.acquire() as c:
            await require_schema(c)
            await c.execute('''UPDATE public.ecommerce_stores SET brand_display_name=$3,brand_logo_url=$4,brand_accent_hex=$5,support_url=$6,buyer_notification_policy=$7::jsonb
               WHERE tenant_id=$1 AND id=$2''',context.tenant_id,store_id,body.brand_display_name,body.brand_logo_url,body.brand_accent_hex,body.support_url,body.buyer_notification_policy.model_dump_json())
        return {'status':'SAVED'}
    @router.put('/api/v1/shipping/{shipment_id}/recipient-notifications')
    async def merchant_permission(shipment_id: UUID,body: RecipientPermission,request: Request,context: Any=Depends(authenticate)) -> dict[str,str]:
        if context.role not in {'OWNER','ADMIN','DISPATCHER'}:raise HTTPException(403,'Dispatch permission required')
        async with request.app.state.finance.pool.acquire() as c:
            await require_schema(c)
            row=await c.fetchrow('SELECT recipient_address FROM public.shipments WHERE tenant_id=$1 AND id=$2',context.tenant_id,shipment_id)
            if not row:raise HTTPException(404,'Shipment unavailable')
            await save_permission(c,context.tenant_id,shipment_id,row,body,actor=context.user_id)
        return {'status':'SAVED'}
    return router
