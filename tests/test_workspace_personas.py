"""Consumer accounts, global prices and provisioning with isolated deterministic IO."""
import copy
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.admin_portal import (AdminService, IndividualPricingUpdate, PlatformOwner, TenantCreate,
    calibrated_pricing_scope, get_client_calibrated_rate, router, authenticate_platform_owner, authenticate_platform_operator,
    update_individual_pricing)
from backend.web_registration import RegistrationStart, RegistrationVerify, start_registration, verify_registration
from test_admin_portal import Connection, Acquire


def personal():
    return {'full_name':'Alex Personal', 'billing_email':'personal@example.test', 'phone_e164':'+447700900123'}


class PricingDB(Connection):
    def __init__(self):
        super().__init__()
        self.setting = {'individual_global_markup_percent':Decimal('12.50'), 'version':1}
        self.events = {}

    async def fetchrow(self, sql, *args):
        if 'individual_pricing_settings' in sql:
            self.calls.append((sql,args))
            return self.setting
        if 'individual_pricing_events' in sql:
            return self.events.get(args)
        return await super().fetchrow(sql,*args)

    async def execute(self, sql, *args):
        if 'INSERT INTO public.individual_pricing_settings' in sql:
            self.setting = {'individual_global_markup_percent':args[0],'version':args[1]}
        elif 'INSERT INTO public.individual_pricing_events' in sql:
            self.events[args[:2]] = {'new_percent':args[3],'previous_version':args[4],'version':args[5]}
        else:
            return await super().execute(sql,*args)


@pytest.mark.asyncio
async def test_personal_pricing_bypasses_business_rules_and_preserves_fallback_and_snapshot():
    db = PricingDB()
    tenant = uuid4()
    db.store['tenants'][tenant] = {'workspace_type':'INDIVIDUAL','workspace_status':'ACTIVE','default_currency':'GBP'}
    db.rule = {'markup_type':'FLAT_RATE','markup_value':Decimal('1000'),'tenant_id':tenant}
    pool = SimpleNamespace(acquire=lambda:Acquire(db))
    with calibrated_pricing_scope(pool):
        assert await get_client_calibrated_rate(tenant,Decimal('10.00'),'DPD','GB') == Decimal('11.25')
        assert not any('public.margin_rules' in sql for sql,_ in db.calls)
        db.setting = None
        assert await get_client_calibrated_rate(tenant,Decimal('10.00'),'DPD','GB') == Decimal('12.00')
    snapshot = {'workspace_type':'INDIVIDUAL','markup_percent':'12.50','version':1}
    db.setting = {'individual_global_markup_percent':Decimal('99.99'),'version':2}
    with calibrated_pricing_scope(pool,persona_policy=snapshot):
        assert await get_client_calibrated_rate(tenant,Decimal('10.00'),'DPD','GB') == Decimal('11.25')


@pytest.mark.asyncio
async def test_global_update_is_owner_only_versioned_exact_and_replay_safe():
    db = PricingDB()
    app = FastAPI()
    app.state.admin_portal = AdminService(SimpleNamespace(acquire=lambda:Acquire(db)))
    app.include_router(router)
    actor = PlatformOwner(uuid4())
    request = Request({'type':'http','app':app,'headers':[]})
    body = IndividualPricingUpdate(expected_version=1,individual_global_markup_percent='21.25')
    first = await update_individual_pricing(body,request,actor)
    assert first == await update_individual_pricing(body,request,actor)
    assert len(db.events) == 1 and db.setting['individual_global_markup_percent'] == Decimal('21.25')
    with pytest.raises(HTTPException) as error:
        await update_individual_pricing(IndividualPricingUpdate(expected_version=1,individual_global_markup_percent='22.00'),request,actor)
    assert error.value.status_code == 409
    with TestClient(app) as client:
        assert client.put('/api/v1/admin/individual-pricing',json=body.model_dump(mode='json')).status_code in (401,403)
    for value in ('NaN','Infinity','-1','1000','1.001',True):
        with pytest.raises(ValidationError):
            IndividualPricingUpdate(expected_version=1,individual_global_markup_percent=value)


def test_persona_cannot_be_combined_with_business_metadata():
    RegistrationStart(workspace_type='INDIVIDUAL',profile=personal())
    TenantCreate(workspace_type='INDIVIDUAL',company_profile=personal(),billing_plan='PREPAID_WALLET')
    with pytest.raises(ValidationError):
        RegistrationStart(workspace_type='BUSINESS',profile=personal())
    with pytest.raises(ValidationError):
        RegistrationStart(workspace_type='INDIVIDUAL',profile={**personal(),'tax_id':'invented'})


