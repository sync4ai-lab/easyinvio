"""Documented XCover contracts with controlled HTTP; never real insurance."""

import base64
import hashlib
import hmac
import json
import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.utils import format_datetime
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from PIL import Image
from pypdf import PdfReader

from backend.shipment_protection import (
    XCoverAddress,
    XCoverClient,
    XCoverParcelQuote,
    XCoverSettings,
    XCoverUncertain,
    calculate_xcover_premium,
    claims_portal_url,
    decimal_json,
    price_snapshot,
    verify_xcover_webhook,
    xcover_headers,
    load_xcover_settings,
    build_router,
    validate_evidence,
)
from backend.booking_receipt import receipt_pdf


def settings():
    return XCoverSettings(
        _env_file=None,
        enabled=True,
        environment="TEST",
        partner_id="UNITTEST",
        api_key="synthetic-test-key",
        signing_secret="synthetic-test-signing-secret-only",
        parcel_contract_verified=True,
        retail_pricing_verified=True,
    )


def native_headers(config, when=None):
    date = format_datetime(when or datetime.now(timezone.utc), usegmt=True)
    digest = hmac.new(
        config.signing_secret.get_secret_value().encode(),
        ("date: " + date).encode(),
        hashlib.sha256,
    ).digest()
    return {
        "date": date,
        "x-api-key": config.api_key.get_secret_value(),
        "authorization": 'Signature keyId="synthetic-test-key",algorithm="hmac-sha256",signature="'
        + quote(base64.b64encode(digest).decode(), safe="")
        + '"',
    }


