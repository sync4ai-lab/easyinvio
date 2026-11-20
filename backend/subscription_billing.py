"""Stripe recurring software billing, isolated from prepaid postage wallets.

Only main.stripe_webhook calls receive_verified_event after signature/mode checks.
Provider GET observations, not query strings or redirects, determine access.
"""
from __future__ import annotations
import json
from datetime import datetime,timezone
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
import stripe
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict
from backend.entitlements import Plan,capabilities,enabled,read_subscription,seed_margin

class SubscriptionCheckout(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    plan:Literal['VELOCITY','COMMAND']
    cycle:Literal['MONTHLY','ANNUAL']='MONTHLY'

def as_dict(value):
    return value.to_dict_recursive() if hasattr(value,'to_dict_recursive') else dict(value)

def reference(value):
    return value.get('id') if isinstance(value,dict) else value

def subscription_reference(invoice):
    return reference(invoice.get('subscription')) or reference((invoice.get('parent') or {}).get('subscription_details',{}).get('subscription'))

def validate_price(price,plan,cycle,livemode,*,require_active=True):
    policy=capabilities(plan);recurring=price.get('recurring') or {}
    expected=int((policy.monthly_fee_gbp if cycle=='MONTHLY' else policy.annual_monthly_fee_gbp*12)*100)
    if (price.get('livemode') is not livemode or price.get('currency')!='gbp' or (require_active and not price.get('active'))
        or price.get('unit_amount')!=expected or recurring.get('interval')!=('month' if cycle=='MONTHLY' else 'year')
        or recurring.get('interval_count',1)!=1 or price.get('billing_scheme')!='per_unit'):
        raise HTTPException(503,'The configured Stripe Price does not match the published plan and billing cycle')

def provider_plan(subscription,settings):
    items=(subscription.get('items') or {}).get('data') or []
    if len(items)!=1 or items[0].get('quantity')!=1:raise HTTPException(409,'Subscription item configuration requires review')
    price=items[0].get('price') or {};price_id=reference(price)
    matches=[key for key,value in settings.subscription_price_ids.items() if value==price_id]
    if len(matches)!=1:raise HTTPException(409,'Subscription Price is not an approved EasyInvio plan')
    plan,cycle=matches[0].split(':');Plan(plan)
    if plan=='STARTER' or cycle not in {'MONTHLY','ANNUAL'}:raise HTTPException(409,'Invalid paid plan mapping')
    validate_price(price,plan,cycle,settings.stripe_livemode,require_active=False)
    start=items[0].get('current_period_start') or subscription.get('current_period_start')
    end=items[0].get('current_period_end') or subscription.get('current_period_end')
    if type(start) is not int or type(end) is not int or start>=end:raise HTTPException(409,'Subscription period requires review')
    return plan,cycle,datetime.fromtimestamp(start,timezone.utc),datetime.fromtimestamp(end,timezone.utc)

def return_origin(settings):
    url=urlsplit(settings.booking_page_url)
    if url.username or url.password or url.scheme!='https' or not url.netloc:raise HTTPException(503,'Configure the HTTPS workspace URL before enabling subscription checkout')
    return url.scheme+'://'+url.netloc

async def checkout(request,context,body:SubscriptionCheckout):
    if context.role!='OWNER' or getattr(context,'assistance_session_id',None):raise HTTPException(403,'The customer workspace Owner must authorize a subscription')
    settings=request.app.state.settings;finance=request.app.state.finance
    if not enabled(settings) or not settings.stripe_enabled or finance.stripe is None:raise HTTPException(503,'Subscription checkout is not enabled')
    price_id=settings.subscription_price_ids.get(body.plan+':'+body.cycle)
    if not price_id or not price_id.startswith('price_'):raise HTTPException(503,'Configure a Stripe recurring Price for this plan and billing cycle')
    base=return_origin(settings)
    # Validate server-configured prices before a durable checkout can be submitted.
    try:price=as_dict(await finance.stripe.v1.prices.retrieve_async(price_id))
    except stripe.StripeError:raise HTTPException(503,'Stripe Price validation is temporarily unavailable') from None
    validate_price(price,body.plan,body.cycle,settings.stripe_livemode)
    async with finance.pool.acquire() as c:
        async with c.transaction():
            subscription=await read_subscription(c,context.tenant_id,lock=True)
            if subscription.is_sandbox==settings.stripe_livemode:raise HTTPException(403,'Workspace and payment environment do not match')
            row=await c.fetchrow('SELECT * FROM public.subscription_checkout_receipts WHERE id=$1',body.request_id)
            if row:
                if (row['tenant_id'],row['auth_user_id'],row['plan'],row['cycle'],row['price_id'])!=(context.tenant_id,context.user_id,body.plan,body.cycle,price_id):
                    raise HTTPException(409,'Checkout reference already used with different details')
                if row['state']=='READY':return {'checkout_url':row['checkout_url'],'request_id':str(body.request_id)}
                raise HTTPException(409,'Checkout is complete or requires reconciliation; do not submit a second charge')
            if subscription.stripe_subscription_id:
                # A completed cancellation/Starter downgrade may restart only after
                # verifying that the previous provider agreement cannot renew.
                lifecycle=bool(getattr(settings,'billing_lifecycle_enabled',False))
                finished=lifecycle and subscription.subscription_plan==Plan.STARTER and not subscription.cancellation_effective_at and not subscription.pending_plan
                evidence=await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.subscription_operations WHERE tenant_id=$1 AND action IN ('CANCEL','DOWNGRADE') AND target_plan='STARTER' AND state='APPLIED' AND payload->>'subscription_id'=$2)",context.tenant_id,subscription.stripe_subscription_id) if finished else False
                if not evidence:raise HTTPException(409,'Manage the existing subscription through Billing; a second subscription cannot be created here')
                try:previous=as_dict(await finance.stripe.v1.subscriptions.retrieve_async(subscription.stripe_subscription_id))
                except stripe.StripeError:raise HTTPException(503,'Previous subscription reconciliation is temporarily unavailable') from None
                expected_customer=await c.fetchval('SELECT stripe_customer_id FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
                if previous.get('status')!='canceled' or previous.get('livemode') is not settings.stripe_livemode or reference(previous.get('customer'))!=expected_customer:
                    raise HTTPException(409,'The previous subscription requires reconciliation before starting another')
                await c.execute('UPDATE public.tenants SET stripe_subscription_id=NULL WHERE tenant_id=$1',context.tenant_id)
            if await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.subscription_checkout_receipts WHERE tenant_id=$1 AND state IN ('CREATING','READY','REVIEW'))",context.tenant_id):
                raise HTTPException(409,'A subscription checkout is already pending; resolve it before starting another')
            tenant=await c.fetchrow('SELECT stripe_customer_id,billing_email FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
            await c.execute("INSERT INTO public.subscription_checkout_receipts(id,tenant_id,auth_user_id,plan,cycle,price_id,state) VALUES($1,$2,$3,$4,$5,$6,'CREATING')",body.request_id,context.tenant_id,context.user_id,body.plan,body.cycle,price_id)
    params={'mode':'subscription','line_items':[{'price':price_id,'quantity':1}],
        'client_reference_id':str(body.request_id),'metadata':{'purpose':'software_subscription'},
        'success_url':base+'/workspace?subscription=processing','cancel_url':base+'/workspace?subscription=cancelled'}
    if tenant['stripe_customer_id']:params['customer']=tenant['stripe_customer_id']
    else:params['customer_email']=tenant['billing_email']
    try:
        session=as_dict(await finance.stripe.v1.checkout.sessions.create_async(params,options={'idempotency_key':'software-subscription:'+str(body.request_id)}))
        url=urlsplit(session.get('url') or '')
        if not session.get('id') or url.scheme!='https' or url.hostname!='checkout.stripe.com' or url.username or url.password:raise ValueError()
    except (stripe.StripeError,ValueError,TypeError):
        async with finance.pool.acquire() as c:await c.execute("UPDATE public.subscription_checkout_receipts SET state='REVIEW',updated_at=now() WHERE id=$1 AND state='CREATING'",body.request_id)
        raise HTTPException(503,'Subscription checkout outcome requires review before retrying') from None
    async with finance.pool.acquire() as c:
        await c.execute("UPDATE public.subscription_checkout_receipts SET state='READY',stripe_session_id=$2,checkout_url=$3,updated_at=now() WHERE id=$1 AND state='CREATING'",body.request_id,session['id'],session['url'])
    return {'checkout_url':session['url'],'request_id':str(body.request_id)}

async def receive_verified_event(request,event):
    """Returns True for subscription events, False for unrelated wallet events."""
    settings=request.app.state.settings
    if not enabled(settings):return False
    kind=event.get('type');obj=as_dict(event['data']['object'])
    is_checkout=kind in {'checkout.session.completed','checkout.session.async_payment_succeeded','checkout.session.expired'} and obj.get('mode')=='subscription'
    is_subscription=kind in {'customer.subscription.updated','customer.subscription.deleted'}
    is_invoice=kind in {'invoice.paid','invoice.payment_failed'} and subscription_reference(obj)
    if not(is_checkout or is_subscription or is_invoice):return False
    event_id=event.get('id');created=event.get('created')
    if not isinstance(event_id,str) or not event_id.startswith('evt_') or type(created) is not int:raise HTTPException(400,'Invalid subscription event')
    finance=request.app.state.finance;subscription_id=reference(obj.get('subscription')) if is_checkout else obj.get('id') if is_subscription else subscription_reference(obj)
    receipt=None
    if is_checkout:
        try:receipt_id=UUID(obj.get('client_reference_id',''))
        except ValueError:raise HTTPException(409,'Subscription checkout reference requires review') from None
        async with finance.pool.acquire() as c:receipt=await c.fetchrow('SELECT * FROM public.subscription_checkout_receipts WHERE id=$1',receipt_id)
        if not receipt:return True # An unrelated application in the same Stripe account.
        if receipt['stripe_session_id'] and receipt['stripe_session_id']!=obj.get('id'):raise HTTPException(409,'Subscription session mismatch')
        if kind=='checkout.session.expired':
            async with finance.pool.acquire() as c:await c.execute("UPDATE public.subscription_checkout_receipts SET state='EXPIRED',updated_at=now() WHERE id=$1 AND state='READY'",receipt_id)
            return True
        if obj.get('payment_status')!='paid':return True
    async with finance.pool.acquire() as c:
        async with c.transaction():
            # Serialize even before the first session links its subscription to a tenant.
            await c.execute("SET LOCAL lock_timeout='5s'")
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,50))',subscription_id)
            if await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.subscription_webhook_events WHERE stripe_event_id=$1)',event_id):return True
            # Observe AFTER the lock: an earlier, slower GET cannot overwrite a newer observation.
            try:current=as_dict(await finance.stripe.v1.subscriptions.retrieve_async(subscription_id))
            except stripe.StripeError:raise HTTPException(503,'Subscription observation is temporarily unavailable') from None
            if current.get('livemode') is not settings.stripe_livemode:raise HTTPException(409,'Subscription environment mismatch')
            plan,cycle,started,ends=provider_plan(current,settings)
            customer=reference(current.get('customer'))
            status={'active':'ACTIVE','trialing':'TRIALING','past_due':'PAST_DUE','unpaid':'PAST_DUE','incomplete':'PAST_DUE',
                'incomplete_expired':'CANCELLED','canceled':'CANCELLED','paused':'PAST_DUE'}.get(current.get('status'))
            if status is None:raise HTTPException(409,'Subscription status requires review')
            if receipt:
                tenant_id=receipt['tenant_id']
                if (receipt['plan'],receipt['cycle'])!=(plan,cycle):raise HTTPException(409,'Purchased plan differs from the stored checkout')
            else:
                tenant_id=await c.fetchval('SELECT tenant_id FROM public.tenants WHERE stripe_subscription_id=$1',subscription_id)
            if is_invoice and kind=='invoice.paid':
                amount=obj.get('amount_paid')
                paid_at=(obj.get('status_transitions') or {}).get('paid_at')
                if type(amount) is not int or amount<0 or obj.get('currency')!='gbp' or type(paid_at) is not int:raise HTTPException(409,'Invoice receipt requires review')
                await c.execute("""INSERT INTO public.subscription_invoice_receipts(stripe_invoice_id,stripe_subscription_id,stripe_event_id,tenant_id,amount_paid_gbp,paid_at)
                    VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(stripe_invoice_id) DO NOTHING""",obj['id'],subscription_id,event_id,tenant_id,Decimal(amount)/100,datetime.fromtimestamp(paid_at,timezone.utc))
            if tenant_id:
                sub=await read_subscription(c,tenant_id,lock=True)
                tenant=await c.fetchrow('SELECT stripe_customer_id,is_sandbox FROM public.tenants WHERE tenant_id=$1',tenant_id)
                if tenant['stripe_customer_id'] and tenant['stripe_customer_id']!=customer:raise HTTPException(409,'Subscription customer mismatch')
                if tenant['is_sandbox']==settings.stripe_livemode:raise HTTPException(409,'Subscription workspace environment mismatch')
                if sub.stripe_subscription_id and sub.stripe_subscription_id!=subscription_id:raise HTTPException(409,'A different subscription is already linked')
                lifecycle=bool(getattr(settings,'billing_lifecycle_enabled',False));now=datetime.now(timezone.utc)
                if lifecycle:
                    intent=await c.fetchrow("SELECT action,effective_at FROM public.subscription_operations WHERE tenant_id=$1 AND action IN ('DOWNGRADE','CANCEL') AND state IN ('AUTHORIZED','PROVIDER_PENDING','REVIEW') ORDER BY created_at DESC LIMIT 1",tenant_id)
                    if intent:
                        # Provider webhooks can arrive before the worker saves its result.
                        # Never erase already-paid access during that interval.
                        plan,cycle,started,ends=sub.subscription_plan.value,sub.billing_cycle,sub.plan_period_start,sub.plan_period_end
                        if intent['action']=='CANCEL':ends=min(ends,intent['effective_at'])
                        status=sub.plan_status
                # A lower recurring Stripe price is set now without proration, but
                # the already-paid higher tier remains available until renewal.
                if lifecycle and sub.pending_plan and sub.pending_plan_effective_at and now<sub.pending_plan_effective_at:
                    plan,cycle,started,ends=sub.subscription_plan.value,sub.billing_cycle,sub.plan_period_start,sub.plan_period_end
                if lifecycle and sub.cancellation_effective_at:
                    plan,cycle,started,ends=sub.subscription_plan.value,sub.billing_cycle,sub.plan_period_start,sub.plan_period_end
                    status='PAST_DUE' if sub.plan_status=='PAST_DUE' else 'PENDING_CANCELLATION'
                await c.execute("""UPDATE public.tenants SET stripe_subscription_id=$2,stripe_customer_id=coalesce(stripe_customer_id,$3),
                    subscription_plan=$4::text,billing_cycle=$5::text,plan_status=$6::text,plan_period_end=$7,plan_period_start=$8,
                    plan_enforcement_enabled=true,subscription_complimentary=false,
                    plan_version=plan_version+CASE WHEN subscription_plan<>$4 OR billing_cycle<>$5 OR plan_status<>$6 THEN 1 ELSE 0 END
                    WHERE tenant_id=$1""",tenant_id,subscription_id,customer,plan,cycle,status,ends,started)
                await seed_margin(c,tenant_id,plan)
                if lifecycle and sub.pending_plan and sub.pending_plan_effective_at and now>=sub.pending_plan_effective_at and plan==sub.pending_plan.value and status=='ACTIVE':
                    await c.execute('UPDATE public.tenants SET pending_plan=NULL,pending_billing_cycle=NULL,pending_plan_effective_at=NULL WHERE tenant_id=$1',tenant_id)
                    await c.execute("UPDATE public.subscription_operations SET state='APPLIED',updated_at=now() WHERE tenant_id=$1 AND action='DOWNGRADE' AND state='SCHEDULED'",tenant_id)
                if lifecycle and is_invoice and kind=='invoice.paid':
                    total=obj.get('total');net=obj.get('total_excluding_tax')
                    if type(total) is int and type(net) is int and 0<=net<=total:
                        await c.execute('''UPDATE public.subscription_invoice_receipts SET invoice_net_gbp=$2,invoice_tax_gbp=$3,invoice_gross_gbp=$4
                         WHERE stripe_invoice_id=$1 AND tenant_id=$5''',obj['id'],Decimal(net)/100,Decimal(total-net)/100,Decimal(total)/100,tenant_id)
                await c.execute('UPDATE public.subscription_invoice_receipts SET tenant_id=$2 WHERE stripe_subscription_id=$1 AND tenant_id IS NULL',subscription_id,tenant_id)
                if receipt:await c.execute("UPDATE public.subscription_checkout_receipts SET state='COMPLETE',stripe_session_id=$2,updated_at=now() WHERE id=$1",receipt['id'],obj['id'])
            await c.execute('INSERT INTO public.subscription_webhook_events(stripe_event_id,event_type,subscription_id,event_created_at) VALUES($1,$2,$3,$4)',event_id,kind,subscription_id,datetime.fromtimestamp(created,timezone.utc))
    return True
