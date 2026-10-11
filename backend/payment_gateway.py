"""Test-mode Checkout gateway over the shared, atomic wallet ledger service."""
import asyncio
import hashlib
import json
import logging
import traceback
from pathlib import Path
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.ai_engine import strict_decimal

FINANCE_ROLES = {'OWNER', 'ADMIN', 'ACCOUNTANT'}
logger = logging.getLogger('easyinvio.payment_snapshots')
SNAPSHOT_EVENTS = {'checkout.session.completed','charge.refunded','charge.failed'}


class ReconciliationError(Exception):
    """A sanitized diagnosis safe for an operational queue and logs."""


def resource_id(value, prefix):
    value = value.get('id') if isinstance(value,dict) else value
    if not isinstance(value,str) or not value.startswith(prefix) or len(value)>200:
        raise ReconciliationError('invalid_resource_reference')
    return value


def minor_amount(value):
    if type(value) is not int or not 0 <= value < 10**17:
        raise ReconciliationError('invalid_minor_amount')
    return Decimal(value)/Decimal('100')


def safe_trace(error):
    # Never format exception messages, locals, Stripe bodies or SQL row data.
    return ';'.join(f'{Path(f.filename).name}:{f.lineno}:{f.name}' for f in traceback.extract_tb(error.__traceback__))


