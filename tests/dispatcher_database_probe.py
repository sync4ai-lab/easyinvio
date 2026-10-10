"""Real Supabase dispatcher intake/preparation/quote/outbox test; final rollback.

Provider responses are controlled. No live purchase, payment or message is sent.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import httpx
from fastapi import FastAPI

from main import Settings, RatingRequest, ClientRate
from backend.database_tls import database_tls_context
from backend.verify_automation_writepath import BorrowedPool
from backend.ecommerce_sync import EcommerceService, ImportPayload
from backend.automation_freight_engine import AutomationService
from backend.dispatch_workspace import build_router
from backend.admin_portal import calibrated_pricing_scope, borrowed_pricing_connection, get_client_calibrated_rate


async def run():
    settings=Settings();assert settings.database_environment=='SANDBOX'
    c=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    tx=c.transaction();await tx.start();ids=[];evidence={}
    try:
        tenant=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
        actor=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='DISPATCHER' AND is_active",tenant)
        store=await c.fetchval("SELECT id FROM public.ecommerce_stores WHERE tenant_id=$1 AND platform='SHOPIFY' AND is_active LIMIT 1",tenant)
        account=await c.fetchval("SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND aggregator='REGIONAL' LIMIT 1",tenant)
        other=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-02' AND is_sandbox")
        assert all([tenant,actor,store,account,other])
        ctx=SimpleNamespace(tenant_id=tenant,user_id=actor,role='DISPATCHER');pool=BorrowedPool(c)
        ecommerce=EcommerceService(pool);captured=[]
        async def accounts(context):return [SimpleNamespace(id=account,provider='REGIONAL')]
        async def quote(context,request):
            captured.append(request)
            with borrowed_pricing_connection(c),calibrated_pricing_scope(pool,currency=request.currency,
                    origin=request.origin.country_code,cargo_type=request.cargo_type):
                total=await get_client_calibrated_rate(context.tenant_id,Decimal('10'),'LOCAL_TEST',request.destination.country_code)
            now=datetime.now(timezone.utc)
            rate=ClientRate(provider='REGIONAL',account_id=account,upstream_shipment_id='CONTROLLED-'+uuid4().hex,
                upstream_rate_id='TEST-RATE',carrier_code='LOCAL_TEST',service_code='TEST',currency=request.currency,
                client_price_ex_tax=total,delivery_days=2,fee_breakdown={'wholesale_total':'10.00','source':'quote_total'})
            return SimpleNamespace(rates=[rate],quoted_at=now,expires_at=now+timedelta(minutes=15),partial=False,issues=[])
        automation=AutomationService(pool,SimpleNamespace(quote=quote),None,SimpleNamespace(accounts=accounts),RatingRequest,None,settings)
        # One borrowed connection: concurrent semantics are tested separately with 100 requests.
        automation.order_limiter=asyncio.Semaphore(1)
        app=FastAPI();app.state.ecommerce=ecommerce;app.state.automation_freight=automation
        app.include_router(build_router(lambda:ctx))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            for i in range(100):
                payload=ImportPayload(store_id=store,order={'id':'DISPATCH-ROLLBACK-'+uuid4().hex,'name':'ROLLBACK-WORKSPACE-'+str(i),
                    'currency':'USD','shipping_address':{'name':'Synthetic Customer','address1':'1 Fixture Street',
                    'city':'New York','zip':'10001','country_code':'US','province':'NY','phone':'+12025550123'},
                    'line_items':[{'title':'Cotton T-shirt','quantity':2,'grams':'200','unit_value':'12.35','origin_country':'GB'}]})
                imported=await ecommerce.import_order(ctx,payload);sid=UUID(imported['shipment_id']);ids.append(sid)
                assert (await ecommerce.import_order(ctx,payload))['replayed']
            evidence['hundred_real_imports_replay_safe']=True
            for sid in ids:
                response=await client.get(f'/api/v1/dispatch-workspace/orders/{sid}');assert response.status_code==200,response.text
                order=response.json()['order'];assert order['items'][0]['hs_code']=='610910'
                order['cargo'].update(actual_weight_kg='2.500',length_cm='40',width_cm='30',height_cm='20')
                order.update(hs_codes_reviewed=True,customs_signer='Synthetic Dispatcher Reviewer')
                response=await client.post(f'/api/v1/dispatch-workspace/orders/{sid}/prepare',json=order)
                assert response.status_code==200 and response.json()['status']=='QUOTED',response.text
                assert response.json()['rate']['fee_breakdown']=={'source':'financial_role_required'}
            assert len(captured)==100 and all(r.customs_document['ready_for_provider'] for r in captured)
            assert all(r.customs_document['totals']['goods_value']=='24.70' for r in captured)
            evidence['packing_hs_customs_db_margin_quotes_100']=True
            stored=await c.fetchrow('SELECT status,parcel_length_cm,customs_reviewed_by_user_id,final_client_price FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,ids[0])
            assert stored['status']=='QUOTED' and stored['parcel_length_cm']==40 and stored['customs_reviewed_by_user_id']
            response=await client.post('/api/v1/dispatch-workspace/process',json={'shipment_ids':[str(i) for i in ids],'mode':'FULFILL'})
            assert response.status_code==200 and all(r['status']=='FAILED' for r in response.json()['results'])
            assert all(r['error']=='PURCHASE_DISABLED_FOR_THIS_ENVIRONMENT' for r in response.json()['results']),response.text[:1000]
            evidence['sandbox_purchase_gate_no_labels_bought']=True
            for sid in ids[:3]:
                await ecommerce.queue_confirmed_tracking(c,tenant,sid,'CONTROLLED-TRACK-'+sid.hex,'UPS')
            assert await c.fetchval('SELECT count(*) FROM public.ecommerce_tracking_outbox WHERE tenant_id=$1 AND shipment_id=ANY($2::uuid[])',tenant,ids)==3
            evidence['durable_tracking_outbox_3_staged_not_sent']=True
            ctx.tenant_id=other
            denied=await client.get(f'/api/v1/dispatch-workspace/orders/{ids[0]}');assert denied.status_code==404
            ctx.tenant_id=tenant;ctx.role='ACCOUNTANT'
            denied=await client.get('/api/v1/dispatch-workspace/orders');assert denied.status_code==403
            evidence['cross_tenant_and_role_boundaries']=True
    finally:
        await tx.rollback()
        assert not await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.shipments WHERE id=ANY($1::uuid[]))',ids)
        await c.close()
    evidence.update(actual_supabase=True,all_writes_rolled_back=True,controlled_carriers=True,external_dispatches=0)
    Path('docs/dispatcher_journey').mkdir(parents=True,exist_ok=True)
    Path('docs/dispatcher_journey/database_evidence.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence))


if __name__=='__main__':asyncio.run(run())
