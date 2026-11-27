"""Migration and tenancy checks against explicitly disposable in-memory PGlite."""
import json
from types import SimpleNamespace
from uuid import uuid4
import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from test_tracking_workspace_postgres import world,ROOT
from backend.store_returns_portal import build_router
from backend.ecommerce_sync import EcommerceService

async def setup(w):
    await w.db.command('''CREATE TABLE public.ecommerce_stores(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,
        platform text NOT NULL CHECK(platform IN ('SHOPIFY','WOOCOMMERCE','AMAZON')),display_name text NOT NULL,
        is_active boolean NOT NULL DEFAULT true,UNIQUE(tenant_id,id));
        ALTER TABLE public.tenants ADD COLUMN billing_status text DEFAULT 'ACTIVE';
        ALTER TABLE public.shipments ADD COLUMN currency text DEFAULT 'GBP',ADD COLUMN recipient_address jsonb DEFAULT '{}',
          ADD COLUMN store_fulfillment_status text;
        DROP TABLE public.ecommerce_tracking_outbox;
        CREATE TABLE public.ecommerce_tracking_outbox(id uuid PRIMARY KEY,tenant_id uuid,shipment_id uuid,store_id uuid,
          store_order_id text,payload jsonb,status text DEFAULT 'PENDING',attempts integer DEFAULT 0,
          tracking_lifecycle_type text DEFAULT 'FORWARD_SHIPMENT',store_sync_error_code text,response jsonb,created_at timestamptz DEFAULT now(),delivered_at timestamptz);
    ''',mode='exec')
    await w.db.command((ROOT/'migrations/057_universal_store_integrations.sql').read_text(encoding='utf-8'),mode='exec')
    stores=[uuid4(),uuid4()]
    for i in range(2):
        await w.db.execute("INSERT INTO public.ecommerce_stores(id,tenant_id,platform,display_name,store_slug,return_policy,return_policy_authorized_by) VALUES($1,$2,'CUSTOM_WEBSITE','Fixture retailer',$3,$4::jsonb,$5)",stores[i],w.tenants[i],f'fixture-shop-{i}',json.dumps({'enabled':True,'maximum_price':'10.00'}),w.actors[i])
        await w.db.execute("UPDATE public.shipments SET ecommerce_store_id=$2,status='DELIVERED',recipient_address=$3::jsonb,logistics_metadata=$4::jsonb WHERE tenant_id=$1",w.tenants[i],stores[i],json.dumps({'postal_code':'LS12 6EJ','email':'shopper@example.test'}),json.dumps({'automation_order':{'origin':{'country_code':'GB'},'destination':{'country_code':'GB'},'items':[{'description':f'Tenant {i} shirt','quantity':1}]}}))
        await w.db.execute("INSERT INTO public.tracking_events(tenant_id,shipment_id,integration_key_id,event_id,body_sha256,status,occurred_at,response) VALUES($1,$2,'fixture','delivered','fixture','DELIVERED',now(),'{}')",w.tenants[i],w.shipments[i])
    return stores

@pytest.mark.asyncio
async def test_migration_portal_real_sql_scope_and_verification(world):
    w=world;stores=await setup(w)
    app=FastAPI();app.state.ecommerce=SimpleNamespace(pool=w.db)
    async def actor():return SimpleNamespace(tenant_id=w.tenants[0],user_id=w.actors[0],role='OWNER')
    app.include_router(build_router(actor))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://fixture.test') as client:
        denied=await client.post('/api/v1/public/store-returns/fixture-shop-0/verify',json={'order_reference':'ORDER-1','verification_value':'LS12 6EJ'})
        assert denied.status_code==404 and 'Tenant 1' not in denied.text
        wrong=await client.post('/api/v1/public/store-returns/fixture-shop-0/verify',json={'order_reference':'ORDER-0','verification_value':'wrong@example.test'})
        assert wrong.status_code==404
        valid=await client.post('/api/v1/public/store-returns/fixture-shop-0/verify',json={'order_reference':'ORDER-0','verification_value':'ls126ej'})
        assert valid.status_code==200,valid.text
        assert valid.json()['items']==[{'description':'Tenant 0 shirt','quantity':1}]
        assert valid.headers['cache-control']=='no-store'
        assert await w.db.fetchval('SELECT count(*) FROM public.store_return_sessions WHERE tenant_id=$1',w.tenants[0])==1
        assert await w.db.fetchval('SELECT count(*) FROM public.store_return_sessions WHERE tenant_id=$1',w.tenants[1])==0
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await w.db.execute('INSERT INTO public.store_return_sessions(id,tenant_id,store_id,shipment_id,request_id,token_sha256,policy_sha256) VALUES($1,$2,$3,$4,$5,$6,$7)',uuid4(),w.tenants[0],stores[1],w.shipments[0],uuid4(),'a'*64,'b'*64)
    await w.db.command('SET ROLE anon',mode='exec')
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):await w.db.fetch('SELECT * FROM public.store_return_sessions')
    finally:await w.db.command('RESET ROLE',mode='exec')

