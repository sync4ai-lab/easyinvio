"""Offline integration tests; no credentials or external API calls."""
import asyncio
from datetime import datetime,timezone
import csv
import io
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import main
from backend.ai_engine import predict_hs_code, analyze_tracking_history
from backend.advanced_logistics import calculate_billable_weight, generate_commercial_invoice, parse_batch_csv, CSV_FIELDS


def payload():
    return {"origin": {"name": "Sender", "line1": "1 Street", "city": "London", "postal_code": "SW1A 1AA", "country_code": "GB"},
            "destination": {"name": "Recipient", "line1": "2 Street", "city": "Paris", "postal_code": "75001", "country_code": "FR"},
            "dimensions": [{"length_cm": "40", "width_cm": "30", "height_cm": "20"}], "weights_kg": ["2.500"], "currency": "GBP"}




BASELINE = {"currency": "GBP", "billable_weight_kg": "4.800", "base_cost": "16.00", "fuel_surcharge": "1.92", "residential_fee": "1.50", "remote_area_fee": "0.00"}


def csv_data(count=2):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(CSV_FIELDS)
    for index in range(count):
        writer.writerow([f"ORDER-{index}", "PARCEL", "Sender", "1 Street", "London", "SW1A 1AA", "GB", "Recipient", "+447700900001", "Recipient", "2 Street", "London", "SW1A 1AA", "GB", "40", "30", "20", "2.500", "GBP", "Cotton T-shirt", "25.00"])
    return output.getvalue().encode()


class MathTests(unittest.TestCase):
    def test_volumetric_and_actual(self):
        self.assertEqual(calculate_billable_weight("40", "30", "20", "2.5")["billable_weight_kg"], "4.800")
        self.assertEqual(calculate_billable_weight("10", "10", "10", "2.5")["billable_weight_kg"], "2.500")

    def test_round_up_without_float(self):
        self.assertEqual(calculate_billable_weight("10.01", "10", "10", "0.1")["billable_weight_kg"], "0.201")
        for invalid in (True, float("nan"), 2.5, "Infinity", "0", "-1"):
            with self.assertRaises((ValueError, ArithmeticError)):
                calculate_billable_weight("10", "10", "10", invalid)

    def test_harmonizer_and_abstention(self):
        self.assertEqual(predict_hs_code("Silk running sneakers leather trim")["hs_code"], "640411")
        self.assertIsNone(predict_hs_code("miscellaneous warehouse goods")["hs_code"])
        self.assertEqual(predict_hs_code("Cotton T-shirt")["hs_code"], "610910")
        with self.assertRaises(ValueError):
            predict_hs_code("x")

    def test_history_not_fabricated(self):
        result = analyze_tracking_history("GBR", "FRA", [])
        self.assertIsNone(result["recommended_provider"])
        self.assertFalse(result["simulated"])
        self.assertEqual(result["origin"], "GB")



    def test_money_rejects_float(self):
        with self.assertRaises(ValidationError):
            main.WholesaleRate(provider="EASYPOST", account_id=uuid4(), upstream_shipment_id="x", upstream_rate_id="y", carrier_code="A", service_code="B", currency="GBP", wholesale_cost="10.005")

    def test_fees_must_reconcile(self):
        with self.assertRaises(ValidationError):
            main.WholesaleRate(provider="REGIONAL", account_id=uuid4(), upstream_shipment_id="x", upstream_rate_id="y", carrier_code="A", service_code="B", currency="GBP", wholesale_cost="10.00", fee_components={"base_cost": "10.00", "fuel_surcharge": "1.00", "residential_fee": "0.00", "remote_area_fee": "0.00"})

    def test_csv_limits_and_duplicate(self):
        rows = parse_batch_csv(csv_data(), main.RatingRequest)
        self.assertEqual(rows[0]["weight"]["billable_weight_kg"], "4.800")
        duplicate = csv_data().replace(b"ORDER-1", b"ORDER-0")
        self.assertIn("duplicate", parse_batch_csv(duplicate, main.RatingRequest)[1]["error"])
        with self.assertRaises(ValueError):
            parse_batch_csv(csv_data(1001), main.RatingRequest)
        with self.assertRaises(ValueError):
            parse_batch_csv(b"wrong,header\n1,2", main.RatingRequest)

    def test_declaration_totals_and_review(self):
        request = payload()
        data = {"invoice_reference": "CI-1", "sender": request["origin"], "recipient": request["destination"], "gross_weight_kg": "2.5", "hs_codes_reviewed": True,
                "items": [{"description": "Cotton T-shirt", "hs_code": "610910", "origin_country": "GB", "quantity": 3, "unit_value": "12.35", "unit_net_weight_kg": "0.250"}]}
        self.assertEqual(generate_commercial_invoice(data)["totals"]["invoice_value"], "37.05")
        with self.assertRaises(ValidationError):
            generate_commercial_invoice({**data, "hs_codes_reviewed": False})
        with self.assertRaises(ValidationError):
            generate_commercial_invoice({**data, "gross_weight_kg": "0.5"})


