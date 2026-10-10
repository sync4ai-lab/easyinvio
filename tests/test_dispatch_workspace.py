import asyncio
import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from pypdf import PdfReader

from backend.dispatch_workspace import build_router, poll_shopify, suggested_order
from backend.dispatch_pdf import bundle_shipments, invoice_pdf, merge_pdfs, fetch_pdf, PrintSettings
from backend.ecommerce_connectors import StoreConnector
from backend.ecommerce_sync import parsed_order, StoreOrder
from backend.automation_freight_engine import Order, customs_matrix
from tests.test_automation_freight import order, address


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def declaration(self):
        data=order()
        data.update(destination=address('US'),currency='USD',customs_signer='Test Reviewer',hs_codes_reviewed=True,
            items=[{'description':'Cotton T-shirt <not markup>','quantity':2,'unit_value':'12.35',
                    'unit_weight_kg':'0.200','origin_country':'GB','hs_code':'610910'}])
        return customs_matrix(uuid4(),Order.model_validate(data),{})

    async def test_combined_pdf_preserves_label_and_adds_invoice(self):
        from reportlab.pdfgen import canvas
        label=BytesIO();c=canvas.Canvas(label,pagesize=(288,432));c.drawString(20,400,'CONTROLLED LABEL');c.save()
        doc=self.declaration()
        row={'id':uuid4(),'status':'BOOKED','booked_at':'2026-10-10','tracking_number':'TEST123','label_storage_path':'https://labels.example.com/test.pdf',
             'customs_required':True,'customer_reference':'#1024','logistics_metadata':{'automation_customs':doc}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=label.getvalue(),headers={'content-type':'application/pdf'}))) as client:
            pdf=await bundle_shipments([row],client=client,hosts=['labels.example.com'])
            doc['postal_form']='CN23'
            with self.assertRaises(HTTPException) as error:await bundle_shipments([row],client=client,hosts=['labels.example.com'])
            self.assertEqual(error.exception.status_code,409)
            doc['postal_form']=None
        reader=PdfReader(BytesIO(pdf));self.assertEqual(len(reader.pages),2)
        self.assertEqual(int(reader.pages[0].mediabox.width),288)
        self.assertIn('CONTROLLED LABEL',reader.pages[0].extract_text())
        self.assertIn('24.70',reader.pages[1].extract_text())
        self.assertIn('Cotton T-shirt <not markup>',reader.pages[1].extract_text())
        from pathlib import Path
        Path('output/pdf').mkdir(parents=True,exist_ok=True)
        Path('output/pdf/dispatcher-journey-test.pdf').write_bytes(pdf)

    async def test_pdf_boundaries_no_fake_or_missing_postal_forms(self):
        doc=self.declaration();doc['postal_form']='CN23'
        row={'id':uuid4(),'status':'QUOTED','booked_at':None,'tracking_number':None,'label_storage_path':None,'customs_required':True,'logistics_metadata':{}}
        with self.assertRaises(HTTPException) as e:await bundle_shipments([row],hosts=[])
        self.assertEqual(e.exception.status_code,409)
        client=AsyncMock()
        for url in ['http://labels.example.com/a.pdf','https://127.0.0.1/a.pdf','https://labels.example.com@evil.com/a.pdf','https://labels.example.com:8080/a.pdf','https://labels.example.com:bad/a.pdf']:
            with self.assertRaises(HTTPException):await fetch_pdf(client,url,['labels.example.com'])
        client.stream.assert_not_called()
        with self.assertRaises(ValueError):PrintSettings(carrier_pdf_hosts=['127.0.0.1'])
        doc['ready_for_provider']=False
        with self.assertRaises(HTTPException):invoice_pdf('test',doc)
        with self.assertRaises(HTTPException):merge_pdfs([b'not a PDF'])

    async def test_shopify_pagination_isolated_import_failure_and_replay(self):
        config=StoreConnector(tenant_id=uuid4(),auth_user_id=uuid4(),platform='SHOPIFY',webhook_secret='x'*32,
            shop_domain='warehouse-test.myshopify.com',access_token='test-token',live_import=True,sku_unit_grams={'TEE':'200'})
        store_id=uuid4();calls=[];imports=[]
        def transport(request):
            payload=json.loads(request.content);calls.append(payload['variables']['after'])
            index=len(calls)
            good={'id':f'gid://shopify/Order/{index}','name':f'#{index}','currencyCode':'USD','cancelledAt':None,'displayFulfillmentStatus':'UNFULFILLED',
                'shippingAddress':{'name':'Client','address1':'1 Test St','city':'New York','zip':'10001','countryCodeV2':'US','provinceCode':'NY','phone':'+12025550123'},
                'lineItems':{'pageInfo':{'hasNextPage':False},'nodes':[{'title':'Cotton T-shirt','sku':'TEE','quantity':1,'unfulfilledQuantity':1,'requiresShipping':True,'originalUnitPriceSet':{'shopMoney':{'amount':'12.35','currencyCode':'USD'}}}]}}
            bad={**good,'id':'gid://shopify/Order/invalid','lineItems':{'pageInfo':{'hasNextPage':True},'nodes':[]}}
            return httpx.Response(200,json={'data':{'orders':{'nodes':[good,bad], 'pageInfo':{'hasNextPage':index==1,'endCursor':'cursor1' if index==1 else None}}}})
        async def imported(context,payload):
            imports.append(payload);return {'status':'PENDING_IMPORT','shipment_id':str(uuid4()),'replayed':False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            service=SimpleNamespace(client=client,import_order=imported)
            result=await poll_shopify(service,SimpleNamespace(),store_id,config)
        self.assertEqual(calls,[None,'cursor1']);self.assertEqual(len(imports),2)
        self.assertEqual([r['status'] for r in result['results']],['PENDING_IMPORT','REVIEW_REQUIRED']*2)
        self.assertEqual(str(imports[0].order.line_items[0].unit_value),'12.35')
        self.assertEqual(imports[0].order.shipping_address.phone,'+12025550123')

    async def test_hundred_orders_shared_limiter_and_per_order_review(self):
        from unittest.mock import patch
        context=SimpleNamespace(role='DISPATCHER',tenant_id=uuid4())
        ids=[uuid4() for _ in range(100)]
        rows=[{'id':id_,'logistics_metadata':{'automation_order':{'index':i}} if i else {}} for i,id_ in enumerate(ids)]
        active=peak=0
        async def process(ctx,raw,mode):
            nonlocal active,peak
            active+=1;peak=max(peak,active);await asyncio.sleep(.001);active-=1
            return {'status':'QUOTED','order_reference':str(raw['index'])}
        app=FastAPI();app.state.ecommerce=SimpleNamespace();app.state.automation_freight=SimpleNamespace(order_limiter=asyncio.Semaphore(4),process=process)
        app.include_router(build_router(lambda:context))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            with patch('backend.dispatch_workspace.selected_rows',AsyncMock(return_value=rows)):
                result=await client.post('/api/v1/dispatch-workspace/process',json={'shipment_ids':[str(i) for i in ids]})
                self.assertEqual(result.status_code,200);self.assertEqual(len(result.json()['results']),100)
                self.assertEqual(result.json()['results'][0]['status'],'REVIEW_REQUIRED')
                self.assertEqual(sum(r['status']=='QUOTED' for r in result.json()['results']),99)
                self.assertEqual(peak,4)
            context.role='ACCOUNTANT'
            denied=await client.post('/api/v1/dispatch-workspace/process',json={'shipment_ids':[str(ids[0])]})
            self.assertEqual(denied.status_code,403)

    async def test_optional_customs_fields_preserve_historical_import_hash_shape(self):
        parsed=parsed_order(StoreOrder.model_validate({'id':'1','name':'#1','currency':'GBP','shipping_address':{
            'name':'Test','address1':'1 Test Street','city':'London','zip':'SW1A 1AA','country_code':'GB'},
            'line_items':[{'title':'Cotton T-shirt','quantity':1,'grams':'200'}]}))
        self.assertNotIn('phone',parsed['shipping_address']);self.assertNotIn('unit_value',parsed['line_items'][0])


if __name__=='__main__':unittest.main()
