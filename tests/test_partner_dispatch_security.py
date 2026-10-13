import io
import json
import logging
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from starlette.requests import Request

from backend.automation_freight_engine import PurchaseRejected, PurchaseUncertain
from backend.automation_three_partners import SendcloudAdapter, easypost_parcel, validate_native_cargo, verify_native_signature
from backend.webhook_security import WebhookSecretFilter, enforce_shippo_source_ip


def request(ip='203.0.113.5', query=b'token=synthetic-secret', headers=()):
    return Request({'type':'http','method':'POST','path':'/tracking', 'query_string':query,
                    'headers':list(headers),'client':(ip,443),'scheme':'https','server':('test',443)})


class SecurityTests(unittest.TestCase):
    def test_token_duplicate_and_mismatch_rejected(self):
        for query in (b'token=wrong', b'token=synthetic-secret&token=synthetic-secret', b''):
            with self.assertRaises(HTTPException):
                verify_native_signature(request(query=query), b'{}', 'SHIPPO','URL_TOKEN','synthetic-secret')
        verify_native_signature(request(), b'{}', 'SHIPPO','URL_TOKEN','synthetic-secret')

    def test_ip_allowlist_rejects_spoofed_forwarding(self):
        with patch.dict(os.environ, {'SHIPPO_WEBHOOK_ALLOWED_IPS':'192.0.2.10', 'TRACKING_WEBHOOK_TRUSTED_PROXY_CIDRS':''}):
            with self.assertRaises(HTTPException) as caught:
                enforce_shippo_source_ip(request(headers=[(b'x-forwarded-for',b'192.0.2.10')]))
            self.assertEqual(caught.exception.status_code,403)
            enforce_shippo_source_ip(request(ip='192.0.2.10'))

    def test_trusted_proxy_chain_resolves_nearest_untrusted_peer(self):
        with patch.dict(os.environ, {'SHIPPO_WEBHOOK_ALLOWED_IPS':'192.0.2.10', 'TRACKING_WEBHOOK_TRUSTED_PROXY_CIDRS':'127.0.0.0/8'}):
            enforce_shippo_source_ip(request(ip='127.0.0.1',headers=[(b'x-forwarded-for',b'198.51.100.1, 192.0.2.10')]))
            with self.assertRaises(HTTPException):
                enforce_shippo_source_ip(request(ip='127.0.0.1',headers=[(b'x-forwarded-for',b'192.0.2.10, 198.51.100.1')]))

    def test_log_redaction_including_exception_tracebacks(self):
        output=io.StringIO();handler=logging.StreamHandler(output);handler.addFilter(WebhookSecretFilter())
        logger=logging.Logger('synthetic');logger.addHandler(handler)
        logger.info('HTTP %s', 'https://test/?source=1&token=secret-value&other=2')
        try:
            raise RuntimeError('https://test/?TOKEN=exception-secret')
        except RuntimeError:
            logger.exception('Callback failed')
        self.assertNotIn('secret-value',output.getvalue());self.assertNotIn('exception-secret',output.getvalue())
        self.assertIn('[REDACTED]',output.getvalue());self.assertIn('RuntimeError',output.getvalue())

    def test_letter_dimensions_stripped_and_exact_weight_boundary(self):
        cargo={'cargo_type':'LETTER','actual_weight_kg':'0.499','length_cm':'99','width_cm':'99','height_cm':'99'}
        parcel=easypost_parcel(cargo)
        self.assertEqual(set(parcel),{'weight','predefined_package'})
        with self.assertRaises(PurchaseRejected):easypost_parcel({**cargo,'actual_weight_kg':'0.500'})

    def test_freight_is_never_silently_cast_to_a_parcel(self):
        for provider in ('EASYPOST','SENDCLOUD','SHIPPO'):
            for kind in ('PALLET','OVERLAND_FREIGHT'):
                with self.assertRaisesRegex(PurchaseRejected,'NATIVE_FREIGHT_CONTRACT_REQUIRED'):
                    validate_native_cargo({'cargo_type':kind,'actual_weight_kg':'100','stackable':False},provider)


class AsyncAnnouncementTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_label_is_pending_and_polling_does_not_reannounce(self):
        calls=[]
        def transport(req):
            calls.append((req.method,req.url.path))
            if req.method=='POST':
                self.assertEqual(req.url.path,'/api/v3/shipments')
                return httpx.Response(202,json={'data':{'id':'shipment-1'}})
            return httpx.Response(200,json={'data':{'id':'shipment-1','parcels':[{'status':{'code':'ANNOUNCED'},
                'tracking_number':'TRACK-1','documents':[{'type':'label','link':'https://panel.sendcloud.sc/label.pdf'}]}]}})
        address={'name':'Test','line1':'1 Test Street','city':'Amsterdam','postal_code':'1011AB','country_code':'NL'}
        snapshot={'origin':address,'destination':address,'order_reference':'TEST','upstream_rate_id':'dpd:home',
            'cargo':{'cargo_type':'PARCEL','actual_weight_kg':'1','length_cm':'20','width_cm':'15','height_cm':'10'}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            adapter=SendcloudAdapter(client,json.dumps({'public_key':'synthetic','secret_key':'synthetic'}),environment='LIVE')
            with self.assertRaises(PurchaseUncertain):await adapter.purchase_label(snapshot)
            self.assertEqual(adapter.last_remote_id,'shipment-1')
            self.assertEqual((await adapter.retrieve_label('shipment-1',snapshot))['tracking_number'],'TRACK-1')
        self.assertEqual(calls,[('POST','/api/v3/shipments'),('GET','/api/v3/shipments/shipment-1')])

    async def test_announcing_cancelled_failed_and_wrong_identity_cannot_finalize(self):
        adapter=SendcloudAdapter(None,'{}',environment='LIVE')
        for code in ('ANNOUNCING','CANCELLED','ANNOUNCEMENT_FAILED'):
            with self.assertRaises(PurchaseUncertain):
                adapter.normalize({'data':{'id':'1','parcels':[{'status':{'code':code},'tracking_number':'T',
                    'documents':[{'type':'label','link':'https://panel.sendcloud.sc/label.pdf'}]}]}})
        def transport(req):return httpx.Response(200,json={'data':{'id':'wrong'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with self.assertRaisesRegex(PurchaseUncertain,'IDENTITY_MISMATCH'):
                await SendcloudAdapter(client,'{"public_key":"synthetic","secret_key":"synthetic"}',environment='LIVE').retrieve_label('expected',{})