class PreviewHTTPTests(unittest.TestCase):
    def setUp(self):
        main.app.state.local_preview = True
        self.client = TestClient(main.app)

    def test_openapi_and_preview_guard(self):
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)
        for path in ("/api/v1/shipments/batch", "/api/v1/audit/invoice", "/v1/rates"):
            self.assertEqual(self.client.post(path).status_code, 503)
        self.assertEqual(self.client.get("/api/v1/config").json()["publishable_key"], None)

    def test_weight_and_preview_rates(self):
        response = self.client.post("/api/v1/rates/preview", json=payload())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["simulated"])
        for rate in data["rates"]:
            fees = rate["fee_breakdown"]
            self.assertEqual(Decimal(fees["label_cost"]) + Decimal(fees["fuel_surcharge"] or '0'), Decimal(rate["client_price_ex_tax"]))
            self.assertNotIn('wholesale_total',fees)
            self.assertNotIn('platform_markup',fees)
        self.assertEqual(self.client.post("/api/v1/logistics/weight", json={"length_cm": "40", "width_cm": "30", "height_cm": "20", "actual_weight_kg": 2.5}).status_code, 422)

    def test_batch_upload(self):
        result = self.client.post("/api/v1/shipments/batch-preview", content=csv_data(), headers={"Content-Type": "text/csv"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["quoted"], 2)
        self.assertEqual(self.client.post("/api/v1/shipments/batch-preview", content="x").status_code, 415)
        partial = self.client.post("/api/v1/shipments/batch-preview", content=csv_data().replace(b"ORDER-1", b"ORDER-0"), headers={"Content-Type": "text/csv"}).json()
        self.assertEqual(partial["quoted"], 1)
        self.assertEqual(partial["results"][1]["status"], "invalid")

    def test_removed_invoice_routes_are_absent(self):
        paths=self.client.get('/openapi.json').json()['paths']
        assert not any('/audit/invoice' in path or '/audit/preview' in path for path in paths)



class FakeConnection:
    def __init__(self, rows):
        self.rows, self.calls = rows, []
    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows
    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "UPDATE 1"


class Acquire:
    def __init__(self, connection): self.connection = connection
    async def __aenter__(self): return self.connection
    async def __aexit__(self, *args): return False


class ConfiguredHTTPTests(unittest.TestCase):
    def setUp(self):
        main.app.state.local_preview = False
        self.context = main.TenantContext(uuid4(), uuid4(), "OWNER", "fixture-token")
        main.app.dependency_overrides[main.authenticate] = lambda: self.context
        self.connection = FakeConnection([])
        main.app.state.finance = SimpleNamespace(pool=SimpleNamespace(acquire=lambda: Acquire(self.connection)))
        self.client = TestClient(main.app)
    def tearDown(self): main.app.dependency_overrides.clear()




    def test_bounded_parallel_batch(self):
        class CSVService:
            active=0
            maximum=0
            automation=SimpleNamespace(order_limiter=asyncio.Semaphore(4))
            async def process(self,context,row):
                self.active+=1
                self.maximum=max(self.maximum,self.active)
                await asyncio.sleep(.01)
                self.active-=1
                return {'row':row['row'],'order_reference':row['order_reference'],'status':'quoted','saved':True}
        service=CSVService();main.app.state.csv_orders=service
        result=self.client.post('/api/v1/shipments/batch',content=csv_data(20),headers={'Content-Type':'text/csv'})
        self.assertEqual(result.json()['quoted'],20)
        self.assertEqual(result.json()['saved'],20)
        self.assertGreater(service.maximum,1)
        self.assertLessEqual(service.maximum,4)


class ProviderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_billable_weight_reaches_provider(self):
        account = SimpleNamespace(provider="EASYPOST", id=uuid4())
        class Repository:
            async def accounts(self, context): return [account]
            async def load(self, context, currency): return []
        class PricingConnection:
            async def fetch(self, sql, *args):
                assert 'FROM public.shipments' in sql
                return []
            def transaction(self, **kwargs): return Acquire(self)
            async def fetchrow(self, sql, *args):
                return {'subscription':{'subscription_plan':'STARTER','plan_period_start':datetime.now(timezone.utc),'plan_enforcement_enabled':True}} if 'AS subscription' in sql else {"default_currency": "GBP", "workspace_status": "ACTIVE"} if "public.tenants" in sql else None
        pricing_pool = SimpleNamespace(acquire=lambda: Acquire(PricingConnection()))
        service = main.RatingService(None, Repository(), SimpleNamespace(max_parallel_provider_requests=4, provider_deadline_seconds=5, quote_ttl_seconds=300), pool=pricing_pool)
        observed = []
        async def run(strategy, request, deadline):
            observed.append(request.weights_kg[0])
            return [main.WholesaleRate(provider="EASYPOST", account_id=account.id, upstream_shipment_id="x", upstream_rate_id="y", carrier_code="DHL", service_code="EXPRESS", currency="GBP", wholesale_cost="10.00")], None
        service.run_provider = run
        context = main.TenantContext(uuid4(), uuid4(), "OWNER", "fixture")
        result = await service.quote(context, main.RatingRequest.model_validate(payload()))
        self.assertEqual(observed, [Decimal("4.800")])
        self.assertEqual(result.rates[0].fee_breakdown["platform_markup"], "1.80")
        self.assertIsNone(result.rates[0].fee_breakdown["fuel_surcharge"])



if __name__ == "__main__":
    unittest.main()
