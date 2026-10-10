import base64
import hmac
import json
import time
import unittest
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.hubspot_crm import HubSpotClient, HubSpotSettings, build_router
from backend.hubspot_provisioning import association_id, verify_signature
from tests.test_hubspot_crm import Merchant, settings


class ActivationTests(unittest.IsolatedAsyncioTestCase):
    async def test_metrics_exact_and_legacy_compatible(self):
        merchant = Merchant()
        async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as http:
            client = HubSpotClient(http,settings())
            tenant = uuid4()
            company = await client.onboard(tenant,'Company','merchant@example.invalid','')
            self.assertTrue(client.contact_ids[str(tenant)].isdigit())
            await client.milestone(tenant,company,'Company',40,Decimal('123.45'),'GBP',wallet_balance=Decimal('342.10'))
        p = merchant.records['companies'][0]['properties']
        self.assertEqual(p['veloce_total_shipments'],'40')
        self.assertEqual(p['veloce_package_count'],'40')
        self.assertEqual(p['veloce_wallet_balance'],'342.10')
        self.assertEqual(p['veloce_total_spend'],'123.45')

    async def test_inbound_company_is_reused_on_sync(self):
        merchant = Merchant()
        merchant.records['companies'].append({'id':'7','properties':{'name':'Existing'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as http:
            company = await HubSpotClient(http,settings()).onboard(uuid4(),'Existing','test@example.invalid','',existing_company_id='7')
        self.assertEqual(company,'7')
        self.assertEqual(len(merchant.records['companies']),1)

    def test_signature_raw_body_timestamp_and_url_integrity(self):
        body=b'[{"example": "raw whitespace"}]'
        url='https://example.test/api/v1/integrations/hubspot-webhook'
        stamp=str(int(time.time()*1000))
        signature=base64.b64encode(hmac.digest(b'test-secret',b'POST'+url.encode()+body+stamp.encode(),'sha256')).decode()
        verify_signature('test-secret',url,body,stamp,signature)
        for u,b,t,s in [(url,body+b' ',stamp,signature),(url+'x',body,stamp,signature),
                        (url,body,str(int(stamp)-300001),signature),(url,body,str(int(stamp)+300001),signature),
                        (url,body,stamp,'bad'),(url,body,'',signature)]:
            with self.assertRaises(HTTPException): verify_signature('test-secret',u,b,t,s)

    def test_association_ambiguity_and_paging_rejected(self):
        from backend.hubspot_crm import CRMError
        self.assertEqual(association_id({'associations':{'companies':{'results':[{'id':'1'},{'id':'1'}]}}},'companies'),'1')
        for block in [{'results':[]},{'results':[{'id':'1'},{'id':'2'}]}, {'results':[{'id':'1'}],'paging':{'next':{}}}]:
            with self.assertRaises(CRMError): association_id({'associations':{'companies':block}},'companies')

    def test_provisioning_configuration_requires_separate_app_credentials(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError): HubSpotSettings(_env_file=None,hubspot_provisioning_enabled=True)
        config=HubSpotSettings(_env_file=None,hubspot_webhook_app_id='',hubspot_webhook_client_secret='')
        self.assertIsNone(config.hubspot_webhook_app_id)
        self.assertIsNone(config.hubspot_webhook_client_secret)

    def test_signed_webhook_queues_only_correct_account_and_stage(self):
        class DB:
            calls=[]
            @asynccontextmanager
            async def acquire(self): yield self
            @asynccontextmanager
            async def transaction(self): yield self
            async def execute(self,sql,*args): self.calls.append((sql,args))
        db=DB()
        app=FastAPI();app.include_router(build_router(lambda: None))
        url='https://example.test/api/v1/integrations/hubspot-webhook'
        config=SimpleNamespace(hubspot_provisioning_enabled=True,hubspot_webhook_url=url,
            hubspot_webhook_client_secret=SimpleNamespace(get_secret_value=lambda:'test-secret'),
            hubspot_expected_portal_id=12345,hubspot_webhook_app_id=99,hubspot_closed_won_stage_ids=['closedwon'])
        app.state.hubspot=SimpleNamespace(pool=db,client=SimpleNamespace(settings=config))
        event={'portalId':12345,'appId':99,'eventId':1,'objectId':10,'occurredAt':int(time.time()*1000),
               'subscriptionType':'deal.propertyChange','propertyName':'dealstage','propertyValue':'closedwon'}
        def send(client,events,sign=True):
            body=json.dumps(events).encode();stamp=str(int(time.time()*1000))
            signature=base64.b64encode(hmac.digest(b'test-secret',b'POST'+url.encode()+body+stamp.encode(),'sha256')).decode()
            return client.post('/api/v1/integrations/hubspot-webhook',content=body,
                headers={'x-hubspot-signature-v3':signature if sign else 'invalid','x-hubspot-request-timestamp':stamp})
        with patch('backend.hubspot_provisioning.safe_pending',new=AsyncMock()), TestClient(app) as client:
            self.assertEqual(send(client,[event]).status_code,202)
            self.assertEqual(db.calls[0][1],(12345,'10'))
            self.assertIn('DO NOTHING',db.calls[0][0])
            self.assertEqual(send(client,[event],False).status_code,401)
            self.assertEqual(send(client,[{**event,'portalId':2}]).status_code,403)
            response=send(client,[{**event,'propertyValue':'closedlost'}])
            self.assertEqual(response.json()['accepted_events'],0)
            self.assertEqual(len(db.calls),1)
            self.assertEqual(send(client,[]).status_code,422)


if __name__=='__main__': unittest.main()
