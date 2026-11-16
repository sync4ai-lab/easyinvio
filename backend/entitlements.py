"""Server-owned plan policy. Tier access never replaces membership/assistance RBAC."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID
import asyncpg
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

class Plan(StrEnum):
    STARTER='STARTER'
    VELOCITY='VELOCITY'
    COMMAND='COMMAND'

class Feature(StrEnum):
    STORES='store_integrations'
    WHATSAPP='whatsapp_bot'
    RETURNS='paperless_qr_returns'
    ADVISOR='ai_carrier_advisor'
    CUSTOMS='customs_hs_builder'
    MANIFESTS='eod_manifests'
    MARGINS='custom_margin_rules'
    BYOC='byoc_carrier_accounts'
    AUDITS='tax_ledger_audits'
    POSTPAID='postpaid_billing'

class PlanCapabilities(BaseModel):
    model_config=ConfigDict(frozen=True,extra='forbid')
    max_users:int
    max_store_connections:int
    included_monthly_parcels:int
    overage_fee_gbp:Decimal
    default_markup_percent:Decimal
    monthly_fee_gbp:Decimal
    annual_monthly_fee_gbp:Decimal
    features:dict[str,bool]

def capabilities(plan:Plan|str)->PlanCapabilities:
    plan=Plan(plan)
    users,stores,parcels,overage,markup,monthly,annual={
        Plan.STARTER:(1,0,150,'0.15','18.00','0','0'),
        Plan.VELOCITY:(3,2,2000,'0.05','9.00','29','24'),
        Plan.COMMAND:(10,5,4000,'0.02','5.00','79','65')}[plan]
    paid=plan!=Plan.STARTER;command=plan==Plan.COMMAND
    return PlanCapabilities(max_users=users,max_store_connections=stores,included_monthly_parcels=parcels,
        overage_fee_gbp=Decimal(overage),default_markup_percent=Decimal(markup),monthly_fee_gbp=Decimal(monthly),
        annual_monthly_fee_gbp=Decimal(annual),features={
            Feature.STORES:paid,Feature.WHATSAPP:paid,Feature.RETURNS:paid,Feature.ADVISOR:paid,Feature.CUSTOMS:command,
            Feature.MANIFESTS:paid,Feature.MARGINS:command,Feature.BYOC:command,Feature.AUDITS:command,
            # Credit still requires FinanceEngine's separately approved postpaid billing agreement.
            Feature.POSTPAID:command})

class Subscription(BaseModel):
    model_config=ConfigDict(extra='ignore')
    subscription_plan:Plan=Plan.STARTER
    billing_cycle:Literal['MONTHLY','ANNUAL']='MONTHLY'
    plan_status:Literal['ACTIVE','TRIALING','PAST_DUE','CANCELLED']='ACTIVE'
    plan_period_start:datetime
    plan_period_end:datetime|None=None
    plan_enforcement_enabled:bool=False
    subscription_complimentary:bool=False
    plan_version:int=1
    is_sandbox:bool=False
    workspace_type:str='BUSINESS'
    dedicated_account_manager:str|None=None
    stripe_subscription_id:str|None=None

    def effective(self,now:datetime|None=None)->Plan:
        now=now or datetime.now(timezone.utc)
        valid=self.plan_status in {'ACTIVE','TRIALING'}
        if self.plan_status=='TRIALING' and self.plan_period_end is None:valid=False
        if self.plan_period_end is not None and self.plan_period_end<=now:valid=False
        return self.subscription_plan if valid else Plan.STARTER

def enabled(settings)->bool:
    return bool(getattr(settings,'subscription_tiers_enabled',False))

def database_plan_error(error):
    """Translate only our fixed SQL messages; never expose arbitrary database diagnostics."""
    code=getattr(error,'message','')
    if code not in {'PLAN_UPGRADE_REQUIRED','PLAN_QUOTA_EXCEEDED','PLAN_PARCEL_QUOTA_EXCEEDED','PLAN_CHANGED_REQUOTE_REQUIRED'}:return None
    return HTTPException(409 if code=='PLAN_CHANGED_REQUOTE_REQUIRED' else 402,{
        'code':code,'pricing_url':'/pricing','retry_requires_fresh_quote':code=='PLAN_CHANGED_REQUOTE_REQUIRED',
        'message':'Your plan changed. Request a fresh quote.' if code=='PLAN_CHANGED_REQUOTE_REQUIRED' else 'Your current plan does not support this service or additional capacity.'})

async def read_subscription(connection,tenant_id:UUID,*,lock=False)->Subscription:
    row=await connection.fetchrow('SELECT to_jsonb(t) AS subscription FROM public.tenants t WHERE tenant_id=$1'+(' FOR UPDATE' if lock else ''),tenant_id)
    if not row:raise HTTPException(404,'Workspace not found')
    data=row['subscription'];data=json.loads(data) if isinstance(data,str) else data
    if 'subscription_plan' not in data:raise HTTPException(503,'Apply migration 050 before enabling subscription tiers')
    try:return Subscription.model_validate(data)
    except ValueError:raise HTTPException(503,'Subscription configuration requires review') from None

def allowed(subscription:Subscription,feature:Feature|str,now=None)->bool:
    feature=Feature(feature)
    if not subscription.plan_enforcement_enabled:return True
    return capabilities(subscription.effective(now)).features[feature]

def require_subscription_feature(subscription:Subscription,feature:Feature|str):
    feature=Feature(feature)
    if allowed(subscription,feature):return
    required=next((p.value for p in Plan if capabilities(p).features[feature]),None)
    raise HTTPException(402,detail={'code':'PLAN_UPGRADE_REQUIRED','feature':feature.value,
        'current_plan':subscription.effective().value,'required_plan':required,
        'pricing_url':'/pricing','message':'This service is not available on your current plan.' if required else 'This service is not available for activation.'})

async def guard_feature(pool,settings,tenant_id,feature):
    if not enabled(settings):return
    try:
        async with pool.acquire() as c:require_subscription_feature(await read_subscription(c,tenant_id),feature)
    except asyncpg.PostgresError:raise HTTPException(503,'Subscription storage is temporarily unavailable') from None

def require_feature(feature_name:str):
    feature=Feature(feature_name)
    from main import authenticate
    async def dependency(request:Request,context=Depends(authenticate)):
        await guard_feature(request.app.state.finance.pool,request.app.state.settings,context.tenant_id,feature)
        return context
    return dependency

async def check_quota(connection,tenant_id:UUID,quota_type:Literal['USERS','STORES','MONTHLY_PARCELS'],*,additional=1,exclude_invitation:UUID|None=None):
    """Caller retains the transaction. Tenant lock serializes every quota-changing write."""
    if quota_type not in {'USERS','STORES','MONTHLY_PARCELS'}:raise ValueError('Unknown quota')
    if type(additional) is not int or additional<0:raise ValueError('Invalid quota increment')
    subscription=await read_subscription(connection,tenant_id,lock=True)
    policy=capabilities(subscription.effective())
    if quota_type=='USERS':
        used=await connection.fetchval("""SELECT (SELECT count(*) FROM public.users WHERE tenant_id=$1 AND is_active)+
            (SELECT count(*) FROM public.workspace_invitations WHERE tenant_id=$1 AND status IN ('SENDING','PENDING')
             AND expires_at>now() AND ($2::uuid IS NULL OR id<>$2))""",tenant_id,exclude_invitation)
        limit=policy.max_users
    elif quota_type=='STORES':
        used=await connection.fetchval('SELECT count(*) FROM public.ecommerce_stores WHERE tenant_id=$1 AND is_active',tenant_id)
        limit=policy.max_store_connections
    else:
        used=await connection.fetchval('SELECT parcels FROM public.v_tenant_monthly_usage WHERE tenant_id=$1',tenant_id) or 0
        limit=policy.included_monthly_parcels
    over=max(0,int(used)+additional-limit)
    if subscription.plan_enforcement_enabled and over and (quota_type!='MONTHLY_PARCELS' or subscription.effective()==Plan.STARTER):
        raise HTTPException(402,{'code':'PLAN_QUOTA_EXCEEDED','quota':quota_type,'used':int(used),'limit':limit,
            'current_plan':subscription.effective().value,'pricing_url':'/pricing'})
    return {'quota':quota_type,'used':int(used),'limit':limit,'projected_overage':over,
        'overage_fee_gbp':str(policy.overage_fee_gbp),'automatic_overage_charge':False}

async def seed_subscription(connection,tenant_id,plan:Plan|str,cycle:str,*,sandbox=False,trial_days=14):
    """Only verified provisioning calls this. A paid choice creates a bounded trial, not ACTIVE access."""
    plan=Plan.COMMAND if sandbox else Plan(plan)
    status='TRIALING' if plan!=Plan.STARTER and not sandbox else 'ACTIVE'
    await connection.execute("""UPDATE public.tenants SET subscription_plan=$2,billing_cycle=$3,plan_status=$4::text,
        plan_period_start=now(),plan_period_end=CASE WHEN $4::text='TRIALING' THEN now()+make_interval(days=>$5) END,
        plan_enforcement_enabled=true,subscription_complimentary=$6 WHERE tenant_id=$1""",
        tenant_id,plan.value,cycle,status,trial_days,sandbox)
    await seed_margin(connection,tenant_id,plan)

async def seed_margin(connection,tenant_id,plan):
    # A tagged baseline, not a rewrite of approved bespoke business rules or personal pricing.
    for currency in ('GBP','EUR','USD'):
        await connection.execute("""INSERT INTO public.margin_rules(id,tenant_id,currency,markup_type,markup_value,priority,is_active,valid_from,subscription_baseline)
            VALUES(gen_random_uuid(),$1,$2,'PERCENTAGE',$3,900000,true,now(),true)
            ON CONFLICT(tenant_id,currency) WHERE subscription_baseline
            DO UPDATE SET markup_value=excluded.markup_value,is_active=true""",
            tenant_id,currency,capabilities(plan).default_markup_percent)
