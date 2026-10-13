import unittest,copy
from unittest.mock import AsyncMock
from uuid import uuid4
from decimal import Decimal
from fastapi import HTTPException
from tests import test_payment_gateway as gateway
from backend.payment_gateway import reconcile_topup,checkout_return_base
class RecoveryTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):gateway.PaymentTests.setUp(self);self.config.allowed_origins=['https://app.easyinvio.com']
 async def paid(self):
  body,session=await gateway.PaymentTests.create(self)
  session['payment_intent']={'id':session['payment_intent'],'status':'succeeded','latest_charge':{'id':'ch_fixture','paid':True,'amount_refunded':0}}
  self.stripe.v1.checkout.sessions.retrieve_async=AsyncMock(return_value=session)
  return body,session
 async def test_paid_api_verification_and_webhook_credit_once(self):
  body,session=await self.paid();result=await reconcile_topup(self.finance,self.context,body.request_id);self.assertEqual(result['status'],'CREDITED')
  again=await reconcile_topup(self.finance,self.context,body.request_id);self.assertTrue(again['already_credited'])
  self.assertFalse(await self.finance.credit_session('evt_signed_after_api',session));self.assertEqual(len(self.c.state['ledger']),1);self.assertEqual(self.c.state['wallet']['balance'],Decimal('100'))
 async def test_unpaid_never_credits(self):
  body,session=await self.paid();session['payment_status']='unpaid';result=await reconcile_topup(self.finance,self.context,body.request_id);self.assertEqual(result['status'],'PENDING');self.assertEqual(self.c.state['wallet']['balance'],0)
 async def test_expired_checkout_never_credits(self):
  body,session=await self.paid();session.update(payment_status='unpaid',status='expired');result=await reconcile_topup(self.finance,self.context,body.request_id);self.assertEqual(result['status'],'EXPIRED');self.assertEqual(self.c.state['wallet']['balance'],0)
 async def test_refunded_charge_never_credits(self):
  body,session=await self.paid();session['payment_intent']['latest_charge']['amount_refunded']=100
  with self.assertRaises(HTTPException) as e:await reconcile_topup(self.finance,self.context,body.request_id)
  self.assertEqual(e.exception.status_code,409);self.assertEqual(self.c.state['wallet']['balance'],0)
 async def test_wrong_customer_never_credits(self):
  body,session=await self.paid();session['customer']='cus_foreign'
  with self.assertRaises(HTTPException):await reconcile_topup(self.finance,self.context,body.request_id)
  self.assertEqual(self.c.state['wallet']['balance'],0)
 async def test_wrong_amount_never_credits(self):
  body,session=await self.paid();session['amount_total']=1
  with self.assertRaises(HTTPException):await reconcile_topup(self.finance,self.context,body.request_id)
  self.assertEqual(self.c.state['wallet']['balance'],0)
 async def test_unknown_topup_never_calls_stripe(self):
  _,session=await self.paid()
  with self.assertRaises(HTTPException):await reconcile_topup(self.finance,self.context,uuid4())
  self.stripe.v1.checkout.sessions.retrieve_async.assert_not_awaited()
 def test_same_loopback_origin_preserved_without_tokens(self):
  self.assertEqual(checkout_return_base(self.config,'http://127.0.0.1:5000','success'),'http://127.0.0.1:5000/')
 def test_external_return_not_approved(self):
  with self.assertRaises(HTTPException):checkout_return_base(self.config,'https://evil.invalid','success')
 def test_query_credentials_not_allowed_in_return(self):
  with self.assertRaises(HTTPException):checkout_return_base(self.config,'http://127.0.0.1:5000/?token=secret','success')
if __name__=='__main__':unittest.main()
