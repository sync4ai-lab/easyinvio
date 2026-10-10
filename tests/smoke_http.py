"""Verify the running local preview over real HTTP, without external services."""
import csv
import io
from pathlib import Path
import httpx


def run():
    with httpx.Client(base_url="http://127.0.0.1:8000", trust_env=False, timeout=10) as client:
        assert client.get("/health").json()["mode"] == "local-preview"
        assert client.get("/").content == Path("index.html").read_bytes()
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/v1/audit/invoice" in paths and "/api/v1/shipments/batch" in paths
        assert "/api/v1/admin/tenants" in paths and "/api/v1/admin/margins" in paths
        assert client.post("/api/v1/admin/tenants").status_code == 503
        assert client.post("/api/v1/admin/margins").status_code == 503
        assert "/api/v1/billing/test-topup" in paths
        assert client.post("/api/v1/billing/test-topup").status_code == 503
        assert "/api/v1/admin/sandbox/whatsapp-setup" in paths
        assert "/api/v1/shipments/{shipment_id}/label/preview" in paths
        harmonized = client.post("/api/v1/customs/harmonize", json={"item_description": "Silk running sneakers leather trim"}).json()
        assert harmonized["hs_code"] == "640411"
        weight = client.post("/api/v1/logistics/weight", json={"length_cm": "40", "width_cm": "30", "height_cm": "20", "actual_weight_kg": "2.500"}).json()
        assert weight["billable_weight_kg"] == "4.800"
        risk = client.get("/api/v1/routing/preview", params={"origin": "GB", "destination": "FR"}).json()
        assert risk["simulated"] and len(risk["providers"]) == 2
        origin = {"name": "Sender", "line1": "1 Street", "city": "London", "postal_code": "SW1A 1AA", "country_code": "GB"}
        destination = {"name": "Recipient", "line1": "2 Street", "city": "Paris", "postal_code": "75001", "country_code": "FR"}
        quote = client.post("/api/v1/rates/preview", json={"origin": origin, "destination": destination, "dimensions": [{"length_cm": "40", "width_cm": "30", "height_cm": "20"}], "weights_kg": ["2.500"], "currency": "GBP"}).json()
        assert len(quote["rates"]) == 3 and quote["simulated"]
        document = client.post("/api/v1/customs/declaration", json={"invoice_reference": "CI-1", "sender": origin, "recipient": destination, "gross_weight_kg": "2.500", "hs_codes_reviewed": True, "items": [{"description": "Cotton knitted T-shirt", "hs_code": "610910", "origin_country": "GB", "quantity": 2, "unit_value": "12.35", "unit_net_weight_kg": "0.250"}]}).json()
        assert document["totals"]["goods_value"] == "24.70"
        invoice = client.post("/api/v1/audit/preview", json={"invoice_reference": "INV-1", "lines": [{"shipment_id": "00000000-0000-4000-8000-000000001043", "currency": "GBP", "billed_weight_kg": "5.200", "base_cost": "18.00", "fuel_surcharge": "4.00", "residential_fee": "1.50", "remote_area_fee": "7.50"}]}).json()
        assert invoice["results"][0]["overcharge"] == "11.58" and not invoice["disputes_sent"]
        from backend.advanced_logistics import CSV_FIELDS
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        writer.writerow(CSV_FIELDS)
        writer.writerow(["ORDER-1", "Sender", "1 Street", "London", "SW1A 1AA", "GB", "Recipient", "2 Street", "Paris", "75001", "FR", "40", "30", "20", "2.500", "GBP"])
        batch = client.post("/api/v1/shipments/batch-preview", content=text.getvalue(), headers={"Content-Type": "text/csv"}).json()
        assert batch["quoted"] == 1 and batch["bookings_created"] == 0
        assert client.post("/api/v1/audit/invoice").status_code == 503
        cors = client.options("/api/v1/logistics/weight", headers={"Origin": "http://127.0.0.1:5500", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
        assert cors.headers["access-control-allow-origin"] == "http://127.0.0.1:5500"
        assert client.get("/.env").status_code == 404
        with httpx.Client(trust_env=False) as frontend:
            assert frontend.get("http://127.0.0.1:5500/").content == Path("index.html").read_bytes()
            assert frontend.get("http://127.0.0.1:5500/.env").status_code == 404
        print(f"HTTP smoke checks passed: {len(paths)} API paths, current frontend, classification, weight, route history, rates, declaration, audit, batch, CORS and secret-file exclusion.")


if __name__ == "__main__":
    run()
