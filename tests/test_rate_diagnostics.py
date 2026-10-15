import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import SecretStr

import main
from backend.automation_three_partners import ShippoRateStrategy
from backend.platform_carriers import upgrade_sendcloud
from backend.rate_diagnostics import RateCurrencyUnavailable, RateHTTPRejected, no_rates_message
from tests.test_logistics import payload


class RateDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_services_are_not_reported_as_currency_mismatch(self):
        service = main.RatingService(None, None, SimpleNamespace(max_parallel_provider_requests=3))
        strategy = SimpleNamespace(account=SimpleNamespace(id=uuid4(), provider='REGIONAL', base_url='https://panel.sendcloud.sc/api/v3'),
                                   rates=AsyncMock(return_value=[]))
        request = main.RatingRequest.model_validate({**payload(), 'weights_kg': ['10'],
            'dimensions': [{'length_cm': '80', 'width_cm': '60', 'height_cm': '90'}]})
        _, issue = await service.run_provider(strategy, request, 5)
        self.assertEqual(issue.code, 'NO_ELIGIBLE_PRICED_SERVICES')
        self.assertIn('Open Packaging sizes', no_rates_message(request, [issue]))
        self.assertIn('some carriers', no_rates_message(request, [issue]))
        self.assertNotIn('girth', no_rates_message(request, [issue]))

    def test_small_package_missing_rates_does_not_claim_size_failure(self):
        message = no_rates_message(main.RatingRequest.model_validate(payload()), [])
        self.assertIn('No shipping options', message)
        self.assertNotIn('larger or heavier', message)

    async def test_unsuccessful_quote_is_saved_for_support_without_an_offer(self):
        ticket_id=uuid4()
        @asynccontextmanager
        async def transaction():yield
        connection = SimpleNamespace(execute=AsyncMock(),transaction=transaction,
            fetchval=AsyncMock(side_effect=[uuid4(),ticket_id]))
        class Pool:
            held=False
            @asynccontextmanager
            async def acquire(self):
                assert not self.held, 'Quote support must not hold one connection while acquiring another'
                self.held=True
                try:yield connection
                finally:self.held=False
        failure = HTTPException(503, {'code': 'NO_CARRIER_RATES_AVAILABLE', 'message': 'No eligible rates', 'issues': []})
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            settings=SimpleNamespace(quote_ttl_seconds=300),
            rating=SimpleNamespace(quote=AsyncMock(side_effect=failure), pool=Pool()))))
        context = main.TenantContext(uuid4(), uuid4(), 'OWNER', 'fixture-token')
        with self.assertRaises(HTTPException) as error:
            await main.get_rates(main.RatingRequest.model_validate(payload()), request, context)
        self.assertEqual(error.exception.status_code, 503)
        self.assertIn('request_id', error.exception.detail)
        self.assertEqual(error.exception.detail['support_case_id'],str(ticket_id))
        self.assertEqual(connection.fetchval.await_count,2)
        args = connection.execute.await_args.args
        self.assertEqual(args[1], context.tenant_id)
        self.assertEqual(json.loads(args[4])['rates'], [])
        self.assertEqual(json.loads(args[3])['weights_kg'], ['2.500'])

    async def test_actual_quote_currency_survives_provider_failure(self):
        service = main.RatingService(None, None, SimpleNamespace(max_parallel_provider_requests=3))
        account = SimpleNamespace(id=uuid4(), provider='REGIONAL', base_url='https://api.goshippo.com')
        strategy = SimpleNamespace(account=account, rates=AsyncMock(side_effect=RateCurrencyUnavailable(['GBP'])))
        request = main.RatingRequest.model_validate({**payload(), 'currency': 'EUR'})
        rates, issue = await service.run_provider(strategy, request, 5)
        self.assertFalse(rates)
        self.assertEqual(issue.available_currencies, ['GBP'])
        message = no_rates_message(request, [issue])
        self.assertIn('returned in GBP', message)
        self.assertIn('none matched EUR', message)

    async def test_sendcloud_authentication_failure_not_empty_rate(self):
        service = main.RatingService(None, None, SimpleNamespace(max_parallel_provider_requests=3))
        strategy = SimpleNamespace(account=SimpleNamespace(id=uuid4(), provider='REGIONAL', base_url='https://panel.sendcloud.sc/api/v3'),
                                   rates=AsyncMock(side_effect=RateHTTPRejected(403)))
        _, issue = await service.run_provider(strategy, main.RatingRequest.model_validate(payload()), 5)
        self.assertEqual(issue.code, 'UPSTREAM_AUTHENTICATION_REJECTED')
        self.assertFalse(issue.retryable)

    async def test_shippo_quote_currency_not_silently_relabelled(self):
        account = SimpleNamespace(id=uuid4(), api_key='shippo_test_fixture', upstream_account_id=None)
        response = {'object_id': 'shipment', 'test': True, 'rates': [{'currency': 'GBP', 'amount': '10.00',
                    'provider': 'DPD', 'object_id': 'rate', 'servicelevel': {'token': 'home'}}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=response))) as client:
            strategy = ShippoRateStrategy(client, account, main.WholesaleRate, 'TEST')
            with self.assertRaises(RateCurrencyUnavailable) as error:
                await strategy.rates(main.RatingRequest.model_validate({**payload(), 'currency': 'EUR'}))
        self.assertEqual(error.exception.available_currencies, ['GBP'])

    async def test_upgrade_refuses_unverified_credentials_without_database_writes(self):
        identifier, key = uuid4(), Fernet.generate_key()
        source = {'id': identifier, 'api_base_url': 'https://panel.sendcloud.sc/api/v2', 'environment': 'TEST',
                  'credential_key_id': 'v1', 'timeout_seconds': 5,
                  'credentials_ciphertext': Fernet(key).encrypt(json.dumps({'platform_id': str(identifier),
                      'api_key': json.dumps({'public_key': 'fixture', 'secret_key': 'fixture'})}).encode())}
        connection = SimpleNamespace(fetchrow=AsyncMock(return_value=source), execute=AsyncMock())
        class Pool:
            @asynccontextmanager
            async def acquire(self):
                yield connection
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            settings=SimpleNamespace(provider_environment='TEST', credential_keys={'v1': SecretStr(key.decode())}),
            finance=SimpleNamespace(pool=Pool()))))
        real = httpx.AsyncClient
        with patch('httpx.AsyncClient', side_effect=lambda **kwargs: real(transport=httpx.MockTransport(
                lambda req: httpx.Response(401)), **kwargs)):
            with self.assertRaises(HTTPException) as error:
                await upgrade_sendcloud(identifier, request, SimpleNamespace(user_id=uuid4()))
        self.assertEqual(error.exception.status_code, 409)
        connection.execute.assert_not_awaited()

    def test_upgrade_requires_platform_owner_authentication(self):
        from fastapi.testclient import TestClient
        self.assertEqual(TestClient(main.app).post('/api/v1/admin/platform-carriers/' + str(uuid4()) +
                         '/upgrade-sendcloud').status_code, 401)
