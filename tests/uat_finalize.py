"""Verify final fixture state and tag the retained race audit distinctly."""
import asyncio,json
from pathlib import Path
from uuid import UUID
import asyncpg
from main import Settings
from backend.database_tls import database_tls_context
async def run():
 s=Settings();assert s.database_environment=='SANDBOX'
 c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict))
 try:
  audit=json.loads(Path('docs/uat_100/post_apply_evidence.json').read_text())
  ids=[UUID(x) for x in audit['race_cleanup']['scratch_shipment_ids']]
  async with c.transaction():
   await c.execute("UPDATE public.shipments SET logistics_metadata=logistics_metadata||'{\"fixture_batch\":\"veloce-uat100-race-v1\"}'::jsonb WHERE id=ANY($1::uuid[]) AND customer_reference LIKE 'UAT-RACE-%'",ids)
  totals={tag:await c.fetchval("SELECT count(*) FROM public.tenants WHERE company_profile->>'fixture_batch'=$1 AND is_sandbox",tag) for tag in ['veloce-rigorous-v1','veloce-uat100-v1']}
  assert totals=={'veloce-rigorous-v1':24,'veloce-uat100-v1':3}
  quote_count=await c.fetchval("SELECT count(*) FROM public.shipments WHERE logistics_metadata->>'fixture_batch'='veloce-uat100-v1'")
  assert quote_count==8
  wallet=await c.fetchrow("SELECT balance,reserved_balance FROM public.wallets WHERE tenant_id=(SELECT tenant_id FROM public.tenants WHERE workspace_slug='uat100-02')")
  assert wallet['balance']==20 and wallet['reserved_balance']==0
  data={'sandbox_tenant_counts':totals,'total_fixture_tenants':27,'original_supplement_quotes':quote_count,'race_wallet_balance':str(wallet['balance']),'race_wallet_reserved':str(wallet['reserved_balance']),'audit_records_retained':True}
  Path('docs/uat_100/final_verification.json').write_text(json.dumps(data,indent=2));print(json.dumps(data))
 finally:await c.close()
if __name__=='__main__':asyncio.run(run())
