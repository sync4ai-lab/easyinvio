"""Disposable PostgreSQL acceptance for finance presentation and explicit support intake."""
import asyncio,os,json
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4
from decimal import Decimal
import pytest,pytest_asyncio,httpx
from fastapi import FastAPI,APIRouter,Header
from backend.billing_ledger import add_routes as ledger_routes
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
  CREATE TABLE support_tickets(id uuid PRIMARY KEY,tenant_id uuid,shipment_id uuid,status text,ai_summary text,ai_method text,prompt_version text,cx_request_id uuid UNIQUE,cx_kind text,issue_category text);''',mode='exec')
  await db.execute("INSERT INTO wallets VALUES($1,'GBP',88,5)",tenant)
  await db.execute("INSERT INTO shipments VALUES($1,$2,'ORDER-1',12,2,'TRACK-1','GBP',10,2,'[]','{}',now(),now()+interval '1 hour',NULL)",shipment,tenant)
  await db.execute('INSERT INTO wallet_reservations VALUES($1,$2,$3)',reservation,tenant,shipment)
  for i,(kind,delta,after,reserve) in enumerate([('TOPUP',100,100,0),('CAPTURE',-12,88,0),('RESERVE',0,88,5)]):
   await db.execute("INSERT INTO wallet_ledger VALUES($1,$2,'GBP',now()+make_interval(secs=>$3),$4,$5,$6,$7,$8,NULL)",uuid4(),tenant,i,kind,delta,reserve,after,reservation)
  await db.execute("INSERT INTO wallet_ledger VALUES($1,$2,'GBP',now(),'TOPUP',999,0,999,NULL,NULL)",uuid4(),other)
  app=FastAPI();app.state.finance=NS(pool=db);app.state.settings=NS()
  async def auth(x_role:str=Header(default='OWNER'),x_other:bool=Header(default=False)):
   return NS(role=x_role,tenant_id=other if x_other else tenant,user_id=user,assistance_session_id=None)
  router=APIRouter(prefix='/api/v1/billing');ledger_routes(router,auth);app.include_router(router)
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
