from types import SimpleNamespace as NS
from uuid import uuid4
from fastapi import FastAPI,Header,HTTPException
from fastapi.testclient import TestClient
from backend.billing_api import build_router
from backend.subscription_lifecycle import owner

def app():
    api=FastAPI()
    async def auth(x_role:str=Header('DISPATCHER')):return NS(role=x_role,tenant_id=uuid4(),user_id=uuid4(),assistance_session_id=None)
    class Service:
        pool=None
        async def status(self,context):return {'can_manage':context.role=='OWNER'}
        async def command(self,context,action,body):owner(context);return {'state':'PREVIEW'}
    api.state.settings=NS(billing_lifecycle_enabled=True);api.state.subscription_lifecycle=Service()
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
