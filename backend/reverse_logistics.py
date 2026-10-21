"""Authenticated, durable full-parcel returns over the existing booking ledger.

Provider calls run outside database transactions. A committed command receipt
fences interrupted requests; a repeated request can observe, never repurchase.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.dispatch_workspace import decoded
from backend.carrier_consolidation import carrier_identity, public_payload
from backend.agents.margin_optimizer import BUDGET_CARRIERS


class ReturnCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    idempotency_key: UUID
    shipment_id: UUID | None = None
    order_reference: str | None = Field(default=None, min_length=1, max_length=200)
    charge_bearer: Literal['RETAILER_PAY', 'CUSTOMER_PAY'] = 'RETAILER_PAY'
    paperless_requested: bool = Field(default=True, strict=True)
    maximum_price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    customs_signer: str | None = Field(default=None, min_length=1, max_length=200)
    hs_codes_reviewed: bool = Field(default=False, strict=True)
    store_return_reference: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator('maximum_price',mode='before')
    @classmethod
    def exact_price_limit(cls, value):
        if value is not None and (isinstance(value,bool) or isinstance(value,float)):
            raise ValueError('Use an exact decimal string for maximum_price')
        return value

    @model_validator(mode='after')
    def reference(self):
        if (self.shipment_id is None) == (self.order_reference is None):
            raise ValueError('Supply exactly one shipment_id or order_reference')
        return self


def cheapest_return(rates):
    """Lowest exact customer price; prefer budget networks at an equal price."""
    eligible = []
    for rate in rates:
        amount = Decimal(str(rate['client_price_ex_tax']))
        if not amount.is_finite() or amount <= 0 or not rate.get('offer_id'):
            continue
        eligible.append(rate)
    if not eligible:
        raise HTTPException(409, 'No eligible return services are available for these details')
    if len({rate['currency'] for rate in eligible}) != 1:
        raise HTTPException(409, 'Return quotes must use a single currency')
    return min(eligible, key=lambda rate: (
        Decimal(str(rate['client_price_ex_tax'])),
        carrier_identity(rate['carrier_code']) not in BUDGET_CARRIERS,
        carrier_identity(rate['carrier_code']), str(rate['offer_id'])))


class ReverseLogisticsService:
    def __init__(self, lifecycle):
        self.lifecycle = lifecycle
        self.pool = lifecycle.pool

    async def status(self, context, request_id):
        from backend.automation_three_partners import authorize
        authorize(context, context.tenant_id)
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow('''SELECT * FROM public.reverse_logistics_requests
                WHERE tenant_id=$1 AND id=$2''', context.tenant_id, request_id)
            if row is None:
                raise HTTPException(404, 'Return request not found in this workspace')
            result = decoded(row['response']) or {}
            shipment = None
            if row['return_shipment_id']:
                shipment = await connection.fetchrow('''SELECT id,status,logistics_metadata,carrier_account_id,pricing_snapshot FROM public.shipments
                    WHERE tenant_id=$1 AND id=$2''', context.tenant_id, row['return_shipment_id'])
            if shipment and shipment['status'] in {'BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED'}:
                metadata = decoded(shipment['logistics_metadata']) or {}
                from backend.return_documents import recover_easypost_qr
                label = await recover_easypost_qr(connection,self.lifecycle,context,shipment,metadata)
                if label:
                    result.update(self.lifecycle.public_result(shipment['id'], label, metadata.get('automation_customs'), True))
                    result['shipment_status'] = shipment['status']
                    await connection.execute('''UPDATE public.reverse_logistics_requests SET state='BOOKED',
                        response=$3::jsonb,updated_at=now() WHERE tenant_id=$1 AND id=$2''',
                        context.tenant_id, request_id, json.dumps(result))
            result.setdefault('status', row['state'])
            result.update(request_id=str(request_id), charge_bearer=row['charge_bearer'], replayed=True)
        from backend.return_documents import public_return_links
        linked = public_payload(public_return_links(self.lifecycle.automation.settings, context, result))
        from backend.logistics_media import publish_return_media
        return await publish_return_media(self.lifecycle, context, linked)

    async def process(self, context, command: ReturnCommand, *, source='API', store_id=None):
        from backend.automation_three_partners import authorize, ReturnRequest, prepare_return_quote, BookingRequest
        authorize(context, context.tenant_id)
        if command.charge_bearer == 'CUSTOMER_PAY' and context.role not in {'OWNER','ADMIN'}:
            raise HTTPException(403, 'An owner or administrator must create customer-paid return checkout')
        digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        async with self.pool.acquire() as connection:
            if not await connection.fetchval("SELECT to_regclass('public.reverse_logistics_requests') IS NOT NULL"):
                raise HTTPException(503, 'Apply migration 042 before using headless returns')
            async with connection.transaction():
                parents = await connection.fetch('''SELECT id,ecommerce_store_id,status FROM public.shipments
                    WHERE tenant_id=$1 AND (id=$2 OR ($3::text IS NOT NULL AND
                      (customer_reference=$3 OR tracking_number=$3 OR store_order_id=$3)))
                    AND ($4::uuid IS NULL OR ecommerce_store_id=$4) LIMIT 2''',
                    context.tenant_id, command.shipment_id, command.order_reference, store_id)
                if len(parents) != 1:
                    raise HTTPException(404, 'No unique original shipment was found in this workspace and store')
                parent_id = parents[0]['id']
                await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                    f'reverse:{context.tenant_id}:{parent_id}')
                previous = await connection.fetchrow('''SELECT * FROM public.reverse_logistics_requests
                    WHERE tenant_id=$1 AND (id=$2 OR original_shipment_id=$3)''',
                    context.tenant_id, command.idempotency_key, parent_id)
                if previous:
                    if (previous['id'] != command.idempotency_key or previous['input_sha256'] != digest
                            or previous['requested_by'] != context.user_id or previous['source'] != source):
                        raise HTTPException(409, {'message':'A return already exists for this shipment or request key.',
                            'request_id': str(previous['id'])})
                else:
                    if parents[0]['status'] != 'DELIVERED':
                        raise HTTPException(409, 'Create a return after the original parcel has recorded delivery. No return request was created.')
                    await connection.execute('''INSERT INTO public.reverse_logistics_requests
                        (tenant_id,id,original_shipment_id,requested_by,source,charge_bearer,input_sha256)
                        VALUES($1,$2,$3,$4,$5,$6,$7)''', context.tenant_id, command.idempotency_key,
                        parent_id, context.user_id, source, command.charge_bearer, digest)
        if previous:
            return await self.status(context, command.idempotency_key)
        try:
            async with self.pool.acquire() as connection:
                warehouse = await connection.fetchrow('''SELECT id,address,version FROM public.tenant_catalog_addresses
                    WHERE tenant_id=$1 AND address_role='RETURN' AND is_default AND archived_at IS NULL''',
                    context.tenant_id)
            if warehouse is None:
                raise HTTPException(409, 'Save a default RETURN warehouse in Settings before creating a return')
            body = ReturnRequest(tenant_id=context.tenant_id, shipment_id=parent_id,
                idempotency_key=command.idempotency_key, customs_signer=command.customs_signer,
                hs_codes_reviewed=command.hs_codes_reviewed, store_return_reference=command.store_return_reference)
            prepared = await prepare_return_quote(self.lifecycle, context, body, warehouse=warehouse,
                paperless_requested=command.paperless_requested)
            shipment_id = UUID(prepared['shipment_id'])
            summary = {'request_id':str(command.idempotency_key), 'shipment_id':str(shipment_id),
                'original_shipment_id':str(parent_id), 'charge_bearer':command.charge_bearer}
            await self.save(context, command, 'PROCESSING', summary, shipment_id)
            if prepared.get('partial'):
                raise HTTPException(409, 'Some providers did not return rates. Review the prepared return before purchasing; no automatic cheapest-service claim is possible.')
            rate = cheapest_return(prepared['all_rates'])
            amount = Decimal(str(rate['client_price_ex_tax']))
            if command.maximum_price is not None and amount > command.maximum_price:
                raise HTTPException(409, 'The cheapest return exceeds the authorized maximum price; no purchase was made')
            summary.update(amount=format(amount,'.2f'), currency=rate['currency'], carrier_code=rate['carrier_code'])
            if command.charge_bearer == 'CUSTOMER_PAY':
                from backend.card_checkout import CardCart, create_cart
                checkout = await create_cart(self.lifecycle, context, CardCart(request_id=command.idempotency_key,
                    offers=[{'shipment_id':shipment_id,'offer_id':rate['offer_id'],
                             'expected_price':amount,'currency':rate['currency']}]))
                result = dict(summary, status='PAYMENT_REQUIRED', checkout_url=checkout['url'],
                    cart_id=checkout['cart_id'], paperless_available=False,
                    message='Customer payment is required on Stripe before the return is purchased. Unused paid credit remains in the merchant workspace wallet.')
            else:
                result = summary | await self.lifecycle.confirm(context, BookingRequest(
                    tenant_id=context.tenant_id, offer_id=UUID(str(rate['offer_id']))))
            state = result['status'] if result['status'] in {'BOOKED','PAYMENT_REQUIRED'} else 'REVIEW_REQUIRED'
            await self.save(context, command, state, result, shipment_id)
            from backend.return_documents import public_return_links
            linked = public_payload(public_return_links(self.lifecycle.automation.settings, context, result))
            from backend.logistics_media import publish_return_media
            return await publish_return_media(self.lifecycle, context, linked)
        except Exception as error:
            message = 'Return outcome needs reconciliation. Do not submit another return or payment.'
            if isinstance(error, HTTPException) and error.status_code < 500:
                message = error.detail if isinstance(error.detail, str) else error.detail.get('message', message)
            async with self.pool.acquire() as connection:
                await connection.execute('''UPDATE public.reverse_logistics_requests SET state='REVIEW_REQUIRED',
                    response=response||jsonb_build_object('status','REVIEW_REQUIRED','message',$3::text),updated_at=now()
                    WHERE tenant_id=$1 AND id=$2''', context.tenant_id, command.idempotency_key, message)
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(503, message) from None

    async def save(self, context, command, state, response, shipment_id):
        async with self.pool.acquire() as connection:
            await connection.execute('''UPDATE public.reverse_logistics_requests SET state=$3,
                return_shipment_id=$4,response=$5::jsonb,updated_at=now() WHERE tenant_id=$1 AND id=$2''',
                context.tenant_id, command.idempotency_key, state, shipment_id, json.dumps(public_payload(response)))


async def process_batch(lifecycle, context, commands, *, source='API', store_id=None):
    from backend.automation_three_partners import authorize
    authorize(context, context.tenant_id)
    if not 1 <= len(commands) <= 20:
        raise HTTPException(422, 'Submit between one and twenty return commands')
    if len({item.idempotency_key for item in commands}) != len(commands):
        raise HTTPException(422, 'Each return command needs its own idempotency key')
    results = []
    service = ReverseLogisticsService(lifecycle)
    for command in commands:
        try:
            results.append(await service.process(context, command, source=source, store_id=store_id))
        except HTTPException as error:
            results.append({'request_id':str(command.idempotency_key), 'status':'REVIEW_REQUIRED',
                'http_status':error.status_code, 'detail':error.detail})
    return {'results':results, 'requested':len(commands),
        'booked':sum(result['status']=='BOOKED' for result in results),
        'payment_required':sum(result['status']=='PAYMENT_REQUIRED' for result in results),
        'review_required':sum(result['status'] not in {'BOOKED','PAYMENT_REQUIRED'} for result in results)}
