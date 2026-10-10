import asyncio
import hashlib
import hmac
import json
import time
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from urllib.parse import urlencode
from datetime import datetime,timezone

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from twilio.request_validator import RequestValidator

from backend.tracking_and_support import TrackingSettings, TrackingKey, build_router, draft_remedy
from backend.support_delivery import DeliverySettings, SupportDelivery, build_router as delivery_router


class OutboxDB:
    def __init__(self):
        self.id=uuid4();self.calls=[];self.state='STAGED';self.sid=None
    @asynccontextmanager
    async def acquire(self):yield self
    @asynccontextmanager
    async def transaction(self,**kwargs):yield
    async def fetchrow(self,sql,*args):
        self.calls.append((sql,args))
        if 'SELECT status,recipient_e164' in sql:
            return {'status':self.state,'recipient_e164':'+447700900123','provider_message_sid':self.sid,'attempts':1}
        if self.state!='STAGED':return None
        self.state='CLAIMED'
        return {'id':self.id,'tenant_id':uuid4(),'recipient_e164':'+447700900123','body':'Shipment TEST: verify the postal code','attempts':0}
    async def execute(self,sql,*args):
        self.calls.append((sql,args))
        if "status='RECONCILIATION_REQUIRED',attempts" in sql:self.state='RECONCILIATION_REQUIRED'
        elif "status='ACCEPTED',provider" in sql:
            if self.state=='RECONCILIATION_REQUIRED':self.state='ACCEPTED';self.sid=args[1]
        elif 'SET status=$2,provider_message_sid=$3' in sql:self.state=args[1];self.sid=args[2]
        elif 'next_attempt_at=now()+' in sql:self.state=args[1]
        elif "status='FAILED'" in sql:self.state='FAILED'
        return 'UPDATE 1'


class SupportMonitoringTests(unittest.IsolatedAsyncioTestCase):
    def settings(self):
        return SimpleNamespace(twilio_enabled=True,twilio_account_sid='AC'+'1'*32,twilio_auth_token=SecretStr('test-secret'),twilio_whatsapp_number='+14155238886',twilio_whatsapp_sandbox_enabled=True)
    def delivery(self):
        return DeliverySettings(_env_file=None,support_whatsapp_enabled=True,support_whatsapp_content_sid='HX'+'2'*32,support_whatsapp_status_url='https://app.example.com/api/v1/support/whatsapp/status')

    async def test_native_easypost_envelope_and_hmac(self):
        key=TrackingKey(tenant_id=uuid4(),carrier_account_id=uuid4(),secret='x'*40,easypost_mode='test')
        service=SimpleNamespace(settings=TrackingSettings(_env_file=None,tracking_webhook_keys={'account':key}),ingest=AsyncMock(return_value={'status':'EXCEPTION','support_queued':True}))
        app=FastAPI();app.state.tracking_support=service;app.include_router(build_router(lambda:None))
        now=datetime.now(timezone.utc).isoformat()
        event={'id':'evt_test','description':'tracker.updated','result':{'object':'Tracker','mode':'test','tracking_code':'TRACK1',
            'status':'failure','updated_at':now,'tracking_details':[{'datetime':now,'message':'Customs delay: postal code layout incorrect'}]}}
        raw=json.dumps(event).encode();signature='hmac-sha256-hex='+hmac.new(b'x'*40,raw,hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            response=await client.post('/api/v1/tracking/webhook?integration_key=account',content=raw,headers={'content-type':'application/json','x-hmac-signature':signature})
            self.assertEqual(response.status_code,200)
            mapped=service.ingest.call_args.args[2];self.assertEqual(mapped.status,'EXCEPTION')
            self.assertIn('postal-code',draft_remedy(mapped.raw_error))
            response=await client.post('/api/v1/tracking/webhook?integration_key=account',content=raw+b' ',headers={'content-type':'application/json','x-hmac-signature':signature})
            self.assertEqual(response.status_code,401)
            self.assertEqual(service.ingest.await_count,1)

    async def test_outbound_fence_and_signed_delivery_receipt(self):
        db=OutboxDB();settings=self.settings();config=self.delivery();requests=[]
        def transport(request):
            self.assertEqual(db.state,'RECONCILIATION_REQUIRED');requests.append(request)
            return httpx.Response(201,json={'sid':'SM'+'3'*32,'status':'queued'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            service=SupportDelivery(db,client,settings,config)
            self.assertEqual(await service.drain(),1);self.assertEqual(db.state,'ACCEPTED')
            self.assertIn(b'ContentSid=',requests[0].content);self.assertNotIn(b'Body=',requests[0].content)
            self.assertEqual(await service.drain(),0);self.assertEqual(len(requests),1)
            self.assertIn('notification_opt_in',db.calls[0][0]);self.assertIn('receiver_e164=$1',db.calls[0][0])
            app=FastAPI();app.state.support_delivery=service;app.include_router(delivery_router(lambda:None))
            params={'AccountSid':settings.twilio_account_sid,'MessageSid':'SM'+'3'*32,'MessageStatus':'delivered','To':'whatsapp:+447700900123'}
            url=config.support_whatsapp_status_url+'/'+str(db.id)
            signature=RequestValidator('test-secret').compute_signature(url,params)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as caller:
                response=await caller.post('/api/v1/support/whatsapp/status/'+str(db.id),content=urlencode(params),headers={'content-type':'application/x-www-form-urlencoded','x-twilio-signature':signature})
                self.assertEqual(response.status_code,200);self.assertEqual(db.state,'DELIVERED')
                params['MessageStatus']='sent';signature=RequestValidator('test-secret').compute_signature(url,params)
                await caller.post('/api/v1/support/whatsapp/status/'+str(db.id),content=urlencode(params),headers={'content-type':'application/x-www-form-urlencoded','x-twilio-signature':signature})
                self.assertEqual(db.state,'DELIVERED')
                response=await caller.post('/api/v1/support/whatsapp/status/'+str(db.id),content=urlencode(params),headers={'content-type':'application/x-www-form-urlencoded','x-twilio-signature':'bad'})
                self.assertEqual(response.status_code,403)

    async def test_uncertain_outcome_never_resends_and_rate_limit_retries(self):
        db=OutboxDB()
        async def transport(request):raise httpx.ReadTimeout('controlled timeout')
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            service=SupportDelivery(db,client,self.settings(),self.delivery())
            await service.drain();self.assertEqual(db.state,'RECONCILIATION_REQUIRED')
            self.assertEqual(await service.drain(),0)
        db=OutboxDB()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(429))) as client:
            service=SupportDelivery(db,client,self.settings(),self.delivery());await service.drain()
            self.assertEqual(db.state,'STAGED');self.assertTrue(any('TWILIO_RATE_LIMIT' in sql for sql,args in db.calls))
        config=DeliverySettings(_env_file=None);disabled=SupportDelivery(db,AsyncMock(),self.settings(),config)
        self.assertEqual(await disabled.drain(),0)


if __name__=='__main__':unittest.main()
