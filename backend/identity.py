"""Password-verified, revocable HS256 app sessions around Supabase Auth identity."""
import hashlib
import json
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4
import httpx
import jwt
import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError

class IdentityRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def safe(request):
            try:
                response=await handler(request)
                response.headers['Cache-Control']='no-store'
                response.headers['Pragma']='no-cache'
                return response
            except asyncpg.PostgresError:
                raise HTTPException(503,'Identity storage is temporarily unavailable') from None
            except RequestValidationError as exc:
                raise HTTPException(422,[{'loc':e['loc'],'msg':e['msg'],'type':e['type']} for e in exc.errors()]) from None
        return safe

router=APIRouter(prefix='/api/v1/auth',tags=['Identity'],route_class=IdentityRoute)
ISSUER='easyinvio-auth'
AUDIENCE='easyinvio-api'


class Login(BaseModel):
    model_config=ConfigDict(extra='forbid',hide_input_in_errors=True)
    email: str=Field(max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: SecretStr=Field(min_length=1,max_length=4096)


class ProfileUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    full_name: str=Field(min_length=1,max_length=200,pattern=r'^[^\x00-\x1f\x7f]+$')
    phone_e164: str | None=Field(default=None,pattern=r'^\+[1-9][0-9]{7,14}$')


async def unwrap_app_session(request: Request, token: str) -> str:
    try:
        if len(token)>16000:raise ValueError()
        if jwt.get_unverified_header(token).get('alg')!='HS256':return token
        settings=request.app.state.settings
        secret=getattr(settings,'auth_jwt_secret',SecretStr('')).get_secret_value()
        if len(secret.encode())<32:raise ValueError()
        claims=jwt.decode(token,secret,algorithms=['HS256'],issuer=ISSUER,audience=AUDIENCE,
            options={'require':['sub','user_id','role','email','jti','exp','iat','iss','aud']})
        if 'tenant_id' not in claims:raise ValueError()
        user_id=UUID(claims['sub']);identifier=UUID(claims['jti'])
        if str(user_id)!=claims['user_id']:raise ValueError()
        async with request.app.state.finance.pool.acquire() as c:
            row=await c.fetchrow("SELECT s.* FROM public.app_auth_sessions s JOIN auth.users a ON a.id=s.auth_user_id WHERE s.id=$1 AND s.auth_user_id=$2 AND s.expires_at>now() AND (a.banned_until IS NULL OR a.banned_until<now()) AND (to_jsonb(a)->>'deleted_at') IS NULL",identifier,user_id)
        if not row or (str(row['tenant_id']) if row['tenant_id'] else None)!=claims['tenant_id']:raise ValueError()
        key=settings.credential_keys[row['key_id']]
        envelope=json.loads(Fernet(key.get_secret_value().encode()).decrypt(bytes(row['provider_token'])))
        if envelope['session_id']!=str(identifier) or envelope['user_id']!=str(user_id):raise ValueError()
        request.state.app_session_claims=claims
        return envelope['access_token']
    except (jwt.PyJWTError,ValueError,KeyError,TypeError,InvalidToken):
        raise HTTPException(401,'Invalid or expired session') from None


@router.post('/token')
async def token(body: Login, request: Request):
    settings=getattr(request.app.state,'settings',None)
    if not settings or len(settings.auth_jwt_secret.get_secret_value().encode())<32 or not settings.credential_keys:
        raise HTTPException(503,'Authentication configuration is unavailable')
    email=body.email.strip().casefold()
    ip=request.client.host if request.client else 'unknown'
    buckets=[('email:'+email,10),('ip:'+ip,30)]
    async with request.app.state.finance.pool.acquire() as c:
        async with c.transaction():
            for value,limit in sorted(buckets):
                count=await c.fetchval('''INSERT INTO public.app_login_limits(bucket,attempts) VALUES($1,1)
                    ON CONFLICT(bucket) DO UPDATE SET attempts=CASE WHEN app_login_limits.window_start<now()-interval '1 minute' THEN 1 ELSE app_login_limits.attempts+1 END,
                    window_start=CASE WHEN app_login_limits.window_start<now()-interval '1 minute' THEN now() ELSE app_login_limits.window_start END RETURNING attempts''',hashlib.sha256(value.encode()).hexdigest())
                if count>limit:raise HTTPException(429,'Too many sign-in attempts; retry in a minute',headers={'Retry-After':'60'})
    try:
        async with httpx.AsyncClient(trust_env=False,timeout=15) as client:
            result=await client.post(settings.supabase_url+'/auth/v1/token?grant_type=password',
                headers={'apikey':settings.supabase_publishable_key.get_secret_value()},
                json={'email':email,'password':body.password.get_secret_value()})
            if result.status_code>=500:raise HTTPException(503,'Authentication provider is unavailable')
            if result.status_code!=200:raise HTTPException(401,'Invalid email or password')
            data=result.json();access=data['access_token']
            identity=await client.get(settings.supabase_url+'/auth/v1/user',headers={
                'apikey':settings.supabase_publishable_key.get_secret_value(),'Authorization':'Bearer '+access})
            if identity.status_code!=200:raise HTTPException(401,'Invalid authentication session')
            principal=identity.json();user_id=UUID(principal['id'])
            if principal.get('email','').casefold()!=email:raise HTTPException(401,'Identity mismatch')
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        raise HTTPException(503,'Authentication provider is unavailable') from None
    async with request.app.state.finance.pool.acquire() as c:
        members=await c.fetch('''SELECT u.tenant_id,u.role FROM public.users u JOIN public.tenants t USING(tenant_id)
            WHERE u.auth_user_id=$1 AND u.is_active AND t.workspace_status='ACTIVE' LIMIT 2''',user_id)
        admin=user_id in settings.platform_admin_user_ids
        if len(members)>1 or (not admin and len(members)!=1):raise HTTPException(403,'An active workspace registration is required')
        tenant_id=members[0]['tenant_id'] if members else None
        role='SUPER_ADMIN' if admin else members[0]['role']
        now=int(time.time());expires=min(now+900,int(data.get('expires_at',now+int(data.get('expires_in',3600)))))
        if expires<=now:raise HTTPException(401,'Authentication session expired')
        identifier=uuid4();key_id=sorted(settings.credential_keys)[0]
        cipher=Fernet(settings.credential_keys[key_id].get_secret_value().encode()).encrypt(json.dumps({
            'session_id':str(identifier),'user_id':str(user_id),'access_token':access}).encode())
        await c.execute('DELETE FROM public.app_auth_sessions WHERE expires_at<now()')
        await c.execute("DELETE FROM public.app_login_limits WHERE window_start<now()-interval '1 day'")
        await c.execute('INSERT INTO public.app_auth_sessions(id,auth_user_id,tenant_id,provider_token,key_id,expires_at) VALUES($1,$2,$3,$4,$5,$6)',identifier,user_id,tenant_id,cipher,key_id,datetime.fromtimestamp(expires,timezone.utc))
    claims={'iss':ISSUER,'aud':AUDIENCE,'sub':str(user_id),'user_id':str(user_id),
        'tenant_id':str(tenant_id) if tenant_id else None,'role':role,'email':email,
        'iat':now,'exp':expires,'jti':str(identifier)}
    return {'access_token':jwt.encode(claims,settings.auth_jwt_secret.get_secret_value(),algorithm='HS256'),
            'token_type':'bearer','expires_at':expires,'user':{'id':str(user_id),'email':email}}


async def current_identity(request):
    from fastapi.security import HTTPBearer
    from backend.admin_portal import authenticate_platform_owner
    credentials=await HTTPBearer(auto_error=False)(request)
    try:
        actor=await authenticate_platform_owner(request,credentials)
        return actor.user_id,'SUPER_ADMIN'
    except HTTPException as exc:
        if exc.status_code!=403:raise
    from main import authenticate
    context=await authenticate(request,credentials)
    return context.user_id,context.role


@router.get('/me')
async def me(request: Request):
    user_id,role=await current_identity(request)
    async with request.app.state.finance.pool.acquire() as c:
        row=await c.fetchrow('''SELECT a.email,coalesce(p.full_name,(SELECT u.full_name FROM public.users u WHERE u.auth_user_id=a.id LIMIT 1),'') AS full_name,p.phone_e164
            FROM auth.users a LEFT JOIN public.app_user_profiles p ON p.auth_user_id=a.id WHERE a.id=$1''',user_id)
    if not row:raise HTTPException(401,'Identity unavailable')
    return {'user_id':str(user_id),'role':role,**dict(row)}


@router.patch('/me')
async def update_me(body: ProfileUpdate,request: Request):
    user_id,_=await current_identity(request)
    if not body.full_name.strip():raise HTTPException(422,'Enter your full name')
    async with request.app.state.finance.pool.acquire() as c:
        async with c.transaction():
            await c.execute('''INSERT INTO public.app_user_profiles(auth_user_id,full_name,phone_e164) VALUES($1,$2,$3)
                ON CONFLICT(auth_user_id) DO UPDATE SET full_name=excluded.full_name,phone_e164=excluded.phone_e164,updated_at=now()''',user_id,body.full_name.strip(),body.phone_e164)
            await c.execute('UPDATE public.users SET full_name=$2 WHERE auth_user_id=$1',user_id,body.full_name.strip())
    return {'updated':True,'notice':'Contact details saved. Verified WhatsApp pairing is unchanged.'}


@router.post('/logout')
async def logout(request: Request):
    user_id,_=await current_identity(request)
    claims=getattr(request.state,'app_session_claims',None)
    if claims:
        async with request.app.state.finance.pool.acquire() as c:
            await c.execute('DELETE FROM public.app_auth_sessions WHERE id=$1 AND auth_user_id=$2',UUID(claims['jti']),user_id)
    return {'logged_out':True}

class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    email: str = Field(max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class ResetPassword(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    token_hash: SecretStr = Field(min_length=20, max_length=1024)
    password: SecretStr = Field(min_length=12, max_length=128)


async def recovery_limit(request: Request):
    """A separate IP bucket protects email delivery and token verification."""
    ip = request.client.host if request.client else 'unknown'
    bucket = hashlib.sha256(('recovery:' + ip).encode()).hexdigest()
    async with request.app.state.finance.pool.acquire() as connection:
        count = await connection.fetchval('''INSERT INTO public.app_login_limits(bucket,attempts) VALUES($1,1)
            ON CONFLICT(bucket) DO UPDATE SET
            attempts=CASE WHEN app_login_limits.window_start<now()-interval '15 minutes' THEN 1 ELSE app_login_limits.attempts+1 END,
            window_start=CASE WHEN app_login_limits.window_start<now()-interval '15 minutes' THEN now() ELSE app_login_limits.window_start END
            RETURNING attempts''', bucket)
    if count > 10:
        raise HTTPException(429, 'Too many recovery attempts. Try again later.', headers={'Retry-After': '900'})


@router.post('/forgot-password')
async def forgot_password(body: RecoveryRequest, request: Request):
    from urllib.parse import urlsplit
    await recovery_limit(request)
    settings = request.app.state.settings
    redirect = settings.auth_recovery_redirect_url
    parsed = urlsplit(redirect)
    if parsed.username or parsed.password or parsed.fragment or not parsed.netloc or (
        parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1'))
    ):
        raise HTTPException(503, 'Password recovery is not configured')
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
            # Supabase deliberately does not reveal whether an account exists.
            response = await client.post(settings.supabase_url + '/auth/v1/recover',
                params={'redirect_to': redirect},
                headers={'apikey': settings.supabase_publishable_key.get_secret_value()},
                json={'email': body.email.strip().casefold()})
            if response.status_code == 429:
                raise HTTPException(429, 'Please wait before requesting another email.', headers={'Retry-After': '60'})
            if response.status_code >= 500:
                raise HTTPException(503, 'Email delivery is temporarily unavailable')
            if response.status_code in (401, 403):
                raise HTTPException(503, 'Password recovery provider configuration is unavailable')
    except httpx.HTTPError:
        raise HTTPException(503, 'Email delivery is temporarily unavailable') from None
    return {'message': 'If this email is registered, a password reset link will arrive shortly. Check your spam folder.'}


@router.post('/reset-password')
async def reset_password(body: ResetPassword, request: Request):
    await recovery_limit(request)
    settings = request.app.state.settings
    headers = {'apikey': settings.supabase_publishable_key.get_secret_value()}
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
            verified = await client.post(settings.supabase_url + '/auth/v1/verify', headers=headers,
                json={'token_hash': body.token_hash.get_secret_value(), 'type': 'recovery'})
            if verified.status_code != 200:
                raise HTTPException(400, 'This reset link is invalid or expired. Request a new link.')
            session = verified.json()
            access = session['access_token']
            user_id = UUID(session['user']['id'])
            headers['Authorization'] = 'Bearer ' + access
            updated = await client.put(settings.supabase_url + '/auth/v1/user', headers=headers,
                json={'password': body.password.get_secret_value()})
            if updated.status_code != 200:
                raise HTTPException(400, 'Password update was rejected. Use a strong, different password and request a new link.')
            # Recovery never grants an app session; revoke all prior app sessions.
            async with request.app.state.finance.pool.acquire() as connection:
                await connection.execute('DELETE FROM public.app_auth_sessions WHERE auth_user_id=$1', user_id)
            signed_out = await client.post(settings.supabase_url + '/auth/v1/logout',
                params={'scope': 'global'}, headers=headers)
            if signed_out.status_code not in (200, 204):
                raise HTTPException(503, 'Password changed and app sessions revoked. Provider sign-out could not be confirmed; contact support.')
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(503, 'Recovery is temporarily unavailable. Request a new link if necessary.') from None
    return {'message': 'Password updated. Sign in with your new password.'}
