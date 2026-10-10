import unittest
from uuid import uuid4
from pydantic import ValidationError
from tests import test_admin_portal as fixtures
from backend.admin_management import CarrierCreate, CarrierUpdate, validate_endpoint
from types import SimpleNamespace
from fastapi import HTTPException
from fastapi.testclient import TestClient
import main,json
from datetime import datetime,timedelta,timezone
from tests import test_logistics as logistics

class EnterpriseSecurityTests(unittest.TestCase):
    setUp=fixtures.AdminHTTPTests.setUp
    tearDown=fixtures.AdminHTTPTests.tearDown
    token=fixtures.AdminHTTPTests.token
    headers=fixtures.AdminHTTPTests.headers
    def test_all_management_routes_reject_missing_and_customer_tokens(self):
        uid=str(uuid4())
        routes=[('GET','tenants',None),('GET','carriers',None),('GET','margins',None),('GET','transactions',None),
            ('DELETE',f'carriers/{uid}',None),('DELETE',f'margins/{uid}',None),
            ('PATCH',f'carriers/{uid}',{'is_active':False}),
            ('PUT',f'margins/{uid}',{'tenant_id':uid,'markup_type':'PERCENTAGE','markup_value':'20'}),
            ('POST','carriers',{'tenant_id':uid,'account_name':'Test','aggregator':'EASYPOST','api_base_url':'https://api.easypost.com/v2','api_key':'test'})]
        forged={'Authorization':'Bearer '+self.token(self.customer,app_metadata={'role':'SUPER_ADMIN','platform_admin':True})}
        for method,path,body in routes:
            with self.subTest(method=method,path=path):
                self.assertEqual(self.client.request(method,'/api/v1/admin/'+path,json=body).status_code,401)
                self.assertEqual(self.client.request(method,'/api/v1/admin/'+path,json=body,headers=forged).status_code,403)
        self.assertEqual(self.connection.calls,[])
    def test_endpoint_allowlist_and_strict_carrier_parameters(self):
        settings=SimpleNamespace(regional_allowed_origins=['https://regional.example.test'])
        validate_endpoint('EASYPOST','https://api.easypost.com/v2',settings)
        for url in ['http://127.0.0.1','https://unapproved.example','https://user:pwd@regional.example.test']:
            with self.assertRaises(HTTPException):validate_endpoint('REGIONAL',url,settings)
        for data in [{'is_active':'false'},{'is_active':True,'priority':True},{'is_active':True,'timeout_seconds':121}]:
            with self.assertRaises(ValidationError):CarrierUpdate(**data)
        body=CarrierCreate(tenant_id=uuid4(),account_name='Test',aggregator='EASYPOST',api_base_url='https://api.easypost.com/v2',api_key='never-return-this')
        self.assertNotIn('never-return-this',body.model_dump_json())

class WarehouseBoundaryTests(unittest.TestCase):
    def tearDown(self):main.app.dependency_overrides.clear()
    def test_operational_responses_exclude_wallet_and_wholesale_data(self):
        context=main.TenantContext(uuid4(),uuid4(),'DISPATCHER','fixture')
        main.app.state.local_preview=False
        main.app.dependency_overrides[main.authenticate]=lambda:context
        now=datetime.now(timezone.utc)
        quote=main.RatingResponse(request_id=uuid4(),currency='GBP',quoted_at=now,expires_at=now+timedelta(minutes=5),partial=False,issues=[],rates=[main.ClientRate(provider='EASYPOST',account_id=uuid4(),upstream_shipment_id='sample',upstream_rate_id='rate',carrier_code='DHL',service_code='express',currency='GBP',client_price_ex_tax='24.00',delivery_days=2,fee_breakdown={'wholesale_total':'20.00','platform_markup':'4.00'})])
        async def quote_service(*args):return quote
        main.app.state.rating=SimpleNamespace(quote=quote_service)
        row={'id':uuid4(),'tenant_id':context.tenant_id,'status':'IN_TRANSIT','currency':'GBP','final_client_price':'24.00','tracking_number':'TEST','logistics_metadata':json.dumps({'carrier':'DHL','invoice_baseline':{'base_cost':'20.00'},'automation_cost':'20.00'})}
        connection=logistics.FakeConnection([row])
        async def summary(sql,*args):
            self.assertNotIn('public.wallets',sql)
            return {'package_count':3,'available':'1000.00'}
        connection.fetchrow=summary
        main.app.state.finance=SimpleNamespace(pool=SimpleNamespace(acquire=lambda:logistics.Acquire(connection)))
        client=TestClient(main.app)
        result=client.post('/v1/rates',json=logistics.payload())
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['rates'][0]['fee_breakdown'],{'source':'financial_role_required'})
        self.assertEqual(quote.rates[0].fee_breakdown['wholesale_total'],'20.00')
        manifest=client.get('/api/v1/shipments/manifest').json()['shipments'][0]
        self.assertEqual(manifest['metadata'],{'carrier':'DHL'})
        self.assertEqual(client.get('/api/v1/dispatch/summary').json(),{'package_count':3})
