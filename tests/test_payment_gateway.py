"""Checkout and signed reconciliation contracts, without real Stripe calls."""
import asyncio
import copy
import hashlib
import hmac
import json
import time
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

import main
from backend.payment_gateway import build_router, checkout_redirect
from tests.test_sandbox_hooks import Connection, Acquire, settings


class CheckoutConnection(Connection):
    async def fetchrow(self, sql, *args):
        if 'SELECT company_name,billing_email' in sql:
            return {'company_name':'Test Company','billing_email':'test@example.invalid'}
        if 'SELECT id,status,amount,currency,credited_at' in sql:
            row = self.state['topups'].get(args[1])
            return row if row and row['tenant_id']==args[0] else None
        return await super().fetchrow(sql,*args)

    async def execute(self, sql, *args):
        if 'INSERT INTO public.wallet_topups' in sql:
            self.state['topups'][args[0]]={'id':args[0],'tenant_id':args[1],'requested_by_auth_user_id':args[2],
                'stripe_customer_id':args[3],'amount':args[4],'currency':args[5],'is_sandbox':False,'status':'PENDING',
                'stripe_session_id':None,'checkout_url':None,'credited_at':None,'created_at':datetime.now(timezone.utc)}
            return 'INSERT 1'
        if 'UPDATE public.wallet_topups SET stripe_session_id' in sql:
            self.state['topups'][args[1]].update(stripe_session_id=args[2],checkout_url=args[3]);return 'UPDATE 1'
        if 'UPDATE public.wallets SET balance=balance+' in sql:
            self.state['wallet']['balance']+=args[1];return 'UPDATE 1'
        if "UPDATE public.wallet_topups SET status='CREDITED'" in sql:
            self.state['topups'][args[1]].update(status='CREDITED',stripe_session_id=args[2],credited_at=datetime.now(timezone.utc));return 'UPDATE 1'
        return await super().execute(sql,*args)


class CheckoutStripe:
    def __init__(self, c):
        self.c=c;self.calls=[];self.sessions={}
        self.v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=self.create)),
            customers=SimpleNamespace(create_async=self.customer))
    async def create(self, params, options):
        assert self.c.depth==0
        self.calls.append((params,options))
        key=options['idempotency_key']
        return self.sessions.setdefault(key,SimpleNamespace(id='cs_test_'+params['client_reference_id'],url='https://checkout.stripe.com/c/pay/'+params['client_reference_id']))
    async def customer(self,params,options):
        assert self.c.depth==0
        self.customer_metadata=params['metadata'];return SimpleNamespace(id='cus_new_test',livemode=False)


class PaymentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tenant,self.user=uuid4(),uuid4();self.c=CheckoutConnection(self.tenant,self.user)
        self.config=settings();self.config.checkout_success_url='https://app.easyinvio.com/?payment=success'
        self.config.checkout_cancel_url='https://app.easyinvio.com/?payment=cancel';self.config.stripe_webhook_secret=SecretStr('whsec_fixture')
        self.context=main.TenantContext(self.tenant,self.user,'OWNER','test')
        self.stripe=CheckoutStripe(self.c);self.finance=main.FinanceEngine(SimpleNamespace(acquire=lambda:Acquire(self.c)),self.config,self.stripe)
        self.app=FastAPI();self.app.state.settings=self.config;self.app.state.finance=self.finance
        self.app.include_router(build_router(lambda:self.context,main.TopupRequest,main.stripe_webhook))

    async def create(self,amount='100.00'):
        body=main.TopupRequest(request_id=uuid4(),amount=amount)
        result=await self.finance.create_checkout(self.context,body)
        session={'id':result.checkout_session_id,'customer':'cus_test','mode':'payment','payment_status':'paid','livemode':False,
            'currency':'gbp','amount_total':main.to_minor_units(body.amount,'GBP'),'client_reference_id':str(body.request_id),
            'metadata':{'purpose':'wallet_topup','tenant_id':str(self.tenant),'topup_id':str(body.request_id)}}
        return body,session

    async def test_new_route_metadata_redirects_and_status(self):
        request_id=str(uuid4());payload={'tenant_id':str(self.tenant),'topup_amount':'100.00','request_id':request_id}
        with TestClient(self.app) as client:
            response=client.post('/api/v1/billing/create-checkout',json=payload)
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['url'].startswith('https://checkout.stripe.com/'))
            again=client.post('/api/v1/billing/create-checkout',json=payload)
            self.assertEqual(again.json(),response.json())
            self.assertEqual(len(self.stripe.calls),1)
            status=client.get('/api/v1/billing/topups/'+request_id).json()
            self.assertEqual(status['status'],'PENDING')
        params=self.stripe.calls[0][0]
        self.assertEqual(params['metadata'],{'tenant_id':str(self.tenant),'purpose':'wallet_topup','topup_id':request_id})
        self.assertEqual(params['line_items'][0]['price_data']['unit_amount'],10000)
        self.assertIn('payment=success',params['success_url']);self.assertIn('topup_id='+request_id,params['success_url'])
        self.assertEqual(self.c.state['wallet']['balance'],Decimal('0'))

    async def test_signed_event_credits_once_and_rejects_tampering(self):
        body,session=await self.create()
        event={'id':'evt_test','type':'checkout.session.completed','livemode':False,'data':{'object':session}}
        raw=json.dumps(event).encode();stamp=str(int(time.time()))
        digest=hmac.new(b'whsec_fixture',stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        with TestClient(self.app) as client:
            for _ in range(2):
                result=client.post('/api/v1/billing/webhooks/stripe',content=raw,headers={'stripe-signature':f't={stamp},v1={digest}'})
                self.assertEqual(result.status_code,200,result.text)
            bad=client.post('/api/v1/billing/webhooks/stripe',content=raw+b' ',headers={'stripe-signature':f't={stamp},v1={digest}'})
            self.assertEqual(bad.status_code,400)
            self.assertEqual(client.get('/api/v1/billing/topups/'+str(body.request_id)).json()['status'],'CREDITED')
        self.assertEqual(self.c.state['wallet']['balance'],Decimal('100.00'));self.assertEqual(len(self.c.state['ledger']),1)

    async def test_concurrent_events_sum_and_replay_only_once(self):
        _,s1=await self.create('100.00');_,s2=await self.create('250.00')
        result=await asyncio.gather(*(self.finance.credit_session('evt_one',s1) for _ in range(10)),self.finance.credit_session('evt_two',s2))
        self.assertEqual(sum(result),2);self.assertEqual(self.c.state['wallet']['balance'],Decimal('350.00'))
        self.assertEqual(len(self.c.state['ledger']),2)

    async def test_ledger_failure_rolls_back_balance_and_status(self):
        _,session=await self.create();before=copy.deepcopy(self.c.state);self.c.fail_ledger=True
        with self.assertRaises(RuntimeError):await self.finance.credit_session('evt_failure',session)
        self.assertEqual(self.c.state,before)

    async def test_wrong_amount_customer_currency_and_unpaid(self):
        _,session=await self.create()
        for changes in [{'amount_total':10001},{'currency':'usd'},{'customer':'cus_wrong'},{'livemode':True}]:
            with self.assertRaises(ValueError):await self.finance.credit_session('evt_wrong',{**session,**changes})
        self.assertFalse(await self.finance.credit_session('evt_unpaid',{**session,'payment_status':'unpaid'}))
        self.assertEqual(self.c.state['wallet']['balance'],Decimal('0'))

    async def test_role_tenant_mode_and_decimal_boundaries(self):
        payload={'tenant_id':str(self.tenant),'topup_amount':'100.00'}
        with TestClient(self.app) as client:
            self.assertEqual(client.post('/api/v1/billing/create-checkout',json={**payload,'tenant_id':str(uuid4())}).status_code,403)
            for value in [True,1.23,'0.99','10000.01','100.001','NaN']:
                self.assertEqual(client.post('/api/v1/billing/create-checkout',json={**payload,'topup_amount':value}).status_code,422)
            self.context=main.TenantContext(self.tenant,self.user,'DISPATCHER','test')
            self.assertEqual(client.post('/api/v1/billing/create-checkout',json=payload).status_code,403)
            self.context=main.TenantContext(self.tenant,self.user,'OWNER','test');self.config.stripe_enabled=False
            self.assertEqual(client.post('/api/v1/billing/create-checkout',json=payload).status_code,503)
        self.assertEqual(self.stripe.calls,[])

    async def test_missing_customer_is_provisioned_without_row_locks(self):
        self.c.state['tenant']['stripe_customer_id']=None
        with TestClient(self.app) as client:
            response=client.post('/api/v1/billing/create-checkout',json={'tenant_id':str(self.tenant),'topup_amount':'100.00'})
            self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.c.state['tenant']['stripe_customer_id'],'cus_new_test')
        self.assertEqual(self.stripe.customer_metadata['tenant_id'],str(self.tenant))


if __name__=='__main__':unittest.main()
