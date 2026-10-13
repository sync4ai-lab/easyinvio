"""Actual sandbox DB and import path; synthetic provider HTTP; all writes rolled back."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx
from fastapi import FastAPI

import main
from backend.ecommerce_sync import EcommerceService
from backend.store_connections import build_router, resolve_connector
from backend.dispatch_workspace import poll_shopify
from backend.dashboard_portal import build_router as dashboard_router


async def run():
    settings = main.Settings()
    assert settings.database_environment == 'SANDBOX'
    connection = await asyncpg.connect(settings.database_url.get_secret_value(),
        ssl=main.database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict))
    transaction = connection.transaction(); await transaction.start()
    class Pool:
        @asynccontextmanager
        async def acquire(self): yield connection
    try:
        tenant = await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
        user = await connection.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active", tenant)
        assert tenant and user
        context = SimpleNamespace(tenant_id=tenant, user_id=user, role='OWNER')
        store = await connection.fetchval("INSERT INTO public.ecommerce_stores(tenant_id,platform,display_name) VALUES($1,'SHOPIFY','ROLLBACK Store probe') RETURNING id", tenant)
        def provider(request):
            assert str(request.url) == 'https://qa-shop.myshopify.com/admin/api/2026-10/graphql.json'
            return httpx.Response(200, json={'data': {'orders': {'pageInfo': {'hasNextPage': False}, 'nodes': [{
                'id':'gid://shopify/Order/100123', 'name':'QA-STORE-100123', 'currencyCode':'GBP', 'cancelledAt':None,
                'displayFulfillmentStatus':'UNFULFILLED', 'shippingAddress':{'name':'Test Recipient','address1':'1 Test Road','city':'London','zip':'SW1A 1AA','countryCodeV2':'GB'},
                'lineItems': {'pageInfo': {'hasNextPage': False}, 'nodes':[{'title':'Test item','sku':'TEE','quantity':2,'unfulfilledQuantity':2,'requiresShipping':True,'originalUnitPriceSet':{'shopMoney':{'amount':'10.00','currencyCode':'GBP'}}}]}
            }]}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            service = EcommerceService(Pool(), client=client, credential_keys=settings.credential_keys)
            app = FastAPI(); app.state.ecommerce = service; app.state.finance = service
            async def authenticate(): return context
            app.include_router(build_router(authenticate)); app.include_router(dashboard_router(authenticate))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as browser:
                result = await browser.put('/api/v1/workspace/stores/'+str(store)+'/connection', json={
                    'shop_domain':'qa-shop.myshopify.com','access_token':'synthetic-probe-token', 'sku_unit_grams':{'TEE':'200'}})
                assert result.status_code == 200, result.text
                registry = await browser.get('/api/v1/workspace/stores')
                assert registry.status_code == 200, registry.text
                assert next(s for s in registry.json()['stores'] if s['id'] == str(store))['connection_saved']
            config = await resolve_connector(service, store)
            first = await poll_shopify(service, context, store, config)
            second = await poll_shopify(service, context, store, config)
            assert first['results'][0]['status'] == 'PENDING_IMPORT', first
            assert not first['results'][0]['replayed'] and second['results'][0]['replayed']
            row = await connection.fetchrow('SELECT status,parcel_weight_kg,store_order_id FROM public.shipments WHERE tenant_id=$1 AND ecommerce_store_id=$2', tenant, store)
            assert str(row['parcel_weight_kg']) == '0.400' and row['store_order_id'] == '100123'
            assert await connection.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid='public.workspace_store_connections'::regclass")
            assert not await connection.fetchval("SELECT has_table_privilege('authenticated','public.workspace_store_connections','SELECT')")
        print('Actual sandbox encrypted connection, persisted order and duplicate replay passed; rolled back; no external merchant calls.')
    finally:
        await transaction.rollback(); await connection.close()

asyncio.run(run())
