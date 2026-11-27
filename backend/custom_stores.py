"""Store-bound signed bridge intake, live checkout rates and outbound callbacks."""
from __future__ import annotations
import hashlib
import hmac
import json
import time
from decimal import Decimal
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.ai_engine import strict_decimal, country_code
from backend.ecommerce_sync import ImportPayload, StoreOrder
from backend.platform_registry import NATIVE
from backend.store_connections import resolve_connector
from backend.store_transport import store_json

def signature(secret: str, timestamp: str, method: str, path: str, store_id: UUID, raw: bytes) -> str:
    canonical='.'.join((timestamp,method.upper(),path,str(store_id),hashlib.sha256(raw).hexdigest()))
    return hmac.new(secret.encode(),canonical.encode(),hashlib.sha256).hexdigest()

async def bounded_body(request: Request, limit: int=1_048_576) -> bytes:
    if request.headers.get('content-type','').split(';')[0].lower()!='application/json':
        raise HTTPException(415,'Use application/json')
    value=bytearray()
    async for chunk in request.stream():
        value.extend(chunk)
        if len(value)>limit: raise HTTPException(413,'Request body exceeds the allowed size')
    return bytes(value)

async def throttle(pool: Any, store_id: UUID, subject: str, limit: int, seconds: int=60) -> None:
    key=hashlib.sha256(subject.encode()).hexdigest()
    bucket=int(time.time())//seconds
    async with pool.acquire() as c:
        count=await c.fetchval('''INSERT INTO public.store_api_usage(store_id,subject_sha256,bucket,requests)
            VALUES($1,$2,$3,1) ON CONFLICT(store_id,subject_sha256,bucket)
            DO UPDATE SET requests=store_api_usage.requests+1 RETURNING requests''',store_id,key,bucket)
        await c.execute('DELETE FROM public.store_api_usage WHERE store_id=$1 AND bucket<$2',store_id,bucket-1440)
    if count>limit: raise HTTPException(429,'Request limit reached; retry later')

async def signed_actor(request: Request, raw: bytes) -> tuple[Any,Any,UUID]:
    def header(name: str) -> str:
        values=request.headers.getlist(name)
        if len(values)!=1 or not 1<=len(values[0])<=200: raise HTTPException(401,'Invalid store authentication')
        return values[0]
    try:
        store_id=UUID(header('x-easyinvio-store-id')); stamp=header('x-easyinvio-timestamp')
        if not stamp.isdigit() or abs(time.time()-int(stamp))>300: raise ValueError()
    except ValueError: raise HTTPException(401,'Invalid or expired store authentication') from None
    service=request.app.state.ecommerce
    config=await resolve_connector(service,store_id)
    if not config or not config.api_key_id or header('x-easyinvio-key-id')!=config.api_key_id:
        raise HTTPException(401,'Invalid store authentication')
    expected=signature(config.webhook_secret.get_secret_value(),stamp,request.method,request.url.path,store_id,raw)
    if not hmac.compare_digest(header('x-easyinvio-signature'),expected): raise HTTPException(401,'Invalid store authentication')
    async with service.pool.acquire() as c:
        row=await c.fetchrow('''SELECT u.role FROM public.ecommerce_stores s JOIN public.users u
            ON u.tenant_id=s.tenant_id JOIN public.tenants t ON t.tenant_id=s.tenant_id
            WHERE s.id=$1 AND s.tenant_id=$2 AND s.is_active AND s.platform=$3
              AND u.auth_user_id=$4 AND u.is_active AND t.workspace_status='ACTIVE'
              AND t.billing_status='ACTIVE' ''',store_id,config.tenant_id,config.platform,config.auth_user_id)
    if not row or row['role'] not in {'OWNER','ADMIN','DISPATCHER'}: raise HTTPException(403,'Store operator is not an active dispatch member')
    context=SimpleNamespace(tenant_id=config.tenant_id,user_id=config.auth_user_id,role=row['role'],bearer_token='',assistance_session_id=None)
    return config,context,store_id

