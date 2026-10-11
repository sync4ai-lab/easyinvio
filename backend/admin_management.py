"""Owner-only, audited management of existing tenant-scoped configuration."""
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Literal
from uuid import UUID, uuid4
from urllib.parse import urlsplit
import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field, SecretStr
from backend.admin_portal import InputModel, MarginCreate, authenticate_platform_owner, database_error

router = APIRouter(prefix='/api/v1/admin', tags=['Platform management'])
owner_dependency = Depends(authenticate_platform_owner)

def public_record(row):
    result = {}
    for key, value in dict(row).items():
        if isinstance(value, Decimal): value = str(value)
        elif isinstance(value, UUID): value = str(value)
        elif isinstance(value, datetime): value = value.isoformat()
        result[key] = value
    return result

async def audit(connection, actor, tenant_id, action, target_id, snapshot):
    # Snapshot is constructed from public fields only, never credential material.
    await connection.execute('''INSERT INTO public.admin_management_events
        (actor_auth_user_id,tenant_id,action,target_id,snapshot)
        VALUES($1,$2,$3,$4,$5::jsonb)''', actor.user_id, tenant_id, action, target_id, json.dumps(snapshot))

@router.get('/tenants')
async def tenants(request: Request, owner=owner_dependency, limit: int=Query(200,ge=1,le=500)):
    async with request.app.state.finance.pool.acquire() as c:
        rows=await c.fetch('''SELECT tenant_id,company_name,workspace_slug,billing_email,billing_plan,
            default_currency,workspace_status,billing_status,is_sandbox,created_at,
            company_profile->'hubspot'->>'company_id' AS hubspot_company_id,
            company_profile->'hubspot'->>'portal_id' AS hubspot_portal_id
            FROM public.tenants ORDER BY created_at DESC,tenant_id LIMIT $1''',limit)
    return {'tenants':[public_record(r) for r in rows], 'limit':limit}

@router.get('/margins')
async def margins(request: Request, owner=owner_dependency, tenant_id: UUID | None=None):
    async with request.app.state.finance.pool.acquire() as c:
        rows=await c.fetch('''SELECT m.id,m.tenant_id,t.company_name,m.rule_name,m.origin_country,
            m.destination_country,m.carrier_code,m.service_code,m.carrier_account_id,m.currency,
            m.markup_type,m.markup_value,m.minimum_markup,m.maximum_markup,m.min_weight_kg,
            m.max_weight_kg,m.min_wholesale_cost,m.max_wholesale_cost,m.priority,m.is_active,
            m.valid_from,m.valid_until,m.billing_plan,m.cargo_type,m.min_volume_m3,m.max_volume_m3 FROM public.margin_rules m JOIN public.tenants t USING(tenant_id)
            WHERE ($1::uuid IS NULL OR m.tenant_id=$1) ORDER BY m.is_active DESC,m.priority,m.created_at DESC LIMIT 500''',tenant_id)
    return {'rules':[public_record(r) for r in rows], 'priority_policy':'Lower numeric priority wins; specificity breaks ties.', 'limit':500}

@router.put('/margins/{rule_id}')
async def update_margin(rule_id: UUID, body: MarginCreate, request: Request, owner=owner_dependency):
    try:
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                old=await c.fetchrow('SELECT * FROM public.margin_rules WHERE id=$1 FOR UPDATE',rule_id)
                if not old: raise HTTPException(404,'Margin rule not found')
                if old['tenant_id']!=body.tenant_id: raise HTTPException(422,'A rule cannot be moved to another tenant')
                if body.carrier_account_id and not await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.carrier_accounts WHERE tenant_id=$1 AND id=$2)',body.tenant_id,body.carrier_account_id):
                    raise HTTPException(422,'Carrier must belong to the selected tenant')
                currency=body.currency or old['currency']
                await c.execute('''UPDATE public.margin_rules SET origin_country=$2,destination_country=$3,
                    carrier_code=$4,service_code=$5,carrier_account_id=$6,currency=$7,markup_type=$8,
                    markup_value=$9,priority=$10,is_active=$11,minimum_markup=$12,maximum_markup=$13,
                    min_weight_kg=$14,max_weight_kg=$15,min_wholesale_cost=$16,max_wholesale_cost=$17,
                    valid_from=coalesce($18,valid_from),valid_until=$19,billing_plan=$20,cargo_type=$21,
                    min_volume_m3=$22,max_volume_m3=$23 WHERE id=$1''',
                    rule_id,body.origin_country,body.destination_country,body.carrier_code,body.service_code,
                    body.carrier_account_id,currency,'FIXED' if body.markup_type=='FLAT_RATE' else 'PERCENTAGE',
                    body.markup_value,body.priority,body.is_active,body.minimum_markup,body.maximum_markup,
                    body.min_weight_kg,body.max_weight_kg,body.min_wholesale_cost,body.max_wholesale_cost,body.valid_from,body.valid_until,
                    body.billing_plan,body.cargo_type,body.min_volume_m3,body.max_volume_m3)
                await audit(c,owner,body.tenant_id,'UPDATE_MARGIN',rule_id,body.model_dump(mode='json'))
        return {'id':str(rule_id),'updated':True}
    except asyncpg.PostgresError as e: raise database_error(e) from None

