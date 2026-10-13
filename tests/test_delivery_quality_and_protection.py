import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from backend.shipment_protection import calculate_shipsurance_premium
from backend.delivery_quality import tracking_readiness
from backend.carrier_consolidation import carrier_identity, service_identity, summarize_history, route_history
from backend.automation_three_partners import BookingRequest, PartnerLifecycleService


class PremiumTests(unittest.IsolatedAsyncioTestCase):
    async def test_floor_percentage_cap_and_no_invented_wholesale(self):
        for value, premium in [('1', '1.20'), ('120', '1.20'), ('200', '2.00'), ('5000', '50.00')]:
            result = await calculate_shipsurance_premium(Decimal(value))
            self.assertEqual(result['premium_estimate'], premium)
            self.assertFalse(result['insured']);self.assertFalse(result['available'])
            self.assertIsNone(result['profit_margin']);self.assertIsNone(result['wholesale_cost'])
        with self.assertRaises(HTTPException) as error:
            await calculate_shipsurance_premium(Decimal('5000.01'))
        self.assertEqual(error.exception.status_code, 400)
        for value in ['0', '-1', 'NaN', 'Infinity']:
            with self.assertRaises(HTTPException):await calculate_shipsurance_premium(Decimal(value))

    async def test_unsupported_protection_fails_before_any_wallet_or_provider_call(self):
        lifecycle = object.__new__(PartnerLifecycleService)
        tenant = uuid4()
        context = SimpleNamespace(tenant_id=tenant, role='OWNER')
        with self.assertRaises(HTTPException) as error:
            await lifecycle.confirm(context, BookingRequest(tenant_id=tenant, offer_id=uuid4(), insurance_requested=True))
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn('No protection fee', str(error.exception.detail))


class QualityTests(unittest.IsolatedAsyncioTestCase):
    def test_service_measurements_do_not_mix_fast_and_slow_tiers(self):
        start = datetime(2026, 10, 5, tzinfo=timezone.utc)
        rows = [{'carrier_code': 'DPD UK', 'service_code': 'DPD_UK_EXPRESS', 'status': 'DELIVERED', 'dispatched_at': start,
                 'delivered_at': start + timedelta(days=1), 'delivery_days': '1'},
                {'carrier_code': 'DPD_GB', 'service_code': 'DPD_GB_ECONOMY', 'status': 'DELIVERED', 'dispatched_at': start,
                 'delivered_at': start + timedelta(days=3), 'delivery_days': '2'}]
        history = summarize_history(rows, service_level=True)
        self.assertEqual(history['DPD|EXPRESS']['on_time_rate'], Decimal('100.0'))
        self.assertEqual(history['DPD|ECONOMY']['on_time_rate'], Decimal('0.0'))
        self.assertEqual(history['DPD|EXPRESS']['metric_scope'], 'SERVICE_ROUTE')
        self.assertEqual(carrier_identity('DPD_GB'), carrier_identity('DPD UK'))
        self.assertEqual(service_identity('DPD UK', 'DPD_UK_EXPRESS'), 'EXPRESS')

    async def test_history_excludes_test_labels_and_is_tenant_and_route_bound(self):
        calls = []
        class Connection:
            async def fetch(self, sql, *args):calls.append((sql, args));return []
        class Pool:
            @asynccontextmanager
            async def acquire(self):yield Connection()
        tenant = uuid4()
        self.assertEqual(await route_history(Pool(), tenant, 'FR', 'GB'), {})
        self.assertIn("a.environment='LIVE'", calls[0][0])
        self.assertEqual(calls[0][1], (tenant, 'FR', 'GB'))

    async def test_readiness_explains_disabled_receivers_and_missing_history(self):
        tenant = uuid4();calls = []
        values = iter([{'connections': 3, 'receivers': 0}, {'received': 0, 'transit': 0, 'delivered': 0}, {'delivered': 0, 'estimated': 0}])
        class Connection:
            async def fetchrow(self, sql, *args):calls.append(args);return next(values)
        class Pool:
            @asynccontextmanager
            async def acquire(self):yield Connection()
        result = await tracking_readiness(Pool(), tenant, 'GB', 'FR', 'TEST')
        self.assertEqual(result['configured_tracking_receivers'], 0)
        self.assertIn('signing credentials', ' '.join(result['reasons']))
        self.assertIn('TEST shipments', ' '.join(result['reasons']))
        self.assertTrue(all(args[0] == tenant for args in calls))
