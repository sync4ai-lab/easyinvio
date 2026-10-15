import unittest
from contextlib import asynccontextmanager
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from fastapi import HTTPException
from backend.bulk_checkout import CheckoutSelection,checkout_orders,review_orders
class BulkTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.tenant=uuid4();self.sid=uuid4();self.oid=uuid4();self.expires=datetime.now(timezone.utc)+timedelta(minutes=5)
  self.context=SimpleNamespace(tenant_id=self.tenant,role='OWNER')
  self.row={'id':self.sid,'status':'QUOTED','quote_expires_at':self.expires,'customer_reference':'QA-ORDER','customs_required':False,'logistics_metadata':{},'pricing_snapshot':{}}
  self.rate={'offer_id':str(self.oid),'client_price_ex_tax':'12.50','currency':'GBP','carrier_code':'DHL','service_code':'Express','account_id':str(uuid4()),'execution_details':{'secret':'must stay private'}}
  self.offer={'offer_id':self.oid,'shipment_id':self.sid,'rate_snapshot':self.rate,'expires_at':self.expires}
  self.wallet={'currency':'GBP','balance':Decimal(100),'reserved_balance':Decimal(0)}
  parent=self
  class Pool:
   @asynccontextmanager
   async def acquire(self):yield self
   async def fetch(self,sql,*args):
    if 'SELECT * FROM public.shipments' in sql:return [parent.row]
    return [parent.offer]
   async def fetchrow(self,sql,*args):
    if 'public.wallets' in sql:return parent.wallet
    return {'billing_plan':'PREPAID_WALLET','workspace_status':'ACTIVE','billing_status':'ACTIVE'}
  self.service=SimpleNamespace(pool=Pool(),automation=SimpleNamespace(settings=SimpleNamespace(provider_environment='TEST')),confirm=AsyncMock(return_value={'shipment_id':str(self.sid),'status':'BOOKED','label':{'tracking_number':'QA'}}))
 def body(self,**update):return CheckoutSelection(offers=[{'shipment_id':self.sid,'offer_id':self.oid,'expected_price':'12.50','currency':'GBP',**update}])
 async def reject(self,status,body=None):
  with self.assertRaises(HTTPException) as e:await checkout_orders(self.service,self.context,body or self.body())
  self.assertEqual(e.exception.status_code,status);self.service.confirm.assert_not_awaited()
 async def test_explicit_service_is_passed_to_native_confirmation(self):
  result=await checkout_orders(self.service,self.context,self.body());self.assertEqual(result['results'][0]['status'],'BOOKED');self.assertEqual(self.service.confirm.call_args.args[1].offer_id,self.oid)
 async def test_changed_price_stops_before_purchase(self):await self.reject(409,self.body(expected_price='11.50'))
 async def test_foreign_offer_stops_before_purchase(self):self.offer['shipment_id']=uuid4();await self.reject(404)
 async def test_expired_offer_stops_before_purchase(self):self.offer['expires_at']=datetime.now(timezone.utc)-timedelta(seconds=1);await self.reject(409)
 async def test_insufficient_total_stops_before_purchase(self):self.wallet['balance']=Decimal('12.00');await self.reject(402)
 async def test_unreviewed_customs_stops_before_purchase(self):self.row['customs_required']=True;await self.reject(409)
 async def test_wallet_currency_stops_before_purchase(self):self.wallet['currency']='USD';await self.reject(409)
 async def test_old_quote_stops_before_purchase(self):self.row['quote_expires_at']+=timedelta(seconds=1);await self.reject(409)
 async def test_failed_booking_rejects_card_before_creating_payment(self):
  from backend.card_checkout import CardCart,create_cart
  self.row['status']='FAILED'
  body=CardCart(request_id=uuid4(),offers=self.body().offers)
  with self.assertRaises(HTTPException) as error:await create_cart(self.service,self.context,body)
  self.assertEqual(error.exception.status_code,409)
  self.assertEqual(error.exception.detail['code'],'FRESH_QUOTE_REQUIRED')
  self.assertTrue(error.exception.detail['retry_requires_fresh_quote'])
  self.service.confirm.assert_not_awaited()
 async def test_structured_carrier_error_is_a_readable_bulk_result(self):
  self.service.confirm.side_effect=HTTPException(502,{'code':'CARRIER_UNAVAILABLE','message':'Carrier unavailable; credit released.'})
  result=await checkout_orders(self.service,self.context,self.body())
  self.assertEqual(result['results'][0]['error'],'Carrier unavailable; credit released.')
 async def test_booking_replay_uses_same_offer(self):
  self.row.update(status='BOOKED',pricing_snapshot={'selected_rate':{'offer_id':str(self.oid)}});self.offer['expires_at']=datetime.now(timezone.utc)-timedelta(minutes=1)
  await checkout_orders(self.service,self.context,self.body());self.service.confirm.assert_awaited_once()
 async def test_review_does_not_expose_execution_details(self):
  result=await review_orders(self.service,self.context,[self.sid]);rate=result['orders'][0]['rates'][0];self.assertNotIn('execution_details',rate);self.assertNotIn('account_id',rate)
 def test_duplicate_order_selection_rejected(self):
  b=self.body().model_dump();b['offers']*=2
  with self.assertRaises(ValueError):CheckoutSelection.model_validate(b)
if __name__=='__main__':unittest.main()
