"""EasyInvio.com: combined rating, financial controls and WhatsApp service.

Python 3.12 or newer. Install dependencies:
    python -m pip install fastapi 'uvicorn[standard]' httpx pydantic \
        pydantic-settings 'PyJWT[crypto]' cryptography asyncpg 'stripe>=13,<15' \
        'twilio>=9,<10' 'pycountry>=24.6,<25'

Run local checks without credentials:
    python main.py --self-test

Start after configuring environment variables and applying Steps 2, 4 and 5 SQL:
    python main.py

Required environment variables (or entries in a local .env file):
    SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SERVICE_ROLE_KEY
    DATABASE_URL, CREDENTIAL_KEYS, REGIONAL_ALLOWED_ORIGINS
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
    CHECKOUT_SUCCESS_URL, CHECKOUT_CANCEL_URL
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER
    TWILIO_WEBHOOK_URL, BOOKING_PAGE_URL, QUOTE_LINK_SECRET

CREDENTIAL_KEYS is a JSON object mapping key IDs to Fernet keys.
REGIONAL_ALLOWED_ORIGINS is a JSON array of approved HTTPS API origins.
Optional: JWT_ALGORITHM=ES256, STRIPE_LIVEMODE=false,
PROVIDER_ENVIRONMENT=TEST, DATABASE_CA_FILE, PORT=8000.

This module does not purchase carrier labels or implement a booking frontend.
wallet_risk_interceptor, mark_submitted and finish_booking are the hooks for
the subsequent label-purchase component. RegionalStrategy defines its actual
wire contract; use an adapter matching the selected regional provider's API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import ssl
import sys
from pathlib import Path
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, localcontext
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import UUID, uuid4

import asyncpg
import httpx
import jwt
import pycountry
import stripe
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import (
    BaseModel, ConfigDict, Field, SecretStr, ValidationError,
    field_validator, model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from backend.admin_portal import (
    AdminService, calibrated_pricing_scope, configure_pricing_pool, borrowed_pricing_connection,
    get_client_calibrated_rate, router as admin_router,
)
from backend.sendcloud_adapter import SendcloudMethod, quote_sendcloud
from backend.sandbox_hooks import (
    SandboxBillingService, authenticated_twilio_form, require_prepaid_funds,
    build_router as sandbox_router,
)
from backend.ecommerce_sync import (
    EcommerceService, configure_ecommerce_service, push_tracking_to_store,
    tracking_worker, build_router as ecommerce_router,
)
from backend.hubspot_crm import (
    HubSpotSettings, HubSpotClient, HubSpotService, configure_hubspot_service,
    build_router as hubspot_router,
)
from backend.database_tls import database_tls_context
from backend.tracking_and_support import TrackingSettings, TrackingSupportService, build_router as tracking_router
from backend.support_delivery import DeliverySettings, SupportDelivery, build_router as support_delivery_router
from backend.dashboard_portal import build_router as dashboard_router
from backend.automation_freight_engine import AutomationService, Cargo, calculate_cargo_charge, build_router as automation_router
from backend.dispatch_workspace import build_router as dispatch_workspace_router


logger = logging.getLogger("veloce")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
ZERO = Decimal("0")
DEFAULT_MARKUP_PERCENT = Decimal("20")
KG_PER_OUNCE = Decimal("0.028349523125")
CM_PER_INCH = Decimal("2.54")
CURRENCIES = {"GBP", "EUR", "USD"}
DISPATCH_ROLES = {"OWNER", "ADMIN", "DISPATCHER"}
FINANCE_ROLES = {"OWNER", "ADMIN", "ACCOUNTANT"}
ALL_ROLES = DISPATCH_ROLES | FINANCE_ROLES
MAX_RESPONSE_BYTES = 2_000_000
MAX_WEBHOOK_BYTES = 1_000_000
MAX_FORM_BYTES = 32_768
PHONE_PATTERN = re.compile(r"^whatsapp:(\+[1-9][0-9]{7,14})$")
SID_PATTERN = re.compile(r"^SM[0-9a-fA-F]{32}$")
QUOTE_PATTERN = re.compile(
    r"^\s*quote\s+(?P<weight>[0-9]{1,4}(?:\.[0-9]{1,3})?)\s*kg\s+"
    r"from\s+(?P<origin>[a-z]{2,3})\s+to\s+(?P<destination>[a-z]{2,3})"
    r"(?:\s+route\s+(?P<route>[a-z0-9_-]{1,24}))?\s*$",
    re.IGNORECASE | re.ASCII,
)


class Settings(BaseSettings):
    sendcloud_methods: dict[UUID, list[SendcloudMethod]] = Field(default_factory=dict)
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    supabase_url: str
    supabase_publishable_key: SecretStr
    supabase_service_role_key: SecretStr
    database_url: SecretStr
    database_ca_file: str | None = None
    database_tls_strict: bool = True
    automation_purchase_enabled: bool = False
    freight_kg_per_m3: Decimal = Field(default=Decimal('333'),gt=0,le=10000)
    freight_kg_per_loading_metre: Decimal = Field(default=Decimal('1750'),gt=0,le=30000)
    freight_deck_width_m: Decimal = Field(default=Decimal('2.4'),gt=0,le=5)
    jwt_algorithm: Literal["ES256", "RS256"] = "ES256"
    jwt_audience: str = "authenticated"
    credential_keys: dict[str, SecretStr] = Field(default_factory=dict)
    regional_allowed_origins: list[str] = Field(min_length=1)
    provider_environment: Literal["TEST", "LIVE"] = "TEST"
    provider_deadline_seconds: int = Field(default=35, ge=5, le=120)
    max_parallel_provider_requests: int = Field(default=20, ge=1, le=100)
    max_accounts_per_tenant: int = Field(default=8, ge=2, le=30)
    quote_ttl_seconds: int = Field(default=300, ge=30, le=900)
    db_pool_max_size: int = Field(default=10, ge=2, le=50)
    platform_admin_user_ids: list[UUID] = Field(default_factory=list)
    database_environment: Literal["SANDBOX", "LIVE"] = "LIVE"
    sandbox_hooks_enabled: bool = False

    stripe_enabled: bool = False
    stripe_secret_key: SecretStr = SecretStr("")
    stripe_webhook_secret: SecretStr = SecretStr("")
    stripe_livemode: bool = False
    checkout_success_url: str = ""
    checkout_cancel_url: str = ""

    twilio_enabled: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: SecretStr = SecretStr("")
    twilio_whatsapp_number: str = ""
    twilio_whatsapp_sandbox_enabled: bool = False
    twilio_webhook_url: str = ""
    booking_page_url: str = ""
    quote_link_secret: SecretStr = SecretStr("")
    whatsapp_deadline_seconds: int = Field(default=12, ge=5, le=12)
    whatsapp_provider_seconds: int = Field(default=7, ge=1, le=8)

    @field_validator("twilio_whatsapp_number", mode="before")
    @classmethod
    def whatsapp_e164(cls, value):
        return value.removeprefix("whatsapp:") if isinstance(value, str) else value

    @model_validator(mode="after")
    def sandbox_modes(self):
        if self.stripe_enabled and (not self.stripe_secret_key.get_secret_value().startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_"))
                                   or not self.stripe_webhook_secret.get_secret_value().startswith("whsec_")
                                   or not self.checkout_success_url or not self.checkout_cancel_url):
            raise ValueError("Enabled Stripe requires real credentials and checkout URLs")
        if self.twilio_enabled and (not re.fullmatch(r"AC[0-9a-fA-F]{32}", self.twilio_account_sid)
                                   or not re.fullmatch(r"\+[1-9][0-9]{7,14}", self.twilio_whatsapp_number)
                                   or not self.twilio_auth_token.get_secret_value()
                                   or not self.twilio_webhook_url or not self.booking_page_url
                                   or len(self.quote_link_secret.get_secret_value().encode()) < 32):
            raise ValueError("Enabled Twilio requires valid account, webhook and link credentials")
        if self.sandbox_hooks_enabled or self.twilio_whatsapp_sandbox_enabled:
            if self.database_environment != "SANDBOX" or self.provider_environment != "TEST":
                raise ValueError("Sandbox hooks require DATABASE_ENVIRONMENT=SANDBOX and PROVIDER_ENVIRONMENT=TEST")
        if self.sandbox_hooks_enabled and (self.stripe_livemode or not self.stripe_secret_key.get_secret_value().startswith("sk_test_")):
            raise ValueError("Sandbox billing requires an sk_test_ key and STRIPE_LIVEMODE=false")
        if self.twilio_whatsapp_sandbox_enabled and self.twilio_whatsapp_number != "+14155238886":
            raise ValueError("Twilio WhatsApp Sandbox requires +14155238886")
        if self.stripe_livemode and any(urlsplit(u).scheme=='http' for u in [self.checkout_success_url,self.checkout_cancel_url]):
            raise ValueError('Live checkout requires HTTPS return URLs')
        return self

    @field_validator("supabase_url")
    @classmethod
    def supabase_origin(cls, value: str) -> str:
        value = value.rstrip("/")
        parts = urlsplit(value)
        if (
            parts.scheme != "https" or not parts.hostname or parts.path
            or parts.username or parts.password or parts.query or parts.fragment
        ):
            raise ValueError("SUPABASE_URL must be an HTTPS origin")
        return value

    @field_validator("regional_allowed_origins")
    @classmethod
    def regional_origins(cls, values: list[str]) -> list[str]:
        result = []
        for value in values:
            value = value.rstrip("/")
            parts = urlsplit(value)
            if (
                parts.scheme != "https" or not parts.hostname or parts.path
                or parts.username or parts.password or parts.query or parts.fragment
            ):
                raise ValueError("Regional origins must be fixed HTTPS origins")
            result.append(value)
        return result

    @field_validator("checkout_success_url", "checkout_cancel_url")
    @classmethod
    def checkout_return_url(cls, value: str) -> str:
        if not value:
            return value
        parts = urlsplit(value)
        local = parts.scheme == 'http' and parts.hostname in {'localhost','127.0.0.1','::1'}
        if (parts.scheme != 'https' and not local) or not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError('Use a fixed HTTPS checkout return URL, or loopback HTTP for local testing')
        return value

    @field_validator("twilio_webhook_url", "booking_page_url")
    @classmethod
    def fixed_https_url(cls, value: str) -> str:
        if not value:
            return value
        parts = urlsplit(value)
        if (
            parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment
        ):
            raise ValueError("Configure a fixed HTTPS URL without query/fragment")
        return value

    @field_validator("credential_keys")
    @classmethod
    def encryption_keys(cls, values: dict[str, SecretStr]) -> dict[str, SecretStr]:
        for key in values.values():
            Fernet(key.get_secret_value().encode("ascii"))
        return values

    @field_validator("quote_link_secret")
    @classmethod
    def link_secret(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value() and len(value.get_secret_value().encode()) < 32:
            raise ValueError("QUOTE_LINK_SECRET must have at least 32 bytes")
        return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def decimal_input(value: Any) -> Any:
    if isinstance(value, (float, bool)):
        raise ValueError("Send decimals as strings, not floating-point JSON numbers")
    return value


Money = Annotated[Decimal, Field(ge=0, lt=Decimal("1000000000000"), decimal_places=2)]
Currency = Literal["GBP", "EUR", "USD"]


class Dimensions(StrictModel):
    length_cm: Decimal = Field(gt=0, le=1500, decimal_places=2)
    width_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)
    height_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)

    @field_validator("length_cm", "width_cm", "height_cm", mode="before")
    @classmethod
    def validate_input(cls, value: Any) -> Any:
        return decimal_input(value)


class Address(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str = Field(min_length=1, max_length=30)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    phone: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{7,14}$")
    email: str | None = Field(
        default=None, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    )

    @field_validator("name", "company", "line1", "line2", "city", "state", "postal_code")
    @classmethod
    def trim(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Address fields cannot be blank")
        return value

    @field_validator("country_code")
    @classmethod
    def country(cls, value: str) -> str:
        if pycountry.countries.get(alpha_2=value) is None:
            raise ValueError("Unknown ISO country code")
        return value


class RatingRequest(StrictModel):
    origin: Address
    destination: Address
    dimensions: list[Dimensions] = Field(default_factory=list, max_length=1)
    weights_kg: list[
        Annotated[Decimal, Field(gt=0, le=30000, decimal_places=3)]
    ] = Field(min_length=1, max_length=1)
    currency: Currency = "GBP"
    cargo_type: Literal['LETTER','PARCEL','PALLET','OVERLAND_FREIGHT'] = 'PARCEL'
    stackable: bool = True
    customs_document: dict | None = None

    @model_validator(mode='before')
    @classmethod
    def letter_dimensions(cls,value):
        if isinstance(value,dict) and value.get('cargo_type')=='LETTER':
            return {**value,'dimensions':[]}
        return value

    @field_validator("weights_kg", mode="before")
    @classmethod
    def weights(cls, value: Any) -> Any:
        if isinstance(value, list):
            for weight in value:
                decimal_input(weight)
        return value

    @model_validator(mode="after")
    def matching_arrays(self) -> RatingRequest:
        if self.cargo_type=='LETTER':
            if self.weights_kg[0]>=Decimal('.5'):
                raise ValueError('LETTER must weigh below 0.5 kg')
            self.dimensions=[]
            return self
        if len(self.dimensions) != len(self.weights_kg):
            raise ValueError("Each parcel requires dimensions and a weight")
        return self


class ProviderFees(StrictModel):
    base_cost: Money
    fuel_surcharge: Money
    residential_fee: Money
    remote_area_fee: Money

    @field_validator("base_cost", "fuel_surcharge", "residential_fee", "remote_area_fee", mode="before")
    @classmethod
    def decimal_values(cls, value):
        return decimal_input(value)


class WholesaleRate(StrictModel):
    provider: Literal["EASYPOST", "REGIONAL"]
    account_id: UUID
    upstream_shipment_id: str = Field(min_length=1, max_length=200)
    upstream_rate_id: str = Field(min_length=1, max_length=200)
    carrier_code: str = Field(min_length=1, max_length=100)
    service_code: str = Field(min_length=1, max_length=100)
    currency: Currency
    wholesale_cost: Money
    fee_components: ProviderFees | None = None
    delivery_days: int | None = Field(default=None, ge=0, le=365)

    @field_validator("wholesale_cost", mode="before")
    @classmethod
    def cost_input(cls, value: Any) -> Any:
        return decimal_input(value)

    @model_validator(mode="after")
    def reconcile_fees(self):
        if self.fee_components:
            total = sum(self.fee_components.model_dump().values(), ZERO)
            if total != self.wholesale_cost:
                raise ValueError("Provider fee split must equal quoted carrier total")
        return self

    @field_validator("carrier_code", "service_code")
    @classmethod
    def codes(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("Carrier/service codes cannot be empty")
        return value


class ClientRate(StrictModel):
    provider: Literal["EASYPOST", "REGIONAL"]
    account_id: UUID
    upstream_shipment_id: str
    upstream_rate_id: str
    carrier_code: str
    service_code: str
    currency: Currency
    client_price_ex_tax: Money
    delivery_days: int | None
    fee_breakdown: dict[str, Any] = Field(default_factory=dict)


class ProviderIssue(StrictModel):
    provider: Literal["EASYPOST", "REGIONAL"]
    account_id: UUID
    code: str
    retryable: bool


class RatingResponse(StrictModel):
    request_id: UUID
    currency: Currency
    quoted_at: datetime
    expires_at: datetime
    partial: bool
    weight: dict[str, str] = Field(default_factory=dict)
    rates: list[ClientRate]
    issues: list[ProviderIssue]


class MarginRule(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    id: UUID
    tenant_id: UUID
    carrier_account_id: UUID | None = None
    carrier_code: str | None = None
    service_code: str | None = None
    origin_country: str | None = None
    destination_country: str | None = None
    currency: Currency
    min_weight_kg: Decimal | None = None
    max_weight_kg: Decimal | None = None
    min_wholesale_cost: Decimal | None = None
    max_wholesale_cost: Decimal | None = None
    markup_type: Literal["FIXED", "PERCENTAGE"]
    markup_value: Decimal = Field(ge=0, lt=Decimal("100000000000000"))
    minimum_markup: Decimal = Field(default=ZERO, ge=0)
    maximum_markup: Decimal | None = Field(default=None, ge=0)
    priority: int = Field(ge=0)
    is_active: bool
    valid_from: datetime
    valid_until: datetime | None = None
    created_at: datetime

    @field_validator("markup_type", mode="before")
    @classmethod
    def flat_type(cls, value: Any) -> Any:
        return "FIXED" if value == "FLAT_RATE" else value

    @field_validator("carrier_code", "service_code")
    @classmethod
    def codes(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @model_validator(mode="after")
    def bounds(self) -> MarginRule:
        for low, high in (
            (self.min_weight_kg, self.max_weight_kg),
            (self.min_wholesale_cost, self.max_wholesale_cost),
        ):
            if low is not None and low < 0:
                raise ValueError("Minimum cannot be negative")
            if high is not None and high <= 0:
                raise ValueError("Maximum must be positive")
            if low is not None and high is not None and high <= low:
                raise ValueError("Maximum must exceed minimum")
        if self.maximum_markup is not None and self.maximum_markup < self.minimum_markup:
            raise ValueError("Invalid markup bounds")
        for value in (self.valid_from, self.valid_until, self.created_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("Timestamps must include timezone")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("Rule expiry must be after its start")
        return self


class TopupRequest(StrictModel):
    request_id: UUID
    amount: Decimal = Field(ge=1, le=10000, decimal_places=2)

    @field_validator("amount", mode="before")
    @classmethod
    def amount_input(cls, value: Any) -> Any:
        return decimal_input(value)


class TopupResponse(StrictModel):
    topup_id: UUID
    checkout_session_id: str
    checkout_url: str


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    user_id: UUID
    role: str
    bearer_token: str


@dataclass(frozen=True)
class CarrierAccount:
    id: UUID
    tenant_id: UUID
    provider: Literal["EASYPOST", "REGIONAL"]
    base_url: str
    upstream_account_id: str | None
    timeout_seconds: int
    api_key: str


@dataclass(frozen=True)
class PriceResult:
    wholesale_cost: Decimal
    markup: Decimal
    client_price: Decimal
    rule_id: UUID | None


@dataclass(frozen=True)
class BookingPermit:
    tenant_id: UUID
    shipment_id: UUID
    reservation_id: UUID
    amount: Decimal
    currency: str
    billing_plan: str


@dataclass(frozen=True)
class ParsedQuote:
    weight_kg: Decimal
    origin_country: str
    destination_country: str
    route_code: str | None


def parse_json(raw: bytes) -> Any:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Response exceeds size limit")

    def reject_constant(value: str) -> None:
        raise ValueError("Non-finite JSON number")

    return json.loads(raw, parse_float=Decimal, parse_constant=reject_constant)


async def streamed_json(response: httpx.Response) -> Any:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Response exceeds size limit")
    return parse_json(bytes(body))


def money(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_minor_units(amount: Decimal, currency: str) -> int:
    if currency not in CURRENCIES or not amount.is_finite() or amount < ZERO:
        raise ValueError("Invalid currency/amount")
    with localcontext() as context:
        context.prec = 50
        exact = amount * HUNDRED
        if exact != exact.to_integral_value():
            raise ValueError("Amount has more than two decimal places")
        return int(exact)


def from_minor_units(amount: Any, currency: str) -> Decimal:
    if currency not in CURRENCIES or type(amount) is not int:
        raise ValueError("Invalid currency/minor-unit integer")
    if not 0 < amount <= 1_000_000:
        raise ValueError("Top-up amount outside allowed range")
    return (Decimal(amount) / HUNDRED).quantize(CENT)


def encrypt_carrier_credentials(
    tenant_id: UUID, account_id: UUID, api_key: str, encryption_key: str
) -> str:
    if not api_key.strip():
        raise ValueError("API key cannot be blank")
    envelope = json.dumps({
        "tenant_id": str(tenant_id), "account_id": str(account_id), "api_key": api_key,
    }, separators=(",", ":")).encode()
    encrypted = Fernet(encryption_key.encode("ascii")).encrypt(envelope)
    return "\\x" + encrypted.hex()


class RuleRepository(Protocol):
    async def load(self, context: TenantContext, currency: str) -> list[MarginRule]:
        ...


class MemoryRuleRepository:
    """Decimal-based test fixtures. Never used by live HTTP endpoints."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.rules = [MarginRule.model_validate(row) for row in rows]

    async def load(self, context: TenantContext, currency: str) -> list[MarginRule]:
        return [rule for rule in self.rules if (
            rule.tenant_id == context.tenant_id
            and rule.currency == currency and rule.is_active
        )]


