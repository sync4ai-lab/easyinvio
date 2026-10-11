"""Real PostgreSQL carrier-history assertions; all inserted shipments are rolled back."""
import asyncio,json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
from decimal import Decimal
from contextlib import asynccontextmanager
import asyncpg
from main import Settings,database_tls_context
from backend.carrier_consolidation import route_history,carrier_identity

async def run():
 s=Settings();assert s.database_environment=='SANDBOX'
 c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict))
 tx=c.transaction();await tx.start()
 try:
  original=json.loads(await c.fetchval("SELECT to_jsonb(s)::text FROM public.shipments s WHERE customer_reference='SEED24-1-5'"))
  tenant=original['tenant_id'];code='QA'+uuid4().hex[:12];start=datetime.now(timezone.utc)-timedelta(days=4)
  columns=await c.fetchval("SELECT string_agg(quote_ident(attname),',' ORDER BY attnum) FROM pg_attribute WHERE attrelid='public.shipments'::regclass AND attnum>0 AND NOT attisdropped AND attgenerated=''")
  for index in range(5):
   data=dict(original);data.update(id=str(uuid4()),idempotency_key=str(uuid4()),customer_reference='ROLLBACK-CONSO-'+str(index),
    tracking_number='ROLLBACK-'+uuid4().hex,ecommerce_store_id=None,store_order_id=None,store_import_hash=None,
    carrier_code=code,status='DELIVERED' if index<2 else 'EXCEPTION',created_at=start.isoformat(),booked_at=start.isoformat(),dispatched_at=start.isoformat(),
    delivered_at=(start+timedelta(days=1,hours=12) if index==0 else start+timedelta(days=3)).isoformat() if index<2 else None,
    last_tracking_event_at=datetime.now(timezone.utc).isoformat(),logistics_metadata={'synthetic':False})
   data['pricing_snapshot']={**original['pricing_snapshot'],'selected_rate':{'delivery_days':2 if index==0 else 0}}
   await c.execute(f'INSERT INTO public.shipments({columns}) SELECT {columns} FROM jsonb_populate_record(NULL::public.shipments,$1::jsonb)',json.dumps(data))
  class Pool:
   @asynccontextmanager
   async def acquire(self):yield c
  result=await route_history(Pool(),__import__('uuid').UUID(tenant),'GB');stats=result[carrier_identity(code)]
  assert stats['on_time_rate']==Decimal('50.0'),stats
  assert stats['avg_transit_days']==Decimal('2.3'),stats
  assert stats['route_risk_level']=='HIGH_DELAY_ALERT' and stats['active_exceptions']==3,stats
  foreign=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-02'")
  assert carrier_identity(code) not in await route_history(Pool(),foreign,'GB')
  assert await c.fetchval("SELECT to_regclass('public.shipments_carrier_history_lane') IS NOT NULL")
  print('PASS: real database Decimal history, active exception risk, tenant isolation and performance index; all five probe shipments rolled back.')
 finally:await tx.rollback();await c.close()
if __name__=='__main__':asyncio.run(run())
