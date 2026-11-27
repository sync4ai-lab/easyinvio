"""Disposable PostgreSQL acceptance for finance presentation and explicit support intake."""
import asyncio,os,json
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4
from decimal import Decimal
import pytest,pytest_asyncio,httpx
from fastapi import FastAPI,APIRouter,Header
from backend.billing_ledger import add_routes as ledger_routes
from backend.audit_packets import add_routes as packet_routes,packet
from backend.invoice_upload import build_router,parse_statement
from tests.test_tracking_workspace_postgres import Database

ROOT=Path(__file__).resolve().parents[1]

@pytest_asyncio.fixture
async def world():
 if not os.getenv('PGLITE_TEST_MODULE'):pytest.skip('Explicit disposable PostgreSQL dependency required')
 process=await asyncio.create_subprocess_exec(os.getenv('PGLITE_TEST_NODE'),str(ROOT/'tests/pglite_tracking_bridge.cjs'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=4_000_000)
 db=Database(process);tenant,other,user,shipment,reservation,dispute= [uuid4() for _ in range(6)]
 try:
  await db.command('''CREATE TABLE wallets(tenant_id uuid PRIMARY KEY,currency text,balance numeric,reserved_balance numeric);
  CREATE TABLE shipments(id uuid PRIMARY KEY,tenant_id uuid,customer_reference text,final_client_price numeric,tax_amount numeric,
  upstream_shipment_id text,currency text,wholesale_cost numeric,parcel_weight_kg numeric,multi_parcel_dimensions jsonb,logistics_metadata jsonb,booked_at timestamptz,quote_expires_at timestamptz,carrier_account_id uuid);
  CREATE TABLE wallet_reservations(id uuid PRIMARY KEY,tenant_id uuid,shipment_id uuid);
  CREATE TABLE wallet_ledger(id uuid PRIMARY KEY,tenant_id uuid,currency text,created_at timestamptz DEFAULT now(),entry_type text,balance_delta numeric,reserved_delta numeric,balance_after numeric,reservation_id uuid,topup_id uuid);
  CREATE TABLE billing_disputes(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid,shipment_id uuid,invoice_reference text,line_sha256 text,findings jsonb,baseline jsonb,invoice_line jsonb,confidence_level int,estimated_overcharge numeric,currency text,email_draft text,created_by uuid,status text DEFAULT 'DRAFT',created_at timestamptz DEFAULT now(),UNIQUE(tenant_id,invoice_reference,shipment_id));
  CREATE TABLE support_tickets(id uuid PRIMARY KEY,tenant_id uuid,shipment_id uuid,status text,ai_summary text,ai_method text,prompt_version text,cx_request_id uuid UNIQUE,cx_kind text,issue_category text);''',mode='exec')
  await db.execute("INSERT INTO wallets VALUES($1,'GBP',88,5)",tenant)
  await db.execute("INSERT INTO shipments VALUES($1,$2,'ORDER-1',12,2,'TRACK-1','GBP',10,2,'[]','{}',now(),now()+interval '1 hour',NULL)",shipment,tenant)
  await db.execute('INSERT INTO wallet_reservations VALUES($1,$2,$3)',reservation,tenant,shipment)
  for i,(kind,delta,after,reserve) in enumerate([('TOPUP',100,100,0),('CAPTURE',-12,88,0),('RESERVE',0,88,5)]):
   await db.execute("INSERT INTO wallet_ledger VALUES($1,$2,'GBP',now()+make_interval(secs=>$3),$4,$5,$6,$7,$8,NULL)",uuid4(),tenant,i,kind,delta,reserve,after,reservation)
  await db.execute("INSERT INTO wallet_ledger VALUES($1,$2,'GBP',now(),'TOPUP',999,0,999,NULL,NULL)",uuid4(),other)
  await db.execute("INSERT INTO billing_disputes(id,tenant_id,shipment_id,invoice_reference,findings,baseline,invoice_line,estimated_overcharge,currency,email_draft) VALUES($1,$2,$3,'=UNTRUSTED','[]','{}','{}',2,'GBP','Review recorded evidence')",dispute,tenant,shipment)
  app=FastAPI();app.state.finance=NS(pool=db);app.state.settings=NS()
  async def auth(x_role:str=Header(default='OWNER'),x_other:bool=Header(default=False)):
   return NS(role=x_role,tenant_id=other if x_other else tenant,user_id=user,assistance_session_id=None)
  router=APIRouter(prefix='/api/v1/billing');ledger_routes(router,auth);app.include_router(router)
  app.include_router(build_router(auth))
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://billing.test') as client:
   yield NS(db=db,client=client,tenant=tenant,other=other,shipment=shipment,dispute=dispute)
 finally:
  process.stdin.close();await process.wait()

@pytest.mark.asyncio
async def test_ledger_filters_cursor_and_exact_balance(world):
 c=world.client;r=await c.get('/api/v1/billing/wallet-ledger?limit=1');assert r.status_code==200,r.text
 data=r.json();assert data['wallet']['available']=='83' and data['entries'][0]['entry_type']=='CAPTURE'
 assert data['month_to_date']['shipping_gross']=='12' and data['month_to_date']['recorded_shipping_vat']=='2'
 assert len(data['entries'])==1 and data['next_cursor']
 second=(await c.get('/api/v1/billing/wallet-ledger',params={'cursor':data['next_cursor']})).json()
 assert [r['entry_type'] for r in second['entries']]==['TOPUP']
 assert len((await c.get('/api/v1/billing/wallet-ledger?holds=true')).json()['entries'])==3
 assert len((await c.get('/api/v1/billing/wallet-ledger?category=LABELS')).json()['entries'])==1
 assert (await c.get('/api/v1/billing/wallet-ledger',headers={'X-Role':'DISPATCHER'})).status_code==403
 assert (await c.get('/api/v1/billing/wallet-ledger?cursor=invalid')).status_code==422

@pytest.mark.asyncio
async def test_dispute_packet_and_support_case_are_scoped_and_replay_safe(world):
 base='/api/v1/finance/billing-disputes/'+str(world.dispute)
 csv=await world.client.get(base+'/export/csv');assert csv.status_code==200 and b"'=UNTRUSTED" in csv.content
 pdf=await world.client.get(base+'/export/pdf');assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
 assert (await world.client.get(base+'/export/csv',headers={'X-Other':'true'})).status_code==404
 for _ in range(2):assert (await world.client.post(base+'/support-case')).status_code==200
 assert await world.db.fetchval('SELECT count(*) FROM support_tickets')==1
 assert await world.db.fetchval('SELECT count(*) FROM wallet_ledger')==4

@pytest.mark.asyncio
async def test_saved_benchmark_uses_customer_price_without_creating_dispute(world,monkeypatch):
 from backend import entitlements
 async def guard(*args,**kwargs):pass
 monkeypatch.setattr(entitlements,'guard_feature',guard)
 raw=f'upstream_shipment_id,currency,invoice_weight_kg,wholesale_cost,residential_fee,easyinvio_shipment_id\nCOMPETITOR-1,GBP,2,15,0,{world.shipment}\n'
 response=await world.client.post('/api/v1/finance/audit-invoice-upload',data={'invoice_reference':'COMP-1','mode':'SAVINGS'},files={'file':('invoice.csv',raw.encode(),'text/csv')})
 assert response.status_code==200,response.text
 row=response.json()['results'][0];assert Decimal(row['expected_amount'])==12 and Decimal(row['estimated_overcharge'])==3
 assert await world.db.fetchval('SELECT count(*) FROM billing_disputes')==1

def test_optional_benchmark_column_can_be_blank():
 rows=parse_statement(b'upstream_shipment_id,currency,invoice_weight_kg,wholesale_cost,residential_fee,easyinvio_shipment_id\nREF,GBP,2,12,0,\n','invoice.csv')
 assert rows[0].easyinvio_shipment_id is None


@pytest.mark.asyncio
async def test_surcharge_audit_persists_once_and_revised_evidence_conflicts(world):
    header='upstream_shipment_id,currency,invoice_weight_kg,wholesale_cost,residential_fee\n'
    async def upload(amount,role='OWNER'):
        return await world.client.post('/api/v1/finance/audit-invoice-upload',headers={'X-Role':role},
            data={'invoice_reference':'INVOICE-1'},files={'file':('invoice.csv',(header+'TRACK-1,GBP,2,'+amount+',0\n').encode(),'text/csv')})
    first=await upload('15');assert first.status_code==200,first.text
    assert first.json()['results'][0]['status']=='FLAGGED'
    second=await upload('15');assert second.json()['results'][0]['dispute_id']==first.json()['results'][0]['dispute_id']
    assert (await upload('17')).status_code==409
    assert (await upload('15','DISPATCHER')).status_code==403
    assert await world.db.fetchval('SELECT count(*) FROM billing_disputes')==2
    assert await world.db.fetchval('SELECT count(*) FROM wallet_ledger')==4
