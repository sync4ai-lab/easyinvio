"""XCover premium arithmetic and explicit integration readiness.

Documented parcel API: https://xcover-api-docs.covergenius.com/parcel_insurance.html
Paid checkout remains gated until partner credentials and product settings
are configured. Native headless claims use the separate XClaim JWT/FNOL/upload
API in backend/xcover_claims.py. Portal referral remains available while
partner claims credentials or insurer form bindings are not configured.
"""

from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID
from uuid import uuid4
from uuid import uuid5, NAMESPACE_URL
from datetime import timedelta
import asyncio
import asyncpg
import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from typing import Literal
from urllib.parse import quote, unquote, urlsplit

import httpx
import pycountry
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response

from backend.ai_engine import strict_decimal

logger = logging.getLogger(__name__)

PROTECTION_NOTICE = (
    "Shipment protection is not available for purchase yet. XCover UK-origin coverage, "
    "partner credentials, the UK-origin parcel product and permitted pricing must be verified. No protection fee is charged."
)
TAX_NOTICE = (
    "The shipping subtotal excludes VAT. VAT is not assessed or collected by the current checkout. "
    "Applicable carrier taxes, import duties and destination charges may be billed separately. "
    "Protection tax treatment will be shown before protection can be purchased."
)


async def calculate_xcover_premium(item_declared_value: Decimal) -> dict:
    """Calculate the requested GBP customer price without creating paid coverage."""
    try:
        value = strict_decimal(item_declared_value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if value > Decimal("5000.00"):
        raise HTTPException(
            400,
            "EasyInvio Error: Declared cargo value exceeds our maximum system protection liability cap of £5,000 per package.",
        )
    if value <= 0:
        raise HTTPException(400, "Declared goods value must be greater than zero")
    premium = max(
        (value * Decimal(".01")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP),
        Decimal("1.20"),
    )
    return {
        "declared_value": str(value),
        "currency": "GBP",
        "premium_estimate": str(premium),
        "maximum_package_value": "5000.00",
        "insured": False,
        "available": False,
        "wholesale_cost": None,
        "profit_margin": None,
        "tax_assessed": False,
        "estimated_baseline_cost": "0.80",
        "estimated_margin": str(premium - Decimal("0.80")),
        "estimate_notice": "The GBP 0.80 baseline is an internal estimate, not an XCover tariff or realized profit.",
        "notice": PROTECTION_NOTICE,
        "tax_notice": TAX_NOTICE,
    }


class XCoverSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="XCOVER_", extra="ignore", hide_input_in_errors=True
    )
    enabled: bool = False
    environment: Literal["TEST", "LIVE"] = "TEST"
    partner_id: str = ""
    api_key: SecretStr = SecretStr("")
    signing_secret: SecretStr = SecretStr("")
    parcel_contract_verified: bool = False
    retail_pricing_verified: bool = False
    claims_enabled: bool = False
    claims_partner_code: str = ""
    claims_api_key: SecretStr = SecretStr("")
    claims_api_password: SecretStr = SecretStr("")
    claims_webhook_secret: SecretStr = SecretStr("")
    claims_webhook_url: str = ""
    claims_live_api_origin: str = ""
    claims_fnol_bindings: dict[str, dict[str, str]] = Field(default_factory=dict)
    claims_settlement_mapping: dict[str, str] = Field(default_factory=dict)
    claims_master_payee_id: str = ""

    @field_validator("environment", mode="before")
    @classmethod
    def environment_alias(cls, value):
        return {"SANDBOX": "TEST", "STAGING": "TEST", "PRODUCTION": "LIVE"}.get(
            str(value).upper(), str(value).upper()
        )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        def partner_dotenv():
            # dotenv sources otherwise pass unprefixed keys matching field names
            # (e.g. the app's ENVIRONMENT) into optional integration settings.
            from dotenv import dotenv_values

            result = {}
            files = dotenv_settings.env_file
            if files is None:
                return result
            if isinstance(files, (str, bytes)) or hasattr(files, "__fspath__"):
                files = [files]
            for filename in files:
                values = dotenv_values(filename, encoding="utf-8")
                for field in cls.model_fields:
                    key = "XCOVER_" + field.upper()
                    if key in values and values[key] is not None:
                        result[field] = (
                            json.loads(values[key])
                            if field
                            in {"claims_fnol_bindings", "claims_settlement_mapping"}
                            else values[key]
                        )
            return result

        return init_settings, env_settings, partner_dotenv, file_secret_settings

    def unavailable_reason(self) -> str | None:
        if not self.enabled:
            return "XCover is disabled. No protection premium is charged."
        if not re.fullmatch(r"[A-Z0-9]+", self.partner_id):
            return "An XCover-issued partner ID is required."
        if (
            not self.api_key.get_secret_value()
            or not self.signing_secret.get_secret_value()
        ):
            return "XCover API key and signing secret are required."
        if not self.parcel_contract_verified or not self.retail_pricing_verified:
            return "The UK-origin parcel product and proposed retail pricing need contractual confirmation."
        return None

    @property
    def base_url(self) -> str:
        return (
            "https://staging.api.xcover.com/xcover"
            if self.environment == "TEST"
            else "https://api.xcover.com/x"
        )


def load_xcover_settings(**kwargs):
    """Optional insurer misconfiguration must not disable shipping or payments."""
    try:
        return XCoverSettings(**kwargs)
    except (ValueError, SettingsError):
        logger.warning(
            "XCover configuration is invalid; protection and claims are disabled. No credential values are logged."
        )
        return XCoverSettings.model_construct(enabled=False, claims_enabled=False)


class PlatformSettlement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    claim_id: UUID
    settlement_id: UUID
    approved_amount: Decimal = Field(gt=0, le=5000, max_digits=8, decimal_places=2)
    currency: Literal["GBP"]
    insurer_payment_reference: str = Field(
        min_length=5, max_length=150, pattern=r"^[A-Za-z0-9_.:/-]+$"
    )
    received_at: datetime
    funds_received_verified: Literal[True]

    @field_validator("approved_amount", mode="before")
    @classmethod
    def exact_payout(cls, value):
        return strict_decimal(value)

    @field_validator("received_at")
    @classmethod
    def received_date(cls, value):
        if value.tzinfo is None or value > datetime.now(timezone.utc):
            raise ValueError(
                "A timezone-aware payment receipt time in the past is required"
            )
        return value


class XCoverAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: str = Field(min_length=2, max_length=2)
    first_name: str = Field(min_length=1, max_length=128)
    last_name: str = Field(default="", max_length=128)
    address1: str = Field(min_length=1, max_length=256)
    address2: str | None = Field(default=None, max_length=256)
    city: str = Field(min_length=1, max_length=128)
    postcode: str = Field(min_length=1, max_length=128)
    region: str | None = Field(default=None, max_length=128)
    email: str | None = Field(
        default=None, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    )
    phone: str | None = Field(default=None, max_length=128)
    company_name: str | None = Field(default=None, max_length=128)

    @field_validator("country")
    @classmethod
    def country_is_valid(cls, value):
        if pycountry.countries.get(alpha_2=value) is None:
            raise ValueError("Valid ISO country required")
        return value


class XCoverGoods(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=10240)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    quantity: int = Field(ge=1)
    hs_code: str | None = Field(default=None, max_length=32)


class XCoverParcelQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: XCoverAddress
    receiver: XCoverAddress
    declared_value: Decimal = Field(gt=0, le=5000, max_digits=8, decimal_places=2)
    carrier: str = Field(min_length=1, max_length=128)
    policy_start_date: datetime
    shipping_date: datetime
    partner_transaction_id: UUID
    items: list[XCoverGoods] = Field(default_factory=list, max_length=100)

    @field_validator("policy_start_date", "shipping_date")
    @classmethod
    def aware_dates(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware shipping dates required")
        return value

    def payload(self):
        if self.sender.country != "GB":
            raise HTTPException(
                422,
                "This proposed protection product is limited to UK-origin shipments",
            )
        payload = {
            "currency": "GBP",
            "customer_country": "GB",
            "partner_transaction_id": str(self.partner_transaction_id),
            "request": [
                {
                    "policy_type": "parcel_insurance",
                    "policy_type_version": 6,
                    "policy_start_date": self.policy_start_date.isoformat(),
                    "shipping_date": self.shipping_date.isoformat(),
                    "sender": self.sender.model_dump(exclude_none=True),
                    "receiver": self.receiver.model_dump(exclude_none=True),
                    "carrier": self.carrier,
                    "origin_country": "GB",
                    "declared_value": self.declared_value,
                }
            ],
        }
        if self.items:
            payload["request"][0]["packages"] = [
                {"items": [item.model_dump(exclude_none=True) for item in self.items]}
            ]
        return payload


def decimal_json(value) -> str:
    """Encode currency as JSON numbers without converting Decimal to float."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite JSON amount")
        return format(value, "f")
    if value is None or isinstance(value, (str, bool, int)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(decimal_json(item) for item in value) + "]"
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return (
            "{"
            + ",".join(
                json.dumps(key) + ":" + decimal_json(item)
                for key, item in value.items()
            )
            + "}"
        )
    raise ValueError("Unsupported JSON value; use exact Decimal amounts")


def xcover_headers(api_key: str, secret: str, now: datetime | None = None) -> dict:
    date = format_datetime(
        (now or datetime.now(timezone.utc)).astimezone(timezone.utc), usegmt=True
    )
    digest = hmac.new(
        secret.encode(), ("date: " + date).encode(), hashlib.sha512
    ).digest()
    signature = quote(base64.b64encode(digest).decode(), safe="")
    return {
        "Date": date,
        "Authorization": f'Signature keyId="{api_key}",algorithm="hmac-sha512",signature="{signature}"',
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


class XCoverRejected(Exception):
    """A documented client rejection; contains no policyholder data."""


class XCoverUncertain(Exception):
    """Timeout/server conflict: reconcile using GET, never repurchase blindly."""


class XCoverClient:
    def __init__(self, client: httpx.AsyncClient, settings: XCoverSettings):
        self.client, self.settings = client, settings

    async def _request(self, method, resource, *, payload=None, idempotency_key=None):
        reason = self.settings.unavailable_reason()
        if reason:
            raise HTTPException(409, reason)
        headers = xcover_headers(
            self.settings.api_key.get_secret_value(),
            self.settings.signing_secret.get_secret_value(),
        )
        if method != "GET":
            if idempotency_key is None:
                raise ValueError("A stable idempotency key is required")
            headers["x-idempotency-key"] = str(UUID(str(idempotency_key)))
        endpoint = (
            self.settings.base_url + "/partners/" + self.settings.partner_id + resource
        )
        try:
            response = await self.client.request(
                method,
                endpoint,
                headers=headers,
                content=(
                    decimal_json(payload).encode("utf-8")
                    if payload is not None
                    else None
                ),
                timeout=20,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            logger.warning("XCover transport outcome uncertain method=%s", method)
            raise XCoverUncertain(
                "XCover response was not confirmed; reconcile before retrying"
            ) from None
        logger.info(
            "XCover request completed method=%s status=%s", method, response.status_code
        )
        if response.status_code in {409, 423, 429} or response.status_code >= 500:
            raise XCoverUncertain("XCover outcome requires reconciliation")
        if not 200 <= response.status_code < 300:
            raise XCoverRejected(
                f"XCover rejected the request (HTTP {response.status_code})"
            )
        if len(response.content) > 1_000_000:
            raise XCoverUncertain("XCover response exceeds the permitted size")
        try:
            data = json.loads(response.content, parse_float=Decimal)
        except (ValueError, UnicodeError):
            raise XCoverUncertain("XCover returned an invalid response") from None
        if not isinstance(data, dict):
            raise XCoverUncertain("XCover returned an invalid response object")
        return data

    @staticmethod
    def resource_id(value):
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9_=-]{1,150}", value
        ):
            raise ValueError("Invalid XCover resource reference")
        return quote(value, safe="")

    async def create_quote(self, parcel: XCoverParcelQuote, idempotency_key: UUID):
        return await self._request(
            "POST",
            "/quotes/",
            payload=parcel.payload(),
            idempotency_key=idempotency_key,
        )

    async def get_quote(self, package_id: str):
        return await self._request(
            "GET", "/quotes/" + self.resource_id(package_id) + "/"
        )

    async def get_booking(self, package_id: str):
        return await self._request(
            "GET", "/bookings/" + self.resource_id(package_id) + "/"
        )

    async def book(
        self,
        package_id: str,
        quote_id: UUID,
        policyholder: XCoverAddress,
        tracking_number: str,
        transaction_id: UUID,
        idempotency_key: UUID,
    ):
        if (
            not isinstance(tracking_number, str)
            or not 1 <= len(tracking_number.strip()) <= 128
        ):
            raise ValueError(
                "A confirmed carrier tracking number is required before policy booking"
            )
        holder = policyholder.model_dump(exclude_none=True, exclude={"company_name"})
        if policyholder.company_name:
            holder["company"] = policyholder.company_name
        payload = {
            "quotes": [
                {"id": str(quote_id), "tracking_reference": tracking_number.strip()}
            ],
            "policyholder": holder,
            "partner_transaction_id": str(transaction_id),
        }
        # No automatic retry: a timed-out POST may have created a policy.
        data = await self._request(
            "POST",
            "/bookings/" + self.resource_id(package_id) + "/",
            payload=payload,
            idempotency_key=idempotency_key,
        )
        self.confirmed_booking(data, package_id, quote_id, transaction_id)
        return data

    @staticmethod
    def confirmed_booking(data, package_id, quote_id, transaction_id):
        if not isinstance(data.get("quotes"), list):
            raise XCoverUncertain("Confirmed policy quotes are missing or invalid")
        if (
            data.get("id") != package_id
            or data.get("status") != "CONFIRMED"
            or data.get("currency") != "GBP"
            or data.get("partner_transaction_id") != str(transaction_id)
            or not any(
                isinstance(item, dict)
                and item.get("id") == str(quote_id)
                and item.get("status") == "CONFIRMED"
                and isinstance(item.get("policy"), dict)
                and item["policy"].get("policy_type") == "parcel_insurance"
                for item in data.get("quotes", [])
            )
        ):
            raise XCoverUncertain(
                "Policy confirmation does not match the booked transaction"
            )
        try:
            if strict_decimal(data["total_price"]) <= 0:
                raise ValueError("Positive premium required")
        except (ValueError, KeyError):
            raise XCoverUncertain(
                "Confirmed policy premium is missing or invalid"
            ) from None


def verify_xcover_webhook(headers, settings, now=None):
    """Verify native date signature; callers must re-fetch authoritative booking.

    Published authentication signs the date, not the body. A valid date signature
    alone must never authorize a wallet credit or trust a supplied policy status.
    """
    if settings.unavailable_reason():
        raise HTTPException(503, "XCover webhook receiver is not configured")
    authorization = headers.get("authorization", "")
    match = re.fullmatch(
        r'Signature keyId="([^"\r\n]+)",algorithm="(hmac-sha256|sha256)",signature="([^"\r\n]+)"',
        authorization,
    )
    if (
        not match
        or not hmac.compare_digest(match[1], settings.api_key.get_secret_value())
        or not hmac.compare_digest(
            headers.get("x-api-key", ""), settings.api_key.get_secret_value()
        )
    ):
        raise HTTPException(401, "Invalid XCover signature")
    date = headers.get("date", "")
    try:
        parsed = parsedate_to_datetime(date)
        if (
            parsed.tzinfo is None
            or abs(((now or datetime.now(timezone.utc)) - parsed).total_seconds()) > 300
        ):
            raise ValueError("Stale timestamp")
        supplied = base64.b64decode(unquote(match[3]), validate=True)
    except (ValueError, TypeError, OverflowError):
        raise HTTPException(401, "Invalid XCover signature timestamp") from None
    expected = hmac.new(
        settings.signing_secret.get_secret_value().encode(),
        ("date: " + date).encode(),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid XCover signature")


def claims_portal_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or not (host == "xcover.com" or host.endswith(".xcover.com"))
    ):
        return None
    return value


def price_snapshot(data, proposed_premium, declared_value=None):
    """Accept the configured retail tariff only when the supplier agrees."""
    try:
        package_id = XCoverClient.resource_id(data["id"])
        quotes = data["quotes"]
        if (
            data["currency"] != "GBP"
            or not isinstance(quotes, list)
            or len(quotes) != 1
            or data.get("errors")
        ):
            raise ValueError("One GBP parcel quote required")
        item = quotes[0]
        if (
            declared_value is not None
            and strict_decimal(item["cover_amount"]) < declared_value
        ):
            raise ValueError("Supplier coverage is below the declared package value")
        if item["policy"]["policy_type"] != "parcel_insurance":
            raise ValueError("Supplier returned a different insurance product")
        quote_id = UUID(item["id"])
        tax = strict_decimal(item["tax"]["total_tax"])
        premium = strict_decimal(item["tax"]["total_amount_without_tax"])
        total = strict_decimal(data["total_price"])
        if any(
            amount != amount.quantize(Decimal(".01"))
            for amount in (tax, premium, total)
        ):
            raise ValueError("Unexpected fractional currency")
        if tax < 0 or premium != proposed_premium or total != premium + tax:
            raise ValueError("Supplier pricing does not match the agreed retail tariff")
        commission = (item.get("commission") or {}).get("total_commission")
        commission = strict_decimal(commission) if commission is not None else None
        if commission is not None and not Decimal(0) <= commission <= premium:
            raise ValueError("Invalid commission")
        terms_url = claims_portal_url(item.get("pds_url") or data.get("pds_url"))
        if not terms_url:
            raise ValueError("Trusted policy disclosure URL required")
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise HTTPException(
            409,
            "XCover did not return the agreed premium, explicit taxes and policy disclosures; no label or policy was purchased",
        ) from None
    return {
        "package_id": unquote(package_id),
        "quote_id": str(quote_id),
        "premium": str(premium),
        "tax": str(tax),
        "total": str(total),
        "commission": str(commission) if commission is not None else None,
        "terms_url": terms_url,
    }


def supplier_address(address):
    first, _, last = address["name"].strip().partition(" ")
    return XCoverAddress(
        country=address["country_code"],
        first_name=first,
        last_name=last,
        address1=address["line1"],
        address2=address.get("line2"),
        city=address["city"],
        postcode=address["postal_code"],
        region=address.get("state"),
        email=address.get("email"),
        phone=address.get("phone"),
        company_name=address.get("company"),
    )


class ProtectionService:
    def __init__(self, pool, client, finance):
        self.pool, self.client, self.finance = pool, client, finance

    async def ready(self):
        reason = self.client.settings.unavailable_reason()
        if reason:
            raise HTTPException(409, reason)
        async with self.pool.acquire() as connection:
            if not await connection.fetchval(
                "SELECT to_regclass('public.insurance_purchases') IS NOT NULL"
            ):
                raise HTTPException(
                    503, "Apply migration 033 before enabling protected wallet checkout"
                )

    async def prepare(self, context, offer_id):
        await self.ready()
        async with self.pool.acquire() as lock:
            offer = await lock.fetchrow(
                """SELECT o.shipment_id,o.rate_snapshot,o.expires_at,s.logistics_metadata,s.status,s.parcel_count
                FROM public.partner_shipping_offers o JOIN public.shipments s ON s.tenant_id=o.tenant_id AND s.id=o.shipment_id
                WHERE o.tenant_id=$1 AND o.offer_id=$2""",
                context.tenant_id,
                offer_id,
            )
            if (
                offer is None
                or offer["status"] != "QUOTED"
                or offer["expires_at"] <= datetime.now(timezone.utc)
            ):
                raise HTTPException(
                    409, "Prepare a current shipping offer before requesting protection"
                )
            if offer["parcel_count"] != 1:
                raise HTTPException(
                    422,
                    "Protection requires a single packed parcel with its own declared value",
                )
            key = (
                "insurance:" + str(context.tenant_id) + ":" + str(offer["shipment_id"])
            )
            if not await lock.fetchval(
                "SELECT pg_try_advisory_lock(hashtextextended($1,0))", key
            ):
                raise HTTPException(409, "Protection is already being prepared")
            try:
                existing = await lock.fetchrow(
                    "SELECT * FROM public.insurance_purchases WHERE tenant_id=$1 AND shipment_id=$2",
                    context.tenant_id,
                    offer["shipment_id"],
                )
                if existing:
                    if (
                        existing["offer_id"] != offer_id
                        or existing["state"] != "QUOTED"
                        or existing["expires_at"] <= datetime.now(timezone.utc)
                    ):
                        raise HTTPException(
                            409,
                            "Protection quote is unavailable or expired; request a new shipment quote",
                        )
                    return self.public_quote(existing)
                order = (
                    decoded(offer["logistics_metadata"]).get("automation_order") or {}
                )
                rate = decoded(offer["rate_snapshot"])
                if (
                    order.get("customs_currency", order.get("currency")) != "GBP"
                    or rate.get("currency") != "GBP"
                ):
                    raise HTTPException(
                        422,
                        "Protected wallet checkout currently requires goods and shipping valued in GBP",
                    )
                items = order.get("items") or []
                if not items:
                    raise HTTPException(
                        422, "Declared goods details are required for protection"
                    )
                value = sum(
                    (
                        strict_decimal(item["unit_value"]) * int(item["quantity"])
                        for item in items
                    ),
                    Decimal(0),
                )
                pricing = await calculate_xcover_premium(value)
                try:
                    parcel = XCoverParcelQuote(
                        sender=supplier_address(order["origin"]),
                        receiver=supplier_address(order["destination"]),
                        declared_value=value,
                        carrier=rate["carrier_code"],
                        policy_start_date=datetime.now(timezone.utc),
                        shipping_date=datetime.now(timezone.utc),
                        partner_transaction_id=offer["shipment_id"],
                        items=[
                            XCoverGoods(
                                description=item["description"],
                                price=strict_decimal(item["unit_value"]),
                                quantity=int(item["quantity"]),
                                hs_code=item.get("hs_code") or None,
                            )
                            for item in items
                        ],
                    )
                except (ValueError, KeyError, TypeError):
                    raise HTTPException(
                        422,
                        "Shipment addresses or goods do not meet the insurer format; correct the shipment and obtain a fresh quote",
                    ) from None
                # Local UUID is the authoritative correlation key sent to XCover.
                parcel.payload()
                purchase_id = uuid5(NAMESPACE_URL, key)
                async with lock.transaction():
                    tenant = await self.finance.lock_tenant(
                        lock,
                        context.tenant_id,
                        context,
                        {"OWNER", "ADMIN", "DISPATCHER"},
                    )
                    if (
                        tenant["billing_plan"] != "PREPAID_WALLET"
                        or tenant["billing_status"] != "ACTIVE"
                    ):
                        raise HTTPException(
                            409, "Protection requires an active prepaid wallet"
                        )
                    if bool(tenant["is_sandbox"]) != (
                        self.client.settings.environment == "TEST"
                    ):
                        raise HTTPException(
                            403, "Insurance environment does not match this workspace"
                        )
                    await lock.execute(
                        """INSERT INTO public.insurance_purchases
                        (id,tenant_id,shipment_id,offer_id,declared_value,state,expires_at,requested_by)
                        VALUES($1,$2,$3,$4,$5,'QUOTE_PENDING',$6,$7)""",
                        purchase_id,
                        context.tenant_id,
                        offer["shipment_id"],
                        offer_id,
                        value,
                        min(
                            offer["expires_at"],
                            datetime.now(timezone.utc) + timedelta(minutes=10),
                        ),
                        context.user_id,
                    )
                try:
                    quote_data = await self.client.create_quote(
                        parcel, uuid5(purchase_id, "quote")
                    )
                    snapshot = price_snapshot(
                        quote_data, Decimal(pricing["premium_estimate"]), value
                    )
                except (XCoverRejected, XCoverUncertain, HTTPException):
                    await lock.execute(
                        "UPDATE public.insurance_purchases SET state='RECONCILIATION_REQUIRED',updated_at=now() WHERE tenant_id=$1 AND id=$2",
                        context.tenant_id,
                        purchase_id,
                    )
                    raise HTTPException(
                        409,
                        "Protection quote could not be confirmed; no label purchase or wallet charge occurred",
                    ) from None
                await lock.execute(
                    """UPDATE public.insurance_purchases SET state='QUOTED',package_id=$3,quote_id=$4,
                    premium=$5,tax_amount=$6,total_charge=$7,reported_commission=$8,terms_url=$9,updated_at=now()
                    WHERE tenant_id=$1 AND id=$2""",
                    context.tenant_id,
                    purchase_id,
                    snapshot["package_id"],
                    UUID(snapshot["quote_id"]),
                    Decimal(snapshot["premium"]),
                    Decimal(snapshot["tax"]),
                    Decimal(snapshot["total"]),
                    (
                        Decimal(snapshot["commission"])
                        if snapshot["commission"] is not None
                        else None
                    ),
                    snapshot["terms_url"],
                )
                row = await lock.fetchrow(
                    "SELECT * FROM public.insurance_purchases WHERE tenant_id=$1 AND id=$2",
                    context.tenant_id,
                    purchase_id,
                )
                return self.public_quote(row)
            finally:
                await lock.execute(
                    "SELECT pg_advisory_unlock(hashtextextended($1,0))", key
                )

    @staticmethod
    def public_quote(row):
        return {
            "insurance_quote_id": str(row["id"]),
            "premium": str(row["premium"]),
            "tax_amount": str(row["tax_amount"]),
            "total_charge": str(row["total_charge"]),
            "currency": "GBP",
            "terms_url": row["terms_url"],
            "expires_at": row["expires_at"].isoformat(),
            "insured": False,
        }

    async def ledger(
        self, connection, row, kind, balance_delta, reserved_delta, wallet
    ):
        await connection.execute(
            """INSERT INTO public.wallet_ledger
            (tenant_id,currency,entry_type,balance_delta,reserved_delta,balance_after,reserved_after,insurance_purchase_id,insurance_reported_commission,insurance_estimated_baseline_cost,insurance_estimated_margin)
            VALUES($1,'GBP',$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
            row["tenant_id"],
            kind,
            balance_delta,
            reserved_delta,
            wallet["balance"] + balance_delta,
            wallet["reserved_balance"] + reserved_delta,
            row["id"],
            row["reported_commission"] if kind == "INSURANCE_CAPTURE" else None,
            Decimal("0.80") if kind == "INSURANCE_CAPTURE" else None,
            row["premium"] - Decimal("0.80") if kind == "INSURANCE_CAPTURE" else None,
        )

    async def reserve(self, context, purchase_id, offer_id):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.finance.lock_tenant(
                    connection,
                    context.tenant_id,
                    context,
                    {"OWNER", "ADMIN", "DISPATCHER"},
                )
                row = await connection.fetchrow(
                    "SELECT * FROM public.insurance_purchases WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                    context.tenant_id,
                    purchase_id,
                )
                if row is None or row["offer_id"] != offer_id:
                    raise HTTPException(
                        404, "Protection quote not found for this offer"
                    )
                if row["state"] in {"RESERVED", "POLICY_SUBMITTED", "INSURED"}:
                    return row
                if row["state"] != "QUOTED" or row["expires_at"] <= datetime.now(
                    timezone.utc
                ):
                    raise HTTPException(409, "Protection quote is not bookable")
                shipment = await connection.fetchrow(
                    """SELECT s.status,o.rate_snapshot FROM public.shipments s
                    JOIN public.partner_shipping_offers o ON o.tenant_id=s.tenant_id AND o.shipment_id=s.id
                    WHERE s.tenant_id=$1 AND s.id=$2 AND o.offer_id=$3 FOR UPDATE OF s""",
                    context.tenant_id,
                    row["shipment_id"],
                    offer_id,
                )
                if shipment is None or shipment["status"] != "QUOTED":
                    raise HTTPException(
                        409, "Shipping offer is no longer ready for purchase"
                    )
                label_charge = strict_decimal(
                    decoded(shipment["rate_snapshot"])["client_price_ex_tax"]
                )
                wallet = await self.finance.lock_wallet(connection, context.tenant_id)
                if (
                    wallet["currency"] != "GBP"
                    or wallet["balance"] - wallet["reserved_balance"]
                    < label_charge + row["total_charge"]
                ):
                    raise HTTPException(
                        402,
                        "Wallet needs enough available GBP credit for both the label and protection, including protection tax",
                    )
                await connection.execute(
                    "UPDATE public.wallets SET reserved_balance=reserved_balance+$2,updated_at=now() WHERE tenant_id=$1",
                    context.tenant_id,
                    row["total_charge"],
                )
                await self.ledger(
                    connection,
                    row,
                    "INSURANCE_RESERVE",
                    Decimal(0),
                    row["total_charge"],
                    wallet,
                )
                pending = {
                    "provider": "XCOVER",
                    "status": "PENDING",
                    "premium": str(row["premium"]),
                    "tax_amount": str(row["tax_amount"]),
                    "total_charge": str(row["total_charge"]),
                }
                await connection.execute(
                    "UPDATE public.shipments SET logistics_metadata=logistics_metadata||jsonb_build_object('insurance',$3::jsonb) WHERE tenant_id=$1 AND id=$2",
                    context.tenant_id,
                    row["shipment_id"],
                    json.dumps(pending),
                )
                await connection.execute(
                    "UPDATE public.insurance_purchases SET state='RESERVED',terms_accepted_at=now(),terms_accepted_by=$3,updated_at=now() WHERE tenant_id=$1 AND id=$2",
                    context.tenant_id,
                    row["id"],
                    context.user_id,
                )
                return row

    async def release(self, tenant_id, row):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.finance.lock_tenant(connection, tenant_id)
                current = await connection.fetchrow(
                    "SELECT state FROM public.insurance_purchases WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                    tenant_id,
                    row["id"],
                )
                if current["state"] not in {"RESERVED", "POLICY_SUBMITTED"}:
                    return
                wallet = await self.finance.lock_wallet(connection, tenant_id)
                if wallet["reserved_balance"] < row["total_charge"]:
                    raise HTTPException(
                        503, "Protection reservation requires reconciliation"
                    )
                await connection.execute(
                    "UPDATE public.wallets SET reserved_balance=reserved_balance-$2,updated_at=now() WHERE tenant_id=$1",
                    tenant_id,
                    row["total_charge"],
                )
                await self.ledger(
                    connection,
                    row,
                    "INSURANCE_RELEASE",
                    Decimal(0),
                    -row["total_charge"],
                    wallet,
                )
                await connection.execute(
                    "UPDATE public.insurance_purchases SET state='FAILED',updated_at=now() WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    row["id"],
                )
                await connection.execute(
                    "UPDATE public.shipments SET logistics_metadata=jsonb_set(logistics_metadata,'{insurance,status}','\"FAILED\"'::jsonb) WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    row["shipment_id"],
                )

    async def book(
        self, tenant_id, shipment_id, item_declared_value, carrier_tracking_code
    ):
        await self.ready()
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM public.insurance_purchases WHERE tenant_id=$1 AND shipment_id=$2",
                tenant_id,
                shipment_id,
            )
            shipment = await connection.fetchrow(
                "SELECT status,tracking_number,logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2",
                tenant_id,
                shipment_id,
            )
        if (
            row is None
            or shipment is None
            or row["declared_value"] != item_declared_value
            or shipment["tracking_number"] != carrier_tracking_code
        ):
            raise HTTPException(409, "Protection inputs do not match the saved booking")
        if row["state"] == "INSURED":
            return {
                "policy_id": row["package_id"],
                "insured": True,
                "premium_charged": str(row["total_charge"]),
            }
        if shipment["status"] not in {
            "BOOKED",
            "MANIFESTED",
            "DISPATCHED",
            "IN_TRANSIT",
            "DELIVERED",
            "EXCEPTION",
        } or row["state"] not in {"RESERVED", "POLICY_SUBMITTED"}:
            raise HTTPException(
                409, "A confirmed label and reserved protection premium are required"
            )
        holder = supplier_address(
            decoded(shipment["logistics_metadata"])["automation_order"]["origin"]
        )
        try:
            if row["state"] == "POLICY_SUBMITTED":
                booking = await self.client.get_booking(row["package_id"])
                self.client.confirmed_booking(
                    booking, row["package_id"], row["quote_id"], shipment_id
                )
            else:
                async with self.pool.acquire() as connection:
                    changed = await connection.fetchval(
                        "UPDATE public.insurance_purchases SET state='POLICY_SUBMITTED',updated_at=now() WHERE tenant_id=$1 AND id=$2 AND state='RESERVED' RETURNING id",
                        tenant_id,
                        row["id"],
                    )
                if changed is None:
                    raise HTTPException(409, "Policy purchase is already in progress")
                booking = await self.client.book(
                    row["package_id"],
                    row["quote_id"],
                    holder,
                    carrier_tracking_code,
                    shipment_id,
                    uuid5(row["id"], "book"),
                )
        except XCoverRejected:
            if row["state"] == "POLICY_SUBMITTED":
                raise HTTPException(
                    503,
                    "Existing policy could not be retrieved; reserved credit is retained for reconciliation",
                ) from None
            await self.release(tenant_id, row)
            raise HTTPException(
                409,
                "Label was created but XCover rejected protection. No protection fee was captured",
            ) from None
        except XCoverUncertain:
            raise HTTPException(
                503,
                "Label was created; protection remains unconfirmed. Reserved protection credit is retained for reconciliation",
            ) from None
        try:
            prices_match = (
                strict_decimal(booking["total_price"]) == row["total_charge"]
                and strict_decimal(booking["total_tax"]) == row["tax_amount"]
            )
        except (ValueError, KeyError):
            prices_match = False
        if not prices_match:
            raise HTTPException(
                503,
                "Confirmed policy price differs from the reserved amount; reconciliation is required",
            )
        booked_quote = next(
            item for item in booking["quotes"] if item["id"] == str(row["quote_id"])
        )
        commission = (booked_quote.get("commission") or {}).get("total_commission")
        try:
            commission = strict_decimal(commission) if commission is not None else None
            if commission is not None and (
                commission < 0 or commission > row["premium"]
            ):
                raise ValueError("Commission outside premium")
        except ValueError:
            raise HTTPException(
                503, "Supplier commission requires reconciliation"
            ) from None
        row = dict(row, reported_commission=commission)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.finance.lock_tenant(connection, tenant_id)
                current = await connection.fetchrow(
                    "SELECT state FROM public.insurance_purchases WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                    tenant_id,
                    row["id"],
                )
                if current["state"] == "INSURED":
                    return {
                        "policy_id": row["package_id"],
                        "insured": True,
                        "premium_charged": str(row["total_charge"]),
                    }
                if current["state"] != "POLICY_SUBMITTED":
                    raise HTTPException(
                        503, "Policy settlement state requires reconciliation"
                    )
                wallet = await self.finance.lock_wallet(connection, tenant_id)
                if (
                    wallet["currency"] != "GBP"
                    or wallet["reserved_balance"] < row["total_charge"]
                    or wallet["balance"] < row["total_charge"]
                ):
                    raise HTTPException(
                        503, "Policy wallet settlement requires reconciliation"
                    )
                await connection.execute(
                    "UPDATE public.wallets SET balance=balance-$2,reserved_balance=reserved_balance-$2,updated_at=now() WHERE tenant_id=$1",
                    tenant_id,
                    row["total_charge"],
                )
                await self.ledger(
                    connection,
                    row,
                    "INSURANCE_CAPTURE",
                    -row["total_charge"],
                    -row["total_charge"],
                    wallet,
                )
                policy = {
                    "provider": "XCOVER",
                    "declared_value": str(row["declared_value"]),
                    "status": "CONFIRMED",
                    "policy_id": row["package_id"],
                    "quote_id": str(row["quote_id"]),
                    "premium": str(row["premium"]),
                    "tax_amount": str(row["tax_amount"]),
                    "total_charge": str(row["total_charge"]),
                    "reported_commission": (
                        str(row["reported_commission"])
                        if row["reported_commission"] is not None
                        else None
                    ),
                }
                await connection.execute(
                    """UPDATE public.shipments SET logistics_metadata=logistics_metadata||jsonb_build_object(
                    'insurance',$3::jsonb,'insurance_policy_id',$4::text),updated_at=now() WHERE tenant_id=$1 AND id=$2""",
                    tenant_id,
                    shipment_id,
                    json.dumps(policy),
                    row["package_id"],
                )
                await connection.execute(
                    "UPDATE public.insurance_purchases SET state='INSURED',reported_commission=$3,updated_at=now() WHERE tenant_id=$1 AND id=$2",
                    tenant_id,
                    row["id"],
                    commission,
                )
                await connection.execute(
                    """INSERT INTO public.workspace_dispatch_events(tenant_id,shipment_id,status)
                    SELECT tenant_id,id,status::text FROM public.shipments WHERE tenant_id=$1 AND id=$2""",
                    tenant_id,
                    shipment_id,
                )
                await connection.execute(
                    "SELECT pg_notify('easyinvio_dispatch',json_build_object('tenant_id',$1::text,'shipment_id',$2::text,'insurance','CONFIRMED')::text)",
                    str(tenant_id),
                    str(shipment_id),
                )
        return {
            "policy_id": row["package_id"],
            "insured": True,
            "premium_charged": str(row["total_charge"]),
        }

    async def confirm(self, context, body, lifecycle):
        await self.ready()
        if body.insurance_quote_id is None:
            raise HTTPException(
                422,
                "Review the actual protection premium, tax and terms before confirming",
            )
        if not body.insurance_terms_accepted:
            raise HTTPException(
                422,
                "Accept the actual protection policy terms and total before confirming",
            )
        async with self.pool.acquire() as lock:
            key = (
                "protected-booking:"
                + str(context.tenant_id)
                + ":"
                + str(body.insurance_quote_id)
            )
            if not await lock.fetchval(
                "SELECT pg_try_advisory_lock(hashtextextended($1,0))", key
            ):
                raise HTTPException(409, "Protected booking is already in progress")
            try:
                row = await self.reserve(
                    context, body.insurance_quote_id, body.offer_id
                )
                booked = await lock.fetchrow(
                    "SELECT logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2 AND booked_at IS NOT NULL",
                    context.tenant_id,
                    row["shipment_id"],
                )
                if booked:
                    metadata = decoded(booked["logistics_metadata"])
                    result = lifecycle.public_result(
                        row["shipment_id"],
                        metadata["automation_label"],
                        metadata.get("automation_customs"),
                        True,
                    )
                else:
                    try:
                        result = await lifecycle.confirm(
                            context,
                            body.model_copy(
                                update={
                                    "insurance_requested": False,
                                    "insurance_quote_id": None,
                                    "insurance_terms_accepted": False,
                                }
                            ),
                        )
                    except Exception:
                        status = await lock.fetchval(
                            "SELECT status FROM public.shipments WHERE tenant_id=$1 AND id=$2",
                            context.tenant_id,
                            row["shipment_id"],
                        )
                        if status in {"QUOTED", "FAILED", "DRAFT"}:
                            await self.release(context.tenant_id, row)
                        raise
                tracking = await lock.fetchval(
                    "SELECT tracking_number FROM public.shipments WHERE tenant_id=$1 AND id=$2 AND booked_at IS NOT NULL",
                    context.tenant_id,
                    row["shipment_id"],
                )
                if not tracking:
                    return dict(
                        result,
                        insurance={
                            "insured": False,
                            "status": "AWAITING_LABEL_CONFIRMATION",
                        },
                    )
                try:
                    insurance = await book_xcover_policy(
                        row["shipment_id"],
                        row["declared_value"],
                        tracking,
                        service=self,
                        tenant_id=context.tenant_id,
                    )
                except HTTPException as exc:
                    # Label already exists. The UI must show it and the protection outcome.
                    return dict(
                        result,
                        insurance={
                            "insured": False,
                            "status": "RECONCILIATION_REQUIRED",
                            "notice": str(exc.detail),
                        },
                    )
                return dict(result, insurance=insurance)
            finally:
                await lock.execute(
                    "SELECT pg_advisory_unlock(hashtextextended($1,0))", key
                )

    async def reconcile_pending(self):
        if self.client.settings.unavailable_reason():
            return 0
        await self.ready()
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT p.id,p.tenant_id,p.shipment_id,p.declared_value,p.total_charge,s.tracking_number,s.booked_at
                FROM public.insurance_purchases p JOIN public.shipments s ON s.tenant_id=p.tenant_id AND s.id=p.shipment_id
                JOIN public.tenants t ON t.tenant_id=p.tenant_id
                WHERE p.state IN ('RESERVED','POLICY_SUBMITTED') AND t.is_sandbox=$1
                AND ((s.booked_at IS NOT NULL AND s.tracking_number IS NOT NULL)
                 OR (p.state='RESERVED' AND s.status IN ('QUOTED','FAILED','DRAFT') AND p.updated_at<now()-interval '2 minutes'))
                ORDER BY p.updated_at LIMIT 20""",
                self.client.settings.environment == "TEST",
            )
        completed = 0
        for row in rows:
            async with self.pool.acquire() as lock:
                key = (
                    "protected-booking:" + str(row["tenant_id"]) + ":" + str(row["id"])
                )
                if not await lock.fetchval(
                    "SELECT pg_try_advisory_lock(hashtextextended($1,0))", key
                ):
                    continue
                try:
                    if row["booked_at"]:
                        await self.book(
                            row["tenant_id"],
                            row["shipment_id"],
                            row["declared_value"],
                            row["tracking_number"],
                        )
                    else:
                        await self.release(row["tenant_id"], row)
                    completed += 1
                except HTTPException as error:
                    logger.warning(
                        "XCover policy reconciliation deferred status=%s",
                        error.status_code,
                    )
                finally:
                    await lock.execute(
                        "UPDATE public.insurance_purchases SET updated_at=now() WHERE tenant_id=$1 AND id=$2",
                        row["tenant_id"],
                        row["id"],
                    )
                    await lock.execute(
                        "SELECT pg_advisory_unlock(hashtextextended($1,0))", key
                    )
        return completed

    async def worker(self):
        while True:
            try:
                await self.reconcile_pending()
            except (asyncpg.PostgresError, HTTPException):
                logger.warning(
                    "XCover reconciliation remains pending; no unconfirmed premium was captured"
                )
            await asyncio.sleep(15)

    async def credit_settlement(
        self,
        body: PlatformSettlement,
        verified_by,
        source="PLATFORM_OPERATOR",
        response_digest=None,
    ):
        service = self
        await service.ready()
        async with service.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await service.finance.lock_tenant(connection, body.tenant_id)
                if (
                    tenant["workspace_status"] != "ACTIVE"
                    or tenant["billing_status"] != "ACTIVE"
                    or tenant["billing_plan"] != "PREPAID_WALLET"
                ):
                    raise HTTPException(
                        409, "Settlement requires an active prepaid workspace"
                    )
                if bool(tenant["is_sandbox"]) != (
                    service.client.settings.environment == "TEST"
                ):
                    raise HTTPException(403, "Settlement environment mismatch")
                case = await connection.fetchrow(
                    "SELECT * FROM public.insurance_claim_cases WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                    body.tenant_id,
                    body.claim_id,
                )
                if case is None:
                    raise HTTPException(
                        404, "Insurance case not found in this workspace"
                    )
                existing = await connection.fetchrow(
                    """SELECT id,approved_amount,insurer_payment_reference FROM public.insurance_settlements
                    WHERE tenant_id=$1 AND case_id=$2""",
                    body.tenant_id,
                    body.claim_id,
                )
                if existing:
                    if (
                        existing["id"] != body.settlement_id
                        or existing["approved_amount"] != body.approved_amount
                        or existing["insurer_payment_reference"]
                        != body.insurer_payment_reference
                    ):
                        raise HTTPException(
                            409, "This claim already has a reconciled settlement"
                        )
                    return {
                        "settlement_id": str(existing["id"]),
                        "status": "REFUND_APPROVED_AND_CREDITED",
                        "duplicate": True,
                    }
                purchase = await connection.fetchrow(
                    "SELECT declared_value,state,package_id FROM public.insurance_purchases WHERE tenant_id=$1 AND shipment_id=$2",
                    body.tenant_id,
                    case["shipment_id"],
                )
                if (
                    purchase is None
                    or purchase["state"] != "INSURED"
                    or purchase["package_id"] != case["policy_id"]
                    or body.approved_amount > purchase["declared_value"]
                ):
                    raise HTTPException(
                        409,
                        "Verified insured booking and payout within its declared limit required",
                    )
                already_paid = await connection.fetchval(
                    "SELECT coalesce(sum(approved_amount),0) FROM public.insurance_settlements WHERE tenant_id=$1 AND shipment_id=$2",
                    body.tenant_id,
                    case["shipment_id"],
                )
                if already_paid + body.approved_amount > purchase["declared_value"]:
                    raise HTTPException(
                        409,
                        "Total payments would exceed this package’s insured liability",
                    )
                wallet = await service.finance.lock_wallet(connection, body.tenant_id)
                if wallet["currency"] != body.currency:
                    raise HTTPException(
                        409,
                        "Settlement currency differs from this wallet; no exchange rate was assumed",
                    )
                inserted = await connection.fetchval(
                    """INSERT INTO public.insurance_settlements
                    (id,tenant_id,case_id,shipment_id,approved_amount,currency,insurer_payment_reference,received_at,verified_by,verification_source,provider_response_sha256)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT DO NOTHING RETURNING id""",
                    body.settlement_id,
                    body.tenant_id,
                    body.claim_id,
                    case["shipment_id"],
                    body.approved_amount,
                    body.currency,
                    body.insurer_payment_reference,
                    body.received_at,
                    verified_by,
                    source,
                    response_digest,
                )
                if inserted is None:
                    raise HTTPException(
                        409, "Settlement or payment reference was already reconciled"
                    )
                await connection.execute(
                    "UPDATE public.wallets SET balance=balance+$2,updated_at=now() WHERE tenant_id=$1",
                    body.tenant_id,
                    body.approved_amount,
                )
                await connection.execute(
                    """INSERT INTO public.wallet_ledger
                    (tenant_id,currency,entry_type,balance_delta,reserved_delta,balance_after,reserved_after,insurance_settlement_id)
                    VALUES($1,$2,'INSURANCE_CLAIM_CREDIT',$3,0,$4,$5,$6)""",
                    body.tenant_id,
                    body.currency,
                    body.approved_amount,
                    wallet["balance"] + body.approved_amount,
                    wallet["reserved_balance"],
                    body.settlement_id,
                )
                await connection.execute(
                    "UPDATE public.insurance_claim_cases SET state='REFUND_APPROVED_AND_CREDITED' WHERE tenant_id=$1 AND id=$2",
                    body.tenant_id,
                    body.claim_id,
                )
                ticket = await connection.fetchval(
                    "UPDATE public.support_tickets SET status='CLOSED',archived_at=now() WHERE tenant_id=$1 AND insurance_claim_id=$2 RETURNING id",
                    body.tenant_id,
                    body.claim_id,
                )
                if ticket:
                    await connection.execute(
                        """INSERT INTO public.support_ticket_activity
                        (tenant_id,ticket_id,actor_auth_user_id,actor_name,activity_type,note)
                        VALUES($1,$2,$3,$4,'RESOLVED',$5)""",
                        body.tenant_id,
                        ticket,
                        verified_by,
                        (
                            "Verified XClaim payment"
                            if source == "XCLAIM_API"
                            else "Platform settlement operator"
                        ),
                        "Verified insurer funds received and credited: "
                        + body.currency
                        + " "
                        + str(body.approved_amount)
                        + ". Payment reference: "
                        + body.insurer_payment_reference,
                    )
                    bindings = await connection.fetch(
                        """SELECT DISTINCT b.sender_e164 FROM public.whatsapp_bindings b
                        JOIN public.users u ON u.tenant_id=b.tenant_id AND u.id=b.user_id
                        WHERE b.tenant_id=$1 AND b.is_active AND b.notification_opt_in AND u.is_active AND u.role IN ('OWNER','ADMIN') LIMIT 10""",
                        body.tenant_id,
                    )
                    for binding in bindings:
                        await connection.execute(
                            """INSERT INTO public.support_message_outbox
                            (tenant_id,ticket_id,recipient_e164,body,status,message_kind)
                            VALUES($1,$2,$3,$4,'STAGED','INSURANCE_SETTLEMENT') ON CONFLICT DO NOTHING""",
                            body.tenant_id,
                            ticket,
                            binding["sender_e164"],
                            "EasyInvio insurance claim "
                            + str(body.claim_id)
                            + ": verified payout "
                            + body.currency
                            + " "
                            + str(body.approved_amount)
                            + " has been credited to your wallet.",
                        )
        return {
            "settlement_id": str(body.settlement_id),
            "status": "REFUND_APPROVED_AND_CREDITED",
            "credited_amount": str(body.approved_amount),
            "currency": body.currency,
            "duplicate": False,
            "notification": "Staged only for verified opted-in merchant bindings; delivery depends on the configured WhatsApp engine.",
        }


async def book_xcover_policy(
    shipment_id: UUID,
    item_declared_value: Decimal,
    carrier_tracking_code: str,
    *,
    service: ProtectionService,
    tenant_id: UUID,
) -> dict:
    """Internal controller; authenticated caller supplies its tenant-bound service."""
    await calculate_xcover_premium(item_declared_value)
    return await service.book(
        tenant_id, shipment_id, item_declared_value, carrier_tracking_code
    )


def require_claim_role(context):
    if context.role not in {"OWNER", "ADMIN", "DISPATCHER", "ACCOUNTANT"}:
        raise HTTPException(403, "Workspace claim access required")


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


async def insurance_schema_ready(connection):
    return bool(
        await connection.fetchval(
            "SELECT to_regclass('public.insurance_claim_cases') IS NOT NULL AND to_regclass('public.insurance_webhook_receipts') IS NOT NULL"
        )
    )


def validate_evidence(data, content_type):
    """Verify raster images; store as private attachments, never public HTML."""
    from io import BytesIO
    import warnings
    from PIL import Image, UnidentifiedImageError

    if (
        not data
        or len(data) > 5_000_000
        or content_type not in {"image/jpeg", "image/png"}
    ):
        raise HTTPException(
            422, "Each photograph must be a JPEG or PNG no larger than 5 MB"
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if (
                    image.format
                    != {"image/jpeg": "JPEG", "image/png": "PNG"}[content_type]
                ):
                    raise ValueError("File format does not match its content type")
                if image.width * image.height > 20_000_000:
                    raise ValueError("Image exceeds 20 megapixels")
                image.verify()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(
            422, "Photograph is invalid or exceeds the image size limit"
        ) from None


async def insured_shipment(connection, tenant_id, shipment_id):
    row = await connection.fetchrow(
        """SELECT s.id,s.customer_reference,s.tracking_number,s.logistics_metadata,
        t.is_sandbox FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
        WHERE s.tenant_id=$1 AND s.id=$2 AND s.booked_at IS NOT NULL""",
        tenant_id,
        shipment_id,
    )
    if row is None:
        raise HTTPException(404, "Insured shipment not found in this workspace")
    policy = (decoded(row["logistics_metadata"]) or {}).get("insurance") or {}
    if (
        policy.get("provider") != "XCOVER"
        or policy.get("status") != "CONFIRMED"
        or not policy.get("policy_id")
        or not policy.get("quote_id")
    ):
        raise HTTPException(
            409, "This shipment does not have a confirmed XCover policy"
        )
    return row, policy


def build_router(authenticate):
    from backend.customer_checkout import offer_context, quoted_goods
    from backend.admin_portal import authenticate_platform_owner

    router = APIRouter(tags=["XCover protection and claims"])

    def provider(request):
        result = request.app.state.xcover
        reason = result.settings.unavailable_reason()
        if reason:
            raise HTTPException(409, reason)
        return result

    @router.get("/api/v1/shipping/protection-quote")
    async def protection_quote(
        offer_id: UUID, request: Request, context=Depends(authenticate)
    ):
        row, shipment, quoted, rate, reference, required = await offer_context(
            request.app.state.partner_lifecycle, context, offer_id
        )
        items = quoted_goods(shipment)
        if shipment.origin.country_code != "GB":
            return {
                "available": False,
                "insured": False,
                "premium_estimate": None,
                "notice": "The configured protection flow requires a UK-origin shipment.",
                "tax_notice": TAX_NOTICE,
                "provider": "XCOVER",
            }
        if not items or (shipment.goods_currency or shipment.currency) != "GBP":
            return {
                "available": False,
                "insured": False,
                "premium_estimate": None,
                "notice": PROTECTION_NOTICE,
                "tax_notice": TAX_NOTICE,
                "provider": "XCOVER",
            }
        value = sum(
            (
                strict_decimal(item["unit_value"]) * int(item["quantity"])
                for item in items
            ),
            Decimal(0),
        )
        try:
            result = await calculate_xcover_premium(value)
        except HTTPException as exc:
            return {
                "available": False,
                "insured": False,
                "premium_estimate": None,
                "notice": str(exc.detail),
                "tax_notice": TAX_NOTICE,
                "provider": "XCOVER",
            }
        result["provider"] = "XCOVER"
        for internal_field in (
            "wholesale_cost",
            "profit_margin",
            "estimated_baseline_cost",
            "estimated_margin",
            "estimate_notice",
        ):
            result.pop(internal_field, None)
        client = request.app.state.xcover
        result["selection_available"] = client.settings.unavailable_reason() is None
        if result["selection_available"]:
            async with request.app.state.finance.pool.acquire() as connection:
                result["selection_available"] = bool(
                    await connection.fetchval(
                        "SELECT to_regclass('public.insurance_purchases') IS NOT NULL"
                    )
                )
            result["notice"] = (
                "Select protection to obtain the actual XCover premium, taxes and policy terms before confirming. Coverage begins only when XCover confirms the policy."
            )
        return result

    @router.post("/api/v1/shipping/protection-quote")
    async def prepare_protection(
        body: dict, request: Request, context=Depends(authenticate)
    ):
        if set(body) != {"offer_id"}:
            raise HTTPException(422, "Only the prepared offer reference is accepted")
        try:
            offer_id = UUID(str(body["offer_id"]))
        except ValueError:
            raise HTTPException(422, "Valid offer reference required") from None
        if context.role not in {"OWNER", "ADMIN", "DISPATCHER"}:
            raise HTTPException(403, "Booking role required")
        return await request.app.state.protection.prepare(context, offer_id)

    @router.get("/api/v1/shipping/insured-shipments")
    async def insured_list(request: Request, context=Depends(authenticate)):
        from main import validate_tenant_query

        require_claim_role(context)
        validate_tenant_query(request, context.tenant_id)
        client = request.app.state.xcover
        reason = client.settings.unavailable_reason()
        if reason:
            return {"shipments": [], "available": False, "notice": reason}
        async with request.app.state.finance.pool.acquire() as connection:
            if not await insurance_schema_ready(connection):
                return {
                    "shipments": [],
                    "available": False,
                    "notice": "Apply the private insurance-case migration before enabling claim intake.",
                }
            rows = await connection.fetch(
                """SELECT id,customer_reference,tracking_number FROM public.shipments
                WHERE tenant_id=$1 AND booked_at IS NOT NULL
                AND logistics_metadata->'insurance'->>'provider'='XCOVER'
                AND logistics_metadata->'insurance'->>'status'='CONFIRMED'
                AND logistics_metadata->'insurance'->>'policy_id' IS NOT NULL
                ORDER BY booked_at DESC LIMIT 200""",
                context.tenant_id,
            )
        return {
            "shipments": [
                {
                    "id": str(row["id"]),
                    "reference": row["customer_reference"],
                    "tracking_number": row["tracking_number"],
                }
                for row in rows
            ],
            "available": True,
            "headless_claims": bool(
                getattr(request.app.state, "claims", None)
                and request.app.state.claims.client.unavailable_reason() is None
            ),
            "notice": "EasyInvio records your claim case and shows whether it is queued, submitted, under insurer review or credited. Portal filing is used when headless access is not configured.",
        }

    @router.post("/api/v1/shipping/submit-claim")
    async def submit_claim(request: Request, context=Depends(authenticate)):
        require_claim_role(context)
        client = provider(request)
        length = request.headers.get("content-length")
        if length is None or not length.isdigit() or int(length) > 21_000_000:
            raise HTTPException(
                413, "Claim submission must have a known size of at most 21 MB"
            )
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 21_000_000:
                raise HTTPException(413, "Claim submission exceeds 21 MB")

        async def receive_form():
            return {"type": "http.request", "body": bytes(raw), "more_body": False}

        bounded_request = Request(request.scope, receive=receive_form)
        async with bounded_request.form(
            max_files=4, max_fields=5, max_part_size=10_000
        ) as form:
            if set(form.keys()) - {
                "shipment_id",
                "claim_id",
                "reason",
                "notes",
                "photos",
                "incident_at",
            }:
                raise HTTPException(422, "Unexpected claim field")
            try:
                shipment_id, case_id = UUID(str(form.get("shipment_id"))), UUID(
                    str(form.get("claim_id"))
                )
            except ValueError:
                raise HTTPException(
                    422, "Valid shipment and claim references required"
                ) from None
            reason, notes = form.get("reason"), form.get("notes")
            incident_at = form.get("incident_at") or None
            if incident_at:
                try:
                    incident = datetime.fromisoformat(incident_at)
                    if incident.tzinfo is None or incident > datetime.now(timezone.utc):
                        raise ValueError("Incident timestamp invalid")
                    incident_at = incident.astimezone(timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except (ValueError, TypeError):
                    raise HTTPException(
                        422,
                        "Provide a valid incident time with a timezone, no later than now",
                    ) from None
            if (
                reason not in {"PARCEL_LOST", "PARCEL_DAMAGED"}
                or not isinstance(notes, str)
                or not 10 <= len(notes.strip()) <= 2000
            ):
                raise HTTPException(
                    422,
                    "Select loss or damage and describe the incident in 10–2000 characters",
                )
            photos = []
            for image in form.getlist("photos"):
                if not isinstance(image, UploadFile):
                    # Starlette constructs the base UploadFile class.
                    from starlette.datastructures import (
                        UploadFile as StarletteUploadFile,
                    )

                    if not isinstance(image, StarletteUploadFile):
                        raise HTTPException(422, "Photograph upload required")
                data = await image.read(5_000_001)
                await asyncio.to_thread(validate_evidence, data, image.content_type)
                photos.append((data, image.content_type))
            if len(photos) > 4:
                raise HTTPException(422, "At most four photographs are allowed")
        pool = request.app.state.finance.pool
        async with pool.acquire() as connection:
            if not await insurance_schema_ready(connection):
                raise HTTPException(
                    503, "The insurance-case migration has not been applied"
                )
            shipment, policy = await insured_shipment(
                connection, context.tenant_id, shipment_id
            )
        if bool(shipment["is_sandbox"]) != (client.settings.environment == "TEST"):
            raise HTTPException(403, "Policy environment does not match this workspace")
        try:
            booking = await client.get_booking(policy["policy_id"])
            client.confirmed_booking(
                booking, policy["policy_id"], policy["quote_id"], shipment_id
            )
        except (XCoverRejected, XCoverUncertain, ValueError):
            raise HTTPException(
                409, "XCover coverage could not be verified; no claim was submitted"
            ) from None
        portal = claims_portal_url(booking.get("fnol_link"))
        claims = getattr(request.app.state, "claims", None)
        headless = None
        if claims and claims.client.unavailable_reason() is None:
            try:
                headless = await claims.prepare_payload(
                    shipment, policy, reason, notes.strip(), incident_at
                )
            except (XCoverRejected, XCoverUncertain, HTTPException):
                if not portal:
                    raise HTTPException(
                        409,
                        "The insurer claim form could not be prepared; contact EasyInvio support",
                    ) from None
        if not portal and not headless:
            raise HTTPException(
                409, "XCover has not supplied a trusted claims portal for this policy"
            )
        if (
            headless
            and any(field["required"] for field in headless["file_fields"])
            and not photos
        ):
            raise HTTPException(
                422, "This insurer claim form requires evidence photographs"
            )
        digest = hashlib.sha256(
            decimal_json(
                {
                    "shipment": str(shipment_id),
                    "policy": policy["policy_id"],
                    "reason": reason,
                    "notes": notes.strip(),
                    "incident_at": incident_at,
                    "photos": [hashlib.sha256(data).hexdigest() for data, _ in photos],
                }
            ).encode()
        ).hexdigest()
        current_case_state = "SUBMISSION_PENDING" if headless else "CLAIM_INGESTED"
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                    "claim:" + str(case_id),
                )
                existing = await connection.fetchrow(
                    "SELECT payload_sha256,state FROM public.insurance_claim_cases WHERE tenant_id=$1 AND id=$2",
                    context.tenant_id,
                    case_id,
                )
                if existing:
                    if existing["payload_sha256"] != digest:
                        from backend.conversational_claims import complete_conversational_claim
                        completed = await complete_conversational_claim(connection, context, case_id=case_id,
                            shipment_id=shipment_id, policy_id=policy['policy_id'], reason=reason, notes=notes.strip(),
                            old_digest=existing['payload_sha256'], digest=digest, state=current_case_state,
                            submission_payload=headless or {}, photos=photos)
                        if not completed:
                            raise HTTPException(409, "This claim reference was already used for different evidence")
                    else:
                        current_case_state = existing["state"]
                else:
                    # Recheck locally under the write transaction in case of cancellation.
                    await insured_shipment(connection, context.tenant_id, shipment_id)
                    actor = await connection.fetchval(
                        "SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND auth_user_id=$2 AND is_active",
                        context.tenant_id,
                        context.user_id,
                    )
                    if actor is None:
                        raise HTTPException(
                            403, "Verified active workspace membership required"
                        )
                    inserted = await connection.fetchval(
                        """INSERT INTO public.insurance_claim_cases
                        (id,tenant_id,shipment_id,policy_id,reason,notes,created_by,payload_sha256,state,submission_payload)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb) ON CONFLICT DO NOTHING RETURNING id""",
                        case_id,
                        context.tenant_id,
                        shipment_id,
                        policy["policy_id"],
                        reason,
                        notes.strip(),
                        actor,
                        digest,
                        current_case_state,
                        decimal_json(headless or {}),
                    )
                    if inserted is None:
                        raise HTTPException(
                            409,
                            "Claim reference is already in use; refresh your claim form",
                        )
                    ticket_id = uuid4()
                    await connection.execute(
                        """INSERT INTO public.support_tickets
                        (id,tenant_id,shipment_id,insurance_claim_id,status,ai_summary,ai_method,prompt_version)
                        VALUES($1,$2,$3,$4,'OPEN',$5,'CUSTOMER_CLAIM','xcover-case-v1')""",
                        ticket_id,
                        context.tenant_id,
                        shipment_id,
                        case_id,
                        (
                            "Insurer claim queued for XClaim submission. "
                            if headless
                            else "Insurance support case received. Customer must file through the XCover policy portal. "
                        )
                        + notes.strip(),
                    )
                    await connection.execute(
                        """INSERT INTO public.support_ticket_activity
                        (tenant_id,ticket_id,actor_auth_user_id,actor_name,activity_type,note)
                        VALUES($1,$2,$3,'Workspace claimant','INTERNAL_NOTE',$4)""",
                        context.tenant_id,
                        ticket_id,
                        actor,
                        notes.strip(),
                    )
                    for data, kind in photos:
                        await connection.execute(
                            """INSERT INTO public.insurance_claim_evidence
                            (tenant_id,case_id,content_type,content_sha256,content)
                            VALUES($1,$2,$3,$4,$5)""",
                            context.tenant_id,
                            case_id,
                            kind,
                            hashlib.sha256(data).hexdigest(),
                            data,
                        )
        credited = current_case_state == "REFUND_APPROVED_AND_CREDITED"
        return {
            "claim_id": str(case_id),
            "status": current_case_state,
            "insurer_submission_confirmed": credited,
            "claims_portal_url": None if headless else portal,
            "timeline": [
                {"status": "CLAIM_INGESTED", "complete": True},
                {"status": "UNDER_INSURER_REVIEW", "complete": credited},
                {"status": "PAYMENT_CONFIRMED", "complete": credited},
            ],
            "notice": (
                "Verified insurer payment was credited to the wallet."
                if credited
                else (
                    "Claim queued for insurer submission. Submission, review and wallet credit are not yet confirmed."
                    if headless
                    else "Support case saved to EasyInvio. Complete your insurer claim at XCover. No approval or wallet credit has occurred."
                )
            ),
        }

    @router.get("/api/v1/shipping/claims/{case_id}")
    async def claim_status(
        case_id: UUID, request: Request, context=Depends(authenticate)
    ):
        require_claim_role(context)
        async with request.app.state.finance.pool.acquire() as connection:
            if not await insurance_schema_ready(connection):
                raise HTTPException(503, "Insurance case storage unavailable")
            row = await connection.fetchrow(
                """SELECT c.id,c.shipment_id,c.reason,c.notes,c.created_at,c.state,c.upstream_claim_id,c.insurer_status,
                t.status AS support_status,t.review_started_at,
                (SELECT count(*) FROM public.insurance_claim_evidence e WHERE e.tenant_id=c.tenant_id AND e.case_id=c.id) AS photograph_count
                FROM public.insurance_claim_cases c LEFT JOIN public.support_tickets t
                ON t.tenant_id=c.tenant_id AND t.insurance_claim_id=c.id
                WHERE c.tenant_id=$1 AND c.id=$2""",
                context.tenant_id,
                case_id,
            )
        if row is None:
            raise HTTPException(404, "Claim case not found in this workspace")
        settled = row["state"] == "REFUND_APPROVED_AND_CREDITED"
        return {
            "claim_id": str(row["id"]),
            "shipment_id": str(row["shipment_id"]),
            "status": row["state"],
            "support_status": row["support_status"],
            "reason": row["reason"],
            "notes": row["notes"],
            "photograph_count": row["photograph_count"],
            "received_at": row["created_at"].isoformat(),
            "insurer_submission_confirmed": settled
            or row["upstream_claim_id"] is not None,
            "wallet_credit": settled,
            "insurer_status": row["insurer_status"],
            "notice": (
                "Insurer payment was reconciled and credited to the wallet."
                if settled
                else (
                    "Insurer status: "
                    + row["insurer_status"]
                    + ". Wallet credit is not confirmed."
                    if row["insurer_status"]
                    else (
                        "Claim queued; insurer submission is not yet confirmed."
                        if row["state"]
                        in {"SUBMISSION_PENDING", "SUBMISSION_SUBMITTED"}
                        else "This is EasyInvio support activity. Insurer review and payment must be confirmed by XCover."
                    )
                )
            ),
        }

    @router.get("/api/v1/shipping/claims/{case_id}/evidence/{evidence_id}")
    async def evidence_download(
        case_id: UUID,
        evidence_id: UUID,
        request: Request,
        context=Depends(authenticate),
    ):
        require_claim_role(context)
        async with request.app.state.finance.pool.acquire() as connection:
            if not await insurance_schema_ready(connection):
                raise HTTPException(503, "Insurance evidence storage unavailable")
            row = await connection.fetchrow(
                """SELECT content FROM public.insurance_claim_evidence
                WHERE tenant_id=$1 AND case_id=$2 AND id=$3""",
                context.tenant_id,
                case_id,
                evidence_id,
            )
        if row is None:
            raise HTTPException(404, "Evidence not found in this workspace")
        return Response(
            bytes(row["content"]),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="claim-photograph.bin"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @router.post("/api/v1/shipping/insurance-updates")
    async def insurance_updates(request: Request):
        client = request.app.state.xcover
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 100_000:
                raise HTTPException(413, "Insurance update is too large")
        if request.headers.get("xclaim-signature"):
            claims = getattr(request.app.state, "claims", None)
            if claims is None:
                raise HTTPException(503, "Native XClaim receiver is unavailable")
            try:
                return await claims.webhook(
                    bytes(raw), request.headers["xclaim-signature"]
                )
            except (XCoverRejected, XCoverUncertain):
                raise HTTPException(
                    503,
                    "Authoritative insurer claim could not be retrieved; no unverified wallet credit",
                ) from None
        verify_xcover_webhook(request.headers, client.settings)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid insurance update JSON") from None
        if not isinstance(body, dict) or body.get("event") not in {
            "BOOKING_CREATED",
            "BOOKING_UPDATED",
            "BOOKING_CANCELLED",
        }:
            raise HTTPException(
                422,
                "Only documented XCover booking events are supported; claim approval cannot authorize wallet credit",
            )
        payload = body.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
            raise HTTPException(422, "XCover policy reference required")
        policy_id = payload["id"]
        pool = request.app.state.finance.pool
        async with pool.acquire() as connection:
            if not await insurance_schema_ready(connection):
                raise HTTPException(503, "Insurance webhook storage unavailable")
            rows = await connection.fetch(
                """SELECT s.id,s.tenant_id,s.logistics_metadata,t.is_sandbox
                FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
                WHERE s.logistics_metadata->'insurance'->>'provider'='XCOVER'
                AND s.logistics_metadata->'insurance'->>'policy_id'=$1 LIMIT 2""",
                policy_id,
            )
        if len(rows) != 1:
            raise HTTPException(
                404, "Policy mapping is absent or ambiguous; reconciliation required"
            )
        shipment = rows[0]
        if bool(shipment["is_sandbox"]) != (client.settings.environment == "TEST"):
            raise HTTPException(403, "Insurance environment mismatch")
        try:
            booking = await client.get_booking(policy_id)
        except (XCoverRejected, XCoverUncertain, ValueError):
            raise HTTPException(
                503, "Authoritative XCover booking could not be retrieved"
            ) from None
        policy = decoded(shipment["logistics_metadata"])["insurance"]
        if (
            booking.get("id") != policy_id
            or booking.get("partner_transaction_id") != str(shipment["id"])
            or booking.get("currency") != "GBP"
            or booking.get("status") not in {"CONFIRMED", "CANCELLED"}
            or not any(
                isinstance(item, dict) and item.get("id") == policy.get("quote_id")
                for item in booking.get("quotes", [])
            )
        ):
            raise HTTPException(
                409, "Authoritative policy does not match this transaction"
            )
        digest = hashlib.sha256(raw).hexdigest()
        async with pool.acquire() as connection:
            async with connection.transaction():
                receipt = await connection.fetchval(
                    """INSERT INTO public.insurance_webhook_receipts
                    (tenant_id,shipment_id,policy_id,body_sha256,event,verified_status)
                    VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(tenant_id,body_sha256) DO NOTHING RETURNING id""",
                    shipment["tenant_id"],
                    shipment["id"],
                    policy_id,
                    digest,
                    body["event"],
                    booking["status"],
                )
                if receipt:
                    await connection.execute(
                        """UPDATE public.shipments SET logistics_metadata=jsonb_set(
                        logistics_metadata,'{insurance,status}',to_jsonb($3::text))
                        WHERE tenant_id=$1 AND id=$2 AND logistics_metadata->'insurance'->>'policy_id'=$4""",
                        shipment["tenant_id"],
                        shipment["id"],
                        booking["status"],
                        policy_id,
                    )
        return {
            "accepted": True,
            "duplicate": receipt is None,
            "verified_policy_status": booking["status"],
            "wallet_credit": False,
        }

    @router.post("/api/v1/admin/insurance/settlements")
    async def platform_settlement(
        body: PlatformSettlement,
        request: Request,
        owner=Depends(authenticate_platform_owner),
    ):
        """Record received master-account funds; never treat approval as payment.

        This operator reconciliation path is available until XCover supplies its
        partner-specific claim and payment verification contract. The operator's
        identity and bank/insurer payment reference form the audit trail.
        """
        return await request.app.state.protection.credit_settlement(body, owner.user_id)

    return router
