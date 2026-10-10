import json
import unittest
from decimal import Decimal
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.ecommerce_sync import EcommerceService, ImportPayload, parsed_order, tracking_link, build_router


def payload(store_id):
    return {"store_id": str(store_id), "platform": "SHOPIFY", "topic": "orders/paid",
            "order": {"id": 123, "name": "#1024", "currency": "GBP",
                      "shipping_address": {"name": "Alex", "address1": "12 Road", "city": "London", "zip": "SW1A 1AA", "country_code": "GBR"},
                      "line_items": [{"title": "Silk shoes", "quantity": 3, "grams": "150.25"}]}}


class Database:
    def __init__(self, tenant, store):
        self.tenant, self.store = tenant, store
        self.shipments, self.events = {}, {}

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        yield

    async def fetchrow(self, sql, *args):
        if 'FROM public.users' in sql:
            return {'id': self.tenant} if args[0] == self.tenant else None
        if 'FROM public.tenants' in sql:
            return {'legal_company_name':'Test warehouse','billing_address':{'line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}}
        if "FROM public.ecommerce_stores" in sql:
            return {"platform": "SHOPIFY"} if args == (self.tenant, self.store) else None
        if "store_import_hash FROM" in sql:
            return self.shipments.get(args)
        if "SELECT ecommerce_store_id" in sql:
            for row in self.shipments.values():
                if args == (self.tenant, row["id"]):
                    return row
        return None

    async def execute(self, sql, *args):
        if "INSERT INTO public.shipments" in sql:
            sid, tenant, currency, store, order, digest, metadata = args[:7]
            assert 'final_client_price' not in sql
            assert args[13] == Decimal('0.451')
            self.shipments[(tenant, store, order)] = {"id": sid, "status": "PENDING_IMPORT", "store_import_hash": digest,
                                                       "ecommerce_store_id": store, "store_order_id": order}
        elif "INSERT INTO public.ecommerce_tracking_outbox" in sql:
            tenant, sid, store, order, body = args
            self.events.setdefault((tenant, sid), {"id": uuid4(), "tenant_id": tenant, "store_order_id": order,
                                                    "payload": body, "status": "PENDING", "attempts": 0})
        elif "UPDATE public.ecommerce_tracking_outbox" in sql:
            for row in self.events.values():
                if (row["tenant_id"], row["id"]) == args[:2]:
                    row["status"] = "SIMULATED_DELIVERED"
                    row["attempts"] += 1
                    row["response"] = json.loads(args[2])

    async def fetch(self, sql, *args):
        if not args:
            return [row for row in self.events.values() if row["status"] == "PENDING"]
        return [row for row in self.events.values() if (row["tenant_id"], row["store_order_id"]) == args]


class EcommerceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tenant, self.store = uuid4(), uuid4()
        self.database = Database(self.tenant, self.store)
        self.service = EcommerceService(self.database)
        self.context = SimpleNamespace(tenant_id=self.tenant, user_id=uuid4(), role="DISPATCHER")

    async def test_exact_import_replay_and_changed_payload(self):
        data = ImportPayload.model_validate(payload(self.store))
        first = await self.service.import_order(self.context, data)
        self.assertEqual(first["total_weight_kg"], "0.45075")
        self.assertEqual(first["shipping_address"]["country_code"], "GB")
        second = await self.service.import_order(self.context, data)
        self.assertTrue(second["replayed"])
        self.assertEqual(first["shipment_id"], second["shipment_id"])
        data.order.shipping_address.city = "York"
        with self.assertRaises(HTTPException) as raised:
            await self.service.import_order(self.context, data)
        self.assertEqual(raised.exception.status_code, 409)

    async def test_tenant_and_permission_isolation(self):
        data = ImportPayload.model_validate(payload(self.store))
        for context, status in [(SimpleNamespace(tenant_id=uuid4(), role="ADMIN"), 404),
                                (SimpleNamespace(tenant_id=self.tenant, role="ACCOUNTANT"), 403)]:
            with self.assertRaises(HTTPException) as raised:
                await self.service.import_order(context, data)
            self.assertEqual(raised.exception.status_code, status)
        self.assertFalse(self.database.shipments)

    async def test_outbox_simulation_retry_idempotency_and_tenant_isolation(self):
        imported = await self.service.import_order(self.context, ImportPayload.model_validate(payload(self.store)))
        from uuid import UUID
        await self.service.queue_confirmed_tracking(self.database, self.tenant, UUID(imported["shipment_id"]), "1Z123", "UPS")
        with self.assertRaises(HTTPException):
            await self.service.push(uuid4(), "123", "1Z123", "UPS")
        await self.service.retry_pending()
        await self.service.push(self.tenant, "123", "1Z123", "UPS")
        event = next(iter(self.database.events.values()))
        self.assertEqual(event["attempts"], 1)
        self.assertTrue(event["response"]["simulated"])
        self.assertEqual(json.loads(event["payload"])["fulfillment_state"], "SHIPPED")

    async def test_validation_limits(self):
        for changed in [0, "NaN", -1]:
            data = payload(self.store)
            data["order"]["line_items"][0]["grams"] = changed
            with self.assertRaises(ValueError):
                parsed_order(ImportPayload.model_validate(data).order)
        data = payload(self.store)
        data["order"]["line_items"][0]["quantity"] = True
        with self.assertRaises(ValueError):
            ImportPayload.model_validate(data)
        self.assertIsNone(tracking_link("unknown", "123"))
        self.assertIn("A%26B", tracking_link("UPS", "A&B"))

    async def test_http_import_and_invalid_body(self):
        app = FastAPI()
        app.state.ecommerce = self.service
        async def authenticate():
            return self.context
        app.include_router(build_router(authenticate))
        with TestClient(app) as client:
            response = client.post("/api/v1/integration/pull-orders", json=payload(self.store))
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["status"], "PENDING_IMPORT")
            self.assertEqual(client.post("/api/v1/integration/pull-orders", json={"tenant_id": str(uuid4())}).status_code, 422)
            self.assertEqual(client.post("/api/v1/integration/pull-orders", content="{}").status_code, 415)


if __name__ == "__main__":
    unittest.main()
