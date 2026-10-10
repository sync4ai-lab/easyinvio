"""Applied UAT fixtures: rollback probes plus an auditable two-connection race."""
import asyncio,json
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import asyncpg
from main import Settings,FinanceEngine
from backend.database_tls import database_tls_context
from backend.verify_automation_writepath import BorrowedPool
from backend.tracking_and_support import TrackingSupportService,TrackingSettings

async def run():
 s=Settings();assert s.database_environment=='SANDBOX'
 pool=await asyncpg.create_pool(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict),min_size=2,max_size=3)
 results={};permits=[];scratch=[]
 try:
  async with pool.acquire() as c:
   tid=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='uat100-02' AND is_sandbox")
   assert tid is not None
   uid=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER'",tid)
   ctx=SimpleNamespace(tenant_id=tid,user_id=uid,role='OWNER')
   async def probe(n,fn):
    tx=c.transaction(isolation='repeatable_read');await tx.start()
    try:results[n]=await fn(c)
    finally:await tx.rollback()
   async def inactive(c):
    inactive_uid=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND NOT is_active",tid)
    try:await FinanceEngine(BorrowedPool(c),s,None).lock_tenant(c,tid,SimpleNamespace(tenant_id=tid,user_id=inactive_uid),{'DISPATCHER'})
    except Exception as e:
     assert getattr(e,'status_code',None)==403
     return {'backend_status':403,'oidc_login_tested':False}
    raise AssertionError('Inactive member allowed')
   await probe('TC-012',inactive)
   async def postpaid(c):
    post_tid=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-04'")
    user=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER'",post_tid)
    ship=await c.fetchval("SELECT id FROM public.shipments WHERE tenant_id=$1 AND customer_reference='SEED24-4-2'",post_tid)
    permit=await FinanceEngine(BorrowedPool(c),s,None).reserve(SimpleNamespace(tenant_id=post_tid,user_id=user),ship)
    assert permit.billing_plan=='POSTPAID_30_DAY'
    return {'reservation':'accepted','wallet_balance':str(await c.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',post_tid)),'label_purchased':False,'rolled_back':True}
   await probe('TC-051',postpaid)
   async def precision(c):
    ship=await c.fetchval("SELECT id FROM public.shipments WHERE tenant_id=$1 AND customer_reference='UAT100-2-4'",tid)
    await FinanceEngine(BorrowedPool(c),s,None).reserve(ctx,ship)
    row=await c.fetchrow('SELECT balance,reserved_balance,balance-reserved_balance AS available FROM public.wallets WHERE tenant_id=$1',tid)
    assert row['reserved_balance']==Decimal('12.33') and row['available']==Decimal('7.67')
    return {**{k:str(v) for k,v in dict(row).items()},'capture_tested':False,'rolled_back':True}
   await probe('TC-061',precision)
   async def weekly(c):
    target=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01'")
    user=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER'",target)
    anchor=await c.fetchval("SELECT generated_at FROM public.fixture_seed_runs WHERE batch_tag='veloce-rigorous-v1'")
    start=(anchor-timedelta(days=18)).date();end=start+timedelta(days=6)
    report=await TrackingSupportService(BorrowedPool(c),TrackingSettings()).report(SimpleNamespace(tenant_id=target,user_id=user,role='ACCOUNTANT'),start,end,1,100)
    rows=await c.fetch("SELECT currency,count(*) AS count,sum(final_client_price) AS spend FROM public.shipments WHERE tenant_id=$1 AND booked_at >= $2 AND booked_at < $3 AND status IN ('BOOKED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED') GROUP BY currency",target,datetime.combine(start,datetime.min.time(),timezone.utc),datetime.combine(end+timedelta(days=1),datetime.min.time(),timezone.utc))
    for row in rows:
     total=next(x for x in report['totals_by_currency'] if x['currency']==row['currency'])
     assert Decimal(total['shipping_spend'])==row['spend'] and total['package_count']==row['count']
    assert report['total_package_count']>0
    return {'start':str(start),'end':str(end),'report':report,'direct_sql_reconciled':True}
   await probe('TC-065',weekly)
   empty=await c.fetchval("SELECT count(*) FROM public.shipments WHERE tenant_id=(SELECT tenant_id FROM public.tenants WHERE workspace_slug='uat100-03')")
   assert empty==0;results['TC-092']={'empty_workspace_shipment_count':empty,'browser_card_verified':False}
   wallet=await c.fetchrow('SELECT balance,reserved_balance FROM public.wallets WHERE tenant_id=$1',tid)
   assert wallet['balance']==20 and wallet['reserved_balance']==0
   # Separate scratch quotes preserve the eight supplied seed quote states.
   columns=await c.fetchval("SELECT string_agg(quote_ident(attname),',' ORDER BY attnum) FROM pg_attribute WHERE attrelid='public.shipments'::regclass AND attnum>0 AND NOT attisdropped AND attgenerated=''")
   for _ in range(2):
    sid=uuid4();scratch.append(sid)
    original=await c.fetchval("SELECT to_jsonb(s)::text FROM public.shipments s WHERE tenant_id=$1 AND customer_reference='UAT100-2-2'",tid)
    data=json.loads(original);data.update(id=str(sid),idempotency_key=str(uuid4()),customer_reference='UAT-RACE-'+str(sid),internal_notes='Auditable UAT race; no provider calls; reservation released after test.',logistics_metadata={'fixture_batch':'veloce-uat100-race-v1','synthetic':True})
    await c.execute(f'INSERT INTO public.shipments({columns}) SELECT '+','.join('x.'+col for col in columns.split(','))+' FROM jsonb_populate_record(NULL::public.shipments,$1::jsonb) x',json.dumps(data))
  finance=FinanceEngine(pool,s,None)
  async def reserve(sid):
   try:
    permit=await finance.reserve(ctx,sid);permits.append(permit);return {'outcome':'RESERVED','shipment_id':str(sid)}
   except Exception as e:
    if hasattr(e,'status_code'):return {'http_status':e.status_code,'shipment_id':str(sid)}
    raise
  outcomes=await asyncio.gather(*(reserve(x) for x in scratch))
  assert sum(x.get('outcome')=='RESERVED' for x in outcomes)==1 and sum(x.get('http_status')==402 for x in outcomes)==1
  results['TC-056']={'simultaneous_requests':outcomes,'label_purchased':False,'method':'Actual asyncpg pool, independently committed concurrent reservation transactions'}
 finally:
  for permit in permits:await FinanceEngine(pool,s,None).finish_booking(permit,outcome='NOT_SUBMITTED')
  if scratch:
   async with pool.acquire() as c:
    await c.execute("UPDATE public.shipments SET status='FAILED',internal_notes=internal_notes||' Test finished; no label generated.' WHERE tenant_id=$1 AND id=ANY($2::uuid[])",tid,scratch)
    after=await c.fetchrow('SELECT balance,reserved_balance FROM public.wallets WHERE tenant_id=$1',tid)
    results['race_cleanup']={'balance':str(after['balance']),'reserved_balance':str(after['reserved_balance']),'retained_audit':'Two FAILED scratch quotes, one RELEASED reservation, RESERVE/RELEASE ledger entries','scratch_shipment_ids':[str(x) for x in scratch]}
    assert after['balance']==20 and after['reserved_balance']==0
  await pool.close()
 Path('docs/uat_100/post_apply_evidence.json').write_text(json.dumps(results,indent=2,default=str));print(json.dumps(results,indent=2,default=str))
if __name__=='__main__':asyncio.run(run())
