import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfReader

import main
from backend.automation_freight_engine import Order,customs_matrix
from backend.customer_checkout import build_router,offer_context,search_tariff
from backend.dispatch_pdf import invoice_pdf


def declaration():
    order=Order.model_validate({'idempotency_key':str(uuid4()),'order_reference':'EI-TEST','invoice_reference':'EI-TEST',
        'origin':{'name':'Test Exporter','line1':'1 Warehouse Street','city':'London','postal_code':'SW1A 1AA','country_code':'GB'},
        'destination':{'name':'Test Buyer','line1':'2 Delivery Street','city':'New York','postal_code':'10001','country_code':'US'},
        'cargo':{'actual_weight_kg':'2','length_cm':'20','width_cm':'20','height_cm':'20'},'customs_currency':'USD',
        'items':[{'description':'Electric smoothing iron','hs_code':'851640','quantity':1,'unit_value':'25.00','unit_weight_kg':'1.000','origin_country':'GB'}],
        'customs_signer':'Test Shipper','hs_codes_reviewed':True,'customs_category':'OTHER','customs_category_other':'Exhibition demonstration'})
    doc=customs_matrix(uuid4(),order,{})
    doc.update(shipping_cost='62.70',shipping_currency='GBP')
    return doc


class CheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_sendcloud_categories_follow_the_official_enum(self):
        from backend.automation_three_partners import SendcloudAdapter
        from backend.automation_freight_engine import PurchaseRejected
        adapter=SendcloudAdapter(None,'{}',environment='TEST')
        doc=declaration()
        with self.assertRaises(PurchaseRejected):await adapter.inject_customs({'customs_document':doc})
        doc['category']='GIFT';doc['category_other']=None
        result=await adapter.inject_customs({'customs_document':doc})
        self.assertEqual(result['customs_information']['export_reason'],'gift')

    async def test_ambiguous_iron_box_does_not_guess(self):
        result=await search_tariff(None,'iron box')
        self.assertFalse(result['candidates']);self.assertIn('electric clothes iron',result['question'])

    async def test_official_search_not_a_mock_confidence_score(self):
        def handler(request):
            self.assertEqual(request.url.host,'www.trade-tariff.service.gov.uk')
            self.assertEqual(request.url.params['q'],'electric smoothing irons')
            return httpx.Response(200,json={'data':{'attributes':{'goods_nomenclature_match':{'commodities':[
                {'_source':{'goods_nomenclature_item_id':'8516400000','description':'Electric smoothing irons','declarable':True}}]}}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result=await search_tariff(client,'electric smoothing irons')
        self.assertEqual(result['candidates'][0]['hs_code'],'851640')
        self.assertNotIn('confidence',result['candidates'][0])
        self.assertIn('trade-tariff',result['candidates'][0]['source_url'])

    async def test_tariff_failure_never_falls_back_to_fabricated_hs(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(503))) as client:
            with self.assertRaises(HTTPException) as caught:await search_tariff(client,'electric iron')
        self.assertEqual(caught.exception.status_code,503)

    async def test_private_quote_lookup_pins_tenant_and_invoice_reference(self):
        tenant,offer,request_id=uuid4(),uuid4(),uuid4();queries=[]
        addresses=declaration()
        quote={'origin':addresses['sender'],'destination':addresses['recipient'],'weights_kg':['2'],
            'dimensions':[{'length_cm':'20','width_cm':'20','height_cm':'20'}],'currency':'GBP'}
        # Strip customs enrichment from address objects to match strict address input.
        for party in ('origin','destination'):
            quote[party]={key:value for key,value in quote[party].items() if key in {'name','line1','city','postal_code','country_code'}}
        rate=main.ClientRate(offer_id=offer,provider='EASYPOST',account_id=uuid4(),upstream_shipment_id='shp_test',upstream_rate_id='rate_test',
            carrier_code='DHL',service_code='Express',currency='GBP',client_price_ex_tax=Decimal('62.70'),delivery_days=2)
        rates=main.RatingResponse(request_id=request_id,currency='GBP',quoted_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc)+timedelta(minutes=10),partial=False,rates=[rate],issues=[])
        class Pool:
            @asynccontextmanager
            async def acquire(self):yield self
            async def fetchrow(self,sql,*args):
                queries.append((sql,args));return {'request_id':request_id,'request_payload':json.dumps(quote),'quote_payload':rates.model_dump_json()}
        data=await offer_context(SimpleNamespace(pool=Pool()),SimpleNamespace(tenant_id=tenant,role='OWNER'),offer)
        self.assertEqual(data[-2],'EI-'+request_id.hex.upper());self.assertTrue(data[-1])
        self.assertEqual(queries[0][1],(tenant,str(offer)))
        with self.assertRaises(HTTPException):await offer_context(None,SimpleNamespace(role='ACCOUNTANT'),offer)

    async def test_other_category_requires_written_reason(self):
        data=declaration();self.assertEqual(data['invoice_reference'],'EI-TEST');self.assertEqual(data['currency'],'USD')
        self.assertEqual(data['category_other'],'Exhibition demonstration')
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            Order.model_validate({'idempotency_key':str(uuid4()),'order_reference':'X','origin':{},'destination':{},
                'cargo':{'cargo_type':'LETTER','actual_weight_kg':'0.1'},'customs_category':'OTHER'})


class InvoiceAccessTests(unittest.TestCase):
    def test_customer_quote_payload_does_not_disclose_wholesale_or_margin(self):
        from backend.carrier_consolidation import public_payload
        quote={'client_price_ex_tax':'62.70','fee_breakdown':{'base_cost':'50.00','wholesale_total':'55.49',
            'platform_markup':'7.21','fuel_surcharge':'5.49'}}
        result=public_payload(quote)
        self.assertEqual(result['fee_breakdown']['label_cost'],'57.21')
        self.assertEqual(result['fee_breakdown']['fuel_surcharge'],'5.49')
        self.assertNotIn('wholesale_total',json.dumps(result));self.assertNotIn('platform_markup',json.dumps(result))
        self.assertEqual(quote['fee_breakdown']['wholesale_total'],'55.49')

    def test_invalid_optional_legacy_webhook_config_fails_closed(self):
        import os
        from unittest.mock import patch
        from backend.tracking_and_support import load_tracking_settings
        with patch.dict(os.environ,{'TRACKING_WEBHOOK_KEYS':'not-json'}):
            self.assertEqual(load_tracking_settings().tracking_webhook_keys,{})

    def test_pdf_has_brand_linked_reference_and_separate_shipping_currency(self):
        data=invoice_pdf('EI-TEST',declaration());text=''.join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)
        self.assertIn('EasyInvio.com',text);self.assertIn('Invoice reference: EI-TEST',text)
        self.assertIn('Shipping cost: 62.70 GBP',text);self.assertIn('25.00 USD',text)
        self.assertIn('Exhibition demonstration',text)

    def test_pending_and_foreign_shipments_cannot_download_invoice(self):
        tenant=uuid4();row={'customer_reference':'EI-TEST','logistics_metadata':{'automation_customs':declaration()},
            'status':'BOOKING','booked_at':None,'tracking_number':None,'reservation_status':'SUBMITTED'}
        class Pool:
            @asynccontextmanager
            async def acquire(self):yield self
            async def fetchrow(self,sql,*args):
                self.args=args;return row
        pool=Pool();app=FastAPI();app.state.partner_lifecycle=SimpleNamespace(pool=pool)
        app.include_router(build_router(lambda:SimpleNamespace(tenant_id=tenant)))
        client=TestClient(app);sid=uuid4();path='/api/v1/checkout/'+str(sid)+'/commercial-invoice.pdf'
        self.assertEqual(client.get(path).status_code,409);self.assertEqual(pool.args,(tenant,sid))
        row.update(status='BOOKED',booked_at=datetime.now(timezone.utc),tracking_number='TEST',reservation_status='CAPTURED')
        response=client.get(path);self.assertEqual(response.status_code,200);self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual(response.headers['cache-control'],'no-store')