class SnapshotWebhookService:
    def __init__(self, finance):
        self.finance=finance;self.pool=finance.pool

    async def register(self, event):
        event_id=resource_id(event.get('id'),'evt_')
        data=event.get('data')
        if not isinstance(data,dict):raise ReconciliationError('snapshot_data_required')
        obj=data.get('object')
        if not isinstance(obj,dict):raise ReconciliationError('snapshot_object_required')
        expected='checkout.session' if event['type']=='checkout.session.completed' else 'charge'
        if obj.get('object')!=expected:raise ReconciliationError('snapshot_resource_type_mismatch')
        if obj.get('livemode') is not event['livemode']:raise ReconciliationError('snapshot_mode_mismatch')
        # Persist only reconciliation fields; omit card/payment details and PII.
        fields=['id','object','customer','payment_intent','metadata','currency','amount_total','amount',
                'amount_refunded','paid','status','payment_status','mode','livemode','client_reference_id']
        payload={k:obj[k] for k in fields if k in obj}
        metadata=payload.get('metadata') or {}
        if not isinstance(metadata,dict):raise ReconciliationError('invalid_metadata')
        payload['metadata']={k:metadata[k] for k in ['tenant_id','topup_id','purpose'] if k in metadata}
        if any(not isinstance(v,str) or len(v)>512 for v in payload['metadata'].values()):
            raise ReconciliationError('invalid_metadata_value')
        if event.get('api_version') is not None and (not isinstance(event['api_version'],str) or len(event['api_version'])>100):
            raise ReconciliationError('invalid_api_version')
        for field,prefix in [('customer','cus_'),('payment_intent','pi_')]:
            if payload.get(field) is not None:payload[field]=resource_id(payload[field],prefix)
        canonical=json.dumps({'type':event['type'],'livemode':event['livemode'],'object':payload},sort_keys=True,separators=(',',':'))
        digest=hashlib.sha256(canonical.encode()).hexdigest()
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'stripe-event:'+event_id)
                old=await c.fetchrow('SELECT payload_sha256 FROM public.stripe_webhook_events WHERE event_id=$1',event_id)
                if old and old['payload_sha256']!=digest:raise ReconciliationError('event_identity_collision')
                if not old:
                    await c.execute('''INSERT INTO public.stripe_webhook_events(event_id,event_type,api_version,livemode,payload,payload_sha256)
                        VALUES($1,$2,$3,$4,$5::jsonb,$6)''',event_id,event['type'],event.get('api_version'),event['livemode'],json.dumps(payload),digest)
        return event_id

    async def charge_topup(self,c,obj):
        metadata=obj.get('metadata') or {}
        if metadata.get('purpose') not in {None,'wallet_topup'}:return None
        intent=resource_id(obj.get('payment_intent'),'pi_');customer=resource_id(obj.get('customer'),'cus_')
        try:
            topup_id=UUID(metadata['topup_id']) if metadata.get('topup_id') else None
            claimed_tenant=UUID(metadata['tenant_id']) if metadata.get('tenant_id') else None
        except (ValueError,TypeError):raise ReconciliationError('invalid_tenant_metadata') from None
        candidates=await c.fetch('''SELECT tenant_id,id FROM public.wallet_topups
            WHERE stripe_customer_id=$1 AND (stripe_payment_intent_id=$2 OR id=$3::uuid) LIMIT 2''',customer,intent,topup_id)
        if len(candidates)!=1:raise ReconciliationError('charge_topup_mapping_pending')
        tenant_id=candidates[0]['tenant_id']
        if claimed_tenant is not None and claimed_tenant!=tenant_id:raise ReconciliationError('charge_tenant_mismatch')
        tenant=await self.finance.lock_tenant(c,tenant_id)
        self.finance.check_payment_environment(tenant)
        topup=await c.fetchrow('SELECT * FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2 FOR UPDATE',tenant_id,candidates[0]['id'])
        if (tenant['stripe_customer_id']!=customer or topup['stripe_customer_id']!=customer
            or topup.get('stripe_payment_intent_id') not in {None,intent} or topup['is_sandbox']):
            raise ReconciliationError('charge_topup_identity_mismatch')
        if str(obj.get('currency','')).upper()!=topup['currency'] or minor_amount(obj.get('amount'))!=topup['amount']:
            raise ReconciliationError('charge_amount_currency_mismatch')
        await c.execute('UPDATE public.wallet_topups SET stripe_payment_intent_id=$3 WHERE tenant_id=$1 AND id=$2',tenant_id,topup['id'],intent)
        return topup

    async def refund(self,c,event_id,obj):
        topup=await self.charge_topup(c,obj)
        if topup is None:return {'ignored':True}
        if topup['status']!='CREDITED':raise ReconciliationError('refund_waiting_for_original_credit')
        if obj.get('paid') is not True or obj.get('status')!='succeeded':raise ReconciliationError('refund_charge_not_paid')
        charge=resource_id(obj.get('id'),'ch_');total=obj.get('amount_refunded')
        minor_amount(total)
        if total>obj['amount']:raise ReconciliationError('refund_exceeds_original_charge')
        tenant=topup['tenant_id'];intent=resource_id(obj['payment_intent'],'pi_')
        await c.execute('''INSERT INTO public.stripe_charge_refunds(charge_id,tenant_id,topup_id,payment_intent_id)
            VALUES($1,$2,$3,$4) ON CONFLICT(charge_id) DO NOTHING''',charge,tenant,topup['id'],intent)
        checkpoint=await c.fetchrow('SELECT * FROM public.stripe_charge_refunds WHERE charge_id=$1 FOR UPDATE',charge)
        if (checkpoint['tenant_id'],checkpoint['topup_id'],checkpoint['payment_intent_id'])!=(tenant,topup['id'],intent):
            raise ReconciliationError('refund_checkpoint_identity_mismatch')
        delta=total-checkpoint['applied_refund_minor']
        if delta<=0:return {'refund_debited':'0.00','replayed':True}
        amount=minor_amount(delta);wallet=await self.finance.lock_wallet(c,tenant)
        if wallet['currency']!=topup['currency']:raise ReconciliationError('refund_wallet_currency_mismatch')
        if wallet['balance']-amount<wallet['reserved_balance']:
            await c.execute("UPDATE public.tenants SET workspace_status='SUSPENDED',billing_status='PAST_DUE' WHERE tenant_id=$1",tenant)
            return {'manual_action_required':True,'code':'refund_insufficient_unreserved_funds','refund_pending':format(amount,'.2f')}
        await c.execute('UPDATE public.wallets SET balance=balance-$2,updated_at=now() WHERE tenant_id=$1',tenant,amount)
        await self.finance.append_ledger(c,tenant_id=tenant,currency=topup['currency'],entry_type='REFUND_DEBIT',
            balance_delta=-amount,reserved_delta=Decimal('0'),balance_after=wallet['balance']-amount,
            reserved_after=wallet['reserved_balance'],topup_id=topup['id'],stripe_event_id=event_id)
        await c.execute('UPDATE public.stripe_charge_refunds SET applied_refund_minor=$2,updated_at=now() WHERE charge_id=$1',charge,total)
        return {'refund_debited':format(amount,'.2f')}

    async def failed(self,c,event_id,obj):
        if obj.get('status')!='failed' or obj.get('paid') is not False:raise ReconciliationError('failed_charge_state_mismatch')
        topup=await self.charge_topup(c,obj)
        if topup is None:return {'ignored':True}
        if topup['status']=='CREDITED':return {'ignored':True,'reason':'already_credited'}
        await c.execute("UPDATE public.wallet_topups SET status='FAILED',transaction_state='FAILED' WHERE tenant_id=$1 AND id=$2",topup['tenant_id'],topup['id'])
        logger.info('Stripe failed charge recorded event_id=%s',event_id)
        return {'failed':True}

    async def process(self,event_id):
        try:
            async with self.pool.acquire() as c:
                async with c.transaction():
                    row=await c.fetchrow('SELECT * FROM public.stripe_webhook_events WHERE event_id=$1 FOR UPDATE',event_id)
                    if not row:return {'deferred':True}
                    if row['status']!='PENDING':return {'replayed':True,'credited':False}
                    if row['livemode'] is not self.finance.settings.stripe_livemode:return {'deferred':True}
                    obj=json.loads(row['payload']) if isinstance(row['payload'],str) else row['payload']
                    if row['event_type']=='checkout.session.completed':
                        result={'credited':await self.finance.credit_session(event_id,obj,connection=c,snapshot_reconciliation=True)}
                    elif row['event_type']=='charge.refunded':
                        result=await self.refund(c,event_id,obj)
                    elif row['event_type']=='charge.failed':
                        result=await self.failed(c,event_id,obj)
                    else:raise ReconciliationError('unsupported_snapshot_event')
                    state='RECONCILIATION_REQUIRED' if result.get('manual_action_required') else 'DONE'
                    await c.execute('''UPDATE public.stripe_webhook_events SET status=$2,result=$3::jsonb,completed_at=now(),last_error=NULL WHERE event_id=$1''',event_id,state,json.dumps(result))
                    return result
        except Exception as error:
            code=str(error) if isinstance(error,ReconciliationError) else type(error).__name__
            logger.error('Stripe event deferred id=%s code=%s trace=%s',event_id,code,safe_trace(error))
            try:
                async with self.pool.acquire() as c:
                    await c.execute('''UPDATE public.stripe_webhook_events SET attempts=attempts+1,last_error=$2,
                        status=CASE WHEN attempts>=11 THEN 'RECONCILIATION_REQUIRED' ELSE 'PENDING' END,
                        next_attempt_at=now()+least(3600,power(2,least(attempts+1,12))) * interval '1 second'
                        WHERE event_id=$1 AND status='PENDING' ''',event_id,code)
            except Exception:
                logger.error('Stripe durable retry scheduling unavailable id=%s',event_id)
            return {'deferred':True,'credited':False}

    async def worker(self):
        while True:
            try:
                async with self.pool.acquire() as c:
                    rows=await c.fetch("SELECT event_id FROM public.stripe_webhook_events WHERE status='PENDING' AND livemode=$1 AND next_attempt_at<=now() ORDER BY next_attempt_at LIMIT 20",self.finance.settings.stripe_livemode)
                for row in rows:await self.process(row['event_id'])
            except Exception as error:
                logger.error('Stripe snapshot queue unavailable error_type=%s',type(error).__name__)
            await asyncio.sleep(5)


