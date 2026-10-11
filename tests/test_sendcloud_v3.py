"""Sendcloud v3 official wire contract and explicit capability boundaries."""
import json,unittest
from types import SimpleNamespace
from uuid import uuid4
from decimal import Decimal
import httpx
from main import RatingRequest
from tests.test_logistics import payload
from backend.sendcloud_adapter import quote_sendcloud_v3,V3_ENDPOINT
from backend.aggregator_registry import identify_aggregator,public_capabilities

class SendcloudV3Tests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.account=SimpleNamespace(id=uuid4(),base_url=V3_ENDPOINT,timeout_seconds=5,api_key=json.dumps({'public_key':'fixture-public','secret_key':'fixture-secret'}))
  self.request=RatingRequest.model_validate(payload());self.calls=[]
 def option(self,value='8.50',currency='GBP'):
  return {'code':'dpd:home','carrier':{'code':'dpd'},'quotes':[{'price':{'total':{'value':value,'currency':currency}},'lead_time':48}]}
 async def rates(self,options,status=200):
  async def provider(req):
   self.calls.append(req)
   return httpx.Response(status,json={'data':options})
  async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
   return await quote_sendcloud_v3(client,self.account,self.request)
 async def test_dynamic_discovery_wire_decimal_and_no_manual_methods(self):
  rates=await self.rates([self.option()]);self.assertEqual(rates[0]['wholesale_cost'],Decimal('8.50'));self.assertEqual(rates[0]['delivery_days'],2)
  call=self.calls[0];self.assertEqual(str(call.url),V3_ENDPOINT+'/shipping-options');self.assertEqual(call.method,'POST')
  body=json.loads(call.content);self.assertTrue(body['calculate_quotes']);self.assertEqual(body['parcels'][0]['weight']['unit'],'kg')
  self.assertIn('from_address',body);self.assertNotIn('from_country_code',body);self.assertTrue(call.headers['authorization'].startswith('Basic '))
 async def test_missing_price_currency_and_estimated_surcharges_not_invented(self):
  options=[self.option(None),self.option('8.50','EUR'),self.option()]
  options[2]['quotes'][0]['estimated_surcharges']=[{'price':{'value':'2.00','currency':'GBP'}}]
  self.assertEqual(await self.rates(options),[])
 async def test_invalid_money_and_scope_errors_fail_closed(self):
  for value in ['NaN','Infinity','not-money']:
   with self.assertRaises((ValueError,ArithmeticError)):await self.rates([self.option(value)])
  with self.assertRaises(ValueError):await self.rates([],403)
 async def test_bounds_dedup_and_service_point_options(self):
  option=self.option();option['quotes'][0]['weight']={'min':{'value':'0','unit':'kg'},'max':{'value':'2','unit':'kg'}}
  point=self.option();point['functionalities']={'last_mile':'service_point'}
  self.assertEqual(await self.rates([option,point]),[])
  self.assertEqual(len(await self.rates([self.option(),self.option()])),1)
 async def test_cargo_and_endpoint_boundaries(self):
  self.request.cargo_type='PALLET'
  with self.assertRaises(ValueError):await self.rates([])
  self.request.cargo_type='PARCEL';self.account.base_url='https://attacker.example'
  with self.assertRaises(ValueError):await self.rates([])
 def test_capabilities_report_native_lifecycle_but_not_order_management(self):
  capability=identify_aggregator(V3_ENDPOINT)
  self.assertTrue(capability.rate_lookup);self.assertTrue(capability.label_purchase);self.assertFalse(capability.order_management);self.assertTrue(capability.returns)
  self.assertEqual(len(public_capabilities()),4)
if __name__=='__main__':unittest.main()

class ConnectionVerificationTests(unittest.IsolatedAsyncioTestCase):
 async def test_server_encrypted_keys_and_read_only_probe(self):
  from contextlib import asynccontextmanager
  from cryptography.fernet import Fernet
  from pydantic import SecretStr
  from backend.platform_carriers import verify_connection
  from fastapi import HTTPException
  from unittest.mock import patch
  connection_id=uuid4();key=Fernet.generate_key()
  row={'id':connection_id,'api_base_url':V3_ENDPOINT,'credential_key_id':'v1','timeout_seconds':5,
       'credentials_ciphertext':Fernet(key).encrypt(json.dumps({'platform_id':str(connection_id),'api_key':json.dumps({'public_key':'fixture','secret_key':'fixture-secret'})}).encode())}
  class Connection:
   async def fetchrow(self,sql,*args):return row
  class Pool:
   @asynccontextmanager
   async def acquire(self):yield Connection()
  request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(credential_keys={'v1':SecretStr(key.decode())}),finance=SimpleNamespace(pool=Pool()))))
  calls=[]
  def provider(req):calls.append(req);return httpx.Response(200,json={'private':'never returned'})
  real=httpx.AsyncClient
  with patch('httpx.AsyncClient',side_effect=lambda **kwargs:real(transport=httpx.MockTransport(provider),**kwargs)):
   result=await verify_connection(connection_id,request,SimpleNamespace())
  self.assertTrue(result['authenticated']);self.assertFalse(result['label_created']);self.assertTrue(result['read_only'])
  self.assertNotIn('fixture-secret',json.dumps(result));self.assertEqual(calls[0].method,'GET');self.assertTrue(str(calls[0].url).endswith('/user/auth/metadata'))
  with self.assertRaises(HTTPException) as error:await verify_connection(uuid4(),request,SimpleNamespace())
  self.assertEqual(error.exception.status_code,503)