class XCoverContractTests(unittest.IsolatedAsyncioTestCase):
    def test_bad_optional_insurance_config_does_not_block_shipping_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text(
                "XCOVER_ENABLED=true\nXCOVER_ENVIRONMENT=INVALID\nXCOVER_CLAIMS_FNOL_BINDINGS=not-json\n",
                encoding="utf-8",
            )
            result = load_xcover_settings(_env_file=path)
            self.assertFalse(result.enabled)
            self.assertFalse(result.claims_enabled)
            self.assertTrue(result.unavailable_reason())

    def test_partner_config_isolated_from_general_app_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text(
                "ENVIRONMENT=DEVELOPMENT\nXCOVER_ENVIRONMENT=TEST\nXCOVER_ENABLED=false\nXCOVER_CLAIMS_FNOL_BINDINGS={}\nXCOVER_CLAIMS_SETTLEMENT_MAPPING={}\n",
                encoding="utf-8",
            )
            self.assertEqual(XCoverSettings(_env_file=path).environment, "TEST")

    async def test_exact_decimal_tariff_and_estimated_margin_are_not_real_profit(self):
        price = await calculate_xcover_premium(Decimal("1"))
        self.assertEqual(price["premium_estimate"], "1.20")
        self.assertEqual(price["estimated_margin"], "0.40")
        self.assertIsNone(price["wholesale_cost"])
        self.assertIsNone(price["profit_margin"])
        self.assertFalse(price["insured"])
        self.assertEqual(decimal_json({"price": Decimal("12.34")}), '{"price":12.34}')
        with self.assertRaises(ValueError):
            decimal_json({"price": float("nan")})

    async def test_real_urls_signatures_tracking_and_idempotency(self):
        config = settings()
        shipment_id, quote_id, key = uuid4(), uuid4(), uuid4()
        requests = []
        holder = XCoverAddress(
            country="GB",
            first_name="Test",
            last_name="Sender",
            address1="1 Test Street",
            city="Leeds",
            postcode="LS1 1AA",
            email="sender@example.test",
        )

        def transport(request):
            requests.append(request)
            self.assertTrue(
                str(request.url).startswith(
                    "https://staging.api.xcover.com/xcover/partners/UNITTEST/"
                )
            )
            self.assertEqual(request.headers["x-idempotency-key"], str(key))
            expected = xcover_headers(
                config.api_key.get_secret_value(),
                config.signing_secret.get_secret_value(),
                datetime.strptime(
                    request.headers["date"], "%a, %d %b %Y %H:%M:%S GMT"
                ).replace(tzinfo=timezone.utc),
            )
            self.assertEqual(
                request.headers["authorization"], expected["Authorization"]
            )
            body = json.loads(request.content, parse_float=Decimal)
            if request.url.path.endswith("/quotes/"):
                self.assertEqual(
                    body["request"][0]["declared_value"], Decimal("123.45")
                )
                self.assertEqual(body["request"][0]["policy_type_version"], 6)
                return httpx.Response(201, json={"id": "UNIT-TEST-INS"})
            self.assertEqual(body["quotes"][0]["tracking_reference"], "TEST-TRACKING")
            self.assertEqual(body["partner_transaction_id"], str(shipment_id))
            return httpx.Response(
                200,
                json={
                    "id": "UNIT-TEST-INS",
                    "currency": "GBP",
                    "status": "CONFIRMED",
                    "partner_transaction_id": str(shipment_id),
                    "total_price": "1.20",
                    "quotes": [
                        {
                            "id": str(quote_id),
                            "status": "CONFIRMED",
                            "policy": {"policy_type": "parcel_insurance"},
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = XCoverClient(http, config)
            parcel = XCoverParcelQuote(
                sender=holder,
                receiver=holder.model_copy(update={"country": "FR"}),
                declared_value=Decimal("123.45"),
                carrier="DPD",
                policy_start_date=datetime.now(timezone.utc),
                shipping_date=datetime.now(timezone.utc),
                partner_transaction_id=shipment_id,
            )
            await client.create_quote(parcel, key)
            await client.book(
                "UNIT-TEST-INS", quote_id, holder, "TEST-TRACKING", shipment_id, key
            )
            with self.assertRaises(ValueError):
                await client.book(
                    "../evil", quote_id, holder, "TEST-TRACKING", shipment_id, key
                )
        self.assertEqual(len(requests), 2)
        self.assertTrue(str(requests[1].url).endswith("/bookings/UNIT-TEST-INS/"))

    async def test_uncertain_purchase_is_not_retried(self):
        calls = []

        def transport(request):
            calls.append(request)
            raise httpx.ReadTimeout("Controlled timeout", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = XCoverClient(http, settings())
            holder = XCoverAddress(
                country="GB",
                first_name="Test",
                address1="1 Test Street",
                city="Leeds",
                postcode="LS1 1AA",
            )
            with self.assertRaises(XCoverUncertain):
                await client.book(
                    "UNIT-TEST-INS", uuid4(), holder, "TEST", uuid4(), uuid4()
                )
        self.assertEqual(len(calls), 1)

    async def test_disabled_credentials_never_make_a_request(self):
        calls = []
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: calls.append(request))
        ) as http:
            with self.assertRaises(HTTPException):
                await XCoverClient(http, XCoverSettings(_env_file=None)).get_booking(
                    "TEST-INS"
                )
        self.assertFalse(calls)

    def test_native_signature_forgery_staleness_and_unsafe_algorithm(self):
        config = settings()
        headers = native_headers(config)
        verify_xcover_webhook(headers, config)
        for bad in [
            dict(
                headers,
                authorization=headers["authorization"].replace(
                    "hmac-sha256", "hmac-sha1"
                ),
            ),
            dict(headers, **{"x-api-key": "other-key"}),
            native_headers(config, datetime.now(timezone.utc) - timedelta(minutes=6)),
        ]:
            with self.assertRaises(HTTPException) as error:
                verify_xcover_webhook(bad, config)
            self.assertEqual(error.exception.status_code, 401)

    async def test_generic_approval_cannot_authorize_a_wallet_credit(self):
        app = FastAPI()
        config = settings()
        app.state.xcover = SimpleNamespace(settings=config)

        async def auth():
            return SimpleNamespace(role="OWNER", tenant_id=uuid4(), user_id=uuid4())

        app.include_router(build_router(auth))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/shipping/insurance-updates",
                headers=native_headers(config),
                json={
                    "event": "APPROVED",
                    "shipment_id": str(uuid4()),
                    "amount": "5000",
                },
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("cannot authorize wallet credit", response.json()["detail"])

    def test_supplier_tax_and_pricing_disagreement_blocks_checkout(self):
        data = {
            "id": "UNIT-TEST-INS",
            "currency": "GBP",
            "total_price": "1.44",
            "quotes": [
                {
                    "id": str(uuid4()),
                    "policy": {"policy_type": "parcel_insurance"},
                    "tax": {"total_tax": "0.24", "total_amount_without_tax": "1.20"},
                    "cover_amount": "100.00",
                    "commission": {"total_commission": "0.40"},
                    "pds_url": "https://www.xcover.com/en/pds/unit-test",
                }
            ],
        }
        self.assertEqual(price_snapshot(data, Decimal("1.20"))["tax"], "0.24")
        with self.assertRaises(HTTPException):
            price_snapshot(data, Decimal("1.20"), Decimal("101.00"))
        for bad in [dict(data, total_price="1.45"), dict(data, currency="USD")]:
            with self.assertRaises(HTTPException):
                price_snapshot(bad, Decimal("1.20"))
        with self.assertRaises(HTTPException):
            price_snapshot(data, Decimal("2.00"))

    def test_private_image_validation_and_portal_host(self):
        image = BytesIO()
        Image.new("RGB", (4, 4)).save(image, format="PNG")
        validate_evidence(image.getvalue(), "image/png")
        for content, kind in [
            (b"<svg/>", "image/png"),
            (image.getvalue(), "image/jpeg"),
            (b"x" * 5_000_001, "image/png"),
        ]:
            with self.assertRaises(HTTPException):
                validate_evidence(content, kind)
        self.assertEqual(
            claims_portal_url("https://www.xcover.com/claims/unit-test"),
            "https://www.xcover.com/claims/unit-test",
        )
        for url in [
            "https://xcover.com.evil.test/claim",
            "http://xcover.com",
            "https://xcover.com:bad",
            "https://evil@xcover.com",
        ]:
            self.assertIsNone(claims_portal_url(url))

    def test_receipt_includes_confirmed_insurance_and_preserves_invoice_reference(self):
        row = {
            "booked_at": datetime.now(timezone.utc),
            "billing_plan": "PREPAID_WALLET",
            "currency": "GBP",
            "customer_reference": "EINVIO-UNIT-TEST",
            "company_name": "Test workspace",
            "tracking_number": "TEST",
            "origin_country": "GB",
            "destination_country": "FR",
            "final_client_price": Decimal("10.00"),
            "tax_amount": Decimal(0),
            "insurance": {
                "provider": "XCOVER",
                "status": "CONFIRMED",
                "policy_id": "UNIT-TEST-INS",
                "premium": "1.20",
                "tax_amount": "0.24",
                "total_charge": "1.44",
            },
        }
        content = "\n".join(
            page.extract_text() for page in PdfReader(BytesIO(receipt_pdf(row))).pages
        )
        for expected in [
            "EINVIO-UNIT-TEST",
            "UNIT-TEST-INS",
            "Shipment protection premium",
            "Protection tax",
            "GBP 11.44",
        ]:
            self.assertIn(expected, content)
