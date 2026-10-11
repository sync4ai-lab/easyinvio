"""Real encrypted session/revocation probe, with no provider token or password calls."""
import asyncio,json,time
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from types import SimpleNamespace
from uuid import UUID,uuid4
import asyncpg,jwt
from cryptography.fernet import Fernet
from fastapi import HTTPException
from main import Settings,database_tls_context
from backend.identity import unwrap_app_session,ISSUER,AUDIENCE

async def run():
    settings=Settings();assert settings.database_environment=='SANDBOX'
    user=UUID('117d268d-b034-4a74-ad4d-050813bf67ac');identifier=uuid4();now=int(time.time());key_id=sorted(settings.credential_keys)[0]
    cipher=Fernet(settings.credential_keys[key_id].get_secret_value().encode()).encrypt(json.dumps({'session_id':str(identifier),'user_id':str(user),'access_token':'synthetic-provider-token-not-for-network-use'}).encode())
    c=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield c
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings,finance=SimpleNamespace(pool=Pool()))),state=SimpleNamespace())
    outer=c.transaction();await outer.start()
    try:
        await c.execute('INSERT INTO public.app_auth_sessions(id,auth_user_id,tenant_id,provider_token,key_id,expires_at) VALUES($1,$2,NULL,$3,$4,$5)',identifier,user,cipher,key_id,datetime.fromtimestamp(now+300,timezone.utc))
        claims={'iss':ISSUER,'aud':AUDIENCE,'sub':str(user),'user_id':str(user),'tenant_id':None,'role':'SUPER_ADMIN','email':'synthetic@example.invalid','iat':now,'exp':now+300,'jti':str(identifier)}
        token=jwt.encode(claims,settings.auth_jwt_secret.get_secret_value(),algorithm='HS256')
        assert await unwrap_app_session(request,token)=='synthetic-provider-token-not-for-network-use'
        await c.execute('DELETE FROM public.app_auth_sessions WHERE id=$1',identifier)
        try:await unwrap_app_session(request,token)
        except HTTPException as exc:assert exc.status_code==401
        else:raise AssertionError('Revoked token accepted')
        try:
            async with c.transaction():
                await c.execute('SET LOCAL ROLE authenticated');await c.fetch('SELECT provider_token FROM public.app_auth_sessions')
        except asyncpg.InsufficientPrivilegeError:pass
        else:raise AssertionError('Browser role can read encrypted provider sessions')
        print('PASS: real encrypted session storage, tenantless-owner envelope, JWT resolution, revocation, private-table grants. Rolled back; no real login/password/provider calls.')
    finally:await outer.rollback();await c.close()

if __name__=='__main__':asyncio.run(run())
