"""Apply additive sandbox migration; roll back all functional test records."""
import asyncio
import json
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
from datetime import datetime,timedelta,timezone

import asyncpg
from fastapi import HTTPException
from main import Settings,RatingRequest,ClientRate
from backend.automation_freight_engine import AutomationService
from backend.database_tls import database_tls_context
from backend.ecommerce_sync import EcommerceService, ImportPayload
from backend.admin_portal import calibrated_pricing_scope, borrowed_pricing_connection, get_client_calibrated_rate
from backend.verify_automation_writepath import BorrowedPool


async def run():
    settings=Settings()
    assert settings.database_environment=='SANDBOX'
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),
        ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    evidence={}
    try:
        sql=Path('migrations/016_core_pillars.sql').read_text()
        sql=re.sub(r'^(BEGIN;|COMMIT;)\s*$','',sql,flags=re.M)
        transaction=connection.transaction();await transaction.start()
        try: await connection.execute(sql)
        finally: await transaction.rollback()
        async with connection.transaction(): await connection.execute(sql)
        evidence['migration_016_applied']=True
        transaction=connection.transaction();await transaction.start()
        try:
            tenant=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
            actor=await connection.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active",tenant)
            store=await connection.fetchval("SELECT id FROM public.ecommerce_stores WHERE tenant_id=$1 AND platform='SHOPIFY' AND is_active LIMIT 1",tenant)
            assert tenant and actor and store
            pool=BorrowedPool(connection)
            service=EcommerceService(pool)
            context=SimpleNamespace(tenant_id=tenant,user_id=actor,role='OWNER')
            order=ImportPayload(store_id=store,order={'id':'PILLAR-ROLLBACK-'+uuid4().hex,'name':'PILLAR IMPORT ROLLBACK','currency':'GBP',
                'shipping_address':{'name':'Synthetic Recipient','address1':'2 Fixture Way','city':'London','zip':'SW1A 1AA','country_code':'GB'},
                'line_items':[{'title':'Synthetic cotton shirt','quantity':3,'grams':'150.25'}]})
            imported=await service.import_order(context,order)
            sid=UUID(imported['shipment_id'])
            stored=await connection.fetchrow('SELECT status,parcel_weight_kg,carrier_account_id,parcel_length_cm,final_client_price FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,sid)
            assert dict(stored)=={'status':'PENDING_IMPORT','parcel_weight_kg':Decimal('.451'),'carrier_account_id':None,'parcel_length_cm':None,'final_client_price':Decimal(0)}
            assert (await service.import_order(context,order))['replayed']
            evidence['native_schema_import_and_replay']=True
            # Leaving the unpacked state without a carrier/dimensions must fail.
            async with connection.transaction():
                try:
                    async with connection.transaction():
                        await connection.execute("UPDATE public.shipments SET status='QUOTED' WHERE tenant_id=$1 AND id=$2",tenant,sid)
                except asyncpg.CheckViolationError: pass
                else: raise AssertionError('Unpacked import became bookable')
            evidence['unpacked_import_booking_guard']=True
            other=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-02' AND is_sandbox")
            try: await service.import_order(SimpleNamespace(tenant_id=other,user_id=actor,role='OWNER'),order)
            except HTTPException as exc: assert exc.status_code==404
            else: raise AssertionError('Cross-tenant import accepted')
            evidence['import_tenant_boundary']=True
            account=await connection.fetchval("SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND aggregator='REGIONAL' LIMIT 1",tenant)
            async def accounts(ctx):return [SimpleNamespace(id=account,provider='REGIONAL')]
            async def quote(ctx,request):
                now=datetime.now(timezone.utc)
                rate=ClientRate(provider='REGIONAL',account_id=account,upstream_shipment_id='controlled-quote',upstream_rate_id='controlled-rate',
                    carrier_code='LOCAL_TEST',service_code='TEST',currency='GBP',client_price_ex_tax='12.00',delivery_days=2,
                    fee_breakdown={'wholesale_total':'10.00','source':'provider','base_cost':'7.00','fuel_surcharge':'2.00','residential_fee':'1.00','remote_area_fee':'0.00'})
                return SimpleNamespace(rates=[rate],quoted_at=now,expires_at=now+timedelta(minutes=15),partial=False,issues=[])
            automation=AutomationService(pool,SimpleNamespace(quote=quote),SimpleNamespace(),SimpleNamespace(accounts=accounts),RatingRequest,None,settings)
            row=await connection.fetchrow('SELECT sender_address,recipient_address FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,sid)
            decode=lambda value:json.loads(value) if isinstance(value,str) else value
            result=await automation.process(context,{'idempotency_key':str(sid),'order_reference':order.order.name,'platform':'SHOPIFY',
                'store_id':str(store),'store_order_id':str(order.order.id),'origin':decode(row['sender_address']),
                'destination':decode(row['recipient_address']),'currency':'GBP',
                'cargo':{'cargo_type':'PARCEL','actual_weight_kg':'0.451','length_cm':'40','width_cm':'30','height_cm':'20'}},'QUOTE_ONLY')
            assert result['status']=='QUOTED',result
            assert result['shipment_id']==str(sid)
            baseline=await connection.fetchval("SELECT logistics_metadata->'invoice_baseline' FROM public.shipments WHERE tenant_id=$1 AND id=$2",tenant,sid)
            baseline=decode(baseline)
            assert baseline['billable_weight_kg']=='4.800' and baseline['base_cost']=='7.00'
            evidence['import_promotion_and_provider_invoice_baseline']=True
            await connection.execute("INSERT INTO public.margin_rules(tenant_id,rule_name,currency,markup_type,markup_value,priority,billing_plan,cargo_type,min_volume_m3,max_volume_m3) VALUES($1,'PILLAR ROLLBACK','GBP','PERCENTAGE',35,0,'PREPAID_WALLET','PALLET',0.5,2)",tenant)
            with borrowed_pricing_connection(connection), calibrated_pricing_scope(pool,currency='GBP',cargo_type='PALLET',volume_m3=Decimal('1')):
                assert await get_client_calibrated_rate(tenant,Decimal('100'),'DHL','GB')==Decimal('135')
            with borrowed_pricing_connection(connection), calibrated_pricing_scope(pool,currency='GBP',cargo_type='PARCEL',volume_m3=Decimal('1')):
                assert await get_client_calibrated_rate(tenant,Decimal('100'),'DHL','GB')!=Decimal('135')
            # Isolated no-rule fixture verifies the exact established fallback.
            empty=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='uat100-01' AND is_sandbox")
            with borrowed_pricing_connection(connection), calibrated_pricing_scope(pool,currency='GBP'):
                assert await get_client_calibrated_rate(empty,Decimal('100'),'DHL','GB')==Decimal('120')
            evidence['cargo_tier_volume_rules_and_fallback']=True
        finally: await transaction.rollback()
        evidence.update(test_records_rolled_back=True,external_provider_calls=0,money_processed=False)
        Path('docs/core_pillars').mkdir(parents=True,exist_ok=True)
        Path('docs/core_pillars/database_evidence.json').write_text(json.dumps(evidence,indent=2))
        print(json.dumps(evidence))
    finally: await connection.close()


if __name__=='__main__': asyncio.run(run())