@router.delete('/margins/{rule_id}')
async def retire_margin(rule_id: UUID, request: Request, owner=owner_dependency):
    try:
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                row=await c.fetchrow('UPDATE public.margin_rules SET is_active=false WHERE id=$1 RETURNING tenant_id',rule_id)
                if not row: raise HTTPException(404,'Margin rule not found')
                await audit(c,owner,row['tenant_id'],'RETIRE_MARGIN',rule_id,{'is_active':False})
        return {'id':str(rule_id),'is_active':False,'notice':'Removed from pricing selection; historical shipment references retained.'}
    except asyncpg.PostgresError as e: raise database_error(e) from None

class CarrierCreate(InputModel):
    request_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    account_name: str=Field(min_length=1,max_length=200)
    aggregator: Literal['EASYPOST','REGIONAL']
    regional_provider_code: str | None=Field(default=None,min_length=1,max_length=100)
    api_base_url: str=Field(max_length=500)
    api_key: SecretStr
    upstream_account_id: str | None=Field(default=None,max_length=200)
    environment: Literal['TEST','LIVE']='TEST'
    priority: int=Field(default=100,ge=0,le=1000000,strict=True)
    timeout_seconds: int=Field(default=30,ge=1,le=120,strict=True)
    is_active: bool=Field(default=False,strict=True)

class CarrierUpdate(InputModel):
    is_active: bool=Field(strict=True)
    priority: int=Field(default=100,ge=0,le=1000000,strict=True)
    timeout_seconds: int=Field(default=30,ge=1,le=120,strict=True)

def validate_endpoint(provider, endpoint, settings):
    parsed=urlsplit(endpoint)
    if provider=='EASYPOST':
        if endpoint!='https://api.easypost.com/v2': raise HTTPException(422,'Use the official EasyPost v2 endpoint')
    elif (parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment
          or f'{parsed.scheme}://{parsed.netloc}' not in settings.regional_allowed_origins):
        raise HTTPException(422,'Regional endpoint origin must be explicitly approved in server configuration')

@router.get('/carriers')
async def carriers(request: Request, owner=owner_dependency):
    async with request.app.state.finance.pool.acquire() as c:
        rows=await c.fetch('''SELECT a.id,a.tenant_id,t.company_name,a.account_name,a.aggregator,
            a.regional_provider_code,a.api_base_url,a.environment,a.is_active,a.priority,a.timeout_seconds
            FROM public.carrier_accounts a JOIN public.tenants t USING(tenant_id)
            WHERE a.platform_connection_id IS NULL
            ORDER BY a.is_active DESC,t.company_name,a.priority LIMIT 500''')
    return {'connections':[public_record(r) for r in rows], 'supported':['EASYPOST','REGIONAL'],
            'notice':'Connections are tenant-assigned. Sendcloud read-only rating uses REGIONAL, its official endpoint and SENDCLOUD_METHODS limits. Purchase requires a separate adapter.', 'limit':500}

@router.post('/carriers',status_code=201)
async def add_carrier(body: CarrierCreate, request: Request, owner=owner_dependency):
    settings=request.app.state.settings
    validate_endpoint(body.aggregator,body.api_base_url,settings)
    if body.environment!=settings.provider_environment: raise HTTPException(422,'Connection environment must match server provider environment')
    if body.aggregator=='REGIONAL' and not body.regional_provider_code: raise HTTPException(422,'Regional provider code required')
    keys=settings.credential_keys
    if not keys: raise HTTPException(503,'Configure CREDENTIAL_KEYS on the server before storing connections')
    key_id=sorted(keys)[0];account_id=body.request_id
    secret=body.api_key.get_secret_value().strip()
    if not secret or len(secret)>4096: raise HTTPException(422,'Carrier API key must be 1–4096 characters')
    if not body.account_name.strip():raise HTTPException(422,'Account name cannot be blank')
    envelope=json.dumps({'tenant_id':str(body.tenant_id),'account_id':str(account_id),'api_key':secret}).encode()
    ciphertext=Fernet(keys[key_id].get_secret_value().encode()).encrypt(envelope)
    try:
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('platform-carriers',0))")
                await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',str(account_id))
                previous=await c.fetchrow('SELECT * FROM public.carrier_accounts WHERE id=$1',account_id)
                if previous:
                    try:
                        old_key=keys[previous['credential_key_id']]
                        old_envelope=json.loads(Fernet(old_key.get_secret_value().encode()).decrypt(bytes(previous['credentials_ciphertext'])))
                        same=old_envelope.get('api_key')==secret and all(previous[k]==getattr(body,k) for k in ['tenant_id','aggregator','environment','api_base_url','regional_provider_code','upstream_account_id','priority','timeout_seconds','is_active']) and previous['account_name']==body.account_name.strip()
                    except (KeyError,TypeError,ValueError,InvalidToken):same=False
                    if not same:raise HTTPException(409,'Connection request ID already exists with different configuration')
                    return {'id':str(account_id),'tenant_id':str(body.tenant_id),'is_active':body.is_active,'replayed':True}
                tenant=await c.fetchrow('SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1 FOR UPDATE',body.tenant_id)
                if not tenant: raise HTTPException(404,'Tenant not found')
                if tenant['is_sandbox'] and body.environment=='LIVE': raise HTTPException(422,'Sandbox tenants cannot use live credentials')
                if body.is_active and await c.fetchval('SELECT count(*) FROM public.carrier_accounts WHERE tenant_id=$1 AND is_active',body.tenant_id)>=settings.max_accounts_per_tenant:
                    raise HTTPException(422,'Tenant active-carrier limit reached; disable a connection first')
                await c.execute('''INSERT INTO public.carrier_accounts(id,tenant_id,account_name,aggregator,
                    regional_provider_code,api_base_url,environment,credentials_ciphertext,credential_key_id,
                    upstream_account_id,timeout_seconds,priority,is_active) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)''',
                    account_id,body.tenant_id,body.account_name.strip(),body.aggregator,body.regional_provider_code,
                    body.api_base_url,body.environment,ciphertext,key_id,body.upstream_account_id,body.timeout_seconds,body.priority,body.is_active)
                await audit(c,owner,body.tenant_id,'CREATE_CARRIER',account_id,{'account_name':body.account_name,'aggregator':body.aggregator,'environment':body.environment,'is_active':body.is_active})
        return {'id':str(account_id),'tenant_id':str(body.tenant_id),'is_active':body.is_active}
    except asyncpg.PostgresError as e: raise database_error(e) from None

