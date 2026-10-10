import json
import unittest
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.hubspot_crm import CRMError, HubSpotClient, HubSpotService, HubSpotSettings, build_router, retry_seconds, spend_string


def settings():
    return HubSpotSettings(_env_file=None, hubspot_access_token="pat-local-test",hubspot_expected_portal_id=12345,hubspot_upsell_enabled=True, hubspot_upsell_pipeline_id="pipeline1", hubspot_upsell_stage_id="stage1")


class Merchant:
    def __init__(self):
        self.records = {"companies": [], "contacts": [], "deals": []}
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        assert request.url.host == "api.hubapi.com"
        assert request.headers["authorization"] == "Bearer pat-local-test"
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path=='/account-info/v3/details':return httpx.Response(200,json={'portalId':12345,'accountType':'DEVELOPER_TEST'})
        if path.startswith("/crm/v3/properties/"):
            numeric=path.rsplit('/',1)[-1] in {'veloce_package_count','veloce_total_shipments','veloce_total_spend','veloce_wallet_balance'}
            return httpx.Response(200, json={"hasUniqueValue": True,'type':'number' if numeric else 'string','fieldType':'number' if numeric else 'text'})
        if path.startswith("/crm/v3/pipelines/"):
            return httpx.Response(200, json={"stages": [{"id": "stage1"}]})
        if path.startswith("/crm/v3/associations/"):
            return httpx.Response(201, json={"status": "COMPLETE", "results": body["inputs"]})
        parts = path.split("/")
        object_type = parts[4]
        if path.endswith("/search"):
            selector = body["filterGroups"][0]["filters"][0]
            rows = [r for r in self.records[object_type] if r["properties"].get(selector["propertyName"]) == selector["value"]]
            return httpx.Response(200, json={"results": rows})
        if request.method == "POST":
            record = {"id": str(len(self.calls)), "properties": body["properties"]}
            self.records[object_type].append(record)
            return httpx.Response(201, json=record)
        if request.method == "PATCH":
            record = next(r for r in self.records[object_type] if r["id"] == parts[5])
            record["properties"].update(body["properties"])
            return httpx.Response(200, json=record)
        return httpx.Response(404)


