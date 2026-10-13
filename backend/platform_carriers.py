"""Owner-managed shared provider connections; tenant shipments retain isolated FKs."""
import json
from uuid import UUID, uuid5, NAMESPACE_URL
import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import SecretStr
from backend.admin_management import CarrierCreate, validate_endpoint, public_record
from backend.admin_portal import authenticate_platform_owner, database_error

router = APIRouter(prefix='/api/v1/admin/platform-carriers', tags=['Platform carrier connections'])
owner = Depends(authenticate_platform_owner)
PUBLIC = 'id,account_name,aggregator,regional_provider_code,api_base_url,upstream_account_id,environment,priority,timeout_seconds,is_active,retired_at'


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
        from backend.aggregator_registry import identify_aggregator
        spec=identify_aggregator(body.api_base_url)
        body=body.model_copy(update={'regional_provider_code':spec.code if spec else 'CUSTOM'})
    if not body.account_name.strip() or not settings.credential_keys:
        raise HTTPException(422, 'Account name and server encryption configuration required')
    identifier = connection_id or body.request_id
    key_id = sorted(settings.credential_keys)[0]
    secret = body.api_key.get_secret_value().strip() if body.api_key else ''
    if body.api_key and (not secret or len(secret) > 4096):
        raise HTTPException(422, 'A nonempty API key of at most 4096 characters is required')
    if secret and body.api_base_url in {'https://panel.sendcloud.sc/api/v2','https://panel.sendcloud.sc/api/v3'}:
        from backend.sendcloud_adapter import sendcloud_credentials
        try:
            sendcloud_credentials(secret)
        except (ValueError,TypeError,KeyError):
            raise HTTPException(422,'Supply both Sendcloud public and secret API keys') from None
    if secret and body.api_base_url=='https://api.goshippo.com':
        prefix='shippo_test_' if body.environment=='TEST' else 'shippo_live_'
        if not secret.startswith(prefix):
            raise HTTPException(422,'Use a Shippo token matching this connection environment')
    try:
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                # Serialize platform rollout and capacity decisions with other platform saves.
                await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('platform-carriers',0))")
                previous = await c.fetchrow('SELECT * FROM public.platform_carrier_connections WHERE id=$1 FOR UPDATE', identifier)
                if connection_id and previous is None:
                    raise HTTPException(404, 'Platform connection not found')
                if previous is not None and not secret and any(previous[k] != getattr(body,k)
                    for k in ('api_base_url','aggregator','environment')):
                    raise HTTPException(422,'Changing provider or environment requires replacement credentials')
                if previous is not None and connection_id and any(previous[k] != getattr(body,k)
                    for k in ('api_base_url','aggregator','environment','upstream_account_id')):
                    used = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.shipments s
                        JOIN public.carrier_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.carrier_account_id
                        WHERE a.platform_connection_id=$1)''', identifier)
                    if used:
                        raise HTTPException(409,'This connection has shipment history. Add a new connection and retire this one to preserve original label and refund access.')
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
                    priority=excluded.priority,timeout_seconds=excluded.timeout_seconds,is_active=excluded.is_active,retired_at=NULL''',
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


@router.post('/{connection_id}/disable')
@router.delete('/{connection_id}',deprecated=True)
async def retire(connection_id: UUID, request: Request, actor=owner):
    async with request.app.state.finance.pool.acquire() as c:
        async with c.transaction():
            row=await c.fetchrow('UPDATE public.platform_carrier_connections SET is_active=false,retired_at=NULL WHERE id=$1 RETURNING id',connection_id)
            if not row: raise HTTPException(404,'Platform connection not found')
            await c.execute("INSERT INTO public.platform_carrier_events(actor_auth_user_id,connection_id,action,snapshot) VALUES($1,$2,'RETIRE','{}')",actor.user_id,connection_id)
    return {'id':str(connection_id),'is_active':False}

@router.get('/capabilities')
async def capabilities(request: Request, actor=owner):
    from backend.aggregator_registry import public_capabilities
    return {'providers': public_capabilities(), 'generic_regional_protocol': True,
            'notice': 'API credentials alone do not implement a new provider wire protocol.'}


