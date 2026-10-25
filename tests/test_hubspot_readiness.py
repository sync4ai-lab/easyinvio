import json,unittest
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
import httpx
from backend.hubspot_crm import HubSpotClient,HubSpotService,CRMError
from backend.check_hubspot import check
from scripts.hubspot_test_transactions import exercise
from tests.test_hubspot_crm import Merchant,settings

class HubSpotReadinessTests(unittest.IsolatedAsyncioTestCase):
 async def test_environment_and_missing_scopes_are_reported_together_without_writes(self):
  requests=[]
  def handler(request):
   requests.append(request)
   return httpx.Response(200,json={'portalId':12345,'accountType':'STANDARD'}) if request.url.path=='/account-info/v3/details' else httpx.Response(403,json={'category':'MISSING_SCOPES'})
  real=httpx.AsyncClient
  with patch('backend.check_hubspot.HubSpotSettings',return_value=settings()),patch('backend.check_hubspot.httpx.AsyncClient',side_effect=lambda **kw:real(transport=httpx.MockTransport(handler),**kw)):
   result=await check()
  codes=[item['code'] for item in result['checks']]
  self.assertIn('hubspot_test_account_required',codes);self.assertIn('hubspot_http_403',codes)
  self.assertFalse(result['ready']);self.assertEqual(result['writes'],0)
  self.assertTrue(all(r.method=='GET' for r in requests));self.assertNotIn('pat-local-test',json.dumps(result))
 async def test_live_fixtures_do_not_write_when_schema_permissions_are_missing(self):
  requests=[]
  def handler(request):
   requests.append(request)
   return httpx.Response(200,json={'portalId':12345,'accountType':'DEVELOPER_TEST'}) if request.url.path=='/account-info/v3/details' else httpx.Response(403,json={})
  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
   with self.assertRaises(CRMError):await exercise(http,settings())
  self.assertTrue(all(r.method=='GET' for r in requests))
 async def test_repeatable_fixture_companies_contacts_and_distinct_shipment_counts(self):
  merchant=Merchant();config=settings().model_copy(update={'hubspot_upsell_enabled':False})
  async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as http:
   first=await exercise(http,config);second=await exercise(http,config)
  self.assertEqual(first['status'],'PASS');self.assertEqual(len(merchant.records['companies']),2)
  self.assertEqual(len(merchant.records['contacts']),2);self.assertEqual(len(merchant.records['deals']),0)
  self.assertEqual(first['fixtures'],second['fixtures'])
  for company in merchant.records['companies']:
   self.assertEqual(company['properties']['veloce_package_count'],'3');self.assertEqual(company['properties']['veloce_total_shipments'],'2')
  self.assertEqual(merchant.records['contacts'][0]['properties']['firstname'],'EasyInvio')
 async def test_worker_maps_contact_details_and_real_shipment_count(self):
  class Pool:
   @asynccontextmanager
   async def acquire(self):yield self
   @asynccontextmanager
   async def transaction(self,**kwargs):yield
   async def fetchval(self,*args):return True
   async def execute(self,*args):return 'UPDATE 1'
   async def fetchrow(self,sql,*args):
    if 'revision,attempts' in sql:return {'revision':1,'attempts':0}
    if 'FROM public.tenants' in sql and 'company_profile' in sql:return {'company_name':'Example Business','company_profile':{'contact_name':'Jane Example','phone_e164':'+447700900123'},'default_currency':'GBP','billing_email':'jane@example.invalid','is_sandbox':True}
    if 'SELECT company_id' in sql:return None
    if 'SELECT balance,currency' in sql:return {'balance':Decimal('50.00'),'currency':'GBP'}
    return {'package_count':3,'shipment_count':2,'total_spend':Decimal('12.34'),'mixed_currency':0}
  merchant=Merchant();config=settings().model_copy(update={'hubspot_upsell_enabled':False})
  async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as http:
   await HubSpotService(Pool(),HubSpotClient(http,config)).process(uuid4())
  self.assertEqual(merchant.records['companies'][0]['properties']['veloce_total_shipments'],'2')
  person=merchant.records['contacts'][0]['properties']
  self.assertEqual(person['firstname'],'Jane');self.assertEqual(person['lastname'],'Example');self.assertEqual(person['phone'],'+447700900123')

 async def test_property_setup_is_explicit_repeatable_and_refuses_incompatible_schema(self):
  from scripts.setup_hubspot_properties import setup
  definitions={};writes=[]
  def handler(request):
   if request.url.path=='/account-info/v3/details':return httpx.Response(200,json={'portalId':12345,'accountType':'DEVELOPER_TEST'})
   if request.method=='POST':
    body=json.loads(request.content);definitions[body['name']]=body;writes.append(body['name']);return httpx.Response(201,json=body)
   name=request.url.path.rsplit('/',1)[-1]
   if name=='email':return httpx.Response(200,json={'type':'string','fieldType':'text'})
   return httpx.Response(200,json=definitions[name]) if name in definitions else httpx.Response(404,json={})
  config=settings().model_copy(update={'hubspot_upsell_enabled':False})
  async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
   plan=await setup(http,config);self.assertEqual(len(plan['missing_properties']),7);self.assertEqual(writes,[])
   result=await setup(http,config,apply=True);self.assertEqual(result['created_properties'],7)
   replay=await setup(http,config,apply=True);self.assertEqual(replay['created_properties'],0);self.assertEqual(len(writes),7)
   definitions['veloce_tenant_id']['hasUniqueValue']=False
   with self.assertRaises(CRMError):await setup(http,config,apply=True)
   self.assertEqual(len(writes),7)
