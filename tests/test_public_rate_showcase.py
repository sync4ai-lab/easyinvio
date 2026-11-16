"""Public rate publication cannot become an anonymous tenant rating gateway."""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.public_rate_showcase import (ApprovedRepository, PublicRateShowcase, catalog,
    configuration, publish_price, router)

TENANT=UUID(int=1)
ACCOUNT=UUID(int=2)
NOW=datetime(2026,11,16,12,tzinfo=timezone.utc)

def settings(**kw):
    return NS(**dict(public_rate_showcase_enabled=True, public_rate_showcase_tenant_id=TENANT,
        public_rate_showcase_account_ids=[ACCOUNT], provider_environment='LIVE', **kw))

def rate(price='4.32', **kw):
    values=dict(currency='GBP',label_purchase_available=True,client_price_ex_tax=Decimal(price),
                carrier_code='EVRI',service_code='STANDARD',delivery_days=3,
                account_id=ACCOUNT,api_key='NEVER_PUBLIC',upstream_rate_id='NEVER_PUBLIC',
                fee_breakdown={'secret':'NEVER_PUBLIC'},execution_details={'credential':'NEVER_PUBLIC'})
    values.update(kw);return NS(**values)

class Pool:
    def __init__(self,payload=None,attempted=None):
        self.row={'payload':json.dumps(payload),'attempted_at':attempted or NOW} if payload is not None else None
        self.reads=0;self.locked=True
    @asynccontextmanager
    async def acquire(self):yield self
    async def fetchrow(self,*args):self.reads+=1;return self.row
    async def fetchval(self,*args):return self.locked
    async def execute(self,sql,*args):
        if sql.startswith('INSERT'):self.row={'payload':args[2], 'attempted_at':args[1]}
        elif sql.startswith('UPDATE'):self.row['payload']=args[1]

class ProjectionTests(TestCase):
    def test_catalog_is_fixed_and_balanced(self):
        rows=catalog();self.assertEqual(len(rows),10)
        self.assertEqual(len({r['id'] for r in rows}),10)
        self.assertEqual(sum(r['destination_country']=='GB' for r in rows),5)
        self.assertTrue(all(r['price_ex_tax'] is None for r in rows))
    def test_lowest_eligible_price_no_internal_identifiers(self):
        result=NS(rates=[rate('1',label_purchase_available=False),rate('4.32'),rate('7'),rate('2',currency='EUR')])
        item=publish_price(catalog()[0],result,NOW)
        self.assertEqual(item['price_ex_tax'],'4.32')
        self.assertIsNone(item['transport_mode'])
        self.assertNotIn('NEVER_PUBLIC',json.dumps(item))
    def test_mode_only_if_provider_explicitly_confirms(self):
        for mode,expected in [('AIR','AIR'),('ROAD','ROAD'),('SEA','SEA'),('Express air guess',None)]:
            item=publish_price(catalog()[0],NS(rates=[rate(execution_details={'transport_mode':mode})]),NOW)
            self.assertEqual(item['transport_mode'],expected)
    def test_disabled_missing_source_or_test_cannot_publish(self):
        for key,value in [('public_rate_showcase_enabled',False),('public_rate_showcase_tenant_id',None),
                ('public_rate_showcase_account_ids',[]),('provider_environment','TEST')]:
            s=settings();setattr(s,key,value);self.assertIsNone(configuration(s))
    def test_public_endpoint_is_read_only_and_rejects_arbitrary_routes(self):
        app=FastAPI();app.include_router(router);app.state.local_preview=False
        service=NS(read=AsyncMock(return_value={'status':'pending','examples':catalog()}),refresh=AsyncMock())
        app.state.public_rate_showcase=service
        with TestClient(app) as client:
            response=client.get('/api/v1/public/rate-showcase')
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.get('/api/v1/public/rate-showcase?tenant_id=anything').status_code,400)
            self.assertEqual(client.post('/api/v1/public/rate-showcase').status_code,405)
        service.refresh.assert_not_called()
    def test_local_preview_requires_no_database(self):
        app=FastAPI();app.include_router(router);app.state.local_preview=True
        with TestClient(app) as client:
            data=client.get('/api/v1/public/rate-showcase').json()
            self.assertEqual(data['status'],'local-preview');self.assertEqual(len(data['examples']),10)