class SupabaseRepository:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client, self.settings = client, settings

    async def select(
        self,
        table: Literal["users", "tenants", "margin_rules", "carrier_accounts"],
        params: dict[str, str],
        context: TenantContext,
        backend: bool = False,
    ) -> list[dict[str, Any]]:
        if backend:
            key = self.settings.supabase_service_role_key.get_secret_value()
            token = key
        else:
            key = self.settings.supabase_publishable_key.get_secret_value()
            token = context.bearer_token
            if not token:
                raise RuntimeError("A real Supabase token is required for RLS HTTP queries")
        try:
            async with self.client.stream(
                "GET", f"{self.settings.supabase_url}/rest/v1/{table}",
                params=params,
                headers={"apikey": key, **({} if backend and key.startswith("sb_secret_") else {"Authorization": f"Bearer {token}"})},
                timeout=httpx.Timeout(10, connect=5),
            ) as response:
                if response.status_code >= 400:
                    raise HTTPException(503, "Database access unavailable")
                result = await streamed_json(response)
            if not isinstance(result, list):
                raise ValueError("Expected database row array")
            return result
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "Database access unavailable") from None

    async def load(self, context: TenantContext, currency: str) -> list[MarginRule]:
        # Step 2 permits accountants/admins to see margins; dispatchers
        # cannot read them directly. Privileged queries remain tenant-scoped.
        rows = await self.select("margin_rules", {
            "select": "*", "tenant_id": f"eq.{context.tenant_id}",
            "currency": f"eq.{currency}", "is_active": "eq.true",
            "order": "priority.asc,created_at.asc,id.asc", "limit": "1000",
        }, context, backend=True)
        if len(rows) >= 1000:
            raise HTTPException(503, "Pricing rule capacity exceeded")
        rules = [MarginRule.model_validate(row) for row in rows]
        if any(rule.tenant_id != context.tenant_id for rule in rules):
            raise HTTPException(503, "Pricing configuration unavailable")
        return rules

    async def accounts(self, context: TenantContext) -> list[CarrierAccount]:
        rows = await self.select("carrier_accounts", {
            "select": "id,tenant_id,aggregator,api_base_url,upstream_account_id,"
                      "timeout_seconds,credentials_ciphertext,credential_key_id",
            "tenant_id": f"eq.{context.tenant_id}",
            "environment": f"eq.{self.settings.provider_environment}",
            "is_active": "eq.true", "order": "priority.asc,id.asc",
            "limit": str(self.settings.max_accounts_per_tenant + 1),
        }, context, backend=True)
        if len(rows) > self.settings.max_accounts_per_tenant:
            raise HTTPException(503, "Carrier account capacity exceeded")
        result = []
        try:
            for row in rows:
                account_id, tenant_id = UUID(row["id"]), UUID(row["tenant_id"])
                if tenant_id != context.tenant_id:
                    raise ValueError("Tenant mismatch")
                provider, endpoint = row["aggregator"], row["api_base_url"].rstrip("/")
                if provider == "EASYPOST":
                    if endpoint != "https://api.easypost.com/v2":
                        raise ValueError("Invalid EasyPost URL")
                elif provider == "REGIONAL":
                    parts = urlsplit(endpoint)
                    if (
                        parts.scheme != "https" or parts.username or parts.password
                        or parts.query or parts.fragment
                        or f"{parts.scheme}://{parts.netloc}"
                        not in self.settings.regional_allowed_origins
                    ):
                        raise ValueError("Regional endpoint is not approved")
                else:
                    raise ValueError("Unknown aggregator")
                encrypted = row["credentials_ciphertext"]
                if not isinstance(encrypted, str) or not encrypted.startswith("\\x"):
                    raise ValueError("Invalid bytea representation")
                key = self.settings.credential_keys[row["credential_key_id"]]
                envelope = parse_json(Fernet(key.get_secret_value().encode()).decrypt(
                    bytes.fromhex(encrypted[2:])
                ))
                if (
                    envelope["tenant_id"] != str(tenant_id)
                    or envelope["account_id"] != str(account_id)
                    or not isinstance(envelope["api_key"], str)
                    or not envelope["api_key"].strip()
                ):
                    raise ValueError("Credential envelope mismatch")
                timeout = int(row["timeout_seconds"])
                if not 1 <= timeout <= 120:
                    raise ValueError("Invalid timeout")
                result.append(CarrierAccount(
                    account_id, tenant_id, provider, endpoint,
                    row["upstream_account_id"], timeout, envelope["api_key"],
                ))
        except (ValueError, KeyError, TypeError, InvalidToken):
            raise HTTPException(503, "Carrier configuration unavailable") from None
        return result


