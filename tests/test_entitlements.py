"""Offline commercial-policy, role and payment isolation regression tests."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from backend.entitlements import (Plan,Feature,Subscription,capabilities,allowed,
    require_subscription_feature,check_quota,seed_subscription,guard_feature)
from backend.subscription_api import PlanChange,change_plan,build_router
from backend.subscription_billing import SubscriptionCheckout,validate_price,checkout,receive_verified_event

def subscription(plan='STARTER',**kwargs):
    return Subscription.model_validate(dict(plan_period_start=datetime.now(timezone.utc)-timedelta(days=1),
        subscription_plan=plan,**{'plan_enforcement_enabled':True,**kwargs}))

class Connection:
    def __init__(self,sub=None,count=0):self.sub=sub or subscription();self.count=count;self.calls=[]
    async def fetchrow(self,sql,*args):
        self.calls.append((sql,args))
        if 'to_jsonb(t)' in sql:return {'subscription':self.sub.model_dump(mode='json')}
        if 'admin_configuration_events' in sql:return None
        raise AssertionError(sql)
    async def fetchval(self,sql,*args):self.calls.append((sql,args));return self.count
    async def execute(self,sql,*args):self.calls.append((sql,args));return 'UPDATE 1'
    @asynccontextmanager
    async def acquire(self):yield self

@pytest.mark.parametrize('plan,seats,stores,parcels,markup',[
    ('STARTER',1,0,150,'18.00'),('VELOCITY',3,2,2000,'9.00'),('COMMAND',10,5,4000,'5.00')])
def test_exact_capabilities(plan,seats,stores,parcels,markup):
    p=capabilities(plan)
    assert (p.max_users,p.max_store_connections,p.included_monthly_parcels)==(seats,stores,parcels)
    assert p.default_markup_percent==Decimal(markup)
    assert isinstance(p.overage_fee_gbp,Decimal)

@pytest.mark.parametrize('status',['PAST_DUE','CANCELLED'])
def test_unpaid_states_never_retain_paid_features(status):
    sub=subscription('COMMAND',plan_status=status)
    assert sub.effective()==Plan.STARTER
    with pytest.raises(HTTPException) as error:require_subscription_feature(sub,Feature.CUSTOMS)
    assert error.value.status_code==402 and error.value.detail['required_plan']=='COMMAND'

def test_expired_and_unbounded_trials_fail_closed():
    for end in (None,datetime.now(timezone.utc)-timedelta(seconds=1)):
        assert subscription('COMMAND',plan_status='TRIALING',plan_period_end=end).effective()==Plan.STARTER
    assert subscription('VELOCITY',plan_status='TRIALING',plan_period_end=datetime.now(timezone.utc)+timedelta(days=14)).effective()==Plan.VELOCITY

def test_legacy_flag_cannot_bypass_plan_and_unknown_feature_rejected():
    assert not allowed(subscription(plan_enforcement_enabled=False),'customs_hs_builder')
    with pytest.raises(ValueError):allowed(subscription(),'made_up_feature')

@pytest.mark.parametrize('quota,plan,count,additional,blocked',[
    ('USERS','VELOCITY',3,1,True),('USERS','VELOCITY',2,1,False),
    ('STORES','STARTER',0,1,True),('STORES','COMMAND',5,1,True),
    ('MONTHLY_PARCELS','STARTER',150,1,True),('MONTHLY_PARCELS','VELOCITY',2000,2,False)])
def test_quotas_include_pending_seats_and_paid_overage_never_debits(quota,plan,count,additional,blocked):
    async def run():
        c=Connection(subscription(plan),count)
        if blocked:
            with pytest.raises(HTTPException) as e:await check_quota(c,uuid4(),quota,additional=additional)
            assert e.value.status_code==402
        else:
            result=await check_quota(c,uuid4(),quota,additional=additional)
            assert result['automatic_overage_charge'] is False
        assert any('FOR UPDATE' in sql for sql,_ in c.calls)
        assert not any('wallet_ledger' in sql for sql,_ in c.calls)
        if quota=='USERS':assert any('workspace_invitations' in sql for sql,_ in c.calls)
    asyncio.run(run())

def test_only_verified_seed_creates_bounded_trial_without_role_or_credit_changes():
    async def run():
        c=Connection();await seed_subscription(c,uuid4(),'VELOCITY','ANNUAL')
        sql,args=c.calls[0];assert args[1:]==('VELOCITY','ANNUAL','TRIALING',14,False)
        assert 'make_interval' in sql
        assert not any('public.users' in sql or 'wallet' in sql for sql,_ in c.calls)
        assert len([sql for sql,_ in c.calls if 'INSERT INTO public.margin_rules' in sql])==3
    asyncio.run(run())

def test_sandbox_seed_preserves_selected_tier_and_is_complimentary():
    async def run():
        c=Connection();await seed_subscription(c,uuid4(),'STARTER','MONTHLY',sandbox=True)
        assert c.calls[0][1][1:]==('STARTER','MONTHLY','ACTIVE',14,True)
    asyncio.run(run())

@pytest.mark.parametrize('role',['DISPATCHER','ACCOUNTANT','ADMIN'])
def test_only_actual_owner_may_start_recurring_checkout(role):
    async def run():
        with pytest.raises(HTTPException) as e:await checkout(None,NS(role=role),SubscriptionCheckout(request_id=uuid4(),plan='COMMAND'))
        assert e.value.status_code==403
    asyncio.run(run())

def test_assistance_owner_cannot_authorize_customer_subscription():
    async def run():
        with pytest.raises(HTTPException) as e:await checkout(None,NS(role='OWNER',assistance_session_id=uuid4()),SubscriptionCheckout(request_id=uuid4(),plan='COMMAND'))
        assert e.value.status_code==403
    asyncio.run(run())

def test_provider_price_must_match_exact_amount_cycle_currency_and_environment():
    p={'livemode':False,'currency':'gbp','active':True,'unit_amount':28800,'recurring':{'interval':'year','interval_count':1},'billing_scheme':'per_unit'}
    validate_price(p,'VELOCITY','ANNUAL',False)
    for key,value in [('unit_amount',2900),('currency','usd'),('livemode',True),('active',False)]:
        with pytest.raises(HTTPException):validate_price({**p,key:value},'VELOCITY','ANNUAL',False)

def test_wallet_webhooks_are_not_processed_as_subscriptions():
    request=NS(app=NS(state=NS(settings=NS(subscription_tiers_enabled=True))))
    assert asyncio.run(receive_verified_event(request,{'type':'checkout.session.completed','data':{'object':{'mode':'payment'}}})) is False

def test_owner_console_dependency_is_distinct_from_tenant_auth():
    async def deny_owner():raise HTTPException(403,'Platform owner required')
    async def member():return NS(role='ACCOUNTANT',tenant_id=uuid4())
    app=FastAPI();app.include_router(build_router(member,deny_owner))
    app.state.settings=NS(subscription_tiers_enabled=False)
    with TestClient(app) as c:
        assert c.get('/api/v1/admin/revenue/overview').status_code==403
        assert c.patch('/api/v1/admin/tenants/'+str(uuid4())+'/plan',json={}).status_code==403
        assert c.get('/api/v1/workspace/entitlements').status_code==503

def test_downgrade_preflight_and_stale_version_do_not_mutate():
    async def run():
        body=PlanChange(request_id=uuid4(),expected_version=1,subscription_plan='STARTER',reason='Customer-approved downgrade')
        c=Connection(subscription('COMMAND'),count=4)
        with pytest.raises(HTTPException) as e:await change_plan(c,uuid4(),body,NS(user_id=uuid4()))
        assert e.value.status_code==409
        assert not any(sql.startswith('UPDATE') for sql,_ in c.calls)
        c=Connection(subscription('COMMAND',plan_version=2))
        with pytest.raises(HTTPException) as e:await change_plan(c,uuid4(),body,NS(user_id=uuid4()))
        assert e.value.status_code==409
    asyncio.run(run())
