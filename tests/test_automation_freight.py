import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import httpx
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
import main
from backend.automation_freight_engine import Cargo,Order,AutomationService,EasyPostPurchase,PurchaseUncertain,calculate_cargo_charge,customs_matrix,generate_customs_declaration,build_router


def address(country='GB'):
    return {'name':'Warehouse','line1':'1 Example Street','city':'London','postal_code':'SW1A 1AA','country_code':country}
def order():
    return {'idempotency_key':str(uuid4()),'order_reference':'TEST-ORDER','origin':address(),'destination':address(),
            'cargo':{'cargo_type':'PARCEL','actual_weight_kg':'2.500','length_cm':'40','width_cm':'30','height_cm':'20'}}


class DB:
    def __init__(self):
        self.tenant,self.user,self.account=uuid4(),uuid4(),uuid4()
        self.calls=[];self.balance=Decimal('100');self.sandbox=False
    @asynccontextmanager
    async def acquire(self): yield self
    @asynccontextmanager
    async def transaction(self,**kwargs): yield
    async def fetchval(self,sql,*args):
        self.calls.append((sql,args))
        if 'RETURNING id' in sql:return uuid4()
        if 'public.users' in sql:return self.user
        return True
    async def fetchrow(self,sql,*args):
        self.calls.append((sql,args))
        if 'public.tenants' in sql:return {'is_sandbox':self.sandbox,'workspace_status':'ACTIVE','billing_status':'ACTIVE','billing_plan':'PREPAID_WALLET'}
        if 'public.wallets' in sql:return {'currency':'GBP','balance':self.balance,'reserved_balance':Decimal(0)}
        return None
    async def execute(self,sql,*args):self.calls.append((sql,args));return 'UPDATE 1'
    async def executemany(self,sql,rows):self.calls.extend((sql,tuple(row)) for row in rows)