@router.patch('/carriers/{account_id}')
async def change_carrier(account_id: UUID, body: CarrierUpdate, request: Request, owner=owner_dependency):
    try:
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('platform-carriers',0))")
                row=await c.fetchrow('SELECT * FROM public.carrier_accounts WHERE id=$1 FOR UPDATE',account_id)
                if not row: raise HTTPException(404,'Carrier connection not found')
                if body.is_active:
                    settings=request.app.state.settings
                    tenant=await c.fetchrow('SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1 FOR UPDATE',row['tenant_id'])
                    if not tenant:raise HTTPException(404,'Tenant not found')
                    if tenant['is_sandbox'] and row['environment']=='LIVE':raise HTTPException(422,'Sandbox tenants cannot enable live credentials')
                    if not row['is_active'] and await c.fetchval('SELECT count(*) FROM public.carrier_accounts WHERE tenant_id=$1 AND is_active',row['tenant_id'])>=settings.max_accounts_per_tenant:
                        raise HTTPException(422,'Tenant active-carrier limit reached; disable a connection first')
                    validate_endpoint(row['aggregator'],row['api_base_url'],settings)
                    if row['environment']!=settings.provider_environment: raise HTTPException(422,'Provider environment mismatch')
                    try:
                        key=settings.credential_keys[row['credential_key_id']]
                        envelope=json.loads(Fernet(key.get_secret_value().encode()).decrypt(bytes(row['credentials_ciphertext'])))
                        if envelope.get('tenant_id')!=str(row['tenant_id']) or envelope.get('account_id')!=str(account_id) or not envelope.get('api_key'): raise ValueError()
                    except (KeyError,ValueError,TypeError,InvalidToken): raise HTTPException(422,'Valid tenant-bound credentials are required before activation') from None
                await c.execute('UPDATE public.carrier_accounts SET is_active=$2,priority=$3,timeout_seconds=$4 WHERE id=$1',account_id,body.is_active,body.priority,body.timeout_seconds)
                await audit(c,owner,row['tenant_id'],'UPDATE_CARRIER',account_id,body.model_dump(mode='json'))
        return {'id':str(account_id),**body.model_dump()}
    except asyncpg.PostgresError as e: raise database_error(e) from None

@router.delete('/carriers/{account_id}')
async def remove_carrier(account_id: UUID, request: Request, owner=owner_dependency):
    # Preserve foreign keys and historic quote/label records by retiring the connection.
    try:
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                row=await c.fetchrow('UPDATE public.carrier_accounts SET is_active=false WHERE id=$1 RETURNING tenant_id',account_id)
                if not row: raise HTTPException(404,'Carrier connection not found')
                await audit(c,owner,row['tenant_id'],'RETIRE_CARRIER',account_id,{'is_active':False})
        return {'id':str(account_id),'is_active':False,'notice':'Connection retired; shipment history retained.'}
    except asyncpg.PostgresError as e: raise database_error(e) from None

@router.get('/transactions')
async def transactions(request: Request, owner=owner_dependency, tenant_id: UUID | None=None):
    async with request.app.state.finance.pool.acquire() as c:
        rows=await c.fetch('''SELECT l.id,l.tenant_id,t.company_name,l.entry_type,l.balance_delta,
            l.reserved_delta,l.balance_after,l.currency,l.created_at FROM public.wallet_ledger l
            JOIN public.tenants t USING(tenant_id) WHERE ($1::uuid IS NULL OR l.tenant_id=$1)
            ORDER BY l.created_at DESC,l.id DESC LIMIT 200''',tenant_id)
    return {'transactions':[public_record(r) for r in rows],'limit':200}
