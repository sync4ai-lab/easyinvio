"""Exercise actual rating orchestration with fault-injected strategies and real pricing."""
import asyncio,json,time
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch
import asyncpg
import main
from backend.database_tls import database_tls_context
from backend.verify_automation_writepath import BorrowedPool
from backend.admin_portal import borrowed_pricing_connection
from tests.test_logistics import payload

async def run():
 s=main.Settings();assert s.database_environment=='SANDBOX'
 c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict))
 try:
  tid=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01'")
  accounts=await c.fetch('SELECT id,aggregator FROM public.carrier_accounts WHERE tenant_id=$1',tid)
  class Repository:
   async def accounts(self,context):return [SimpleNamespace(provider=a['aggregator'],id=a['id']) for a in accounts]
  starts={}
  async def unavailable(strategy,request):
   starts['EASYPOST']=time.perf_counter();await asyncio.sleep(.08);raise TimeoutError('Fault-injected provider timeout')
  async def available(strategy,request):
   starts['REGIONAL']=time.perf_counter();await asyncio.sleep(.08)
   return [main.WholesaleRate(provider='REGIONAL',account_id=strategy.account.id,upstream_shipment_id='CONTROLLED-QUOTE',upstream_rate_id='CONTROLLED-RATE',carrier_code='DPD',service_code='TEST',currency='GBP',wholesale_cost='12.35')]
  service=main.RatingService(None,Repository(),s,pool=BorrowedPool(c));start=time.perf_counter()
  with borrowed_pricing_connection(c),patch.object(main.EasyPostStrategy,'rates',unavailable),patch.object(main.RegionalStrategy,'rates',available):
   result=await service.quote(main.TenantContext(tid,uuid4(),'OWNER','controlled-context'),main.RatingRequest.model_validate(payload()))
  assert result.partial and len(result.rates)==1 and result.rates[0].carrier_code=='DPD'
  assert result.issues[0].code=='UPSTREAM_TIMEOUT'
  data={'case':'TC-032','fault_quote':result.model_dump(mode='json'),'controlled_parallel_start_gap_ms':round(abs(starts['EASYPOST']-starts['REGIONAL'])*1000,3),'elapsed_ms':round((time.perf_counter()-start)*1000,2),'actual_external_carrier_calls':0,'real_database_pricing':True}
  Path('docs/uat_100/provider_fault_evidence.json').write_text(json.dumps(data,indent=2));print(json.dumps({k:v for k,v in data.items() if k!='fault_quote'},indent=2))
 finally:await c.close()
if __name__=='__main__':asyncio.run(run())