class AutomationTests(unittest.IsolatedAsyncioTestCase):
    async def test_letter_and_freight_matrix(self):
        letter=Cargo(cargo_type='LETTER',actual_weight_kg='0.499',length_cm='40',width_cm='30',height_cm='20')
        self.assertIsNone(letter.length_cm)
        self.assertEqual(calculate_cargo_charge(letter)['billable_weight_kg'],'0.499')
        with self.assertRaises(ValueError):Cargo(cargo_type='LETTER',actual_weight_kg='0.500')
        with self.assertRaises(ValueError):Cargo(actual_weight_kg='2.5')
        pallet=Cargo(cargo_type='PALLET',actual_weight_kg='100',length_cm='120',width_cm='80',height_cm='100',stackable=False)
        result=calculate_cargo_charge(pallet)
        self.assertEqual(result['loading_metres'],'0.4')
        self.assertEqual(result['billable_weight_kg'],'700.000')
        self.assertEqual(result['basis'],'floor')
        parcel=calculate_cargo_charge(Cargo.model_validate(order()['cargo']))
        self.assertEqual(parcel['billable_weight_kg'],'4.800')

    async def test_decimal_and_customs_matrix(self):
        data=order();data.update(destination=address('US'),currency='USD',customs_signer='Warehouse manager',hs_codes_reviewed=True,
            sender_eori='GBTEST',recipient_vat='USTEST',postal_form='CN23',items=[{'description':'Cotton T-shirt','quantity':3,'unit_value':'12.35','unit_weight_kg':'0.200','origin_country':'GB'}])
        declaration=customs_matrix(uuid4(),Order.model_validate(data),{})
        self.assertEqual(declaration['totals']['goods_value'],'37.05')
        self.assertEqual(declaration['items'][0]['hs_code'],'610910')
        self.assertTrue(declaration['ready_for_provider'])
        self.assertIn('CN23',declaration['print_documents'])
        self.assertFalse(customs_matrix(uuid4(),Order.model_validate(order()),{})['required'])
        data['items'][0]['unit_value']=1.23
        with self.assertRaises(ValueError):Order.model_validate(data)
        with self.assertRaises(HTTPException):await generate_customs_declaration(uuid4())

    async def test_easypost_letter_has_no_fake_dimensions(self):
        account=SimpleNamespace(id=uuid4(),upstream_account_id=None)
        strategy=main.EasyPostStrategy(None,account)
        strategy.post=AsyncMock(return_value={'id':'shp_test','from_address':{'verifications':{'delivery':{'success':True}}},
            'to_address':{'verifications':{'delivery':{'success':True}}},'rates':[{'id':'rate_test','carrier':'UPS','service':'Letter','currency':'GBP','rate':'5.00'}]})
        request=main.RatingRequest(origin=address(),destination=address(),cargo_type='LETTER',weights_kg=['0.100'])
        await strategy.rates(request)
        payload=strategy.post.call_args.args[1]['shipment']['parcel']
        self.assertEqual(set(payload),{'weight'})
        self.assertTrue(strategy.post.call_args.args[1]['shipment']['to_address']['verify_strict'])

    async def test_purchase_wire_and_mode_fencing(self):
        rate=SimpleNamespace(upstream_shipment_id='shp_live',upstream_rate_id='rate_live')
        account=SimpleNamespace(base_url='https://api.easypost.com/v2',api_key='fixture')
        requests=[]
        def host(request):
            requests.append(request)
            return httpx.Response(200,json={'id':'shp_live','mode':'production','selected_rate':{'id':'rate_live'},'tracking_code':'TRACK1','postage_label':{'label_url':'https://files.example/label.pdf'},'forms':[]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(host)) as client:
            adapter=EasyPostPurchase(client)
            label=await adapter.buy(account,rate)
            self.assertEqual(label['tracking_number'],'TRACK1')
            self.assertEqual(requests[0].url.path,'/v2/shipments/shp_live/buy')
            with self.assertRaises(PurchaseUncertain):adapter.label({'mode':'test'},rate)

    def service(self):
        db=DB();now=datetime.now(timezone.utc)
        rate=main.ClientRate(provider='EASYPOST',account_id=db.account,upstream_shipment_id='shp_live',upstream_rate_id='rate_live',carrier_code='UPS',service_code='Ground',currency='GBP',client_price_ex_tax='12.00',delivery_days=None,fee_breakdown={'wholesale_total':'10.00'})
        expensive=rate.model_copy(update={'client_price_ex_tax':Decimal('15.00'),'upstream_rate_id':'rate_expensive'})
        rating=SimpleNamespace(quote=AsyncMock(return_value=SimpleNamespace(rates=[expensive,rate],quoted_at=now,expires_at=now+timedelta(minutes=5))))
        account=SimpleNamespace(id=db.account,provider='EASYPOST')
        repository=SimpleNamespace(accounts=AsyncMock(return_value=[account]))
        finance=SimpleNamespace(reserve=AsyncMock(return_value=object()),mark_submitted=AsyncMock(),finish_booking=AsyncMock())
        service=AutomationService(db,rating,finance,repository,main.RatingRequest,None,SimpleNamespace(provider_environment='LIVE',automation_purchase_enabled=True,db_pool_max_size=10))
        adapter=SimpleNamespace(buy=AsyncMock(return_value={'tracking_number':'TRACK1','label_url':'https://files.example/label.pdf','carrier_forms':[]}),reconcile=AsyncMock())
        service.adapters['EASYPOST']=adapter
        return db,service,SimpleNamespace(tenant_id=db.tenant,user_id=db.user,role='OWNER'),adapter

    async def test_cheapest_rate_and_finance_settlement(self):
        db,service,context,adapter=self.service()
        result=await service.process(context,order(),'FULFILL')
        self.assertEqual(result['status'],'BOOKED')
        self.assertEqual(adapter.buy.call_args.args[1].upstream_rate_id,'rate_live')
        service.finance.reserve.assert_awaited_once()
        service.finance.mark_submitted.assert_awaited_once()
        self.assertEqual(service.finance.finish_booking.call_args.args[1],'SUCCESS')

    async def test_prepared_quotes_persist_all_private_offers_without_purchase(self):
        db,service,context,adapter=self.service()
        result=await service.process(context,order(),'QUOTE_ONLY')
        self.assertEqual(result['status'],'QUOTED')
        stored=[args for sql,args in db.calls if 'INSERT INTO public.partner_shipping_offers' in sql]
        self.assertEqual(len(stored),2)
        self.assertEqual({row[1] for row in stored},{rate.offer_id for rate in service.rating.quote.return_value.rates})
        self.assertTrue(all(row[0]==context.tenant_id for row in stored))
        adapter.buy.assert_not_awaited()

    async def test_insufficient_credit_and_sandbox_never_purchase(self):
        for sandbox,balance,code in [(False,Decimal(0),'INSUFFICIENT_WALLET_CREDIT'),(True,Decimal('100'),'PURCHASE_DISABLED_FOR_THIS_ENVIRONMENT')]:
            db,service,context,adapter=self.service();db.sandbox=sandbox;db.balance=balance
            result=await service.process(context,order(),'FULFILL')
            self.assertEqual(result['error'],code)
            self.assertTrue(result['support_ticket_recorded'])
            adapter.buy.assert_not_awaited()
            service.rating.quote.assert_not_awaited()

    async def test_ambiguous_purchase_keeps_reservation(self):
        db,service,context,adapter=self.service();adapter.buy.side_effect=PurchaseUncertain()
        result=await service.process(context,order(),'FULFILL')
        self.assertEqual(result['status'],'RECONCILIATION_REQUIRED')
        service.finance.finish_booking.assert_not_awaited()

    async def test_bulk_99_orders_survive_one_failure(self):
        app=FastAPI();active=maximum=0
        async def process(context,row,mode):
            nonlocal active,maximum
            active+=1;maximum=max(maximum,active);await asyncio.sleep(.001);active-=1
            return {'order_reference':str(row['n']),'status':'FAILED' if row['n']==50 else 'QUOTED'}
        app.state.automation_freight=SimpleNamespace(process=process,settings=SimpleNamespace(db_pool_max_size=10))
        async def authenticate():return SimpleNamespace(role='OWNER',tenant_id=uuid4())
        app.include_router(build_router(authenticate))
        with TestClient(app) as client:
            response=client.post('/api/v1/automation/bulk-fulfill',json=[{'n':i} for i in range(100)])
        self.assertEqual(response.json()['quoted'],99)
        self.assertEqual(response.json()['failed'],1)
        self.assertLessEqual(maximum,4)


if __name__=='__main__':unittest.main()
