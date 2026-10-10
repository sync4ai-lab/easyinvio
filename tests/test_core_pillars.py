import base64
import hashlib
import hmac
import json
import time
import unittest
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from backend.ecommerce_connectors import StoreConnector,ShopifyFulfillment,normalize_woocommerce
from backend.ecommerce_sync import build_router
from backend.ecommerce_sync import EcommerceService
from backend.admin_portal import MarginCreate
from backend.sendcloud_adapter import SendcloudMethod,quote_sendcloud


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.store=uuid4()
        self.config=StoreConnector(tenant_id=uuid4(),auth_user_id=uuid4(),platform='SHOPIFY',
            webhook_secret='s'*32,shop_domain='veloce-test.myshopify.com')
        self.service=SimpleNamespace(connectors={self.store:self.config},import_order=AsyncMock(return_value={'status':'PENDING_IMPORT'}))
        app=FastAPI();app.state.ecommerce=self.service
        app.include_router(build_router(lambda:None));self.client=TestClient(app)
        self.body={'id':123,'name':'#123','currency':'GBP',
            'shipping_address':{'name':'Test','address1':'1 Road','city':'London','zip':'SW1A 1AA','country_code':'GB'},
            'line_items':[{'title':'Cotton shirt','quantity':1,'grams':'100'}]}

    def headers(self,raw):
        return {'content-type':'application/json','x-shopify-topic':'orders/paid',
            'x-shopify-shop-domain':self.config.shop_domain,
            'x-shopify-hmac-sha256':base64.b64encode(hmac.digest(b's'*32,raw,'sha256')).decode()}

    def test_shopify_signature_and_configured_tenant(self):
        raw=json.dumps(self.body).encode()
        response=self.client.post(f'/api/v1/integration/webhooks/{self.store}',content=raw,headers=self.headers(raw))
        self.assertEqual(response.status_code,201)
        context,payload=self.service.import_order.call_args.args
        self.assertEqual(context.tenant_id,self.config.tenant_id)
        self.assertEqual(context.user_id,self.config.auth_user_id)
        self.assertEqual(payload.store_id,self.store)

    def test_reject_modified_body_wrong_host_duplicate_signature_and_unconfigured(self):
        raw=json.dumps(self.body).encode();headers=self.headers(raw)
        path=f'/api/v1/integration/webhooks/{self.store}'
        self.assertEqual(self.client.post(path,content=raw+b' ',headers=headers).status_code,401)
        headers['x-shopify-shop-domain']='attacker.myshopify.com'
        self.assertEqual(self.client.post(path,content=raw,headers=headers).status_code,401)
        headers=list(self.headers(raw).items())+[('x-shopify-hmac-sha256','forged')]
        self.assertEqual(self.client.post(path,content=raw,headers=headers).status_code,401)
        self.assertEqual(self.client.post(f'/api/v1/integration/webhooks/{uuid4()}',content=raw,headers=self.headers(raw)).status_code,401)
        self.service.import_order.assert_not_called()

    def test_woocommerce_native_signature_and_verified_weights(self):
        config=StoreConnector(tenant_id=self.config.tenant_id,auth_user_id=self.config.auth_user_id,
            platform='WOOCOMMERCE',webhook_secret='s'*32,sku_unit_grams={'SKU1':'125.25'})
        self.service.connectors[self.store]=config
        data={'id':14,'number':'14','currency':'GBP','status':'processing','shipping':{'first_name':'A','last_name':'B',
            'address_1':'1 Road','city':'London','postcode':'SW1A 1AA','country':'GB'},
            'line_items':[{'name':'T-shirt','quantity':2,'sku':'SKU1'}]}
        raw=json.dumps(data).encode()
        headers={'content-type':'application/json','x-wc-webhook-topic':'order.created',
            'x-wc-webhook-signature':base64.b64encode(hmac.digest(b's'*32,raw,'sha256')).decode()}
        self.assertEqual(self.client.post(f'/api/v1/integration/webhooks/{self.store}',content=raw,headers=headers).status_code,201)
        self.assertEqual(self.service.import_order.call_args.args[1].order.line_items[0].grams,Decimal('125.25'))
        data['line_items'][0]['sku']='UNKNOWN'
        with self.assertRaises(ValueError):normalize_woocommerce(data,config)

    def test_amazon_gateway_signed_timestamp(self):
        self.service.connectors[self.store]=StoreConnector(tenant_id=self.config.tenant_id,
            auth_user_id=self.config.auth_user_id,platform='AMAZON',webhook_secret='s'*32)
        raw=json.dumps(self.body).encode();timestamp=str(int(time.time()))
        headers={'content-type':'application/json','x-veloce-timestamp':timestamp,
            'x-veloce-signature':hmac.new(b's'*32,timestamp.encode()+b'.'+str(self.store).encode()+b'.'+raw,hashlib.sha256).hexdigest()}
        path=f'/api/v1/integration/webhooks/{self.store}'
        self.assertEqual(self.client.post(path,content=raw,headers=headers).status_code,201)
        headers['x-veloce-timestamp']='0'
        self.assertEqual(self.client.post(path,content=raw,headers=headers).status_code,401)

    def test_selector_validation_and_secret_masking(self):
        model=MarginCreate(tenant_id=uuid4(),markup_type='FLAT_RATE',markup_value='5.50',
            billing_plan='POSTPAID_30_DAY',cargo_type='PALLET',min_volume_m3='0.960',max_volume_m3='2')
        self.assertEqual(model.min_volume_m3,Decimal('.960'))
        with self.assertRaises(ValueError):
            MarginCreate(tenant_id=uuid4(),markup_type='PERCENTAGE',markup_value='20',min_volume_m3='2',max_volume_m3='1')
        self.assertNotIn('s'*32,repr(self.config))
        with self.assertRaises(ValueError):
            self.config.model_copy(update={'live_delivery':True}).model_validate(self.config.model_dump()|{'live_delivery':True})


class ShopifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_letter_quotes_fail_closed_without_delivery_verification(self):
        from main import EasyPostStrategy,RatingRequest,ProviderFailure
        from tests.test_automation_freight import address
        strategy=EasyPostStrategy(None,SimpleNamespace(id=uuid4(),upstream_account_id=None))
        strategy.post=AsyncMock(return_value={'id':'shp_test','rates':[]})
        with self.assertRaises(ProviderFailure):
            await strategy.rates(RatingRequest(origin=address(),destination=address(),cargo_type='LETTER',weights_kg=['.100']))
    async def test_uncertain_delivery_is_fenced_before_http_and_never_resent(self):
        tenant,store,event=uuid4(),uuid4(),uuid4()
        state={'status':'PENDING','calls':0}
        body={'store_order_id':'123','tracking_number':'TRACK1','carrier_name':'UPS'}
        class Database:
            @asynccontextmanager
            async def acquire(self):yield self
            async def fetch(self,sql,*args):
                return [{'id':event,'store_id':store,'payload':body}] if state['status']=='PENDING' else []
            async def fetchval(self,sql,*args):
                if state['status']=='PENDING':state['status']='RECONCILIATION_REQUIRED';return event
            async def execute(self,sql,*args):state['status']='DELIVERED'
        async def merchant(request):
            self.assertEqual(state['status'],'RECONCILIATION_REQUIRED')
            state['calls']+=1
            raise httpx.ReadTimeout('Test only',request=request)
        config=StoreConnector(tenant_id=tenant,auth_user_id=uuid4(),platform='SHOPIFY',webhook_secret='s'*32,
            shop_domain='veloce-test.myshopify.com',live_delivery=True,access_token='test-token')
        async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as client:
            service=EcommerceService(Database(),connectors={store:config},client=client)
            await service.push_live(tenant,'123','TRACK1','UPS')
            await service.push_live(tenant,'123','TRACK1','UPS')
        self.assertEqual(state,{'status':'RECONCILIATION_REQUIRED','calls':1})

    async def test_confirmed_fulfillment_and_replay(self):
        calls=[]
        async def merchant(request):
            data=json.loads(request.content);calls.append(data)
            if data['query'].startswith('query'):
                return httpx.Response(200,json={'data':{'order':{'fulfillments':[],
                    'fulfillmentOrders':{'pageInfo':{'hasNextPage':False},'nodes':[{'id':'gid://shopify/FulfillmentOrder/1','status':'OPEN','assignedLocation':{'location':{'id':'location1'}}}]}}}})
            return httpx.Response(200,json={'data':{'fulfillmentCreate':{'userErrors':[],'fulfillment':{'id':'gid://shopify/Fulfillment/2','status':'SUCCESS'}}}})
        config=StoreConnector(tenant_id=uuid4(),auth_user_id=uuid4(),platform='SHOPIFY',webhook_secret='s'*32,
            shop_domain='veloce-test.myshopify.com',live_delivery=True,access_token='test-token')
        body={'store_order_id':'123','tracking_number':'TRACK1','carrier_name':'UPS','tracking_url':'https://www.ups.com/track?tracknum=TRACK1'}
        async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as client:
            adapter=ShopifyFulfillment(client,config)
            result=await adapter.deliver(body)
            self.assertEqual(result['fulfillment_state'],'SHIPPED')
            self.assertFalse(calls[1]['variables']['fulfillment']['notifyCustomer'])
            with self.assertRaises(HTTPException):await adapter.deliver(body,verify_only=True)
        self.assertEqual(len(calls),3) # Reconciliation performed only the read.

    async def test_existing_tracking_is_not_fulfilled_twice(self):
        async def merchant(request):
            return httpx.Response(200,json={'data':{'order':{'fulfillments':[{'id':'F1','status':'SUCCESS','trackingInfo':[{'number':'TRACK1'}]}]}}})
        config=StoreConnector(tenant_id=uuid4(),auth_user_id=uuid4(),platform='SHOPIFY',webhook_secret='s'*32,
            shop_domain='veloce-test.myshopify.com',live_delivery=True,access_token='test-token')
        async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as client:
            result=await ShopifyFulfillment(client,config).deliver({'store_order_id':'123','tracking_number':'TRACK1','carrier_name':'UPS'})
        self.assertTrue(result['replayed'])


class SendcloudTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_wire_format_exact_money_and_contract_dimensions(self):
        from main import RatingRequest
        from tests.test_logistics import payload
        account=SimpleNamespace(id=uuid4(),base_url='https://panel.sendcloud.sc/api/v2',
            api_key=json.dumps({'public_key':'fake-public','secret_key':'fake-secret'}),timeout_seconds=5)
        body=payload();body['destination']=body['origin'].copy();body['currency']='GBP'
        request=RatingRequest.model_validate(body)
        method=SendcloudMethod(method_id=123,carrier_code='DPD',origin_country='GB',destination_countries=['GB'],
            max_weight_kg='20',max_length_cm='100',max_width_cm='100',max_height_cm='100')
        calls=[]
        async def provider(http_request):
            calls.append(http_request)
            self.assertEqual(http_request.method,'GET')
            self.assertEqual(http_request.url.params['shipping_method_id'],'123')
            self.assertTrue(http_request.headers['authorization'].startswith('Basic '))
            return httpx.Response(200,json=[{'price':'6.50','currency':'GBP','to_country':'GB'}])
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            rates=await quote_sendcloud(client,account,request,[method])
            self.assertEqual(rates[0]['wholesale_cost'],Decimal('6.50'))
            method.max_length_cm=Decimal('1')
            self.assertEqual(await quote_sendcloud(client,account,request,[method]),[])
            with self.assertRaises(ValueError):await quote_sendcloud(client,account,request,[])
        self.assertEqual(len(calls),1)

    async def test_missing_price_is_never_invented(self):
        from main import RatingRequest
        from tests.test_logistics import payload
        body=payload();body['destination']=body['origin'].copy()
        request=RatingRequest.model_validate(body)
        account=SimpleNamespace(id=uuid4(),base_url='https://panel.sendcloud.sc/api/v2',
            api_key=json.dumps({'public_key':'fake','secret_key':'fake'}),timeout_seconds=5)
        method=SendcloudMethod(method_id=123,carrier_code='DPD',origin_country='GB',destination_countries=['GB'],
            max_weight_kg='20',max_length_cm='100',max_width_cm='100',max_height_cm='100')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=[{'price':None,'currency':None,'to_country':'GB'}]))) as client:
            self.assertEqual(await quote_sendcloud(client,account,request,[method]),[])


if __name__=='__main__':unittest.main()