class IsolationTests(IsolatedAsyncioTestCase):
    async def test_repository_limits_tenant_and_exact_account_set(self):
        repository=NS(accounts=AsyncMock(return_value=[NS(id=ACCOUNT,tenant_id=TENANT),NS(id=UUID(int=3),tenant_id=TENANT)]),load=AsyncMock())
        approved=ApprovedRepository(repository,TENANT,{ACCOUNT})
        selected=await approved.accounts(NS(tenant_id=TENANT))
        self.assertEqual([row.id for row in selected],[ACCOUNT])
        with self.assertRaises(ValueError):await approved.accounts(NS(tenant_id=UUID(int=9)))
        repository.accounts.return_value=[NS(id=ACCOUNT,tenant_id=UUID(int=9))]
        with self.assertRaises(ValueError):await approved.accounts(NS(tenant_id=TENANT))
    async def test_read_projects_known_fields_and_memoizes(self):
        item=publish_price(catalog()[0],NS(rates=[rate()]),NOW);item['secret']='NEVER_PUBLIC'
        pool=Pool({'examples':[item]})
        service=PublicRateShowcase(pool,None,settings(),now=lambda:NOW)
        result=await service.read();await service.read()
        self.assertEqual(result['status'],'partial');self.assertEqual(len(result['examples']),10)
        self.assertNotIn('NEVER_PUBLIC',json.dumps(result));self.assertEqual(pool.reads,1)
    async def test_yesterday_prices_are_not_presented_as_todays(self):
        item=publish_price(catalog()[0],NS(rates=[rate()]),NOW-timedelta(days=1))
        result=await PublicRateShowcase(Pool({'examples':[item]}),None,settings(),now=lambda:NOW).read()
        self.assertIsNone(result['examples'][0]['price_ex_tax']);self.assertEqual(result['examples'][0]['status'],'stale')
    async def test_invalid_price_fails_closed(self):
        item=catalog()[0];item.update(price_ex_tax='not money',status='available')
        result=await PublicRateShowcase(Pool({'examples':[item]}),None,settings(),now=lambda:NOW).read()
        self.assertEqual(result['status'],'pending');self.assertTrue(all(x['price_ex_tax'] is None for x in result['examples']))
    async def test_refresh_is_bounded_and_reuses_same_day_results(self):
        pool=Pool();repository=NS(accounts=AsyncMock(return_value=[NS(id=ACCOUNT,tenant_id=TENANT)]))
        original=NS(repository=repository,client=None,pool=pool)
        quoted=NS(quote=AsyncMock(return_value=NS(rates=[rate()])))
        service=PublicRateShowcase(pool,original,settings(),now=lambda:NOW)
        with patch('main.RatingService',return_value=quoted):
            self.assertTrue(await service.refresh());self.assertFalse(await service.refresh())
        self.assertEqual(quoted.quote.await_count,10)
        self.assertNotIn('NEVER_PUBLIC',pool.row['payload'])
        self.assertTrue(all(x['status']=='available' for x in json.loads(pool.row['payload'])['examples']))
    async def test_another_refresh_owner_does_not_call_providers(self):
        pool=Pool();pool.locked=False
        self.assertFalse(await PublicRateShowcase(pool,None,settings(),now=lambda:NOW).refresh())
    async def test_unconfigured_never_accesses_database(self):
        s=settings();s.public_rate_showcase_enabled=False
        service=PublicRateShowcase(None,None,s,now=lambda:NOW)
        self.assertEqual((await service.read())['status'],'unconfigured');self.assertFalse(await service.refresh())
