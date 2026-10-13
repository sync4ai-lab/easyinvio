import json
import time
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
import main
from backend.admin_management import CarrierUpdate
from backend.credential_rotation import require_recent_admin_auth
from backend.package_sets import package_charge
from backend.automation_freight_engine import Order, PurchaseUncertain
from backend.automation_three_partners import EasyPostAdapter, ShippoAdapter, SendcloudAdapter
from backend.store_returns import ShopifyReturnTracking
from tests.test_logistics import payload


def boxes():
    return [{'box_index':1,'length_cm':'30','width_cm':'20','height_cm':'10','actual_weight_kg':'3'},
            {'box_index':2,'length_cm':'60','width_cm':'40','height_cm':'40','actual_weight_kg':'2.5'}]


def request():
    value=payload();value.pop('dimensions');value.pop('weights_kg');value['multi_parcel_dimensions']=boxes()
    return main.RatingRequest.model_validate(value)


class MultiPieceTests(unittest.IsolatedAsyncioTestCase):
    def test_canonical_packages_and_exact_individual_billing(self):
        body=request();charge=package_charge(body.dimensions,body.weights_kg)
        self.assertEqual(Decimal(charge['billable_weight_kg']),Decimal('22.2'))
        self.assertEqual(Decimal(charge['actual_weight_kg']),Decimal('5.5'))
        self.assertEqual(len(body.dimensions),2)
        order=Order.model_validate({'idempotency_key':str(uuid4()),'order_reference':'MPS','origin':payload()['origin'],
            'destination':payload()['destination'],'multi_parcel_dimensions':boxes()})
        self.assertEqual(order.packages[0],order.cargo)
        self.assertEqual(order.packages[1].actual_weight_kg,Decimal('2.5'))

    def test_conflicting_snapshots_and_missing_allocation_rejected(self):
        value=payload();value['multi_parcel_dimensions']=boxes()
        with self.assertRaises(ValidationError):main.RatingRequest.model_validate(value)
        value=request().model_dump(mode='json');value['shipment_items']=[{'description':'Electric motor','quantity':1,'unit_value':'20','unit_weight_kg':'1','origin_country':'GB'}]
        with self.assertRaises(ValidationError):main.RatingRequest.model_validate(value)
        value['shipment_items'][0]['package_index']=2
        self.assertEqual(main.RatingRequest.model_validate(value).shipment_items[0]['package_index'],2)

    async def test_easypost_rates_use_independent_native_order_parcels(self):
        calls=[]
        def transport(req):
            data=json.loads(req.content)['order'];calls.append(data)
            self.assertEqual(req.url.path,'/v2/orders');self.assertEqual(len(data['shipments']),2)
            self.assertNotEqual(data['shipments'][0]['parcel'],data['shipments'][1]['parcel'])
            return httpx.Response(201,json={'id':'order_fixture','mode':'test','shipments':[{'id':'shp_one'},{'id':'shp_two'}],
                'rates':[{'id':'rate_fixture','carrier':'UPS','service':'Ground','currency':'GBP','rate':'10','delivery_days':2}]})
        account=SimpleNamespace(id=uuid4(),provider='EASYPOST',api_key='fixture',base_url='https://api.easypost.com/v2',upstream_account_id=None,timeout_seconds=10)
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            rates=await main.EasyPostStrategy(client,account).rates(request())
        self.assertTrue(rates[0].execution_details['easypost_order'])
        self.assertEqual(rates[0].execution_details['package_shipment_ids'],['shp_one','shp_two'])

    async def test_easypost_group_confirmed_only_with_all_labels(self):
        snapshot={'upstream_shipment_id':'order_fixture','upstream_rate_id':'rate_fixture','carrier_code':'UPS','service_code':'GROUND',
                  'easypost_order':True,'package_shipment_ids':['shp_one','shp_two'],'package_count':2}
        body={'id':'order_fixture','mode':'test','shipments':[{'id':identifier,'mode':'test','tracking_code':'TRACK'+str(i),
              'selected_rate':{'id':'rate_'+str(i),'carrier':'UPS','service':'Ground'},'postage_label':{'label_pdf_url':'https://files.example.com/'+str(i)+'.pdf'}}
              for i,identifier in enumerate(snapshot['package_shipment_ids'])]}
        adapter=EasyPostAdapter(None,'fixture',environment='TEST')
        result=adapter.normalize_order(body,snapshot)
        self.assertEqual(result['package_count'],2)
        self.assertEqual(result['carrier_forms'][0]['document_type'],'PACKAGE_LABEL_2')
        body['shipments'][1]['postage_label']={}
        with self.assertRaises(PurchaseUncertain):adapter.normalize_order(body,snapshot)

    async def test_shippo_retrieves_every_transaction_after_one_purchase(self):
        calls=[]
        def transport(req):
            calls.append(req.method)
            pieces=[{'object_id':'tx_'+str(i),'test':True,'status':'SUCCESS','rate':'rate_fixture','tracking_number':'T'+str(i),'label_url':'https://files.example.com/'+str(i)+'.pdf'} for i in range(2)]
            return httpx.Response(201,json=pieces[0]) if req.method=='POST' else httpx.Response(200,json={'next':None,'results':pieces})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result=await ShippoAdapter(client,'shippo_test_fixture',environment='TEST').purchase_label({'upstream_rate_id':'rate_fixture','package_count':2})
        self.assertEqual(calls,['POST','GET']);self.assertEqual(len(result['package_labels']),2)

    def test_sendcloud_payload_and_confirmation_preserve_two_boxes(self):
        adapter=SendcloudAdapter(None,'{}',environment='TEST')
        packages=[{'cargo_type':'PARCEL',**{key:value for key,value in box.items() if key!='box_index'}} for box in boxes()]
        value={'cargo':packages[0],'packages':packages,'origin':payload()['origin'],'destination':payload()['destination'],
               'order_reference':'MPS','upstream_rate_id':'dpd:home'}
        self.assertEqual(len(adapter.payload(value)['parcels']),2)
        body={'data':{'id':7,'parcels':[{'id':index,'tracking_number':'T'+str(index),'status':{'code':'ANNOUNCED'},
              'documents':[{'type':'label','link':'https://files.example.com/'+str(index)+'.pdf'}]} for index in [11,12]]}}
        self.assertEqual(adapter.normalize(body,2)['package_count'],2)
        body['data']['parcels'].pop()
        with self.assertRaises(PurchaseUncertain):adapter.normalize(body,2)

    async def test_shippo_partial_purchase_is_uncertain_not_refundable(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'status':'ERROR','object_id':'tx_partial'}))) as client:
            with self.assertRaises(PurchaseUncertain):
                await ShippoAdapter(client,'shippo_test_fixture',environment='TEST').purchase_label({'upstream_rate_id':'rate_fixture','package_count':2,'upstream_shipment_id':'shp_fixture'})

    def test_duplicate_group_tracking_and_invoice_mass(self):
        from backend.multi_label import bundle_labels
        from backend.invoice_upload import StatementLine,compare_line
        pieces=[{'upstream_id':str(index),'tracking_number':'DUPLICATE','label_url':'https://files.example.com/'+str(index)+'.pdf'} for index in range(2)]
        with self.assertRaises(PurchaseUncertain):bundle_labels(pieces,'group')
        line=StatementLine(upstream_shipment_id='order_fixture',currency='GBP',invoice_weight_kg=Decimal('5.5'),wholesale_cost=Decimal('18'),residential_fee=Decimal('0'))
        findings,baseline,amount,draft=compare_line(line,{'parcel_weight_kg':Decimal('3'),'multi_parcel_dimensions':boxes(),'wholesale_cost':Decimal('18'),'currency':'GBP','logistics_metadata':{}})
        self.assertEqual(findings,[]);self.assertEqual(Decimal(baseline['parcel_weight_kg']),Decimal('5.5'))

    def test_reauthentication_requires_recent_verified_method_not_fresh_iat(self):
        request=SimpleNamespace(state=SimpleNamespace(platform_auth_claims={'iat':time.time()}))
        with self.assertRaises(HTTPException):require_recent_admin_auth(request)
        request.state.platform_auth_claims={'amr':[{'method':'password','timestamp':time.time()-600}]}
        with self.assertRaises(HTTPException):require_recent_admin_auth(request)
        request.state.platform_auth_claims={'amr':[{'method':'password','timestamp':time.time()}]}
        require_recent_admin_auth(request)
        with self.assertRaises(HTTPException) as error:CarrierUpdate.model_validate({'is_active':True,'credentials_ciphertext':'injection'})
        self.assertEqual(error.exception.status_code,403)

    async def test_native_return_tracking_never_fulfills_forward_order(self):
        adapter=ShopifyReturnTracking(None,None)
        reverse={'id':'gid://shopify/ReverseFulfillmentOrder/1','status':'OPEN','order':{'id':'gid://shopify/Order/9'},
            'lineItems':{'pageInfo':{'hasNextPage':False},'nodes':[{'id':'gid://shopify/ReverseFulfillmentOrderLineItem/4','totalQuantity':1}]},
            'reverseDeliveries':{'pageInfo':{'hasNextPage':False},'nodes':[]}}
        adapter.graphql=AsyncMock(side_effect=[{'reverseFulfillmentOrder':reverse},{'reverseDeliveryCreateWithShipping':{'userErrors':[],'reverseDelivery':{'id':'gid://shopify/ReverseDelivery/3'}}}])
        body={'tracking_lifecycle_type':'RETURN_SHIPMENT','store_return_reference':reverse['id'],'store_order_id':'9','tracking_number':'RETURN1','return_quantity':1}
        result=await adapter.deliver(body)
        self.assertFalse(result['original_fulfillment_changed'])
        query,variables=adapter.graphql.await_args.args
        self.assertIn('notifyCustomer:false',query);self.assertNotIn('fulfillmentCreate(',query)
        adapter.graphql=AsyncMock(return_value={'reverseFulfillmentOrder':reverse})
        with self.assertRaises(HTTPException):await adapter.deliver({**body,'store_order_id':'10'})
        with self.assertRaises(HTTPException):await adapter.deliver({**body,'return_quantity':2})


if __name__=='__main__':unittest.main()
