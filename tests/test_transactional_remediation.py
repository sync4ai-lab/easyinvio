import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
from types import SimpleNamespace
import unittest
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend.dispatch_realtime import DispatchUpdates, build_router as realtime_router
from backend.ecommerce_connectors import StoreConnector, normalize_shopify
from backend.ecommerce_inbound import amazon_order, fetch_amazon_order, AmazonInbound
from backend.invoice_upload import StatementLine, compare_line, parse_statement, build_router


class StatementTests(unittest.TestCase):
    def test_native_shopify_nullable_fields_and_missing_native_weights(self):
        config=StoreConnector(tenant_id=uuid4(),auth_user_id=uuid4(),platform='SHOPIFY',
            shop_domain='synthetic-shop.myshopify.com',webhook_secret='x'*32,sku_unit_grams={'TEE':'200'})
        order={'shipping_address':{'address2':None,'phone':None},'line_items':[{'sku':'TEE','quantity':2,'price':'12.50'}]}
        mapped=normalize_shopify(order,config)
        self.assertEqual(mapped['shipping_address']['phone'],'')
        self.assertEqual(mapped['line_items'][0]['grams'],'200')
        self.assertEqual(mapped['line_items'][0]['unit_value'],'12.50')
        order['line_items'][0]['sku']='UNKNOWN'
        with self.assertRaises(ValueError):normalize_shopify(order,config)
    def line(self, **changes):
        return StatementLine.model_validate({'upstream_shipment_id':'shipment-native-1','currency':'GBP',
            'invoice_weight_kg':'1.100','wholesale_cost':'20.00','residential_fee':'3.00', **changes})

    def snapshot(self, **changes):
        return {'parcel_weight_kg':Decimal('1.000'),'wholesale_cost':Decimal('15.00'),'currency':'GBP',
            'logistics_metadata':{'address_verification':{'verified':True,'is_commercial':True}}, **changes}

    def test_exact_threshold_no_double_counting(self):
        findings, baseline, amount, draft = compare_line(self.line(), self.snapshot())
        self.assertEqual([f['code'] for f in findings], ['RESIDENTIAL_FEE_ON_VERIFIED_COMMERCIAL_ADDRESS','WHOLESALE_COST_EXCEEDS_SNAPSHOT'])
        self.assertEqual(amount, Decimal('5.00'))
        self.assertIn('not an adjudicated refund', draft)
        findings, *_ = compare_line(self.line(invoice_weight_kg='1.100001'), self.snapshot())
        self.assertEqual(findings[0]['code'], 'WEIGHT_DELTA')

    def test_unverified_address_never_becomes_commercial_evidence(self):
        findings, _, amount, _ = compare_line(self.line(wholesale_cost='15.00'), self.snapshot(logistics_metadata={}))
        self.assertFalse(findings);self.assertEqual(amount, 0)

    def test_csv_validation_duplicate_currency_and_float_rejection(self):
        header='upstream_shipment_id,currency,invoice_weight_kg,wholesale_cost,residential_fee\n'
        rows=parse_statement((header+'native-1,GBP,1.200,20.05,0.00\n').encode(),'statement.csv')
        self.assertEqual(rows[0].wholesale_cost,Decimal('20.05'))
        aliased=b'Carrier Reference,Currency Code,Billed Weight (kg),Invoice Wholesale Cost,Residential Surcharge,Tax\nnative-2,GBP,1.200,20.05,0.00,4.01\n'
        self.assertEqual(parse_statement(aliased,'statement.csv')[0].upstream_shipment_id,'native-2')
        for data in [header+'a,GBP,NaN,20,0',header+'a,GBP,not-a-number,20,0',header+'a,JPY,1,20,0',header+'a,GBP,1,20,0\na,GBP,1,20,0',header+'a,GBP,1,-20,0']:
            with self.assertRaises(HTTPException):parse_statement(data.encode(),'bad.csv')
        with self.assertRaises(HTTPException):parse_statement(b'a,b\n1,2','bad.csv')

    def test_excel_formula_and_multisheet_rejection(self):
        book=Workbook();sheet=book.active
        sheet.append(['upstream_shipment_id','currency','invoice_weight_kg','wholesale_cost','residential_fee'])
        sheet.append(['native-1','GBP',1.25,20.50,0])
        buffer=io.BytesIO();book.save(buffer)
        self.assertEqual(parse_statement(buffer.getvalue(),'statement.xlsx')[0].wholesale_cost,Decimal('20.5'))
        sheet['D2']='=10+10';buffer=io.BytesIO();book.save(buffer)
        with self.assertRaises(HTTPException):parse_statement(buffer.getvalue(),'statement.xlsx')
        book.create_sheet('second');buffer=io.BytesIO();book.save(buffer)
        with self.assertRaises(HTTPException):parse_statement(buffer.getvalue(),'statement.xlsx')


