"""Owner-managed shared provider connections; tenant shipments retain isolated FKs."""
import json
from uuid import UUID
import asyncpg
from cryptography.fernet import Fernet
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import SecretStr
from backend.admin_management import CarrierCreate, validate_endpoint, public_record
from backend.admin_portal import authenticate_platform_owner, database_error

router = APIRouter(prefix='/api/v1/admin/platform-carriers', tags=['Platform carrier connections'])
owner = Depends(authenticate_platform_owner)
PUBLIC = 'id,account_name,aggregator,regional_provider_code,api_base_url,upstream_account_id,environment,priority,timeout_seconds,is_active'


class PlatformConnection(CarrierCreate):
    tenant_id: UUID | None = None
    api_key: SecretStr | None = None


async def save(body, request, actor, connection_id=None):
    settings = request.app.state.settings
    if body.tenant_id is not None:
        raise HTTPException(422, 'Platform connections belong to EasyInvio, not an assigned client')
    validate_endpoint(body.aggregator, body.api_base_url, settings)
    if body.environment != settings.provider_environment:
        raise HTTPException(422, 'Environment must match the server provider mode')
    if body.aggregator == 'REGIONAL' and not body.regional_provider_code:
        raise HTTPException(422, 'Regional provider identifier required')
    if not body.account_name.strip() or not settings.credential_keys:
        raise HTTPException(422, 'Account name and server encryption configuration required')
    identifier = connection_id or body.request_id
    key_id = sorted(settings.credential_keys)[0]
    secret = body.api_key.get_secret_value().strip() if body.api_key else ''
    if body.api_key and (not secret or len(secret) > 4096):
        raise HTTPException(422, 'A nonempty API key of at most 4096 characters is required')
    try:
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                # Serialize platform rollout and capacity decisions with other platform saves.
                await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('platform-carriers',0))")
                previous = await c.fetchrow('SELECT * FROM public.platform_carrier_connections WHERE id=$1 FOR UPDATE', identifier)
                if connection_id and previous is None:
                    raise HTTPException(404, 'Platform connection not found')
                if previous is None and not secret:
                    raise HTTPException(422, 'Supply the aggregator API key')
                if previous and not connection_id:
                    key = settings.credential_keys[previous['credential_key_id']]
                    envelope = json.loads(Fernet(key.get_secret_value().encode()).decrypt(bytes(previous['credentials_ciphertext'])))
                    fields = ['account_name','aggregator','api_base_url','environment','regional_provider_code','upstream_account_id','priority','timeout_seconds','is_active']
                    if envelope.get('api_key') != secret or any(previous[k] != getattr(body,k) for k in fields):
                        raise HTTPException(409, 'Request ID already used; retry the original request or edit the connection')
                    return {'id': str(identifier), 'platform_owned': True, 'is_active': previous['is_active']}
                if body.is_active:
                    full = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.tenants t WHERE t.is_sandbox=$1
                        AND t.workspace_status='ACTIVE' AND (SELECT count(*) FROM public.carrier_accounts a
                        WHERE a.tenant_id=t.tenant_id AND a.is_active AND a.platform_connection_id IS DISTINCT FROM $2)>=$3)''',
                        body.environment == 'TEST', identifier, settings.max_accounts_per_tenant)
                    if full:
                        raise HTTPException(422, 'A client has reached its active-provider capacity; retire an unused connection first')
                cipher = (Fernet(settings.credential_keys[key_id].get_secret_value().encode()).encrypt(
                    json.dumps({'platform_id': str(identifier), 'api_key': secret}).encode()) if secret else bytes(previous['credentials_ciphertext']))
                if not secret:
                    key_id = previous['credential_key_id']
                await c.execute('''INSERT INTO public.platform_carrier_connections
                    (id,account_name,aggregator,regional_provider_code,api_base_url,upstream_account_id,environment,
                     credentials_ciphertext,credential_key_id,priority,timeout_seconds,is_active)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) ON CONFLICT(id) DO UPDATE SET
                    account_name=excluded.account_name,aggregator=excluded.aggregator,regional_provider_code=excluded.regional_provider_code,
                    api_base_url=excluded.api_base_url,upstream_account_id=excluded.upstream_account_id,environment=excluded.environment,
                    credentials_ciphertext=excluded.credentials_ciphertext,credential_key_id=excluded.credential_key_id,
                    priority=excluded.priority,timeout_seconds=excluded.timeout_seconds,is_active=excluded.is_active''',
                    identifier,body.account_name.strip(),body.aggregator,body.regional_provider_code,body.api_base_url,
                    body.upstream_account_id,body.environment,cipher,key_id,body.priority,body.timeout_seconds,body.is_active)
                snapshot = body.model_dump(mode='json', exclude={'api_key','tenant_id','request_id'})
                await c.execute("INSERT INTO public.platform_carrier_events(actor_auth_user_id,connection_id,action,snapshot) VALUES($1,$2,'SAVE',$3::jsonb)",actor.user_id,identifier,json.dumps(snapshot))
        return {'id':str(identifier),'platform_owned':True,'is_active':body.is_active}
    except asyncpg.PostgresError as exc:
        raise database_error(exc) from None


@router.get('')
async def list_connections(request: Request, actor=owner):
    async with request.app.state.finance.pool.acquire() as c:
        rows = await c.fetch('SELECT '+PUBLIC+' FROM public.platform_carrier_connections ORDER BY priority,id LIMIT 500')
    return {'connections':[{**public_record(r),'platform_owned':True,'company_name':'EasyInvio · all eligible clients'} for r in rows]}


@router.post('', status_code=201)
async def create(body: PlatformConnection, request: Request, actor=owner):
    return await save(body,request,actor)


@router.put('/{connection_id}')
async def update(connection_id: UUID, body: PlatformConnection, request: Request, actor=owner):
    return await save(body,request,actor,connection_id)


@router.delete('/{connection_id}')
async def retire(connection_id: UUID, request: Request, actor=owner):
    async with request.app.state.finance.pool.acquire() as c:
        async with c.transaction():
            row=await c.fetchrow('UPDATE public.platform_carrier_connections SET is_active=false WHERE id=$1 RETURNING id',connection_id)
            if not row: raise HTTPException(404,'Platform connection not found')
            await c.execute("INSERT INTO public.platform_carrier_events(actor_auth_user_id,connection_id,action,snapshot) VALUES($1,$2,'RETIRE','{}')",actor.user_id,connection_id)
    return {'id':str(connection_id),'is_active':False}