class CheckoutDestination(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    postal_code: str=Field(min_length=1,max_length=30)
    country_code: str
    city: str=Field(min_length=1,max_length=100)
    line1: str=Field(min_length=1,max_length=200)
    name: str=Field(min_length=1,max_length=200)
    @field_validator('country_code')
    @classmethod
    def country(cls,value: str) -> str: return country_code(value)

class CheckoutRates(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    weight_kg: Decimal=Field(gt=0,le=1000,decimal_places=3)
    length_cm: Decimal=Field(gt=0,le=1500,decimal_places=2)
    width_cm: Decimal=Field(gt=0,le=1000,decimal_places=2)
    height_cm: Decimal=Field(gt=0,le=1000,decimal_places=2)
    destination: CheckoutDestination
    currency: Literal['GBP','EUR','USD']='GBP'
    @field_validator('weight_kg','length_cm','width_cm','height_cm',mode='before')
    @classmethod
    def decimal(cls,value: Any) -> Decimal: return strict_decimal(value)

async def live_checkout(request: Request, context: Any, body: CheckoutRates) -> dict[str,Any]:
    from main import RatingRequest, Address, Dimensions
    service=request.app.state.ecommerce
    async with service.pool.acquire() as c:
        row=await c.fetchrow('SELECT legal_company_name,billing_address FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
    if not row: raise HTTPException(403,'Workspace unavailable')
    address=json.loads(row['billing_address']) if isinstance(row['billing_address'],str) else dict(row['billing_address'])
    address.setdefault('name',row['legal_company_name'])
    try:
        origin=Address.model_validate(address)
        destination=Address.model_validate(body.destination.model_dump())
        quote=RatingRequest(origin=origin,destination=destination,weights_kg=[body.weight_kg],currency=body.currency,
            dimensions=[Dimensions(length_cm=body.length_cm,width_cm=body.width_cm,height_cm=body.height_cm)])
    except ValueError: raise HTTPException(422,'Supply complete valid checkout addresses and measured parcel dimensions') from None
    from backend.entitlements import guard_feature
    await guard_feature(service.pool,service.settings,context.tenant_id,'store_integrations')
    result=await request.app.state.rating.quote(context,quote)
    # The same tier/margin engine as the workspace; never return cost or credentials.
    return {'currency':body.currency,'partial':result.partial,'expires_at':result.expires_at.isoformat(),
        'rates':[{'carrier':r.carrier_code,'service':r.service_code,'price_ex_tax':str(r.client_price_ex_tax),
                  'currency':r.currency,'delivery_days':r.delivery_days} for r in result.rates],
        'notice':'Live checkout estimate. Confirm complete shipment and customs details before buying a label.'}

async def callback(client: httpx.AsyncClient, config: Any, store_id: UUID, body: dict[str,Any]) -> dict[str,Any]:
    if not config.tracking_callback_url: raise HTTPException(409,'Configure a signed tracking callback URL')
    raw=json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    stamp=str(int(time.time())); path=urlsplit(config.tracking_callback_url).path or '/'
    await store_json(client,'POST',config.tracking_callback_url,content=raw,headers={
        'Content-Type':'application/json','X-EasyInvio-Store-Id':str(store_id),
        'X-EasyInvio-Key-Id':config.api_key_id,'X-EasyInvio-Timestamp':stamp,
        'X-EasyInvio-Signature':signature(config.webhook_secret.get_secret_value(),stamp,'POST',path,store_id,raw),
        'Idempotency-Key':body['event_id']})
    return {'simulated':False,'callback_accepted':True}

def signed_schema(model: type[BaseModel]) -> dict[str,Any]:
    """Inline this bounded non-recursive contract for raw-body OpenAPI routes."""
    schema=model.model_json_schema()
    definitions=schema.pop('$defs',{})
    def expand(value: Any) -> Any:
        if isinstance(value,list): return [expand(v) for v in value]
        if not isinstance(value,dict): return value
        if '$ref' in value:
            key=value['$ref'].removeprefix('#/$defs/')
            return expand({**definitions[key],**{k:v for k,v in value.items() if k!='$ref'}})
        return {k:expand(v) for k,v in value.items()}
    return expand(schema)

def build_router() -> APIRouter:
    def private_response(response: Response) -> None:
        response.headers['Cache-Control']='no-store'
    router=APIRouter(prefix='/api/v1/integration/custom-store',tags=['Signed store API'],dependencies=[Depends(private_response)])
    @router.post('/orders',status_code=201,openapi_extra={'requestBody':{'required':True,'content':{'application/json':{'schema':signed_schema(StoreOrder)}}}})
    async def orders(request: Request) -> dict[str,Any]:
        raw=await bounded_body(request); config,context,store_id=await signed_actor(request,raw)
        await throttle(request.app.state.ecommerce.pool,store_id,'order-import',120)
        try: order=StoreOrder.model_validate_json(raw)
        except ValueError: raise HTTPException(422,'Invalid normalized StoreOrder; consult the custom website guide') from None
        return await request.app.state.ecommerce.import_order(context,ImportPayload(store_id=store_id,platform=config.platform,order=order,cargo_type=config.cargo_type))
    @router.post('/checkout-rates',openapi_extra={'requestBody':{'required':True,'content':{'application/json':{'schema':signed_schema(CheckoutRates)}}}})
    async def rates(request: Request) -> dict[str,Any]:
        raw=await bounded_body(request,32768); _,context,store_id=await signed_actor(request,raw)
        await throttle(request.app.state.ecommerce.pool,store_id,'checkout-rates',20)
        try: body=CheckoutRates.model_validate_json(raw)
        except ValueError: raise HTTPException(422,'Invalid checkout parcel/address; consult the custom website guide') from None
        from backend.entitlements import guard_feature
        await guard_feature(request.app.state.ecommerce.pool,request.app.state.ecommerce.settings,context.tenant_id,'store_integrations')
        digest=hashlib.sha256(raw).hexdigest()
        pool=request.app.state.ecommerce.pool
        async with pool.acquire() as c:
            cached=await c.fetchrow('SELECT response FROM public.store_checkout_cache WHERE tenant_id=$1 AND store_id=$2 AND input_sha256=$3 AND expires_at>now()',context.tenant_id,store_id,digest)
        if cached:
            return json.loads(cached['response']) if isinstance(cached['response'],str) else dict(cached['response'])
        result=await live_checkout(request,context,body)
        async with pool.acquire() as c:
            await c.execute('''INSERT INTO public.store_checkout_cache(tenant_id,store_id,input_sha256,response,expires_at)
                VALUES($1,$2,$3,$4::jsonb,LEAST(now()+interval '90 seconds',$5::timestamptz))
                ON CONFLICT(tenant_id,store_id,input_sha256) DO UPDATE SET response=excluded.response,expires_at=excluded.expires_at''',context.tenant_id,store_id,digest,json.dumps(result),datetime.fromisoformat(result['expires_at']))
            await c.execute('DELETE FROM public.store_checkout_cache WHERE store_id=$1 AND expires_at<now()',store_id)
        return result
    return router