class HubSpotTests(unittest.IsolatedAsyncioTestCase):
    async def test_companies_contacts_onboard_without_deal_configuration(self):
        merchant=Merchant();config=settings().model_copy(update={'hubspot_upsell_enabled':False,'hubspot_upsell_pipeline_id':'','hubspot_upsell_stage_id':''})
        async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as http:
            client=HubSpotClient(http,config);tenant=uuid4()
            company=await client.onboard(tenant,'Sandbox Company','test@example.invalid','GB123',address={'line1':'1 Test Street','city':'London','postal_code':'SW1A 1AA','country_code':'GB'})
            self.assertIsNone(await client.milestone(tenant,company,'Sandbox Company',100,Decimal('123.45'),'GBP'))
        self.assertFalse(any('/deals' in str(r.url) for r in merchant.calls))
        properties=merchant.records['companies'][0]['properties']
        self.assertEqual(properties['street'],'1 Test Street');self.assertEqual(properties['veloce_total_spend'],'123.45')
        self.assertEqual(merchant.records['contacts'][0]['properties'],{'email':'test@example.invalid'})

    async def test_account_mismatch_and_standard_account_block_before_writes(self):
        for response,code in [({'portalId':99999,'accountType':'DEVELOPER_TEST'},'hubspot_account_mismatch'),({'portalId':12345,'accountType':'STANDARD'},'hubspot_test_account_required')]:
            calls=[]
            def transport(request):calls.append(request);return httpx.Response(200,json=response)
            async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
                with self.assertRaises(CRMError) as error:await HubSpotClient(http,settings()).onboard(uuid4(),'Sandbox','test@example.invalid','')
                self.assertEqual(error.exception.code,code)
            self.assertEqual([r.method for r in calls],['GET'])

    async def test_property_type_and_ambiguous_create_fail_securely(self):
        merchant=Merchant()
        def wrong_type(request):
            if request.url.path.endswith('/veloce_package_count'):return httpx.Response(200,json={'type':'string','fieldType':'text'})
            return merchant(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(wrong_type)) as http:
            with self.assertRaises(CRMError) as error:await HubSpotClient(http,settings()).onboard(uuid4(),'Sandbox','test@example.invalid','')
            self.assertEqual(error.exception.code,'hubspot_property_type_mismatch')
        calls=[]
        def uncertain(request):calls.append(request);return httpx.Response(503,text='sensitive response not retained')
        async with httpx.AsyncClient(transport=httpx.MockTransport(uncertain)) as http:
            with self.assertRaises(CRMError) as error:await HubSpotClient(http,settings()).request('POST','/crm/v3/objects/companies',{'properties':{'name':'Sandbox'}})
            self.assertEqual(error.exception.code,'hubspot_create_outcome_uncertain')
        self.assertEqual(len(calls),1)

    async def test_environment_placeholder_and_secret_validation(self):
        from pydantic import ValidationError
        config=HubSpotSettings(_env_file=None,hubspot_expected_portal_id='',hubspot_access_token='  pat-local-test  ')
        self.assertIsNone(config.hubspot_expected_portal_id)
        self.assertEqual(config.hubspot_access_token.get_secret_value(),'pat-local-test')
        with self.assertRaises(ValidationError) as error:HubSpotSettings(_env_file=None,hubspot_access_token='Bearer pat-sensitive-value')
        self.assertNotIn('pat-sensitive-value',str(error.exception))
        with self.assertRaises(ValidationError):HubSpotSettings(_env_file=None,hubspot_enabled=True)
        with self.assertRaises(ValidationError):HubSpotSettings(_env_file=None,hubspot_upsell_pipeline_id='../contacts')

    async def test_onboarding_replay_and_same_company_names_distinct_tenants(self):
        merchant = Merchant()
        async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as http:
            client = HubSpotClient(http, settings())
            tenant = uuid4()
            company = await client.onboard(tenant, "Acme", "alex@example.com", "GB123")
            self.assertEqual(await client.onboard(tenant, "Acme", "alex@example.com", "GB123"), company)
            other = await client.onboard(uuid4(), "Acme", "bob@example.com", "GB999")
            self.assertNotEqual(company, other)
        self.assertEqual(len(merchant.records["companies"]), 2)
        self.assertEqual(len(merchant.records["contacts"]), 2)
        associations = [r for r in merchant.calls if "/associations/contacts/companies/" in r.url.path]
        self.assertEqual(json.loads(associations[0].content)["inputs"][0]["type"], "contact_to_company")

    async def test_milestone_exact_decimal_threshold_and_single_upsell(self):
        merchant = Merchant()
        async with httpx.AsyncClient(transport=httpx.MockTransport(merchant)) as http:
            client = HubSpotClient(http, settings())
            tenant = uuid4()
            company = await client.onboard(tenant, "Acme", "alex@example.com", "GB123")
            self.assertIsNone(await client.milestone(tenant, company, "Acme", 50, Decimal("1234.50"), "GBP"))
            deal = await client.milestone(tenant, company, "Acme", 51, Decimal("1300.75"), "GBP")
            self.assertEqual(await client.milestone(tenant, company, "Acme", 75, Decimal("1500.90"), "GBP"), deal)
        self.assertEqual(len(merchant.records["deals"]), 1)
        self.assertEqual(merchant.records["companies"][0]["properties"]["veloce_total_spend"], "1500.90")
        self.assertEqual(merchant.records["deals"][0]["properties"]["dealstage"], "stage1")

    async def test_rate_limit_backoff_and_retry_after(self):
        calls, sleeps = [], []
        def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={"Retry-After": "3"}) if len(calls) < 3 else httpx.Response(200, json={"ok": True})
        async def sleep(seconds):
            sleeps.append(seconds)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await HubSpotClient(http, settings(), sleep=sleep).request("GET", "/crm/v3/properties/companies")
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(s >= 3 for s in sleeps))

    async def test_long_rate_limit_deferred_and_no_secret_errors(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "120"}, text="secret remote body"))) as http:
            with self.assertRaises(CRMError) as raised:
                await HubSpotClient(http, settings()).request("POST", "/crm/v3/objects/companies", {})
        self.assertEqual(raised.exception.retry_after, 120)
        self.assertNotIn("secret", str(raised.exception))

    async def test_authentication_failure_is_not_retried(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(401, text="do not log this token")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with self.assertRaises(CRMError) as raised:
                await HubSpotClient(http, settings()).request("GET", "/crm/v3/objects/companies")
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(len(calls), 1)

    async def test_unique_properties_required_before_creating_records(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'portalId':12345,'accountType':'DEVELOPER_TEST'} if r.url.path=='/account-info/v3/details' else {"hasUniqueValue": False}))) as http:
            with self.assertRaises(CRMError) as raised:
                await HubSpotClient(http, settings()).onboard(uuid4(), "Acme", "alex@example.com", "")
        self.assertEqual(raised.exception.code, "hubspot_unique_property_required")

    async def test_decimal_validation_and_retry_headers(self):
        for value in [1.1, Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), Decimal("1.001")]:
            with self.assertRaises(ValueError):
                spend_string(value)
        self.assertEqual(spend_string(Decimal("1")), "1.00")
        self.assertEqual(retry_seconds("garbage"), 0)
        self.assertEqual(retry_seconds("NaN"), 0)

    async def test_queued_endpoint_tenant_role_and_disabled_checks(self):
        tenant = uuid4()
        context = SimpleNamespace(tenant_id=tenant, role="OWNER")
        queued = []
        async def enqueue(value):
            queued.append(value)
        async def authenticate():
            return context
        app = FastAPI()
        app.state.hubspot = SimpleNamespace(enqueue=enqueue)
        app.include_router(build_router(authenticate))
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/v1/crm/sync-tenant", json={"tenant_id": str(tenant)}).status_code, 202)
            self.assertEqual(client.post("/api/v1/crm/sync-tenant", json={"tenant_id": str(uuid4())}).status_code, 403)
            context.role = "DISPATCHER"
            self.assertEqual(client.post("/api/v1/crm/sync-tenant", json={"tenant_id": str(tenant)}).status_code, 403)
            context.role = "ADMIN"
            app.state.hubspot = None
            self.assertEqual(client.post("/api/v1/crm/sync-tenant", json={"tenant_id": str(tenant)}).status_code, 503)
        self.assertEqual(queued, [tenant])

    async def test_service_uses_tenant_totals_and_blocks_mixed_currency(self):
        tenant = uuid4()
        class DB:
            @asynccontextmanager
            async def acquire(self):
                yield self
            async def fetchrow(self, sql, *args):
                self.sql, self.args = sql, args
                return {"package_count": 51, "total_spend": Decimal("123.45"), "mixed_currency": 1}
        db = DB()
        with self.assertRaises(CRMError):
            await HubSpotService(db, None).totals(db, tenant)
        self.assertIn("s.tenant_id=$1", db.sql)
        self.assertEqual(db.args, (tenant,))

    async def test_worker_persists_delivery_and_preserves_new_revision(self):
        tenant_id = uuid4()
        class DB:
            def __init__(self):
                self.revision, self.deleted, self.linked, self.unlocked = 1, False, False, False
            @asynccontextmanager
            async def acquire(self):
                yield self
            async def fetchval(self, sql, *args):
                return True
            async def fetchrow(self, sql, *args):
                if "revision,attempts" in sql:
                    return {"revision": self.revision, "attempts": 0}
                if "company_profile" in sql:
                    return {"company_name": "Acme", "company_profile": {"billing_email": "alex@example.com"}, "default_currency": "GBP"}
                return {"package_count": 51, "total_spend": Decimal("123.45"), "mixed_currency": 0}
            async def execute(self, sql, *args):
                if "INSERT INTO public.hubspot_tenant_links" in sql:
                    self.linked = True
                if "DELETE FROM" in sql:
                    self.deleted = args[1] == self.revision
                if "pg_advisory_unlock" in sql:
                    self.unlocked = True
        db = DB()
        class Client:
            async def onboard(self, *args):
                db.revision += 1  # A shipment commits while CRM HTTP is in flight.
                return "10"
            async def milestone(self, *args):
                return "20"
        await HubSpotService(db, Client()).process(tenant_id)
        self.assertTrue(db.linked)
        self.assertTrue(db.unlocked)
        self.assertFalse(db.deleted)

    async def test_worker_blocks_permanent_failure_and_unlocks(self):
        class DB:
            @asynccontextmanager
            async def acquire(self):
                yield self
            async def fetchval(self, sql, *args):
                return True
            async def fetchrow(self, sql, *args):
                if "revision,attempts" in sql:
                    return {"revision": 1, "attempts": 0}
                return {"company_name": "Acme", "company_profile": {"billing_email": "alex@example.com"}, "default_currency": "GBP"}
            async def execute(self, sql, *args):
                if "UPDATE public.hubspot_sync_jobs" in sql:
                    self.failure = args
                if "pg_advisory_unlock" in sql:
                    self.unlocked = True
        class Client:
            async def onboard(self, *args):
                raise CRMError("hubspot_http_401", retryable=False)
        db = DB()
        await HubSpotService(db, Client()).process(uuid4())
        self.assertEqual(db.failure[3], "hubspot_http_401")
        self.assertTrue(db.failure[4])
        self.assertTrue(db.unlocked)


if __name__ == "__main__":
    unittest.main()
