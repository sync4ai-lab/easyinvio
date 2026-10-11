import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.datastructures import Headers, QueryParams

import main
from backend.automation_three_partners import (
    EasyPostAdapter, SendcloudAdapter, ShippoAdapter, NativePartnerService,
    NativeProviderSettings, PurchaseUncertain, decimal_json,
    native_order_key, parse_easypost_tracking, parse_sendcloud_tracking,
    parse_shippo_tracking, verify_native_signature,
)


def snapshot():
    address={'name':'Synthetic QA','line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
    return {'tenant_id':str(uuid4()),'shipment_id':str(uuid4()),'order_reference':'QA-NATIVE',
        'idempotency_key':str(uuid4()),'origin':address,'destination':address,'currency':'GBP',
        'cargo':{'cargo_type':'PARCEL','actual_weight_kg':'1.000','length_cm':'20','width_cm':'15','height_cm':'10'},
        'placed_at':datetime.now(timezone.utc).isoformat(),'items':[{'description':'Cotton shirt','quantity':3,
            'unit_value':'12.33','unit_weight_kg':'0.155','origin_country':'GB','hs_code':'610910'}]}


def request(headers=None, query=''):
    return SimpleNamespace(headers=Headers(headers or {}),query_params=QueryParams(query))


class NativeWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_customs_eori_and_item_totals_are_provider_specific(self):
        data=snapshot();data['currency']='USD';data['destination']={**data['destination'],'country_code':'US'}
        doc={'required':True,'ready_for_provider':True,'signer':'Synthetic QA','currency':'USD','incoterm':'DAP',
            'invoice_number':'QA-INVOICE','items':data['items'],'sender':{**data['origin'],'eori':'GB-SYNTHETIC'},
            'recipient':data['destination'],'totals':{'goods_value':'36.99'}}
        data['customs_document']=doc
        ep=await EasyPostAdapter(None,'synthetic',environment='TEST').inject_customs(data)
        self.assertEqual(ep['customs_info']['customs_items'][0]['value'],'36.99')
        self.assertEqual(ep['tax_identifiers'][0]['tax_id'],'GB-SYNTHETIC')
        sc=await SendcloudAdapter(None,'{}',environment='TEST').inject_customs(data)
        self.assertEqual(sc['customs_information']['tax_numbers']['sender'][0]['value'],'GB-SYNTHETIC')
        calls=[]
        def handler(req):
            body=json.loads(req.content);calls.append(req.url.path)
            if req.url.path=='/customs/items/':
                self.assertEqual(body['value_amount'],'36.99')
                self.assertEqual(body['net_weight'],'0.465')
                return httpx.Response(201,json={'object_id':'item1'})
            self.assertEqual(body['exporter_identification']['eori_number'],'GB-SYNTHETIC')
            self.assertEqual(body['items'],['item1'])
            return httpx.Response(201,json={'object_id':'customs1'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sp=await ShippoAdapter(client,'shippo_test_synthetic',environment='TEST').inject_customs(data)
        self.assertEqual(sp['customs_declaration'],'customs1')
        self.assertEqual(calls,['/customs/items/','/customs/declarations/'])

    async def test_shippo_order_uses_unversioned_endpoint_and_exact_line_values(self):
        data=snapshot()
        def handler(req):
            self.assertEqual(req.url.path,'/orders/')
            body=json.loads(req.content,parse_float=Decimal)
            self.assertEqual(body['line_items'][0]['total_price'],'36.99')
            self.assertEqual(body['placed_at'],data['placed_at'])
            self.assertEqual(body['order_status'],'UNKNOWN')
            self.assertEqual(req.headers['Authorization'],'ShippoToken shippo_test_synthetic')
            return httpx.Response(201,json={'object_id':'native1','order_number':body['order_number']})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result=await ShippoAdapter(client,'shippo_test_synthetic',environment='TEST').sync_order(data)
        self.assertEqual(result['remote_id'],'native1')

    async def test_sendcloud_orders_are_native_arrays_with_decimal_json_numbers(self):
        data=snapshot();data['sendcloud_integration_id']=7
        calls=[]
        def handler(req):
            calls.append(req.method)
            self.assertEqual(req.url.path,'/api/v3/orders' if req.method=='POST' else '/api/v3/orders/9')
            if req.method=='GET':
                return httpx.Response(200,json={'data':{'id':9,'order_id':native_order_key(data)}})
            body=json.loads(req.content,parse_float=Decimal)
            self.assertIsInstance(body,list)
            self.assertEqual(body[0]['order_details']['integration']['id'],7)
            self.assertEqual(body[0]['order_details']['order_items'][0]['unit_price']['value'],Decimal('12.33'))
            self.assertEqual(body[0]['payment_details']['total_price']['value'],Decimal('36.99'))
            return httpx.Response(201,json={'data':[{'id':9,'order_id':body[0]['order_id']}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result=await SendcloudAdapter(client,'{"public_key":"synthetic","secret_key":"synthetic"}',environment='TEST').sync_order(data)
        self.assertEqual(calls,['POST','GET'])
        self.assertEqual(result['remote_id'],'9')

    async def test_sendcloud_async_acceptance_is_not_false_completion(self):
        data=snapshot();data['sendcloud_integration_id']=7
        def handler(req):
            if req.method=='POST':return httpx.Response(201,json={'data':[{'id':9,'order_id':native_order_key(data)}]})
            return httpx.Response(404,json={'errors':[]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=SendcloudAdapter(client,'{"public_key":"synthetic","secret_key":"synthetic"}',environment='TEST')
            with self.assertRaises(PurchaseUncertain):await adapter.sync_order(data)
            self.assertEqual(adapter.last_order_id,'9')

    async def test_easypost_multi_package_order_has_explicit_nested_shipments(self):
        data=snapshot();data['packages']=[data['cargo'],data['cargo']]
        def handler(req):
            self.assertEqual(req.url.path,'/v2/orders')
            body=json.loads(req.content)['order']
            self.assertEqual(len(body['shipments']),2)
            self.assertNotIn('customs_info',body)
            self.assertEqual(body['reference'],native_order_key(data))
            return httpx.Response(201,json={'id':'order_test','mode':'test'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result=await EasyPostAdapter(client,'synthetic',environment='TEST').sync_order(data)
        self.assertEqual(result['object_type'],'Order')

    async def test_easypost_single_parcel_reuses_quoted_shipment(self):
        data=snapshot();data['upstream_shipment_id']='shp_test'
        def handler(req):
            self.assertEqual(req.method,'GET')
            self.assertEqual(req.url.path,'/v2/shipments/shp_test')
            return httpx.Response(200,json={'id':'shp_test','mode':'test'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result=await EasyPostAdapter(client,'synthetic',environment='TEST').sync_order(data)
        self.assertEqual(result['object_type'],'Shipment')

    async def test_shippo_purchase_links_previously_synced_native_order(self):
        def handler(req):
            payload=json.loads(req.content)
            self.assertEqual(req.url.path,'/transactions/')
            self.assertEqual(payload['order'],'native_order')
            return httpx.Response(201,json={'status':'SUCCESS','test':True,'rate':'rate1','object_id':'tx1',
                'tracking_number':'T1','label_url':'https://deliver.goshippo.com/test.pdf'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await ShippoAdapter(client,'shippo_test_synthetic',environment='TEST').purchase_label(
                {'upstream_rate_id':'rate1','native_order_id':'native_order'})

    async def test_sendcloud_native_fulfillment_is_absolute_idempotent_update(self):
        data=snapshot();calls=[]
        def handler(req):
            calls.append(req.method)
            if req.method=='PATCH':
                self.assertEqual(json.loads(req.content)['order_details']['status']['code'],'fulfilled')
                return httpx.Response(200,json={})
            return httpx.Response(200,json={'data':{'id':9,'order_id':native_order_key(data)}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await SendcloudAdapter(client,'{"public_key":"synthetic","secret_key":"synthetic"}',environment='LIVE').confirm_order_fulfillment('9',data,{'tracking_number':'T1'})
        self.assertEqual(calls,['GET','PATCH'])


class NativeTrackingTests(unittest.TestCase):
    def test_all_native_signature_formats_and_tampering(self):
        raw=b'{"event":"synthetic"}';secret='s'*32;timestamp=1700000000
        signatures={
            'EASYPOST':('x-hmac-signature','hmac-sha256-hex='+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()),
            'SENDCLOUD':('sendcloud-signature',hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()),
            'SHIPPO':('shippo-auth-signature','t='+str(timestamp)+',v1='+hmac.new(secret.encode(),str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest())}
        for provider,(header,value) in signatures.items():
            req=request({header:value})
            verify_native_signature(req,raw,provider,'HMAC',secret,now=timestamp)
            with self.assertRaises(HTTPException):verify_native_signature(req,raw+b' ',provider,'HMAC',secret,now=timestamp)

    def test_shippo_signature_age_and_duplicate_tokens_rejected(self):
        secret='s'*32;raw=b'{}';signature=hmac.new(secret.encode(),b'1.'+raw,hashlib.sha256).hexdigest()
        with self.assertRaises(HTTPException):verify_native_signature(request({'shippo-auth-signature':'t=1,v1='+signature}),raw,'SHIPPO','HMAC',secret,now=1000)
        with self.assertRaises(HTTPException):verify_native_signature(request(query='token='+secret+'&token='+secret),raw,'SHIPPO','URL_TOKEN',secret)
        verify_native_signature(request(query='token='+secret),raw,'SHIPPO','URL_TOKEN',secret)

    def test_all_native_parsers_capture_real_pod_urls_and_exceptions(self):
        timestamp=datetime.now(timezone.utc).isoformat();url='https://carrier.example.test/signature.jpg'
        ep={'id':'evt_test','description':'tracker.updated','result':{'object':'Tracker','mode':'test',
            'status':'delivered','tracking_code':'T1','updated_at':timestamp,'proof_of_delivery_url':url}}
        self.assertEqual(parse_easypost_tracking(ep,'TEST')[0].proof_of_delivery_url,url)
        sc={'action':'parcel_status_changed','timestamp':int(datetime.now(timezone.utc).timestamp()),
            'parcel':{'tracking_number':'T2','status':{'id':11,'message':'Localized description'},'proof_of_delivery_url':url}}
        self.assertEqual(parse_sendcloud_tracking(sc,{'11':'DELIVERED'})[0].proof_of_delivery_url,url)
        sp={'event':'track_updated','test':True,'data':{'tracking_number':'T3',
            'tracking_status':{'status':'FAILURE','status_date':timestamp,'status_details':'Customs postal code issue'}}}
        self.assertEqual(parse_shippo_tracking(sp,'TEST')[0].status,'EXCEPTION')
        self.assertIsNone(parse_sendcloud_tracking(sc,{}))
        ep['result']['mode']='production'
        with self.assertRaises(ValueError):parse_easypost_tracking(ep,'TEST')

    def test_decimal_encoder_never_round_trips_money_through_float(self):
        encoded=decimal_json({'amount':Decimal('12345678901234567890.123456789')})
        self.assertEqual(json.loads(encoded,parse_float=Decimal)['amount'],Decimal('12345678901234567890.123456789'))
        with self.assertRaises(ValueError):decimal_json(Decimal('NaN'))

    def test_sensitive_settings_require_strong_secrets_and_numeric_status_ids(self):
        with self.assertRaises(ValidationError):NativeProviderSettings(webhook_secret='short')
        with self.assertRaises(ValidationError):NativeProviderSettings(sendcloud_status_map={'delivered':'DELIVERED'})
        with self.assertRaises(ValidationError):NativeProviderSettings(pod_allowed_hosts=['127.0.0.1'])

    def test_native_owner_configuration_and_order_routes_require_auth(self):
        main.app.state.local_preview=False
        client=TestClient(main.app)
        root='/api/v1/admin/platform-carriers/'+str(uuid4())+'/native-settings'
        self.assertEqual(client.get(root).status_code,401)
        self.assertEqual(client.put(root,json={}).status_code,401)
        self.assertEqual(client.post('/api/v1/shipping/native-orders/sync',json={'tenant_id':str(uuid4()),'shipment_ids':[str(uuid4())]}).status_code,401)


class OrderSendFenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_webhook_resolves_tenant_from_connection_not_payload(self):
        source_id=uuid4();tenant=uuid4();account=uuid4();key=Fernet.generate_key();secret='s'*32
        source={'api_base_url':EasyPostAdapter.endpoint,'environment':'TEST','credential_key_id':'v1',
            'webhook_secret':Fernet(key).encrypt(secret.encode()),'webhook_auth':'HMAC','pod_allowed_hosts':'[]'}
        rows=[{'tenant_id':tenant,'carrier_account_id':account,'upstream_shipment_id':'shp_good','logistics_metadata':'{}'}]
        class Connection:
            async def fetchrow(self,*args):return source
            async def fetch(self,*args):return rows
        class Pool:
            @asynccontextmanager
            async def acquire(self):yield Connection()
        tracking=SimpleNamespace(ingest=AsyncMock(return_value={'applied':True}))
        service=NativePartnerService(SimpleNamespace(pool=Pool(),settings=SimpleNamespace(credential_keys={'v1':SecretStr(key.decode())})),None,tracking)
        body={'tenant_id':str(uuid4()),'id':'evt_native','description':'tracker.updated','result':{'object':'Tracker',
            'mode':'test','status':'in_transit','tracking_code':'T1','shipment_id':'shp_good','updated_at':datetime.now(timezone.utc).isoformat()}}
        async def deliver():
            raw=json.dumps(body).encode();signature='hmac-sha256-hex='+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
            class Request:
                headers=Headers({'content-type':'application/json','x-hmac-signature':signature})
                query_params=QueryParams('source='+str(source_id))
                async def stream(self):yield raw
            return await service.receive_tracking(Request())
        await deliver()
        self.assertEqual(tracking.ingest.await_args.args[1].tenant_id,tenant)
        self.assertEqual(tracking.ingest.await_args.args[1].carrier_account_id,account)
        tracking.ingest.reset_mock();rows.append(rows[0])
        with self.assertRaises(HTTPException) as error:await deliver()
        self.assertEqual(error.exception.status_code,409)
        tracking.ingest.assert_not_awaited()
        rows.pop();body['result']['shipment_id']='shp_foreign'
        with self.assertRaises(HTTPException) as error:await deliver()
        self.assertEqual(error.exception.status_code,409)
        tracking.ingest.assert_not_awaited()

    async def test_unknown_order_post_is_not_retried_and_failure_is_durable(self):
        data=snapshot();tid=__import__('uuid').UUID(data['tenant_id']);sid=__import__('uuid').UUID(data['shipment_id']);aid=uuid4();pid=uuid4();key=Fernet.generate_key()
        job={'state':'PENDING','remote_object_id':None,'payload':json.dumps({'order':{k:v for k,v in data.items() if k not in {'tenant_id','shipment_id','placed_at'}},'placed_at':data['placed_at']})}
        account={'is_active':True,'order_sync_enabled':True,'workspace_status':'ACTIVE','selected_account':aid,
            'environment':'TEST','is_sandbox':True,'sendcloud_integration_id':None,'credential_key_id':'v1',
            'platform_connection_id':pid,'api_base_url':ShippoAdapter.endpoint,
            'credentials_ciphertext':Fernet(key).encrypt(json.dumps({'platform_id':str(pid),'api_key':'shippo_test_synthetic'}).encode())}
        class Connection:
            async def fetchval(self,*args):return True
            async def fetchrow(self,sql,*args):return account if 'SELECT a.*' in sql else job
            async def execute(self,sql,*args):
                if "state='SENDING'" in sql:job['state']='SENDING'
                elif 'state=$4' in sql:job['state']=args[3]
        class Pool:
            @asynccontextmanager
            async def acquire(self):yield Connection()
        calls=[]
        def handler(req):calls.append(req.method);raise httpx.ReadTimeout('synthetic',request=req)
        automation=SimpleNamespace(pool=Pool(),settings=SimpleNamespace(provider_environment='TEST',database_environment='SANDBOX',credential_keys={'v1':SecretStr(key.decode())}),fail_ticket=AsyncMock())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service=NativePartnerService(automation,client,None)
            with self.assertRaises(HTTPException) as error:await service.sync_one(tid,sid,aid)
            self.assertEqual(error.exception.status_code,502)
            self.assertEqual(job['state'],'RECONCILIATION_REQUIRED')
            self.assertEqual((await service.sync_one(tid,sid,aid))['state'],'RECONCILIATION_REQUIRED')
        self.assertEqual(calls,['POST'])
        automation.fail_ticket.assert_awaited_once()


if __name__=='__main__':unittest.main()
