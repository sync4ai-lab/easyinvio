import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from backend.aggregator_lifecycle import (
    ADAPTERS, BookingRequest, EasyPostAdapter, SendcloudAdapter, ShippoAdapter,
    PartnerLifecycleService, create_adapter, declaration,
    return_snapshot, secure_link, authorize, verify_quote_connection,
)
from backend.automation_freight_engine import PurchaseRejected, PurchaseUncertain


class NativeContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_quote_invalidated_when_connection_key_changes(self):
        import hashlib
        account=SimpleNamespace(base_url=ShippoAdapter.endpoint,api_key='synthetic-current',upstream_account_id=None)
        rate=SimpleNamespace(execution_details={'account_endpoint':account.base_url,
            'account_credential_sha256':hashlib.sha256(account.api_key.encode()).hexdigest(), 'account_upstream_id':None})
        verify_quote_connection(account,rate)
        account.api_key='synthetic-replacement'
        with self.assertRaises(PurchaseRejected):
            verify_quote_connection(account,rate)

    async def test_factory_uses_exact_provider_endpoints(self):
        self.assertEqual(set(ADAPTERS),{EasyPostAdapter.endpoint,ShippoAdapter.endpoint,SendcloudAdapter.endpoint})
        for endpoint, adapter in ADAPTERS.items():
            account = SimpleNamespace(base_url=endpoint, api_key='synthetic')
            self.assertIsInstance(create_adapter(None, account, environment='TEST'), adapter)
        with self.assertRaises(PurchaseRejected):
            create_adapter(None, SimpleNamespace(base_url='https://unapproved.example', api_key='synthetic'), environment='TEST')

    async def test_easypost_preflight_and_purchase_bind_exact_rate_and_mode(self):
        calls = []
        async def handler(request):
            calls.append((request.method, request.url.path))
            body = {'id': 'shp_test', 'mode': 'test', 'rates': [{'id': 'rate_test'}]}
            if request.method == 'POST':
                self.assertEqual(json.loads(request.content), {'rate': {'id': 'rate_test'}})
                body.update(selected_rate={'id': 'rate_test'}, tracking_code='TEST123',
                            postage_label={'label_pdf_url': 'https://easypost-files.s3.amazonaws.com/test.pdf'})
            return httpx.Response(200, json=body)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = EasyPostAdapter(client, 'synthetic', environment='TEST')
            result = await adapter.purchase_label({'upstream_shipment_id': 'shp_test', 'upstream_rate_id': 'rate_test'})
        self.assertEqual(result['tracking_number'], 'TEST123')
        self.assertEqual(calls, [('GET', '/v2/shipments/shp_test'), ('POST', '/v2/shipments/shp_test/buy')])

    async def test_live_key_cannot_buy_into_test_environment(self):
        calls = []
        def handler(request):
            calls.append(request.method)
            return httpx.Response(200, json={'mode': 'production'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(PurchaseRejected):
                await EasyPostAdapter(client, 'synthetic', environment='TEST').purchase_label(
                    {'upstream_shipment_id': 'shp_test', 'upstream_rate_id': 'rate_test'})
        self.assertEqual(calls, ['GET'])

    async def test_ambiguous_post_has_no_automatic_retry(self):
        calls = []
        def handler(request):
            calls.append(request.method)
            raise httpx.ReadTimeout('synthetic', request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(PurchaseUncertain):
                await ShippoAdapter(client, 'shippo_test_synthetic', environment='TEST').purchase_label({'upstream_rate_id': 'r1'})
        self.assertEqual(calls, ['POST'])

    async def test_shippo_transaction_and_queued_refund(self):
        def handler(request):
            self.assertEqual(request.headers['Authorization'], 'ShippoToken shippo_test_synthetic')
            if request.url.path == '/refunds/':
                return httpx.Response(201, json={'object_id': 'refund1', 'status': 'QUEUED'})
            return httpx.Response(201, json={'object_id': 'tx1', 'rate': 'r1', 'test': True,
                'status': 'SUCCESS', 'tracking_number': 'T1', 'label_url': 'https://deliver.goshippo.com/test.pdf'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = ShippoAdapter(client, 'shippo_test_synthetic', environment='TEST')
            self.assertEqual((await adapter.purchase_label({'upstream_rate_id': 'r1'}))['upstream_id'], 'tx1')
            self.assertFalse(await adapter.void_label('tx1'))
            self.assertEqual(adapter.pending_void_id, 'refund1')

    async def test_sendcloud_current_document_schema_and_queued_cancel(self):
        def handler(request):
            if request.url.path.endswith('/cancel'):
                return httpx.Response(202, json={'data': {'status': 'queued'}})
            payload = json.loads(request.content)
            self.assertEqual(payload['ship_with']['properties']['shipping_option_code'], 'dpd:home')
            return httpx.Response(201, json={'data': {'id': 's1', 'parcels': [{'tracking_number': 'T2',
                'documents': [{'document_type': 'label', 'link': 'https://panel.sendcloud.sc/label.pdf'},
                    {'document_type': 'customs-declaration', 'link': 'https://panel.sendcloud.sc/customs.pdf'}]}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = SendcloudAdapter(client, '{"public_key":"synthetic","secret_key":"synthetic"}', environment='LIVE')
            address = {'name': 'QA', 'line1': '1 Test Road', 'postal_code': '1011AB', 'city': 'Amsterdam', 'country_code': 'NL'}
            result = await adapter.purchase_label({'origin': address, 'destination': address,
                'cargo': {'actual_weight_kg': '1.5', 'length_cm': '20', 'width_cm': '15', 'height_cm': '10'},
                'order_reference': 'QA', 'upstream_rate_id': 'dpd:home'})
            self.assertEqual(result['carrier_forms'][0]['document_type'], 'customs-declaration')
            self.assertFalse(await adapter.void_label('s1'))

    async def test_sendcloud_return_cancellation_requires_separate_native_confirmation(self):
        calls=[]
        def handler(request):
            calls.append((request.method,request.url.path))
            if request.method=='PATCH':
                return httpx.Response(202,json={'message':'Cancellation requested successfully'})
            return httpx.Response(200,json={'status':{'parent_status':'Cancelled'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=SendcloudAdapter(client,'{"public_key":"synthetic","secret_key":"synthetic"}',environment='LIVE')
            adapter.is_return=True
            self.assertFalse(await adapter.void_label('123'))
            self.assertTrue(await adapter.void_confirmed('123'))
        self.assertEqual(calls,[('PATCH','/api/v3/returns/123/cancel'),('GET','/api/v3/returns/123')])

    async def test_sendcloud_test_mode_cannot_accidentally_create_billable_labels(self):
        client = AsyncMock()
        adapter = SendcloudAdapter(client, '{}', environment='TEST')
        with self.assertRaises(PurchaseRejected):
            await adapter.purchase_label({})
        client.stream.assert_not_called()

    async def test_customs_and_returns_require_reviewed_new_authorization(self):
        with self.assertRaises(PurchaseRejected):
            declaration({'customs_document': {'required': True, 'ready_for_provider': False}})
        with self.assertRaises(PurchaseRejected):
            return_snapshot({'origin': {}, 'destination': {}, 'upstream_rate_id': 'forward-price'})
        result = return_snapshot({'return_quote_authorized': True, 'return_rate_id': 'return-price',
            'origin': {'name': 'warehouse'}, 'destination': {'name': 'buyer'}})
        self.assertEqual(result['origin']['name'], 'buyer')
        self.assertEqual(result['upstream_rate_id'], 'return-price')

    async def test_document_links_reject_non_https_and_credentials(self):
        for value in ('http://example.test/a', 'https://user:secret@example.test/a', '/relative', None):
            with self.assertRaises(PurchaseUncertain):
                secure_link(value)

    async def test_public_label_response_never_exposes_remote_pipeline(self):
        service = PartnerLifecycleService(SimpleNamespace(pool=None, finance=None), None)
        result = service.public_result(uuid4(), {'upstream_id': 'private', 'tracking_number': 'T1',
            'label_url': 'https://deliver.goshippo.com/private', 'carrier_forms': []})
        self.assertNotIn('goshippo', json.dumps(result))
        self.assertNotIn('upstream_id', result['label'])

    async def test_tenant_tampering_and_accountant_booking_rejected(self):
        context = SimpleNamespace(tenant_id=uuid4(), role='OWNER')
        with self.assertRaises(HTTPException) as error:
            authorize(context, uuid4())
        self.assertEqual(error.exception.status_code, 403)
        context.role = 'ACCOUNTANT'
        with self.assertRaises(HTTPException):
            authorize(context, context.tenant_id)

    async def test_easypost_return_quote_uses_forward_addresses_once(self):
        warehouse = {'name': 'Warehouse', 'line1': '1 Test Road', 'city': 'London', 'postal_code': 'SW1A 1AA', 'country_code': 'GB'}
        buyer = {**warehouse, 'name': 'Buyer'}
        strategy = main.EasyPostStrategy(None, SimpleNamespace(upstream_account_id=None, id=uuid4()))
        strategy.post = AsyncMock(return_value={'id': 'return1', 'rates': []})
        request = main.RatingRequest(origin=buyer, destination=warehouse, weights_kg=['1'],
            dimensions=[{'length_cm': '20', 'width_cm': '15', 'height_cm': '10'}], is_return=True)
        await strategy.rates(request)
        payload = strategy.post.call_args.args[1]['shipment']
        self.assertTrue(payload['is_return'])
        self.assertEqual(payload['from_address']['name'], 'Warehouse')
        self.assertEqual(payload['to_address']['name'], 'Buyer')

    async def test_test_financial_permission_cannot_bypass_environment_boundary(self):
        finance = main.FinanceEngine(None, SimpleNamespace(provider_environment='TEST', database_environment='SANDBOX'), None)
        self.assertTrue(finance.verified_test_booking({'is_sandbox': True}, True))
        self.assertFalse(finance.verified_test_booking({'is_sandbox': False}, True))
        self.assertFalse(finance.verified_test_booking({'is_sandbox': True}, False))
        finance.settings.database_environment = 'LIVE'
        self.assertFalse(finance.verified_test_booking({'is_sandbox': True}, True))

    async def test_native_quotes_keep_actual_weight_and_margin_rules_keep_billable_weight(self):
        from unittest.mock import patch
        tenant = uuid4()
        account = SimpleNamespace(id=uuid4(), provider='EASYPOST', base_url=EasyPostAdapter.endpoint, api_key='synthetic', upstream_account_id=None)
        repository = SimpleNamespace(accounts=AsyncMock(return_value=[account]))
        settings = SimpleNamespace(max_parallel_provider_requests=2, provider_deadline_seconds=5, quote_ttl_seconds=300)
        service = main.RatingService(None, repository, settings)
        rate = main.WholesaleRate(provider='EASYPOST', account_id=account.id,
            upstream_shipment_id='shp1', upstream_rate_id='rate1', carrier_code='UPS', service_code='Ground',
            currency='GBP', wholesale_cost='10.00')
        service.run_provider = AsyncMock(return_value=([rate], None))
        address = {'name': 'QA', 'line1': '1 Test Road', 'city': 'London', 'postal_code': 'SW1A 1AA', 'country_code': 'GB'}
        request = main.RatingRequest(origin=address, destination=address, weights_kg=['2.500'],
            dimensions=[{'length_cm': '40', 'width_cm': '30', 'height_cm': '20'}])
        with patch('main.get_client_calibrated_rate', AsyncMock(return_value=Decimal('12.00'))):
            result = await service.quote(SimpleNamespace(tenant_id=tenant), request)
        self.assertEqual(service.run_provider.call_args.args[1].weights_kg, [Decimal('2.500')])
        self.assertEqual(result.weight['billable_weight_kg'], '4.800')

    async def test_new_routes_require_authenticated_context(self):
        main.app.state.local_preview = False
        client = TestClient(main.app)
        body = {'tenant_id': str(uuid4()), 'offer_id': str(uuid4())}
        self.assertEqual(client.post('/api/v1/shipping/confirm-booking', json=body).status_code, 401)
        self.assertEqual(client.post('/api/v1/shipping/request-void', json={'tenant_id': body['tenant_id'], 'shipment_id': str(uuid4())}).status_code, 401)
        self.assertEqual(client.get('/api/v1/shipping/' + str(uuid4()) + '/documents/label').status_code, 401)
        self.assertEqual(client.post('/api/v1/shipping/prepare-return', json={'tenant_id': body['tenant_id'],
            'shipment_id': str(uuid4()), 'idempotency_key': str(uuid4())}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
