import asyncio
import csv
import io
import unittest
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from main import RatingRequest
from backend.order_csv import CSV_FIELDS,LEGACY_CSV_FIELDS,OPTIONAL_CSV_FIELDS,CSVCustomsReview,CSVOrderService,parse_batch_csv,template
from backend.advanced_logistics import build_router


def encode(rows,fields=CSV_FIELDS):
    output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=fields)
    writer.writeheader();writer.writerows(rows)
    return output.getvalue().encode('utf-8')


def example(index=0,extended=False):
    data=template(extended)
    return dict(zip(data['columns'],data['examples'][index]))


class CSVParsingTests(unittest.TestCase):
    def test_exact_requested_header_and_all_cargo_types(self):
        self.assertEqual(','.join(CSV_FIELDS),'order_reference,cargo_type,origin_name,origin_line1,origin_city,origin_postal_code,origin_country_code,recipient_name,recipient_phone,destination_name,destination_line1,destination_city,destination_postal_code,destination_country_code,length_cm,width_cm,height_cm,weight_kg,currency,item_description,item_declared_value')
        rows=[example(i) for i in range(4)]
        road=example(2);road.update(order_reference='CSV-ROAD',cargo_type='OVERLAND_FREIGHT',length_cm='200',width_cm='120',weight_kg='900.000');rows.append(road)
        parsed=parse_batch_csv(encode(rows),RatingRequest)
        self.assertFalse(any(row.get('error') for row in parsed))
        self.assertEqual(parsed[1]['request'].dimensions,[])
        self.assertEqual(parsed[2]['weight']['billable_weight_kg'],'700.000')
        self.assertEqual(parsed[4]['weight']['billable_weight_kg'],'1750.000')
        self.assertIn('item_origin_country',parsed[3]['missing_fields'])
        self.assertIn('destination_state',parsed[3]['missing_fields'])

    def test_recipient_contact_company_phone_and_decimal_mapping(self):
        row=example();row['recipient_phone']="'+447700900001"
        data=parse_batch_csv(encode([row]),RatingRequest)[0]
        self.assertEqual(data['request'].destination.name,'Alex Example')
        self.assertEqual(data['request'].destination.company,'Example Customer')
        self.assertEqual(data['request'].destination.phone,'+447700900001')
        self.assertEqual(data['declared_value'],'25.00')
        self.assertEqual(data['hs_suggestion']['hs_code'],'610910')

    def test_invalid_rows_do_not_discard_valid_peers(self):
        good=example();bad=example(1);bad['weight_kg']='0.500'
        malformed=example(2);malformed['recipient_phone']='0044broken'
        data=parse_batch_csv(encode([good,bad,malformed]),RatingRequest)
        self.assertNotIn('error',data[0]);self.assertIn('error',data[1]);self.assertIn('error',data[2])
        duplicate=parse_batch_csv(encode([good,good]),RatingRequest)
        self.assertIn('duplicate',duplicate[1]['error'])
        class UnavailablePool:
            def acquire(self):raise OSError('Controlled unavailable database')
        service=CSVOrderService(UnavailablePool(),None)
        failure=asyncio.run(service.process(SimpleNamespace(tenant_id=uuid4()),data[0]))
        self.assertEqual(failure['status'],'failed')
        self.assertNotIn('Controlled unavailable database',failure['error'])

    def test_extended_international_customs_and_store_identity(self):
        row=example(3,True);row.update(hs_codes_reviewed='true',customs_signer='Test Signer',
            store_id=str(uuid4()),store_order_id='1024',platform='SHOPIFY')
        data=parse_batch_csv(encode([row],CSV_FIELDS+OPTIONAL_CSV_FIELDS),RatingRequest)[0]
        self.assertEqual(data['missing_fields'],[])
        order=data['order'];self.assertEqual(order.items[0].unit_value,Decimal('25'))
        self.assertEqual(order.items[0].origin_country,'GB');self.assertEqual(order.destination['state'],'NY')
        self.assertEqual(order.store_order_id,'1024');self.assertTrue(order.hs_codes_reviewed)
        row.update(item_quantity='3',item_net_weight_kg='0.500')
        multiple=parse_batch_csv(encode([row],CSV_FIELDS+OPTIONAL_CSV_FIELDS),RatingRequest)[0]['order']
        self.assertEqual(multiple.items[0].unit_value*multiple.items[0].quantity,Decimal('75.00'))
        row['item_net_weight_kg']='3.000'
        self.assertIn('error',parse_batch_csv(encode([row],CSV_FIELDS+OPTIONAL_CSV_FIELDS),RatingRequest)[0])

    def test_validation_boundaries_and_unknown_tenant_column(self):
        for field,value in [('item_declared_value','NaN'),('item_declared_value','-1'),('item_declared_value','1.001'),('cargo_type','UNKNOWN')]:
            row=example();row[field]=value
            self.assertIn('error',parse_batch_csv(encode([row]),RatingRequest)[0])
        with self.assertRaises(ValueError):parse_batch_csv(encode([example()|{'tenant_id':str(uuid4())}],CSV_FIELDS+('tenant_id',)),RatingRequest)
        with self.assertRaises(ValueError):parse_batch_csv(encode([example()]*1001),RatingRequest)

    def test_legacy_layout_and_bom_are_supported(self):
        source=example();row={field:source[field] for field in LEGACY_CSV_FIELDS}
        parsed=parse_batch_csv(b'\xef\xbb\xbf'+encode([row],LEGACY_CSV_FIELDS),RatingRequest)[0]
        self.assertNotIn('error',parsed);self.assertEqual(parsed['order'].cargo.cargo_type,'PARCEL')

    def test_review_requires_explicit_codes_and_boolean_confirmation(self):
        body={'items':[{'description':'Cotton T-shirt','quantity':1,'unit_value':'25.00','unit_weight_kg':'2.000','origin_country':'GB','hs_code':'610910'}],
            'customs_signer':'Test Signer','recipient_phone':'+12025550123','hs_codes_reviewed':True}
        self.assertTrue(CSVCustomsReview.model_validate(body).hs_codes_reviewed)
        for bad in [False,1,'true']:
            with self.assertRaises(ValueError):CSVCustomsReview.model_validate(body|{'hs_codes_reviewed':bad})
        body['items'][0]['hs_code']=None
        with self.assertRaises(ValueError):CSVCustomsReview.model_validate(body)


