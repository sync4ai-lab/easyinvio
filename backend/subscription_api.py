"""Workspace plan visibility and owner-only, audited platform commercial controls."""
from __future__ import annotations
import csv
import hashlib
import io
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from backend.entitlements import (Plan,capabilities,enabled,read_subscription,seed_margin,
    require_subscription_feature)
from backend.subscription_billing import SubscriptionCheckout,checkout

class PlanChange(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    request_id:UUID
    expected_version:int=Field(ge=1)
    subscription_plan:Plan
    billing_cycle:Literal['MONTHLY','ANNUAL']='MONTHLY'
    plan_status:Literal['ACTIVE','TRIALING','PAST_DUE','CANCELLED']='ACTIVE'
    trial_days:int=Field(default=14,ge=1,le=30)
    complimentary:bool=Field(default=False,strict=True)
    dedicated_account_manager:str|None=Field(default=None,max_length=200,pattern=r'^[^\x00-\x1f\x7f]*$')
    reason:str=Field(min_length=10,max_length=500)

def plain(value):
    if isinstance(value,(UUID,Decimal)):return str(value)
    if isinstance(value,datetime):return value.isoformat()
    if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [plain(v) for v in value]
    return value

def ready(request):
    if not enabled(request.app.state.settings):raise HTTPException(503,'Subscription tiers are not enabled on this deployment')
    pool=getattr(getattr(request.app.state,'finance',None),'pool',None)
    if pool is None:raise HTTPException(503,'Subscription storage is unavailable')
    return pool

def period(start:datetime|None,end:datetime|None):
    now=datetime.now(timezone.utc)
    start=start or now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    end=end or now
    if start.tzinfo is None or end.tzinfo is None or end<=start or end-start>timedelta(days=366):
        raise HTTPException(422,'Choose a timezone-aware reporting range of at most 366 days')
    return start,end

async def change_plan(c,tenant_id,body,actor):
    subscription=await read_subscription(c,tenant_id,lock=True)
    digest=hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    previous=await c.fetchrow("""SELECT tenant_id,payload_sha256,response FROM public.admin_configuration_events
        WHERE actor_auth_user_id=$1 AND operation='UPDATE_SUBSCRIPTION' AND request_id=$2""",actor.user_id,body.request_id)
    if previous:
        if previous['tenant_id']!=tenant_id or previous['payload_sha256']!=digest:raise HTTPException(409,'Request reference already used with different plan settings')
        return json.loads(previous['response']) if isinstance(previous['response'],str) else previous['response']
    if subscription.plan_version!=body.expected_version:raise HTTPException(409,'Plan changed. Refresh before saving.')
    if subscription.stripe_subscription_id:
        raise HTTPException(409,'A provider-managed subscription must be changed through its billing agreement, not overridden locally')
    if subscription.pending_plan or subscription.cancellation_effective_at:
        raise HTTPException(409,'Resolve the scheduled commercial change before applying a manual plan override')
    policy=capabilities(body.subscription_plan if body.plan_status in {'ACTIVE','TRIALING'} else Plan.STARTER)
    seats=await c.fetchval("""SELECT (SELECT count(*) FROM public.users WHERE tenant_id=$1 AND is_active)+
        (SELECT count(*) FROM public.workspace_invitations WHERE tenant_id=$1 AND status IN ('SENDING','PENDING') AND expires_at>now())""",tenant_id)
    stores=await c.fetchval('SELECT count(*) FROM public.ecommerce_stores WHERE tenant_id=$1 AND is_active',tenant_id)
    if seats>policy.max_users or stores>policy.max_store_connections:
        raise HTTPException(409,{'code':'PLAN_DOWNGRADE_CAPACITY','active_or_reserved_users':seats,'active_stores':stores,
            'message':'Deactivate excess users, pending invitations or stores before changing the plan.'})
    if body.plan_status=='TRIALING' and body.subscription_plan==Plan.STARTER:raise HTTPException(422,'Starter does not require a trial')
    result=await c.fetchrow("""UPDATE public.tenants SET subscription_plan=$2,billing_cycle=$3,plan_status=$4::text,
        plan_period_end=CASE WHEN $4::text='TRIALING' THEN now()+make_interval(days=>$5) ELSE NULL END,
        subscription_complimentary=$6,dedicated_account_manager=$7,plan_version=plan_version+1,
        plan_enforcement_enabled=true WHERE tenant_id=$1
        RETURNING tenant_id,subscription_plan,billing_cycle,plan_status,plan_period_end,subscription_complimentary,dedicated_account_manager,plan_version""",
        tenant_id,body.subscription_plan.value,body.billing_cycle,body.plan_status,body.trial_days,
        body.complimentary or body.plan_status=='TRIALING',body.dedicated_account_manager)
    await seed_margin(c,tenant_id,body.subscription_plan)
    response=plain(dict(result))
    response['previous_plan']=subscription.subscription_plan.value
    response['reason']=body.reason
    await c.execute("""INSERT INTO public.admin_configuration_events(id,actor_auth_user_id,operation,request_id,tenant_id,payload_sha256,response)
        VALUES($1,$2,'UPDATE_SUBSCRIPTION',$3,$4,$5,$6::jsonb)""",uuid4(),actor.user_id,body.request_id,tenant_id,digest,json.dumps(response))
    # A downgrade cannot retain an old quote/price; quote-version fencing handles other in-flight actions.
    return response

MRR_SQL="""CASE WHEN t.workspace_status='ACTIVE' AND t.plan_status IN ('ACTIVE','PENDING_CANCELLATION') AND NOT t.subscription_complimentary
 AND (t.plan_period_end IS NULL OR t.plan_period_end>now()) THEN
 CASE t.subscription_plan WHEN 'VELOCITY' THEN CASE t.billing_cycle WHEN 'ANNUAL' THEN 24 ELSE 29 END
 WHEN 'COMMAND' THEN CASE t.billing_cycle WHEN 'ANNUAL' THEN 65 ELSE 79 END ELSE 0 END ELSE 0 END"""

def build_router(authenticate,authenticate_platform_owner):
    router=APIRouter(tags=['Subscription plans'])

    @router.post('/api/v1/workspace/subscription/checkout')
    async def start_checkout(body:SubscriptionCheckout,request:Request,context=Depends(authenticate)):
        ready(request)
        return await checkout(request,context,body)

    @router.get('/api/v1/workspace/entitlements')
    async def entitlements(request:Request,context=Depends(authenticate)):
        pool=ready(request)
        async with pool.acquire() as c:
            subscription=await read_subscription(c,context.tenant_id)
            usage=await c.fetchrow('SELECT * FROM public.v_tenant_monthly_usage WHERE tenant_id=$1',context.tenant_id)
        policy=capabilities(subscription.effective())
        return plain({'plan':subscription.subscription_plan.value,'effective_plan':subscription.effective().value,
            'billing_cycle':subscription.billing_cycle,'status':subscription.plan_status,'expires_at':subscription.plan_period_end,
            'version':subscription.plan_version,'grandfathered':False,
            'capabilities':policy.model_dump(exclude={'default_markup_percent'}),'usage':dict(usage) if usage else {},
            'automatic_overage_charge':False,'can_manage_subscription':context.role=='OWNER' and not getattr(context,'assistance_session_id',None),
            'dedicated_account_manager':subscription.dedicated_account_manager})

    @router.patch('/api/v1/admin/tenants/{tenant_id}/plan')
    async def update_plan(tenant_id:UUID,body:PlanChange,request:Request,actor=Depends(authenticate_platform_owner)):
        pool=ready(request)
        try:
            async with pool.acquire() as c:
                async with c.transaction():return await change_plan(c,tenant_id,body,actor)
        except asyncpg.PostgresError:raise HTTPException(503,'Plan storage is temporarily unavailable') from None

    @router.get('/api/v1/admin/revenue/overview')
    async def overview(request:Request,actor=Depends(authenticate_platform_owner),environment:Literal['PRODUCTION','SANDBOX']='PRODUCTION',
                       start:datetime|None=None,end:datetime|None=None,after:UUID|None=None,limit:int=Query(50,ge=1,le=200)):
        pool=ready(request);start,end=period(start,end);sandbox=environment=='SANDBOX'
        async with pool.acquire() as c:
            async with c.transaction(isolation='repeatable_read',readonly=True):
                tiers=await c.fetch("""SELECT subscription_plan,count(*) FILTER(WHERE workspace_status='ACTIVE') AS active_tenants,
                    sum("""+MRR_SQL+""")::numeric AS contracted_mrr_gbp FROM public.tenants t WHERE is_sandbox=$1 GROUP BY subscription_plan""",sandbox)
                totals=await c.fetch("""SELECT s.currency,sum(s.final_client_price)::numeric AS label_gross_revenue,
                    sum(s.final_client_price-s.profit_markup)::numeric AS recorded_wholesale_cost,
                    sum(s.profit_markup)::numeric AS stored_gross_label_margin FROM public.shipments s JOIN public.tenants t USING(tenant_id)
                    WHERE t.is_sandbox=$1 AND s.booked_at>=$2 AND s.booked_at<$3 GROUP BY s.currency""",sandbox,start,end)
                rows=await c.fetch("""SELECT t.tenant_id,t.company_name,t.subscription_plan,t.billing_cycle,t.plan_status,t.plan_version,
                    public.effective_subscription_plan(t.subscription_plan,t.plan_status,t.plan_period_end) AS effective_plan,
                    t.plan_period_end,t.subscription_complimentary,t.plan_enforcement_enabled,t.dedicated_account_manager,
                    ("""+MRR_SQL+""")::numeric AS contracted_mrr_gbp,u.parcels AS parcels_this_month,
                    w.currency AS wallet_currency,w.balance AS wallet_balance,
                    (SELECT max(created_at) FROM public.wallet_ledger WHERE tenant_id=t.tenant_id) AS last_transaction_at,
                    coalesce((SELECT jsonb_agg(x) FROM (SELECT currency,sum(final_client_price)::text AS label_gross_revenue,
                     sum(profit_markup)::text AS stored_gross_label_margin FROM public.shipments WHERE tenant_id=t.tenant_id
                     AND booked_at>=$2 AND booked_at<$3 GROUP BY currency) x),'[]'::jsonb) AS shipping_totals,
                    coalesce((SELECT sum(amount_paid_gbp) FROM public.subscription_invoice_receipts i WHERE i.tenant_id=t.tenant_id
                     AND i.paid_at>=$2 AND i.paid_at<$3),0)::numeric AS subscription_cash_collected_gbp
                    FROM public.tenants t LEFT JOIN public.v_tenant_monthly_usage u USING(tenant_id)
                    LEFT JOIN public.wallets w USING(tenant_id) WHERE t.is_sandbox=$1 AND ($4::uuid IS NULL OR t.tenant_id>$4)
                    ORDER BY t.tenant_id LIMIT $5""",sandbox,start,end,after,limit+1)
        has_more=len(rows)>limit;rows=rows[:limit]
        result=[]
        for row in rows:
            item=dict(row);item['monthly_parcel_allowance']=capabilities(item['effective_plan']).included_monthly_parcels
            if isinstance(item['shipping_totals'],str):item['shipping_totals']=json.loads(item['shipping_totals'])
            result.append(item)
        return plain({'environment':environment,'start':start,'end':end,'tiers':[dict(x) for x in tiers],
            'contracted_mrr_gbp':sum((Decimal(str(x['contracted_mrr_gbp'] or 0)) for x in tiers),Decimal(0)),
            'label_totals_by_currency':[dict(x) for x in totals],'tenants':result,
            'next_cursor':rows[-1]['tenant_id'] if has_more else None,
            'basis':'MRR is contracted monthly run rate, not cash or profit. Annual contracts use their monthly equivalent. Trials and complimentary access are excluded. Label margin is stored gross markup before refunds, carrier adjustments, taxes and operating expenses. Wallet balances are customer funds, not revenue.'})

    @router.get('/api/v1/admin/revenue/tenants/{tenant_id}/transactions')
    async def transactions(tenant_id:UUID,request:Request,actor=Depends(authenticate_platform_owner),
                           before:datetime|None=None,before_id:str|None=None,limit:int=Query(100,ge=1,le=200)):
        pool=ready(request)
        if (before is None)!=(before_id is None) or (before and before.tzinfo is None):raise HTTPException(422,'Supply both timestamp and entry ID cursor')
        if before_id and len(before_id)>100:raise HTTPException(422,'Invalid cursor')
        async with pool.acquire() as c:
            if not await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.tenants WHERE tenant_id=$1)',tenant_id):raise HTTPException(404,'Workspace not found')
            ledger=await c.fetch("""SELECT id,created_at,currency,entry_type,balance_delta,reserved_delta,balance_after,reserved_after,reservation_id
                FROM public.wallet_ledger WHERE tenant_id=$1 AND ($2::timestamptz IS NULL OR (created_at,id::text)<($2,$3))
                ORDER BY created_at DESC,id::text DESC LIMIT $4""",tenant_id,before,before_id,limit+1)
            shipments=await c.fetch("""SELECT id,booked_at,currency,carrier_code,final_client_price,
                final_client_price-profit_markup AS recorded_wholesale_cost,profit_markup AS stored_gross_label_margin
                FROM public.shipments WHERE tenant_id=$1 AND booked_at IS NOT NULL ORDER BY booked_at DESC,id DESC LIMIT $2""",tenant_id,limit)
        more=len(ledger)>limit;ledger=ledger[:limit]
        return plain({'tenant_id':tenant_id,'wallet_movements':[dict(x) for x in ledger],
            'recent_shipments':[dict(x) for x in shipments],'next_cursor':{'before':ledger[-1]['created_at'],'before_id':str(ledger[-1]['id'])} if more else None})

    @router.get('/api/v1/workspace/ledger/export')
    async def export(request:Request,context=Depends(authenticate),start:datetime|None=None,end:datetime|None=None):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:raise HTTPException(403,'Finance permission required')
        pool=ready(request);start,end=period(start,end)
        async with pool.acquire() as c:
            require_subscription_feature(await read_subscription(c,context.tenant_id),'tax_ledger_audits')
            rows=await c.fetch("""SELECT created_at,currency,entry_type,balance_delta,reserved_delta,balance_after,reserved_after
                FROM public.wallet_ledger WHERE tenant_id=$1 AND created_at>=$2 AND created_at<$3 ORDER BY created_at,id LIMIT 10001""",context.tenant_id,start,end)
        if len(rows)>10000:raise HTTPException(422,'Choose a shorter export period (maximum 10,000 entries)')
        text=io.StringIO(newline='');writer=csv.writer(text)
        writer.writerow(['Recorded UTC','Currency','Event','Wallet change','Hold change','Wallet after','Held after'])
        writer.writerows([[plain(v) for v in dict(row).values()] for row in rows])
        return Response(text.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="easyinvio-ledger.csv"','Cache-Control':'no-store'})
    return router
