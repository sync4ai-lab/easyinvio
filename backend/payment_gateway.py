"""Test-mode Checkout gateway over the shared, atomic wallet ledger service."""
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

    # Both paths use the same verified-byte handler and atomic reconciliation.
    router.add_api_route('/webhooks/stripe',webhook_handler,methods=['POST'])
    return router