class CSVRouteTests(unittest.TestCase):
    def setUp(self):
        app=FastAPI();app.state.local_preview=True
        self.context=SimpleNamespace(tenant_id=uuid4(),user_id=uuid4(),role='OWNER')
        async def authenticate():return self.context
        app.include_router(build_router(authenticate,RatingRequest))
        self.app,self.client=app,TestClient(app)

    def test_downloaded_template_round_trips_and_stages_international(self):
        downloaded=self.client.get('/api/v1/shipments/batch-template').json()
        rows=[dict(zip(downloaded['columns'],values)) for values in downloaded['examples']]
        response=self.client.post('/api/v1/shipments/batch-preview',content=encode(rows),headers={'Content-Type':'text/csv'})
        self.assertEqual(response.status_code,200)
        result=response.json();self.assertEqual(result['quoted'],3);self.assertEqual(result['review_required'],1)
        self.assertEqual(result['saved'],0);self.assertEqual(result['bookings_created'],0)
        self.assertEqual(result['results'][3]['customs']['items'][0]['origin_country'],None)

    def test_batch_roles_and_row_dispatch_are_isolated(self):
        calls=[]
        async def process(context,row):
            calls.append((context,row));return {'row':row['row'],'order_reference':row['order_reference'],'status':'quoted','saved':True}
        self.app.state.csv_orders=SimpleNamespace(automation=SimpleNamespace(order_limiter=asyncio.Semaphore(2)),process=process)
        response=self.client.post('/api/v1/shipments/batch',content=encode([example()]),headers={'Content-Type':'text/csv'})
        self.assertEqual(response.json()['saved'],1);self.assertEqual(calls[0][0].tenant_id,self.context.tenant_id)
        self.context.role='ACCOUNTANT'
        self.assertEqual(self.client.post('/api/v1/shipments/batch',content=encode([example()]),headers={'Content-Type':'text/csv'}).status_code,403)
        self.assertEqual(len(calls),1)

    def test_review_preview_never_accepts_unreviewed_customs(self):
        row=example(3,True);parsed=parse_batch_csv(encode([row],CSV_FIELDS+OPTIONAL_CSV_FIELDS),RatingRequest)[0]
        order=parsed['order'].model_dump(mode='json')
        self.assertEqual(self.client.post('/api/v1/shipments/batch-review-preview',json=order).status_code,422)
        order.update(hs_codes_reviewed=True,customs_signer='Test Signer')
        response=self.client.post('/api/v1/shipments/batch-review-preview',json=order)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['status'],'quoted')
        self.assertTrue(response.json()['customs']['ready_for_provider']);self.assertFalse(response.json()['saved'])


if __name__=='__main__':unittest.main()
