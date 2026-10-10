"""Concurrent real database quote writes with controlled provider responses."""
import asyncio,json,time
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal
from uuid import UUID,uuid4
from datetime import datetime,timedelta,timezone
import asyncpg
from main import Settings,RatingRequest,ClientRate
from backend.database_tls import database_tls_context
from backend.verify_automation_writepath import BorrowedPool
from backend.automation_freight_engine import AutomationService
from backend.admin_portal import borrowed_pricing_connection,calibrated_pricing_scope,get_client_calibrated_rate

async def run():
 s=Settings();assert s.database_environment=='SANDBOX'
 async def tenant_case(slug):
  c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict))
  tx=c.transaction();await tx.start()
  try:
   t=await c.fetchrow('SELECT tenant_id,default_currency FROM public.tenants WHERE workspace_slug=$1 AND is_sandbox',slug)
   uid=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER'",t['tenant_id'])
   account=await c.fetchval("SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND aggregator='REGIONAL'",t['tenant_id'])
   ctx=SimpleNamespace(tenant_id=t['tenant_id'],user_id=uid,role='OWNER')
   async def accounts(context):return [SimpleNamespace(id=account,provider='REGIONAL')]
   async def quote(context,request):
    with borrowed_pricing_connection(c),calibrated_pricing_scope(None,currency=request.currency):
     price=await get_client_calibrated_rate(context.tenant_id,Decimal('10.00'),'LOCAL_TEST','GB')
    now=datetime.now(timezone.utc)
    return SimpleNamespace(rates=[ClientRate(provider='REGIONAL',account_id=account,upstream_shipment_id='CONTROLLED-'+uuid4().hex,upstream_rate_id='CONTROLLED-'+uuid4().hex,carrier_code='LOCAL_TEST',service_code='TEST',currency=request.currency,client_price_ex_tax=price,delivery_days=None,fee_breakdown={'wholesale_total':'10.00','platform_markup':str(price-Decimal('10.00'))})],quoted_at=now,expires_at=now+timedelta(minutes=15),partial=False,issues=[])
   service=AutomationService(BorrowedPool(c),SimpleNamespace(quote=quote),None,SimpleNamespace(accounts=accounts),RatingRequest,None,s)
   address={'name':'Bulk isolation probe','line1':'1 Fixture Way','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
   raw={'idempotency_key':str(uuid4()),'order_reference':'ROLLBACK BULK ISOLATION','origin':address,'destination':address,'cargo':{'cargo_type':'PARCEL','actual_weight_kg':'2.500','length_cm':'40','width_cm':'30','height_cm':'20'},'currency':t['default_currency']}
   start=time.perf_counter();result=await service.process(ctx,raw,'QUOTE_ONLY');elapsed=round((time.perf_counter()-start)*1000,2);assert result['status']=='QUOTED',result
   sid=UUID(result['shipment_id']);row=await c.fetchrow('SELECT tenant_id,currency,final_client_price FROM public.shipments WHERE id=$1',sid)
   assert row['tenant_id']==t['tenant_id']
   other=await c.fetchval('SELECT tenant_id FROM public.tenants WHERE workspace_slug=$1','seed24-02' if slug=='seed24-01' else 'seed24-01')
   assert await c.fetchval('SELECT count(*) FROM public.shipments WHERE tenant_id=$1 AND id=$2',other,sid)==0
   return {'tenant':slug,'currency':row['currency'],'customer_price':str(row['final_client_price']),'other_tenant_lookup_rows':0,'shipment_written':True,'quote_process_ms':elapsed}
  finally:await tx.rollback();await c.close()
 results=await asyncio.gather(tenant_case('seed24-01'),tenant_case('seed24-02'))
 assert {r['customer_price'] for r in results}=={'11.50','12.00'}
 data={'concurrent_tenant_quotes':results,'provider_responses':'controlled; no external carriers','all_writes_rolled_back':True,'case':'TC-013'}
 Path('docs/uat_100/bulk_isolation_evidence.json').write_text(json.dumps(data,indent=2));print(json.dumps(data,indent=2))
if __name__=='__main__':asyncio.run(run())