@pytest.mark.asyncio
async def test_real_rating_gateway_uses_one_personal_policy_and_snapshots_it():
    import main
    db = PricingDB()
    tenant = uuid4()
    db.store['tenants'][tenant] = {'workspace_type':'INDIVIDUAL','workspace_status':'ACTIVE','default_currency':'GBP'}
    pool = SimpleNamespace(acquire=lambda:Acquire(db))
    account = SimpleNamespace(id=uuid4(),provider='EASYPOST',base_url='https://api.easypost.com/v2',api_key='synthetic',upstream_account_id=None)
    settings = SimpleNamespace(max_parallel_provider_requests=2,provider_deadline_seconds=5,quote_ttl_seconds=300,provider_environment='TEST')
    service = main.RatingService(None,SimpleNamespace(accounts=AsyncMock(return_value=[account])),settings,pool=pool)
    service.run_provider = AsyncMock(return_value=([main.WholesaleRate(provider='EASYPOST',account_id=account.id,
        upstream_shipment_id='synthetic-shipment',upstream_rate_id='synthetic-rate',carrier_code='UPS',service_code='Ground',
        currency='GBP',wholesale_cost='10.00')],None))
    address = {'name':'Alex','line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
    request = main.RatingRequest(origin=address,destination=address,weights_kg=['1.5'],dimensions=[{'length_cm':'24','width_cm':'16','height_cm':'8'}])
    with patch('backend.carrier_consolidation.route_history',AsyncMock(return_value={})):
        result = await service.quote(SimpleNamespace(tenant_id=tenant),request)
    assert result.rates[0].client_price_ex_tax == Decimal('11.25')
    policy = result.rates[0].execution_details['pricing_policy']
    assert policy['markup_percent'] == '12.50' and policy['version'] == 1
    assert sum('individual_pricing_settings' in sql for sql,_ in db.calls) == 1
    assert not any('public.margin_rules' in sql for sql,_ in db.calls)


def test_admin_cohort_report_keeps_currency_totals_and_persona_groups_separate():
    from backend.dashboard_portal import build_router
    from test_dashboard_portal import DB

    class CohortDB(DB):
        async def fetch(self, sql, *args):
            if 'AS revenue' in sql:
                self.calls.append((sql,args))
                return [dict(workspace_type=kind,currency=currency,revenue=Decimal(revenue),margin=Decimal('1.00'),package_count=1,label_count=1)
                    for kind,currency,revenue in [('BUSINESS','GBP','10.00'),('INDIVIDUAL','GBP','20.00'),('INDIVIDUAL','EUR','5.00')]]
            if 'GROUP BY t.workspace_type' in sql:
                self.calls.append((sql,args))
                return [{'workspace_type':'INDIVIDUAL','ticket_count':3}]
            if 'GROUP BY workspace_type' in sql:
                self.calls.append((sql,args))
                return [{'workspace_type':'INDIVIDUAL','active_tenants':2}]
            return await super().fetch(sql,*args)

    db = CohortDB()
    app = FastAPI()
    app.state.finance = SimpleNamespace(pool=db)
    app.include_router(build_router(AsyncMock()))
    app.dependency_overrides[authenticate_platform_operator] = lambda: PlatformOwner(uuid4())
    with TestClient(app) as client:
        result = client.get('/api/v1/admin/analytics/dashboard?start_date=2026-09-01&end_date=2026-09-30').json()
    assert result['totals_by_currency'][0]['revenue'] == '30.00'
    assert result['totals_by_currency'][1]['revenue'] == '5.00'
    assert len(result['cohorts']['shipping']) == 3
    assert result['cohorts']['tickets'][0]['ticket_count'] == 3
    sql,args = next((sql,args) for sql,args in db.calls if 'AS revenue' in sql)
    assert 'GROUP BY t.workspace_type,currency' in sql and len(args) == 3


class WebDB:
    def __init__(self):
        self.row = None
        self.writes = []
        self.blocked = False
        self.fail_wallet = False

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        before = copy.deepcopy((self.row,self.writes))
        try:
            yield
        except BaseException:
            self.row,self.writes = before
            raise

    async def fetchval(self, sql, *args):
        return self.blocked

    async def fetchrow(self, sql, *args):
        if 'INSERT INTO public.web_registration_sessions' in sql:
            self.row = {'id':uuid4(),'secret_sha256':args[0],'email_address':args[1],'workspace_type':args[2],
                'profile':args[3],'state':'SENDING_EMAIL','created_at':datetime.now(timezone.utc),
                'expires_at':datetime.now(timezone.utc)+timedelta(minutes=15),'attempts':0,'tenant_id':uuid4()}
            return self.row
        if 'public.web_registration_sessions' in sql:
            return self.row
        if 'public.wallets' in sql:
            return {'currency':'GBP','balance':Decimal(1) if self.fail_wallet else Decimal(0),'reserved_balance':Decimal(0)}
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self.writes.append((sql,args))
        if "SET state='PENDING_OTP'" in sql:
            self.row['state'] = 'PENDING_OTP'
        if "SET state='RECONCILIATION_REQUIRED'" in sql:
            self.row.update(state='RECONCILIATION_REQUIRED',attempts=self.row['attempts']+1)
        if "SET state='VERIFIED'" in sql:
            self.row.update(state='VERIFIED',auth_user_id=args[1])


@pytest.fixture
def web_fixture():
    db = WebDB()
    app = FastAPI()
    app.state.finance = SimpleNamespace(pool=db)
    app.state.settings = SimpleNamespace(platform_admin_user_ids=[],database_environment='SANDBOX',provider_environment='TEST')
    request = Request({'type':'http','app':app,'headers':[]})
    provider = SimpleNamespace(send_code=AsyncMock(),verify=AsyncMock(return_value=uuid4()),bind_workspace=AsyncMock(),request=AsyncMock())
    return db,request,provider


@pytest.mark.asyncio
async def test_web_activation_requires_email_proof_and_atomic_zero_wallet(web_fixture):
    db,request,provider = web_fixture
    with patch('backend.identity.recovery_limit',AsyncMock()), patch('backend.web_registration.SupabaseSignupProvider',return_value=provider):
        started = await start_registration(RegistrationStart(workspace_type='INDIVIDUAL',profile=personal()),request)
        assert not any('INSERT INTO public.tenants' in sql for sql,_ in db.writes)
        assert db.row['secret_sha256'] == hashlib.sha256(started['registration_secret'].encode()).hexdigest()
        verification = RegistrationVerify(registration_id=started['registration_id'],registration_secret=started['registration_secret'],
            code='12345678',password='synthetic-password-only')
        provider.verify.return_value = None
        with pytest.raises(HTTPException):
            await verify_registration(verification,request)
        assert db.row['attempts'] == 1 and db.row['state'] == 'PENDING_OTP'
        assert not any('INSERT INTO public.tenants' in sql for sql,_ in db.writes)
        provider.verify.return_value = uuid4()
        result = await verify_registration(verification,request)
        assert db.row['state'] == 'VERIFIED'
        tenant_args = next(args for sql,args in db.writes if 'INSERT INTO public.tenants' in sql)
        assert tenant_args[-1] == 'INDIVIDUAL' and tenant_args[7] is None
        assert 'sign in' in result['message'].lower()
        calls = provider.request.await_count
        await verify_registration(verification,request)
        assert provider.request.await_count == calls
        assert not any('synthetic-password-only' in str(args) for sql,args in db.writes)


@pytest.mark.asyncio
async def test_web_nonce_failures_and_partial_provision_never_activate(web_fixture):
    db,request,provider = web_fixture
    with patch('backend.identity.recovery_limit',AsyncMock()), patch('backend.web_registration.SupabaseSignupProvider',return_value=provider):
        started = await start_registration(RegistrationStart(workspace_type='INDIVIDUAL',profile=personal()),request)
        verify = RegistrationVerify(registration_id=started['registration_id'],registration_secret='wrong'*10,code='12345678',password='synthetic-password-only')
        with pytest.raises(HTTPException):
            await verify_registration(verify,request)
        provider.verify.assert_not_awaited()
        verify = verify.model_copy(update={'registration_secret':__import__('pydantic').SecretStr(started['registration_secret'])})
        db.fail_wallet = True
        with pytest.raises(HTTPException):
            await verify_registration(verify,request)
        assert db.row['state'] == 'RECONCILIATION_REQUIRED'
        assert not any('INSERT INTO public.tenants' in sql for sql,_ in db.writes)
