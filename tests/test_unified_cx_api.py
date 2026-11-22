"""ASGI authorization contract tests with synthetic service dependencies."""
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI,HTTPException

from backend.cx_automation import build_router


class SchemaPool:
    @asynccontextmanager
    async def acquire(self):yield self
    async def fetchval(self,*args):return True


@pytest.mark.asyncio
async def test_platform_health_and_fixtures_require_platform_owner():
    async def member():return NS(tenant_id=uuid4(),user_id=uuid4(),role='OWNER')
    async def deny():raise HTTPException(403,'Platform owner required')
    app=FastAPI();app.state.finance=NS(pool=SchemaPool());app.include_router(build_router(member,deny))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test.invalid') as client:
        assert (await client.get('/api/v1/admin/connectors/health')).status_code==403
        result=await client.post('/api/v1/admin/uat/plan-fixtures',json={'owner_auth_user_ids':[str(uuid4()) for _ in range(3)]})
        assert result.status_code==403


@pytest.mark.asyncio
async def test_fixture_endpoint_cannot_run_against_live_configuration():
    async def owner():return NS(user_id=uuid4())
    app=FastAPI();app.state.finance=NS(pool=SchemaPool());app.state.settings=NS(provider_environment='LIVE',database_environment='LIVE')
    app.include_router(build_router(owner,owner))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test.invalid') as client:
        result=await client.post('/api/v1/admin/uat/plan-fixtures',json={'owner_auth_user_ids':[str(uuid4()) for _ in range(3)]})
        assert result.status_code==403


@pytest.mark.asyncio
async def test_public_reference_endpoint_reuses_non_pii_projection_and_budget(monkeypatch):
    async def deny():raise HTTPException(401,'Auth required')
    app=FastAPI();app.state.finance=NS(pool=SchemaPool());app.state.settings=NS()
    calls=[];app.state.tracking_workspace=NS(public_rate_limit=lambda key:calls.append(key))
    mock=AsyncMock(return_value='Public parcel status\nIn transit • Carrier service')
    monkeypatch.setattr('backend.whatsapp_progressive.GuestShippingAssistant.public_status',mock)
    app.include_router(build_router(deny,deny))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test.invalid') as client:
        response=await client.post('/api/v1/public/tracking/status',json={'text':'TRACKING123456'})
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        assert list(response.json())==['message'] and len(calls)==1
        assert (await client.post('/api/v1/public/tracking/status',json={'text':'bad ref'})).status_code==422


@pytest.mark.asyncio
async def test_schema_missing_is_clear_failure_without_provider_calls():
    pool=SchemaPool();pool.fetchval=AsyncMock(return_value=False)
    async def owner():return NS(user_id=uuid4())
    app=FastAPI();app.state.finance=NS(pool=pool);app.include_router(build_router(owner,owner))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test.invalid') as client:
        response=await client.get('/api/v1/admin/connectors/health')
        assert response.status_code==503 and 'migration 056' in response.json()['detail']
