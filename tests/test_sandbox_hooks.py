"""Sandbox integration contracts without real provider traffic."""
import asyncio
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import uuid4
from xml.etree import ElementTree

import stripe
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator

import main
from backend.sandbox_hooks import SandboxBillingService, TestTopupInput, require_prepaid_funds, zero_balance_probe


def settings():
    return SimpleNamespace(stripe_enabled=True, twilio_enabled=True, sandbox_hooks_enabled=True, database_environment="SANDBOX", provider_environment="TEST",
                           stripe_secret_key=SecretStr("sk_test_fixture"), stripe_livemode=False,
                           twilio_account_sid="AC" + "a" * 32, twilio_auth_token=SecretStr("fixture-auth-token"),
                           twilio_whatsapp_number="+14155238886", twilio_whatsapp_sandbox_enabled=True,
                           twilio_webhook_url="https://sandbox.example.com/webhooks/twilio/whatsapp",
                           whatsapp_deadline_seconds=12, whatsapp_provider_seconds=7,
                           quote_link_secret=SecretStr("x" * 40), booking_page_url="https://sandbox.example.com/book")


class Transaction:
    def __init__(self, connection, **kwargs): self.connection = connection
    async def __aenter__(self):
        await self.connection.lock.acquire()
        self.snapshot = copy.deepcopy(self.connection.state)
        self.connection.depth += 1
        return self.connection
    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.connection.state = self.snapshot
        self.connection.depth -= 1
        self.connection.lock.release()
        return False


class Acquire:
    def __init__(self, connection): self.connection = connection
    async def __aenter__(self): return self.connection
    async def __aexit__(self, *args): return False


