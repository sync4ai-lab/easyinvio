from types import SimpleNamespace as NS
from uuid import uuid4
from fastapi import FastAPI,Header,HTTPException
from fastapi.testclient import TestClient
from backend.billing_api import build_router
from backend.subscription_lifecycle import owner

def app(lifecycle=True,statements=False):
    api=FastAPI()
    async def auth(x_role:str=Header('DISPATCHER')):return NS(role=x_role,tenant_id=uuid4(),user_id=uuid4(),assistance_session_id=None)
    class Service:
        pool=None
        async def status(self,context):return {'can_manage':context.role=='OWNER'}
        async def command(self,context,action,body):owner(context);return {'state':'PREVIEW'}
    api.state.settings=NS(billing_lifecycle_enabled=lifecycle,billing_statements_enabled=statements);api.state.subscription_lifecycle=Service()
    api.include_router(build_router(auth));return api

def test_finance_reads_private_and_dispatcher_denied():
    with TestClient(app()) as client:
        for role in ['OWNER','ADMIN','ACCOUNTANT']:
            r=client.get('/api/v1/billing/subscription',headers={'X-Role':role})
            assert r.status_code==200 and r.headers['cache-control']=='private, no-store'
            assert r.json()['can_manage']==(role=='OWNER')
        assert client.get('/api/v1/billing/subscription').status_code==403

def test_only_owner_authorizes_and_naive_periods_are_invalid():
    with TestClient(app()) as client:
        body={'request_id':str(uuid4())}
        for role in ['ADMIN','ACCOUNTANT','DISPATCHER']:
            assert client.post('/api/v1/billing/subscription/cancel',json=body,headers={'X-Role':role}).status_code==403
        assert client.post('/api/v1/billing/subscription/cancel',json=body,headers={'X-Role':'OWNER'}).status_code==200
        assert client.post('/api/v1/billing/statements',json={'start':'2026-10-01T00:00:00','end':'2026-11-01T00:00:00'},headers={'X-Role':'OWNER'}).status_code==422

def test_disabled_billing_is_discoverable_without_503_requests():
    with TestClient(app(lifecycle=False)) as client:
        r=client.get('/api/v1/billing/capabilities',headers={'X-Role':'ACCOUNTANT'})
        assert r.status_code==200 and r.headers['cache-control']=='private, no-store'
        assert r.json()['statements_enabled'] is False
        assert client.get('/api/v1/billing/capabilities').status_code==403
        r=client.get('/api/v1/billing/statements',headers={'X-Role':'ACCOUNTANT'})
        assert r.status_code==503 and r.json()['detail']['code']=='BILLING_STATEMENTS_DISABLED'

def test_statements_can_be_enabled_without_payment_processing():
    with TestClient(app(lifecycle=False,statements=True)) as client:
        data=client.get('/api/v1/billing/capabilities',headers={'X-Role':'OWNER'}).json()
        assert data['statements_enabled'] is True and data['subscription_changes_enabled'] is False
