"""Platform-owner administration and database-backed tenant pricing.

Uses the application's trusted asyncpg pool. Platform permissions come from
server configuration, never from customer roles or client-supplied metadata.
Call get_client_calibrated_rate with await; PostgreSQL access is asynchronous.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import contextmanager, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, localcontext
from typing import Any, Iterator, Literal
from uuid import UUID, uuid4

import asyncpg
import jwt
import pycountry
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.ai_engine import country_code, strict_decimal
from backend.workspace_personas import PersonalProfile, storage_profile, individual_policy

logger = logging.getLogger("veloce.admin")
CENT = Decimal("0.01")
ZERO = Decimal("0")
DEFAULT_MARKUP_PERCENT = Decimal("20")
Currency = Literal["GBP", "EUR", "USD"]
BillingPlan = Literal["PREPAID_WALLET", "POSTPAID_30_DAY"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def printable(value: str) -> str:
    value = value.strip()
    if not value or any(ord(character) < 32 for character in value):
        raise ValueError("Enter nonblank text without control characters")
    return value


class CompanyProfile(InputModel):
    phone_e164: str | None = Field(default=None, pattern=r'^\+[1-9][0-9]{7,14}$')
    company_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=200)
    billing_email: str = Field(max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    address_line1: str = Field(min_length=1, max_length=200)
    address_line2: str | None = Field(default=None, min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=1, max_length=30)
    country_code: str
    company_registration_number: str | None = Field(default=None, min_length=1, max_length=100)
    tax_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("company_name", "contact_name", "address_line1", "address_line2", "city", "postal_code", "company_registration_number", "tax_id")
    @classmethod
    def trim_text(cls, value):
        return printable(value) if value is not None else None

    @field_validator("country_code")
    @classmethod
    def normalize_country(cls, value):
        return country_code(value)


class TenantCreate(InputModel):
    # Supply the same request_id when retrying to avoid duplicate accounts.
    request_id: UUID = Field(default_factory=uuid4)
    company_profile: CompanyProfile | PersonalProfile
    workspace_type: Literal["BUSINESS", "INDIVIDUAL"] = "BUSINESS"
    billing_plan: BillingPlan
    default_currency: Currency = "GBP"
    owner_auth_user_id: UUID | None = None
    stripe_customer_id: str | None = Field(default=None, pattern=r"^cus_[A-Za-z0-9]{1,100}$")
    is_sandbox: bool = False


    @model_validator(mode="after")
    def persona_profile(self):
        if (self.workspace_type == 'INDIVIDUAL') != isinstance(self.company_profile, PersonalProfile):
            raise ValueError('The profile must match the selected account type')
        return self


class TenantCreated(InputModel):
    request_id: UUID
    tenant_id: UUID
    company_profile: CompanyProfile | PersonalProfile
    workspace_type: Literal["BUSINESS", "INDIVIDUAL"] = "BUSINESS"
    billing_plan: BillingPlan
    default_currency: Currency
    workspace_status: Literal["ACTIVE"] = "ACTIVE"
    billing_status: Literal["ACTIVE"] = "ACTIVE"
    owner_auth_user_id: UUID | None
    wallet_provisioned: bool = True
    is_sandbox: bool = False


class MarginCreate(InputModel):
    request_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    destination_country: str | None = None
    origin_country: str | None = None
    billing_plan: BillingPlan | None = None
    cargo_type: Literal['LETTER','PARCEL','PALLET','OVERLAND_FREIGHT'] | None = None
    min_volume_m3: Decimal | None = Field(default=None, ge=0, le=100000, decimal_places=9)
    max_volume_m3: Decimal | None = Field(default=None, gt=0, le=100000, decimal_places=9)
    carrier_code: str | None = Field(default=None, min_length=1, max_length=100)
    service_code: str | None = Field(default=None, min_length=1, max_length=100)
    carrier_account_id: UUID | None = None
    currency: Currency | None = None
    markup_type: Literal["PERCENTAGE", "FLAT_RATE"]
    markup_value: Decimal = Field(ge=0, le=1000000, decimal_places=6)
    minimum_markup: Decimal = Field(default=ZERO, ge=0, le=1000000, decimal_places=2)
    maximum_markup: Decimal | None = Field(default=None, ge=0, le=1000000, decimal_places=2)
    min_weight_kg: Decimal | None = Field(default=None, ge=0, le=1000, decimal_places=3)
    max_weight_kg: Decimal | None = Field(default=None, gt=0, le=1000, decimal_places=3)
    min_wholesale_cost: Decimal | None = Field(default=None, ge=0, le=1000000, decimal_places=2)
    max_wholesale_cost: Decimal | None = Field(default=None, gt=0, le=1000000, decimal_places=2)
    priority: int = Field(default=100, ge=0, le=1000000)
    is_active: bool = True
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @field_validator("markup_value", "minimum_markup", "maximum_markup", "min_weight_kg", "max_weight_kg", "min_wholesale_cost", "max_wholesale_cost", "min_volume_m3", "max_volume_m3", mode="before")
    @classmethod
    def exact_decimals(cls, value):
        return strict_decimal(value) if value is not None else None

    @field_validator("priority", mode="before")
    @classmethod
    def integer_priority(cls, value):
        if type(value) is not int:
            raise ValueError("Priority must be an integer")
        return value

    @field_validator("is_active", mode="before")
    @classmethod
    def boolean_active(cls, value):
        if type(value) is not bool:
            raise ValueError("is_active must be a boolean")
        return value

    @field_validator("carrier_code", "service_code")
    @classmethod
    def normalize_codes(cls, value):
        return printable(value).upper() if value is not None else None

    @field_validator("destination_country", "origin_country")
    @classmethod
    def normalize_countries(cls, value):
        return country_code(value) if value is not None else None

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.markup_type == 'PERCENTAGE' and self.markup_value >= Decimal('500'):
            raise ValueError('Markup of 500% or greater requires a pricing policy review; use a value below 500%')
        if self.markup_type == "FLAT_RATE" and self.markup_value != self.markup_value.quantize(CENT):
            raise ValueError("FLAT_RATE requires at most two decimal places")
        if self.maximum_markup is not None and self.maximum_markup < self.minimum_markup:
            raise ValueError("maximum_markup cannot be below minimum_markup")
        for low, high in ((self.min_weight_kg, self.max_weight_kg), (self.min_wholesale_cost, self.max_wholesale_cost), (self.min_volume_m3, self.max_volume_m3)):
            if low is not None and high is not None and high <= low:
                raise ValueError("Upper bounds must exceed lower bounds (upper bound is exclusive)")
        for timestamp in (self.valid_from, self.valid_until):
            if timestamp is not None and timestamp.tzinfo is None:
                raise ValueError("Validity timestamps require a timezone")
        if self.valid_until is not None and self.valid_until <= (self.valid_from or datetime.now(timezone.utc)):
            raise ValueError("valid_until must be after valid_from")
        return self


class MarginCreated(InputModel):
    request_id: UUID
    id: UUID
    tenant_id: UUID
    destination_country: str | None
    carrier_code: str | None
    currency: Currency
    markup_type: Literal["PERCENTAGE", "FLAT_RATE"]
    markup_value: Decimal
    priority: int
    is_active: bool
    valid_from: datetime
    valid_until: datetime | None


@dataclass(frozen=True)
class PlatformOwner:
    user_id: UUID
    role: str = "SUPER_ADMIN"


admin_bearer = HTTPBearer(auto_error=False)


async def verified_platform_identity(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(admin_bearer),
) -> UUID:
    if getattr(request.app.state, "local_preview", False):
        raise HTTPException(503, "Platform administration requires configured database/authentication")
    unauthorized = HTTPException(401, "Invalid or expired authentication token", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None or credentials.scheme.lower() != "bearer" or len(credentials.credentials) > 16000:
        raise unauthorized
    settings = request.app.state.settings
    try:
        token = credentials.credentials
        from backend.identity import unwrap_app_session
        token = await unwrap_app_session(request, token)
        header = jwt.get_unverified_header(token)
        if header.get("alg") != settings.jwt_algorithm or not isinstance(header.get("kid"), str):
            raise unauthorized
        signing_key = await asyncio.to_thread(request.app.state.jwks.get_signing_key_from_jwt, token)
        claims = jwt.decode(token, signing_key.key, algorithms=[settings.jwt_algorithm],
                            audience=settings.jwt_audience, issuer=f"{settings.supabase_url}/auth/v1", leeway=5,
                            options={"require": ["sub", "role", "exp", "iat", "iss", "aud"]})
        if claims["role"] != "authenticated":
            raise unauthorized
        bound_session = getattr(request.state, "app_session_claims", None)
        if bound_session and bound_session["user_id"] != claims["sub"]: raise unauthorized
        user_id = UUID(claims["sub"])
    except HTTPException:
        raise
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise unauthorized from None
    request.state.platform_auth_claims = claims
    return user_id


async def authenticate_platform_owner(request: Request, credentials=Depends(admin_bearer)) -> PlatformOwner:
    user_id = await verified_platform_identity(request, credentials)
    if user_id not in set(getattr(request.app.state.settings, 'platform_admin_user_ids', [])):
        raise HTTPException(403, 'Platform-owner permission required')
    return PlatformOwner(user_id)


async def authenticate_platform_operator(request: Request, credentials=Depends(admin_bearer)) -> PlatformOwner:
    user_id = await verified_platform_identity(request, credentials)
    settings = request.app.state.settings
    if user_id in set(getattr(settings, 'platform_admin_user_ids', [])):
        return PlatformOwner(user_id)
    from backend.platform_staff import platform_role
    finance = getattr(request.app.state, 'finance', None)
    role = None
    if finance is not None:
        async with finance.pool.acquire() as connection:
            role = await platform_role(connection, settings, user_id)
    if role != 'AGENT':
        raise HTTPException(403, 'EasyInvio platform staff permission required')
    return PlatformOwner(user_id, role)


def decode_json(value):
    return json.loads(value) if isinstance(value, str) else value


class AdminService:
    def __init__(self, pool: Any):
        self.pool = pool

    @staticmethod
    def fingerprint(body: InputModel) -> str:
        canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def replay(self, connection, actor: PlatformOwner, operation: str, body: InputModel):
        key = f"{actor.user_id}:{operation}:{body.request_id}"
        await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", key)
        row = await connection.fetchrow(
            """SELECT payload_sha256,response FROM public.admin_configuration_events
               WHERE actor_auth_user_id=$1 AND operation=$2 AND request_id=$3""",
            actor.user_id, operation, body.request_id)
        if row is not None:
            if row["payload_sha256"] != self.fingerprint(body):
                raise HTTPException(409, "request_id already used with different configuration")
            return decode_json(row["response"])
        return None

    async def audit(self, connection, actor: PlatformOwner, operation: str, body: InputModel, response: InputModel):
        await connection.execute(
            """INSERT INTO public.admin_configuration_events
               (id,actor_auth_user_id,operation,request_id,tenant_id,payload_sha256,response)
               VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)""",
            uuid4(), actor.user_id, operation, body.request_id, response.tenant_id,
            self.fingerprint(body), response.model_dump_json())

    async def create_tenant(self, body: TenantCreate, actor: PlatformOwner) -> TenantCreated:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                replay = await self.replay(connection, actor, "CREATE_TENANT", body)
                if replay is not None:
                    return TenantCreated.model_validate(replay)
                if body.owner_auth_user_id is not None and not await connection.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM auth.users WHERE id=$1)", body.owner_auth_user_id):
                    raise HTTPException(422, "owner_auth_user_id must identify an existing Supabase Auth user")
                tenant_id = uuid4()
                profile = storage_profile(body.company_profile)
                await connection.execute(
                    """INSERT INTO public.tenants
                       (tenant_id,company_name,company_profile,billing_plan,default_currency,
                        workspace_status,billing_status,stripe_customer_id,is_sandbox,
                        workspace_slug,workspace_name,legal_company_name,billing_email,billing_address,
                        country_code,company_registration_number,vat_registration_number,workspace_type)
                       VALUES ($1,$2,$3::jsonb,$4,$5,'ACTIVE','ACTIVE',$6,$7,
                               $8,$2,CASE WHEN $14='BUSINESS' THEN $2 END,$9,$10::jsonb,$11,$12,$13,$14)""",
                    tenant_id, profile.company_name, profile.model_dump_json(),
                    body.billing_plan, body.default_currency, body.stripe_customer_id, body.is_sandbox,
                    "tenant-" + tenant_id.hex, profile.billing_email,
                    json.dumps({"line1": profile.address_line1,
                                "line2": profile.address_line2, "city": profile.city,
                                "postal_code": profile.postal_code, "country_code": profile.country_code}),
                    profile.country_code, profile.company_registration_number,
                    profile.tax_id, body.workspace_type)
                await connection.execute(
                    """INSERT INTO public.wallets (tenant_id,currency,balance,reserved_balance)
                       VALUES ($1,$2,0,0) ON CONFLICT (tenant_id) DO NOTHING""", tenant_id, body.default_currency)
                # Support schemas which provision a wallet in a tenant trigger.
                wallet = await connection.fetchrow(
                    "SELECT currency FROM public.wallets WHERE tenant_id=$1 FOR SHARE", tenant_id)
                if wallet is None or wallet["currency"] != body.default_currency:
                    raise HTTPException(409, "Provisioned wallet currency does not match the tenant")
                if body.owner_auth_user_id is not None:
                    await connection.execute(
                        """INSERT INTO public.users (id,tenant_id,auth_user_id,role,is_active)
                           VALUES ($1,$2,$3,'OWNER',true)""", uuid4(), tenant_id, body.owner_auth_user_id)
                response = TenantCreated(request_id=body.request_id, tenant_id=tenant_id,
                                         company_profile=body.company_profile, billing_plan=body.billing_plan,
                                         default_currency=body.default_currency, owner_auth_user_id=body.owner_auth_user_id,
                                         is_sandbox=body.is_sandbox,workspace_type=body.workspace_type)
                await self.audit(connection, actor, "CREATE_TENANT", body, response)
                return response

    async def create_margin(self, body: MarginCreate, actor: PlatformOwner) -> MarginCreated:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                replay = await self.replay(connection, actor, "CREATE_MARGIN", body)
                if replay is not None:
                    return MarginCreated.model_validate(replay)
                tenant = await connection.fetchrow(
                    "SELECT default_currency FROM public.tenants WHERE tenant_id=$1 FOR SHARE", body.tenant_id)
                if tenant is None:
                    raise HTTPException(404, "Target tenant does not exist")
                if body.carrier_account_id is not None and not await connection.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM public.carrier_accounts WHERE tenant_id=$1 AND id=$2)",
                    body.tenant_id, body.carrier_account_id):
                    raise HTTPException(422, "Carrier account must belong to the target tenant")
                currency = body.currency or tenant["default_currency"]
                rule_id, valid_from = uuid4(), body.valid_from or datetime.now(timezone.utc)
                if body.valid_until is not None and body.valid_until <= valid_from:
                    raise HTTPException(422, "Rule validity has already expired")
                await connection.execute(
                    """INSERT INTO public.margin_rules
                       (id,tenant_id,carrier_account_id,carrier_code,service_code,origin_country,
                        destination_country,currency,min_weight_kg,max_weight_kg,min_wholesale_cost,
                        max_wholesale_cost,markup_type,markup_value,minimum_markup,maximum_markup,
                        priority,is_active,valid_from,valid_until,created_at,rule_name,billing_plan,cargo_type,min_volume_m3,max_volume_m3)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26)""",
                    rule_id, body.tenant_id, body.carrier_account_id, body.carrier_code, body.service_code,
                    body.origin_country, body.destination_country, currency, body.min_weight_kg, body.max_weight_kg,
                    body.min_wholesale_cost, body.max_wholesale_cost, 'FIXED' if body.markup_type == 'FLAT_RATE' else body.markup_type, body.markup_value,
                    body.minimum_markup, body.maximum_markup, body.priority, body.is_active,
                    valid_from, body.valid_until, datetime.now(timezone.utc),f'Calibrated {body.markup_type} {str(rule_id)[:8]}',
                    body.billing_plan,body.cargo_type,body.min_volume_m3,body.max_volume_m3)
                response = MarginCreated(request_id=body.request_id, id=rule_id, tenant_id=body.tenant_id,
                                         destination_country=body.destination_country, carrier_code=body.carrier_code,
                                         currency=currency, markup_type=body.markup_type, markup_value=body.markup_value,
                                         priority=body.priority, is_active=body.is_active,
                                         valid_from=valid_from, valid_until=body.valid_until)
                await self.audit(connection, actor, "CREATE_MARGIN", body, response)
                return response


@dataclass(frozen=True)
class PricingScope:
    pool: Any
    currency: str | None = None
    origin: str | None = None
    carrier_account_id: UUID | None = None
    service_code: str | None = None
    weight_kg: Decimal | None = None
    quoted_at: datetime | None = None
    cargo_type: str | None = None
    volume_m3: Decimal | None = None
    persona_policy: dict | None = None


_scope: ContextVar[PricingScope | None] = ContextVar("veloce_pricing_scope", default=None)
_borrowed_connection: ContextVar[Any] = ContextVar("veloce_borrowed_pricing_connection", default=None)
_pool: Any = None


def configure_pricing_pool(pool: Any) -> None:
    """Bind during application startup; clear with None during shutdown."""
    global _pool
    _pool = pool


@contextmanager
def borrowed_pricing_connection(connection: Any) -> Iterator[None]:
    """Reuse a trusted caller-owned transaction; never acquire a second slot."""
    token = _borrowed_connection.set(connection)
    try:
        yield
    finally:
        _borrowed_connection.reset(token)


@asynccontextmanager
async def pricing_read_connection(scope: PricingScope):
    existing = _borrowed_connection.get()
    if existing is not None:
        yield existing
    else:
        async with scope.pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                yield connection


@contextmanager
def calibrated_pricing_scope(pool: Any, **kwargs) -> Iterator[None]:
    """Task-local optional selectors preserve rich existing pricing rules."""
    scope = PricingScope(pool=pool, **kwargs)
    if scope.currency is not None and scope.currency not in ("GBP", "EUR", "USD"):
        raise ValueError("Unsupported currency")
    if scope.quoted_at is not None and scope.quoted_at.tzinfo is None:
        raise ValueError("quoted_at requires a timezone")
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)


def country_aliases(value: str) -> list[str]:
    code = country_code(value)
    return [code, pycountry.countries.get(alpha_2=code).alpha_3]


def validate_wholesale_cost(base: Decimal) -> None:
    if not isinstance(base, Decimal) or not base.is_finite() or not ZERO <= base < Decimal("1000000000000"):
        raise ValueError("Wholesale cost must be a finite, nonnegative Decimal below 1e12")


def calculate_calibrated_price(base: Decimal, rule: Any | None) -> Decimal:
    """Preserve existing fallback, clamp and rounding semantics."""
    validate_wholesale_cost(base)
    with localcontext() as context:
        context.prec = 50
        wholesale = base.quantize(CENT, rounding=ROUND_CEILING)
        if rule is None:
            markup = (wholesale * DEFAULT_MARKUP_PERCENT / 100).quantize(CENT, rounding=ROUND_CEILING)
        else:
            value = strict_decimal(rule["markup_value"])
            minimum = strict_decimal(rule.get("minimum_markup", ZERO))
            maximum = strict_decimal(rule["maximum_markup"]) if rule.get("maximum_markup") is not None else None
            if value < 0 or minimum < 0 or (maximum is not None and maximum < minimum):
                raise ValueError("Invalid stored markup bounds")
            if rule["markup_type"] == "PERCENTAGE":
                raw = wholesale * value / 100
            elif rule["markup_type"] in ("FLAT_RATE", "FIXED"):
                raw = value
            else:
                raise ValueError("Unsupported stored markup type")
            raw = max(raw, minimum)
            if maximum is not None:
                raw = min(raw, maximum)
            markup = raw.quantize(CENT, rounding=ROUND_HALF_UP)
            if markup < minimum:
                markup = minimum.quantize(CENT, rounding=ROUND_CEILING)
            if maximum is not None and markup > maximum:
                raise ValueError("Stored bounds cannot be represented in currency")
        final = (wholesale + markup).quantize(CENT, rounding=ROUND_HALF_UP)
        if final >= Decimal("1000000000000"):
            raise ValueError("Final price exceeds supported limit")
        return final


async def get_client_calibrated_rate(
    tenant_id: UUID, base_wholesale_cost: Decimal, carrier: str, destination: str,
) -> Decimal:
    """Query the highest-priority tenant rule and return final customer price.

    Lower priority numbers win. Equal priority: more selectors, then oldest
    creation time, then UUID. Missing rules use the established 20% fallback.
    Without a pricing scope, currency comes from the tenant's default and
    rules needing unavailable account/service/origin/weight details cannot match.
    """
    if not isinstance(tenant_id, UUID):
        raise ValueError("tenant_id must be a UUID")
    validate_wholesale_cost(base_wholesale_cost)
    carrier = printable(carrier).upper()
    if len(carrier) > 100:
        raise ValueError("Carrier code is limited to 100 characters")
    destinations = country_aliases(destination)
    scope = _scope.get() or PricingScope(pool=_pool)
    if scope.pool is None and _borrowed_connection.get() is None:
        raise RuntimeError("Configure the pricing database pool during startup")
    origins = country_aliases(scope.origin) if scope.origin is not None else None
    try:
        async with pricing_read_connection(scope) as connection:
            tenant = await connection.fetchrow(
                "SELECT default_currency,workspace_status,billing_plan,workspace_type FROM public.tenants WHERE tenant_id=$1", tenant_id)
            if tenant is None:
                raise HTTPException(404, "Tenant not found")
            if tenant["workspace_status"] != "ACTIVE":
                raise HTTPException(403, "Active workspace required")
            currency = scope.currency or tenant["default_currency"]
            if currency not in ("GBP", "EUR", "USD"):
                raise ValueError("Unsupported tenant currency")
            if tenant.get('workspace_type', 'BUSINESS') == 'INDIVIDUAL':
                policy = scope.persona_policy or await individual_policy(connection)
                return calculate_calibrated_price(base_wholesale_cost, {
                    'markup_type': 'PERCENTAGE', 'markup_value': strict_decimal(policy['markup_percent']),
                    'minimum_markup': ZERO})
            rule = await connection.fetchrow(
                """SELECT * FROM public.margin_rules
                   WHERE tenant_id=$1 AND currency=$2 AND is_active=true
                   AND (carrier_code IS NULL OR upper(carrier_code)=$3)
                   AND (destination_country IS NULL OR upper(destination_country)=ANY($4::text[]))
                   AND (carrier_account_id IS NULL OR carrier_account_id=$5::uuid)
                   AND (origin_country IS NULL OR upper(origin_country)=ANY($6::text[]))
                   AND (service_code IS NULL OR upper(service_code)=$7::text)
                   AND (min_weight_kg IS NULL OR ($8::numeric IS NOT NULL AND $8>=min_weight_kg))
                   AND (max_weight_kg IS NULL OR ($8::numeric IS NOT NULL AND $8<max_weight_kg))
                   AND (min_wholesale_cost IS NULL OR $9::numeric>=min_wholesale_cost)
                   AND (max_wholesale_cost IS NULL OR $9::numeric<max_wholesale_cost)
                   AND valid_from <= $10 AND (valid_until IS NULL OR valid_until > $10)
                   AND (billing_plan IS NULL OR billing_plan=$11::text)
                   AND (cargo_type IS NULL OR cargo_type=$12::text)
                   AND (min_volume_m3 IS NULL OR ($13::numeric IS NOT NULL AND $13>=min_volume_m3))
                   AND (max_volume_m3 IS NULL OR ($13::numeric IS NOT NULL AND $13<max_volume_m3))
                   ORDER BY priority ASC,
                     ((carrier_account_id IS NOT NULL)::int + (carrier_code IS NOT NULL)::int +
                      (service_code IS NOT NULL)::int + (origin_country IS NOT NULL)::int +
                      (destination_country IS NOT NULL)::int + (min_weight_kg IS NOT NULL)::int +
                      (max_weight_kg IS NOT NULL)::int + (min_wholesale_cost IS NOT NULL)::int +
                      (max_wholesale_cost IS NOT NULL)::int + (billing_plan IS NOT NULL)::int +
                      (cargo_type IS NOT NULL)::int + (min_volume_m3 IS NOT NULL)::int +
                      (max_volume_m3 IS NOT NULL)::int) DESC,
                     created_at ASC,id ASC LIMIT 1""",
                tenant_id, currency, carrier, destinations, scope.carrier_account_id, origins,
                printable(scope.service_code).upper() if scope.service_code is not None else None,
                scope.weight_kg, base_wholesale_cost, scope.quoted_at or datetime.now(timezone.utc),
                tenant.get('billing_plan'), scope.cargo_type, scope.volume_m3)
            if rule is not None and rule["tenant_id"] != tenant_id:
                raise ValueError("Stored pricing tenant mismatch")
            return calculate_calibrated_price(base_wholesale_cost, rule)
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError, ArithmeticError):
        logger.error("Calibrated pricing unavailable tenant=%s", tenant_id)
        raise HTTPException(503, "Tenant pricing unavailable; check schema and margin configuration") from None


router = APIRouter(prefix="/api/v1/admin", tags=["Platform administration"])


def service_for(request: Request) -> AdminService:
    service = getattr(request.app.state, "admin_portal", None)
    if service is None:
        raise HTTPException(503, "Platform administration is not configured")
    return service


def database_error(exc: Exception) -> HTTPException:
    if isinstance(exc, asyncpg.InsufficientPrivilegeError):
        return HTTPException(403, 'Credential identity is locked. Sign in again as a platform administrator and use a replacement connection.')
    if isinstance(exc, asyncpg.UniqueViolationError):
        return HTTPException(409, "Configuration conflicts with an existing record")
    if isinstance(exc, (asyncpg.ForeignKeyViolationError, asyncpg.CheckViolationError)):
        return HTTPException(422, "Configuration violates a database relationship or constraint")
    logger.error("Admin database operation failed type=%s", type(exc).__name__)
    return HTTPException(503, "Admin database unavailable; check migration 007 and schema compatibility")


@router.post("/tenants", response_model=TenantCreated, status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreate, request: Request, actor: PlatformOwner = Depends(authenticate_platform_operator)):
    # Agents may onboard a new client, but cannot attach staff/root identities or
    # move an existing customer's identity into another business.
    if actor.role == 'AGENT' and body.owner_auth_user_id is not None:
        from backend.platform_staff import platform_role
        async with request.app.state.finance.pool.acquire() as connection:
            staff = await platform_role(connection, request.app.state.settings, body.owner_auth_user_id)
            enrolled = await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)', body.owner_auth_user_id)
        if staff or enrolled:
            raise HTTPException(409, 'Use a new customer identity for onboarding; existing identities require platform-owner review')
    try:
        return await service_for(request).create_tenant(body, actor)
    except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
        raise database_error(exc) from None


@router.post("/margins", response_model=MarginCreated, status_code=status.HTTP_201_CREATED)
async def create_margin(body: MarginCreate, request: Request, actor: PlatformOwner = Depends(authenticate_platform_owner)):
    try:
        return await service_for(request).create_margin(body, actor)
    except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
        raise database_error(exc) from None


class IndividualPricingUpdate(InputModel):
    request_id: UUID = Field(default_factory=uuid4)
    expected_version: int = Field(ge=0)
    individual_global_markup_percent: Decimal = Field(ge=0, le=Decimal('999.99'), decimal_places=2)

    @field_validator('individual_global_markup_percent', mode='before')
    @classmethod
    def fixed_point(cls, value):
        return strict_decimal(value)


@router.get('/individual-pricing')
async def read_individual_pricing(request: Request, actor: PlatformOwner = Depends(authenticate_platform_owner)):
    async with service_for(request).pool.acquire() as connection:
        policy = await individual_policy(connection)
    return {'individual_global_markup_percent': policy['markup_percent'], 'version': policy['version']}


@router.put('/individual-pricing')
async def update_individual_pricing(body: IndividualPricingUpdate, request: Request,
                                    actor: PlatformOwner = Depends(authenticate_platform_owner)):
    async with service_for(request).pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('individual-pricing',0))")
            replay = await connection.fetchrow('SELECT * FROM public.individual_pricing_events WHERE actor_auth_user_id=$1 AND request_id=$2', actor.user_id, body.request_id)
            if replay:
                if replay['new_percent'] != body.individual_global_markup_percent or replay['previous_version'] != body.expected_version:
                    raise HTTPException(409, 'Request reference already used with different settings')
                return {'individual_global_markup_percent': str(replay['new_percent']), 'version': replay['version']}
            previous = await individual_policy(connection)
            if previous['version'] != body.expected_version:
                raise HTTPException(409, 'Pricing changed. Refresh settings before saving.')
            version = previous['version'] + 1
            await connection.execute('''INSERT INTO public.individual_pricing_settings(singleton,individual_global_markup_percent,version,updated_by)
                VALUES(true,$1,$2,$3) ON CONFLICT(singleton) DO UPDATE SET
                individual_global_markup_percent=excluded.individual_global_markup_percent,version=excluded.version,
                updated_by=excluded.updated_by,updated_at=now()''',body.individual_global_markup_percent,version,actor.user_id)
            await connection.execute('''INSERT INTO public.individual_pricing_events
                (actor_auth_user_id,request_id,previous_percent,new_percent,previous_version,version)
                VALUES($1,$2,$3,$4,$5,$6)''',actor.user_id,body.request_id,Decimal(previous['markup_percent']),
                body.individual_global_markup_percent,previous['version'],version)
    return {'individual_global_markup_percent': str(body.individual_global_markup_percent), 'version': version}
