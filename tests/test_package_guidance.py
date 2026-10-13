import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException
from backend.package_guidance import PackageCheck, evaluate_package, build_router


class PackageGuidanceTests(unittest.IsolatedAsyncioTestCase):
    def body(self, **changes):
        return PackageCheck.model_validate({'origin_country': 'GB', 'destination_country': 'FR',
            'cargo_type': 'PARCEL', 'actual_weight_kg': '10',
            'dimensions': {'length_cm': '80', 'width_cm': '60', 'height_cm': '90'}, **changes})

    def test_large_parcel_warns_without_rejecting_other_carriers(self):
        result = evaluate_package(self.body())
        self.assertFalse(result['blocking'])
        self.assertEqual(result['measurements']['combined_length_girth_cm'], '370')
        self.assertIn('below 300 cm', result['messages'][0]['text'])
        self.assertIn('physically repack', result['messages'][0]['suggestion'])
        self.assertIn('coverage is partial', result['scope'])

    def test_small_parcel_and_rotation_have_same_combined_measure(self):
        for dims in [dict(length_cm='40', width_cm='30', height_cm='20'), dict(length_cm='20', width_cm='40', height_cm='30')]:
            result = evaluate_package(self.body(dimensions=dims))
            self.assertEqual(result['measurements']['combined_length_girth_cm'], '140')
            self.assertEqual(result['messages'], [])

    def test_exact_service_boundaries_and_country_scope(self):
        result = evaluate_package(self.body(dimensions={'length_cm': '100', 'width_cm': '50', 'height_cm': '50'}))
        self.assertTrue(result['messages'])  # 300 cm is outside the cited strict <300 rule.
        self.assertEqual(evaluate_package(self.body(origin_country='US'))['messages'], [])
        self.assertEqual(evaluate_package(self.body(destination_country='GB'))['messages'], [])

    def test_letter_weight_and_merchandise_guidance(self):
        result = evaluate_package(self.body(cargo_type='LETTER', actual_weight_kg='0.5', dimensions=None))
        self.assertTrue(result['blocking'])
        self.assertEqual(result['messages'][0]['code'], 'LETTER_WEIGHT_LIMIT')
        self.assertFalse(evaluate_package(self.body(cargo_type='LETTER', actual_weight_kg='0.1', dimensions=None))['blocking'])

    def test_native_freight_blocks_before_futile_quote_but_custom_contract_is_unknown(self):
        body = self.body(cargo_type='PALLET')
        self.assertTrue(evaluate_package(body, [SimpleNamespace(base_url='https://api.goshippo.com')])['blocking'])
        self.assertFalse(evaluate_package(body, [SimpleNamespace(base_url='https://regional.example')])['blocking'])

    def test_goods_weight_and_supported_range_block_with_suggestions(self):
        body = self.body(shipment_items=[{'description': 'Fixture', 'quantity': 2, 'unit_value': '1',
            'unit_weight_kg': '6', 'origin_country': 'GB'}])
        self.assertEqual(evaluate_package(body)['messages'][0]['code'], 'GOODS_EXCEED_PACKED_WEIGHT')
        body = self.body(actual_weight_kg='1001')
        self.assertTrue(evaluate_package(body)['blocking'])

    async def test_workspace_check_uses_only_current_workspace_connections(self):
        repository = SimpleNamespace(accounts=AsyncMock(return_value=[]))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(rating=SimpleNamespace(repository=repository))))
        context = SimpleNamespace(role='DISPATCHER', tenant_id=uuid4())
        endpoint = next(route.endpoint for route in build_router(lambda: None).routes if route.path.endswith('package-check'))
        result = await endpoint(self.body(), request, context)
        repository.accounts.assert_awaited_once_with(context)
        self.assertTrue(result['blocking'])
        with self.assertRaises(HTTPException):
            await endpoint(self.body(), request, SimpleNamespace(role='UNKNOWN'))

    def test_route_is_authenticated_and_invalid_units_rejected(self):
        from fastapi.testclient import TestClient
        import main
        main.app.state.local_preview = False
        client = TestClient(main.app)
        body = self.body().model_dump(mode='json')
        self.assertEqual(client.post('/api/v1/shipping/package-check', json=body).status_code, 401)
        body['actual_weight_kg'] = 'NaN'
        self.assertEqual(client.post('/api/v1/logistics/package-guidance', json=body).status_code, 422)
