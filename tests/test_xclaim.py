"""Native XClaim contracts; credentials and provider responses are synthetic."""

import hashlib
import hmac
import json
import unittest
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import HTTPException
from pydantic import SecretStr

from backend.xcover_claims import XClaimClient, XClaimService, json_pointer
from test_xcover_protection import settings


def claim_settings():
    result = settings()
    return result.model_copy(
        update={
            "claims_enabled": True,
            "claims_partner_code": "UNITCLAIM",
            "claims_api_key": SecretStr("synthetic-claim-api-key"),
            "claims_api_password": SecretStr("synthetic-claim-password"),
            "claims_webhook_secret": SecretStr(
                "synthetic-claim-body-signature-secret-32"
            ),
            "claims_fnol_bindings": {
                "PARCEL_DAMAGED": {
                    "claim_information:description": "notes",
                    "evidence:photos": "photos",
                }
            },
        }
    )


class XClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_jwt_fnol_upload_async_claim_and_reference_lookup(self):
        calls = []
        claim_type, claim_id, file_id = uuid4(), uuid4(), uuid4()

        def transport(request):
            calls.append(request)
            self.assertEqual(request.url.host, "api.xclaim.xcover-staging.com")
            path = request.url.path
            if path.endswith("/auth/jwt/token/programmatic-access"):
                self.assertTrue(request.headers["authorization"].startswith("Basic "))
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "jwt": "synthetic.synthetic.synthetic",
                            "expiresIn": 20160,
                        }
                    },
                )
            self.assertEqual(
                request.headers["authorization"], "Bearer synthetic.synthetic.synthetic"
            )
            if path.endswith("/claim-types"):
                return httpx.Response(
                    200,
                    json={"data": [{"id": str(claim_type), "name": "parcel_damaged"}]},
                )
            if "/fnol/" in path:
                return httpx.Response(200, json={"data": {"sections": []}})
            if path.endswith("/files"):
                self.assertIn("multipart/form-data", request.headers["content-type"])
                return httpx.Response(201, json={"data": {"id": str(file_id)}})
            if request.method == "POST":
                self.assertEqual(path, "/api/v2/partners/UNITCLAIM/claims")
                return httpx.Response(
                    202, json={"data": {"claim_reference": "UNIT-TEST-CLA"}}
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": str(claim_id),
                        "bookingReference": "UNIT-TEST-INS",
                        "status": {"category": "Submitted"},
                    }
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = XClaimClient(http, claim_settings())
            self.assertEqual(await client.claim_type("PARCEL_DAMAGED"), str(claim_type))
            await client.fnol(str(claim_type))
            self.assertEqual(
                await client.upload(b"controlled-file", "image/png"), str(file_id)
            )
            self.assertEqual(
                await client.create({"claimTypeId": str(claim_type)}), "UNIT-TEST-CLA"
            )
            await client.get_claim(claim_id)
            await client.get_reference("UNIT-TEST-CLA")
        self.assertEqual(sum("/auth/jwt/" in request.url.path for request in calls), 1)

    def test_body_signature_detects_tampering(self):
        client = XClaimClient(None, claim_settings())
        raw = b'{"event":"claim.status-update"}'
        signature = (
            "sha256="
            + hmac.new(
                client.settings.claims_webhook_secret.get_secret_value().encode(),
                raw,
                hashlib.sha256,
            ).hexdigest()
        )
        client.verify_signature(raw, signature)
        with self.assertRaises(HTTPException):
            client.verify_signature(raw + b" ", signature)
        with self.assertRaises(HTTPException):
            client.verify_signature(raw, "sha256=invalid")

    async def test_fnol_required_fields_are_not_invented(self):
        client = SimpleNamespace(
            settings=claim_settings(), unavailable_reason=lambda: None
        )

        async def claim_type(reason):
            return str(uuid4())

        async def fnol(claim_type):
            return {
                "sections": [
                    {
                        "name": "claim_information",
                        "sectionFields": [
                            {"name": "description", "type": "string", "required": True},
                            {"name": "police_report", "type": "file", "required": True},
                        ],
                    }
                ]
            }

        client.claim_type = claim_type
        client.fnol = fnol
        service = XClaimService(None, client, None)
        shipment = {
            "tracking_number": "TEST",
            "logistics_metadata": {
                "automation_order": {
                    "origin": {
                        "name": "Test Sender",
                        "country_code": "GB",
                        "line1": "1 Test Street",
                        "city": "Leeds",
                        "postal_code": "LS1 1AA",
                        "email": "test@example.test",
                    }
                }
            },
        }
        with self.assertRaises(HTTPException) as error:
            await service.prepare_payload(
                shipment,
                {"policy_id": "TEST-INS", "quote_id": str(uuid4())},
                "PARCEL_DAMAGED",
                "Controlled damage notes.",
            )
        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("police_report", error.exception.detail)

    def test_settlement_mapping_uses_explicit_partner_paths(self):
        self.assertEqual(
            json_pointer({"a": {"b/c": [{"~key": "value"}]}}, "/a/b~1c/0/~0key"),
            "value",
        )
        with self.assertRaises((ValueError, KeyError)):
            json_pointer({"amount": "5000"}, "/actual/paid/amount")

    async def test_timeout_does_not_duplicate_claim_post(self):
        calls = []

        def transport(request):
            calls.append(request)
            if "/auth/jwt/" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "jwt": "synthetic.synthetic.synthetic",
                            "expiresIn": 60,
                        }
                    },
                )
            raise httpx.ReadTimeout("Controlled ambiguous creation", request=request)

        from backend.shipment_protection import XCoverUncertain

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            with self.assertRaises(XCoverUncertain):
                await XClaimClient(http, claim_settings()).create(
                    {"bookingReference": "TEST-INS"}
                )
        self.assertEqual(sum(request.method == "POST" for request in calls), 1)
