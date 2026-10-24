"""Admin controller and pricing contract tests; no external services."""
import asyncio
import copy
import json
import time
import unittest
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from backend.admin_portal import (
    AdminService, MarginCreate, PlatformOwner, TenantCreate,
    calibrated_pricing_scope, calculate_calibrated_price,
    configure_pricing_pool, get_client_calibrated_rate,
)


def company():
    return {"company_name": "Northstar Trading Ltd", "contact_name": "Alex Smith", "billing_email": "billing@example.com",
            "address_line1": "10 Business Road", "city": "London", "postal_code": "SW1A 1AA", "country_code": "GBR"}


class Transaction:
    def __init__(self, connection, **options): self.connection, self.options = connection, options
    async def __aenter__(self):
        self.before = copy.deepcopy(self.connection.store)
        self.connection.transactions.append(self.options)
        return self.connection
    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.connection.store = self.before
            self.connection.rollbacks += 1
        return False


class Acquire:
    def __init__(self, connection): self.connection = connection
    async def __aenter__(self): return self.connection
    async def __aexit__(self, *args): return False


class Connection:
    def __init__(self):
        self.store = {"tenants": {}, "wallets": [], "users": [], "margins": [], "events": {}}
        self.calls, self.transactions = [], []
        self.staff_calls = []
        self.rollbacks = 0
        self.owner_exists = True
        self.account_exists = True
        self.fail_wallet = False
        self.rule = None
        self.auto_wallet_currency = None
    def transaction(self, **options): return Transaction(self, **options)
    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "public.admin_configuration_events" in sql:
            return self.store["events"].get(tuple(args))
        if "public.tenants" in sql:
            return self.store["tenants"].get(args[0])
        if "public.wallets" in sql:
            wallet = next((row for row in self.store["wallets"] if row[0] == args[0]), None)
            return {"currency": wallet[1]} if wallet else None
        if "public.margin_rules" in sql:
            return self.rule
        raise AssertionError(sql)
    async def fetchval(self, sql, *args):
        if "public.platform_staff" in sql:
            self.staff_calls.append((sql,args)); return False
        self.calls.append((sql, args))
        return self.owner_exists if "auth.users" in sql else self.account_exists
    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if "INSERT INTO public.tenants" in sql:
            self.store["tenants"][args[0]] = {"default_currency": args[4], "workspace_status": "ACTIVE", "billing_plan": args[3], "company_profile": json.loads(args[2])}
            if self.auto_wallet_currency:
                self.store["wallets"].append((args[0], self.auto_wallet_currency))
        elif "INSERT INTO public.wallets" in sql:
            if self.fail_wallet:
                raise asyncpg.CheckViolationError("internal wallet error")
            if not any(row[0] == args[0] for row in self.store["wallets"]):
                self.store["wallets"].append(args)
        elif "INSERT INTO public.users" in sql:
            self.store["users"].append(args)
        elif "INSERT INTO public.margin_rules" in sql:
            self.store["margins"].append(args)
        elif "INSERT INTO public.admin_configuration_events" in sql:
            self.store["events"][(args[1], args[2], args[3])] = {"payload_sha256": args[5], "response": args[6]}
        return "INSERT 0 1"


def pool(connection):
    return SimpleNamespace(acquire=lambda: Acquire(connection))


