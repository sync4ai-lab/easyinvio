"""Real SQL rollout/decryption/security probe; all synthetic changes roll back."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4
import asyncpg
from fastapi import HTTPException
import main
from backend.admin_portal import AdminService, PlatformOwner, TenantCreate
from backend.platform_carriers import PlatformConnection, save


async def run():
    settings=main.Settings()
    assert settings.database_environment=='SANDBOX'
    actor=PlatformOwner(UUID('117d268d-b034-4a74-ad4d-050813bf67ac'))
    assert actor.user_id in settings.platform_admin_user_ids
    c=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=main.database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield c
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings,finance=SimpleNamespace(pool=Pool()))))
    outer=c.transaction();await outer.start()
    try:
        body=PlatformConnection(account_name='ROLLBACK platform probe',aggregator='EASYPOST',api_base_url='https://api.easypost.com/v2',environment='TEST',api_key='synthetic-no-carrier-call',is_active=True)
        created=await save(body,request,actor)
        eligible=await c.fetchval('SELECT count(*) FROM public.tenants WHERE is_sandbox')
        assert await c.fetchval('SELECT count(*) FROM public.carrier_accounts WHERE platform_connection_id=$1',body.request_id)==eligible
        assert (await save(body,request,actor))['id']==created['id']
        tenant=await AdminService(Pool()).create_tenant(TenantCreate(billing_plan='PREPAID_WALLET',is_sandbox=True,company_profile={'company_name':'ROLLBACK platform client','contact_name':'Test','billing_email':'platform@example.invalid','address_line1':'1 Fixture Way','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}),actor)
        linked=await c.fetchrow('SELECT * FROM public.carrier_accounts WHERE tenant_id=$1 AND platform_connection_id=$2',tenant.tenant_id,body.request_id)
        assert linked and linked['is_active']
        row=dict(linked)
        for key in ['id','tenant_id','platform_connection_id']:row[key]=str(row[key])
        row['credentials_ciphertext']='\\x'+bytes(row['credentials_ciphertext']).hex()
        repo=main.SupabaseRepository(None,settings)
        async def select(*args,**kwargs):return [row]
        repo.select=select
        context=main.TenantContext(tenant.tenant_id,actor.user_id,'OWNER','')
        accounts=await repo.accounts(context)
        assert accounts[0].api_key=='synthetic-no-carrier-call'
        assert accounts[0].platform_connection_id==body.request_id
        row['platform_connection_id']=str(uuid4())
        try:await repo.accounts(context)
        except HTTPException as exc:assert exc.status_code==503
        else:raise AssertionError('Mismatched platform envelope accepted')
        row['platform_connection_id']=str(body.request_id)
        try:await repo.accounts(main.TenantContext(uuid4(),actor.user_id,'OWNER',''))
        except HTTPException as exc:assert exc.status_code==503
        else:raise AssertionError('Cross-tenant projection accepted')
        await c.execute('UPDATE public.platform_carrier_connections SET is_active=false WHERE id=$1',body.request_id)
        assert await c.fetchval('SELECT count(*) FROM public.carrier_accounts WHERE platform_connection_id=$1 AND is_active',body.request_id)==0
        try:
            async with c.transaction():
                await c.execute('SET LOCAL ROLE authenticated')
                await c.fetch('SELECT credentials_ciphertext FROM public.platform_carrier_connections')
        except asyncpg.InsufficientPrivilegeError:pass
        else:raise AssertionError('Browser role can read master credentials')
        print('PASS: existing/new client rollout, idempotence, shared-key rating resolution, tenant/envelope isolation, global retirement, browser secret denial. All records rolled back; zero carrier calls.')
    finally:
        await outer.rollback();await c.close()

if __name__=='__main__':asyncio.run(run())
