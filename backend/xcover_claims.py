"""Native XClaim JWT, FNOL, evidence, async claims and signed status events.

Partner-specific FNOL bindings and settlement field paths are configuration,
not guessed wire fields. See https://partner-docs.covergenius.com/xclaim.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time
from decimal import Decimal
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
from uuid import UUID, NAMESPACE_URL, uuid5

import asyncpg
import httpx
from fastapi import HTTPException

from backend.ai_engine import strict_decimal
from backend.shipment_protection import (
    PlatformSettlement,
    XCoverRejected,
    XCoverUncertain,
    decimal_json,
    decoded,
    supplier_address,
)

logger = logging.getLogger(__name__)


def json_pointer(data, pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("An explicit partner-provided JSON pointer is required")
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(data, dict):
            data = data[key]
        elif isinstance(data, list) and key.isdigit():
            data = data[int(key)]
        else:
            raise ValueError("Settlement field does not exist")
    return data


class XClaimClient:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings
        self._token = None
        self._expires = 0
        self._token_lock = asyncio.Lock()

    def unavailable_reason(self):
        if not self.settings.claims_enabled:
            return (
                "Headless XClaim access is not enabled; use the policy claims portal."
            )
        if self.settings.unavailable_reason():
            return (
                "Configure the XCover partner account before enabling headless claims."
            )
        if not re.fullmatch(r"[A-Za-z0-9]+", self.settings.claims_partner_code):
            return "The XClaim partner code is required."
        if (
            not self.settings.claims_api_key.get_secret_value()
            or not self.settings.claims_api_password.get_secret_value()
        ):
            return "XClaim programmatic API key and password are required."
        if len(self.settings.claims_webhook_secret.get_secret_value()) < 32:
            return (
                "A separate 32-byte-or-longer XClaim webhook signing key is required."
            )
        if self.settings.environment == "LIVE":
            try:
                parsed = urlsplit(self.settings.claims_live_api_origin)
                port = parsed.port
            except ValueError:
                return "Set a valid production XClaim HTTPS origin supplied by Cover Genius."
            if (
                parsed.scheme != "https"
                or not (parsed.hostname or "").endswith(".xcover.com")
                or parsed.path not in {"", "/"}
                or port not in {None, 443}
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                return "Set the production XClaim origin supplied by Cover Genius."
        return None

    @property
    def origin(self):
        if self.settings.environment == "TEST":
            return "https://api.xclaim.xcover-staging.com"
        return self.settings.claims_live_api_origin.rstrip("/")

    def partner_path(self):
        return "/partners/" + quote(self.settings.claims_partner_code, safe="")

    async def token(self):
        if self.unavailable_reason():
            raise HTTPException(409, self.unavailable_reason())
        async with self._token_lock:
            if self._token and time.monotonic() < self._expires:
                return self._token
            try:
                response = await self.client.get(
                    self.origin + "/auth/jwt/token/programmatic-access",
                    auth=httpx.BasicAuth(
                        self.settings.claims_api_key.get_secret_value(),
                        self.settings.claims_api_password.get_secret_value(),
                    ),
                    timeout=20,
                    follow_redirects=False,
                )
                data = response.json()["data"]
                if (
                    response.status_code != 200
                    or not isinstance(data["jwt"], str)
                    or not 20 <= len(data["jwt"]) <= 20_000
                    or not re.fullmatch(
                        r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", data["jwt"]
                    )
                ):
                    raise ValueError("Invalid token response")
                minutes = int(data["expiresIn"])
                if minutes < 2:
                    raise ValueError("Invalid token expiry")
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise XCoverUncertain(
                    "XClaim authentication could not be confirmed"
                ) from None
            self._token = data["jwt"]
            self._expires = time.monotonic() + min(minutes * 60 - 60, 3600)
            return self._token

    async def request(self, method, path, *, payload=None, files=None):
        headers = {
            "Authorization": "Bearer " + await self.token(),
            "Accept": "application/json",
        }
        if files is None:
            headers["Content-Type"] = "application/json"
        try:
            response = await self.client.request(
                method,
                self.origin + path,
                headers=headers,
                content=decimal_json(payload).encode() if payload is not None else None,
                files=files,
                timeout=20,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise XCoverUncertain(
                "XClaim response is uncertain; no automatic duplicate submission"
            ) from None
        logger.info("XClaim request method=%s status=%s", method, response.status_code)
        if response.status_code == 401:
            self._token = None
            self._expires = 0
        if response.status_code in {409, 423, 429} or response.status_code >= 500:
            raise XCoverUncertain("XClaim outcome requires reconciliation")
        if not 200 <= response.status_code < 300:
            raise XCoverRejected(
                "XClaim rejected the request (HTTP " + str(response.status_code) + ")"
            )
        if len(response.content) > 2_000_000:
            raise XCoverUncertain("XClaim response is too large")
        try:
            data = json.loads(response.content, parse_float=Decimal)
            if not isinstance(data, dict):
                raise ValueError("Invalid JSON object")
        except (ValueError, UnicodeError):
            raise XCoverUncertain("Invalid XClaim response") from None
        return data

    async def claim_type(self, reason):
        data = (
            await self.request(
                "GET",
                self.partner_path() + "/policy-types/parcel_insurance/claim-types",
            )
        ).get("data")
        if not isinstance(data, list):
            raise XCoverUncertain("Invalid XClaim types")
        match = [
            item
            for item in data
            if isinstance(item, dict) and item.get("name") == reason.lower()
        ]
        if len(match) != 1:
            raise HTTPException(
                409, "The partner product does not advertise this parcel claim type"
            )
        return str(UUID(match[0]["id"]))

    async def fnol(self, claim_type):
        return (
            await self.request(
                "GET", self.partner_path() + "/fnol/" + str(UUID(claim_type))
            )
        ).get("data")

    async def upload(self, data, content_type):
        extension = "png" if content_type == "image/png" else "jpg"
        result = await self.request(
            "POST",
            self.partner_path() + "/files",
            files={"file": ("claim-evidence." + extension, data, content_type)},
        )
        try:
            return str(UUID(result["data"]["id"]))
        except (KeyError, ValueError, TypeError):
            raise XCoverUncertain("XClaim upload reference is missing") from None

    async def create(self, payload):
        result = await self.request(
            "POST", "/api/v2" + self.partner_path() + "/claims", payload=payload
        )
        reference = (result.get("data") or {}).get("claim_reference")
        if not isinstance(reference, str) or not re.fullmatch(
            r"[A-Za-z0-9-]{1,150}", reference
        ):
            raise XCoverUncertain("The asynchronous XClaim reference is missing")
        return reference

    async def get_claim(self, claim_id):
        return (
            await self.request(
                "GET", self.partner_path() + "/claims/" + str(UUID(str(claim_id)))
            )
        ).get("data")

    async def get_reference(self, reference):
        if not re.fullmatch(r"[A-Za-z0-9-]{1,150}", reference):
            raise ValueError("Invalid claim reference")
        return (
            await self.request(
                "GET",
                "/api/v2"
                + self.partner_path()
                + "/claims/"
                + quote(reference, safe=""),
            )
        ).get("data")

    def verify_signature(self, raw, signature):
        if self.unavailable_reason():
            raise HTTPException(503, "Native XClaim receiver is not configured")
        if not isinstance(signature, str) or not signature.startswith("sha256="):
            raise HTTPException(401, "Invalid XClaim signature")
        supplied = signature[len("sha256=") :]
        if not re.fullmatch(r"[A-Za-z0-9+/=]{32,128}", supplied):
            raise HTTPException(401, "Invalid XClaim signature encoding")
        digest = hmac.new(
            self.settings.claims_webhook_secret.get_secret_value().encode(),
            raw,
            hashlib.sha256,
        ).digest()
        if not (
            hmac.compare_digest(supplied, digest.hex())
            or hmac.compare_digest(supplied, base64.b64encode(digest).decode())
        ):
            raise HTTPException(401, "Invalid XClaim signature")


class XClaimService:
    def __init__(self, pool, client, protection):
        self.pool, self.client, self.protection = pool, client, protection

    async def prepare_payload(self, shipment, policy, reason, notes, incident_at=None):
        if self.client.unavailable_reason():
            return None
        bindings = self.client.settings.claims_fnol_bindings.get(reason)
        if not bindings:
            raise HTTPException(
                409,
                "XClaim FNOL field bindings must be configured for this partner before headless submission",
            )
        claim_type = await self.client.claim_type(reason)
        fnol = await self.client.fnol(claim_type)
        if not isinstance(fnol, dict) or not isinstance(fnol.get("sections"), list):
            raise XCoverUncertain("Invalid XClaim FNOL form")
        order = decoded(shipment["logistics_metadata"])["automation_order"]
        address = supplier_address(order["origin"])
        if not address.email and not address.phone:
            raise HTTPException(
                422,
                "The shipment sender needs an email address or telephone number for insurer claim communications",
            )
        sources = {
            "notes": notes,
            "tracking_number": shipment["tracking_number"],
            "first_name": address.first_name,
            "last_name": address.last_name,
            "email": address.email,
            "phone": address.phone,
            "address1": address.address1,
            "address2": address.address2,
            "city": address.city,
            "region": address.region,
            "postcode": address.postcode,
            "country": address.country,
            "photos": None,
            "incident_at": incident_at,
            "declared_value": (
                strict_decimal(policy["declared_value"])
                if policy.get("declared_value")
                else None
            ),
            "currency": "GBP",
        }
        fields = {}
        file_fields = []
        for section in fnol["sections"]:
            for field in section.get("sectionFields", []):
                name = section["name"] + ":" + field["name"]
                source = bindings.get(name)
                if source is None:
                    if field.get("required"):
                        raise HTTPException(
                            422,
                            "The insurer requires additional information for "
                            + name
                            + ". Complete the policy claims portal until its field binding is configured.",
                        )
                    continue
                if source not in sources:
                    raise HTTPException(
                        409, "Unsupported partner FNOL source: " + source
                    )
                if source == "photos":
                    if field.get("type") != "file":
                        raise HTTPException(
                            409, "Photographs must map to an insurer file field"
                        )
                    file_fields.append(
                        {"name": name, "required": bool(field.get("required"))}
                    )
                    continue
                value = sources[source]
                if field.get("required") and value in {None, ""}:
                    raise HTTPException(422, "The insurer requires " + name)
                if value is not None and field.get("type") not in {
                    "string",
                    "email",
                    "date",
                    "datetime",
                    "country",
                    "currency",
                    "numeric",
                }:
                    raise HTTPException(
                        409,
                        "This FNOL binding requires another supported input type: "
                        + name,
                    )
                fields[name] = {"value": value}
        holder = {
            "firstName": address.first_name,
            "lastName": address.last_name,
            "country": address.country,
            "address1": address.address1,
            "postalCode": address.postcode,
            "city": address.city,
        }
        if address.email:
            holder["email"] = address.email
        if address.phone:
            holder["phone"] = address.phone
        payload = {
            "claimTypeId": claim_type,
            "bookingReference": policy["policy_id"],
            "quoteReference": policy["quote_id"],
            "language": "en",
            "claimantSection": holder,
            "sectionFields": fields,
        }
        callback = self.client.settings.claims_webhook_url
        if callback:
            parsed = urlsplit(callback)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path != "/api/v1/shipping/insurance-updates"
            ):
                raise HTTPException(
                    409,
                    "The XClaim callback must be the public HTTPS insurance receiver",
                )
            payload["webhooks"] = [
                {
                    "url": callback,
                    "key": self.client.settings.claims_webhook_secret.get_secret_value(),
                }
            ]
        # The signing key is added just before dispatch, not stored in plaintext.
        if "webhooks" in payload:
            payload["webhooks"][0].pop("key")
        return {"payload": payload, "file_fields": file_fields}

    async def submit_one(self, case_id, tenant_id):
        async with self.pool.acquire() as lock:
            key = "xclaim:" + str(case_id)
            if not await lock.fetchval(
                "SELECT pg_try_advisory_lock(hashtextextended($1,0))", key
            ):
                return False
            try:
                case = await lock.fetchrow(
                    "SELECT * FROM public.insurance_claim_cases WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    case_id,
                )
                if case is None or case["state"] != "SUBMISSION_PENDING":
                    return False
                prepared = decoded(case["submission_payload"])
                payload = prepared["payload"]
                file_ids = []
                evidence = await lock.fetch(
                    "SELECT * FROM public.insurance_claim_evidence WHERE tenant_id=$1 AND case_id=$2 ORDER BY id",
                    tenant_id,
                    case_id,
                )
                for image in evidence:
                    if image["upstream_file_id"]:
                        file_ids.append(str(image["upstream_file_id"]))
                        continue
                    if image["upload_state"] != "PENDING":
                        raise XCoverUncertain(
                            "Existing evidence upload requires reconciliation"
                        )
                    await lock.execute(
                        "UPDATE public.insurance_claim_evidence SET upload_state='SUBMITTED' WHERE tenant_id=$1 AND id=$2",
                        tenant_id,
                        image["id"],
                    )
                    remote = await self.client.upload(
                        bytes(image["content"]), image["content_type"]
                    )
                    await lock.execute(
                        "UPDATE public.insurance_claim_evidence SET upstream_file_id=$3,upload_state='CONFIRMED' WHERE tenant_id=$1 AND id=$2",
                        tenant_id,
                        image["id"],
                        UUID(remote),
                    )
                    file_ids.append(remote)
                for field in prepared["file_fields"]:
                    if field["required"] and not file_ids:
                        raise XCoverRejected("Insurer requires photographic evidence")
                    payload["sectionFields"][field["name"]] = {"value": file_ids}
                if "webhooks" in payload:
                    payload["webhooks"][0][
                        "key"
                    ] = self.client.settings.claims_webhook_secret.get_secret_value()
                # Persist the send fence before POST. The API has no documented
                # idempotency key for claim creation; ambiguous sends stay fenced.
                await lock.execute(
                    "UPDATE public.insurance_claim_cases SET state='SUBMISSION_SUBMITTED',updated_at=now() WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    case_id,
                )
                reference = await self.client.create(payload)
                await lock.execute(
                    "UPDATE public.insurance_claim_cases SET upstream_claim_reference=$3,updated_at=now() WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    case_id,
                    reference,
                )
                return True
            except (
                XCoverRejected,
                XCoverUncertain,
                ValueError,
                KeyError,
                TypeError,
            ) as error:
                await lock.execute(
                    "UPDATE public.insurance_claim_cases SET state='RECONCILIATION_REQUIRED',last_error_code=$3,updated_at=now() WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    case_id,
                    type(error).__name__,
                )
                return False
            finally:
                await lock.execute(
                    "SELECT pg_advisory_unlock(hashtextextended($1,0))", key
                )

    async def reconcile(self, case, data):
        if (
            not isinstance(data, dict)
            or data.get("bookingReference") != case["policy_id"]
            or not isinstance(data.get("status"), dict)
        ):
            raise HTTPException(
                409, "Authoritative XClaim response does not match this policy"
            )
        try:
            remote_id = UUID(str(data["id"]))
        except (ValueError, KeyError, TypeError):
            raise HTTPException(
                503, "Authoritative insurer claim identity is invalid; no wallet credit"
            ) from None
        if case["upstream_claim_id"] and case["upstream_claim_id"] != remote_id:
            raise HTTPException(
                409, "Claim reference differs from the saved insurer claim"
            )
        category = data["status"].get("category")
        state = {
            "Submitted": "INSURER_SUBMITTED",
            "Under Assessment": "UNDER_INSURER_REVIEW",
            "Under Review": "UNDER_INSURER_REVIEW",
            "Action Required": "ACTION_REQUIRED",
            "Declined": "DECLINED",
            "Withdrawn": "DECLINED",
            "Closed": "CLOSED",
            "Duplicate Claim": "ACTION_REQUIRED",
            "Payment Processing": "UNDER_INSURER_REVIEW",
            "Processing": "UNDER_INSURER_REVIEW",
            "Payment Complete": "INSURER_PAYMENT_REPORTED",
            "Settled": "INSURER_PAYMENT_REPORTED",
        }.get(category)
        if state is None:
            raise HTTPException(
                409, "Unrecognized insurer claim status; no wallet credit"
            )
        digest = hashlib.sha256(decimal_json(data).encode()).hexdigest()
        async with self.pool.acquire() as connection:
            await connection.execute(
                """UPDATE public.insurance_claim_cases SET state=$3,upstream_claim_id=$4,
                insurer_status=$5,updated_at=now() WHERE tenant_id=$1 AND id=$2 AND state<>'REFUND_APPROVED_AND_CREDITED' """,
                case["tenant_id"],
                case["id"],
                state,
                remote_id,
                category,
            )
        if state != "INSURER_PAYMENT_REPORTED":
            return {"accepted": True, "claim_status": state, "wallet_credit": False}
        mapping = self.client.settings.claims_settlement_mapping
        required = {
            "amount",
            "currency",
            "payment_reference",
            "payee",
            "funds_received",
            "received_at",
        }
        if set(mapping) != required or not self.client.settings.claims_master_payee_id:
            return {
                "accepted": True,
                "claim_status": state,
                "wallet_credit": False,
                "notice": "Insurer reports payment. Master-account settlement field mapping needs confirmation before automatic wallet credit.",
            }
        try:
            values = {
                name: json_pointer(data, pointer) for name, pointer in mapping.items()
            }
            if (
                values["payee"] != self.client.settings.claims_master_payee_id
                or values["funds_received"] is not True
            ):
                raise ValueError("Master-account receipt is not confirmed")
            amount = strict_decimal(values["amount"])
            reference = values["payment_reference"]
            body = PlatformSettlement(
                tenant_id=case["tenant_id"],
                claim_id=case["id"],
                settlement_id=uuid5(NAMESPACE_URL, "xclaim-payment:" + str(reference)),
                approved_amount=amount,
                currency=values["currency"],
                insurer_payment_reference=reference,
                received_at=values["received_at"],
                funds_received_verified=True,
            )
        except (ValueError, KeyError, TypeError, IndexError):
            raise HTTPException(
                409,
                "Approved amount, currency or confirmed master-account payment could not be reconciled",
            ) from None
        result = await self.protection.credit_settlement(
            body, None, source="XCLAIM_API", response_digest=digest
        )
        return dict(result, wallet_credit=True)

    async def webhook(self, raw, signature):
        self.client.verify_signature(raw, signature)
        try:
            body = json.loads(raw)
            if body.get("event") not in {
                "claim.status-update",
                "claim.status-category-update",
                "claim.deleted",
            }:
                raise ValueError("Unsupported native event")
            remote = UUID(body["payload"]["id"])
            reference = body["payload"].get("claimReference")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(422, "Invalid native XClaim status event") from None
        digest = hashlib.sha256(raw).hexdigest()
        async with self.pool.acquire() as connection:
            cases = await connection.fetch(
                """SELECT * FROM public.insurance_claim_cases WHERE upstream_claim_id=$1
                OR ($2::text IS NOT NULL AND upstream_claim_reference=$2) LIMIT 2""",
                remote,
                reference,
            )
        if len(cases) != 1:
            raise HTTPException(404, "Insurer claim mapping is missing or ambiguous")
        case = cases[0]
        async with self.pool.acquire() as connection:
            sandbox = await connection.fetchval(
                "SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1",
                case["tenant_id"],
            )
        if bool(sandbox) != (self.client.settings.environment == "TEST"):
            raise HTTPException(403, "Claim environment does not match this workspace")
        # Native HMAC protects the body; GET additionally fences stale/replayed status.
        data = await self.client.get_claim(remote)
        result = await self.reconcile(case, data)
        async with self.pool.acquire() as connection:
            await connection.execute(
                """INSERT INTO public.xclaim_webhook_receipts(tenant_id,case_id,body_sha256,event)
                VALUES($1,$2,$3,$4) ON CONFLICT(tenant_id,body_sha256) DO NOTHING""",
                case["tenant_id"],
                case["id"],
                digest,
                body["event"],
            )
        return result

    async def drain(self):
        if self.client.unavailable_reason():
            return 0
        async with self.pool.acquire() as connection:
            if not await connection.fetchval(
                "SELECT to_regclass('public.xclaim_webhook_receipts') IS NOT NULL"
            ):
                return 0
            cases = await connection.fetch(
                """SELECT c.* FROM public.insurance_claim_cases c JOIN public.tenants t ON t.tenant_id=c.tenant_id
                WHERE t.is_sandbox=$1 AND (c.state='SUBMISSION_PENDING' OR
                (c.upstream_claim_reference IS NOT NULL AND c.state NOT IN ('REFUND_APPROVED_AND_CREDITED','DECLINED','CLOSED')))
                ORDER BY c.updated_at LIMIT 20""",
                self.client.settings.environment == "TEST",
            )
        completed = 0
        for case in cases:
            try:
                if case["state"] == "SUBMISSION_PENDING":
                    await self.submit_one(case["id"], case["tenant_id"])
                else:
                    data = await self.client.get_reference(
                        case["upstream_claim_reference"]
                    )
                    await self.reconcile(case, data)
                completed += 1
            except (
                XCoverRejected,
                XCoverUncertain,
                HTTPException,
                ValueError,
                KeyError,
                TypeError,
            ):
                logger.warning(
                    "XClaim reconciliation deferred; no unverified payout was credited"
                )
            finally:
                async with self.pool.acquire() as connection:
                    await connection.execute(
                        "UPDATE public.insurance_claim_cases SET updated_at=now() WHERE tenant_id=$1 AND id=$2",
                        case["tenant_id"],
                        case["id"],
                    )
        return completed

    async def worker(self):
        while True:
            try:
                await self.drain()
            except asyncpg.PostgresError:
                logger.warning(
                    "XClaim jobs remain pending; storage temporarily unavailable"
                )
            await asyncio.sleep(15)