async def snapshot_webhook(request: Request):
    settings=request.app.state.settings
    if not settings.stripe_enabled:raise HTTPException(503,'Stripe integration is disabled')
    signatures=request.headers.getlist('stripe-signature')
    if len(signatures)!=1:raise HTTPException(400,'Exactly one Stripe signature is required')
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>1048576:raise HTTPException(413,'Webhook payload too large')
    try:
        stripe.Webhook.construct_event(bytes(raw),signatures[0],settings.stripe_webhook_secret.get_secret_value(),tolerance=300)
        event=json.loads(raw)
    except (ValueError,TypeError,AttributeError,stripe.SignatureVerificationError):
        raise HTTPException(400,'Invalid Stripe webhook signature or payload') from None
    if not isinstance(event,dict):raise HTTPException(400,'Invalid Stripe event envelope')
    if event.get('livemode') is not settings.stripe_livemode or event.get('account'):
        raise HTTPException(400,'Stripe account/environment mismatch')
    if event.get('type') not in SNAPSHOT_EVENTS:return {'received':True,'ignored':True,'credited':False}
    service=getattr(request.app.state,'payment_snapshots',None) or SnapshotWebhookService(request.app.state.finance)
    try:
        event_id=await service.register(event)
    except ReconciliationError:
        raise HTTPException(400,'Invalid Stripe snapshot identity') from None
    except Exception as error:
        logger.error('Stripe receipt persistence failed type=%s trace=%s',type(error).__name__,safe_trace(error))
        # No durable receipt means acknowledging would permanently lose money.
        raise HTTPException(503,'Stripe event could not be saved; retry required') from None
    result=await service.process(event_id)
    return {'received':True,**result}


class CheckoutInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    tenant_id: UUID
    topup_amount: Decimal = Field(ge=1, le=10000, decimal_places=2)
    request_id: UUID = Field(default_factory=uuid4)

    @field_validator('topup_amount', mode='before')
    @classmethod
    def fixed_amount(cls, value):
        return strict_decimal(value)


def checkout_redirect(base: str, outcome: str, topup_id: UUID) -> str:
    """Fixed server-owned destination; no redirect URL is accepted from clients."""
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(payment=outcome, topup_id=str(topup_id))
    return urlunsplit((parts.scheme, parts.netloc, parts.path or '/', urlencode(query), ''))


def safe_checkout_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == 'https' and parts.hostname == 'checkout.stripe.com' and not parts.username
                 and not parts.password and parts.port in {None, 443})
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(503, 'Unexpected Stripe Checkout destination')
    return value