class Connection:
    def __init__(self, tenant, user):
        self.tenant, self.user = tenant, user
        self.shipment_id = uuid4()
        self.lock, self.depth, self.calls = asyncio.Lock(), 0, []
        self.fail_ledger = False
        self.messages = {}
        self.state = {"tenant": {"tenant_id": tenant, "workspace_status": "ACTIVE", "billing_status": "ACTIVE", "billing_plan": "PREPAID_WALLET", "default_currency": "GBP", "stripe_customer_id": "cus_test", "is_sandbox": True},
                      "wallet": {"tenant_id": tenant, "currency": "GBP", "balance": Decimal("0.00"), "reserved_balance": Decimal("0.00")},
                      "topups": {}, "ledger": [], "reservations": [], "receipts": {}, "choices": [],
                      "shipment": {"id": self.shipment_id, "status": "BOOKED", "currency": "GBP", "final_client_price": Decimal("10.00"), "tracking_number": "TEST^XZ-INJECTION", "quote_expires_at": datetime.now(timezone.utc) + timedelta(minutes=5)}}
    def transaction(self, **kwargs): return Transaction(self, **kwargs)
    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "FROM public.conversational_messages" in sql: return self.messages.get(args[2])
        if "FROM public.tenants" in sql: return dict(self.state["tenant"]) if args[0] == self.tenant else None
        if "FROM public.users" in sql: return {"role": "OWNER"}
        if "FROM public.wallets" in sql: return dict(self.state["wallet"]) if args[0] == self.tenant else None
        if "FROM public.wallet_topups" in sql:
            key = args[1] if len(args) == 2 else args[0]
            row = self.state["topups"].get(key)
            return dict(row) if row and (len(args) != 2 or row["tenant_id"] == args[0]) else None
        if "FROM public.shipments" in sql: return dict(self.state["shipment"]) if args[:2] == (self.tenant, self.shipment_id) else None
        if "FROM public.wallet_reservations" in sql: return None
        raise AssertionError(sql)
    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if "FROM public.whatsapp_bindings" in sql:
            if args[0] != "+447700900123" or (args[2] and not self.state["tenant"]["is_sandbox"]): return []
            return [{"tenant_id": self.tenant, "auth_user_id": self.user, "role": "OWNER"}]
        if "FROM public.whatsapp_routes" in sql:
            return [{"origin_address": json.dumps({"name": "Sender", "line1": "1 Street", "city": "London", "postal_code": "SW1A 1AA", "country_code": "GB"}),
                     "destination_address": json.dumps({"name": "Receiver", "line1": "2 Street", "city": "New York", "postal_code": "10001", "country_code": "US"}),
                     "dimensions": json.dumps({"length_cm": "10", "width_cm": "10", "height_cm": "10"}), "currency": "GBP"}]
        raise AssertionError(sql)
    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        if "to_regclass('public.conversational_messages')" in sql or 'pg_try_advisory_lock' in sql: return True
        if 'SELECT EXISTS(SELECT 1 FROM public.conversational_messages' in sql: return False
        if 'SELECT response FROM public.conversational_messages' in sql:
            quotes = [row['response'] for row in self.messages.values() if row['state'] == 'COMPLETED' and json.loads(row['response']).get('action_taken') == 'QUOTE']
            return quotes[-1] if quotes else None
        if "response_xml" in sql: return self.state["receipts"].get(args)
        raise AssertionError(sql)
    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if "INSERT INTO public.conversational_messages" in sql:
            self.messages[args[0]] = {'input_sha256': args[4], 'state': 'PROCESSING', 'response': '{}'}
        elif "UPDATE public.conversational_messages" in sql:
            self.messages[args[2]].update(state='COMPLETED', response=args[3])
        elif "UPDATE public.tenants SET stripe_customer_id" in sql: self.state["tenant"]["stripe_customer_id"] = args[1]
        elif "INSERT INTO public.wallet_topups" in sql:
            self.state["topups"][args[0]] = {"id": args[0], "tenant_id": args[1], "requested_by_auth_user_id": args[2], "stripe_customer_id": args[3], "amount": args[4], "currency": "GBP", "is_sandbox": True, "sandbox_test_token": args[5], "status": "PENDING", "stripe_payment_intent_id": None, "created_at": datetime.now(timezone.utc)}
        elif "UPDATE public.wallets SET balance" in sql: self.state["wallet"]["balance"] = args[1]
        elif "INSERT INTO public.wallet_ledger" in sql:
            if self.fail_ledger: raise RuntimeError("injected ledger failure")
            self.state["ledger"].append(args)
        elif "UPDATE public.wallet_topups SET status='CREDITED'" in sql:
            self.state["topups"][args[1]].update(status="CREDITED", stripe_payment_intent_id=args[2])
        elif "INSERT INTO public.whatsapp_quote_choices" in sql: self.state["choices"].append(args)
        elif "INSERT INTO public.whatsapp_receipts" in sql: self.state["receipts"][args[:2]] = args[2]
        return "UPDATE 1"


class FakeStripe:
    def __init__(self, connection):
        self.connection, self.calls, self.methods, self.intents = connection, [], {}, {}
        self.intent_changes = {}
        self.v1 = SimpleNamespace(customers=SimpleNamespace(create_async=self.customer_create, retrieve_async=self.customer_get),
                                  payment_methods=SimpleNamespace(create_async=self.method_create),
                                  payment_intents=SimpleNamespace(create_async=self.intent_create))
    def outside_transaction(self):
        if self.connection.depth: raise AssertionError("Stripe call held financial row locks")
    async def customer_create(self, params, options):
        self.outside_transaction(); self.calls.append(("customer_create", params, options))
        await asyncio.sleep(0)
        return SimpleNamespace(id="cus_created", livemode=False)
    async def customer_get(self, customer):
        self.outside_transaction(); self.calls.append(("customer_get", customer))
        await asyncio.sleep(0)
        return SimpleNamespace(id=customer, livemode=False)
    async def method_create(self, params, options):
        self.outside_transaction(); self.calls.append(("method", params, options))
        await asyncio.sleep(0)
        key = options["idempotency_key"]
        result = self.methods.setdefault(key, SimpleNamespace(id="pm_" + key.split(":")[-1], livemode=False))
        result.decline = params["card"]["token"] == "tok_chargeDeclined"
        return result
    async def intent_create(self, params, options):
        self.outside_transaction(); self.calls.append(("intent", params, options))
        await asyncio.sleep(0)
        if any(method.id == params["payment_method"] and method.decline for method in self.methods.values()):
            raise stripe.CardError("declined", "payment_method", "card_declined")
        key = options["idempotency_key"]
        return self.intents.setdefault(key, SimpleNamespace(**{"id": "pi_" + key.split(":")[-1], "livemode": False,
                "status": "succeeded", "amount": 10000, "amount_received": 10000, "currency": "gbp",
                "customer": params["customer"], "metadata": params["metadata"], **self.intent_changes}))


class BillingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = main.TenantContext(uuid4(), uuid4(), "OWNER", "fixture")
        self.connection = Connection(self.context.tenant_id, self.context.user_id)
        self.settings = settings()
        self.stripe = FakeStripe(self.connection)
        self.pool = SimpleNamespace(acquire=lambda: Acquire(self.connection))
        self.finance = main.FinanceEngine(self.pool, self.settings, self.stripe)
        self.service = SandboxBillingService(self.finance, self.settings)

    async def test_100_credit_and_idempotent_retry(self):
        body = TestTopupInput(request_id=uuid4())
        first = await self.service.test_topup(self.context, body)
        self.assertEqual(first["balance"], "100.00")
        self.assertTrue(first["zero_balance_label_check"]["blocked"])
        self.assertFalse(first["zero_balance_label_check"]["wallet_mutated"])
        calls = len(self.stripe.calls)
        second = await self.service.test_topup(self.context, body)
        self.assertFalse(second["credited"])
        self.assertEqual(len(self.stripe.calls), calls)
        self.assertEqual(len(self.connection.state["ledger"]), 1)
        intent_params = next(call[1] for call in self.stripe.calls if call[0] == "intent")
        self.assertEqual(intent_params["amount"], 10000)
        self.assertEqual(intent_params["currency"], "gbp")
        self.assertEqual(self.connection.state["ledger"][0][3], Decimal("100.00"))

    async def test_concurrent_retries_credit_only_once(self):
        body = TestTopupInput(request_id=uuid4())
        results = await asyncio.gather(self.service.test_topup(self.context, body), self.service.test_topup(self.context, body))
        self.assertEqual(sum(result["credited"] for result in results), 1)
        self.assertEqual(self.connection.state["wallet"]["balance"], Decimal("100.00"))
        self.assertEqual(len(self.connection.state["ledger"]), 1)

    async def test_live_keys_and_unmarked_tenants_rejected_before_stripe(self):
        self.settings.stripe_secret_key = SecretStr("sk_live_fixture")
        with self.assertRaises(main.HTTPException) as error:
            await self.service.test_topup(self.context, TestTopupInput(request_id=uuid4()))
        self.assertEqual(error.exception.status_code, 403)
        self.settings.stripe_secret_key = SecretStr("sk_test_fixture")
        self.connection.state["tenant"]["is_sandbox"] = False
        with self.assertRaises(main.HTTPException):
            await self.service.test_topup(self.context, TestTopupInput(request_id=uuid4()))
        self.assertEqual(self.stripe.calls, [])

    async def test_decline_and_wrong_stripe_response_never_credit(self):
        with self.assertRaises(main.HTTPException) as error:
            await self.service.test_topup(self.context, TestTopupInput(request_id=uuid4(), test_token="tok_chargeDeclined"))
        self.assertEqual(error.exception.status_code, 402)
        for changes in ({"amount_received": 9999}, {"livemode": True}, {"currency": "usd"}, {"customer": "cus_wrong"}, {"metadata": {}}, {"status": "processing"}):
            self.stripe.intent_changes = changes
            with self.assertRaises(main.HTTPException) as error:
                await self.service.test_topup(self.context, TestTopupInput(request_id=uuid4()))
            self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(self.connection.state["wallet"]["balance"], Decimal("0.00"))

    async def test_zero_balance_blocks_actual_label_and_booking_guards(self):
        with self.assertRaises(main.HTTPException) as error:
            await self.finance.authorize_label_preview(self.context, self.connection.shipment_id)
        self.assertEqual(error.exception.status_code, 402)
        self.connection.state["shipment"]["status"] = "QUOTED"
        with self.assertRaises(main.HTTPException) as error:
            await self.finance.reserve(self.context, self.connection.shipment_id)
        self.assertEqual(error.exception.status_code, 402)
        self.assertTrue(any("FOR UPDATE" in sql and "public.wallets" in sql for sql, _ in self.connection.calls))
        self.assertEqual(self.connection.state["ledger"], [])

    async def test_funded_label_is_sample_without_charge(self):
        await self.service.test_topup(self.context, TestTopupInput(request_id=uuid4()))
        result = await self.finance.authorize_label_preview(self.context, self.connection.shipment_id)
        self.assertIn("SAMPLE ONLY", result["zpl"])
        self.assertNotIn("TEST^XZ", result["zpl"])
        self.assertFalse(result["charged"])
        self.assertEqual(self.connection.state["wallet"]["balance"], Decimal("100.00"))

    async def test_sandbox_cannot_submit_carrier_purchase(self):
        permit = main.BookingPermit(self.context.tenant_id, self.connection.shipment_id, uuid4(), Decimal("10.00"), "GBP", "PREPAID_WALLET")
        with self.assertRaises(main.HTTPException) as error:
            await self.finance.mark_submitted(permit)
        self.assertEqual(error.exception.status_code, 403)

    async def test_failed_ledger_rolls_back_and_retry_reconciles_same_payment(self):
        self.connection.fail_ledger = True
        body = TestTopupInput(request_id=uuid4())
        with self.assertRaises(RuntimeError):
            await self.service.test_topup(self.context, body)
        self.assertEqual(self.connection.state["wallet"]["balance"], Decimal("0.00"))
        self.connection.fail_ledger = False
        result = await self.service.test_topup(self.context, body)
        self.assertTrue(result["credited"])
        self.assertEqual(len(self.stripe.intents), 1)

    async def test_missing_customer_is_created_in_test_mode(self):
        self.connection.state["tenant"]["stripe_customer_id"] = None
        result = await self.service.test_topup(self.context, TestTopupInput(request_id=uuid4()))
        self.assertTrue(result["credited"])
        self.assertEqual(self.connection.state["tenant"]["stripe_customer_id"], "cus_created")


