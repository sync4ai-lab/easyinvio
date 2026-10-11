import json
import unittest
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import main
from backend.carrier_access import verified_return_parent


class DisabledCarrierTests(unittest.IsolatedAsyncioTestCase):
    def addresses(self):
        warehouse={'name':'Warehouse','line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
        buyer={**warehouse,'name':'Buyer','line1':'2 Buyer Road'}
        return warehouse,buyer

    async def test_historical_return_requires_own_outbound_parent_and_reverse_addresses(self):
        warehouse,buyer=self.addresses();aid=uuid4();tenant=uuid4();sid=uuid4()
        connection=SimpleNamespace(fetchrow=AsyncMock(return_value={'carrier_account_id':aid,'logistics_metadata':json.dumps({'automation_order':{'origin':warehouse,'destination':buyer}})}))
        self.assertEqual(await verified_return_parent(connection,tenant,sid,buyer,warehouse),aid)
        self.assertEqual(connection.fetchrow.call_args.args[1:],(tenant,sid))
        with self.assertRaises(HTTPException) as error:await verified_return_parent(connection,tenant,sid,warehouse,buyer)
        self.assertEqual(error.exception.status_code,403)
        connection.fetchrow.return_value=None
        with self.assertRaises(HTTPException) as error:await verified_return_parent(connection,uuid4(),sid,buyer,warehouse)
        self.assertEqual(error.exception.status_code,404)

    async def test_repository_normal_queries_exclude_disabled_but_history_keeps_tenant_filter(self):
        repository=main.SupabaseRepository(None,SimpleNamespace(provider_environment='TEST',max_accounts_per_tenant=8))
        repository.select=AsyncMock(return_value=[])
        tenant=uuid4();context=SimpleNamespace(tenant_id=tenant);account=uuid4()
        await repository.accounts(context)
        self.assertEqual(repository.select.call_args.args[1]['is_active'],'eq.true')
        await repository.accounts(context,historical_account_id=account)
        filters=repository.select.call_args.args[1]
        self.assertNotIn('is_active',filters)
        self.assertEqual(filters['tenant_id'],'eq.'+str(tenant))
        self.assertEqual(filters['id'],'eq.'+str(account))

    async def test_return_rating_uses_verified_historical_connection(self):
        warehouse,buyer=self.addresses();tenant=uuid4();account_id=uuid4();parent=uuid4()
        account=main.CarrierAccount(account_id,tenant,'EASYPOST','https://api.easypost.com/v2',None,30,'synthetic')
        class Connection:
            async def fetchrow(self,*args):return {'carrier_account_id':account_id,'logistics_metadata':{'automation_order':{'origin':warehouse,'destination':buyer}}}
            async def fetch(self,*args):return []
        class Pool:
            @asynccontextmanager
            async def acquire(self):yield Connection()
        repository=SimpleNamespace(accounts=AsyncMock(return_value=[account]))
        service=main.RatingService(None,repository,SimpleNamespace(provider_environment='TEST',provider_deadline_seconds=5,quote_ttl_seconds=60,max_parallel_provider_requests=4),pool=Pool())
        service.run_provider=AsyncMock(return_value=([main.WholesaleRate(provider='EASYPOST',account_id=account_id,
            upstream_shipment_id='return1',upstream_rate_id='rate1',carrier_code='UPS',service_code='Ground',currency='USD',wholesale_cost='10.00')],None))
        request=main.RatingRequest(origin=buyer,destination=warehouse,currency='USD',is_return=True,weights_kg=['1.0'],dimensions=[{'length_cm':'20','width_cm':'15','height_cm':'10'}])
        with patch('main.get_client_calibrated_rate',AsyncMock(return_value=Decimal('12.00'))):
            result=await service.quote(SimpleNamespace(tenant_id=tenant,role='OWNER'),request,return_of_shipment_id=parent)
        repository.accounts.assert_awaited_once()
        self.assertEqual(repository.accounts.call_args.kwargs['historical_account_id'],account_id)
        self.assertEqual(result.rates[0].account_id,account_id)

    async def test_disable_routes_require_verified_owner(self):
        main.app.state.local_preview=False;client=TestClient(main.app)
        self.assertEqual(client.post('/api/v1/admin/platform-carriers/'+str(uuid4())+'/disable').status_code,401)
        self.assertEqual(client.post('/api/v1/admin/carriers/'+str(uuid4())+'/disable').status_code,401)


if __name__=='__main__':unittest.main()
