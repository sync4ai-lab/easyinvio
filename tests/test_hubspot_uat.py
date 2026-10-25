"""Explicit UAT export, fixture exclusion and validation before remote writes."""
import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import httpx
from pydantic import ValidationError
from backend.hubspot_crm import HubSpotClient, HubSpotService, HubSpotSettings, tenant_crm_scope
from tests.test_hubspot_crm import Merchant, settings

class Pool:
 def __init__(self):
  self.tenant=uuid4();self.failure=None
  self.profile={'company_name':'UAT Client','company_profile':{'contact_name':'Test Contact'},'default_currency':'GBP','billing_email':'uat@example.com','is_sandbox':True}
  self.metrics={'package_count':3,'shipment_count':2,'total_spend':Decimal('12.34'),'mixed_currency':0}
 @asynccontextmanager
 async def acquire(self):yield self
 @asynccontextmanager
 async def transaction(self,**kw):yield
 async def fetchval(self,*args):return True
 async def fetchrow(self,sql,*args):
  if 'revision,attempts' in sql:return {'revision':1,'attempts':0}
  if 'company_profile' in sql:return self.profile
  if 'SELECT company_id' in sql:return None
  if 'SELECT balance,currency' in sql:return {'balance':Decimal('50.00'),'currency':'GBP'}
  return self.metrics
 async def execute(self,sql,*args):
  if 'UPDATE public.hubspot_sync_jobs' in sql:self.failure=args[3]
  return 'UPDATE 1'

class UATTests(IsolatedAsyncioTestCase):
 async def exercise(self,pool,allowed=True):
  merchant=Merchant();config=settings().model_copy(update={'hubspot_environment':'PRODUCTION','hubspot_uat_tenant_ids':[pool.tenant] if allowed else [],'hubspot_upsell_enabled':False})
  def respond(request):
   if request.url.path=='/account-info/v3/details':return httpx.Response(200,json={'portalId':12345,'accountType':'STANDARD'})
   return merchant(request)
  async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
   await HubSpotService(pool,HubSpotClient(http,config)).process(pool.tenant)
  return merchant
 async def test_only_allowlisted_uat_syncs_and_company_is_labelled_without_changing_shipping(self):
  pool=Pool();merchant=await self.exercise(pool)
  self.assertIsNone(pool.failure);self.assertTrue(pool.profile['is_sandbox'])
  company=merchant.records['companies'][0]['properties']
  self.assertEqual(company['name'],'[UAT] UAT Client');self.assertEqual(company['veloce_tenant_id'],str(pool.tenant))
  self.assertEqual(company['veloce_total_shipments'],'2');self.assertEqual(company['veloce_package_count'],'3')
 async def test_unlisted_uat_and_seed_fixtures_make_no_remote_requests(self):
  for fixture,allowed,code in [(False,False,'crm_tenant_environment_mismatch'),(True,True,'crm_fixture_excluded')]:
   pool=Pool()
   if fixture:pool.profile['company_profile']['fixture_batch']='seed-batch'
   merchant=await self.exercise(pool,allowed)
   self.assertEqual(pool.failure,code);self.assertEqual(merchant.calls,[])
 async def test_invalid_profile_or_metrics_never_create_partial_crm_records(self):
  for scenario in ['blank_name','currency','negative_spend']:
   pool=Pool()
   if scenario=='blank_name':pool.profile['company_name']='  '
   if scenario=='currency':pool.metrics['mixed_currency']=1
   if scenario=='negative_spend':pool.metrics['total_spend']=Decimal('-1.00')
   merchant=await self.exercise(pool)
   self.assertIsNotNone(pool.failure);self.assertEqual(merchant.calls,[])
 async def test_production_and_test_account_boundaries_are_preserved(self):
  tenant=uuid4();config=settings().model_copy(update={'hubspot_environment':'PRODUCTION','hubspot_uat_tenant_ids':[tenant]})
  self.assertEqual(tenant_crm_scope(config,uuid4(),False),'PRODUCTION')
  self.assertEqual(tenant_crm_scope(config,tenant,True),'UAT')
  self.assertIsNone(tenant_crm_scope(config,uuid4(),True))
  self.assertIsNone(tenant_crm_scope(config,tenant,False,fixture=True))
  self.assertIsNone(tenant_crm_scope(settings(),tenant,False))
  with self.assertRaises(ValidationError):HubSpotSettings(_env_file=None,hubspot_environment='SANDBOX',hubspot_uat_tenant_ids=[tenant])
 async def test_worker_fetches_explicit_allowlist_and_excludes_fixtures(self):
  pool=Pool();pool.calls=[]
  async def fetch(sql,*args):pool.calls.append((sql,args));return [{'tenant_id':pool.tenant}]
  pool.fetch=fetch
  config=settings().model_copy(update={'hubspot_environment':'PRODUCTION','hubspot_uat_tenant_ids':[pool.tenant]})
  client=type('Client',(),{'settings':config})();service=HubSpotService(pool,client);service.process=AsyncMock()
  with patch('backend.hubspot_crm.asyncio.sleep',side_effect=asyncio.CancelledError):
   with self.assertRaises(asyncio.CancelledError):await service.worker()
  sql,args=pool.calls[0]
  self.assertEqual(args,(False,[pool.tenant]));self.assertIn('fixture_batch',sql);self.assertIn('ANY($2::uuid[])',sql)
  service.process.assert_awaited_once_with(pool.tenant)
