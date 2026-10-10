"""Offline integration tests; no credentials or external API calls."""
import asyncio
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
from backend.ai_engine import InvoiceLine, audit_invoice_line, predict_hs_code, analyze_tracking_history, record_invoice_baseline
from backend.advanced_logistics import calculate_billable_weight, generate_commercial_invoice, parse_batch_csv, CSV_FIELDS


def payload():
    return {"origin": {"name": "Sender", "line1": "1 Street", "city": "London", "postal_code": "SW1A 1AA", "country_code": "GB"},
            "destination": {"name": "Recipient", "line1": "2 Street", "city": "Paris", "postal_code": "75001", "country_code": "FR"},
            "dimensions": [{"length_cm": "40", "width_cm": "30", "height_cm": "20"}], "weights_kg": ["2.500"], "currency": "GBP"}


def invoice_line(**overrides):
    return InvoiceLine.model_validate({"shipment_id": "00000000-0000-4000-8000-000000001043", "currency": "GBP", "billed_weight_kg": "5.200", "base_cost": "18.00", "fuel_surcharge": "4.00", "residential_fee": "1.50", "remote_area_fee": "7.50", **overrides})


BASELINE = {"currency": "GBP", "billable_weight_kg": "4.800", "base_cost": "16.00", "fuel_surcharge": "1.92", "residential_fee": "1.50", "remote_area_fee": "0.00"}


def csv_data(count=2):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(CSV_FIELDS)
    for index in range(count):
        writer.writerow([f"ORDER-{index}", "Sender", "1 Street", "London", "SW1A 1AA", "GB", "Recipient", "2 Street", "Paris", "75001", "FR", "40", "30", "20", "2.500", "GBP"])
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

    def test_audit_exact_sums_no_weight_double_count(self):
        result = audit_invoice_line(invoice_line(), BASELINE)
        self.assertEqual(result["overcharge"], "11.58")
        self.assertEqual(len(result["findings"]), 4)
        self.assertIn("unsent draft", result["dispute_draft"])

    def test_audit_missing_and_currency(self):
        self.assertIsNone(audit_invoice_line(invoice_line(), {})["overcharge"])
        self.assertEqual(audit_invoice_line(invoice_line(currency="EUR"), BASELINE)["status"], "currency_mismatch")
        self.assertEqual(audit_invoice_line(invoice_line(), {"currency": "GBP"})["status"], "baseline_missing_or_invalid")
        self.assertEqual(audit_invoice_line(invoice_line(), "bad")["status"], "baseline_missing_or_invalid")
        self.assertEqual(audit_invoice_line(invoice_line(), {"currency": []})["status"], "baseline_missing_or_invalid")

    def test_money_rejects_float(self):
        with self.assertRaises(ValidationError):
            invoice_line(base_cost=18.0)
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
            self.assertEqual(Decimal(fees["wholesale_total"]) + Decimal(fees["platform_markup"]), Decimal(rate["client_price_ex_tax"]))
        self.assertEqual(self.client.post("/api/v1/logistics/weight", json={"length_cm": "40", "width_cm": "30", "height_cm": "20", "actual_weight_kg": 2.5}).status_code, 422)

    def test_batch_upload(self):
        result = self.client.post("/api/v1/shipments/batch-preview", content=csv_data(), headers={"Content-Type": "text/csv"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["quoted"], 2)
        self.assertEqual(self.client.post("/api/v1/shipments/batch-preview", content="x").status_code, 415)
        partial = self.client.post("/api/v1/shipments/batch-preview", content=csv_data().replace(b"ORDER-1", b"ORDER-0"), headers={"Content-Type": "text/csv"}).json()
        self.assertEqual(partial["quoted"], 1)
        self.assertEqual(partial["results"][1]["status"], "invalid")

    def test_audit_and_customs(self):
        result = self.client.post("/api/v1/audit/preview", json={"invoice_reference": "INV-1", "lines": [invoice_line().model_dump(mode="json")]})
        self.assertEqual(result.json()["results"][0]["overcharge"], "11.58")
        result = self.client.post("/api/v1/customs/harmonize", json={"item_description": "Silk running sneakers leather trim"})
        self.assertEqual(result.json()["hs_code"], "640411")


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
        self.connection = FakeConnection([{"id": invoice_line().shipment_id, "logistics_metadata": json.dumps({"invoice_baseline": BASELINE})}])
        main.app.state.finance = SimpleNamespace(pool=SimpleNamespace(acquire=lambda: Acquire(self.connection)))
        self.client = TestClient(main.app)
    def tearDown(self): main.app.dependency_overrides.clear()

    def test_invoice_scoped_by_tenant(self):
        response = self.client.post("/api/v1/audit/invoice", json={"invoice_reference": "INV-1", "lines": [invoice_line().model_dump(mode="json")]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["component_overcharges_by_currency"]["GBP"], "11.58")
        sql, args = self.connection.calls[0]
        self.assertIn("tenant_id=$1", sql)
        self.assertEqual(args[0], self.context.tenant_id)

    def test_finance_role_and_unknown_shipment(self):
        self.connection.rows = []
        response = self.client.post("/api/v1/audit/invoice", json={"invoice_reference": "INV-1", "lines": [invoice_line().model_dump(mode="json")]})
        self.assertEqual(response.json()["results"][0]["status"], "shipment_not_found")
        self.connection.calls.clear()
        self.context = main.TenantContext(self.context.tenant_id, self.context.user_id, "DISPATCHER", "fixture-token")
        self.assertEqual(self.client.post("/api/v1/audit/invoice", json={"invoice_reference": "INV-1", "lines": [invoice_line().model_dump(mode="json")]}).status_code, 403)
        self.assertEqual(self.connection.calls, [])

    def test_preview_disabled(self):
        self.assertEqual(self.client.post("/api/v1/rates/preview", json=payload()).status_code, 404)

    def test_bounded_parallel_batch(self):
        class Rating:
            active = 0
            maximum = 0
            async def quote(self, context, request):
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                await asyncio.sleep(0.01)
                self.active -= 1
                return SimpleNamespace(model_dump=lambda **kwargs: {"rates": [], "currency": "GBP"})
        rating = Rating()
        main.app.state.rating = rating
        result = self.client.post("/api/v1/shipments/batch", content=csv_data(20), headers={"Content-Type": "text/csv"})
        self.assertEqual(result.json()["quoted"], 20)
        self.assertGreater(rating.maximum, 1)
        self.assertLessEqual(rating.maximum, 8)


class ProviderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_billable_weight_reaches_provider(self):
        account = SimpleNamespace(provider="EASYPOST", id=uuid4())
        class Repository:
            async def accounts(self, context): return [account]
            async def load(self, context, currency): return []
        class PricingConnection:
            def transaction(self, **kwargs): return Acquire(self)
            async def fetchrow(self, sql, *args):
                return {"default_currency": "GBP", "workspace_status": "ACTIVE"} if "public.tenants" in sql else None
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
        self.assertEqual(result.rates[0].fee_breakdown["platform_markup"], "2.00")
        self.assertIsNone(result.rates[0].fee_breakdown["fuel_surcharge"])

    async def test_baseline_writer_scoped(self):
        connection = FakeConnection([])
        tenant, shipment = uuid4(), uuid4()
        await record_invoice_baseline(connection, tenant, shipment, BASELINE)
        self.assertEqual(connection.calls[0][1][:2], (tenant, shipment))


if __name__ == "__main__":
    unittest.main()