class MarginEvaluator:
    @staticmethod
    def matches(
        rule: MarginRule, tenant_id: UUID, request: RatingRequest,
        rate: WholesaleRate, now: datetime,
    ) -> bool:
        if (
            rule.tenant_id != tenant_id or not rule.is_active
            or rule.currency != rate.currency or rule.valid_from > now
            or (rule.valid_until is not None and now >= rule.valid_until)
        ):
            return False
        for expected, actual in (
            (rule.carrier_account_id, rate.account_id),
            (rule.carrier_code, rate.carrier_code),
            (rule.service_code, rate.service_code),
            (rule.origin_country, request.origin.country_code),
            (rule.destination_country, request.destination.country_code),
        ):
            if expected is not None and expected != actual:
                return False
        for value, low, high in (
            (request.weights_kg[0], rule.min_weight_kg, rule.max_weight_kg),
            (rate.wholesale_cost, rule.min_wholesale_cost, rule.max_wholesale_cost),
        ):
            if low is not None and value < low:
                return False
            if high is not None and value >= high:
                return False
        return True

    @staticmethod
    def specificity(rule: MarginRule) -> int:
        return sum(value is not None for value in (
            rule.carrier_account_id, rule.carrier_code, rule.service_code,
            rule.origin_country, rule.destination_country,
            rule.min_weight_kg, rule.max_weight_kg,
            rule.min_wholesale_cost, rule.max_wholesale_cost,
        ))

    def evaluate(
        self, tenant_id: UUID, request: RatingRequest, rate: WholesaleRate,
        rules: list[MarginRule], now: datetime,
    ) -> PriceResult:
        candidates = [r for r in rules if self.matches(r, tenant_id, request, rate, now)]
        candidates.sort(key=lambda r: (
            r.priority, -self.specificity(r), r.created_at, str(r.id),
        ))
        rule = candidates[0] if candidates else None
        with localcontext() as context:
            context.prec = 50
            wholesale = rate.wholesale_cost.quantize(CENT, rounding=ROUND_CEILING)
            if rule is None:
                raw = wholesale * DEFAULT_MARKUP_PERCENT / HUNDRED
                markup = raw.quantize(CENT, rounding=ROUND_CEILING)
            else:
                raw = (wholesale * rule.markup_value / HUNDRED
                       if rule.markup_type == "PERCENTAGE" else rule.markup_value)
                raw = max(raw, rule.minimum_markup)
                if rule.maximum_markup is not None:
                    raw = min(raw, rule.maximum_markup)
                markup = money(raw)
                # Preserve configured minimum/maximum even if they contain
                # more precision than the shipment's two-decimal currency.
                if markup < rule.minimum_markup:
                    markup = rule.minimum_markup.quantize(CENT, rounding=ROUND_CEILING)
                if rule.maximum_markup is not None and markup > rule.maximum_markup:
                    raise ValueError("Markup bounds cannot be represented in currency")
            return PriceResult(wholesale, markup, money(wholesale + markup),
                               rule.id if rule else None)


