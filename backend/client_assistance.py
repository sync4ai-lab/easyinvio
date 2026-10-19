"""Verified platform operators acting in a tenant, with durable request audit events."""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from backend.admin_portal import authenticate_platform_owner

HEADER = 'X-EasyInvio-Assistance'
logger = logging.getLogger(__name__)
class AssistanceRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def guarded(request):
            try:
                response = await handler(request)
                response.headers['Cache-Control'] = 'no-store'
                return response
            except asyncpg.UndefinedTableError:
                raise HTTPException(503, 'Apply migration 037_admin_client_assistance.sql before using client assistance') from None
            except asyncpg.PostgresError:
                raise HTTPException(503, 'Client assistance storage is temporarily unavailable') from None
        return guarded


router = APIRouter(prefix='/api/v1/admin/client-assistance', tags=['Client assistance'], route_class=AssistanceRoute)
owner_dependency = Depends(authenticate_platform_owner)


def redact_change(value, depth=0):
    if depth > 8:
        return '[nested data omitted]'
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:100]:
            normalized = str(key).lower().replace('_', '').replace('-', '')
            result[str(key)[:100]] = '[redacted]' if any(word in normalized for word in
                ('password','secret','credential','token','apikey','signature','authorization')) else redact_change(item, depth+1)
        return result
    if isinstance(value, list):
        return [redact_change(item, depth+1) for item in value[:100]]
    if isinstance(value, str):
        return value[:1000]
    return value


