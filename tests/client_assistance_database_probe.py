"""Validate migration 037 and assistance attribution in SANDBOX; always rollback."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import asyncpg
from fastapi import FastAPI, HTTPException, Request
import main
from backend import client_assistance as support


async def run():
    settings=main.Settings()
    assert settings.database_environment=='SANDBOX' and settings.provider_environment=='TEST'
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=main.database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict),timeout=15)
    outer=connection.transaction();await outer.start()
    class Pool:
        @asynccontextmanager
        async def acquire(self): yield connection
    try:
        source=Path('migrations/037_admin_client_assistance.sql').read_text(encoding='utf-8').replace('BEGIN;\n','',1).rsplit('COMMIT;',1)[0]
        await connection.execute(source);await connection.execute(source)
        tenant=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE is_sandbox AND workspace_status='ACTIVE' ORDER BY tenant_id LIMIT 1")
        actor=await connection.fetchval('SELECT id FROM auth.users WHERE banned_until IS NULL ORDER BY created_at LIMIT 1')
        assert tenant and actor
        app=FastAPI();app.state.finance=SimpleNamespace(pool=Pool())
        request=Request({'type':'http','method':'POST','path':'/api/v1/admin/client-assistance/sessions',
            'headers':[(b'authorization',b'Bearer rollback-assistance-probe')],'query_string':b'','app':app})
        request.state.platform_auth_claims={'exp':int(datetime.now(timezone.utc).timestamp())+600}
        request.state.app_session_claims={'exp':int(datetime.now(timezone.utc).timestamp())+300}
        owner=SimpleNamespace(user_id=actor)
        result=await support.start(support.StartAssistance(tenant_id=tenant,reason='Rollback-only attribution verification'),request,owner)
        identifier=UUID(result['session_id'])
        session=await connection.fetchrow('SELECT * FROM public.admin_client_assistance_sessions WHERE id=$1',identifier)
        assert session['actor_auth_user_id']==actor and session['tenant_id']==tenant
        assert session['expires_at'].timestamp()<=request.state.app_session_claims['exp']
        assert await connection.fetchval('SELECT auth_user_id FROM public.users WHERE id=$1',session['operator_membership_id'])==actor
        scope={'type':'http','method':'GET','path':'/api/v1/profile','headers':[(b'authorization',b'Bearer rollback-assistance-probe'),(b'x-easyinvio-assistance',str(identifier).encode())],'query_string':b'','app':app}
        with patch.object(support,'authenticate_platform_owner',AsyncMock(return_value=owner)):
            resolved=await support.resolve_assistance(Request(scope));assert resolved['tenant_id']==tenant
        context=main.TenantContext(tenant,actor,'OWNER','',identifier)
        assert await support.operator_member_id(connection,context)==session['operator_membership_id']
        try:
            async with connection.transaction():
                await connection.execute('UPDATE public.admin_client_assistance_events SET detail=\'{}\' WHERE session_id=$1',identifier)
        except asyncpg.InsufficientPrivilegeError: pass
        else: raise AssertionError('Audit history was mutable')
        for table in ('admin_client_assistance_sessions','admin_client_assistance_events'):
            assert await connection.fetchval('SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass','public.'+table)
            assert not await connection.fetchval("SELECT has_table_privilege('authenticated',$1,'SELECT')",'public.'+table)
        await support.stop(identifier,request,owner);await support.stop(identifier,request,owner)
        assert await connection.fetchval("SELECT count(*) FROM public.admin_client_assistance_events WHERE session_id=$1 AND event_type='SESSION_ENDED'",identifier)==1
        with patch.object(support,'authenticate_platform_owner',AsyncMock(return_value=owner)):
            try: await support.resolve_assistance(Request(scope))
            except HTTPException as error: assert error.status_code==401
            else: raise AssertionError('Revoked session remained usable')
        print('PASS: migration applies twice; operator attribution; parent keys; private RLS; append-only audit; idempotent revocation; revoked session rejection')
    finally:
        await outer.rollback();await connection.close()
        print('ROLLBACK: no migration, support sessions, memberships or audit rows persisted')


if __name__=='__main__': asyncio.run(run())
