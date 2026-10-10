"""Validate the proposed supplemental SQL in Supabase, then roll it all back."""
import asyncio,json
from pathlib import Path
from uuid import UUID
from decimal import Decimal
import asyncpg
from main import Settings
from backend.database_tls import database_tls_context
from backend.admin_portal import borrowed_pricing_connection,calibrated_pricing_scope,get_client_calibrated_rate

async def run():
 s=Settings();assert s.database_environment=='SANDBOX'
 c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict))
 tx=c.transaction();await tx.start()
 try:
  already_applied=bool(await c.fetchval("SELECT completed FROM public.fixture_seed_runs WHERE batch_tag='veloce-uat100-v1'"))
  if not already_applied:await c.execute(Path('seeds/uat_100/01_supplemental_data.sql').read_text())
  tid=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='uat100-02'")
  fallback=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='uat100-01'")
  async def rate(tenant,service=None,weight=None):
   with borrowed_pricing_connection(c),calibrated_pricing_scope(None,service_code=service,weight_kg=weight):
    return str(await get_client_calibrated_rate(tenant,Decimal('10'),'DHL','GB'))
  data={'sql_constraints_passed':True,'committed':already_applied,'supplement_applied_only_inside_rollback_test':not already_applied,
    'TC-033':await rate(fallback),'TC-037':await rate(tid,'UAT_FIXED'),'TC-038':await rate(tid,'UAT_ZERO'),
    'TC-042':{'below_20':await rate(tid,'UAT_TIER',Decimal('19.999')),'at_20':await rate(tid,'UAT_TIER',Decimal('20'))},
    'TC-048':await rate(tid,'UAT_PRIORITY')}
  data['counts']={table:await c.fetchval(f"SELECT count(*) FROM public.{table} r JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-uat100-v1'") for table in ['users','shipments','carrier_accounts','margin_rules','wallets']}
  data['counts']['shipments']=await c.fetchval("SELECT count(*) FROM public.shipments WHERE logistics_metadata->>'fixture_batch'='veloce-uat100-v1' AND customer_reference LIKE 'UAT100-%'")
  assert data['counts']=={'users':9,'shipments':8,'carrier_accounts':6,'margin_rules':6,'wallets':3}
  assert data['TC-033']=='12.00' and data['TC-037']=='15.50' and data['TC-038']=='10.00'
  assert data['TC-042']=={'below_20':'11.00','at_20':'12.50'}
  await tx.rollback()
  data['persistent_supplement_tenants_after_rollback']=await c.fetchval("SELECT count(*) FROM public.tenants WHERE company_profile->>'fixture_batch'='veloce-uat100-v1'")
  Path('docs/uat_100/supplement_evidence.json').write_text(json.dumps(data,indent=2));print(json.dumps(data,indent=2))
 except Exception as e:
  if c.is_in_transaction():await tx.rollback()
  print(type(e).__name__,getattr(e,'sqlstate',None),getattr(e,'constraint_name',None));raise
 finally:await c.close()
if __name__=='__main__':asyncio.run(run())