class StartAssistance(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    tenant_id: UUID
    reason: str = Field(min_length=10, max_length=500, pattern=r'^[^\x00-\x1f\x7f]+$')


async def append_event(connection, session, kind, request_id=None, method=None, path=None, status=None, detail=None):
    await connection.execute('''INSERT INTO public.admin_client_assistance_events
        (session_id,actor_auth_user_id,tenant_id,event_type,request_id,method,path,status_code,detail)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)''',
        session['id'], session['actor_auth_user_id'], session['tenant_id'], kind,
        request_id, method, path, status, json.dumps(detail or {}, separators=(',', ':')))


def token_fingerprint(request):
    claims=getattr(request.state,'app_session_claims',None)
    if claims:
        return hashlib.sha256(('app-session:'+claims['jti']).encode()).hexdigest()
    return hashlib.sha256(request.headers.get('authorization', '').encode()).hexdigest()


async def resolve_assistance(request, credentials=None):
    identifier = request.headers.get(HEADER)
    if not identifier:
        return None
    try:
        identifier = UUID(identifier)
    except ValueError:
        raise HTTPException(401, 'Invalid client assistance session') from None
    if credentials is None:
        credentials = await HTTPBearer(auto_error=False)(request)
    actor = await authenticate_platform_owner(request, credentials)
    async with request.app.state.finance.pool.acquire() as connection:
        session = await connection.fetchrow('''SELECT s.*,t.company_name,t.workspace_type,t.workspace_status,t.is_sandbox
            FROM public.admin_client_assistance_sessions s JOIN public.tenants t USING(tenant_id)
            WHERE s.id=$1 AND s.actor_auth_user_id=$2 AND s.bearer_sha256=ANY($3::text[])
            AND s.revoked_at IS NULL AND s.expires_at>now()''', identifier, actor.user_id,
            [token_fingerprint(request),hashlib.sha256(request.headers.get('authorization','').encode()).hexdigest()])
    if not session:
        raise HTTPException(401, 'Client assistance ended or expired. Return to Super Admin and select the client again.')
    request.state.client_assistance = dict(session)
    return request.state.client_assistance


async def operator_member_id(connection, context):
    """Use the actual admin's inactive audit membership only for verified assistance."""
    identifier = getattr(context, 'assistance_session_id', None)
    if identifier is None:
        return await connection.fetchval('''SELECT id FROM public.users WHERE tenant_id=$1
            AND auth_user_id=$2 AND is_active AND role IN ('OWNER','ADMIN','DISPATCHER')''', context.tenant_id, context.user_id)
    return await connection.fetchval('''SELECT operator_membership_id FROM public.admin_client_assistance_sessions
        WHERE id=$1 AND tenant_id=$2 AND actor_auth_user_id=$3 AND revoked_at IS NULL AND expires_at>now()''',
        identifier, context.tenant_id, context.user_id)


@router.get('/clients')
async def clients(request: Request, q: str=Query('', max_length=200), owner=owner_dependency):
    async with request.app.state.finance.pool.acquire() as connection:
        rows = await connection.fetch('''SELECT tenant_id,company_name,workspace_name,workspace_slug,
            billing_email,workspace_type,workspace_status,billing_status,is_sandbox FROM public.tenants
            WHERE $1='' OR position(lower($1) in lower(concat_ws(' ',tenant_id::text,company_name,
             workspace_name,workspace_slug,billing_email)))>0
            ORDER BY company_name,tenant_id LIMIT 50''', q.strip())
    return {'clients': [{**dict(row), 'tenant_id': str(row['tenant_id'])} for row in rows], 'limit': 50}


@router.post('/sessions', status_code=201)
async def start(body: StartAssistance, request: Request, owner=owner_dependency):
    claims = request.state.platform_auth_claims
    app_claims = getattr(request.state, 'app_session_claims', None)
    token_expiry = min(claims['exp'], app_claims['exp']) if app_claims else claims['exp']
    expiry = min(datetime.now(timezone.utc)+timedelta(minutes=30), datetime.fromtimestamp(token_expiry, timezone.utc))
    if expiry <= datetime.now(timezone.utc):
        raise HTTPException(401, 'Sign in again before assisting a client')
    async with request.app.state.finance.pool.acquire() as connection:
        async with connection.transaction():
            tenant = await connection.fetchrow('SELECT tenant_id,company_name,workspace_type,is_sandbox,workspace_status FROM public.tenants WHERE tenant_id=$1 FOR SHARE', body.tenant_id)
            if not tenant:
                raise HTTPException(404, 'Client workspace not found')
            # Inactive operator rows satisfy historical shipment FKs without
            # granting ordinary client membership or changing login behavior.
            await connection.execute('''INSERT INTO public.users(tenant_id,auth_user_id,role,full_name,is_active)
                VALUES($1,$2,'OWNER','EasyInvio platform support',false)
                ON CONFLICT(tenant_id,auth_user_id) DO NOTHING''', body.tenant_id, owner.user_id)
            member = await connection.fetchval('SELECT id FROM public.users WHERE tenant_id=$1 AND auth_user_id=$2', body.tenant_id, owner.user_id)
            session = await connection.fetchrow('''INSERT INTO public.admin_client_assistance_sessions
                (actor_auth_user_id,tenant_id,operator_membership_id,bearer_sha256,reason,expires_at)
                VALUES($1,$2,$3,$4,$5,$6) RETURNING *''',
                owner.user_id, body.tenant_id, member, token_fingerprint(request), body.reason.strip(), expiry)
            await append_event(connection, session, 'SESSION_STARTED', detail={'reason': body.reason.strip()})
    return {'session_id': str(session['id']), 'tenant_id': str(body.tenant_id), 'company_name': tenant['company_name'],
            'actor_user_id': str(owner.user_id), 'expires_at': expiry.isoformat(), 'workspace_role': 'OWNER',
            'is_sandbox': tenant['is_sandbox'], 'workspace_status': tenant['workspace_status'], 'workspace_type':tenant.get('workspace_type','BUSINESS')}


@router.delete('/sessions/{session_id}')
async def stop(session_id: UUID, request: Request, owner=owner_dependency):
    async with request.app.state.finance.pool.acquire() as connection:
        async with connection.transaction():
            session = await connection.fetchrow('SELECT * FROM public.admin_client_assistance_sessions WHERE id=$1 AND actor_auth_user_id=$2 FOR UPDATE', session_id, owner.user_id)
            if not session:
                raise HTTPException(404, 'Client assistance session not found')
            if session['revoked_at'] is None:
                await connection.execute('UPDATE public.admin_client_assistance_sessions SET revoked_at=now() WHERE id=$1', session_id)
                await append_event(connection, session, 'SESSION_ENDED')
    return {'ended': True}


@router.get('/events')
async def events(request: Request, tenant_id: UUID | None=None, include_reads: bool=False, owner=owner_dependency):
    async with request.app.state.finance.pool.acquire() as connection:
        rows = await connection.fetch('''SELECT e.id,e.session_id,e.actor_auth_user_id,e.tenant_id,
            t.company_name,e.event_type,e.request_id,e.method,e.path,e.status_code,e.detail,e.created_at,
            s.reason FROM public.admin_client_assistance_events e JOIN public.tenants t USING(tenant_id)
            JOIN public.admin_client_assistance_sessions s ON s.id=e.session_id
            WHERE ($1::uuid IS NULL OR e.tenant_id=$1)
            AND ($2::boolean OR e.event_type IN ('SESSION_STARTED','SESSION_ENDED') OR e.method NOT IN ('GET','HEAD','OPTIONS'))
            ORDER BY e.id DESC LIMIT 200''', tenant_id, include_reads)
    return {'events': [{**dict(row), **{key: str(row[key]) if row[key] is not None else None
        for key in ('session_id','actor_auth_user_id','tenant_id','request_id')},
        'created_at': row['created_at'].isoformat(),
        'detail': json.loads(row['detail']) if isinstance(row['detail'], str) else row['detail']} for row in rows]}


class ClientAssistanceMiddleware:
    """Write-ahead request audit. A failed outcome append leaves a durable STARTED event."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not any(key.lower() == HEADER.lower().encode() for key, _ in scope.get('headers', [])):
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = scope['path']
        try:
            if path.startswith('/api/v1/admin/') or path.startswith('/api/v1/auth/') or path.startswith('/webhooks/'):
                raise HTTPException(403, 'Return to Super Admin for platform or identity operations')
            session = await resolve_assistance(request)
            request_id = uuid4()
            async with request.app.state.finance.pool.acquire() as connection:
                await append_event(connection, session, 'REQUEST_STARTED', request_id, scope['method'], path[:1000])
        except HTTPException as error:
            return await JSONResponse({'detail': error.detail}, status_code=error.status_code)(scope, receive, send)
        except (asyncpg.PostgresError, OSError, TimeoutError):
            return await JSONResponse({'detail': 'Client assistance audit storage is unavailable. No action was started.'}, status_code=503)(scope, receive, send)
        status = 500
        body_digest = hashlib.sha256()
        body_bytes = 0
        body_preview = bytearray()
        async def audited_receive():
            nonlocal body_bytes
            message = await receive()
            if message['type'] == 'http.request':
                chunk = message.get('body', b'')
                body_digest.update(chunk)
                body_bytes += len(chunk)
                if body_bytes <= 16384:
                    body_preview.extend(chunk)
                else:
                    body_preview.clear()
            return message
        async def audited_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                message['headers'] = list(message.get('headers', [])) + [
                    (b'x-easyinvio-audit-id', str(request_id).encode()), (b'cache-control', b'no-store')]
            await send(message)
        try:
            await self.app(scope, audited_receive, audited_send)
        finally:
            try:
                change = None
                if body_bytes and body_bytes <= 16384 and 'application/json' in request.headers.get('content-type',''):
                    try:
                        change = redact_change(json.loads(bytes(body_preview), parse_float=str, parse_constant=lambda value: '[non-finite number]'))
                    except (ValueError, UnicodeDecodeError):
                        change = '[unparseable request body]'
                async with asyncio.timeout(5):
                    async with request.app.state.finance.pool.acquire() as connection:
                        await append_event(connection, session, 'REQUEST_FINISHED', request_id,
                            scope['method'], path[:1000], status, {'outcome': 'HTTP_RESPONSE',
                            'mutation_requested': scope['method'] not in {'GET','HEAD','OPTIONS'},
                            'body_sha256': body_digest.hexdigest(), 'body_bytes_consumed': body_bytes,
                            'requested_change': change, 'outcome_is_database_commit_proof': False})
            except Exception as error:
                logger.error('Assistance outcome audit pending request_id=%s error_type=%s', request_id, type(error).__name__)
