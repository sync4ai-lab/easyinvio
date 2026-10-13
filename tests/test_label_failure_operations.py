import json
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from backend.automation_freight_engine import PurchaseRejected
from backend.automation_three_partners import ShippoAdapter
from backend.dashboard_portal import build_router as dashboard_router
from backend.support_alert_controls import AlertPause, build_router
from backend.support_delivery import Consent, build_router as consent_router
from backend.label_availability import label_availability, require_label_purchase


class Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


class LabelFailureOperationsTests(unittest.IsolatedAsyncioTestCase):
    def test_quote_only_connections_are_blocked_before_checkout(self):
        settings = SimpleNamespace(provider_environment='TEST')
        rate = SimpleNamespace(execution_details={'account_endpoint': 'https://panel.sendcloud.sc/api/v3'})
        self.assertFalse(label_availability(settings, rate)[0])
        with self.assertRaises(HTTPException) as error:
            require_label_purchase(settings, rate)
        self.assertIn('No label purchase', error.exception.detail)
        rate.execution_details['account_endpoint'] = 'https://api.goshippo.com'
        self.assertTrue(label_availability(settings, rate)[0])

    async def test_real_shippo_unavailability_is_classified_without_exposing_body(self):
        response = {'object_id': 'transaction_fixture', 'status': 'ERROR', 'test': True,
                    'messages': [{'code': 'carrier_request_failed', 'text': 'Carrier is unavailable. Please try again in a few minutes.'}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(201, json=response))) as client:
            adapter = ShippoAdapter(client, 'shippo_test_fixture', environment='TEST')
            with self.assertRaises(PurchaseRejected) as error:
                await adapter.purchase_label({'upstream_rate_id': 'rate_fixture'})
            self.assertEqual(str(error.exception), 'SHIPPO_CARRIER_UNAVAILABLE')
            self.assertEqual(adapter.last_remote_id, 'transaction_fixture')

    async def test_unknown_rejection_not_misreported_as_temporary_unavailability(self):
        response = {'status': 'ERROR', 'messages': [{'code': 'other', 'text': 'Private provider detail'}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(201, json=response))) as client:
            with self.assertRaisesRegex(PurchaseRejected, '^LABEL_REJECTED$'):
                await ShippoAdapter(client, 'shippo_test_fixture', environment='TEST').purchase_label({'upstream_rate_id': 'rate_fixture'})

    async def test_client_tickets_exclude_internal_processing_failures(self):
        connection = SimpleNamespace(fetchval=AsyncMock(return_value=True), fetch=AsyncMock(return_value=[]))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(finance=SimpleNamespace(pool=Pool(connection)))))
        endpoint = next(route.endpoint for route in dashboard_router(lambda: None).routes if route.path == '/api/v1/support/tickets')
        context = SimpleNamespace(tenant_id=uuid4())
        self.assertEqual(await endpoint(request, context), {'tickets': []})
        sql, tenant, *_ = connection.fetch.await_args.args
        self.assertIn('t.automation_failure_id IS NULL', sql)
        self.assertEqual(tenant, context.tenant_id)

    async def test_opt_out_without_binding_succeeds_and_opt_in_requires_verification(self):
        connection = SimpleNamespace(execute=AsyncMock(return_value='UPDATE 0'))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(finance=SimpleNamespace(pool=Pool(connection)))))
        endpoint = next(route.endpoint for route in consent_router(lambda: None).routes if route.path.endswith('/consent'))
        context = SimpleNamespace(role='OWNER', tenant_id=uuid4(), user_id=uuid4())
        self.assertEqual(await endpoint(Consent(notification_opt_in=False), request, context), {'notification_opt_in': False})
        with self.assertRaises(HTTPException) as error:
            await endpoint(Consent(notification_opt_in=True), request, context)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn('verified WhatsApp number', error.exception.detail)

    async def test_admin_pause_is_idempotent_and_resume_never_grants_consent(self):
        @asynccontextmanager
        async def transaction():
            yield
        connection = SimpleNamespace(fetchval=AsyncMock(return_value=True), transaction=transaction,
                                     fetchrow=AsyncMock(return_value={'id': uuid4(), 'is_active': True,
                                     'notification_opt_in': False, 'verified_at': datetime.now(timezone.utc)}), execute=AsyncMock())
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(finance=SimpleNamespace(pool=Pool(connection)))))
        endpoint = next(route.endpoint for route in build_router(lambda: None).routes if route.path.endswith('/{binding_id}'))
        identifier = uuid4()
        self.assertTrue((await endpoint(identifier, AlertPause(paused=True), request, None))['alerts_paused'])
        with self.assertRaises(HTTPException) as error:
            await endpoint(identifier, AlertPause(paused=False), request, None)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(connection.execute.await_count, 1)
        self.assertNotIn('notification_opt_in', connection.execute.await_args.args[0])

    def test_admin_endpoints_require_platform_authentication(self):
        client = TestClient(main.app)
        self.assertEqual(client.get('/api/v1/admin/support/whatsapp/bindings').status_code, 401)
        self.assertEqual(client.patch('/api/v1/admin/support/whatsapp/bindings/' + str(uuid4()), json={'paused': True}).status_code, 401)
