"""Durable subscription commands. Quotes never charge; payment precedes paid access.

Software wallet debits have their own constrained, idempotent ledger event. Stripe
upgrades use a dedicated hosted invoice, then change the recurring price without
Stripe generating a second proration. Unknown provider outcomes require review.
"""
from __future__ import annotations
import asyncio,hashlib,json,logging
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID,uuid4
import asyncpg,stripe
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from backend.entitlements import Plan,capabilities,read_subscription,seed_margin
from backend.subscription_math import money,calculate_proration,upgrade_breakdown,cancellation_breakdown,annual_refund_breakdown,cycle_price,add_cycle
from backend.subscription_billing import as_dict,reference,provider_plan,validate_price

logger=logging.getLogger('easyinvio.subscription_lifecycle')

class ChangeRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    target_plan:Plan|None=None
    confirm:bool=Field(default=False,strict=True)
    quote_sha256:str|None=Field(default=None,min_length=64,max_length=64,pattern=r'^[a-f0-9]+$')
    funding:Literal['STRIPE','WALLET']='STRIPE'

def utcnow():return datetime.now(timezone.utc).replace(microsecond=0)
def decoded(value):return json.loads(value) if isinstance(value,str) else value
def document(value):
    if isinstance(value,(Decimal,UUID)):return str(value)
    if isinstance(value,datetime):return value.isoformat()
    if isinstance(value,dict):return {k:document(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [document(v) for v in value]
    return value

def owner(context):
    if context.role!='OWNER' or getattr(context,'assistance_session_id',None):
        raise HTTPException(403,'The customer workspace Owner must authorize commercial changes')

def statements_enabled(settings):
    # Existing lifecycle-enabled deployments retain statement access. The new
    # independent switch never starts payment workers or authorizes plan changes.
    return bool(getattr(settings,'billing_statements_enabled',False) or getattr(settings,'billing_lifecycle_enabled',False))

def require_statements(settings):
    if not statements_enabled(settings):raise HTTPException(503,{
        'code':'BILLING_STATEMENTS_DISABLED',
        'message':'Billing statements are not enabled for this deployment. Contact the platform administrator to enable statement access.'})

def management_options(sub,settings,context,now=None):
    """Explain eligibility without inventing a paid term for assigned/free access."""
    now=now or utcnow();reason=None
    if context.role!='OWNER' or getattr(context,'assistance_session_id',None):reason='Only the workspace Owner can change or cancel the subscription.'
    elif not getattr(settings,'billing_lifecycle_enabled',False):reason='Subscription changes are not enabled. You can still compare plans and view statements.'
    elif not sub.plan_enforcement_enabled:reason='Your access is managed by EasyInvio. Contact support to change the assigned plan.'
    elif sub.pending_plan or sub.cancellation_effective_at:reason='A change is already scheduled. Its effective date is shown above.'
    elif sub.subscription_plan==Plan.STARTER and not sub.stripe_subscription_id:
        reason='Starter has no paid subscription to cancel. To activate a paid plan, choose a plan below, review the terms and confirm to continue to payment.'
    elif sub.plan_period_end is None:
        reason=('No paid subscription. Choose a plan to review a new subscription.' if sub.subscription_complimentary
            else 'No billing period or renewal date is recorded for this account. Contact support to configure the billing agreement before changing or cancelling it.')
    elif sub.plan_period_end<=now:reason='The recorded billing period has ended. Contact support to reconcile the subscription before changing it.'
    elif sub.plan_status not in {'ACTIVE','TRIALING','PAST_DUE'}:reason='This subscription is not active. Contact support to review the agreement.'
    ordered=list(Plan);rank=ordered.index(sub.subscription_plan)
    return {'reason':reason,'upgrade_targets':[p.value for p in ordered[rank+1:]] if not reason and sub.plan_status!='PAST_DUE' else [],
        'downgrade_targets':[p.value for p in ordered[:rank]] if not reason and sub.plan_status!='PAST_DUE' else [],
        'can_cancel':not reason and sub.subscription_plan!=Plan.STARTER,
        'activation_targets':[p.value for p in Plan if p!=Plan.STARTER] if context.role=='OWNER' and not getattr(context,'assistance_session_id',None) and not sub.stripe_subscription_id and not sub.pending_plan and not sub.cancellation_effective_at and (sub.subscription_complimentary or sub.subscription_plan==Plan.STARTER) else [],
        'access_type':'COMPLIMENTARY' if sub.subscription_complimentary else 'BILLED' if sub.plan_period_end else 'ASSIGNED'}

class SubscriptionLifecycle:
    def __init__(self,finance,settings):self.finance=finance;self.pool=finance.pool;self.settings=settings

    def ready(self):
        if not getattr(self.settings,'billing_lifecycle_enabled',False):raise HTTPException(503,{
            'code':'BILLING_LIFECYCLE_DISABLED','message':'Subscription changes are not enabled for this deployment. Statement access can be enabled separately.'})

    async def event(self,c,op,event_type,*,amount=None,breakdown=None):
        await c.execute('''INSERT INTO public.subscription_change_events
         (tenant_id,operation_id,event_type,actor_auth_user_id,amount,currency,effective_at,breakdown)
         VALUES($1,$2,$3,$4,$5,'GBP',$6,$7::jsonb) ON CONFLICT(operation_id,event_type) DO NOTHING''',
         op['tenant_id'],op['id'],event_type,op['actor_auth_user_id'],money(op['amount'] if amount is None else amount),
         op['effective_at'],json.dumps(document(breakdown or decoded(op['payload']))))

    async def status(self,context):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:raise HTTPException(403,'Financial permission required')
        async with self.pool.acquire() as c:
            sub=await read_subscription(c,context.tenant_id)
            tenant=await c.fetchrow('''SELECT tenant_id,created_at AS registered_at,subscription_plan,billing_cycle,plan_status,plan_period_start,plan_period_end,stripe_subscription_id,
             plan_version,subscription_complimentary,pending_plan,pending_billing_cycle,pending_plan_effective_at,
             cancellation_requested_at,cancellation_effective_at,final_notice_prorated_amount,final_notice_billed
             FROM public.tenants WHERE tenant_id=$1''',context.tenant_id)
            operations=await c.fetch('''SELECT id,action,state,amount,currency,effective_at,provider_url,error_code,created_at
             FROM public.subscription_operations WHERE tenant_id=$1 ORDER BY created_at DESC,id DESC LIMIT 20''',context.tenant_id)
            usage=await c.fetchval('SELECT parcels FROM public.v_tenant_monthly_usage WHERE tenant_id=$1',context.tenant_id) or 0
        if not tenant:raise HTTPException(404,'Workspace not found')
        return document({'registered_at':tenant['registered_at'],'effective_plan':sub.effective().value,'usage':{'parcels':int(usage)},'subscription':dict(tenant),'operations':[dict(x) for x in operations],
            'can_manage':bool(getattr(self.settings,'billing_lifecycle_enabled',False)) and context.role=='OWNER' and not getattr(context,'assistance_session_id',None),
            'is_sandbox':sub.is_sandbox,'management':management_options(sub,self.settings,context),
            'activation_checkout_available':{p.value:bool(getattr(self.settings,'stripe_enabled',False) and getattr(self.settings,'subscription_price_ids',{}).get(p.value+':'+sub.billing_cycle)) for p in Plan if p!=Plan.STARTER},
            'plans':[{'plan':p.value,'annual_fee_gbp':cycle_price(p,'ANNUAL'),**capabilities(p).model_dump()} for p in Plan],
            'annual_cancellation_policy':'MONTHLY_PRICE_CLAWBACK'})

    async def command(self,context,action,body:ChangeRequest):
        self.ready();owner(context)
        if action not in {'UPGRADE','DOWNGRADE','CANCEL'}:raise HTTPException(422,'Unknown commercial action')
        if action=='CANCEL' and body.target_plan is not None:raise HTTPException(422,'Cancellation does not accept a target tier')
        now=utcnow();execute=False
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,52))','commercial:'+str(context.tenant_id))
                sub=await read_subscription(c,context.tenant_id,lock=True)
                tenant=await c.fetchrow('SELECT * FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
                op=await c.fetchrow('SELECT * FROM public.subscription_operations WHERE tenant_id=$1 AND request_id=$2 FOR UPDATE',context.tenant_id,body.request_id)
                if op:
                    wanted=body.target_plan.value if body.target_plan else 'STARTER'
                    if op['action']!=action or op['target_plan']!=wanted or op['funding']!=body.funding:
                        raise HTTPException(409,'Request reference was used for different commercial terms')
                    if op['actor_auth_user_id']!=context.user_id:raise HTTPException(403,'Only the original customer Owner may confirm this preview')
                    if op['state']!='PREVIEW':return self.present(op)
                    if not body.confirm:return self.present(op)
                    if body.quote_sha256!=op['payload_sha256'] or op['expires_at']<=now or op['plan_version']!=sub.plan_version:
                        raise HTTPException(409,'The commercial preview changed or expired. Request a fresh preview.')
                    if tenant['pending_plan'] or tenant['cancellation_requested_at']:
                        raise HTTPException(409,'An existing scheduled change must be resolved first')
                    await c.execute("UPDATE public.subscription_operations SET state='AUTHORIZED',updated_at=now() WHERE id=$1",op['id'])
                    op={**dict(op),'state':'AUTHORIZED'};await self.event(c,op,'AUTHORIZED');execute=True
                else:
                    if body.confirm:raise HTTPException(409,'Request a preview before authorizing a charge')
                    if not sub.plan_enforcement_enabled:raise HTTPException(409,'Enroll this workspace in subscription tiers before changing its agreement')
                    if tenant['pending_plan'] or tenant['cancellation_requested_at']:raise HTTPException(409,'A commercial change is already scheduled')
                    statuses={'ACTIVE','TRIALING','PAST_DUE'} if action=='CANCEL' else {'ACTIVE','TRIALING'}
                    if sub.plan_status not in statuses or sub.plan_period_end is None or sub.plan_period_end<=now:
                        raise HTTPException(409,'A current, bounded subscription period is required. Activate or reconcile your subscription first.')
                    if sub.stripe_subscription_id and body.funding!='STRIPE':raise HTTPException(409,'A Stripe subscription must be changed through its Stripe agreement')
                    if not sub.stripe_subscription_id and body.funding=='STRIPE':raise HTTPException(409,'Activate a Stripe subscription first, or explicitly select your wallet for a wallet-funded agreement')
                    target=body.target_plan or Plan.STARTER;effective=now;amount=Decimal(0)
                    if action=='UPGRADE':
                        if body.target_plan is None:raise HTTPException(422,'Choose an upgrade tier')
                        breakdown=upgrade_breakdown(sub.subscription_plan,target,sub.billing_cycle,sub.plan_period_start,sub.plan_period_end,now)
                        amount=money(breakdown['prorated_amount'])
                        if sub.plan_status=='TRIALING' or sub.subscription_complimentary:
                            amount=Decimal('0.00');breakdown['complimentary_or_trial']=True
                    elif action=='DOWNGRADE':
                        if list(Plan).index(target)>=list(Plan).index(sub.subscription_plan):raise HTTPException(422,'Choose a strictly lower tier')
                        effective=sub.plan_period_end
                        breakdown={'effective_at':effective,'current_features_retained_until':effective,
                            'next_period_price':cycle_price(target,sub.billing_cycle),'no_mid_cycle_credit':True}
                    else:
                        if sub.subscription_plan==Plan.STARTER:raise HTTPException(409,'Starter has no paid subscription to cancel')
                        target=Plan.STARTER
                        if sub.plan_status=='TRIALING' or sub.subscription_complimentary:
                            trial_end=min(now+timedelta(days=30),sub.plan_period_end)
                            breakdown={'requested_at':now.isoformat(),'cancellation_effective_at':trial_end.isoformat(),
                                'final_notice_prorated_amount':'0.00','notice_days':30,'complimentary_or_trial':True}
                        else:breakdown=cancellation_breakdown(sub.subscription_plan,sub.billing_cycle,sub.plan_period_start,sub.plan_period_end,now)
                        effective=datetime.fromisoformat(breakdown['cancellation_effective_at'])
                        if sub.billing_cycle=='ANNUAL':
                            if sub.plan_status=='ACTIVE' and not sub.subscription_complimentary:
                                invoices=await c.fetch('''SELECT * FROM public.subscription_invoice_receipts WHERE tenant_id=$1
                                 AND stripe_subscription_id=$2 AND paid_at>=$3 AND paid_at<=$4 ORDER BY paid_at,stripe_invoice_id''',
                                 context.tenant_id,sub.stripe_subscription_id,sub.plan_period_start,now)
                                if not invoices or any(r['invoice_net_gbp'] is None or not r['invoice_payment_intent_id'] for r in invoices):
                                    raise HTTPException(409,'Annual payment receipts are being reconciled. Please retry shortly; no cancellation fee or refund has been charged.')
                                prepaid=Decimal(0);proof=[]
                                for r in invoices:
                                    gross=money(r['invoice_gross_gbp']);net=money(r['invoice_net_gbp']);refunded=money(r['invoice_refunded_gbp'])
                                    if not 0<=net<=gross or not 0<=refunded<=gross or money(r['amount_paid_gbp'])!=gross:
                                        raise HTTPException(409,'Annual payment amounts require reconciliation')
                                    available_net=money(net*(gross-refunded)/gross) if gross else Decimal(0)
                                    prepaid+=available_net;proof.append({'invoice_id':r['stripe_invoice_id'],'payment_intent_id':r['invoice_payment_intent_id'],
                                        'net_available':str(available_net),'gross_available':str(max(Decimal(0),gross-refunded)),
                                        'gross_refunded_at_preview':str(refunded),
                                        'net_original':str(net),'gross_original':str(gross)})
                                changes=await c.fetch('''SELECT o.source_plan,o.target_plan,coalesce(o.applied_at,o.effective_at) AS effective_at FROM public.subscription_operations o
                                 WHERE o.tenant_id=$1 AND o.action='UPGRADE' AND o.state='APPLIED'
                                 AND coalesce(o.applied_at,o.effective_at)>=$2 AND coalesce(o.applied_at,o.effective_at)<=$3
                                 ORDER BY coalesce(o.applied_at,o.effective_at),o.id''',context.tenant_id,sub.plan_period_start,now)
                                initial=changes[0]['source_plan'] if changes else sub.subscription_plan
                                bases=[r for r in invoices if r['operation_id'] is None]
                                if len(bases)!=1 or money(bases[0]['invoice_net_gbp'])!=cycle_price(initial,'ANNUAL'):
                                    raise HTTPException(409,'The original annual tier or an untracked adjustment requires finance reconciliation before calculating a refund')
                                annual=annual_refund_breakdown(initial,sub.plan_period_start,sub.plan_period_end,now,prepaid,
                                    [(r['effective_at'],r['target_plan']) for r in changes])
                                breakdown={**breakdown,'annual_clawback':annual,'refund_sources':proof,
                                    'final_notice_prorated_amount':annual['additional_balance_for_review']}
                                effective=datetime.fromisoformat(annual['cancellation_effective_at'])
                        amount=money(breakdown['final_notice_prorated_amount'])
                        if sub.plan_status=='TRIALING' or sub.subscription_complimentary:
                            amount=Decimal('0.00');effective=min(effective,sub.plan_period_end)
                            breakdown.update(final_notice_prorated_amount='0.00',cancellation_effective_at=effective,complimentary_or_trial=True)
                        if sub.plan_status=='PAST_DUE':
                            amount=Decimal('0.00');breakdown.update(final_notice_prorated_amount='0.00',unpaid_agreement_requires_reconciliation=True)
                    tax_rate=Decimal(str(getattr(self.settings,'subscription_wallet_tax_percent','0')))
                    tax=money(amount*tax_rate/100) if body.funding=='WALLET' else Decimal(0)
                    if action=='DOWNGRADE' and body.funding=='WALLET':
                        next_net=cycle_price(target,sub.billing_cycle)
                        breakdown['next_period_wallet_tax']=money(next_net*tax_rate/100)
                        breakdown['next_period_total']=next_net+breakdown['next_period_wallet_tax']
                    payload=document({'breakdown':breakdown,'net_amount':amount,'wallet_tax_amount':tax,
                        'wallet_tax_percent':tax_rate,
                        'stripe_tax_is_on_secure_invoice':body.funding=='STRIPE','paid_period_start':sub.plan_period_start,
                        'paid_period_end':sub.plan_period_end,'subscription_id':sub.stripe_subscription_id,
                        'source_status':sub.plan_status,'complimentary':sub.subscription_complimentary,
                        'target_price_id':getattr(self.settings,'subscription_price_ids',{}).get(target.value+':'+sub.billing_cycle),
                        'next_period_price':cycle_price(target,sub.billing_cycle)})
                    canonical=json.dumps(payload,sort_keys=True,separators=(',',':'));digest=hashlib.sha256(canonical.encode()).hexdigest()
                    op=await c.fetchrow('''INSERT INTO public.subscription_operations
                     (id,tenant_id,actor_auth_user_id,request_id,action,state,source_plan,target_plan,billing_cycle,plan_version,
                      amount,funding,effective_at,preview_at,expires_at,payload,payload_sha256)
                     VALUES($1,$2,$3,$4,$5,'PREVIEW',$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16) RETURNING *''',
                     uuid4(),context.tenant_id,context.user_id,body.request_id,action,sub.subscription_plan.value,target.value,sub.billing_cycle,
                     sub.plan_version,amount+tax,body.funding,effective,now,min(now+timedelta(minutes=10),sub.plan_period_end),canonical,digest)
                    await self.event(c,op,'PREVIEWED')
        # The HTTP process never waits on a multi-call provider workflow.
        if execute and op['funding']!='STRIPE':
            try:await self.execute(op['id'])
            except HTTPException as exc:
                async with self.pool.acquire() as c:await c.execute("UPDATE public.subscription_operations SET state='FAILED',error_code='WALLET_PAYMENT_FAILED' WHERE id=$1 AND state='AUTHORIZED'",op['id'])
                raise exc
        async with self.pool.acquire() as c:op=await c.fetchrow('SELECT * FROM public.subscription_operations WHERE tenant_id=$1 AND id=$2',context.tenant_id,op['id'])
        return self.present(op)

    @staticmethod
    def present(op):
        return document({k:op[k] for k in ('id','request_id','action','state','source_plan','target_plan','billing_cycle',
            'amount','currency','effective_at','expires_at','payload','payload_sha256','provider_url','error_code')}) | {'payload':document(decoded(op['payload']))}

    async def debit_wallet(self,c,op):
        if money(op['amount'])==0:return
        existing=await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.wallet_ledger WHERE tenant_id=$1 AND subscription_operation_id=$2)',op['tenant_id'],op['id'])
        if existing:return
        wallet=await c.fetchrow('SELECT currency,balance,reserved_balance FROM public.wallets WHERE tenant_id=$1 FOR UPDATE',op['tenant_id'])
        amount=money(op['amount'])
        if not wallet or wallet['currency']!='GBP':raise HTTPException(409,'Software wallet billing requires a GBP wallet')
        balance=money(wallet['balance']);reserved=money(wallet['reserved_balance'])
        if balance-reserved<amount:raise HTTPException(402,'Insufficient available wallet funds for this software charge')
        after=balance-amount
        await c.execute('UPDATE public.wallets SET balance=$2,updated_at=now() WHERE tenant_id=$1',op['tenant_id'],after)
        await c.execute('''INSERT INTO public.wallet_ledger(tenant_id,currency,entry_type,balance_delta,reserved_delta,
         balance_after,reserved_after,subscription_operation_id) VALUES($1,'GBP','SUBSCRIPTION_DEBIT',$2,0,$3,$4,$5)''',op['tenant_id'],-amount,after,reserved,op['id'])
        await self.event(c,op,'PAID')

    async def apply(self,c,op):
        payload=decoded(op['payload']);action=op['action']
        if action=='UPGRADE':
            await c.execute('''UPDATE public.tenants SET subscription_plan=$2,plan_version=plan_version+1 WHERE tenant_id=$1''',op['tenant_id'],op['target_plan'])
            await seed_margin(c,op['tenant_id'],op['target_plan'])
        elif action=='DOWNGRADE':
            await c.execute('''UPDATE public.tenants SET pending_plan=$2,pending_billing_cycle=$3,pending_plan_effective_at=$4 WHERE tenant_id=$1''',op['tenant_id'],op['target_plan'],op['billing_cycle'],op['effective_at'])
        elif action=='CANCEL':
            paid_end=datetime.fromisoformat(payload['paid_period_end'])
            await c.execute('''UPDATE public.tenants SET cancellation_requested_at=$2,cancellation_effective_at=$3,
             final_notice_prorated_amount=$4,final_notice_billed=($4::numeric=0),plan_status=CASE WHEN plan_status='PAST_DUE' THEN 'PAST_DUE' ELSE 'PENDING_CANCELLATION' END,
             plan_period_end=least($3::timestamptz,$5::timestamptz),plan_version=plan_version+1 WHERE tenant_id=$1''',
             op['tenant_id'],op['preview_at'],op['effective_at'],money(payload['net_amount']),paid_end)
        elif action=='NOTICE_CHARGE':
            await c.execute('''UPDATE public.tenants SET final_notice_billed=true,plan_period_end=cancellation_effective_at
             WHERE tenant_id=$1 AND cancellation_effective_at>now() AND plan_status='PENDING_CANCELLATION' ''',op['tenant_id'])
        elif action=='DOWNGRADE_RENEWAL':
            await c.execute('''UPDATE public.tenants SET subscription_plan=$2,billing_cycle=$3,plan_period_start=$4,
             plan_period_end=$5,plan_status='ACTIVE',pending_plan=NULL,pending_billing_cycle=NULL,pending_plan_effective_at=NULL,
             plan_version=plan_version+1 WHERE tenant_id=$1''',op['tenant_id'],op['target_plan'],op['billing_cycle'],op['effective_at'],add_cycle(op['effective_at'],op['billing_cycle']))
            await seed_margin(c,op['tenant_id'],op['target_plan'])
            parent=await c.fetchrow("UPDATE public.subscription_operations SET state='APPLIED',updated_at=now() WHERE tenant_id=$1 AND action='DOWNGRADE' AND state='SCHEDULED' RETURNING *",op['tenant_id'])
            if parent:await self.event(c,parent,'DOWNGRADE_EFFECTIVE',amount=0)
        scheduled=action in {'DOWNGRADE','CANCEL'}
        await c.execute('UPDATE public.subscription_operations SET state=$2,updated_at=now(),applied_at=CASE WHEN $2=\'APPLIED\' THEN now() ELSE applied_at END,error_code=NULL WHERE id=$1',op['id'],'SCHEDULED' if scheduled else 'APPLIED')
        await self.event(c,op,'SCHEDULED' if scheduled else 'APPLIED')

    async def stripe_client(self,op):
        if not self.settings.stripe_enabled or self.finance.stripe is None:raise HTTPException(503,'Stripe is not enabled for subscription changes')
        payload=decoded(op['payload'])
        async with self.pool.acquire() as c:tenant=await c.fetchrow('SELECT stripe_customer_id,is_sandbox FROM public.tenants WHERE tenant_id=$1',op['tenant_id'])
        if not tenant or not tenant['stripe_customer_id'] or tenant['is_sandbox']==self.settings.stripe_livemode:raise HTTPException(409,'Subscription payment identity or environment requires reconciliation')
        return self.finance.stripe,tenant['stripe_customer_id'],payload

    async def execute(self,operation_id):
        self.ready()
        async with self.pool.acquire() as c:
            async with c.transaction():
                # All writers take tenant before operation: never invert finance's tenant-first order.
                identity=await c.fetchrow('SELECT tenant_id FROM public.subscription_operations WHERE id=$1',operation_id)
                if not identity:return
                sub=await read_subscription(c,identity['tenant_id'],lock=True)
                op=await c.fetchrow('SELECT * FROM public.subscription_operations WHERE id=$1 FOR UPDATE',operation_id)
                if op['state'] not in {'AUTHORIZED','PROVIDER_PENDING','PAID'}:return
                if op['lease_until'] and op['lease_until']>utcnow():return
                if op['action']=='DOWNGRADE_RENEWAL' and op['effective_at']+timedelta(days=1)<utcnow():
                    await c.execute("UPDATE public.subscription_operations SET state='REVIEW',error_code='RENEWAL_SETTLEMENT_LATE' WHERE id=$1",operation_id);return
                if op['action']=='UPGRADE' and sub.plan_version!=op['plan_version'] and sub.subscription_plan.value!=op['target_plan']:
                    await c.execute("UPDATE public.subscription_operations SET state='REVIEW',error_code='PLAN_CHANGED' WHERE id=$1",operation_id);return
                if op['funding'] in {'WALLET','NONE'}:
                    if op['action'] not in {'CANCEL','DOWNGRADE'}:await self.debit_wallet(c,op)
                    await self.apply(c,op);return
                if op['state']=='AUTHORIZED':
                    await c.execute("UPDATE public.subscription_operations SET state='PROVIDER_PENDING',lease_until=now()+interval '5 minutes',updated_at=now() WHERE id=$1",operation_id)
                elif op['state']=='PROVIDER_PENDING' and not op['provider_invoice_id'] and op['action']!='ANNUAL_REFUND':
                    # A crash could have occurred after provider submission. Never create another charge.
                    await c.execute("UPDATE public.subscription_operations SET state='REVIEW',error_code='PROVIDER_OUTCOME_UNKNOWN' WHERE id=$1",operation_id);return
                else:await c.execute("UPDATE public.subscription_operations SET lease_until=now()+interval '5 minutes' WHERE id=$1",operation_id)
        try:
            client,customer,payload=await self.stripe_client(op)
            sid=payload['subscription_id'];action=op['action']
            if action=='ANNUAL_REFUND':
                await self.process_refund(op,client,customer);return
            if action in {'UPGRADE','DOWNGRADE','CANCEL'}:
                current=as_dict(await client.v1.subscriptions.retrieve_async(sid))
                await self.validate_subscription(current,op,payload)
                if reference(current.get('customer'))!=customer or current.get('livemode') is not self.settings.stripe_livemode:
                    raise HTTPException(409,'Subscription customer or environment mismatch')
            if action in {'UPGRADE','DOWNGRADE'} and op['target_plan']!='STARTER':
                price=as_dict(await client.v1.prices.retrieve_async(payload['target_price_id']))
                validate_price(price,op['target_plan'],op['billing_cycle'],self.settings.stripe_livemode)
            if action in {'CANCEL','DOWNGRADE'}:
                if action=='CANCEL' or op['target_plan']=='STARTER':
                    cancel_at=min(datetime.fromisoformat(payload['paid_period_end']),op['effective_at'])
                    await client.v1.subscriptions.update_async(sid,{'cancel_at':int(cancel_at.timestamp()),'proration_behavior':'none'},options={'idempotency_key':'ei-change:'+str(op['id'])})
                else:
                    current=as_dict(await client.v1.subscriptions.retrieve_async(sid))
                    await self.validate_subscription(current,op,payload)
                    price_id=payload['target_price_id']
                    price=as_dict(await client.v1.prices.retrieve_async(price_id))
                    validate_price(price,op['target_plan'],op['billing_cycle'],self.settings.stripe_livemode)
                    # No proration and unchanged interval: next renewal uses the lower price.
                    # The webhook pins local access to the old plan until the scheduled boundary.
                    await client.v1.subscriptions.update_async(sid,{'items':[{'id':current['items']['data'][0]['id'],'price':price_id}],
                        'proration_behavior':'none'},options={'idempotency_key':'ei-change:'+str(op['id'])})
                async with self.pool.acquire() as c:
                    async with c.transaction():
                        await read_subscription(c,op['tenant_id'],lock=True)
                        await self.apply(c,op)
                return
            if not op['provider_invoice_id']:
                invoice=as_dict(await client.v1.invoices.create_async({'customer':customer,'collection_method':'send_invoice','days_until_due':1,
                    'pending_invoice_items_behavior':'exclude','auto_advance':False,
                    'automatic_tax':{'enabled':bool(getattr(self.settings,'subscription_automatic_tax_enabled',False))},
                    'metadata':{'easyinvio_operation_id':str(op['id']),'purpose':'subscription_lifecycle'}},options={'idempotency_key':'ei-invoice:'+str(op['id'])}))
                async with self.pool.acquire() as c:await c.execute('UPDATE public.subscription_operations SET provider_invoice_id=$2 WHERE id=$1',op['id'],invoice['id'])
                await client.v1.invoice_items.create_async({'customer':customer,'invoice':invoice['id'],'amount':int(money(payload['net_amount'])*100),
                    'currency':'gbp','description':'EasyInvio '+action.replace('_',' ').lower()},options={'idempotency_key':'ei-invoice-item:'+str(op['id'])})
                invoice=as_dict(await client.v1.invoices.finalize_invoice_async(invoice['id'],{'auto_advance':False},options={'idempotency_key':'ei-finalize:'+str(op['id'])}))
            else:invoice=as_dict(await client.v1.invoices.retrieve_async(op['provider_invoice_id']))
            if reference(invoice.get('customer'))!=customer or invoice.get('livemode') is not self.settings.stripe_livemode or invoice.get('currency')!='gbp':raise HTTPException(409,'Invoice identity mismatch')
            if (invoice.get('metadata') or {}).get('easyinvio_operation_id')!=str(op['id']):raise HTTPException(409,'Invoice operation mismatch')
            if invoice.get('status')=='draft':raise HTTPException(409,'Unfinalized invoice requires reconciliation')
            if invoice.get('subtotal')!=int(money(payload['net_amount'])*100):raise HTTPException(409,'Invoice amount differs from authorized terms')
            if invoice.get('total_excluding_tax')!=int(money(payload['net_amount'])*100):raise HTTPException(409,'Invoice net amount differs from authorized terms')
            if invoice.get('status')=='paid' and (invoice.get('amount_paid')!=invoice.get('total') or invoice.get('amount_remaining')!=0):
                raise HTTPException(409,'Invoice payment requires reconciliation')
            if invoice.get('status')!='paid':
                async with self.pool.acquire() as c:await c.execute('UPDATE public.subscription_operations SET provider_url=$2,lease_until=now()+interval \'20 seconds\' WHERE id=$1',op['id'],invoice.get('hosted_invoice_url'))
                return
            if action=='UPGRADE':
                current=as_dict(await client.v1.subscriptions.retrieve_async(sid))
                await self.validate_subscription(current,op,payload)
                price=as_dict(await client.v1.prices.retrieve_async(payload['target_price_id']))
                validate_price(price,op['target_plan'],op['billing_cycle'],self.settings.stripe_livemode)
                await client.v1.subscriptions.update_async(sid,{'items':[{'id':current['items']['data'][0]['id'],'price':price['id']}],
                    'proration_behavior':'none'},options={'idempotency_key':'ei-apply:'+str(op['id'])})
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await read_subscription(c,op['tenant_id'],lock=True)
                    locked=await c.fetchrow('SELECT * FROM public.subscription_operations WHERE id=$1 FOR UPDATE',op['id'])
                    if locked['state']=='APPLIED':return
                    await self.record_invoice(c,locked,invoice)
                    await self.apply(c,locked)
        except (stripe.StripeError,HTTPException,ValueError,KeyError,TypeError):
            async with self.pool.acquire() as c:await c.execute("UPDATE public.subscription_operations SET state='REVIEW',error_code='PROVIDER_RECONCILIATION_REQUIRED',updated_at=now() WHERE id=$1 AND state NOT IN ('APPLIED','SCHEDULED')",operation_id)

    async def validate_subscription(self,current,op,payload):
        plan,cycle,start,end=provider_plan(current,self.settings)
        if current.get('status') not in {'active','trialing'} or cycle!=op['billing_cycle'] or reference(current.get('customer')) is None:
            raise HTTPException(409,'The provider subscription requires reconciliation')
        if end!=datetime.fromisoformat(payload['paid_period_end']) or start!=datetime.fromisoformat(payload['paid_period_start']):raise HTTPException(409,'The paid period changed; request a fresh commercial preview')
        if plan not in {op['source_plan'],op['target_plan']}:raise HTTPException(409,'The provider plan changed')

    async def record_invoice(self,c,op,invoice):
        amount=invoice.get('amount_paid');gross=invoice.get('total');net=invoice.get('total_excluding_tax')
        if type(amount) is not int or type(gross) is not int or amount<0 or gross<0:raise HTTPException(409,'Invoice money requires reconciliation')
        if type(net) is not int:net=None
        await c.execute('''INSERT INTO public.subscription_invoice_receipts(stripe_invoice_id,stripe_subscription_id,stripe_event_id,
         tenant_id,amount_paid_gbp,paid_at,invoice_net_gbp,invoice_tax_gbp,invoice_gross_gbp,operation_id)
         VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(stripe_invoice_id) DO NOTHING''',
         invoice['id'],decoded(op['payload'])['subscription_id'],'operation:'+str(op['id']),op['tenant_id'],Decimal(amount)/100,
         datetime.fromtimestamp((invoice.get('status_transitions') or {}).get('paid_at') or int(utcnow().timestamp()),timezone.utc),
         Decimal(net)/100 if net is not None else None,Decimal(gross-net)/100 if net is not None else None,Decimal(gross)/100,op['id'])
        await self.event(c,op,'PAID',breakdown={'invoice_id':invoice['id'],'paid_gbp':str(Decimal(amount)/100)})

    async def process_due(self):
        """Short batches; financial uncertainty never becomes an automatic retry charge."""
        self.ready();now=utcnow()
        await self.sync_receipts()
        async with self.pool.acquire() as c:
            active=await c.fetch("SELECT id FROM public.subscription_operations WHERE state IN ('AUTHORIZED','PROVIDER_PENDING','PAID') AND (action IN ('UPGRADE','DOWNGRADE','CANCEL') OR effective_at<=now()) AND (lease_until IS NULL OR lease_until<=now()) ORDER BY effective_at LIMIT 20")
        for op in active:
            try:await self.execute(op['id'])
            except HTTPException:
                async with self.pool.acquire() as c:await c.execute("UPDATE public.subscription_operations SET state='FAILED',error_code='WALLET_PAYMENT_FAILED' WHERE id=$1 AND state='AUTHORIZED' AND funding='WALLET'",op['id'])
                logger.warning('subscription_operation_deferred')
            except asyncpg.PostgresError:logger.warning('subscription_operation_deferred')
        async with self.pool.acquire() as c:
            due=await c.fetch("SELECT tenant_id FROM public.tenants WHERE pending_plan_effective_at<=now() OR cancellation_effective_at<=now() OR (plan_status='PENDING_CANCELLATION' AND NOT final_notice_billed AND (plan_period_end<=now() OR billing_cycle='ANNUAL')) ORDER BY tenant_id LIMIT 20")
        for row in due:
            try:await self.settle_due(row['tenant_id'],now)
            except (HTTPException,asyncpg.PostgresError,stripe.StripeError):logger.warning('subscription_schedule_deferred')

    async def settle_due(self,tenant_id,now):
        async with self.pool.acquire() as c:
            async with c.transaction():
                sub=await read_subscription(c,tenant_id,lock=True)
                t=await c.fetchrow('SELECT * FROM public.tenants WHERE tenant_id=$1',tenant_id)
                original=await c.fetchrow("SELECT * FROM public.subscription_operations WHERE tenant_id=$1 AND state='SCHEDULED' AND action IN ('DOWNGRADE','CANCEL') ORDER BY created_at DESC LIMIT 1",tenant_id)
                if not original:return
                payload=decoded(original['payload'])
                # Queue the authorized final amount even after a worker outage. Unpaid
                # money never delays the customer's requested service end date.
                if original['action']=='CANCEL' and not t['final_notice_billed'] and (sub.plan_period_end<=now or sub.billing_cycle=='ANNUAL'):
                    await self.queue_charge(c,original,sub,'NOTICE_CHARGE',money(t['final_notice_prorated_amount']),now)
                if t['cancellation_effective_at'] and t['cancellation_effective_at']<=now:
                    await self.prepare_annual_refund(c,original)
                    await c.execute("UPDATE public.tenants SET subscription_plan='STARTER',plan_status='ACTIVE',plan_period_end=NULL,plan_version=plan_version+1,cancellation_requested_at=NULL,cancellation_effective_at=NULL WHERE tenant_id=$1",tenant_id)
                    await seed_margin(c,tenant_id,'STARTER')
                    await c.execute("UPDATE public.subscription_operations SET state='APPLIED' WHERE id=$1",original['id']);await self.event(c,original,'CANCELLATION_EFFECTIVE',amount=0)
                    return
                if original['action']=='DOWNGRADE' and t['pending_plan_effective_at'] and t['pending_plan_effective_at']<=now:
                    if original['funding']=='STRIPE' and original['target_plan']!='STARTER':return # verified renewal webhook applies the provider's paid tier
                    if payload['source_status']=='TRIALING' or payload['complimentary']:
                        # A trial selection is not a mandate to take a full renewal fee.
                        original={**dict(original),'target_plan':'STARTER'}
                    net=Decimal(0) if original['target_plan']=='STARTER' else money(payload['next_period_price'])
                    await self.queue_charge(c,original,sub,'DOWNGRADE_RENEWAL',net,t['pending_plan_effective_at'])

    async def queue_charge(self,c,original,sub,action,net,effective):
        now=utcnow();payload=decoded(original['payload']);tax=Decimal(0)
        if action=='NOTICE_CHARGE' and net==0:
            await c.execute('UPDATE public.tenants SET final_notice_billed=true WHERE tenant_id=$1',original['tenant_id']);return
        if original['funding']=='WALLET':
            rate=Decimal(payload.get('wallet_tax_percent','0'))
            tax=money(net*rate/Decimal(100))
        payload={**payload,'net_amount':str(net),'wallet_tax_amount':str(tax)}
        funding=original['funding'] if net>0 else 'NONE'
        request_id=UUID(hashlib.md5((str(original['id'])+action).encode(),usedforsecurity=False).hexdigest())
        await c.fetchrow('''INSERT INTO public.subscription_operations(id,tenant_id,actor_auth_user_id,request_id,action,state,
                 source_plan,target_plan,billing_cycle,plan_version,amount,funding,effective_at,preview_at,expires_at,payload,payload_sha256)
                 VALUES($1,$2,$3,$4,$5,'AUTHORIZED',$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16)
                 ON CONFLICT(tenant_id,request_id) DO NOTHING RETURNING id''',uuid4(),original['tenant_id'],original['actor_auth_user_id'],request_id,action,
                 original['source_plan'],original['target_plan'],original['billing_cycle'],sub.plan_version,net+tax,funding,effective,now,
                 now+timedelta(days=1),json.dumps(payload),hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest())

    async def sync_receipts(self):
        """Backfill verified original invoice totals/payment references without inventing tax."""
        if not self.settings.stripe_enabled or self.finance.stripe is None:return
        async with self.pool.acquire() as c:
            rows=await c.fetch('''SELECT i.*,t.stripe_customer_id FROM public.subscription_invoice_receipts i
             JOIN public.tenants t USING(tenant_id) WHERE i.invoice_payment_intent_id IS NULL
             AND t.is_sandbox=$1 ORDER BY i.reconciliation_attempted_at NULLS FIRST,i.created_at LIMIT 5''',not self.settings.stripe_livemode)
        for row in rows:
            try:
                async with self.pool.acquire() as c:await c.execute('UPDATE public.subscription_invoice_receipts SET reconciliation_attempted_at=now() WHERE stripe_invoice_id=$1',row['stripe_invoice_id'])
                invoice=as_dict(await self.finance.stripe.v1.invoices.retrieve_async(row['stripe_invoice_id']))
                if reference(invoice.get('customer'))!=row['stripe_customer_id'] or invoice.get('livemode') is not self.settings.stripe_livemode or invoice.get('status')!='paid' or invoice.get('currency')!='gbp':continue
                net=invoice.get('total_excluding_tax');gross=invoice.get('total')
                if (type(net) is not int or type(gross) is not int or not 0<=net<=gross
                    or invoice.get('amount_paid')!=gross or Decimal(gross)/100!=money(row['amount_paid_gbp'])):continue
                pi=reference(invoice.get('payment_intent'))
                if not pi:
                    payments=as_dict(await self.finance.stripe.v1.invoice_payments.list_async({'invoice':invoice['id'],'limit':10}))
                    paid=[r for r in payments.get('data',[]) if r.get('status')=='paid' and (r.get('payment') or {}).get('type')=='payment_intent']
                    if len(paid)!=1:continue # Split/tender or credit-funded invoices require explicit reconciliation.
                    pi=reference(paid[0]['payment']['payment_intent'])
                payment=as_dict(await self.finance.stripe.v1.payment_intents.retrieve_async(pi,{'expand':['latest_charge']}))
                charge=payment.get('latest_charge')
                if not isinstance(charge,dict) or reference(payment.get('customer'))!=row['stripe_customer_id'] or payment.get('currency')!='gbp' or payment.get('livemode') is not self.settings.stripe_livemode:continue
                refunded=charge.get('amount_refunded')
                if type(refunded) is not int or not 0<=refunded<=gross or charge.get('amount')!=gross:continue
                async with self.pool.acquire() as c:await c.execute('''UPDATE public.subscription_invoice_receipts SET invoice_net_gbp=$2,
                 invoice_tax_gbp=$3,invoice_gross_gbp=$4,invoice_payment_intent_id=$5,invoice_refunded_gbp=$6
                 WHERE stripe_invoice_id=$1 AND tenant_id=$7''',row['stripe_invoice_id'],Decimal(net)/100,Decimal(gross-net)/100,Decimal(gross)/100,pi,Decimal(refunded)/100,row['tenant_id'])
            except (stripe.StripeError,KeyError,ValueError,TypeError):logger.warning('subscription_invoice_reconciliation_deferred')

    async def prepare_annual_refund(self,c,cancellation):
        payload=decoded(cancellation['payload']);annual=payload['breakdown'].get('annual_clawback')
        if not annual or money(annual['net_refund'])<=0:return
        remaining=money(annual['net_refund']);allocations=[]
        for source in payload['breakdown']['refund_sources']:
            net=min(remaining,money(source['net_available']))
            if net<=0:continue
            gross=min(money(source['gross_available']),money(net*Decimal(source['gross_original'])/Decimal(source['net_original'])))
            allocations.append((source,net,gross));remaining-=net
        if remaining:raise HTTPException(409,'Refund allocation requires reconciliation')
        request_id=UUID(hashlib.md5((str(cancellation['id'])+'ANNUAL_REFUND').encode(),usedforsecurity=False).hexdigest())
        identifier=uuid4();amount=sum((gross for _,_,gross in allocations),Decimal(0))
        op=await c.fetchrow('''INSERT INTO public.subscription_operations(id,tenant_id,actor_auth_user_id,request_id,action,state,
         source_plan,target_plan,billing_cycle,plan_version,amount,funding,effective_at,preview_at,expires_at,payload,payload_sha256)
         VALUES($1,$2,$3,$4,'ANNUAL_REFUND','AUTHORIZED',$5,'STARTER','ANNUAL',$6,$7,'STRIPE',$8,$9,$10,$11::jsonb,$12)
         ON CONFLICT(tenant_id,request_id) DO NOTHING RETURNING *''',identifier,cancellation['tenant_id'],cancellation['actor_auth_user_id'],request_id,
         cancellation['source_plan'],cancellation['plan_version'],amount,cancellation['effective_at'],cancellation['preview_at'],
         cancellation['effective_at']+timedelta(days=30),json.dumps(payload),cancellation['payload_sha256'])
        if not op:return
        for source,net,gross in allocations:
            await c.execute('''INSERT INTO public.subscription_refunds(id,tenant_id,operation_id,stripe_invoice_id,payment_intent_id,
             net_amount,tax_amount,gross_amount,state) VALUES($1,$2,$3,$4,$5,$6,$7,$8,'READY')''',uuid4(),op['tenant_id'],op['id'],source['invoice_id'],source['payment_intent_id'],net,gross-net,gross)
        await self.event(c,op,'REFUND_QUEUED',amount=-amount)

    async def process_refund(self,op,client,customer):
        async with self.pool.acquire() as c:rows=await c.fetch('SELECT * FROM public.subscription_refunds WHERE operation_id=$1 AND tenant_id=$2 ORDER BY id',op['id'],op['tenant_id'])
        sources={r['invoice_id']:r for r in decoded(op['payload'])['breakdown']['refund_sources']}
        pending=False
        for row in rows:
            if row['state']=='SUCCEEDED':continue
            if row['provider_refund_id']:
                result=as_dict(await client.v1.refunds.retrieve_async(row['provider_refund_id']))
            elif row['state']=='READY':
                payment=as_dict(await client.v1.payment_intents.retrieve_async(row['payment_intent_id'],{'expand':['latest_charge']}))
                charge=payment.get('latest_charge')
                expected=money(sources[row['stripe_invoice_id']]['gross_refunded_at_preview'])
                if (not isinstance(charge,dict) or reference(payment.get('customer'))!=customer or payment.get('livemode') is not self.settings.stripe_livemode
                    or payment.get('currency')!='gbp' or Decimal(charge.get('amount_refunded',-1))/100!=expected
                    or Decimal(charge.get('amount',0)-charge.get('amount_refunded',0))/100<money(row['gross_amount'])):
                    raise HTTPException(409,'Refund source changed; finance review is required before returning funds')
                async with self.pool.acquire() as c:await c.execute("UPDATE public.subscription_refunds SET state='SUBMITTED' WHERE id=$1",row['id'])
                result=as_dict(await client.v1.refunds.create_async({'payment_intent':row['payment_intent_id'],'amount':int(money(row['gross_amount'])*100),
                    'metadata':{'easyinvio_refund_id':str(row['id'])}},options={'idempotency_key':'ei-refund:'+str(row['id'])}))
                async with self.pool.acquire() as c:await c.execute('UPDATE public.subscription_refunds SET provider_refund_id=$2 WHERE id=$1',row['id'],result['id'])
            else:raise HTTPException(409,'Unknown refund outcome requires reconciliation before any retry')
            if reference(result.get('payment_intent'))!=row['payment_intent_id'] or result.get('amount')!=int(money(row['gross_amount'])*100) or result.get('currency')!='gbp' or result.get('livemode') is not self.settings.stripe_livemode:
                raise HTTPException(409,'Refund identity mismatch')
            if result.get('status') in {'failed','canceled'}:raise HTTPException(409,'Refund failed; finance review required')
            if result.get('status')!='succeeded':pending=True;continue
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await read_subscription(c,op['tenant_id'],lock=True)
                    updated=await c.fetchrow("UPDATE public.subscription_refunds SET state='SUCCEEDED',settled_at=now() WHERE id=$1 AND state<>'SUCCEEDED' RETURNING id",row['id'])
                    if updated:await c.execute('UPDATE public.subscription_invoice_receipts SET invoice_refunded_gbp=invoice_refunded_gbp+$2 WHERE stripe_invoice_id=$1',row['stripe_invoice_id'],money(row['gross_amount']))
        async with self.pool.acquire() as c:
            async with c.transaction():
                await read_subscription(c,op['tenant_id'],lock=True)
                if pending:await c.execute("UPDATE public.subscription_operations SET lease_until=now()+interval '30 seconds' WHERE id=$1",op['id'])
                else:
                    await c.execute("UPDATE public.subscription_operations SET state='APPLIED',lease_until=NULL WHERE id=$1",op['id'])
                    await self.event(c,op,'REFUND_SETTLED',amount=-money(op['amount']))

    async def worker(self):
        while True:
            try:await self.process_due()
            except (asyncpg.PostgresError,HTTPException,TimeoutError) as error:
                logger.warning('subscription_lifecycle_storage_unavailable error_type=%s sqlstate=%s status=%s',
                    type(error).__name__,getattr(error,'sqlstate',None),getattr(error,'status_code',None))
            await asyncio.sleep(20)
