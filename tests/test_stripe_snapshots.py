import asyncio
import hashlib
import hmac
import json
import time
import unittest
from uuid import uuid4
from decimal import Decimal
from fastapi.testclient import TestClient
from backend.payment_gateway import SnapshotWebhookService
from tests import test_payment_gateway as fixture


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixture.PaymentTests.setUp
    create=fixture.PaymentTests.create

    def event(self,kind,obj,event_id=None):
        return {'id':event_id or 'evt_'+uuid4().hex,'type':kind,'api_version':'2026-09-30.endive','livemode':False,'data':{'object':obj}}

    def charge(self,session,**changes):
        return {'object':'charge','id':'ch_'+session['payment_intent'][3:],'payment_intent':session['payment_intent'],
            'customer':session['customer'],'metadata':session['metadata'],'livemode':False,'currency':'gbp',
            'amount':session['amount_total'],'amount_refunded':0,'status':'succeeded','paid':True,**changes}

    async def dispatch(self,event):
        service=SnapshotWebhookService(self.finance)
        return await service.process(await service.register(event))

    def post(self,client,event,tamper=False):
        raw=json.dumps(event).encode();stamp=str(int(time.time()))
        digest=hmac.new(b'whsec_fixture',stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return client.post('/api/v1/billing/webhooks/stripe',content=raw+(b' ' if tamper else b''),headers={'stripe-signature':f't={stamp},v1={digest}'})

    async def test_credit_success_state_intent_and_stored_url(self):
        body,session=await self.create()
        result=await self.dispatch(self.event('checkout.session.completed',session))
        self.assertTrue(result['credited']);row=self.c.state['topups'][body.request_id]
        self.assertEqual(row['status'],'CREDITED');self.assertEqual(row['transaction_state'],'SUCCESS')
        self.assertEqual(row['stripe_payment_intent_id'],session['payment_intent']);self.assertTrue(row['checkout_url'].startswith('https://checkout.stripe.com'))

    async def test_cumulative_partial_refunds_replays_and_out_of_order(self):
        _,session=await self.create();await self.dispatch(self.event('checkout.session.completed',session))
        first=self.event('charge.refunded',self.charge(session,amount_refunded=2000))
        self.assertEqual((await self.dispatch(first))['refund_debited'],'20.00')
        self.assertTrue((await self.dispatch(first))['replayed'])
        second=self.event('charge.refunded',self.charge(session,amount_refunded=6000))
        self.assertEqual((await self.dispatch(second))['refund_debited'],'40.00')
        self.assertEqual((await self.dispatch(self.event('charge.refunded',self.charge(session,amount_refunded=2000))))['refund_debited'],'0.00')
        self.assertEqual(self.c.state['wallet']['balance'],Decimal('40.00'))
        self.assertEqual([row[2] for row in self.c.state['ledger']],['TOPUP','REFUND_DEBIT','REFUND_DEBIT'])

    async def test_concurrent_refund_events_do_not_double_debit(self):
        _,session=await self.create();await self.dispatch(self.event('checkout.session.completed',session))
        await asyncio.gather(*(self.dispatch(self.event('charge.refunded',self.charge(session,amount_refunded=5000))) for _ in range(5)))
        self.assertEqual(self.c.state['wallet']['balance'],Decimal('50.00'));self.assertEqual(len(self.c.state['ledger']),2)

    async def test_refund_respects_reserved_money_and_holds_workspace(self):
        _,session=await self.create();await self.dispatch(self.event('checkout.session.completed',session))
        self.c.state['wallet']['reserved_balance']=Decimal('90.00')
        result=await self.dispatch(self.event('charge.refunded',self.charge(session,amount_refunded=2000)))
        self.assertTrue(result['manual_action_required']);self.assertEqual(self.c.state['wallet']['balance'],Decimal('100.00'))
        self.assertEqual(self.c.state['tenant']['workspace_status'],'SUSPENDED')
        self.assertTrue(any(r['status']=='RECONCILIATION_REQUIRED' for r in self.c.state['events'].values()))

    async def test_failed_charge_maps_pending_intent_but_never_downgrades_paid(self):
        body,session=await self.create();charge=self.charge(session,status='failed',paid=False)
        self.assertTrue((await self.dispatch(self.event('charge.failed',charge)))['failed'])
        self.assertEqual(self.c.state['topups'][body.request_id]['status'],'FAILED')
        await self.dispatch(self.event('checkout.session.completed',session))
        self.assertTrue((await self.dispatch(self.event('charge.failed',charge)))['ignored'])
        self.assertEqual(self.c.state['topups'][body.request_id]['status'],'CREDITED')

    async def test_cross_tenant_or_wrong_amount_refunds_never_debit(self):
        _,session=await self.create();await self.dispatch(self.event('checkout.session.completed',session))
        for changes in [{'metadata':{**session['metadata'],'tenant_id':str(uuid4())}}, {'amount':10001},{'amount_refunded':10001}]:
            values={'amount_refunded':2000,**changes}
            result=await self.dispatch(self.event('charge.refunded',self.charge(session,**values)))
            self.assertTrue(result['deferred'])
        self.assertEqual(self.c.state['wallet']['balance'],Decimal('100.00'))

    async def test_process_failure_is_durable_and_returns_200(self):
        _,session=await self.create();event=self.event('checkout.session.completed',session)
        self.c.fail_ledger=True
        with TestClient(self.app) as client:
            response=self.post(client,event);self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['deferred'])
        self.assertEqual(self.c.state['wallet']['balance'],Decimal('0.00'))
        self.assertEqual(self.c.state['events'][event['id']]['status'],'PENDING')
        self.c.fail_ledger=False
        self.assertTrue((await SnapshotWebhookService(self.finance).process(event['id']))['credited'])

    async def test_receipt_storage_outage_returns_retryable_503(self):
        _,session=await self.create();original=self.c.execute
        async def broken(sql,*args):
            if 'INSERT INTO public.stripe_webhook_events' in sql:raise RuntimeError('Private exception text must not be exposed')
            return await original(sql,*args)
        self.c.execute=broken
        with TestClient(self.app) as client:
            response=self.post(client,self.event('checkout.session.completed',session));self.assertEqual(response.status_code,503)
            self.assertNotIn('Private',response.text)

    async def test_signature_exact_scope_snapshot_and_collision(self):
        _,session=await self.create();event=self.event('checkout.session.completed',session)
        with TestClient(self.app) as client:
            self.assertEqual(self.post(client,event,True).status_code,400)
            unsupported=self.event('payment_intent.succeeded',session)
            self.assertTrue(self.post(client,unsupported).json()['ignored'])
            self.assertEqual(self.post(client,{**event,'account':'acct_other'}).status_code,400)
            self.assertEqual(self.post(client,event).status_code,200)
            collision={**event,'data':{'object':{**session,'amount_total':10001}}}
            self.assertEqual(self.post(client,collision).status_code,400)


if __name__=='__main__':unittest.main()
