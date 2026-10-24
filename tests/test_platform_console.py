"""Read-only business reporting, environment isolation and public connection metadata."""
import unittest
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from backend.admin_management import router
from backend.admin_portal import authenticate_platform_operator
from backend.dashboard_portal import build_router

class DB:
 def __init__(self):self.calls=[];self.tenant=uuid4()
 @asynccontextmanager
 async def acquire(self):yield self
 @asynccontextmanager
 async def transaction(self,**kwargs):yield
 async def fetchval(self,sql,*args):self.calls.append((sql,args));return 1
 async def fetch(self,sql,*args):
  self.calls.append((sql,args))
  if "date_trunc('month'" in sql:return [{'month':date(2026,9,1),'currency':'GBP','labels':2,'packages':3,'gross_revenue':Decimal('20.25'),'gross_markup':Decimal('2.75')}]
  if 'AS gross_revenue' in sql:return [{'tenant_id':self.tenant,'company_name':'Example Shop','currency':'GBP','labels':2,'packages':3,'gross_revenue':Decimal('20.25'),'gross_markup':Decimal('2.75')}]
  if 'AS wallet_balance' in sql:return [{'currency':'GBP','wallets':1,'wallet_balance':Decimal('100.00'),'reserved_balance':Decimal('8.10')}]
  if 'AS shipments' in sql:return [{'status':'BOOKED','shipments':2},{'status':'FAILED','shipments':1}]
  if 'public.ecommerce_stores' in sql:return [{'id':uuid4(),'tenant_id':self.tenant,'company_name':'Example Shop','platform':'SHOPIFY','credentials_saved':True,'is_active':True,'imported_orders':3,'last_import_at':None}]
  if 'public.wallet_ledger' in sql:return [{'company_name':'Example Shop','is_sandbox':False,'entry_type':'CAPTURE','balance_delta':Decimal('-8.10'),'reserved_delta':Decimal('-8.10'),'balance_after':Decimal('91.90'),'reserved_after':Decimal('0.00'),'currency':'GBP'}]
  if 'hubspot_sync_jobs' in sql:return [{'tenant_id':self.tenant,'company_name':'Example Shop','crm_queued':True,'crm_blocked':False,'crm_error':None}]
  return []

class ConsoleTests(unittest.TestCase):
 def setUp(self):
  self.db=DB();self.app=FastAPI();self.app.state.finance=SimpleNamespace(pool=self.db);self.app.state.hubspot=None
  self.app.include_router(router);self.app.include_router(build_router(lambda:None))
  async def staff():return SimpleNamespace(user_id=uuid4(),role='AGENT')
  self.app.dependency_overrides[authenticate_platform_operator]=staff
  self.client=TestClient(self.app)
 def tearDown(self):self.client.close()
 def test_marketplaces_are_environment_scoped_and_exclude_credentials(self):
  response=self.client.get('/api/v1/admin/marketplaces?environment=SANDBOX&search=Example')
  self.assertEqual(response.status_code,200,response.text)
  self.assertTrue(response.json()['stores'][0]['credentials_saved'])
  sql,args=self.db.calls[-1];self.assertEqual(args,(True,'Example',200));self.assertIn('w.tenant_id=s.tenant_id',sql)
  self.assertNotIn('credentials_ciphertext',sql);self.assertNotIn('credential_key_id',response.text)
  self.assertEqual(self.client.get('/api/v1/admin/marketplaces?environment=WRONG').status_code,422)
 def test_crm_distinguishes_disabled_processing_from_queued_work(self):
  response=self.client.get('/api/v1/admin/tenants')
  self.assertFalse(response.json()['crm']['enabled']);self.assertTrue(response.json()['tenants'][0]['crm_queued'])
  self.app.state.hubspot=SimpleNamespace(client=SimpleNamespace(settings=SimpleNamespace(hubspot_environment='SANDBOX')))
  response=self.client.get('/api/v1/admin/tenants')
  self.assertEqual(response.json()['crm'],{'enabled':True,'environment':'SANDBOX'})
 def test_business_health_is_decimal_safe_scoped_and_not_net_profit(self):
  response=self.client.get('/api/v1/admin/analytics/dashboard?start_date=2026-09-01&end_date=2026-09-30&environment=SANDBOX')
  self.assertEqual(response.status_code,200,response.text);health=response.json()['business_health']
  self.assertEqual(health['monthly'][0]['gross_revenue'],'20.25')
  self.assertEqual(health['top_clients'][0]['tenant_id'],str(self.db.tenant))
  self.assertEqual(health['wallet_exposure'][0]['reserved_balance'],'8.10')
  self.assertIn('net profit is unavailable',response.json()['margin_basis'])
  for sql,args in self.db.calls:
   if 'date_trunc' in sql or 'AS gross_revenue' in sql or 'AS shipments' in sql:self.assertIs(args[2],True)
   self.assertNotIn('UPDATE ',sql);self.assertNotIn('INSERT ',sql)

 def test_ledger_scope_and_historical_balances_are_explicit(self):
  response=self.client.get('/api/v1/admin/transactions?environment=PRODUCTION')
  self.assertEqual(response.status_code,200,response.text)
  entry=response.json()['transactions'][0]
  self.assertEqual(entry['balance_delta'],'-8.10');self.assertEqual(entry['balance_after'],'91.90');self.assertEqual(entry['reserved_after'],'0.00')
  self.assertEqual(self.db.calls[-1][1],(None,False))
  self.client.get('/api/v1/admin/transactions?environment=SANDBOX');self.assertEqual(self.db.calls[-1][1],(None,True))


class ConsentStatusTests(unittest.TestCase):
 def setUp(self):
  from backend.support_delivery import build_router as consent_router
  self.db=DB();self.context=SimpleNamespace(tenant_id=uuid4(),user_id=uuid4(),role='OWNER')
  self.app=FastAPI();self.app.state.finance=SimpleNamespace(pool=self.db)
  async def identity():return self.context
  self.app.include_router(consent_router(identity));self.client=TestClient(self.app)
 def tearDown(self):self.client.close()
 def test_consent_read_is_for_current_recipient_only(self):
  response=self.client.get('/api/v1/support/whatsapp/consent')
  self.assertEqual(response.status_code,200,response.text);self.assertFalse(response.json()['eligible'])
  sql,args=self.db.calls[-1];self.assertEqual(args,(self.context.tenant_id,self.context.user_id))
  self.assertIn('u.auth_user_id=$2',sql);self.assertIn('b.verified_at IS NOT NULL',sql)
  self.assertNotIn('UPDATE ',sql)
 def test_unprivileged_roles_cannot_view_or_change_merchant_consent(self):
  for role in ['DISPATCHER','ACCOUNTANT','AGENT','SUPER_ADMIN']:
   self.context.role=role
   self.assertEqual(self.client.get('/api/v1/support/whatsapp/consent').status_code,403)
   self.assertEqual(self.client.post('/api/v1/support/whatsapp/consent',json={'notification_opt_in':True}).status_code,403)
  self.assertEqual(self.db.calls,[])