def require_test_gateway(settings):
    if not settings.stripe_enabled:
        raise HTTPException(503, 'Stripe integration is disabled')
    if settings.stripe_livemode or not settings.stripe_secret_key.get_secret_value().startswith('sk_test_'):
        raise HTTPException(403, 'This gateway requires a Stripe test secret key')
    if settings.database_environment != 'SANDBOX':
        raise HTTPException(403, 'Test payments require a sandbox database')


async def ensure_customer(finance, context):
    """Create a tenant-scoped Stripe customer outside all financial transactions.

    A session lock and Stripe idempotency key recover an ambiguous remote create
    without duplicating customers. The customer never comes from browser input.
    """
    async with finance.pool.acquire() as c:
        key = f'stripe-customer:{context.tenant_id}'
        await c.execute('SELECT pg_advisory_lock(hashtextextended($1,0))', key)
        try:
            async with c.transaction():
                tenant = await finance.lock_tenant(c, context.tenant_id, context, FINANCE_ROLES)
                finance.check_payment_environment(tenant)
                if tenant['billing_plan'] != 'PREPAID_WALLET':
                    raise HTTPException(409, 'Workspace does not use a prepaid wallet')
                if tenant['stripe_customer_id']:
                    return
                profile = await c.fetchrow('SELECT company_name,billing_email FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
            try:
                customer = await finance.stripe.v1.customers.create_async({
                    'name': profile['company_name'], 'email': profile['billing_email'],
                    'metadata': {'tenant_id':str(context.tenant_id), 'purpose':'wallet_topup'}},
                    options={'idempotency_key':key})
            except stripe.StripeError:
                raise HTTPException(503, 'Stripe customer creation needs retry or reconciliation') from None
            if not customer.id or not str(customer.id).startswith('cus_') or customer.livemode is not False:
                raise HTTPException(503, 'Invalid Stripe customer response')
            async with c.transaction():
                tenant = await finance.lock_tenant(c,context.tenant_id,context,FINANCE_ROLES)
                finance.check_payment_environment(tenant)
                if tenant['stripe_customer_id'] not in {None, customer.id}:
                    raise HTTPException(409, 'Stripe customer mapping changed; reconciliation required')
                await c.execute('UPDATE public.tenants SET stripe_customer_id=$2 WHERE tenant_id=$1',context.tenant_id,customer.id)
        finally:
            await c.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))',key)


def build_router(authenticate, topup_model, webhook_handler):
    router = APIRouter(prefix='/api/v1/billing',tags=['Prepaid payments'])

    @router.post('/create-checkout')
    async def create_checkout(body: CheckoutInput, request: Request, context: Any = Depends(authenticate)):
        if context.tenant_id != body.tenant_id:
            raise HTTPException(403, 'Tenant mismatch')
        if context.role not in FINANCE_ROLES:
            raise HTTPException(403, 'Financial permission required')
        settings = request.app.state.settings
        require_test_gateway(settings)
        finance = getattr(request.app.state,'finance',None)
        if finance is None or finance.stripe is None:
            raise HTTPException(503, 'Configured payment backend required')
        try:
            await ensure_customer(finance,context)
            result = await finance.create_checkout(context,topup_model(request_id=body.request_id,amount=body.topup_amount),
                return_urls=(checkout_redirect(settings.checkout_success_url,'success',body.request_id),
                             checkout_redirect(settings.checkout_cancel_url,'cancel',body.request_id)))
        except asyncpg.PostgresError:
            raise HTTPException(503, 'Payment database temporarily unavailable') from None
        return {'url':safe_checkout_url(result.checkout_url),'topup_id':str(result.topup_id),
                'checkout_session_id':result.checkout_session_id,'mode':'TEST'}

    @router.get('/topups/{topup_id}')
    async def topup_status(topup_id: UUID, request: Request, context: Any = Depends(authenticate)):
        if context.role not in FINANCE_ROLES:
            raise HTTPException(403, 'Financial permission required')
        try:
            async with request.app.state.finance.pool.acquire() as c:
                row = await c.fetchrow('''SELECT id,status,amount,currency,credited_at FROM public.wallet_topups
                    WHERE tenant_id=$1 AND id=$2''',context.tenant_id,topup_id)
        except asyncpg.PostgresError:
            raise HTTPException(503, 'Payment status temporarily unavailable') from None
        if not row:
            raise HTTPException(404, 'Top-up not found')
        return {'topup_id':str(row['id']),'status':row['status'],'amount':format(row['amount'],'.2f'),
                'currency':row['currency'],'credited_at':row['credited_at'].isoformat() if row['credited_at'] else None}

    # This primary endpoint has the explicit durable snapshot scope. The caller
    # retains the legacy webhook_handler on its compatibility route.
    router.add_api_route('/webhooks/stripe',snapshot_webhook,methods=['POST'])
    return router