class RemediationAsyncTests(unittest.IsolatedAsyncioTestCase):
    def amazon_config(self):
        return StoreConnector(tenant_id=uuid4(),auth_user_id=uuid4(),platform='AMAZON',webhook_secret='x'*32,
            amazon_seller_id='seller-test',amazon_marketplace_ids=['market-test'],amazon_client_id='client-test',
            amazon_client_secret='private-client-test',amazon_refresh_token='private-refresh-test',sku_unit_grams={'TEE':'200'})

    def amazon_body(self):
        return {'order':{'orderId':'123-1234567-1234567','salesChannel':{'marketplaceId':'market-test'},
            'fulfillment':{'fulfilledBy':'MERCHANT','fulfillmentStatus':'UNSHIPPED'},
            'recipient':{'deliveryAddress':{'name':'Test Buyer','addressLine1':'1 Test Road','city':'London','postalCode':'SW1A 1AA','countryCode':'GB'}},
            'orderItems':[{'quantityOrdered':2,'fulfillment':{'quantityUnfulfilled':2},'product':{'sellerSku':'TEE','title':'Test shirt','price':{'unitPrice':{'amount':'15.00','currencyCode':'GBP'}}}}]}}

    async def test_amazon_authorization_native_mapping_and_unsafe_allocations(self):
        config=self.amazon_config();calls=[];body=self.amazon_body()
        def transport(request):
            calls.append(request)
            return httpx.Response(200,json={'access_token':'synthetic-access-token'}) if request.url.host=='api.amazon.com' else httpx.Response(200,json=body)
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            fetched=await fetch_amazon_order(client,config,'123-1234567-1234567')
        mapped=amazon_order(fetched,config,'123-1234567-1234567')
        self.assertEqual(mapped['line_items'][0]['grams'],'200');self.assertEqual(mapped['currency'],'GBP')
        self.assertEqual(str(calls[1].url).split('?')[0],'https://sellingpartnerapi-eu.amazon.com/orders/2026-01-01/orders/123-1234567-1234567')
        self.assertEqual(calls[1].headers['x-amz-access-token'],'synthetic-access-token')
        body['order']['fulfillment']['fulfilledBy']='AMAZON'
        self.assertIsNone(amazon_order(body,config,'123-1234567-1234567'))
        body['order']['fulfillment']['fulfilledBy']='MERCHANT';body['order']['orderItems'][0]['fulfillment']['quantityUnfulfilled']=1
        with self.assertRaises(ValueError):amazon_order(body,config,'123-1234567-1234567')
        with self.assertRaises(ValueError):amazon_order(body,config,'999-1234567-1234567')

    async def test_api_upload_financial_permission(self):
        app=FastAPI()
        async def auth():return SimpleNamespace(role='DISPATCHER')
        app.include_router(build_router(auth))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            result=await client.post('/api/v1/finance/audit-invoice-upload',data={'invoice_reference':'test'},files={'file':('statement.csv',b'a,b\n1,2','text/csv')})
        self.assertEqual(result.status_code,403)

    async def test_realtime_tenant_isolation_and_overflow_refresh(self):
        broker=DispatchUpdates(SimpleNamespace(),None)
        first,other=asyncio.Queue(maxsize=1),asyncio.Queue(maxsize=1)
        broker.connections={'tenant-one':{first},'tenant-two':{other}}
        broker.notified(None,0,'easyinvio_dispatch',json.dumps({'tenant_id':'tenant-one','shipment_id':'test','status':'EXCEPTION'}))
        self.assertEqual((await first.get())['status'],'EXCEPTION');self.assertTrue(other.empty())
        first.put_nowait({'old':True});broker.publish('tenant-one',{'type':'shipment_changed'})
        self.assertEqual(await first.get(),{'type':'refresh_required'})


class SocketAuthTests(unittest.TestCase):
    def app(self):
        app=FastAPI();app.state.settings=SimpleNamespace(provider_environment='LIVE')
        app.state.dispatch_updates=DispatchUpdates(SimpleNamespace(),None)
        async def auth(request,credentials):
            if credentials.credentials!='synthetic-token':raise HTTPException(401)
            return SimpleNamespace(tenant_id='tenant-test',role='OWNER')
        app.include_router(realtime_router(auth,lambda:['https://app.example.test']))
        return app

    def test_origin_authentication_and_no_query_tokens(self):
        with TestClient(self.app()) as client:
            for url,origin in [('/api/v1/dispatch-workspace/live','https://evil.test'),('/api/v1/dispatch-workspace/live?token=secret','https://app.example.test')]:
                from starlette.websockets import WebSocketDisconnect
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect(url,headers={'Origin':origin}):pass
            with client.websocket_connect('/api/v1/dispatch-workspace/live',headers={'Origin':'https://app.example.test'}) as socket:
                socket.send_json({'access_token':'synthetic-token'})
                self.assertEqual(socket.receive_json(),{'type':'refresh_required'})
