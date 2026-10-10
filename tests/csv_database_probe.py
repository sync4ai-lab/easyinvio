"""Exercise CSV persistence against Supabase; roll back every test write."""
import asyncio
import json
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID,uuid4

import asyncpg
from fastapi import HTTPException
from main import Settings,RatingRequest,ClientRate
from backend.database_tls import database_tls_context
from backend.automation_freight_engine import AutomationService
from backend.order_csv import CSVOrderService,CSVCustomsReview,CSV_FIELDS,OPTIONAL_CSV_FIELDS,parse_batch_csv
from backend.ecommerce_sync import EcommerceService
from backend.verify_automation_writepath import BorrowedPool
from tests.test_order_csv import example,encode


async def run():
    settings=Settings();assert settings.database_environment=='SANDBOX'
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    transaction=connection.transaction();await transaction.start();evidence={};ids=[]
    try:
        tenant=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
        actor=await connection.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER'",tenant)
        other=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-02' AND is_sandbox")
        account=await connection.fetchval("SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND aggregator='REGIONAL' LIMIT 1",tenant)
        store=await connection.fetchval("SELECT id FROM public.ecommerce_stores WHERE tenant_id=$1 AND platform='SHOPIFY' LIMIT 1",tenant)
        assert tenant and actor and account and store
        context=SimpleNamespace(tenant_id=tenant,user_id=actor,role='OWNER')
        pool=BorrowedPool(connection);calls=[]
        async def accounts(ctx):return [SimpleNamespace(id=account,provider='REGIONAL')]
        async def quote(ctx,request):
            calls.append(request);now=datetime.now(timezone.utc)
            rate=ClientRate(provider='REGIONAL',account_id=account,upstream_shipment_id='controlled-csv-'+uuid4().hex,upstream_rate_id='controlled-rate',
                carrier_code='LOCAL_CSV',service_code='TEST',currency=request.currency,client_price_ex_tax='12.00',delivery_days=2,
                fee_breakdown={'wholesale_total':'10.00','source':'quote_total'})
            return SimpleNamespace(rates=[rate],quoted_at=now,expires_at=now+timedelta(minutes=15),partial=False,issues=[])
        automation=AutomationService(pool,SimpleNamespace(quote=quote),SimpleNamespace(),SimpleNamespace(accounts=accounts),RatingRequest,None,settings)
        service=CSVOrderService(pool,automation)
        sources=[example(i) for i in range(4)]
        for row in sources:row['order_reference']='ROLLBACK-CSV-'+uuid4().hex
        rows=parse_batch_csv(encode(sources),RatingRequest,settings)
        results=[]
        for row in rows:
            result=await service.process(context,row);results.append(result)
            assert result.get('saved'),result
            ids.append(UUID(result['shipment_id']))
        assert [r['status'] for r in results]==['quoted','quoted','quoted','customs_review_required'],results
        assert len(calls)==3
        stored=await connection.fetchrow('SELECT cargo_type,recipient_address,logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,ids[0])
        decode=lambda value:json.loads(value) if isinstance(value,str) else value
        assert decode(stored['recipient_address'])['phone']=='+447700900001'
        assert decode(stored['recipient_address'])['name']=='Alex Example'
        assert decode(stored['logistics_metadata'])['batch_csv']['declared_value']=='25.00'
        evidence['domestic_parcel_letter_pallet_saved_and_quoted']=True
        before=await connection.fetchval('SELECT count(*) FROM public.shipments WHERE tenant_id=$1',tenant)
        replay=await service.process(context,rows[0]);assert replay['replayed'] and replay['shipment_id']==str(ids[0])
        equivalent=sources[0]|{'weight_kg':'2.5','length_cm':'40.0','item_declared_value':'25','recipient_phone':"'+447700900001"}
        repeated=await service.process(context,parse_batch_csv(encode([equivalent]),RatingRequest)[0]);assert repeated.get('replayed'),repeated
        assert before==await connection.fetchval('SELECT count(*) FROM public.shipments WHERE tenant_id=$1',tenant)
        changed=sources[0]|{'weight_kg':'3.000'}
        conflict=await service.process(context,parse_batch_csv(encode([changed]),RatingRequest)[0]);assert conflict['http_status']==409
        evidence['reupload_and_changed_data_guards']=True
        review=CSVCustomsReview(items=[{'description':'Cotton T-shirt','quantity':1,'unit_value':'25.00','unit_weight_kg':'2.000','origin_country':'GB','hs_code':'610910'}],
            customs_signer='Explicit Test Reviewer',recipient_phone='+12025550123',destination_state='NY',postal_form='CN23',hs_codes_reviewed=True)
        reviewed=await service.review_and_quote(context,ids[3],review);assert reviewed['status']=='quoted',reviewed
        assert calls[-1].customs_document['ready_for_provider'] and calls[-1].customs_document['postal_form']=='CN23'
        assert calls[-1].customs_document['items'][0]['hs_code']=='610910'
        stored=await connection.fetchrow('SELECT status,customs_items,customs_reviewed_by_user_id,recipient_address FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,ids[3])
        assert stored['status']=='QUOTED' and stored['customs_reviewed_by_user_id']
        assert decode(stored['recipient_address'])['state']=='NY'
        assert decode(stored['customs_items'])[0]['unit_value']=='25.00'
        evidence['international_review_and_carrier_customs_payload']=True
        try:await service.review_and_quote(SimpleNamespace(tenant_id=other,user_id=actor,role='OWNER'),ids[3],review)
        except HTTPException as exc:assert exc.status_code==404
        else:raise AssertionError('Cross-tenant review accepted')
        evidence['cross_tenant_review_denied']=True
        shop=example(0,True);shop.update(order_reference='ROLLBACK-SHOP-'+uuid4().hex,store_id=str(store),store_order_id='CSV-SHOP-'+uuid4().hex,platform='SHOPIFY')
        linked=await service.process(context,parse_batch_csv(encode([shop],CSV_FIELDS+OPTIONAL_CSV_FIELDS),RatingRequest)[0]);assert linked['status']=='quoted',linked
        linked_id=UUID(linked['shipment_id']);ids.append(linked_id)
        await EcommerceService(pool).queue_confirmed_tracking(connection,tenant,linked_id,'CONTROLLED-TEST-TRACKING','UPS')
        event=await connection.fetchrow('SELECT store_id,store_order_id,status FROM public.ecommerce_tracking_outbox WHERE tenant_id=$1 AND shipment_id=$2',tenant,linked_id)
        assert event['store_id']==store and event['store_order_id']==shop['store_order_id'] and event['status']=='PENDING'
        evidence['store_identity_and_durable_tracking_handoff']=True
    finally:
        await transaction.rollback()
        assert not await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.shipments WHERE id=ANY($1::uuid[]))',ids)
        await connection.close()
    evidence.update(actual_supabase=True,controlled_rates=True,all_writes_rolled_back=True,carrier_calls=0,bookings_created=0,payments_processed=False)
    Path('docs/bulk_csv').mkdir(exist_ok=True)
    Path('docs/bulk_csv/database_evidence.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence))


if __name__=='__main__':asyncio.run(run())
