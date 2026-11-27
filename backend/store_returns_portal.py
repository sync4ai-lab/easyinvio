"""Store-scoped shopper verification and bounded merchant-authorized returns."""
from __future__ import annotations
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from backend.custom_stores import bounded_body
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.custom_stores import throttle
from backend.dispatch_workspace import decoded

SLUG=r'^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$'
PRIVATE_HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}

class ReturnPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    enabled: bool=Field(default=False,strict=True)
    return_window_days: int=Field(default=30,strict=True,ge=1,le=90)
    charge_bearer: Literal['RETAILER_PAY','CUSTOMER_PAY']='RETAILER_PAY'
    maximum_price: Decimal=Field(default=Decimal('10.00'),gt=0,le=100,decimal_places=2)
    currency: Literal['GBP']='GBP'
    allowed_countries: list[str]=Field(default_factory=lambda:['GB'],min_length=1,max_length=10)
    paperless_requested: bool=Field(default=True,strict=True)
    @field_validator('maximum_price',mode='before')
    @classmethod
    def exact_amount(cls,value: Any) -> Decimal:
        from backend.ai_engine import strict_decimal
        return strict_decimal(value)
    @field_validator('allowed_countries')
    @classmethod
    def countries(cls,values: list[str]) -> list[str]:
        from backend.ai_engine import country_code
        return sorted(set(country_code(v) for v in values))

class PortalSettings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    store_slug: str=Field(pattern=SLUG)
    return_policy: ReturnPolicy