@router.post('/{connection_id}/upgrade-sendcloud')
async def upgrade_sendcloud(connection_id: UUID, request: Request, actor=owner):
    """Replace legacy rate configuration without modifying historical connections."""
    import httpx
    from backend.sendcloud_adapter import sendcloud_credentials, V3_ENDPOINT
    settings = request.app.state.settings
    replacement_id = uuid5(NAMESPACE_URL, 'easyinvio:sendcloud-v3:' + str(connection_id))
    async with request.app.state.finance.pool.acquire() as c:
        source = await c.fetchrow('SELECT * FROM public.platform_carrier_connections WHERE id=$1', connection_id)
    if source is None:
        raise HTTPException(404, 'Platform connection not found')
    if source['api_base_url'] != 'https://panel.sendcloud.sc/api/v2' or source['environment'] != settings.provider_environment:
        raise HTTPException(422, 'Only a legacy Sendcloud connection in the current environment can be upgraded')
    try:
        key = settings.credential_keys[source['credential_key_id']].get_secret_value().encode()
        envelope = json.loads(Fernet(key).decrypt(bytes(source['credentials_ciphertext'])))
        if envelope.get('platform_id') != str(connection_id):
            raise ValueError('Credential identity mismatch')
        secret = envelope['api_key']
        auth = sendcloud_credentials(secret)
    except (ValueError, KeyError, TypeError, InvalidToken):
        raise HTTPException(503, 'Private carrier credential configuration is unavailable') from None
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=min(source['timeout_seconds'], 20)) as client:
            response = await client.get(V3_ENDPOINT + '/user/auth/metadata', auth=auth, follow_redirects=False)
        if response.status_code != 200:
            raise HTTPException(409, 'Sendcloud v3 credential verification failed; no connection was changed')
    except httpx.HTTPError:
        raise HTTPException(503, 'Sendcloud verification is temporarily unavailable; no connection was changed') from None
    try:
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('platform-carriers',0))")
                current = await c.fetchrow('SELECT * FROM public.platform_carrier_connections WHERE id=$1 FOR UPDATE', connection_id)
                if current is None or any(current[field] != source[field] for field in (
                        'api_base_url', 'environment', 'credentials_ciphertext', 'credential_key_id', 'is_active', 'retired_at',
                        'priority', 'timeout_seconds', 'account_name', 'upstream_account_id')):
                    raise HTTPException(409, 'Connection changed during verification; retry the upgrade')
                existing = await c.fetchrow('SELECT * FROM public.platform_carrier_connections WHERE id=$1', replacement_id)
                if existing is not None:
                    if source['is_active'] or existing['api_base_url'] != V3_ENDPOINT or existing['environment'] != source['environment']:
                        raise HTTPException(409, 'Replacement connection identity is invalid')
                    return {'id': str(replacement_id), 'previous_connection_id': str(connection_id),
                            'is_active': existing['is_active'], 'upgraded': True}
                # Disabling first keeps active connection counts unchanged during propagation.
                await c.execute('UPDATE public.platform_carrier_connections SET is_active=false,retired_at=NULL WHERE id=$1', connection_id)
                cipher = Fernet(key).encrypt(json.dumps({'platform_id': str(replacement_id), 'api_key': secret}).encode())
                await c.execute('''INSERT INTO public.platform_carrier_connections
                    (id,account_name,aggregator,regional_provider_code,api_base_url,upstream_account_id,environment,
                     credentials_ciphertext,credential_key_id,priority,timeout_seconds,is_active)
                    VALUES($1,$2,'REGIONAL','SENDCLOUD_V3',$3,$4,$5,$6,$7,$8,$9,$10)''',
                    replacement_id, source['account_name'][:195] + ' v3', V3_ENDPOINT, source['upstream_account_id'],
                    source['environment'], cipher, source['credential_key_id'], source['priority'],
                    source['timeout_seconds'], source['is_active'])
                for identifier, action, snapshot in (
                        (connection_id, 'RETIRE', {'replacement_id': str(replacement_id), 'reason': 'SENDCLOUD_V3_UPGRADE'}),
                        (replacement_id, 'SAVE', {'previous_connection_id': str(connection_id), 'reason': 'SENDCLOUD_V3_UPGRADE'})):
                    await c.execute('''INSERT INTO public.platform_carrier_events(actor_auth_user_id,connection_id,action,snapshot)
                        VALUES($1,$2,$3,$4::jsonb)''', actor.user_id, identifier, action, json.dumps(snapshot))
        return {'id': str(replacement_id), 'previous_connection_id': str(connection_id),
                'is_active': source['is_active'], 'upgraded': True}
    except asyncpg.PostgresError as exc:
        raise database_error(exc) from None


@router.post('/{connection_id}/verify')
async def verify_connection(connection_id: UUID, request: Request, actor=owner):
    """Read-only credential verification; never purchase or dispatch a label."""
    import httpx
    from backend.aggregator_registry import identify_aggregator
    from backend.sendcloud_adapter import sendcloud_credentials
    settings=request.app.state.settings
    async with request.app.state.finance.pool.acquire() as connection:
        row=await connection.fetchrow('SELECT * FROM public.platform_carrier_connections WHERE id=$1',connection_id)
    if row is None:raise HTTPException(404,'Platform connection not found')
    spec=identify_aggregator(row['api_base_url'])
    if spec is None:
        raise HTTPException(422,'This provider needs its own read-only verification adapter')
    try:
        key=settings.credential_keys[row['credential_key_id']]
        envelope=json.loads(Fernet(key.get_secret_value().encode()).decrypt(bytes(row['credentials_ciphertext'])))
        if envelope.get('platform_id')!=str(connection_id):raise ValueError('Credential identity mismatch')
        secret=envelope['api_key']
        auth=(sendcloud_credentials(secret) if spec.code.startswith('SENDCLOUD') else httpx.BasicAuth(secret,''))
        headers={}
        if spec.code=='SHIPPO':
            if not secret.startswith('shippo_test_' if row['environment']=='TEST' else 'shippo_live_'):
                raise ValueError('Connection token environment mismatch')
            from backend.automation_three_partners import ShippoAdapter
            headers=ShippoAdapter(None,secret,environment=row['environment']).authentication()['headers'];auth=None
    except (ValueError,KeyError,TypeError,InvalidToken):
        raise HTTPException(503,'Private carrier credential configuration is unavailable') from None
    path='/user/auth/metadata' if spec.code=='SENDCLOUD_V3' else '/shipping_methods' if spec.code=='SENDCLOUD_V2' else '/addresses/' if spec.code=='SHIPPO' else '/shipments'
    try:
        async with httpx.AsyncClient(trust_env=False,timeout=min(row['timeout_seconds'],20)) as client:
            response=await client.get(spec.endpoint+path,auth=auth,headers=headers,params={'page_size':1} if spec.code=='EASYPOST' else None,follow_redirects=False)
        return {'connection_id':str(connection_id),'provider':spec.name,'authenticated':response.status_code==200,
                'upstream_http_status':response.status_code,'read_only':True,'label_created':False,
                'label_purchase_supported':spec.label_purchase}
    except httpx.HTTPError:
        raise HTTPException(503,'Provider verification is temporarily unavailable') from None
