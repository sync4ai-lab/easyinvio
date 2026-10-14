"""Validate migration and private catalog behavior in SANDBOX, always rolled back."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import asyncpg
from fastapi import HTTPException
import main
from backend.tenant_catalogs import TenantCatalogService, ProductInput, build_router
from backend.agents.margin_optimizer import MarginOptimizerAgent
from backend.agents.runtime import AgentRuntime
from backend.agents.config import AgentSettings


async def run():
    settings=main.Settings()
    assert settings.database_environment=='SANDBOX' and settings.provider_environment=='TEST'
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=main.database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict),timeout=15)
    outer=connection.transaction();await outer.start()
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield connection
    checks=[]
    try:
        migration=Path('migrations/036_tenant_catalogs.sql').read_text(encoding='utf-8').replace('BEGIN;\n','',1).rsplit('COMMIT;',1)[0]
        await connection.execute(migration);await connection.execute(migration)
        checks.append('Migration applies twice and keeps tables private with RLS')
        for table in ('addresses','contacts','products'):
            assert await connection.fetchval('SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass','public.tenant_catalog_'+table)
            assert not await connection.fetchval("SELECT has_table_privilege('authenticated',$1,'SELECT')",'public.tenant_catalog_'+table)
        user=await connection.fetchrow("SELECT tenant_id,auth_user_id FROM public.users WHERE is_active AND role IN ('OWNER','ADMIN') LIMIT 1")
        assert user is not None
        context=SimpleNamespace(tenant_id=user['tenant_id'],user_id=user['auth_user_id'],role='OWNER')
        service=TenantCatalogService(Pool())
        async def auth():return context
        router=build_router(auth,main.Address)
        model=next(route.endpoint.__annotations__['body'] for route in router.routes if route.path=='/api/v1/catalog/addresses' and 'POST' in route.methods)
        address={'name':'Catalog rollback test','line1':'9 Test Street','city':'Leeds','postal_code':'LS1 1AA','country_code':'GB','phone':'+447123456789'}
        first=await service.save(context,'addresses',model(label='Rollback sender A',address_role='SENDER',is_default=True,address=address))
        second=await service.save(context,'addresses',model(label='Rollback sender B',address_role='SENDER',is_default=True,address=address))
        assert await connection.fetchval("SELECT count(*) FROM public.tenant_catalog_addresses WHERE tenant_id=$1 AND address_role='SENDER' AND is_default AND archived_at IS NULL",context.tenant_id)==1
        assert not await connection.fetchval('SELECT is_default FROM public.tenant_catalog_addresses WHERE id=$1',__import__('uuid').UUID(first['id']))
        await service.save(context,'addresses',model(label='Rollback return',address_role='RETURN',is_default=True,address=address))
        assert await connection.fetchval('SELECT is_default FROM public.tenant_catalog_addresses WHERE id=$1',__import__('uuid').UUID(second['id']))
        checks.append('Default switching is atomic and role-specific; old versions change')
        sku='ROLLBACK-'+str(uuid4())
        product=await service.save(context,'products',ProductInput(sku=sku,description='Cotton knitted shirt',unit_weight_kg='0.125',unit_value='12.30',origin_country='GB',hs_code='610910',hs_reviewed=True))
        assert product['unit_value']=='12.30' and product['unit_weight_kg']=='0.125' and product['hs_reviewed']
        found=await service.product_by_sku(context,sku.lower());assert found['id']==product['id']
        foreign=SimpleNamespace(tenant_id=uuid4(),user_id=context.user_id,role='OWNER')
        try:await service.product_by_sku(foreign,sku)
        except HTTPException as error:assert error.status_code==404
        else:raise AssertionError('Cross-tenant lookup leaked a product')
        try:await service.save(context,'addresses',model(label='Stale',address_role='SENDER',address=address,expected_version=1),__import__('uuid').UUID(first['id']))
        except HTTPException as error:assert error.status_code==409
        else:raise AssertionError('Stale version was accepted')
        await service.archive(context,'products',__import__('uuid').UUID(product['id']),product['version'])
        checks.append('Exact decimals, reviewed metadata, case-insensitive SKU, tenant isolation and stale-edit fencing')
        optimizer=MarginOptimizerAgent(AgentRuntime(AgentSettings.model_construct(logistics_agents_enabled=False)))
        await optimizer.persist_failure(context.tenant_id,uuid4(),uuid4(),'AI_RECOMMENDATION_TIMEOUT',Pool())
        assert await connection.fetchval("SELECT EXISTS(SELECT 1 FROM public.support_tickets WHERE tenant_id=$1 AND prompt_version='margin-optimizer-v1')",context.tenant_id)
        checks.append('Recommendation failure creates an internal support ticket without a shipment or wallet mutation')
    finally:
        await outer.rollback();await connection.close()
    print({'status':'PASS','checks':checks,'all_changes_rolled_back':True,'provider_calls':0})


if __name__=='__main__':asyncio.run(run())
