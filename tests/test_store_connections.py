import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pydantic import SecretStr

from backend.ecommerce_connectors import StoreConnector, shopify_access_token
from backend.store_connections import build_router, resolve_connector


class StoreConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tenant, self.store, self.actor = uuid4(), uuid4(), uuid4()
        self.context = SimpleNamespace(tenant_id=self.tenant, user_id=self.actor, role='OWNER')
        self.rows = {}
        self.key = Fernet.generate_key()
        test = self
        class Pool:
            @asynccontextmanager
            async def acquire(self): yield self
            @asynccontextmanager
            async def transaction(self): yield self
            async def fetchrow(self, sql, *args):
                if 'FROM public.ecommerce_stores' in sql:
                    return {'platform': 'SHOPIFY', 'is_active': True} if args == (test.tenant, test.store) else None
                return test.rows.get(test.store) if args[-1] == test.store else None
            async def execute(self, sql, *args):
                if sql.startswith('INSERT'):
                    test.rows[args[1]] = dict(tenant_id=args[0], credentials_ciphertext=args[2], credential_key_id=args[3])
        self.service = SimpleNamespace(pool=Pool(), connectors={}, credential_keys={'k': SecretStr(self.key.decode())})
        self.app = FastAPI(); self.app.state.ecommerce = self.service
        async def authenticate(): return self.context
        self.app.include_router(build_router(authenticate))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')
        self.url = '/api/v1/workspace/stores/' + str(self.store) + '/connection'
        self.body = {'shop_domain': 'test-shop.myshopify.com', 'access_token': 'private-test-token',
                     'sku_unit_grams': {'TEE': '200'}, 'live_import': True}

    async def asyncTearDown(self): await self.client.aclose()

    async def test_encrypted_bound_write_only_and_blank_preserves_credentials(self):
        response = await self.client.put(self.url, json=self.body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('private-test-token', response.text)
        raw = self.rows[self.store]['credentials_ciphertext']
        self.assertNotIn(b'private-test-token', raw)
        body = json.loads(Fernet(self.key).decrypt(raw))
        self.assertEqual(body['store_id'], str(self.store)); self.assertEqual(body['tenant_id'], str(self.tenant))
        self.assertEqual(body['access_token'], 'private-test-token')
        response = await self.client.get(self.url)
        self.assertNotIn('private-test-token', response.text)
        update = {k: v for k, v in self.body.items() if k != 'access_token'}
        update['access_token'] = ''
        self.assertEqual((await self.client.put(self.url, json=update)).status_code, 200)
        config = await resolve_connector(self.service, self.store)
        self.assertEqual(config.access_token.get_secret_value(), 'private-test-token')

    async def test_role_and_tenant_boundaries(self):
        for role in ('ACCOUNTANT', 'DISPATCHER'):
            self.context.role = role
            self.assertEqual((await self.client.put(self.url, json=self.body)).status_code, 403)
            self.assertEqual((await self.client.get(self.url)).status_code, 403)
        self.context.role = 'OWNER'; self.context.tenant_id = uuid4()
        self.assertEqual((await self.client.put(self.url, json=self.body)).status_code, 404)
        self.assertFalse(self.rows)

    async def test_invalid_domain_weights_credentials_never_saved(self):
        for change in ({'shop_domain': '127.0.0.1'}, {'shop_domain': 'test-shop.myshopify.com/evil'},
                       {'sku_unit_grams': {'TEE': '-1'}}, {'access_token': None}, {'client_id': 'missing-secret'}):
            response = await self.client.put(self.url, json={**self.body, **change})
            self.assertEqual(response.status_code, 422, response.text)
            self.assertFalse(self.rows)

    async def test_corrupt_envelope_rejected(self):
        await self.client.put(self.url, json=self.body)
        body = json.loads(Fernet(self.key).decrypt(self.rows[self.store]['credentials_ciphertext']))
        body['tenant_id'] = str(uuid4())
        self.rows[self.store]['credentials_ciphertext'] = Fernet(self.key).encrypt(json.dumps(body).encode())
        self.assertEqual((await self.client.get(self.url)).status_code, 503)

    async def test_new_dashboard_client_credentials_renew_without_logging(self):
        config = StoreConnector(tenant_id=self.tenant, auth_user_id=self.actor, platform='SHOPIFY',
            shop_domain='test-shop.myshopify.com', webhook_secret='x'*32, live_import=True,
            client_id='app-client', client_secret='private-app-secret')
        calls = []
        def transport(request):
            calls.append(request)
            return httpx.Response(200, json={'access_token': 'renewed-test-token', 'expires_in': 86400})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            self.assertEqual(await shopify_access_token(client, config), 'renewed-test-token')
        self.assertEqual(str(calls[0].url), 'https://test-shop.myshopify.com/admin/oauth/access_token')
        self.assertIn(b'grant_type=client_credentials', calls[0].content)