@pytest.mark.asyncio
async def test_live_disabled_outbox_is_pending_in_real_sql(world):
    w=world;stores=await setup(w);event_id=uuid4()
    await w.db.execute("INSERT INTO public.ecommerce_tracking_outbox(id,tenant_id,shipment_id,store_id,store_order_id,payload) VALUES($1,$2,$3,$4,'1042',$5::jsonb)",event_id,w.tenants[0],w.shipments[0],stores[0],json.dumps({'tracking_number':'TRACK-1','carrier_name':'UPS'}))
    service=EcommerceService(w.db,settings=SimpleNamespace(provider_environment='LIVE'))
    await service.push(w.tenants[0],'1042','TRACK-1','UPS')
    row=await w.db.fetchrow('SELECT status,store_sync_error_code FROM public.ecommerce_tracking_outbox WHERE id=$1',event_id)
    assert row=={'status':'PENDING','store_sync_error_code':'LIVE_DELIVERY_DISABLED'}

@pytest.mark.asyncio
async def test_store_policy_spending_fence_uses_current_subscription_cap_and_window(world):
    import hashlib
    from unittest.mock import patch
    from fastapi import HTTPException
    from backend.return_review import SelectReturn
    from test_return_review_postgres import setup as return_setup
    w=world;x=await return_setup(w)
    await w.db.command('''CREATE TABLE public.ecommerce_stores(id uuid PRIMARY KEY,tenant_id uuid,platform text,
        display_name text,is_active boolean DEFAULT true,UNIQUE(tenant_id,id));
        ALTER TABLE public.tenants ADD COLUMN subscription_plan text DEFAULT 'COMMAND',
          ADD COLUMN plan_period_start timestamptz DEFAULT now();''',mode='exec')
    await w.db.command((ROOT/'migrations/057_universal_store_integrations.sql').read_text(encoding='utf-8'),mode='exec')
    store=uuid4();policy={'enabled':True,'maximum_price':'10.00'}
    await w.db.execute("INSERT INTO public.ecommerce_stores(id,tenant_id,platform,display_name,return_policy,return_policy_authorized_by) VALUES($1,$2,'CUSTOM_WEBSITE','Fixture',$3::jsonb,$4)",store,w.tenants[0],json.dumps(policy),w.actors[0])
    await w.db.execute('UPDATE public.shipments SET ecommerce_store_id=$2 WHERE id=$1',w.shipments[0],store)
    await w.db.execute("INSERT INTO public.tracking_events(tenant_id,shipment_id,integration_key_id,event_id,body_sha256,status,occurred_at,response) VALUES($1,$2,'fixture','delivered','fixture','DELIVERED',now(),'{}')",w.tenants[0],w.shipments[0])
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote):await x.service.prepare(x.context,x.body)
    digest=hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    await w.db.execute("UPDATE public.tenants SET subscription_plan='STARTER' WHERE tenant_id=$1",w.tenants[0])
    with pytest.raises(HTTPException):await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]),expected_store_policy=(store,digest))
    x.lifecycle.confirm.assert_not_awaited()
    await w.db.execute("UPDATE public.tenants SET subscription_plan='COMMAND' WHERE tenant_id=$1",w.tenants[0])
    await w.db.execute("UPDATE public.ecommerce_stores SET return_policy='{\"enabled\":false}' WHERE id=$1",store)
    with pytest.raises(HTTPException):await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]),expected_store_policy=(store,digest))
    x.lifecycle.confirm.assert_not_awaited()
    await w.db.execute('UPDATE public.ecommerce_stores SET return_policy=$2::jsonb WHERE id=$1',store,json.dumps(policy))
    result=await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]),expected_store_policy=(store,digest))
    assert result['status']=='BOOKED' and x.lifecycle.confirm.await_count==1
