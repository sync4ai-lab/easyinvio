"""Catalog validation, role boundaries, parameter binding and version fencing."""
import json
import unittest
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from main import Address
from backend.tenant_catalogs import ProductInput, TenantCatalogService, build_router, public_record
from backend.agents.supervisor import LogisticsSupervisor
from backend.agents.config import AgentSettings


def context(role='OWNER'):
    return SimpleNamespace(tenant_id=uuid4(), user_id=uuid4(), role=role)


class Pool:
    def __init__(self, row=None):
        self.calls = []
        self.row = row
        self.transactions = 0

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        self.transactions += 1
        yield self

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return [self.row] if self.row else []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self.row

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


class ValidationTests(unittest.TestCase):
    def product(self, **changes):
        return ProductInput.model_validate({'sku':'SKU1','description':'Cotton knitted shirt',
            'unit_value':'12.30','unit_weight_kg':'0.125','origin_country':'GB',**changes})

    def test_decimal_and_hs_validation(self):
        product = self.product(hs_code='610910', hs_reviewed=True)
        self.assertEqual(product.unit_value, Decimal('12.30'))
        for changes in ({'unit_value':12.3}, {'unit_weight_kg':'0.1234'}, {'hs_code':'1234567'},
                        {'hs_reviewed':True}, {'unit_value':'NaN'}, {'tenant_id':str(uuid4())}):
            with self.assertRaises(ValidationError):
                self.product(**changes)
        for code in ('123456','12345678','1234567890'):
            self.assertEqual(self.product(hs_code=code).hs_code, code)

    def test_native_address_validation(self):
        body={'name':'Recipient','line1':'9 Test Street','city':'Leeds','postal_code':'LS1 1AA','country_code':'GB'}
        for changes in ({'phone':'07123456789'},{'email':'not-an-email'},{'country_code':'ZZ'},{'city':'  '}):
            with self.assertRaises(ValidationError):
                Address.model_validate(body|changes)
        self.assertEqual(Address.model_validate(body|{'phone':'+447123456789'}).phone,'+447123456789')

    def test_public_projection_preserves_decimal_and_hides_tenant(self):
        result=public_record({'id':uuid4(),'tenant_id':uuid4(),'unit_value':Decimal('12.30'),'unit_weight_kg':Decimal('.125'),'hs_reviewed_by':uuid4(),'hs_reviewed_at':None})
        self.assertEqual(result['unit_value'],'12.30')
        self.assertNotIn('tenant_id',result)
        self.assertNotIn('hs_reviewed_by',result)

    def test_api_denies_cross_tenant_body_and_accountant_writes(self):
        actor=context('ACCOUNTANT')
        async def auth(): return actor
        app=FastAPI();app.state.finance=SimpleNamespace(pool=Pool())
        app.include_router(build_router(auth,Address))
        body={'sku':'SKU1','description':'Cotton shirt','unit_value':'20','unit_weight_kg':'1','origin_country':'GB'}
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/v1/catalog/products',json=body).status_code,403)
            actor.role='OWNER'
            self.assertEqual(client.post('/api/v1/catalog/products',json=body|{'tenant_id':str(uuid4())}).status_code,422)
            self.assertEqual(client.get('/api/v1/catalog/contacts?limit=101').status_code,422)
            self.assertEqual(client.get('/api/v1/catalog/contacts?address_role=SENDER').status_code,422)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_binds_verified_tenant_and_escapes_wildcards(self):
        actor=context();pool=Pool()
        result=await TenantCatalogService(pool).list(actor,'products','SKU%_')
        self.assertEqual(result['items'],[])
        sql,args=pool.calls[0]
        self.assertIn('tenant_id=$1',sql)
        self.assertEqual(args[0],actor.tenant_id)
        self.assertEqual(args[1],'%SKU\\%\\_%')

    async def test_missing_foreign_record_cannot_be_edited(self):
        actor=context();pool=Pool()
        body=ProductInput(sku='SKU1',description='Cotton shirt',unit_value='12',unit_weight_kg='1',origin_country='GB',expected_version=1)
        with self.assertRaises(HTTPException) as raised:
            await TenantCatalogService(pool).save(actor,'products',body,uuid4())
        self.assertEqual(raised.exception.status_code,404)
        self.assertTrue(all(not sql.startswith('UPDATE') for sql,args in pool.calls))
        self.assertEqual(pool.calls[0][1][0],actor.tenant_id)

    async def test_stale_version_fails_before_update(self):
        actor=context();pool=Pool({'version':3})
        body=ProductInput(sku='SKU1',description='Cotton shirt',unit_value='12',unit_weight_kg='1',origin_country='GB',expected_version=2)
        with self.assertRaises(HTTPException) as raised:
            await TenantCatalogService(pool).save(actor,'products',body,uuid4())
        self.assertEqual(raised.exception.status_code,409)
        self.assertTrue(all(not sql.startswith('UPDATE') for sql,args in pool.calls))

    async def test_default_change_is_locked_and_role_scoped_inside_transaction(self):
        actor=context();pool=Pool({'id':uuid4(),'version':1})
        async def auth():return actor
        app=FastAPI();app.state.finance=SimpleNamespace(pool=pool);app.include_router(build_router(auth,Address))
        route=next(route for route in build_router(auth,Address).routes if getattr(route,'path','')=='/api/v1/catalog/addresses' and 'POST' in route.methods)
        model=route.endpoint.__annotations__['body']
        body=model(label='Warehouse',address_role='SENDER',is_default=True,address={'name':'Sender','line1':'9 Test Street','city':'Leeds','postal_code':'LS1 1AA','country_code':'GB'})
        await TenantCatalogService(pool).save(actor,'addresses',body)
        self.assertEqual(pool.transactions,1)
        self.assertIn('pg_advisory_xact_lock',pool.calls[0][0])
        update=next((sql,args) for sql,args in pool.calls if 'SET is_default=false' in sql)
        self.assertIn('address_role=$2',update[0]);self.assertEqual(update[1][:2],(actor.tenant_id,'SENDER'))

    async def test_archiving_never_edits_shipments(self):
        actor=context();pool=Pool({'version':1})
        await TenantCatalogService(pool).archive(actor,'products',uuid4(),1)
        self.assertTrue(any('archived_at=now()' in sql for sql,args in pool.calls))
        self.assertTrue(all('shipments' not in sql for sql,args in pool.calls))

    async def test_reviewed_catalog_suggestion_uses_no_model_and_grants_no_approval(self):
        engine=LogisticsSupervisor(AgentSettings.model_construct(logistics_agents_enabled=False))
        result=await engine.customs.suggest(context(),'Cotton shirt',product={'sku':'SKU1','description':'Cotton shirt','hs_code':'610910','hs_reviewed':True})
        self.assertEqual(result['source'],'tenant_reviewed_catalog')
        self.assertFalse(result['customs_approved'])
        self.assertEqual(engine.runtime.usage['model_calls'],0)


if __name__=='__main__':unittest.main()
