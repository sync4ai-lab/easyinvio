"""Actual PostgreSQL settlement tests with controlled upstream receipts.

No carrier calls. All temporary records (including a non-sandbox service-test
tenant needed to exercise settlement fencing) exist only in an outer rollback.
"""
import asyncio,json
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from types import SimpleNamespace
import asyncpg
from fastapi import HTTPException
from main import Settings,FinanceEngine
from backend.database_tls import database_tls_context
from backend.verify_automation_writepath import BorrowedPool

async def run():
 s=Settings();assert s.database_environment=='SANDBOX'
 c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict))
 tx=c.transaction();await tx.start();result=[]
 try:
  tid,aid,uid,carrier=uuid4(),uuid4(),uuid4(),uuid4()
  async def clone(table,source,overrides):
   data=json.loads(source);data.update(overrides)
   cols=await c.fetchval("SELECT string_agg(quote_ident(attname),',' ORDER BY attnum) FROM pg_attribute WHERE attrelid=$1::regclass AND attnum>0 AND NOT attisdropped AND attgenerated=''",'public.'+table)
   await c.execute(f'INSERT INTO public.{table}({cols}) SELECT '+','.join('x.'+a for a in cols.split(','))+f' FROM jsonb_populate_record(NULL::public.{table},$1::jsonb) x',json.dumps(data))
  template=await c.fetchval("SELECT to_jsonb(t)::text FROM public.tenants t WHERE workspace_slug='seed24-01'")
  await clone('tenants',template,{'tenant_id':str(tid),'workspace_slug':'rollback-capture-'+str(tid),'is_sandbox':False,'billing_email':'rollback@example.invalid','company_profile':{'fixture_batch':'ROLLBACK_ONLY_CAPTURE','synthetic':True}})
  await c.execute("INSERT INTO auth.users(id,aud,role,email,encrypted_password,raw_app_meta_data,raw_user_meta_data,banned_until,is_sso_user,is_anonymous) VALUES($1,'authenticated','authenticated','rollback-capture@example.invalid','','{}','{}','infinity',false,false)",aid)
  await c.execute("INSERT INTO public.users(id,tenant_id,auth_user_id,role,full_name,is_active) VALUES($1,$2,$3,'OWNER','Rollback capture probe',true)",uid,tid,aid)
  parent=await c.fetchval("SELECT to_jsonb(a)::text FROM public.carrier_accounts a WHERE tenant_id=(SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01') AND aggregator='EASYPOST'")
  await clone('carrier_accounts',parent,{'id':str(carrier),'tenant_id':str(tid),'is_active':False})
  ship_template=await c.fetchval("SELECT to_jsonb(s)::text FROM public.shipments s WHERE customer_reference='SEED24-1-2'")
  engine=FinanceEngine(BorrowedPool(c),s,None);ctx=SimpleNamespace(tenant_id=tid,user_id=aid,role='OWNER')
  for cost in ['20.00','12.33','100.00']:
   sid=uuid4()
   await c.execute('UPDATE public.wallets SET balance=100,reserved_balance=0 WHERE tenant_id=$1',tid)
   await clone('shipments',ship_template,{'id':str(sid),'tenant_id':str(tid),'created_by_user_id':str(uid),'carrier_account_id':str(carrier),'applied_margin_rule_id':None,'ecommerce_store_id':None,'store_order_id':None,'store_import_hash':None,'idempotency_key':str(uuid4()),'customer_reference':'ROLLBACK-CAPTURE','wholesale_cost':cost,'profit_markup':'0.00','tax_amount':'0.00','quote_expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'pricing_snapshot':{'markup_type':'MANUAL','markup_value':'0.00','currency':'GBP'}})
   permit=await engine.reserve(ctx,sid);await engine.mark_submitted(permit)
   await engine.finish_booking(permit,outcome='SUCCESS',tracking_number='CONTROLLED-UAT-RECEIPT',label_storage_path='https://label.example.invalid/simulated-receipt.zpl')
   wallet=await c.fetchrow('SELECT balance,reserved_balance FROM public.wallets WHERE tenant_id=$1',tid)
   assert wallet['balance']==Decimal('100')-Decimal(cost) and wallet['reserved_balance']==0
   entries=await c.fetch('SELECT entry_type,balance_delta,reserved_delta FROM public.wallet_ledger WHERE tenant_id=$1 AND reservation_id=$2 ORDER BY created_at',tid,permit.reservation_id)
   assert sum(e['balance_delta'] for e in entries)==-Decimal(cost)
   assert {e['entry_type'] for e in entries}=={'RESERVE','CAPTURE'}
   assert await c.fetchval('SELECT status FROM public.shipments WHERE tenant_id=$1 AND id=$2',tid,sid)=='BOOKED'
   result.append({'cost':cost,'balance_after':str(wallet['balance']),'reserved_after':str(wallet['reserved_balance']),'ledger_entries':[e['entry_type'] for e in entries],'shipment_status':'BOOKED'})
  zero_sid=uuid4()
  await clone('shipments',ship_template,{'id':str(zero_sid),'tenant_id':str(tid),'created_by_user_id':str(uid),'carrier_account_id':str(carrier),'applied_margin_rule_id':None,'ecommerce_store_id':None,'store_order_id':None,'store_import_hash':None,'idempotency_key':str(uuid4()),'customer_reference':'ROLLBACK-ZERO-CREDIT','wholesale_cost':'1.00','profit_markup':'0.00','tax_amount':'0.00','quote_expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'pricing_snapshot':{'markup_type':'MANUAL','markup_value':'0.00','currency':'GBP'}})
  try:await engine.reserve(ctx,zero_sid)
  except HTTPException as exc:assert exc.status_code==402
  else:raise AssertionError('Zero-credit reservation unexpectedly accepted')
  assert await c.fetchval('SELECT status FROM public.shipments WHERE tenant_id=$1 AND id=$2',tid,zero_sid)=='QUOTED'
 finally:
  await tx.rollback()
  remaining=await c.fetchval('SELECT count(*) FROM public.tenants WHERE tenant_id=$1',tid)
  assert remaining==0;await c.close()
 evidence={'actual_postgresql_settlement_cases':result,'zero_credit_next_dispatch_blocked':True,'controlled_provider_receipts':True,'carrier_api_calls':0,'all_test_records_rolled_back':True,'temporary_service_test_tenant_persisted':False}
 Path('docs/uat_100/finance_capture_evidence.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence,indent=2))
if __name__=='__main__':asyncio.run(run())