class ProviderFailure(Exception):
    def __init__(self, code: str, retryable: bool = False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


class RateStrategy(ABC):
    def __init__(self, client: httpx.AsyncClient, account: CarrierAccount):
        self.client, self.account = client, account

    async def post(self, path: str, payload: dict[str, Any]) -> Any:
        kwargs: dict[str, Any] = {
            "json": payload,
            "timeout": httpx.Timeout(self.account.timeout_seconds, connect=5),
        }
        if self.account.provider == "EASYPOST":
            kwargs["auth"] = httpx.BasicAuth(self.account.api_key, "")
        else:
            kwargs["headers"] = {"Authorization": f"Bearer {self.account.api_key}"}
        async with self.client.stream(
            "POST", f"{self.account.base_url}{path}", **kwargs
        ) as response:
            if response.status_code >= 400:
                raise ProviderFailure(
                    "UPSTREAM_HTTP_ERROR",
                    response.status_code in {408, 429} or response.status_code >= 500,
                )
            try:
                return await streamed_json(response)
            except ValueError:
                raise ProviderFailure("INVALID_UPSTREAM_RESPONSE") from None

    @abstractmethod
    async def rates(self, request: RatingRequest) -> list[WholesaleRate]:
        raise NotImplementedError


class EasyPostStrategy(RateStrategy):
    @staticmethod
    def address(address: Address) -> dict[str, str]:
        values = {
            "name": address.name, "company": address.company,
            "street1": address.line1, "street2": address.line2,
            "city": address.city, "state": address.state, "zip": address.postal_code,
            "country": address.country_code, "phone": address.phone, "email": address.email,
        }
        return {k: v for k, v in values.items() if v is not None}

    async def rates(self, request: RatingRequest) -> list[WholesaleRate]:
        if request.cargo_type in {'PALLET','OVERLAND_FREIGHT'}:
            raise ProviderFailure('FREIGHT_REQUIRES_REGIONAL_ADAPTER')
        dimensions = request.dimensions[0] if request.dimensions else None
        with localcontext() as context:
            context.prec = 50
            measures=[('weight',request.weights_kg[0],KG_PER_OUNCE)]
            if dimensions:
                measures.extend([('length',dimensions.length_cm,CM_PER_INCH),('width',dimensions.width_cm,CM_PER_INCH),('height',dimensions.height_cm,CM_PER_INCH)])
            parcel = {
                field: str((value / divisor).quantize(
                    Decimal("0.1"), rounding=ROUND_CEILING
                )) for field, value, divisor in measures
            }
        shipment: dict[str, Any] = {
            "from_address": self.address(request.origin),
            "to_address": self.address(request.destination), "parcel": parcel,
            "options": {"label_format": "PDF"},
        }
        if request.cargo_type=='LETTER':
            # EasyPost creates these embedded addresses with strict AVS enabled.
            shipment['from_address']['verify_strict']=True
            shipment['to_address']['verify_strict']=True
        if request.customs_document and request.customs_document.get('required'):
            doc=request.customs_document
            if doc.get('currency')!='USD' or not doc.get('ready_for_provider'):
                raise ProviderFailure('CUSTOMS_DATA_NOT_PROVIDER_READY')
            shipment['customs_info']={'customs_certify':True,'customs_signer':doc['signer'],'contents_type':'merchandise',
                'non_delivery_option':'return','restriction_type':'none','customs_items':[
                    {'description':item['description'],'quantity':item['quantity'],'value':item['line_value'],
                     'weight':str(Decimal(item['line_weight_kg'])/KG_PER_OUNCE),'hs_tariff_number':item['hs_code'],
                     'origin_country':item['origin_country']} for item in doc['items']]}
        if self.account.upstream_account_id:
            shipment["carrier_accounts"] = [self.account.upstream_account_id]
        body = await self.post("/shipments", {"shipment": shipment})
        if (not isinstance(body, dict) or not isinstance(body.get("id"), str)
                or not isinstance(body.get("rates"), list)):
            raise ProviderFailure("INVALID_UPSTREAM_RESPONSE")
        if request.cargo_type=='LETTER' and any(
            body.get(party,{}).get('verifications',{}).get('delivery',{}).get('success') is not True
            for party in ('from_address','to_address')):
            raise ProviderFailure('LETTER_ADDRESS_VERIFICATION_REQUIRED')
        result = []
        for raw in body["rates"]:
            if not isinstance(raw, dict):
                raise ProviderFailure("INVALID_UPSTREAM_RESPONSE")
            if raw.get("currency") != request.currency:
                continue
            result.append(WholesaleRate(
                provider="EASYPOST", account_id=self.account.id,
                upstream_shipment_id=body["id"], upstream_rate_id=raw["id"],
                carrier_code=raw["carrier"], service_code=raw["service"],
                currency=raw["currency"], wholesale_cost=raw["rate"],
                delivery_days=raw.get("delivery_days"),
            ))
        return result


class RegionalStrategy(RateStrategy):
    """HTTPS bearer-authenticated POST /rates contract.

    Request: RatingRequest JSON with Decimal fields represented as strings.
    Response: {"quote_id": provider_identifier, "rates": [...]}.
    Each rate needs id, carrier_code, service_code, currency,
    wholesale_cost (decimal string) and optional delivery_days (integer/null).
    """

    async def rates(self, request: RatingRequest) -> list[WholesaleRate]:
        payload=request.model_dump(mode='json')
        if request.cargo_type=='LETTER':payload['address_validation_required']=True
        body = await self.post("/rates", payload)
        if (not isinstance(body, dict) or not isinstance(body.get("quote_id"), str)
                or not isinstance(body.get("rates"), list)):
            raise ProviderFailure("INVALID_UPSTREAM_RESPONSE")
        if request.cargo_type=='LETTER' and (body.get('address_validation',{}).get('origin_verified') is not True
            or body.get('address_validation',{}).get('destination_verified') is not True):
            raise ProviderFailure('LETTER_ADDRESS_VERIFICATION_REQUIRED')
        result = []
        for raw in body["rates"]:
            if not isinstance(raw, dict):
                raise ProviderFailure("INVALID_UPSTREAM_RESPONSE")
            if raw.get("currency") != request.currency:
                continue
            result.append(WholesaleRate(
                provider="REGIONAL", account_id=self.account.id,
                upstream_shipment_id=body["quote_id"], upstream_rate_id=raw["id"],
                carrier_code=raw["carrier_code"], service_code=raw["service_code"],
                currency=raw["currency"], wholesale_cost=raw["wholesale_cost"],
                fee_components=raw.get("fee_breakdown"),
                delivery_days=raw.get("delivery_days"),
            ))
        return result


class SendcloudStrategy(RateStrategy):
    def __init__(self,client,account,methods):
        super().__init__(client,account)
        self.methods=methods

    async def rates(self,request):
        try:
            return [WholesaleRate.model_validate(row) for row in await quote_sendcloud(self.client,self.account,request,self.methods)]
        except (ValueError,KeyError,TypeError):
            raise ProviderFailure('SENDCLOUD_CONFIGURATION_OR_PRICE_UNAVAILABLE') from None


class RatingService:
    def __init__(self, client: httpx.AsyncClient, repository: SupabaseRepository,
                 settings: Settings, pool: Any = None):
        self.client, self.repository, self.settings = client, repository, settings
        self.pool = pool
        self.semaphore = asyncio.Semaphore(settings.max_parallel_provider_requests)

    async def run_provider(self, strategy: RateStrategy, request: RatingRequest,
                           deadline: int) -> tuple[list[WholesaleRate], ProviderIssue | None]:
        account = strategy.account
        try:
            async with asyncio.timeout(deadline):
                async with self.semaphore:
                    rates = await strategy.rates(request)
            if not rates:
                raise ProviderFailure("NO_RATES_IN_REQUESTED_CURRENCY")
            return rates, None
        except ProviderFailure as exc:
            code, retryable = exc.code, exc.retryable
        except (TimeoutError, httpx.TimeoutException):
            code, retryable = "UPSTREAM_TIMEOUT", True
        except httpx.RequestError:
            code, retryable = "UPSTREAM_UNAVAILABLE", True
        except (ValueError, TypeError, KeyError):
            code, retryable = "INVALID_UPSTREAM_RESPONSE", False
        except Exception:
            code, retryable = "PROVIDER_PROCESSING_ERROR", False
        logger.warning("Provider failed provider=%s account=%s code=%s",
                       account.provider, account.id, code)
        return [], ProviderIssue(provider=account.provider, account_id=account.id,
                                 code=code, retryable=retryable)

    async def quote(self, context: TenantContext, request: RatingRequest,
                    provider_deadline: int | None = None) -> RatingResponse:
        dimensions=request.dimensions[0] if request.dimensions else None
        cargo=Cargo(cargo_type=request.cargo_type,actual_weight_kg=request.weights_kg[0],stackable=request.stackable,
            length_cm=dimensions.length_cm if dimensions else None,width_cm=dimensions.width_cm if dimensions else None,height_cm=dimensions.height_cm if dimensions else None)
        weight=calculate_cargo_charge(cargo,kg_per_m3=getattr(self.settings,'freight_kg_per_m3',Decimal('333')),
            kg_per_loading_metre=getattr(self.settings,'freight_kg_per_loading_metre',Decimal('1750')),
            deck_width_m=getattr(self.settings,'freight_deck_width_m',Decimal('2.4')))
        maximum=30000 if request.cargo_type in {'PALLET','OVERLAND_FREIGHT'} else 1000
        if Decimal(weight['billable_weight_kg'])>maximum:
            raise HTTPException(422,'Billable cargo weight exceeds service limits')
        request = request.model_copy(update={"weights_kg": [Decimal(weight["billable_weight_kg"])]})
        accounts = await self.repository.accounts(context)
        if request.cargo_type in {'PALLET','OVERLAND_FREIGHT'} or (request.customs_document and request.customs_document.get('required') and request.currency!='USD'):
            accounts=[account for account in accounts if account.provider=='REGIONAL']
        if not accounts:
            raise HTTPException(503, "No active carrier accounts configured")
        strategies = []
        for account in accounts:
            if getattr(account,'base_url',None) == 'https://panel.sendcloud.sc/api/v2':
                strategies.append(SendcloudStrategy(self.client,account,getattr(self.settings,'sendcloud_methods',{}).get(account.id,[])))
            else:
                strategies.append((EasyPostStrategy if account.provider == 'EASYPOST' else RegionalStrategy)(self.client,account))
        results = await asyncio.gather(*(
            self.run_provider(s, request, provider_deadline or self.settings.provider_deadline_seconds)
            for s in strategies
        ))
        quoted_at = datetime.now(timezone.utc)
        issues = [issue for _, issue in results if issue is not None]
        rates = []
        for wholesale_rates, _ in results:
            for rate in wholesale_rates:
                with calibrated_pricing_scope(
                    self.pool, currency=rate.currency, origin=request.origin.country_code,
                    carrier_account_id=rate.account_id, service_code=rate.service_code,
                    weight_kg=request.weights_kg[0], quoted_at=quoted_at, cargo_type=request.cargo_type,
                    volume_m3=(dimensions.length_cm*dimensions.width_cm*dimensions.height_cm/Decimal('1000000')) if dimensions else None,
                ):
                    client_price = await get_client_calibrated_rate(
                        context.tenant_id, rate.wholesale_cost, rate.carrier_code,
                        request.destination.country_code,
                    )
                rates.append(ClientRate(
                    provider=rate.provider, account_id=rate.account_id,
                    upstream_shipment_id=rate.upstream_shipment_id,
                    upstream_rate_id=rate.upstream_rate_id,
                    carrier_code=rate.carrier_code, service_code=rate.service_code,
                    currency=rate.currency, client_price_ex_tax=client_price,
                    delivery_days=rate.delivery_days,
                    fee_breakdown={
                        **({key: str(money(value)) for key, value in rate.fee_components.model_dump().items()}
                           if rate.fee_components else {key: None for key in ("base_cost", "fuel_surcharge", "residential_fee", "remote_area_fee")}),
                        "wholesale_total": str(money(rate.wholesale_cost)),
                        "platform_markup": str(money(client_price - rate.wholesale_cost)),
                        "source": "provider" if rate.fee_components else "quote_total",
                    },
                ))
        if not rates:
            raise HTTPException(503, {
                "code": "NO_CARRIER_RATES_AVAILABLE",
                "issues": [i.model_dump(mode="json") for i in issues],
            })
        rates.sort(key=lambda r: (r.client_price_ex_tax, r.provider, str(r.account_id),
                                 r.upstream_rate_id))
        return RatingResponse(
            request_id=uuid4(), currency=request.currency, quoted_at=quoted_at,
            expires_at=quoted_at + timedelta(seconds=self.settings.quote_ttl_seconds),
            partial=bool(issues), rates=rates, issues=issues, weight={key: str(value) for key, value in weight.items()},
        )


class FinanceEngine:
    def __init__(self, pool: asyncpg.Pool, settings: Settings, client: stripe.StripeClient):
        self.pool, self.settings, self.stripe = pool, settings, client

    async def lock_tenant(self, connection, tenant_id: UUID,
                          context: TenantContext | None = None,
                          roles: set[str] | None = None):
        # Consistent lock order: tenant, related record, wallet.
        tenant = await connection.fetchrow(
            """SELECT tenant_id, workspace_status, billing_status, billing_plan,
                      default_currency, stripe_customer_id, is_sandbox
               FROM public.tenants WHERE tenant_id=$1 FOR UPDATE""", tenant_id,
        )
        if tenant is None:
            raise HTTPException(404, "Workspace not found")
        if context is not None:
            if context.tenant_id != tenant_id:
                raise HTTPException(403, "Workspace mismatch")
            member = await connection.fetchrow(
                """SELECT role FROM public.users
                   WHERE tenant_id=$1 AND auth_user_id=$2 AND is_active FOR SHARE""",
                tenant_id, context.user_id,
            )
            if member is None or (roles and member["role"] not in roles):
                raise HTTPException(403, "Workspace permission denied")
            if tenant["workspace_status"] != "ACTIVE":
                raise HTTPException(403, "Workspace is not active")
        return tenant

    async def lock_wallet(self, connection, tenant_id: UUID):
        # FOR UPDATE retains the row lock through COMMIT/ROLLBACK.
        # Balance check AND reservation happen in the SAME transaction.
        # Concurrent label requests cannot spend the same available funds.
        wallet = await connection.fetchrow(
            """SELECT tenant_id, currency, balance, reserved_balance
               FROM public.wallets WHERE tenant_id=$1 FOR UPDATE""", tenant_id,
        )
        if wallet is None:
            raise HTTPException(503, "Wallet is not provisioned")
        return wallet

    async def append_ledger(self, connection, *, tenant_id: UUID, currency: str,
                            entry_type: str, balance_delta: Decimal,
                            reserved_delta: Decimal, balance_after: Decimal,
                            reserved_after: Decimal, reservation_id: UUID | None = None,
                            topup_id: UUID | None = None,
                            stripe_session_id: str | None = None,
                            stripe_event_id: str | None = None,
                            stripe_payment_intent_id: str | None = None):
        await connection.execute(
            """INSERT INTO public.wallet_ledger (
                   tenant_id,currency,entry_type,balance_delta,reserved_delta,
                   balance_after,reserved_after,reservation_id,topup_id,
                   stripe_session_id,stripe_event_id,stripe_payment_intent_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            tenant_id, currency, entry_type, balance_delta, reserved_delta,
            balance_after, reserved_after, reservation_id, topup_id,
            stripe_session_id, stripe_event_id, stripe_payment_intent_id,
        )

    async def reserve(self, context: TenantContext, shipment_id: UUID) -> BookingPermit:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await self.lock_tenant(connection, context.tenant_id,
                                                context, DISPATCH_ROLES)
                if tenant["billing_status"] != "ACTIVE":
                    raise HTTPException(403, "Billing account is not active")
                shipment = await connection.fetchrow(
                    """SELECT id,currency,final_client_price,status,quote_expires_at
                       FROM public.shipments
                       WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
                    context.tenant_id, shipment_id,
                )
                if shipment is None:
                    raise HTTPException(404, "Shipment not found")
                existing = await connection.fetchrow(
                    """SELECT id,status FROM public.wallet_reservations
                       WHERE tenant_id=$1 AND shipment_id=$2 FOR UPDATE""",
                    context.tenant_id, shipment_id,
                )
                if existing:
                    raise HTTPException(409, {
                        "code": "BOOKING_ALREADY_STARTED",
                        "reservation_id": str(existing["id"]), "status": existing["status"],
                    })
                if shipment["status"] not in {"DRAFT", "QUOTED"}:
                    raise HTTPException(409, "Shipment is not ready for booking")
                if shipment["quote_expires_at"] <= datetime.now(timezone.utc):
                    raise HTTPException(409, "Shipping quote has expired")
                amount, currency, plan = (shipment["final_client_price"],
                                          shipment["currency"], tenant["billing_plan"])
                if currency not in CURRENCIES:
                    raise HTTPException(409, "Unsupported shipment currency")
                wallet = None
                if plan == "PREPAID_WALLET":
                    wallet = await self.lock_wallet(connection, context.tenant_id)
                    require_prepaid_funds(wallet, amount, currency)
                elif plan != "POSTPAID_30_DAY":
                    raise HTTPException(403, "Unsupported billing plan")
                # Active postpaid tenants bypass wallet funding checks.
                reservation = await connection.fetchrow(
                    """INSERT INTO public.wallet_reservations
                       (tenant_id,shipment_id,billing_plan,amount,currency)
                       VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                    context.tenant_id, shipment_id, plan, amount, currency,
                )
                if wallet is not None:
                    reserved = wallet["reserved_balance"] + amount
                    await connection.execute(
                        """UPDATE public.wallets SET reserved_balance=$2,updated_at=now()
                           WHERE tenant_id=$1""", context.tenant_id, reserved,
                    )
                    await self.append_ledger(
                        connection, tenant_id=context.tenant_id, currency=currency,
                        entry_type="RESERVE", balance_delta=ZERO, reserved_delta=amount,
                        balance_after=wallet["balance"], reserved_after=reserved,
                        reservation_id=reservation["id"],
                    )
                await connection.execute(
                    "UPDATE public.shipments SET status='BOOKING' WHERE tenant_id=$1 AND id=$2",
                    context.tenant_id, shipment_id,
                )
                return BookingPermit(context.tenant_id, shipment_id, reservation["id"],
                                     amount, currency, plan)

    async def locked_reservation(self, connection, permit: BookingPermit):
        row = await connection.fetchrow(
            """SELECT * FROM public.wallet_reservations
               WHERE tenant_id=$1 AND id=$2 AND shipment_id=$3 FOR UPDATE""",
            permit.tenant_id, permit.reservation_id, permit.shipment_id,
        )
        if row is None:
            raise HTTPException(404, "Reservation not found")
        if (row["amount"] != permit.amount or row["currency"] != permit.currency
                or row["billing_plan"] != permit.billing_plan):
            raise HTTPException(409, "Booking permit mismatch")
        return row

    async def mark_submitted(self, permit: BookingPermit) -> None:
        """Call immediately before purchasing the provider label."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await self.lock_tenant(connection, permit.tenant_id)
                if tenant["is_sandbox"]:
                    raise HTTPException(403, "Sandbox tenants cannot submit carrier label purchases")
                reservation = await self.locked_reservation(connection, permit)
                if reservation["status"] != "RESERVED":
                    raise HTTPException(409, "Booking cannot be submitted")
                shipment = await connection.fetchrow(
                    """SELECT final_client_price,currency,status FROM public.shipments
                       WHERE tenant_id=$1 AND id=$2 FOR UPDATE""",
                    permit.tenant_id, permit.shipment_id,
                )
                if (shipment is None or shipment["final_client_price"] != permit.amount
                        or shipment["currency"] != permit.currency
                        or shipment["status"] != "BOOKING"):
                    raise HTTPException(409, "Shipment changed after reservation")
                await connection.execute(
                    """UPDATE public.wallet_reservations SET status='SUBMITTED'
                       WHERE tenant_id=$1 AND id=$2""", permit.tenant_id, permit.reservation_id,
                )

    async def finish_booking(
        self, permit: BookingPermit,
        outcome: Literal["SUCCESS", "DEFINITIVE_FAILURE", "NOT_SUBMITTED"],
        *, tracking_number: str | None = None, label_storage_path: str | None = None,
        carrier_name: str = "UNKNOWN",
        label_documents: dict | None = None,
    ) -> None:
        """Backend-only settlement after a confirmed provider outcome.

        Never release on a network timeout: a label may have been purchased.
        Reconcile SUBMITTED reservations against the provider before release.
        NOT_SUBMITTED is only valid before mark_submitted().
        """
        if outcome not in {"SUCCESS", "DEFINITIVE_FAILURE", "NOT_SUBMITTED"}:
            raise ValueError("Unknown booking outcome")
        if outcome == "SUCCESS" and (
            not tracking_number or not tracking_number.strip()
            or len(tracking_number) > 200
            or not label_storage_path or not label_storage_path.strip()
        ):
            raise ValueError("Confirmed purchase requires tracking and label location")
        imported_order_id = None
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await self.lock_tenant(connection, permit.tenant_id)
                if tenant["is_sandbox"] and outcome == "SUCCESS":
                    raise HTTPException(403, "Sandbox tenants cannot settle real carrier dispatches")
                row = await self.locked_reservation(connection, permit)
                target = "CAPTURED" if outcome == "SUCCESS" else "RELEASED"
                if row["status"] == target:
                    return
                if row["status"] in {"CAPTURED", "RELEASED"}:
                    raise HTTPException(409, "Reservation already finalized")
                expected = "RESERVED" if outcome == "NOT_SUBMITTED" else "SUBMITTED"
                if row["status"] != expected:
                    raise HTTPException(409, "Booking requires reconciliation")
                if row["billing_plan"] == "PREPAID_WALLET":
                    wallet = await self.lock_wallet(connection, permit.tenant_id)
                    amount = row["amount"]
                    if wallet["currency"] != row["currency"] or wallet["reserved_balance"] < amount:
                        raise HTTPException(503, "Wallet reconciliation required")
                    delta = -amount if outcome == "SUCCESS" else ZERO
                    balance, reserved = wallet["balance"] + delta, wallet["reserved_balance"] - amount
                    await connection.execute(
                        """UPDATE public.wallets SET balance=$2,reserved_balance=$3,updated_at=now()
                           WHERE tenant_id=$1""", permit.tenant_id, balance, reserved,
                    )
                    await self.append_ledger(
                        connection, tenant_id=permit.tenant_id, currency=row["currency"],
                        entry_type="CAPTURE" if outcome == "SUCCESS" else "RELEASE",
                        balance_delta=delta, reserved_delta=-amount,
                        balance_after=balance, reserved_after=reserved,
                        reservation_id=permit.reservation_id,
                    )
                await connection.execute(
                    "UPDATE public.wallet_reservations SET status=$3 WHERE tenant_id=$1 AND id=$2",
                    permit.tenant_id, permit.reservation_id, target,
                )
                if outcome == "SUCCESS":
                    await connection.execute(
                        """UPDATE public.shipments SET status='BOOKED',booked_at=now(),
                           tracking_number=$3,label_storage_path=$4,
                           logistics_metadata=logistics_metadata || $5::jsonb WHERE tenant_id=$1 AND id=$2""",
                        permit.tenant_id, permit.shipment_id, tracking_number, label_storage_path,
                        json.dumps({'automation_label':label_documents} if label_documents is not None else {}),
                    )
                    imported_order_id = await EcommerceService(self.pool).queue_confirmed_tracking(
                        connection, permit.tenant_id, permit.shipment_id, tracking_number, carrier_name)
                else:
                    await connection.execute(
                        "UPDATE public.shipments SET status='FAILED' WHERE tenant_id=$1 AND id=$2",
                        permit.tenant_id, permit.shipment_id,
                    )
        if imported_order_id is not None:
            try:
                await push_tracking_to_store(permit.tenant_id, imported_order_id, tracking_number, carrier_name)
            except Exception:
                logger.warning("Store tracking remains queued for retry after label settlement")

    def check_payment_environment(self, tenant):
        key = self.settings.stripe_secret_key.get_secret_value()
        live = self.settings.stripe_livemode
        if live:
            if (tenant["is_sandbox"] or getattr(self.settings, "database_environment", "LIVE") != "LIVE"
                    or not key.startswith(("sk_live_", "rk_live_"))):
                raise HTTPException(403, "Live payments cannot fund sandbox tenants")
        elif (not tenant["is_sandbox"] or getattr(self.settings, "database_environment", "LIVE") != "SANDBOX"
              or not key.startswith(("sk_test_", "rk_test_"))):
            raise HTTPException(403, "Test payments require a marked tenant in a SANDBOX database")

    async def authorize_label_preview(self, context: TenantContext, shipment_id: UUID) -> dict:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await self.lock_tenant(connection, context.tenant_id, context, DISPATCH_ROLES)
                if tenant["billing_status"] != "ACTIVE":
                    raise HTTPException(403, "Billing account is not active")
                shipment = await connection.fetchrow(
                    """SELECT id,status,currency,tracking_number FROM public.shipments
                       WHERE tenant_id=$1 AND id=$2 FOR SHARE""", context.tenant_id, shipment_id)
                if shipment is None:
                    raise HTTPException(404, "Shipment not found")
                if shipment["status"] not in {"BOOKED", "DELIVERED"}:
                    raise HTTPException(409, "Shipment is not ready for label preview")
                if tenant["billing_plan"] == "PREPAID_WALLET":
                    wallet = await self.lock_wallet(connection, context.tenant_id)
                    require_prepaid_funds(wallet, CENT, shipment["currency"])
                elif tenant["billing_plan"] != "POSTPAID_30_DAY":
                    raise HTTPException(403, "Unsupported billing plan")
                tracking = re.sub(r"[^A-Za-z0-9 ._-]", "", shipment["tracking_number"] or str(shipment_id))[:100]
                zpl = ("^XA\n^PW812\n^LL1218\n^FO50,60^A0N,45,45^FDEASYINVIO.COM - SAMPLE ONLY^FS\n"
                       "^FO50,140^A0N,28,28^FDNOT A CARRIER SHIPPING LABEL^FS\n"
                       f"^FO50,220^A0N,30,30^FD{shipment_id}^FS\n"
                       f"^FO50,350^BY3^BCN,120,Y,N,N^FD{tracking}^FS\n^XZ")
                return {"shipment_id": str(shipment_id), "zpl": zpl, "simulated": True,
                        "charged": False, "printer_broadcast": False}

    async def create_checkout(self, context: TenantContext, body: TopupRequest, *, return_urls: tuple[str,str] | None = None) -> TopupResponse:
        if self.stripe is None:
            raise HTTPException(503, "Stripe integration is disabled")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await self.lock_tenant(connection, context.tenant_id, context, FINANCE_ROLES)
                self.check_payment_environment(tenant)
                if tenant["billing_plan"] != "PREPAID_WALLET":
                    raise HTTPException(409, "Workspace does not use a wallet")
                customer = tenant["stripe_customer_id"]
                if not customer:
                    raise HTTPException(409, "Stripe customer is not configured")
                wallet = await self.lock_wallet(connection, context.tenant_id)
                currency = wallet["currency"]
                existing = await connection.fetchrow(
                    "SELECT * FROM public.wallet_topups WHERE id=$1 FOR UPDATE", body.request_id,
                )
                if existing:
                    if existing["is_sandbox"]:
                        raise HTTPException(409, "Test-hook request IDs cannot be reused for Checkout")
                    if (
                        existing["tenant_id"] != context.tenant_id
                        or existing["requested_by_auth_user_id"] != context.user_id
                        or existing["amount"] != body.amount or existing["currency"] != currency
                        or existing["stripe_customer_id"] != customer
                    ):
                        raise HTTPException(409, "Top-up request conflicts")
                    if existing["status"] == "CREDITED":
                        raise HTTPException(409, "Top-up is already credited")
                    if existing["stripe_session_id"] and existing["checkout_url"]:
                        return TopupResponse(topup_id=existing["id"],
                            checkout_session_id=existing["stripe_session_id"],
                            checkout_url=existing["checkout_url"])
                    # Stripe idempotency keys can expire. Never create a new
                    # session for an old ambiguous creation attempt.
                    if datetime.now(timezone.utc) - existing["created_at"] > timedelta(hours=23):
                        raise HTTPException(409, "Old checkout attempt needs reconciliation")
                else:
                    await connection.execute(
                        """INSERT INTO public.wallet_topups
                           (id,tenant_id,requested_by_auth_user_id,stripe_customer_id,amount,currency)
                           VALUES ($1,$2,$3,$4,$5,$6)""",
                        body.request_id, context.tenant_id, context.user_id, customer, body.amount, currency,
                    )
        try:
            # Native async Stripe SDK call; no network call inside a DB transaction.
            session = await self.stripe.v1.checkout.sessions.create_async({
                "mode": "payment", "customer": customer, "payment_method_types": ["card"],
                "success_url": return_urls[0] if return_urls else self.settings.checkout_success_url,
                "cancel_url": return_urls[1] if return_urls else self.settings.checkout_cancel_url,
                "client_reference_id": str(body.request_id),
                "metadata": {"purpose": "wallet_topup", "tenant_id": str(context.tenant_id),
                             "topup_id": str(body.request_id)},
                "line_items": [{"quantity": 1, "price_data": {
                    "currency": currency.lower(), "unit_amount": to_minor_units(body.amount, currency),
                    "product_data": {"name": "EasyInvio.com wallet top-up"},
                }}],
            }, options={"idempotency_key": f"wallet-topup:{body.request_id}"})
        except stripe.StripeError:
            raise HTTPException(503, "Checkout temporarily unavailable") from None
        if not session.id or not session.url:
            raise HTTPException(503, "Checkout response is incomplete")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await self.lock_tenant(connection, context.tenant_id)
                current = await connection.fetchrow(
                    """SELECT stripe_session_id FROM public.wallet_topups
                       WHERE tenant_id=$1 AND id=$2 FOR UPDATE""", context.tenant_id, body.request_id,
                )
                if current is None or current["stripe_session_id"] not in {None, session.id}:
                    raise HTTPException(409, "Checkout reconciliation required")
                await connection.execute(
                    """UPDATE public.wallet_topups SET stripe_session_id=$3,checkout_url=$4
                       WHERE tenant_id=$1 AND id=$2""",
                    context.tenant_id, body.request_id, session.id, session.url,
                )
        return TopupResponse(topup_id=body.request_id, checkout_session_id=session.id,
                             checkout_url=session.url)

    async def credit_session(self, event_id: str, session: dict[str, Any]) -> bool:
        metadata = session.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("Invalid metadata")
        if metadata.get("purpose") != "wallet_topup" or session.get("payment_status") != "paid":
            return False
        if session.get("mode") != "payment" or session.get("livemode") is not self.settings.stripe_livemode:
            raise ValueError("Invalid payment mode/environment")
        tenant_id, topup_id = UUID(metadata["tenant_id"]), UUID(metadata["topup_id"])
        session_id, customer = session["id"], session["customer"]
        currency = str(session["currency"]).upper()
        amount = from_minor_units(session["amount_total"], currency)
        if (
            not isinstance(session_id, str) or not session_id.startswith("cs_")
            or not isinstance(customer, str) or not customer.startswith("cus_")
            or session.get("client_reference_id") != str(topup_id)
        ):
            raise ValueError("Invalid checkout identifiers")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await self.lock_tenant(connection, tenant_id)
                self.check_payment_environment(tenant)
                topup = await connection.fetchrow(
                    "SELECT * FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                    tenant_id, topup_id,
                )
                if topup is None or (
                    topup["stripe_customer_id"] != customer or topup["currency"] != currency
                    or topup["amount"] != amount
                    or topup["stripe_session_id"] not in {None, session_id}
                ):
                    raise ValueError("Checkout does not match registered top-up")
                if topup["is_sandbox"]:
                    raise ValueError("Sandbox PaymentIntent top-ups cannot be credited through Checkout webhooks")
                if topup["status"] == "CREDITED":
                    return False
                if tenant["stripe_customer_id"] != customer:
                    raise ValueError("Workspace/customer mismatch")
                wallet = await self.lock_wallet(connection, tenant_id)
                if wallet["currency"] != currency:
                    raise ValueError("Wallet currency mismatch")
                balance = wallet["balance"] + amount
                await connection.execute(
                    "UPDATE public.wallets SET balance=balance+$2,updated_at=now() WHERE tenant_id=$1",
                    tenant_id, amount,
                )
                await self.append_ledger(
                    connection, tenant_id=tenant_id, currency=currency, entry_type="TOPUP",
                    balance_delta=amount, reserved_delta=ZERO, balance_after=balance,
                    reserved_after=wallet["reserved_balance"], topup_id=topup_id,
                    stripe_session_id=session_id, stripe_event_id=event_id,
                )
                await connection.execute(
                    """UPDATE public.wallet_topups SET status='CREDITED',
                       stripe_session_id=$3,credited_at=now() WHERE tenant_id=$1 AND id=$2""",
                    tenant_id, topup_id, session_id,
                )
                return True


def country_to_alpha2(value: str) -> str:
    code = value.upper()
    country = pycountry.countries.get(**({"alpha_2": code} if len(code) == 2 else {"alpha_3": code}))
    if country is None:
        raise ValueError("Unknown ISO country code")
    return country.alpha_2


def parse_quote(body: str) -> ParsedQuote:
    if len(body) > 500:
        raise ValueError("Message is too long")
    match = QUOTE_PATTERN.fullmatch(body)
    if match is None:
        raise ValueError("Unrecognized quote format")
    weight = Decimal(match.group("weight"))
    if not ZERO < weight <= Decimal("1000"):
        raise ValueError("Weight must be greater than zero and at most 1000kg")
    route = match.group("route")
    return ParsedQuote(weight, country_to_alpha2(match.group("origin")),
                       country_to_alpha2(match.group("destination")), route.upper() if route else None)


def twiml(text: str) -> str:
    response = MessagingResponse()
    response.message(text)
    return str(response)


def xml_response(xml: str) -> Response:
    return Response(content=xml, media_type="application/xml")


def decode_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def rls_context(connection, context: TenantContext) -> None:
    # Trusted context comes from verified JWT membership or a signed
    # Twilio request plus a verified phone binding, never message text.
    # These variables are LOCAL to the transaction and reset on pool reuse.
    await connection.execute("SELECT set_config('request.jwt.claims', $1, true)",
                             json.dumps({"sub": str(context.user_id),
                                         "role": "authenticated", "tenant_id": str(context.tenant_id)}))
    await connection.execute("SET LOCAL ROLE authenticated")


class WhatsAppService:
    def __init__(self, pool: asyncpg.Pool, settings: Settings, rating: RatingService):
        self.pool, self.settings, self.rating = pool, settings, rating

    async def resolve_sender(self, sender: str, receiver: str) -> TenantContext | None:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT b.tenant_id,u.auth_user_id,u.role
                   FROM public.whatsapp_bindings b
                   JOIN public.users u ON u.tenant_id=b.tenant_id AND u.id=b.user_id
                   JOIN public.tenants t ON t.tenant_id=b.tenant_id
                   WHERE b.sender_e164=$1 AND b.receiver_e164=$2 AND b.is_active
                     AND u.is_active AND u.role IN ('OWNER','ADMIN','DISPATCHER')
                     AND t.workspace_status='ACTIVE'
                     AND (NOT $3::boolean OR t.is_sandbox) LIMIT 2""", sender, receiver,
                getattr(self.settings, "twilio_whatsapp_sandbox_enabled", False),
            )
        if len(rows) != 1:
            return None
        row = rows[0]
        # A Twilio signature is not a Supabase access token. The rating
        # repository uses tenant-scoped backend queries for this context.
        return TenantContext(row["tenant_id"], row["auth_user_id"], row["role"], "")

    def sign_choice(self, context: TenantContext, choice_id: UUID, expires_at: datetime) -> str:
        return jwt.encode({
            "iss": "veloce-whatsapp", "aud": "veloce-booking", "sub": str(context.user_id),
            "t": str(context.tenant_id), "q": str(choice_id),
            "iat": int(datetime.now(timezone.utc).timestamp()), "exp": int(expires_at.timestamp()),
        }, self.settings.quote_link_secret.get_secret_value(), algorithm="HS256")

    async def process(self, context: TenantContext, message_sid: str, body: str, sender_e164: str | None = None) -> str:
        async with self.pool.acquire() as connection:
            # READ COMMITTED sees a competing receipt after the advisory lock
            # wait. A repeatable-read snapshot taken before that wait would
            # miss the just-committed receipt and repeat the carrier work.
            async with connection.transaction():
                # Cross-worker duplicate suppression uses a transactional
                # advisory lock. A hash collision only serializes requests.
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1::text,0))",
                    f"whatsapp:{context.tenant_id}:{message_sid}",
                )
                cached = await connection.fetchval(
                    "SELECT response_xml FROM public.whatsapp_receipts WHERE tenant_id=$1 AND message_sid=$2",
                    context.tenant_id, message_sid,
                )
                if cached is not None:
                    return cached
                if sender_e164 is not None:
                    # Only the authenticated inbound route supplies the sender.
                    # Existing SID receipts prevent replay from extending the window.
                    await connection.execute('''UPDATE public.whatsapp_bindings b SET last_inbound_at=now()
                        FROM public.users u WHERE b.tenant_id=$1 AND b.user_id=u.id AND u.tenant_id=b.tenant_id
                         AND u.auth_user_id=$2 AND b.sender_e164=$3 AND b.receiver_e164=$4 AND b.is_active AND u.is_active''',
                        context.tenant_id,context.user_id,sender_e164,self.settings.twilio_whatsapp_number)
                try:
                    parsed = parse_quote(body)
                except ValueError:
                    xml = twiml("Send: Quote 4.5kg from GBR to USA\n"
                                "Use ISO country codes and a weight up to 1000kg.\n"
                                "If needed, add: route YOUR_ROUTE_CODE")
                else:
                    await rls_context(connection, context)
                    routes = await connection.fetch(
                        """SELECT origin_address,destination_address,dimensions,currency
                           FROM public.whatsapp_routes WHERE tenant_id=$1
                             AND origin_country=$2 AND destination_country=$3 AND is_active
                             AND ($4::text IS NULL OR route_code=$4)
                           ORDER BY route_code LIMIT 2""",
                        context.tenant_id, parsed.origin_country, parsed.destination_country, parsed.route_code,
                    )
                    await connection.execute("RESET ROLE")
                    if len(routes) != 1:
                        xml = twiml("No unique saved route matches. Ask your admin to configure real "
                                    "addresses and parcel dimensions, or add a route code:\n"
                                    "Quote 4.5kg from GBR to USA route EXPORT_US")
                    else:
                        route = routes[0]
                        rating_request = RatingRequest(
                            origin=Address.model_validate(decode_json(route["origin_address"])),
                            destination=Address.model_validate(decode_json(route["destination_address"])),
                            dimensions=[Dimensions.model_validate(decode_json(route["dimensions"]))],
                            weights_kg=[parsed.weight_kg], currency=route["currency"],
                        )
                        # Short per-provider deadlines preserve fast provider
                        # results rather than waiting 35s for a slow provider.
                        with borrowed_pricing_connection(connection):
                            result = await self.rating.quote(context, rating_request,
                                                             self.settings.whatsapp_provider_seconds)
                        sandbox = getattr(self.settings, "twilio_whatsapp_sandbox_enabled", False)
                        lines = ["EasyInvio.com sandbox quotes" if sandbox else "EasyInvio.com live quotes",
                                 f"{parsed.weight_kg}kg | {parsed.origin_country} → {parsed.destination_country}",
                                 "Prices exclude tax. Final total is confirmed in app."]
                        for position, rate in enumerate(result.rates[:3], 1):
                            choice_id = uuid4()
                            await connection.execute(
                                """INSERT INTO public.whatsapp_quote_choices
                                   (id,tenant_id,auth_user_id,rating_request,selected_rate,expires_at)
                                   VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6)""",
                                choice_id, context.tenant_id, context.user_id,
                                rating_request.model_dump_json(), rate.model_dump_json(), result.expires_at,
                            )
                            link = self.settings.booking_page_url + "?" + urlencode({
                                "t": str(context.tenant_id),
                                "quote": self.sign_choice(context, choice_id, result.expires_at),
                            })
                            delivery = (f" | estimated {rate.delivery_days} days"
                                        if rate.delivery_days is not None else "")
                            lines.extend(["", f"{position}. {rate.carrier_code} {rate.service_code}",
                                          f"{rate.currency} {rate.client_price_ex_tax:.2f}{delivery}", link])
                        if result.partial:
                            lines.extend(["", "Some providers did not return rates."])
                        if sandbox:
                            lines.extend(["", "Sandbox pricing only. No carrier labels or live payments are created."])
                        lines.extend(["", f"Links expire at {result.expires_at:%H:%M:%S UTC}. Sign in to review and book."])
                        xml = twiml("\n".join(lines))
                await connection.execute(
                    """INSERT INTO public.whatsapp_receipts (tenant_id,message_sid,response_xml)
                       VALUES ($1,$2,$3)""", context.tenant_id, message_sid, xml,
                )
                return xml


@asynccontextmanager
async def lifespan(application: FastAPI):
    if "--local-preview" in sys.argv:
        logger.warning("Local preview: database and external integrations are disabled")
        application.state.local_preview = True
        yield
        return
    application.state.local_preview = False
    settings = Settings()
    tls = database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict)
    async with httpx.AsyncClient(
        follow_redirects=False, trust_env=False,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=30),
        timeout=httpx.Timeout(30, connect=5),
    ) as http_client:
        pool = await asyncpg.create_pool(
            dsn=settings.database_url.get_secret_value(), ssl=tls,
            min_size=1, max_size=settings.db_pool_max_size, command_timeout=15,
            server_settings={"application_name": "veloce-main", "statement_timeout": "15000",
                             "lock_timeout": "5000", "idle_in_transaction_session_timeout": "15000"},
        )
        try:
            async with pool.acquire() as connection:
                capability = await connection.fetchrow(
                    """SELECT rolsuper OR rolbypassrls AS bypass,
                              pg_has_role(current_user,'authenticated','MEMBER') AS can_set_role
                       FROM pg_roles WHERE rolname=current_user"""
                )
                if not capability or not capability["bypass"] or not capability["can_set_role"]:
                    raise RuntimeError("DB role must be a trusted BYPASSRLS role able to SET ROLE authenticated")
                # Confirm migrations at startup instead of failing on the first payment.
                for table in ("tenants", "users", "carrier_accounts", "margin_rules", "shipments",
                              "wallets", "wallet_topups", "wallet_reservations", "wallet_ledger",
                              "whatsapp_bindings", "whatsapp_routes", "whatsapp_quote_choices", "whatsapp_receipts",
                              "admin_configuration_events", "ecommerce_stores", "ecommerce_tracking_outbox",
                              "tracking_events", "support_tickets", "support_message_outbox"):
                    if await connection.fetchval("SELECT to_regclass($1)", f"public.{table}") is None:
                        raise RuntimeError(f"Required migration table is missing: public.{table}")
                await connection.execute("SELECT is_sandbox FROM public.tenants LIMIT 0")
                await connection.execute("SELECT is_sandbox,sandbox_test_token,stripe_payment_intent_id FROM public.wallet_topups LIMIT 0")
                await connection.execute("SELECT stripe_payment_intent_id FROM public.wallet_ledger LIMIT 0")
                await connection.execute("SELECT proof_of_delivery_url FROM public.shipments LIMIT 0")
                await connection.execute("SELECT billing_plan,cargo_type,min_volume_m3,max_volume_m3 FROM public.margin_rules LIMIT 0")
            repository = SupabaseRepository(http_client, settings)
            configure_pricing_pool(pool)
            rating = RatingService(http_client, repository, settings, pool=pool)
            stripe_http = stripe.HTTPXClient(timeout=20)
            try:
                stripe_client = stripe.StripeClient(
                    settings.stripe_secret_key.get_secret_value(),
                    http_client=stripe_http, max_network_retries=2,
                ) if settings.stripe_enabled else None
                application.state.settings = settings
                application.state.repository = repository
                application.state.rating = rating
                application.state.finance = FinanceEngine(pool, settings, stripe_client)
                application.state.automation_freight=AutomationService(pool,rating,application.state.finance,repository,RatingRequest,http_client,settings)
                from backend.order_csv import CSVOrderService
                application.state.csv_orders=CSVOrderService(pool,application.state.automation_freight)
                from backend.ecommerce_connectors import StoreConnectorSettings
                application.state.ecommerce = EcommerceService(pool,client=http_client,
                    connectors=StoreConnectorSettings().ecommerce_connectors)
                application.state.tracking_support = TrackingSupportService(pool, TrackingSettings())
                application.state.support_delivery = SupportDelivery(pool,http_client,settings,DeliverySettings())
                application.state.sandbox_billing = SandboxBillingService(application.state.finance, settings) if settings.stripe_enabled else None
                application.state.admin_portal = AdminService(pool)
                application.state.whatsapp = WhatsAppService(pool, settings, rating)
                application.state.twilio_validator = RequestValidator(settings.twilio_auth_token.get_secret_value()) if settings.twilio_enabled else None
                application.state.jwks = PyJWKClient(
                    f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
                    cache_jwk_set=True, lifespan=300, timeout=5,
                )
                configure_ecommerce_service(application.state.ecommerce)
                ecommerce_task = asyncio.create_task(tracking_worker(application.state.ecommerce))
                support_task = asyncio.create_task(application.state.tracking_support.worker())
                notification_task = asyncio.create_task(application.state.support_delivery.worker())
                crm_task = None
                application.state.hubspot = None
                try:
                    crm_settings = HubSpotSettings()
                    if crm_settings.hubspot_enabled:
                        application.state.hubspot = HubSpotService(pool, HubSpotClient(http_client, crm_settings))
                        configure_hubspot_service(application.state.hubspot)
                        crm_task = asyncio.create_task(application.state.hubspot.worker())
                except (ValueError, ValidationError):
                    logger.warning("HubSpot configuration invalid; optional CRM worker disabled")
                try:
                    yield
                finally:
                    notification_task.cancel()
                    try:
                        await notification_task
                    except asyncio.CancelledError:
                        pass
                    support_task.cancel()
                    try:
                        await support_task
                    except asyncio.CancelledError:
                        pass
                    if crm_task is not None:
                        crm_task.cancel()
                        try:
                            await crm_task
                        except asyncio.CancelledError:
                            pass
                    configure_hubspot_service(None)
                    ecommerce_task.cancel()
                    try:
                        await ecommerce_task
                    except asyncio.CancelledError:
                        pass
                    configure_ecommerce_service(None)
            finally:
                await stripe_http.close_async()
        finally:
            configure_pricing_pool(None)
            await pool.close()


app = FastAPI(title="EasyInvio.com Backend", version="1.0.0", lifespan=lifespan)
from dotenv import dotenv_values
try:
    _origin_values = os.environ.get("FRONTEND_ALLOWED_ORIGINS", dotenv_values(".env").get("FRONTEND_ALLOWED_ORIGINS"))
    _frontend_origins = json.loads(_origin_values) if _origin_values else ["http://127.0.0.1:5500", "http://localhost:5500"]
    if not isinstance(_frontend_origins, list) or any(not isinstance(origin, str) or origin == "*" for origin in _frontend_origins):
        raise ValueError("Invalid origins")
except (ValueError, TypeError):
    raise RuntimeError("FRONTEND_ALLOWED_ORIGINS must be a JSON array of explicit origins") from None
app.add_middleware(CORSMiddleware, allow_origins=_frontend_origins,
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])
bearer = HTTPBearer(auto_error=False)


@app.middleware("http")
async def preview_guard(request: Request, call_next):
    public_tools = {"/api/v1/config", "/api/v1/customs/harmonize", "/api/v1/customs/declaration",
                    "/api/v1/logistics/weight", "/api/v1/logistics/cargo-weight", "/api/v1/rates/sample", "/api/v1/routing/sample", "/api/v1/rates/preview", "/api/v1/routing/preview",
                    "/api/v1/shipments/batch-preview", "/api/v1/shipments/batch-template",
                    "/api/v1/shipments/batch-review-preview", "/api/v1/audit/preview"}
    if (getattr(request.app.state, "local_preview", False)
            and request.url.path.startswith(("/v1/", "/webhooks/", "/api/v1/"))
            and request.url.path not in public_tools):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"detail": "Local preview: configure credentials and database migrations to enable integrations"})
    return await call_next(request)


async def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> TenantContext:
    unauthorized = HTTPException(401, "Invalid or expired authentication token",
                                 headers={"WWW-Authenticate": "Bearer"})
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    token = credentials.credentials
    if len(token) > 16000:
        raise unauthorized
    settings = request.app.state.settings
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != settings.jwt_algorithm or not isinstance(header.get("kid"), str):
            raise unauthorized
        signing_key = await asyncio.to_thread(request.app.state.jwks.get_signing_key_from_jwt, token)
        claims = jwt.decode(
            token, signing_key.key, algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience, issuer=f"{settings.supabase_url}/auth/v1", leeway=5,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "role"]},
        )
        if claims["role"] != "authenticated":
            raise unauthorized
        app_metadata = claims.get('app_metadata')
        metadata_tenant = app_metadata.get('tenant_id') if isinstance(app_metadata, dict) else None
        tenant_claim = claims.get('tenant_id') or metadata_tenant
        if not isinstance(tenant_claim, str):
            raise unauthorized
        if claims.get('tenant_id') and metadata_tenant and claims['tenant_id'] != metadata_tenant:
            raise unauthorized
        # app_metadata is issuer-controlled; user_metadata is never an identity source.
        user_id, tenant_id = UUID(claims["sub"]), UUID(tenant_claim)
    except HTTPException:
        raise
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise unauthorized from None
    context = TenantContext(tenant_id, user_id, "", token)
    repository = request.app.state.repository
    members, tenants = await asyncio.gather(
        repository.select("users", {
            "select": "tenant_id,auth_user_id,role,is_active", "tenant_id": f"eq.{tenant_id}",
            "auth_user_id": f"eq.{user_id}", "is_active": "eq.true", "limit": "2",
        }, context),
        repository.select("tenants", {
            "select": "tenant_id,workspace_status", "tenant_id": f"eq.{tenant_id}",
            "workspace_status": "eq.ACTIVE", "limit": "2",
        }, context),
    )
    if len(members) != 1 or len(tenants) != 1:
        raise HTTPException(403, "Active workspace membership required")
    member = members[0]
    if (member.get("tenant_id") != str(tenant_id) or member.get("auth_user_id") != str(user_id)
            or member.get("role") not in ALL_ROLES):
        raise HTTPException(403, "Active workspace membership required")
    # Authentication permits all defined roles. Each endpoint checks its
    # own authorization, so accountants can access financial operations.
    return TenantContext(tenant_id, user_id, member["role"], token)


async def wallet_risk_interceptor(
    shipment_id: UUID, request: Request,
    context: Annotated[TenantContext, Depends(authenticate)],
) -> BookingPermit:
    """Attach this dependency to the future label-purchase endpoint.

    The amount is read from the tenant's DB shipment, never request input.
    Do not attach this dependency to a read-only preview endpoint: it reserves
    funds and marks the shipment BOOKING before returning.
    """
    try:
        return await request.app.state.finance.reserve(context, shipment_id)
    except asyncpg.PostgresError:
        logger.error("Wallet reservation DB failure tenant=%s shipment=%s", context.tenant_id, shipment_id)
        raise HTTPException(503, "Financial controls temporarily unavailable") from None


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "mode": "local-preview" if request.app.state.local_preview else "configured"}


@app.get("/", include_in_schema=False)
async def frontend():
    return FileResponse(Path(__file__).with_name("index.html"), media_type="text/html")


@app.get("/api/v1/config")
async def public_config(request: Request):
    if request.app.state.local_preview:
        return {"mode": "local-preview", "supabase_url": None, "publishable_key": None}
    settings = request.app.state.settings
    return {"mode": "configured", "supabase_url": settings.supabase_url,
            "publishable_key": settings.supabase_publishable_key.get_secret_value()}


@app.post("/v1/rates", response_model=RatingResponse)
async def get_rates(body: RatingRequest, request: Request,
                    context: Annotated[TenantContext, Depends(authenticate)]) -> RatingResponse:
    if context.role not in DISPATCH_ROLES:
        raise HTTPException(403, "Dispatch permission required")
    try:
        result = await request.app.state.rating.quote(context, body)
        if context.role == 'DISPATCHER':
            result = result.model_copy(update={'rates': [rate.model_copy(update={'fee_breakdown': {'source': 'financial_role_required'}}) for rate in result.rates]})
        return result
    except HTTPException:
        raise
    except Exception:
        logger.error("Rating processing failure tenant=%s", context.tenant_id)
        raise HTTPException(503, "Rating service temporarily unavailable") from None


@app.post("/v1/wallet/topups", response_model=TopupResponse)
async def create_wallet_topup(body: TopupRequest, request: Request,
                              context: Annotated[TenantContext, Depends(authenticate)]) -> TopupResponse:
    if context.role not in FINANCE_ROLES:
        raise HTTPException(403, "Financial permission required")
    try:
        return await request.app.state.finance.create_checkout(context, body)
    except asyncpg.PostgresError:
        logger.error("Top-up DB failure tenant=%s", context.tenant_id)
        raise HTTPException(503, "Top-up service temporarily unavailable") from None


async def limited_body(request: Request, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise HTTPException(413, "Webhook payload too large")
    return bytes(body)


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict[str, bool]:
    settings = request.app.state.settings
    if not settings.stripe_enabled:
        raise HTTPException(503, "Stripe integration is disabled")
    signatures = request.headers.getlist("stripe-signature")
    signature = signatures[0] if len(signatures)==1 else None
    if not signature:
        raise HTTPException(400, "Missing Stripe signature")
    raw = await limited_body(request, MAX_WEBHOOK_BYTES)
    try:
        # Verify original bytes; do not parse/re-serialize before verification.
        event = stripe.Webhook.construct_event(raw, signature,
                    settings.stripe_webhook_secret.get_secret_value(), tolerance=300)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid Stripe webhook signature") from None
    if event.get("livemode") is not settings.stripe_livemode:
        raise HTTPException(400, "Stripe environment mismatch")
    if event.get("type") not in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        return {"received": True, "credited": False}
    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id.startswith("evt_"):
        raise HTTPException(400, "Invalid event identifier")
    try:
        session = event["data"]["object"].to_dict_recursive()
        credited = await request.app.state.finance.credit_session(event_id, session)
    except (ValueError, KeyError, TypeError):
        logger.error("Stripe wallet validation failure event=%s", event_id)
        raise HTTPException(409, "Wallet top-up reconciliation required") from None
    except asyncpg.PostgresError:
        logger.error("Stripe wallet DB failure event=%s", event_id)
        raise HTTPException(503, "Wallet credit temporarily unavailable") from None
    return {"received": True, "credited": credited}


from backend.payment_gateway import build_router as payment_gateway_router
app.include_router(payment_gateway_router(authenticate, TopupRequest, stripe_webhook))


@app.post("/webhooks/twilio/whatsapp")
async def inbound_whatsapp(request: Request) -> Response:
    settings = request.app.state.settings
    if not settings.twilio_enabled:
        raise HTTPException(503, "Twilio integration is disabled")
    form = await authenticated_twilio_form(request)
    sender, receiver = PHONE_PATTERN.fullmatch(form["From"]), PHONE_PATTERN.fullmatch(form["To"])
    try:
        async with asyncio.timeout(settings.whatsapp_deadline_seconds):
            context = await request.app.state.whatsapp.resolve_sender(sender.group(1), receiver.group(1))
            if context is None:
                return xml_response(twiml("This number is not registered for EasyInvio.com dispatch.\n"
                    "Ask your workspace owner to verify and register your WhatsApp number, then resend."))
            if form.get("NumMedia", "0") != "0":
                return xml_response(twiml("Please send text: Quote 4.5kg from GBR to USA"))
            return xml_response(await request.app.state.whatsapp.process(context, form["MessageSid"], form["Body"], sender.group(1)))
    except TimeoutError:
        return xml_response(twiml("The carriers did not respond quickly enough. Please resend shortly."))
    except HTTPException as exc:
        text = ("Live rates are temporarily unavailable. Please try again." if exc.status_code == 503
                else "This quote could not be processed. Contact your workspace admin.")
        return xml_response(twiml(text))
    except (ValueError, ValidationError, asyncpg.PostgresError):
        logger.error("WhatsApp route or DB processing failure")
        return xml_response(twiml("Ask your workspace admin to check the saved route and carrier configuration."))


@app.get("/v1/whatsapp/quote-choice")
async def resolve_quote_choice(token: str, request: Request,
                               context: Annotated[TenantContext, Depends(authenticate)]) -> dict[str, Any]:
    if context.role not in DISPATCH_ROLES:
        raise HTTPException(403, "Dispatch permission required")
    if len(token) > 2048:
        raise HTTPException(400, "Invalid quote token")
    try:
        claims = jwt.decode(token, request.app.state.settings.quote_link_secret.get_secret_value(),
            algorithms=["HS256"], issuer="veloce-whatsapp", audience="veloce-booking",
            options={"require": ["sub", "t", "q", "iat", "exp"]})
        tenant_id, user_id, choice_id = UUID(claims["t"]), UUID(claims["sub"]), UUID(claims["q"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(410, "Quote link is invalid or expired") from None
    if tenant_id != context.tenant_id or user_id != context.user_id:
        raise HTTPException(403, "Quote belongs to another workspace or user")
    async with request.app.state.finance.pool.acquire() as connection:
        async with connection.transaction():
            await rls_context(connection, context)
            row = await connection.fetchrow(
                """SELECT rating_request,selected_rate,expires_at FROM public.whatsapp_quote_choices
                   WHERE tenant_id=$1 AND auth_user_id=$2 AND id=$3 AND expires_at>now()""",
                context.tenant_id, context.user_id, choice_id,
            )
    if row is None:
        raise HTTPException(410, "Quote is unavailable or expired")
    # GET only resolves a quote. It never purchases labels or debits wallets.
    return {
        "rating_request": RatingRequest.model_validate(decode_json(row["rating_request"])).model_dump(mode="json"),
        "selected_rate": ClientRate.model_validate(decode_json(row["selected_rate"])).model_dump(mode="json"),
        "expires_at": row["expires_at"].isoformat(),
    }


from backend.ai_engine import build_router as ai_router
from backend.advanced_logistics import build_router as logistics_router
app.include_router(ai_router(authenticate))
app.include_router(logistics_router(authenticate, RatingRequest))
app.include_router(admin_router)
from backend.admin_management import router as admin_management_router
app.include_router(admin_management_router)
app.include_router(sandbox_router(authenticate, RatingRequest))
app.include_router(ecommerce_router(authenticate))
app.include_router(hubspot_router(authenticate))
app.include_router(tracking_router(authenticate))
app.include_router(support_delivery_router(authenticate))
app.include_router(dashboard_router(authenticate))
app.include_router(automation_router(authenticate))
app.include_router(dispatch_workspace_router(authenticate))


def verify_local_logic() -> None:
    """Offline assertions for financial precision, matching and webhook parsing."""
    now, tenant_id, account_id = datetime.now(timezone.utc), uuid4(), uuid4()
    request = RatingRequest(
        origin=Address(name="Sender", line1="1 High Street", city="Leeds", postal_code="LS1 1AA", country_code="GB"),
        destination=Address(name="Recipient", line1="2 High Street", city="London", postal_code="SW1A 1AA", country_code="GB"),
        dimensions=[Dimensions(length_cm="30", width_cm="20", height_cm="10")],
        weights_kg=["2.000"], currency="GBP",
    )
    rate = WholesaleRate(provider="EASYPOST", account_id=account_id,
        upstream_shipment_id="fixture-shipment", upstream_rate_id="fixture-rate",
        carrier_code="DHL", service_code="EXPRESS", currency="GBP", wholesale_cost=Decimal("10.00"))
    evaluator = MarginEvaluator()
    assert evaluator.evaluate(tenant_id, request, rate, [], now).client_price == Decimal("12.00")
    base = {"id": uuid4(), "tenant_id": tenant_id, "currency": "GBP", "markup_type": "PERCENTAGE",
            "markup_value": Decimal("15"), "minimum_markup": ZERO, "priority": 100,
            "is_active": True, "valid_from": now, "created_at": now}
    percentage = MarginRule.model_validate(base)
    assert evaluator.evaluate(tenant_id, request, rate, [percentage], now).client_price == Decimal("11.50")
    flat = MarginRule.model_validate({**base, "id": uuid4(), "markup_type": "FLAT_RATE",
                                     "markup_value": Decimal("3.25"), "priority": 1})
    assert evaluator.evaluate(tenant_id, request, rate, [percentage, flat], now).client_price == Decimal("13.25")
    foreign = MarginRule.model_validate({**base, "tenant_id": uuid4(), "priority": 0, "markup_value": ZERO})
    assert evaluator.evaluate(tenant_id, request, rate, [foreign], now).client_price == Decimal("12.00")
    excluded = MarginRule.model_validate({**base, "max_weight_kg": Decimal("2.000")})
    assert evaluator.evaluate(tenant_id, request, rate, [excluded], now).client_price == Decimal("12.00")
    specific = MarginRule.model_validate({**base, "id": uuid4(), "carrier_code": "DHL", "markup_value": Decimal("30")})
    assert evaluator.evaluate(tenant_id, request, rate, [percentage, specific], now).client_price == Decimal("13.00")
    expired = MarginRule.model_validate({**base, "valid_from": now - timedelta(hours=2),
                                        "valid_until": now - timedelta(hours=1)})
    assert evaluator.evaluate(tenant_id, request, rate, [expired], now).client_price == Decimal("12.00")
    assert from_minor_units(12345, "GBP") == Decimal("123.45")
    assert to_minor_units(Decimal("123.45"), "GBP") == 12345
    try:
        from_minor_units(True, "GBP")
        raise AssertionError("Boolean minor units accepted")
    except ValueError:
        pass
    parsed = parse_quote("Quote 4.5kg from GBR to USA route EXPORT_US")
    assert parsed == ParsedQuote(Decimal("4.5"), "GB", "US", "EXPORT_US")
    for invalid in ("Quote 0kg from GBR to USA", "Quote 4kg from XYZ to USA", "Quote -2kg from GB to US"):
        try:
            parse_quote(invalid)
            raise AssertionError("Invalid quote accepted")
        except ValueError:
            pass
    from xml.etree import ElementTree
    text = "Rate & Service <Express> https://app.easyinvio.com/book?t=1&quote=2"
    assert ElementTree.fromstring(twiml(text)).find("Message").text == text
    key = Fernet.generate_key().decode()
    encrypted = encrypt_carrier_credentials(tenant_id, account_id, "fixture-secret", key)
    envelope = parse_json(Fernet(key.encode()).decrypt(bytes.fromhex(encrypted[2:])))
    assert envelope["tenant_id"] == str(tenant_id) and envelope["account_id"] == str(account_id)
    print("Local checks passed: Decimal pricing, rule isolation/priority, currency conversion, ISO parsing, XML and encryption.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if "--self-test" in sys.argv:
        verify_local_logic()
    else:
        from dotenv import load_dotenv
        load_dotenv(override=False)
        import uvicorn
        # Loopback is appropriate for local VS Code development. Deploy
        # behind an HTTPS reverse proxy with explicit hosting configuration.
        uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
