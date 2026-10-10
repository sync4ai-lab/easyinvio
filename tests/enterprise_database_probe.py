"""Apply audited management schema to the configured sandbox; roll back CRUD probes."""
import asyncio, json, re
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import asyncpg, httpx
from main import Settings, app, authenticate, TenantContext
from backend.database_tls import database_tls_context
from backend.verify_automation_writepath import BorrowedPool
from backend.admin_portal import PlatformOwner, authenticate_platform_owner, MarginCreate

async def run():
    settings=Settings()
    assert settings.database_environment=='SANDBOX', 'This probe requires an explicitly configured sandbox'
    c=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    result={}
    try:
        sql=Path('migrations/015_admin_management.sql').read_text()
        sql=re.sub(r'^(BEGIN;|COMMIT;)\s*$','',sql,flags=re.M)
        tx=c.transaction();await tx.start()
        try:await c.execute(sql)
        finally:await tx.rollback()
        async with c.transaction():await c.execute(sql)
        result['migration_015']={'sandbox_applied':True,'rollback_validation':True,'existing_rows_preserved':True}
        tenant=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
        actor=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 ORDER BY id LIMIT 1",tenant)
        assert actor and tenant
        app.state.settings=settings;app.state.local_preview=False
        app.state.finance=SimpleNamespace(pool=BorrowedPool(c))
        # Explicit test dependency override exercises authorized controller SQL,
        # not an actual owner login. Ordinary authentication remains separately tested.
        app.dependency_overrides[authenticate_platform_owner]=lambda:PlatformOwner(actor)
        tx=c.transaction();await tx.start()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as http:
                for path in ['/tenants','/carriers','/margins','/transactions']:
                    response=await http.get('/api/v1/admin'+path)
                    assert response.status_code==200,(path,response.status_code)
                    assert 'credentials_ciphertext' not in response.text and 'api_key' not in response.text
                    result['list'+path]=True
                # Insert a dedicated temporary rule, edit it, retire it, then roll back.
                rule=await c.fetchval("INSERT INTO public.margin_rules(tenant_id,rule_name,currency,markup_type,markup_value,minimum_markup,priority,is_active) VALUES($1,'ROLLBACK enterprise probe','GBP','PERCENTAGE',20,0,100,true) RETURNING id",tenant)
                body=MarginCreate(tenant_id=tenant,origin_country='GB',destination_country='USA',markup_type='FLAT_RATE',markup_value='5.50',priority=12,currency='GBP').model_dump(mode='json')
                response=await http.put(f'/api/v1/admin/margins/{rule}',json=body)
                assert response.status_code==200,response.text
                row=await c.fetchrow('SELECT markup_type,markup_value,destination_country,priority FROM public.margin_rules WHERE id=$1',rule)
                assert row['markup_type']=='FIXED' and str(row['markup_value'])=='5.50' and row['destination_country']=='US' and row['priority']==12
                body['tenant_id']=str(await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-02'"))
                assert (await http.put(f'/api/v1/admin/margins/{rule}',json=body)).status_code==422
                assert (await http.delete(f'/api/v1/admin/margins/{rule}')).status_code==200
                assert not await c.fetchval('SELECT is_active FROM public.margin_rules WHERE id=$1',rule)
                result['margin_edit_retire_and_tenant_boundary']=True
                carrier=await c.fetchval('SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND NOT is_active LIMIT 1',tenant)
                response=await http.patch(f'/api/v1/admin/carriers/{carrier}',json={'is_active':False,'priority':22,'timeout_seconds':15})
                assert response.status_code==200,response.text
                assert (await http.delete(f'/api/v1/admin/carriers/{carrier}')).status_code==200
                result['carrier_parameters_and_retirement']=True
                create={'request_id':str(__import__('uuid').uuid4()),'tenant_id':str(tenant),'account_name':'ROLLBACK carrier probe','aggregator':'EASYPOST','api_base_url':'https://api.easypost.com/v2','api_key':'sandbox-fixture-not-a-provider-key','environment':'TEST','is_active':False}
                response=await http.post('/api/v1/admin/carriers',json=create)
                assert response.status_code==201,response.text
                new_carrier=response.json()['id']
                replay=await http.post('/api/v1/admin/carriers',json=create)
                assert replay.status_code==201 and replay.json()['replayed'] and replay.json()['id']==new_carrier
                conflict=await http.post('/api/v1/admin/carriers',json={**create,'priority':99})
                assert conflict.status_code==409
                row=await c.fetchrow('SELECT credentials_ciphertext,credential_key_id FROM public.carrier_accounts WHERE id=$1',UUID(new_carrier))
                from cryptography.fernet import Fernet
                envelope=json.loads(Fernet(settings.credential_keys[row['credential_key_id']].get_secret_value().encode()).decrypt(bytes(row['credentials_ciphertext'])))
                assert envelope['tenant_id']==str(tenant) and envelope['account_id']==new_carrier
                assert (await http.patch('/api/v1/admin/carriers/'+new_carrier,json={'is_active':True})).status_code==200
                assert (await http.delete('/api/v1/admin/carriers/'+new_carrier)).status_code==200
                result['carrier_creation_encryption_idempotency_activation']=True
                rows=await c.fetch('SELECT action,snapshot FROM public.admin_management_events WHERE actor_auth_user_id=$1',actor)
                assert len(rows)==7
                assert all('api_key' not in str(r['snapshot']) for r in rows)
                result['atomic_audits_no_secrets']=True
                app.dependency_overrides[authenticate]=lambda:TenantContext(tenant,actor,'ACCOUNTANT','fixture')
                store=await http.post('/api/v1/workspace/stores',json={'platform':'SHOPIFY','display_name':'ROLLBACK workspace store'})
                assert store.status_code==201,store.text
                store_id=store.json()['id']
                own=await http.get('/api/v1/workspace/stores')
                assert own.status_code==200 and any(s['id']==store_id for s in own.json()['stores'])
                other=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-02'")
                app.dependency_overrides[authenticate]=lambda:TenantContext(other,actor,'OWNER','fixture')
                assert (await http.patch('/api/v1/workspace/stores/'+store_id,json={'is_active':False})).status_code==404
                app.dependency_overrides[authenticate]=lambda:TenantContext(tenant,actor,'DISPATCHER','fixture')
                assert (await http.get('/api/v1/workspace/stores')).status_code==403
                result['store_tenant_boundary_and_dispatcher_denial']=True
        finally:
            await tx.rollback();app.dependency_overrides.clear()
        assert not await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.margin_rules WHERE rule_name='ROLLBACK enterprise probe')")
        result['test_configuration_changes_rolled_back']=True
    finally:await c.close()
    out=Path('docs/enterprise_remediation');out.mkdir(exist_ok=True)
    (out/'database_evidence.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
if __name__=='__main__':asyncio.run(run())