class ShopperVerification(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    order_reference: str=Field(min_length=1,max_length=200)
    verification_value: str=Field(min_length=3,max_length=254)

class ShopperConfirmation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token: str=Field(min_length=32,max_length=100)
    original_packaging_confirmed: bool=Field(default=False,strict=True)
    notify_email: bool=Field(default=False,strict=True)
    notify_whatsapp: bool=Field(default=False,strict=True)

def verification_matches(shipment: Any, value: str) -> bool:
    address=decoded(shipment['recipient_address']) or {}
    metadata=decoded(shipment['logistics_metadata']) or {}
    email=address.get('email') or metadata.get('ecommerce',{}).get('shipping_address',{}).get('email') or ''
    postcode=address.get('postal_code') or ''
    norm=lambda s: ''.join(s.upper().split())
    return bool((postcode and hmac.compare_digest(norm(postcode),norm(value))) or
                (email and hmac.compare_digest(email.strip().lower().encode(),value.strip().lower().encode())))

def check_eligibility(shipment: Any, policy: ReturnPolicy) -> None:
    delivered=shipment.get('delivered_at')
    now=datetime.now(timezone.utc)
    if not policy.enabled or shipment['status']!='DELIVERED' or not delivered or not now-timedelta(days=policy.return_window_days)<=delivered<=now:
        raise HTTPException(409,'This order needs retailer review under the return policy')
    original=(decoded(shipment['logistics_metadata']) or {}).get('automation_order') or {}
    origin=original.get('origin',{}).get('country_code'); destination=original.get('destination',{}).get('country_code')
    if (not original or original.get('is_return') or len(original.get('packages') or [])>1
            or origin!=destination or origin not in policy.allowed_countries or shipment['currency']!=policy.currency):
        raise HTTPException(409,'Changed packaging, grouped or international returns need retailer review')

async def get_store(pool: Any, slug: str) -> Any:
    async with pool.acquire() as c:
        row=await c.fetchrow('''SELECT s.*,u.role FROM public.ecommerce_stores s
            JOIN public.users u ON u.tenant_id=s.tenant_id AND u.auth_user_id=s.return_policy_authorized_by
            JOIN public.tenants t ON t.tenant_id=s.tenant_id WHERE s.store_slug=$1 AND s.is_active
              AND u.is_active AND u.role IN ('OWNER','ADMIN') AND t.workspace_status='ACTIVE'
              AND t.billing_status='ACTIVE' ''',slug)
    if not row: raise HTTPException(404,'Return portal unavailable; contact your retailer')
    return row

def policy_for(store: Any) -> ReturnPolicy:
    return ReturnPolicy.model_validate(decoded(store['return_policy']))

def policy_digest(store: Any) -> str:
    return hashlib.sha256(json.dumps(decoded(store['return_policy']),sort_keys=True,separators=(',',':')).encode()).hexdigest()

async def session_scope(pool: Any, slug: str, token: str) -> tuple[Any,Any]:
    store=await get_store(pool,slug)
    async with pool.acquire() as c:
        session=await c.fetchrow('''SELECT * FROM public.store_return_sessions WHERE store_id=$1 AND tenant_id=$2
            AND token_sha256=$3 AND expires_at>now()''',store['id'],store['tenant_id'],hashlib.sha256(token.encode()).hexdigest())
    if not session: raise HTTPException(401,'Return session expired; verify the order again')
    return store,session

def actor_for(store: Any) -> Any:
    return SimpleNamespace(tenant_id=store['tenant_id'],user_id=store['return_policy_authorized_by'],
        role=store['role'],bearer_token='',assistance_session_id=None)

async def public_result(request: Request, store: Any, session: Any) -> dict[str,Any]:
    from backend.return_review import ReturnReviewService
    from backend.return_delivery import signed_document
    try:
        result=await ReturnReviewService(request.app.state.partner_lifecycle).status(actor_for(store),session['request_id'])
    except HTTPException as error:
        if error.status_code!=404: raise
        return {'status':'REVIEW_REQUIRED','message':'Contact your retailer to review the recorded return request.'}
    response={'status':result['status'],'request_id':str(session['request_id'])}
    if result.get('checkout_url'):
        from backend.payment_gateway import safe_checkout_url
        response['checkout_url']=safe_checkout_url(result['checkout_url'])
    if result['status']=='BOOKED' and result.get('label_path'):
        response['label_url']=signed_document(request.app.state.partner_lifecycle,store['tenant_id'],session['request_id'])
        if result.get('qr_path'): response['qr_url']=signed_document(request.app.state.partner_lifecycle,store['tenant_id'],session['request_id'],'return-qr')
    return response

class SmallJsonRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def limited(request: Request):
            if request.method in {'POST','PUT'}:
                request._body=await bounded_body(request,16384)
            return await handler(request)
        return limited

def build_router(authenticate: Any) -> APIRouter:
    def private_response(response: Response) -> None:
        response.headers.update(PRIVATE_HEADERS)
    router=APIRouter(tags=['Store returns portal'],dependencies=[Depends(private_response)],route_class=SmallJsonRoute)
    @router.put('/api/v1/workspace/stores/{store_id}/returns-portal')
    async def configure(store_id: UUID, body: PortalSettings, request: Request, actor: Any=Depends(authenticate)) -> dict[str,Any]:
        if actor.role not in {'OWNER','ADMIN'} or getattr(actor,'assistance_session_id',None):
            raise HTTPException(403,'A merchant owner/admin must authorize this return spending policy')
        from backend.entitlements import guard_feature
        await guard_feature(request.app.state.ecommerce.pool,request.app.state.settings,actor.tenant_id,'paperless_qr_returns')
        async with request.app.state.ecommerce.pool.acquire() as c:
            async with c.transaction():
                conflict=await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.ecommerce_stores WHERE store_slug=$1 AND id<>$2)',body.store_slug,store_id)
                if conflict: raise HTTPException(409,'This portal address is already in use')
                row=await c.fetchrow('''UPDATE public.ecommerce_stores SET store_slug=$3,return_policy=$4::jsonb,
                    return_policy_authorized_by=$5 WHERE tenant_id=$1 AND id=$2 RETURNING id''',
                    actor.tenant_id,store_id,body.store_slug,body.return_policy.model_dump_json(),actor.user_id)
                if not row: raise HTTPException(404,'Store not found in workspace')
        return {'store_slug':body.store_slug,'portal_path':'/returns/'+body.store_slug,'return_policy':body.return_policy.model_dump(mode='json')}

    @router.get('/api/v1/workspace/stores/{store_id}/returns-portal')
    async def settings(store_id: UUID, request: Request, actor: Any=Depends(authenticate)) -> dict[str,Any]:
        if actor.role not in {'OWNER','ADMIN'}: raise HTTPException(403,'Merchant administrator required')
        async with request.app.state.ecommerce.pool.acquire() as c:
            row=await c.fetchrow('SELECT store_slug,return_policy FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2',actor.tenant_id,store_id)
        if not row: raise HTTPException(404,'Store not found')
        return {'store_slug':row['store_slug'],'return_policy':decoded(row['return_policy'])}

    @router.get('/returns/{store_slug}',include_in_schema=False)
    async def page(store_slug: str) -> FileResponse:
        return FileResponse(Path(__file__).resolve().parents[1]/'frontend/landing/returns-portal.html',headers={**PRIVATE_HEADERS,
            'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"})

    @router.get('/api/v1/public/store-returns/{store_slug}')
    async def brand(store_slug: str, request: Request) -> dict[str,Any]:
        store=await get_store(request.app.state.ecommerce.pool,store_slug); policy=policy_for(store)
        if not policy.enabled: raise HTTPException(404,'Return portal unavailable; contact your retailer')
        return {'store_name':store['display_name'],'return_window_days':policy.return_window_days,
                'charge_bearer':policy.charge_bearer,'notice':'Full original parcel returns. Different packaging or international returns require retailer review.'}

    @router.post('/api/v1/public/store-returns/{store_slug}/verify')
    async def verify(store_slug: str, body: ShopperVerification, request: Request) -> dict[str,Any]:
        pool=request.app.state.ecommerce.pool; store=await get_store(pool,store_slug)
        peer=request.client.host if request.client else 'unknown'
        await throttle(pool,store['id'],'portal-verify:'+peer,8)
        await throttle(pool,store['id'],'portal-verify-total',60)
        async with pool.acquire() as c:
            rows=await c.fetch('''SELECT s.*,(SELECT max(e.occurred_at) FROM public.tracking_events e
                WHERE e.tenant_id=s.tenant_id AND e.shipment_id=s.id AND e.status='DELIVERED') AS delivered_at
                FROM public.shipments s WHERE s.tenant_id=$1 AND s.ecommerce_store_id=$2
                AND (s.store_order_id=$3 OR s.customer_reference=$3) AND s.return_of_shipment_id IS NULL LIMIT 2''',
                store['tenant_id'],store['id'],body.order_reference)
        if len(rows)!=1 or not verification_matches(rows[0],body.verification_value):
            raise HTTPException(404,'Unable to verify this order. Check the reference and delivery postcode/email, or contact the retailer.')
        shipment=rows[0]; policy=policy_for(store); check_eligibility(shipment,policy)
        token=secrets.token_urlsafe(32); request_id=uuid5(NAMESPACE_URL,f"easyinvio-store-return:{store['id']}:{shipment['id']}")
        async with pool.acquire() as c:
            await c.execute('DELETE FROM public.store_return_sessions WHERE store_id=$1 AND expires_at<now()',store['id'])
            await c.execute('''INSERT INTO public.store_return_sessions(id,tenant_id,store_id,shipment_id,request_id,token_sha256,policy_sha256)
                VALUES($1,$2,$3,$4,$5,$6,$7)''',uuid4(),store['tenant_id'],store['id'],shipment['id'],request_id,hashlib.sha256(token.encode()).hexdigest(),policy_digest(store))
        order=(decoded(shipment['logistics_metadata']) or {}).get('automation_order') or {}
        return {'token':token,'request_id':str(request_id),'items':[{'description':v['description'],'quantity':v['quantity']} for v in order.get('items',[])],
                'charge_bearer':policy.charge_bearer,'notice':'Confirm that all original goods, packed weight and dimensions are unchanged. No label has been purchased.'}

    @router.post('/api/v1/public/store-returns/{store_slug}/confirm')
    async def confirm(store_slug: str, body: ShopperConfirmation, request: Request) -> dict[str,Any]:
        from backend.return_review import ReturnReviewService,ReviewRequest,ReturnEdits,ReturnDelivery,SelectReturn,ordered_rates
        pool=request.app.state.ecommerce.pool; store,session=await session_scope(pool,store_slug,body.token)
        await throttle(pool,store['id'],'portal-confirm:'+str(session['shipment_id']),10)
        from backend.entitlements import guard_feature
        await guard_feature(pool,getattr(request.app.state,'settings',None),store['tenant_id'],'paperless_qr_returns')
        if not body.original_packaging_confirmed: raise HTTPException(422,'Changed goods or packaging require retailer review')
        if session['state']!='VERIFIED': return await public_result(request,store,session)
        policy=policy_for(store)
        if not policy.enabled or session['policy_sha256']!=policy_digest(store): raise HTTPException(409,'Return policy changed; contact your retailer')
        async with pool.acquire() as c:
            existing=await c.fetchval('SELECT id FROM public.return_review_sessions WHERE tenant_id=$1 AND id=$2',store['tenant_id'],session['request_id'])
            shipment=await c.fetchrow('''SELECT s.*,(SELECT max(e.occurred_at) FROM public.tracking_events e
                WHERE e.tenant_id=s.tenant_id AND e.shipment_id=s.id AND e.status='DELIVERED') AS delivered_at
                FROM public.shipments s WHERE s.tenant_id=$1 AND s.ecommerce_store_id=$2 AND s.id=$3''',store['tenant_id'],store['id'],session['shipment_id'])
            if not shipment: raise HTTPException(404,'Original store shipment unavailable')
            check_eligibility(shipment,policy)
        if existing: return await public_result(request,store,session)
        async with pool.acquire() as c:
            claimed=await c.fetchval("UPDATE public.store_return_sessions SET state='PROCESSING' WHERE id=$1 AND state='VERIFIED' RETURNING id",session['id'])
        if not claimed: return {'status':'PROCESSING','request_id':str(session['request_id'])}
        review=ReturnReviewService(request.app.state.partner_lifecycle); actor=actor_for(store)
        try:
            facts=await review.context(actor,session['shipment_id'])
            if (facts['destination']['country_code'] not in policy.allowed_countries or facts['destination']['country_code']!=(decoded(shipment['logistics_metadata']) or {}).get('automation_order',{}).get('origin',{}).get('country_code')): raise HTTPException(409,'Return warehouse requires retailer review')
            prepared=await review.prepare(actor,ReviewRequest(request_id=session['request_id'],shipment_id=session['shipment_id'],
                charge_bearer=policy.charge_bearer,paperless_requested=policy.paperless_requested,edits=ReturnEdits.model_validate(facts['edits']),
                delivery=ReturnDelivery(email=body.notify_email,whatsapp=body.notify_whatsapp,customer_permission_confirmed=body.notify_email or body.notify_whatsapp)))
            rates=ordered_rates(prepared.get('rates',[]))
            if prepared.get('partial') or not rates or rates[0]['currency']!=policy.currency or Decimal(str(rates[0]['client_price_ex_tax']))>policy.maximum_price:
                raise HTTPException(409,'Return price needs retailer review or exceeds the authorized postage cap; no label purchased')
            current=await get_store(pool,store_slug)
            if policy_digest(current)!=session['policy_sha256']: raise HTTPException(409,'Return policy changed before purchase')
            await review.select(actor,session['request_id'],SelectReturn(offer_id=UUID(rates[0]['offer_id'])),expected_store_policy=(store['id'],session['policy_sha256']))
            async with pool.acquire() as c: await c.execute("UPDATE public.store_return_sessions SET state='SUBMITTED' WHERE id=$1",session['id'])
            return await public_result(request,store,session)
        except Exception:
            async with pool.acquire() as c: await c.execute("UPDATE public.store_return_sessions SET state='REVIEW_REQUIRED' WHERE id=$1",session['id'])
            raise

    @router.post('/api/v1/public/store-returns/{store_slug}/status')
    async def status(store_slug: str, body: ShopperConfirmation, request: Request) -> dict[str,Any]:
        store,session=await session_scope(request.app.state.ecommerce.pool,store_slug,body.token)
        await throttle(request.app.state.ecommerce.pool,store['id'],'portal-status:'+str(session['id']),20)
        if session['state']=='VERIFIED': return {'status':'VERIFIED'}
        return await public_result(request,store,session)
    return router