class WhatsAppTests(unittest.TestCase):
    def setUp(self):
        self.tenant, self.user = uuid4(), uuid4()
        self.connection = Connection(self.tenant, self.user)
        self.settings = settings()
        self.pool = SimpleNamespace(acquire=lambda: Acquire(self.connection))
        self.observed = []
        observed = self.observed
        class Rating:
            async def quote(self, context, request, deadline=None):
                observed.append((context, request))
                now = datetime.now(timezone.utc)
                return main.RatingResponse(request_id=uuid4(), currency="GBP", quoted_at=now, expires_at=now + timedelta(minutes=5), partial=False, issues=[],
                                          rates=[main.ClientRate(provider="EASYPOST", account_id=uuid4(), upstream_shipment_id="test-shipment", upstream_rate_id="test-rate", carrier_code="DHL", service_code="EXPRESS", currency="GBP", client_price_ex_tax="23.45", delivery_days=2)])
        main.app.state.local_preview = False
        main.app.state.settings = self.settings
        main.app.state.twilio_validator = RequestValidator(self.settings.twilio_auth_token.get_secret_value())
        main.app.state.whatsapp = main.WhatsAppService(self.pool, self.settings, Rating())
        main.app.state.rating = main.app.state.whatsapp.rating
        main.app.state.finance = SimpleNamespace(pool=self.pool)
        main.app.state.logistics_supervisor = None
        main.app.state.settings.whatsapp_brand_name = "EasyInvio.com"
        self.client = TestClient(main.app)
    def fields(self, **overrides):
        return {"AccountSid": self.settings.twilio_account_sid, "From": "whatsapp:+447700900123", "To": "whatsapp:+14155238886", "MessageSid": "SM" + "b" * 32, "Body": "Quote 4.5kg from GBR to USA route TEST", "NumMedia": "0", **overrides}
    def post(self, fields, *, signature=None):
        pairs = list(fields.items()) if isinstance(fields, dict) else fields
        signature = signature or main.app.state.twilio_validator.compute_signature(self.settings.twilio_webhook_url, FormData(pairs))
        return self.client.post("/webhooks/twilio/whatsapp", content=urlencode(pairs), headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": signature})
    def test_signed_query_exact_decimal_pricing_and_duplicate_receipt(self):
        response = self.post(self.fields(FutureTwilioParameter="must be included in signature"))
        self.assertEqual(response.status_code, 200, response.text)
        text = ElementTree.fromstring(response.text).find("Message").text
        self.assertIn("23.45 GBP", text)
        self.assertIn("sandbox quotes", text)
        self.assertIn("4.5kg", text)
        context, request = self.observed[0]
        self.assertEqual(context.tenant_id, self.tenant)
        self.assertEqual(request.weights_kg, [Decimal("4.5")])
        self.assertEqual(request.destination.country_code, "US")
        self.assertEqual(self.post(self.fields(FutureTwilioParameter="must be included in signature")).text, response.text)
        self.assertEqual(len(self.observed), 1)
    def test_invalid_signature_never_reads_tenant_data(self):
        self.assertEqual(self.post(self.fields(), signature="invalid").status_code, 403)
        self.assertEqual(self.connection.calls, [])
    def test_signed_structural_failures(self):
        for fields in (self.fields(NumMedia="-1"), self.fields(MessageSid="bad"), self.fields(From="+447700900123"), self.fields(SmsSid="SM" + "c" * 32)):
            self.assertEqual(self.post(fields).status_code, 400)
        self.assertEqual(self.post([*self.fields().items(), ("Body", "second body")]).status_code, 400)
        self.assertEqual(self.post({key: value for key, value in self.fields().items() if key != "NumMedia"}).status_code, 400)
        self.assertEqual(self.connection.calls, [])
    def test_wrong_account_receiver_and_unbound_phone(self):
        self.assertEqual(self.post(self.fields(AccountSid="AC" + "c" * 32)).status_code, 403)
        self.assertEqual(self.post(self.fields(To="whatsapp:+14155550000")).status_code, 403)
        response = self.post(self.fields(From="whatsapp:+447700900999"))
        self.assertIn("not registered", response.text)
        self.assertEqual(self.observed, [])
    def test_media_returns_text_instruction_and_unknown_location_collects_details(self):
        self.assertIn("Please send text", self.post(self.fields(NumMedia="1")).text)
        self.assertIn("Origin Postcode", self.post(self.fields(Body="Quote 4.5kg from XYZ to USA")).text)
        self.assertEqual(self.observed, [])
    def test_non_sandbox_binding_cannot_be_quoted(self):
        self.connection.state["tenant"]["is_sandbox"] = False
        self.assertIn("not registered", self.post(self.fields()).text)
        self.assertEqual(self.observed, [])


class SandboxHTTPTests(unittest.TestCase):
    def setUp(self):
        self.context = main.TenantContext(uuid4(), uuid4(), "OWNER", "fixture")
        self.connection = Connection(self.context.tenant_id, self.context.user_id)
        self.settings = settings()
        self.stripe = FakeStripe(self.connection)
        pool = SimpleNamespace(acquire=lambda: Acquire(self.connection))
        self.finance = main.FinanceEngine(pool, self.settings, self.stripe)
        main.app.state.local_preview = False
        main.app.state.finance = self.finance
        main.app.state.sandbox_billing = SandboxBillingService(self.finance, self.settings)
        main.app.dependency_overrides[main.authenticate] = lambda: self.context
        self.client = TestClient(main.app)
    def tearDown(self): main.app.dependency_overrides.clear()
    def test_http_credit_and_zero_print_block(self):
        url = f"/api/v1/shipments/{self.connection.shipment_id}/label/preview"
        self.assertEqual(self.client.get(url).status_code, 402)
        response = self.client.post("/api/v1/billing/test-topup", json={"request_id": str(uuid4())})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["balance"], "100.00")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.connection.state["wallet"]["balance"] = Decimal("0.00")
        self.assertEqual(self.client.get(url).status_code, 402)
    def test_client_cannot_change_amount_and_preview_disables_hook(self):
        self.assertEqual(self.client.post("/api/v1/billing/test-topup", json={"request_id": str(uuid4()), "amount": "1000.00"}).status_code, 422)
        main.app.state.local_preview = True
        self.assertEqual(self.client.post("/api/v1/billing/test-topup", json={"request_id": str(uuid4())}).status_code, 503)
        self.assertEqual(self.stripe.calls, [])

    def test_platform_setup_saves_binding_and_route_idempotently(self):
        from backend.admin_portal import PlatformOwner, authenticate_platform_owner
        class SetupConnection(Connection):
            async def fetch(self, sql, *args):
                if "FROM public.whatsapp_bindings" in sql:
                    self.calls.append((sql, args))
                    return self.state.get("bindings", [])
                return await super().fetch(sql, *args)
            async def fetchrow(self, sql, *args):
                if "FROM public.users" in sql:
                    self.calls.append((sql, args))
                    return {"id": self.user, "role": "OWNER"} if args[1] == self.user else None
                return await super().fetchrow(sql, *args)
            async def fetchval(self, sql, *args):
                if "count(*) FROM public.whatsapp_routes" in sql:
                    self.calls.append((sql, args))
                    return len(self.state.get("routes", []))
                return await super().fetchval(sql, *args)
            async def execute(self, sql, *args):
                if "INSERT INTO public.whatsapp_bindings" in sql:
                    self.state["bindings"] = [{"tenant_id": args[0], "user_id": args[1]}]
                if "INSERT INTO public.whatsapp_routes" in sql:
                    self.state["routes"] = [args]
                return await super().execute(sql, *args)
        connection = SetupConnection(self.context.tenant_id, self.context.user_id)
        main.app.state.settings = self.settings
        main.app.state.finance = SimpleNamespace(pool=SimpleNamespace(acquire=lambda: Acquire(connection)))
        main.app.dependency_overrides[authenticate_platform_owner] = lambda: PlatformOwner(uuid4())
        body = {"tenant_id": str(self.context.tenant_id), "auth_user_id": str(self.context.user_id), "sender_e164": "+447700900123",
                "origin_address": {"name": "Sender", "line1": "1 Street", "city": "London", "postal_code": "SW1A 1AA", "country_code": "GB"},
                "destination_address": {"name": "Receiver", "line1": "2 Street", "city": "New York", "postal_code": "10001", "country_code": "US"},
                "dimensions": {"length_cm": "30", "width_cm": "20", "height_cm": "10"}}
        for _ in range(2):
            response = self.client.post("/api/v1/admin/sandbox/whatsapp-setup", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["receiver"], "whatsapp:+14155238886")
        self.assertEqual(len(connection.state["bindings"]), 1)
        self.assertEqual(len(connection.state["routes"]), 1)
        bad = self.client.post("/api/v1/admin/sandbox/whatsapp-setup", json={**body, "auth_user_id": str(uuid4())})
        self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