class AdminHTTPTests(unittest.TestCase):
    def setUp(self):
        self.connection = Connection()
        self.owner, self.customer = uuid4(), uuid4()
        self.key = ec.generate_private_key(ec.SECP256R1())
        main.app.state.local_preview = False
        main.app.state.settings = SimpleNamespace(platform_admin_user_ids=[self.owner], jwt_algorithm="ES256", jwt_audience="authenticated", supabase_url="https://fixture.supabase.co")
        main.app.state.jwks = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=self.key.public_key()))
        main.app.state.admin_portal = AdminService(pool(self.connection))
        main.app.state.finance = SimpleNamespace(pool=pool(self.connection))
        self.client = TestClient(main.app)
    def tearDown(self): main.app.dependency_overrides.clear()
    def token(self, user_id, **extra):
        now = int(time.time())
        claims = {"sub": str(user_id), "role": "authenticated", "aud": "authenticated", "iss": "https://fixture.supabase.co/auth/v1", "iat": now, "exp": now + 60, **extra}
        return jwt.encode(claims, self.key, algorithm="ES256", headers={"kid": "fixture-key"})
    def headers(self, user_id=None): return {"Authorization": "Bearer " + self.token(user_id or self.owner)}
    def tenant_body(self, **extra): return {"company_profile": company(), "billing_plan": "PREPAID_WALLET", **extra}

    def test_platform_owner_can_bootstrap_without_tenant_claim(self):
        auth_user = uuid4()
        response = self.client.post("/api/v1/admin/tenants", json=self.tenant_body(owner_auth_user_id=str(auth_user)), headers=self.headers())
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data["company_profile"]["country_code"], "GB")
        self.assertEqual(data["billing_plan"], "PREPAID_WALLET")
        self.assertTrue(data["wallet_provisioned"])
        self.assertEqual(len(self.connection.store["wallets"]), 1)
        self.assertEqual(self.connection.store["users"][0][2], auth_user)
        self.assertEqual(len(self.connection.store["events"]), 1)

    def test_customer_owner_cannot_administer_platform(self):
        headers = {"Authorization": "Bearer " + self.token(self.customer, tenant_id=str(uuid4()), app_metadata={"role": "OWNER", "platform_admin": True})}
        response = self.client.post("/api/v1/admin/tenants", json=self.tenant_body(), headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.connection.calls, [])

    def test_missing_expired_and_tampered_tokens(self):
        body = self.tenant_body()
        self.assertEqual(self.client.post("/api/v1/admin/tenants", json=body).status_code, 401)
        expired = {"Authorization": "Bearer " + self.token(self.owner, exp=int(time.time()) - 30)}
        self.assertEqual(self.client.post("/api/v1/admin/tenants", json=body, headers=expired).status_code, 401)
        other_key = ec.generate_private_key(ec.SECP256R1())
        tampered = jwt.encode({"sub": str(self.owner)}, other_key, algorithm="ES256", headers={"kid": "fixture-key"})
        self.assertEqual(self.client.post("/api/v1/admin/tenants", json=body, headers={"Authorization": "Bearer " + tampered}).status_code, 401)

    def test_registration_retry_is_idempotent(self):
        body = self.tenant_body(request_id=str(uuid4()))
        first = self.client.post("/api/v1/admin/tenants", json=body, headers=self.headers())
        second = self.client.post("/api/v1/admin/tenants", json=body, headers=self.headers())
        self.assertEqual(first.json(), second.json())
        self.assertEqual(len(self.connection.store["tenants"]), 1)
        self.assertEqual(len(self.connection.store["wallets"]), 1)
        conflict = self.client.post("/api/v1/admin/tenants", json={**body, "billing_plan": "POSTPAID_30_DAY"}, headers=self.headers())
        self.assertEqual(conflict.status_code, 409)

    def test_failed_wallet_rolls_back_tenant_and_hides_database_error(self):
        self.connection.fail_wallet = True
        response = self.client.post("/api/v1/admin/tenants", json=self.tenant_body(), headers=self.headers())
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("internal wallet error", response.text)
        self.assertEqual(self.connection.store["tenants"], {})
        self.assertEqual(self.connection.rollbacks, 1)

    def test_unknown_auth_user_cannot_leave_partial_account(self):
        self.connection.owner_exists = False
        response = self.client.post("/api/v1/admin/tenants", json=self.tenant_body(owner_auth_user_id=str(uuid4())), headers=self.headers())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.connection.store["tenants"], {})

    def test_postpaid_registration(self):
        response = self.client.post("/api/v1/admin/tenants", json=self.tenant_body(billing_plan="POSTPAID_30_DAY", default_currency="EUR"), headers=self.headers())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["billing_plan"], "POSTPAID_30_DAY")
        self.assertEqual(self.connection.store["wallets"][0][1], "EUR")

    def test_wallet_trigger_compatibility_and_currency_guard(self):
        self.connection.auto_wallet_currency = "GBP"
        response = self.client.post("/api/v1/admin/tenants", json=self.tenant_body(), headers=self.headers())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.connection.store["wallets"]), 1)
        mismatch = self.client.post("/api/v1/admin/tenants", json=self.tenant_body(default_currency="EUR"), headers=self.headers())
        self.assertEqual(mismatch.status_code, 409)
        self.assertEqual(len(self.connection.store["tenants"]), 1)

    def test_margin_is_saved_as_decimal_and_country_normalized(self):
        tenant_id = uuid4()
        self.connection.store["tenants"][tenant_id] = {"default_currency": "USD", "workspace_status": "ACTIVE"}
        body = {"request_id": str(uuid4()), "tenant_id": str(tenant_id), "destination_country": "USA", "carrier_code": " dhl ", "markup_type": "PERCENTAGE", "markup_value": "17.125", "priority": 3}
        first = self.client.post("/api/v1/admin/margins", json=body, headers=self.headers())
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()["destination_country"], "US")
        self.assertEqual(first.json()["currency"], "USD")
        stored = self.connection.store["margins"][0]
        self.assertEqual(stored[1], tenant_id)
        self.assertEqual(stored[3], "DHL")
        self.assertEqual(stored[6], "US")
        self.assertEqual(stored[13], Decimal("17.125"))
        self.assertIsInstance(stored[13], Decimal)
        second = self.client.post("/api/v1/admin/margins", json=body, headers=self.headers())
        self.assertEqual(first.json(), second.json())
        self.assertEqual(len(self.connection.store["margins"]), 1)

    def test_margin_validation_and_unknown_target(self):
        body = {"tenant_id": str(uuid4()), "destination_country": "USA", "markup_type": "FLAT_RATE", "markup_value": "2.50"}
        self.assertEqual(self.client.post("/api/v1/admin/margins", json=body, headers=self.headers()).status_code, 404)
        for fields in ({"markup_value": 2.5}, {"markup_value": "-1"}, {"markup_value": "NaN"}, {"markup_value": "2.501"}, {"destination_country": "XYZ"}, {"priority": True}):
            self.assertEqual(self.client.post("/api/v1/admin/margins", json={**body, **fields}, headers=self.headers()).status_code, 422)

    def test_carrier_account_cannot_cross_tenants(self):
        tenant_id = uuid4()
        self.connection.store["tenants"][tenant_id] = {"default_currency": "GBP"}
        self.connection.account_exists = False
        body = {"tenant_id": str(tenant_id), "carrier_account_id": str(uuid4()), "markup_type": "FLAT_RATE", "markup_value": "2.50"}
        self.assertEqual(self.client.post("/api/v1/admin/margins", json=body, headers=self.headers()).status_code, 422)
        self.assertEqual(self.connection.store["margins"], [])
        sql, args = next(call for call in self.connection.calls if "public.carrier_accounts" in call[0])
        self.assertEqual(args[0], tenant_id)
        self.assertIn("tenant_id=$1", sql)

    def test_admin_preview_disabled(self):
        main.app.state.local_preview = True
        response = self.client.post("/api/v1/admin/tenants", json=self.tenant_body(), headers=self.headers())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.connection.calls, [])


class PricingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = Connection()
        self.tenant = uuid4()
        self.connection.store["tenants"][self.tenant] = {"default_currency": "USD", "workspace_status": "ACTIVE"}
        configure_pricing_pool(pool(self.connection))
    async def asyncTearDown(self): configure_pricing_pool(None)

    async def test_exact_signature_queries_tenant_currency_and_matching_rule(self):
        self.connection.rule = {"tenant_id": self.tenant, "markup_type": "PERCENTAGE", "markup_value": Decimal("12.5"), "minimum_markup": Decimal("0"), "maximum_markup": None}
        result = await get_client_calibrated_rate(self.tenant, Decimal("8.33"), "dhl", "USA")
        self.assertEqual(result, Decimal("9.37"))
        sql, args = self.connection.calls[-1]
        self.assertEqual(args[:4], (self.tenant, "USD", "DHL", ["US", "USA"]))
        self.assertIn("tenant_id=$1", sql)
        self.assertIn("ORDER BY priority ASC", sql)
        self.assertIn("created_at ASC,id ASC LIMIT 1", sql)
        self.assertIn("valid_until > $10", sql)
        self.assertEqual(self.connection.transactions[-1], {"isolation": "repeatable_read", "readonly": True})

    async def test_flat_rate_fallback_and_clamps(self):
        self.assertEqual(await get_client_calibrated_rate(self.tenant, Decimal("8.33"), "DHL", "US"), Decimal("10.00"))
        self.connection.rule = {"tenant_id": self.tenant, "markup_type": "FLAT_RATE", "markup_value": Decimal("2.50"), "minimum_markup": Decimal("0"), "maximum_markup": None}
        self.assertEqual(await get_client_calibrated_rate(self.tenant, Decimal("8.33"), "DHL", "US"), Decimal("10.83"))
        self.connection.rule.update(markup_type="PERCENTAGE", markup_value=Decimal("100"), minimum_markup=Decimal("1"), maximum_markup=Decimal("3"))
        self.assertEqual(await get_client_calibrated_rate(self.tenant, Decimal("8.33"), "DHL", "US"), Decimal("11.33"))
        self.connection.rule.update(markup_value=Decimal("0"), minimum_markup=Decimal("0"), maximum_markup=None)
        self.assertEqual(await get_client_calibrated_rate(self.tenant, Decimal("900000000000"), "DHL", "US"), Decimal("900000000000.00"))

    async def test_wrong_tenant_and_unknown_tenant_fail_closed(self):
        self.connection.rule = {"tenant_id": uuid4(), "markup_type": "FLAT_RATE", "markup_value": Decimal("0")}
        with self.assertRaises(main.HTTPException) as error:
            await get_client_calibrated_rate(self.tenant, Decimal("10"), "DHL", "US")
        self.assertEqual(error.exception.status_code, 503)
        with self.assertRaises(main.HTTPException) as error:
            await get_client_calibrated_rate(uuid4(), Decimal("10"), "DHL", "US")
        self.assertEqual(error.exception.status_code, 404)

    async def test_scope_includes_all_existing_selectors(self):
        account_id = uuid4()
        with calibrated_pricing_scope(pool(self.connection), currency="EUR", origin="GBR", carrier_account_id=account_id, service_code="express", weight_kg=Decimal("4.800")):
            await get_client_calibrated_rate(self.tenant, Decimal("10"), "DHL", "US")
        args = self.connection.calls[-1][1]
        self.assertEqual(args[1], "EUR")
        self.assertEqual(args[4:8], (account_id, ["GB", "GBR"], "EXPRESS", Decimal("4.800")))
        await get_client_calibrated_rate(self.tenant, Decimal("10"), "DHL", "US")
        self.assertEqual(self.connection.calls[-1][1][1], "USD")

    async def test_whatsapp_transaction_does_not_need_second_pool_slot(self):
        from backend.admin_portal import borrowed_pricing_connection
        with borrowed_pricing_connection(self.connection):
            with calibrated_pricing_scope(SimpleNamespace(acquire=lambda: (_ for _ in ()).throw(AssertionError("Second pool slot acquired")))):
                price = await get_client_calibrated_rate(self.tenant, Decimal("10.00"), "DHL", "USA")
        self.assertEqual(price, Decimal("12.00"))
        self.assertEqual(self.connection.transactions, [])
        await get_client_calibrated_rate(self.tenant, Decimal("10.00"), "DHL", "US")
        self.assertEqual(len(self.connection.transactions), 1)

    async def test_concurrent_scopes_are_isolated(self):
        async def price(currency):
            with calibrated_pricing_scope(pool(self.connection), currency=currency):
                await asyncio.sleep(0)
                await get_client_calibrated_rate(self.tenant, Decimal("10"), "DHL", "US")
        await asyncio.gather(price("GBP"), price("EUR"))
        currencies = [args[1] for sql, args in self.connection.calls if "public.margin_rules" in sql]
        self.assertCountEqual(currencies, ["GBP", "EUR"])

    async def test_decimal_input_and_corrupt_stored_rule(self):
        for value in (10.0, True, Decimal("NaN"), Decimal("-1")):
            with self.assertRaises(ValueError):
                await get_client_calibrated_rate(self.tenant, value, "DHL", "US")
        self.connection.rule = {"tenant_id": self.tenant, "markup_type": "UNKNOWN", "markup_value": Decimal("1")}
        with self.assertRaises(main.HTTPException):
            await get_client_calibrated_rate(self.tenant, Decimal("10"), "DHL", "US")


class LivePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_tenants_receive_different_prices_for_same_wholesale(self):
        tenant_a, tenant_b = uuid4(), uuid4()
        class MatrixConnection(Connection):
            async def fetch(self, sql, *args):
                assert 'FROM public.shipments' in sql
                return []
            async def fetchrow(self, sql, *args):
                if "public.margin_rules" in sql:
                    self.calls.append((sql, args))
                    return {"tenant_id": args[0], "markup_type": "PERCENTAGE", "markup_value": Decimal("10") if args[0] == tenant_a else Decimal("25"), "minimum_markup": Decimal("0"), "maximum_markup": None}
                return await super().fetchrow(sql, *args)
        connection = MatrixConnection()
        for tenant in (tenant_a, tenant_b):
            connection.store["tenants"][tenant] = {"default_currency": "GBP", "workspace_status": "ACTIVE"}
        accounts = {tenant_a: uuid4(), tenant_b: uuid4()}
        class Repository:
            async def accounts(self, context):
                return [SimpleNamespace(provider="EASYPOST", id=accounts[context.tenant_id])]
            async def load(self, *args):
                raise AssertionError("Live pricing must use the database evaluator")
        service = main.RatingService(None, Repository(), SimpleNamespace(max_parallel_provider_requests=4, provider_deadline_seconds=5, quote_ttl_seconds=300), pool=pool(connection))
        async def run(strategy, request, deadline):
            return [main.WholesaleRate(provider="EASYPOST", account_id=strategy.account.id,
                    upstream_shipment_id="shipment", upstream_rate_id="rate", carrier_code="DHL",
                    service_code="EXPRESS", currency="GBP", wholesale_cost="10.00")], None
        service.run_provider = run
        from test_logistics import payload
        request = main.RatingRequest.model_validate(payload())
        results = await asyncio.gather(*(service.quote(main.TenantContext(tenant, uuid4(), "OWNER", "fixture"), request) for tenant in (tenant_a, tenant_b)))
        self.assertEqual([result.rates[0].client_price_ex_tax for result in results], [Decimal("11.00"), Decimal("12.50")])
        self.assertEqual([result.rates[0].fee_breakdown["platform_markup"] for result in results], ["1.00", "2.50"])
        self.assertCountEqual([args[0] for sql, args in connection.calls if "public.margin_rules" in sql], [tenant_a, tenant_b])


if __name__ == "__main__":
    unittest.main()
