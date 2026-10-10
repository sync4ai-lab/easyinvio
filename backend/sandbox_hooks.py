"""Real Stripe test-mode hooks and strict signed Twilio Sandbox requests."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import asyncpg
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import FormData

from backend.admin_portal import PlatformOwner, authenticate_platform_owner
from backend.ai_engine import strict_decimal

SANDBOX_NUMBER = "+14155238886"
TEST_AMOUNT = Decimal("100.00")
CENT = Decimal("0.01")
FINANCE_ROLES = {"OWNER", "ADMIN", "ACCOUNTANT"}
DISPATCH_ROLES = {"OWNER", "ADMIN", "DISPATCHER"}
PHONE = re.compile(r"^whatsapp:(\+[1-9][0-9]{7,14})$")
MESSAGE_SID = re.compile(r"^SM[0-9a-fA-F]{32}$")


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TestTopupInput(InputModel):
    request_id: UUID
    test_token: Literal["tok_visa", "tok_chargeDeclined"] = "tok_visa"


def require_prepaid_funds(wallet: Any, required: Decimal, currency: str) -> None:
    """One Decimal credit guard shared by booking, printing and the probe."""
    if not isinstance(required, Decimal) or not required.is_finite() or required < 0:
        raise ValueError("Required amount must be a finite nonnegative Decimal")
    if wallet["currency"] != currency:
        raise HTTPException(409, "Wallet currency mismatch")
    balance, reserved = strict_decimal(wallet["balance"]), strict_decimal(wallet["reserved_balance"])
    if balance < 0 or reserved < 0 or reserved > balance:
        raise HTTPException(503, "Wallet reconciliation required")
    available = balance - reserved
    if available <= 0 or available < required:
        raise HTTPException(402, {"code": "INSUFFICIENT_WALLET_BALANCE", "currency": currency,
                                  "required": format(required, ".2f"), "available": format(available, ".2f")})


def zero_balance_probe(wallet: Any) -> dict:
    snapshot = {"currency": wallet["currency"], "balance": Decimal("0.00"), "reserved_balance": Decimal("0.00")}
    try:
        require_prepaid_funds(snapshot, CENT, snapshot["currency"])
    except HTTPException as exc:
        if exc.status_code != 402:
            raise
        return {"blocked": True, "http_status": 402, "available": "0.00", "required": "0.01",
                "guard": "shared_booking_and_label_guard", "probe": "zero_balance_snapshot", "wallet_mutated": False}
    raise RuntimeError("Zero-balance credit guard did not block printing")


def require_sandbox_environment(settings: Any, *, stripe_payment: bool = False) -> None:
    if (not getattr(settings, "sandbox_hooks_enabled", False)
            or getattr(settings, "database_environment", "LIVE") != "SANDBOX"
            or settings.provider_environment != "TEST"):
        raise HTTPException(403, "Sandbox hooks require an enabled SANDBOX database and TEST providers")
    if stripe_payment and (settings.stripe_livemode or not settings.stripe_secret_key.get_secret_value().startswith("sk_test_")):
        raise HTTPException(403, "Sandbox payments require an sk_test_ key and STRIPE_LIVEMODE=false")


async def simulate_stripe_test_payment(client: Any, secret_key: str, customer_id: str,
                                      tenant_id: UUID, request_id: UUID, test_token: str) -> Any:
    """Official reusable test token -> PaymentMethod -> confirmed PaymentIntent.

    Despite the simulated card, these are real calls to Stripe's test API.
    No card numbers, CVCs or live payment credentials are accepted by the route.
    """
    if not secret_key.startswith("sk_test_") or test_token not in {"tok_visa", "tok_chargeDeclined"}:
        raise HTTPException(403, "Only supported Stripe test keys/tokens are accepted")
    try:
        method = await client.v1.payment_methods.create_async(
            {"type": "card", "card": {"token": test_token}},
            options={"idempotency_key": f"sandbox-method:{tenant_id}:{request_id}"})
        if getattr(method, "livemode", None) is not False or not str(getattr(method, "id", "")).startswith("pm_"):
            raise HTTPException(502, "Unexpected Stripe test payment method")
        intent = await client.v1.payment_intents.create_async(
            {"amount": 10000, "currency": "gbp", "customer": customer_id,
             "payment_method": method.id, "payment_method_types": ["card"], "confirm": True,
             "error_on_requires_action": True, "description": "Veloce sandbox wallet test — no live funds",
             "metadata": {"purpose": "sandbox_test_topup", "tenant_id": str(tenant_id), "topup_id": str(request_id)}},
            options={"idempotency_key": f"sandbox-payment:{tenant_id}:{request_id}"})
    except stripe.CardError:
        raise HTTPException(402, "Stripe test card was declined; wallet was not credited") from None
    except stripe.StripeError:
        raise HTTPException(503, "Stripe test payment unavailable; retry with the same request_id") from None
    if (intent.livemode is not False or intent.status != "succeeded"
            or type(intent.amount) is not int or intent.amount != 10000
            or type(intent.amount_received) is not int or intent.amount_received != 10000
            or intent.currency != "gbp" or intent.customer != customer_id
            or not str(intent.id).startswith("pi_")
            or dict(intent.metadata) != {"purpose": "sandbox_test_topup", "tenant_id": str(tenant_id), "topup_id": str(request_id)}):
        raise HTTPException(502, "Stripe payment did not match the registered £100.00 sandbox top-up")
    return intent


class SandboxBillingService:
    def __init__(self, finance: Any, settings: Any):
        self.finance, self.settings = finance, settings
        self.pool, self.client = finance.pool, finance.stripe

    def check_tenant(self, tenant: Any, wallet: Any) -> None:
        if tenant["is_sandbox"] is not True:
            raise HTTPException(403, "Test credits are restricted to marked sandbox tenants")
        if tenant["billing_plan"] != "PREPAID_WALLET" or tenant["billing_status"] != "ACTIVE":
            raise HTTPException(409, "An active prepaid sandbox wallet is required")
        if wallet["currency"] != "GBP":
            raise HTTPException(409, "The £100.00 test requires a GBP wallet")

    @staticmethod
    def check_topup(topup: Any, context: Any, body: TestTopupInput, customer: str) -> None:
        if (topup["tenant_id"] != context.tenant_id or topup["requested_by_auth_user_id"] != context.user_id
                or not topup["is_sandbox"] or topup["amount"] != TEST_AMOUNT or topup["currency"] != "GBP"
                or topup["sandbox_test_token"] != body.test_token or topup["stripe_customer_id"] != customer):
            raise HTTPException(409, "Test top-up request_id conflicts with another request")

    @staticmethod
    def response(wallet: Any, body: TestTopupInput, intent_id: str, credited: bool) -> dict:
        if not isinstance(intent_id, str) or not intent_id.startswith("pi_"):
            raise HTTPException(503, "Test top-up payment identifier needs reconciliation")
        return {"request_id": str(body.request_id), "payment_intent_id": intent_id, "currency": "GBP", "amount": "100.00",
                "credited": credited, "balance": format(wallet["balance"], ".2f"),
                "reserved_balance": format(wallet["reserved_balance"], ".2f"),
                "available": format(wallet["balance"] - wallet["reserved_balance"], ".2f"),
                "livemode": False, "zero_balance_label_check": zero_balance_probe(wallet)}

    async def test_topup(self, context: Any, body: TestTopupInput) -> dict:
        require_sandbox_environment(self.settings, stripe_payment=True)
        if context.role not in FINANCE_ROLES:
            raise HTTPException(403, "Financial permission required")
        # Check eligibility before any Stripe API call. All network I/O below
        # occurs outside financial DB transactions and row locks.
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await self.finance.lock_tenant(connection, context.tenant_id, context, FINANCE_ROLES)
                wallet = await self.finance.lock_wallet(connection, context.tenant_id)
                self.check_tenant(tenant, wallet)
                customer_id = tenant["stripe_customer_id"]
                existing = await connection.fetchrow("SELECT * FROM public.wallet_topups WHERE id=$1 FOR UPDATE", body.request_id)
                if existing is not None:
                    self.check_topup(existing, context, body, customer_id)
                    if existing["status"] == "CREDITED":
                        return self.response(wallet, body, existing["stripe_payment_intent_id"], False)
                    if datetime.now(timezone.utc) - existing["created_at"] > timedelta(hours=23):
                        raise HTTPException(409, "Old ambiguous test payment needs reconciliation")
        try:
            if customer_id is None:
                customer = await self.client.v1.customers.create_async(
                    {"name": "Veloce sandbox tenant", "metadata": {"tenant_id": str(context.tenant_id), "environment": "SANDBOX"}},
                    options={"idempotency_key": f"sandbox-customer:{context.tenant_id}"})
            else:
                customer = await self.client.v1.customers.retrieve_async(customer_id)
        except stripe.StripeError:
            raise HTTPException(503, "Stripe test customer unavailable") from None
        if getattr(customer, "livemode", None) is not False or not str(getattr(customer, "id", "")).startswith("cus_"):
            raise HTTPException(502, "Expected a Stripe test customer")
        customer_id = customer.id
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await self.finance.lock_tenant(connection, context.tenant_id, context, FINANCE_ROLES)
                wallet = await self.finance.lock_wallet(connection, context.tenant_id)
                self.check_tenant(tenant, wallet)
                if tenant["stripe_customer_id"] not in {None, customer_id}:
                    raise HTTPException(409, "Sandbox customer changed during top-up")
                if tenant["stripe_customer_id"] is None:
                    await connection.execute("UPDATE public.tenants SET stripe_customer_id=$2 WHERE tenant_id=$1", context.tenant_id, customer_id)
                existing = await connection.fetchrow("SELECT * FROM public.wallet_topups WHERE id=$1 FOR UPDATE", body.request_id)
                if existing is None:
                    await connection.execute(
                        """INSERT INTO public.wallet_topups
                           (id,tenant_id,requested_by_auth_user_id,stripe_customer_id,amount,currency,is_sandbox,sandbox_test_token)
                           VALUES ($1,$2,$3,$4,$5,'GBP',true,$6)""",
                        body.request_id, context.tenant_id, context.user_id, customer_id, TEST_AMOUNT, body.test_token)
                else:
                    self.check_topup(existing, context, body, customer_id)
                    if existing["status"] == "CREDITED":
                        return self.response(wallet, body, existing["stripe_payment_intent_id"], False)
                    if datetime.now(timezone.utc) - existing["created_at"] > timedelta(hours=23):
                        raise HTTPException(409, "Old ambiguous test payment needs reconciliation")
        intent = await simulate_stripe_test_payment(self.client, self.settings.stripe_secret_key.get_secret_value(),
                                                  customer_id, context.tenant_id, body.request_id, body.test_token)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant = await self.finance.lock_tenant(connection, context.tenant_id, context, FINANCE_ROLES)
                topup = await connection.fetchrow(
                    "SELECT * FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2 FOR UPDATE", context.tenant_id, body.request_id)
                wallet = await self.finance.lock_wallet(connection, context.tenant_id)
                self.check_tenant(tenant, wallet)
                if topup is None or tenant["stripe_customer_id"] != customer_id:
                    raise HTTPException(409, "Registered test top-up changed")
                self.check_topup(topup, context, body, customer_id)
                if topup["stripe_payment_intent_id"] not in {None, intent.id}:
                    raise HTTPException(409, "Test payment identifier conflict")
                if topup["status"] == "CREDITED":
                    return self.response(wallet, body, intent.id, False)
                with localcontext() as decimal_context:
                    decimal_context.prec = 50
                    balance = wallet["balance"] + TEST_AMOUNT
                await connection.execute("UPDATE public.wallets SET balance=$2,updated_at=now() WHERE tenant_id=$1", context.tenant_id, balance)
                await self.finance.append_ledger(
                    connection, tenant_id=context.tenant_id, currency="GBP", entry_type="TOPUP",
                    balance_delta=TEST_AMOUNT, reserved_delta=Decimal("0.00"), balance_after=balance,
                    reserved_after=wallet["reserved_balance"], topup_id=body.request_id, stripe_payment_intent_id=intent.id)
                await connection.execute(
                    """UPDATE public.wallet_topups SET status='CREDITED',stripe_payment_intent_id=$3,credited_at=now()
                       WHERE tenant_id=$1 AND id=$2""", context.tenant_id, body.request_id, intent.id)
                updated = dict(wallet)
                updated["balance"] = balance
                return self.response(updated, body, intent.id, True)


async def authenticated_twilio_form(request: Request) -> FormData:
    """Authenticate the exact configured external HTTPS URL and every field."""
    settings = request.app.state.settings
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Expected form-urlencoded payload")
    if request.url.path != urlsplit(settings.twilio_webhook_url).path or request.url.query:
        raise HTTPException(400, "Unexpected webhook URL")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 32768:
            raise HTTPException(413, "Webhook payload too large")
    try:
        if re.search(rb"%(?![0-9A-Fa-f]{2})", raw):
            raise ValueError("Invalid percent encoding")
        form = FormData(parse_qsl(bytes(raw).decode("utf-8"), keep_blank_values=True,
                                  encoding="utf-8", errors="strict", max_num_fields=150))
    except (UnicodeError, ValueError):
        raise HTTPException(400, "Invalid form payload") from None
    if len(request.headers.getlist("x-twilio-signature")) != 1 or not request.app.state.twilio_validator.validate(
            settings.twilio_webhook_url, form, request.headers.get("x-twilio-signature", "")):
        raise HTTPException(403, "Invalid Twilio signature")
    required = ("AccountSid", "From", "To", "MessageSid", "Body", "NumMedia")
    if any(len(form.getlist(name)) != 1 for name in required):
        raise HTTPException(400, "Missing or repeated webhook fields")
    if form["AccountSid"] != settings.twilio_account_sid:
        raise HTTPException(403, "Unexpected Twilio account")
    sender, receiver = PHONE.fullmatch(form["From"]), PHONE.fullmatch(form["To"])
    if sender is None or receiver is None:
        raise HTTPException(400, "Expected WhatsApp sender and receiver")
    if receiver.group(1) != settings.twilio_whatsapp_number:
        raise HTTPException(403, "Unexpected receiving number")
    if getattr(settings, "twilio_whatsapp_sandbox_enabled", False) and receiver.group(1) != SANDBOX_NUMBER:
        raise HTTPException(403, "Expected Twilio WhatsApp Sandbox number")
    if MESSAGE_SID.fullmatch(form["MessageSid"]) is None or len(form["Body"]) > 1600:
        raise HTTPException(400, "Invalid message identifier or body size")
    if not re.fullmatch(r"[0-9]{1,2}", form["NumMedia"]) or int(form["NumMedia"]) > 10:
        raise HTTPException(400, "Invalid NumMedia")
    for name in ("SmsSid", "SmsMessageSid"):
        if name in form and (len(form.getlist(name)) != 1 or form[name] != form["MessageSid"]):
            raise HTTPException(400, "Inconsistent message identifiers")
    return form


class WhatsAppSandboxSetup(InputModel):
    tenant_id: UUID
    auth_user_id: UUID
    sender_e164: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")
    route_code: str = Field(default="EXPORT_US", pattern=r"^[A-Z0-9_-]{1,24}$")
    origin_address: dict
    destination_address: dict
    dimensions: dict
    currency: Literal["GBP", "EUR", "USD"] = "GBP"


def build_router(authenticate: Any, rating_model: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Sandbox integrations"])

    @router.post("/billing/test-topup")
    async def test_topup(body: TestTopupInput, request: Request, context: Any = Depends(authenticate)):
        service = getattr(request.app.state, "sandbox_billing", None)
        if service is None:
            raise HTTPException(503, "Sandbox billing is unavailable in local preview")
        try:
            return await service.test_topup(context, body)
        except (asyncpg.PostgresError, OSError, TimeoutError):
            raise HTTPException(503, "Sandbox billing unavailable; check migration 008 and retry with the same request_id") from None

    @router.get("/shipments/{shipment_id}/label/preview")
    async def print_preview(shipment_id: UUID, request: Request, context: Any = Depends(authenticate)):
        try:
            return await request.app.state.finance.authorize_label_preview(context, shipment_id)
        except asyncpg.PostgresError:
            raise HTTPException(503, "Label preview unavailable") from None

    @router.post("/admin/sandbox/whatsapp-setup")
    async def setup_whatsapp(body: WhatsAppSandboxSetup, request: Request, actor: PlatformOwner = Depends(authenticate_platform_owner)):
        from pydantic import ValidationError
        settings = request.app.state.settings
        require_sandbox_environment(settings)
        if not settings.twilio_whatsapp_sandbox_enabled or settings.twilio_whatsapp_number != SANDBOX_NUMBER:
            raise HTTPException(403, "Enable Twilio WhatsApp Sandbox first")
        try:
            rating = rating_model.model_validate({"origin": body.origin_address, "destination": body.destination_address,
                                                  "dimensions": [body.dimensions], "weights_kg": ["1.000"], "currency": body.currency})
        except ValidationError:
            raise HTTPException(422, "Invalid saved-route addresses or dimensions") from None
        try:
            async with request.app.state.finance.pool.acquire() as connection:
                async with connection.transaction():
                    tenant = await connection.fetchrow("SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1 FOR SHARE", body.tenant_id)
                    if tenant is None or not tenant["is_sandbox"]:
                        raise HTTPException(403, "Target a marked sandbox tenant")
                    user = await connection.fetchrow(
                        """SELECT id,role FROM public.users WHERE tenant_id=$1 AND auth_user_id=$2 AND is_active FOR SHARE""",
                        body.tenant_id, body.auth_user_id)
                    if user is None or user["role"] not in DISPATCH_ROLES:
                        raise HTTPException(422, "An active dispatch member is required")
                    await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                                             f"sandbox-binding:{body.sender_e164}:{SANDBOX_NUMBER}")
                    bindings = await connection.fetch(
                        """SELECT tenant_id,user_id FROM public.whatsapp_bindings
                           WHERE sender_e164=$1 AND receiver_e164=$2 LIMIT 2 FOR UPDATE""", body.sender_e164, SANDBOX_NUMBER)
                    if len(bindings) > 1 or (bindings and (bindings[0]["tenant_id"] != body.tenant_id or bindings[0]["user_id"] != user["id"])):
                        raise HTTPException(409, "Phone binding conflicts with another workspace/member")
                    if bindings:
                        await connection.execute(
                            """UPDATE public.whatsapp_bindings SET is_active=true
                               WHERE tenant_id=$1 AND user_id=$2 AND sender_e164=$3 AND receiver_e164=$4""",
                            body.tenant_id, user["id"], body.sender_e164, SANDBOX_NUMBER)
                    else:
                        await connection.execute(
                            """INSERT INTO public.whatsapp_bindings (tenant_id,user_id,sender_e164,receiver_e164,verified_at,is_active)
                               VALUES ($1,$2,$3,$4,now(),true)""", body.tenant_id, user["id"], body.sender_e164, SANDBOX_NUMBER)
                    await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"sandbox-route:{body.tenant_id}:{body.route_code}")
                    exists = await connection.fetchval("SELECT count(*) FROM public.whatsapp_routes WHERE tenant_id=$1 AND route_code=$2", body.tenant_id, body.route_code)
                    if exists > 1:
                        raise HTTPException(409, "Duplicate saved route codes require reconciliation")
                    route_values = (body.tenant_id, body.route_code, rating.origin.country_code, rating.destination.country_code,
                                    rating.origin.model_dump_json(), rating.destination.model_dump_json(), rating.dimensions[0].model_dump_json(), body.currency)
                    if exists:
                        await connection.execute(
                            """UPDATE public.whatsapp_routes SET origin_country=$3,destination_country=$4,
                               origin_address=$5::jsonb,destination_address=$6::jsonb,dimensions=$7::jsonb,currency=$8,is_active=true
                               WHERE tenant_id=$1 AND route_code=$2""", *route_values)
                    else:
                        await connection.execute(
                            """INSERT INTO public.whatsapp_routes
                               (tenant_id,route_code,origin_country,destination_country,origin_address,destination_address,dimensions,currency,is_active)
                               VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8,true)""", *route_values)
        except asyncpg.PostgresError:
            raise HTTPException(503, "Sandbox WhatsApp setup unavailable; check schema and migration 008") from None
        return {"tenant_id": str(body.tenant_id), "receiver": "whatsapp:" + SANDBOX_NUMBER, "route_code": body.route_code,
                "configured": True, "notice": "Join this Twilio Sandbox from your mobile before texting. No message was sent by this setup endpoint."}

    return router
