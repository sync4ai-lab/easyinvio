"""Two-phase, tenant-bound return preparation and explicit service selection.

Preparation never buys postage. The original full-parcel command receipt is
claimed atomically before checkout; ambiguous purchases are never replayed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.automation_freight_engine import Cargo, Goods
from backend.dispatch_workspace import decoded
from backend.carrier_consolidation import public_payload


class ReturnEdits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cargo: Cargo
    items: list[Goods] = Field(max_length=100)
    customs_signer: str | None = Field(default=None, min_length=1, max_length=200)
    hs_codes_reviewed: bool = Field(default=False, strict=True)
    sender_eori: str | None = Field(default=None, max_length=40)
    recipient_eori: str | None = Field(default=None, max_length=40)
    sender_vat: str | None = Field(default=None, max_length=40)
    recipient_vat: str | None = Field(default=None, max_length=40)
    customs_currency: str = Field(default='GBP', pattern='^(GBP|EUR|USD)$')
    incoterm: str = Field(default='DAP', pattern='^(DAP|DDP|FCA|EXW)$')
    postal_form: str | None = Field(default=None, pattern='^(CN22|CN23)$')


class ReturnDelivery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: bool = Field(default=False, strict=True)
    whatsapp: bool = Field(default=False, strict=True)
    customer_permission_confirmed: bool = Field(default=False, strict=True)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    shipment_id: UUID
    charge_bearer: str = Field(pattern='^(RETAILER_PAY|CUSTOMER_PAY)$')
    paperless_requested: bool = Field(default=True, strict=True)
    edits: ReturnEdits
    delivery: ReturnDelivery = Field(default_factory=ReturnDelivery)


class SelectReturn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    offer_id: UUID


async def assert_review_purchase(connection, tenant_id: UUID, shipment_id: UUID,
                                 request_id: UUID, offer_id: UUID) -> None:
    """Every native entry point must respect a reviewed return's selected payer."""
    row = await connection.fetchrow('''SELECT r.* FROM public.return_review_sessions r
        JOIN public.reverse_logistics_requests command ON command.tenant_id=r.tenant_id AND command.id=r.id
          AND command.return_shipment_id=r.return_shipment_id
          AND command.original_shipment_id=r.original_shipment_id
        WHERE r.tenant_id=$1 AND r.id=$2 AND r.return_shipment_id=$3''', tenant_id, request_id, shipment_id)
    if not row or row['selected_offer_id'] != offer_id or row['state'] not in {'PROCESSING','PAYMENT_REQUIRED','BOOKED','REVIEW_REQUIRED'}:
        raise HTTPException(409, 'Choose and confirm this service in the original return review before booking')
    if row['charge_bearer'] == 'CUSTOMER_PAY':
        paid = await connection.fetchval("SELECT EXISTS(SELECT 1 FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2 AND status='CREDITED')", tenant_id, request_id)
        if not paid:
            raise HTTPException(409, 'Customer payment must be verified before buying this return label')


def ordered_rates(rates: list[dict]) -> list[dict]:
    from backend.agents.margin_optimizer import BUDGET_CARRIERS
    from backend.carrier_consolidation import carrier_identity
    usable = [r for r in rates if r.get('offer_id') and r.get('label_purchase_available') is not False
              and Decimal(str(r['client_price_ex_tax'])).is_finite()
              and Decimal(str(r['client_price_ex_tax'])) > 0]
    return sorted(usable, key=lambda r: (Decimal(str(r['client_price_ex_tax'])),
        carrier_identity(r['carrier_code']) not in BUDGET_CARRIERS, str(r['offer_id'])))[:10]


class ReturnReviewService:
    def __init__(self, lifecycle):
        self.lifecycle, self.pool = lifecycle, lifecycle.pool

    async def ready(self):
        async with self.pool.acquire() as c:
            if not await c.fetchval("SELECT to_regclass('public.return_review_sessions') IS NOT NULL AND to_regclass('public.return_customer_deliveries') IS NOT NULL"):
                raise HTTPException(503, 'Apply migration 046_return_review_and_delivery.sql, then restart the backend to enable reviewed returns')

    async def context(self, context, shipment_id: UUID) -> dict:
        from backend.automation_three_partners import authorize
        from backend.return_delivery import delivery_capabilities
        authorize(context, context.tenant_id)
        await self.ready()
        async with self.pool.acquire() as c:
            row = await c.fetchrow('''SELECT id,status,customer_reference,logistics_metadata,currency,
                booked_at,tracking_number FROM public.shipments WHERE tenant_id=$1 AND id=$2''',
                context.tenant_id, shipment_id)
            if not row:
                raise HTTPException(404, 'Shipment not found in this workspace')
            if row['status'] != 'DELIVERED' or not row['booked_at'] or not row['tracking_number']:
                raise HTTPException(409, 'Create a return after the original parcel has recorded delivery. A label or manifest alone is not delivery.')
            original = decoded(row['logistics_metadata']).get('automation_order') or {}
            if not original or original.get('is_return'):
                raise HTTPException(409, 'An original prepared outbound shipment is required')
            if len(original.get('packages') or []) > 1:
                raise HTTPException(409, 'This grouped shipment needs separately measured return parcels; a grouped return label cannot be purchased.')
            warehouse = await c.fetchrow('''SELECT id,address,version FROM public.tenant_catalog_addresses
                WHERE tenant_id=$1 AND address_role='RETURN' AND is_default AND archived_at IS NULL''', context.tenant_id)
            if not warehouse:
                raise HTTPException(409, 'Save a default RETURN address in Settings, then reopen this return.')
            existing = await c.fetchrow('''SELECT id,state FROM public.reverse_logistics_requests
                WHERE tenant_id=$1 AND original_shipment_id=$2''', context.tenant_id, shipment_id)
        if existing:
            raise HTTPException(409, {'message': 'A return already exists. Check its existing result before starting another.',
                                      'request_id': str(existing['id'])})
        customs = decoded(row['logistics_metadata']).get('automation_customs') or {}
        # No prior signature, consent or quote is reused. Parties are never editable
        # through this endpoint; the verified RETURN warehouse is version-fenced.
        edits = dict(cargo=original['cargo'], items=original.get('items') or [],
            customs_currency=original.get('customs_currency') or row['currency'],
            sender_eori=customs.get('recipient', {}).get('eori'),
            recipient_eori=customs.get('sender', {}).get('eori'),
            sender_vat=customs.get('recipient', {}).get('vat_registration'),
            recipient_vat=customs.get('sender', {}).get('vat_registration'),
            incoterm=original.get('incoterm') or 'DAP', hs_codes_reviewed=False, customs_signer=None,
            postal_form=original.get('postal_form'))
        return public_payload({'reference': row['customer_reference'] or str(shipment_id),
            'shipment_id': str(shipment_id), 'origin': original['destination'],
            'destination': decoded(warehouse['address']), 'edits': edits,
            'currency': row['currency'], 'delivery_capabilities': delivery_capabilities(self.lifecycle),
            'notice': 'Review the returned parcel and customs details. Prices are new return quotes; the original shipping price is not a return price.'})

    async def prepare(self, context, body: ReviewRequest) -> dict:
        from backend.automation_three_partners import ReturnRequest, prepare_return_quote
        from backend.return_delivery import validate_delivery
        facts = await self.context(context, body.shipment_id)
        if body.charge_bearer == 'CUSTOMER_PAY' and context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}:
            raise HTTPException(403, 'An owner or administrator must create customer-paid checkout')
        validate_delivery(self.lifecycle, body.delivery, facts['origin'])
        digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'return-review:{context.tenant_id}:{body.request_id}')
                previous = await c.fetchrow('SELECT * FROM public.return_review_sessions WHERE tenant_id=$1 AND id=$2', context.tenant_id, body.request_id)
                if previous:
                    if previous['input_sha256'] != digest or previous['requested_by'] != context.user_id:
                        raise HTTPException(409, 'This return preparation key already belongs to another request')
                    return public_payload(decoded(previous['response']) | {'request_id': str(body.request_id), 'status': previous['state'], 'replayed': True})
                await c.execute('''INSERT INTO public.return_review_sessions
                    (tenant_id,id,original_shipment_id,requested_by,input_sha256,charge_bearer,state,delivery)
                    VALUES($1,$2,$3,$4,$5,$6,'PREPARING',$7::jsonb)''', context.tenant_id, body.request_id,
                    body.shipment_id, context.user_id, digest, body.charge_bearer, body.delivery.model_dump_json())
        try:
            async with self.pool.acquire() as c:
                warehouse = await c.fetchrow('''SELECT id,address,version FROM public.tenant_catalog_addresses
                    WHERE tenant_id=$1 AND address_role='RETURN' AND is_default AND archived_at IS NULL''', context.tenant_id)
            if not warehouse:
                raise HTTPException(409, 'Default return address changed. Reopen the return for review.')
            prepared = await prepare_return_quote(self.lifecycle, context, ReturnRequest(
                tenant_id=context.tenant_id, shipment_id=body.shipment_id, idempotency_key=body.request_id,
                preparation_edits=body.edits.model_dump(mode='json')), warehouse=warehouse,
                paperless_requested=body.paperless_requested)
            rates = ordered_rates(prepared.get('all_rates') or [])
            if not rates:
                raise HTTPException(409, 'No purchasable return services are available. Check the parcel and route details.')
            async with self.pool.acquire() as c:
                expiry = await c.fetchval('SELECT quote_expires_at FROM public.shipments WHERE tenant_id=$1 AND id=$2', context.tenant_id, UUID(prepared['shipment_id']))
                result = public_payload({'request_id': str(body.request_id), 'shipment_id': prepared['shipment_id'],
                    'status': 'QUOTED', 'rates': rates, 'expires_at': expiry.isoformat(),
                    'partial': bool(prepared.get('partial')), 'charge_bearer': body.charge_bearer,
                    'notice': 'Choose a return service. No label has been purchased.'})
                await c.execute('''UPDATE public.return_review_sessions SET state='QUOTED',return_shipment_id=$3,
                    response=$4::jsonb,expires_at=$5,updated_at=now() WHERE tenant_id=$1 AND id=$2''',
                    context.tenant_id, body.request_id, UUID(prepared['shipment_id']), json.dumps(result), expiry)
                await c.execute('''UPDATE public.shipments SET logistics_metadata=logistics_metadata||
                    jsonb_build_object('return_review_id',$3::text) WHERE tenant_id=$1 AND id=$2''',
                    context.tenant_id, UUID(prepared['shipment_id']), str(body.request_id))
            return result
        except Exception:
            async with self.pool.acquire() as c:
                await c.execute("UPDATE public.return_review_sessions SET state='REVIEW_REQUIRED',updated_at=now() WHERE tenant_id=$1 AND id=$2", context.tenant_id, body.request_id)
            raise

    async def select(self, context, request_id: UUID, body: SelectReturn) -> dict:
        from backend.automation_three_partners import authorize, BookingRequest
        from backend.card_checkout import CardCart, create_cart
        authorize(context, context.tenant_id)
        await self.ready()
        async with self.pool.acquire() as c:
            async with c.transaction():
                row = await c.fetchrow('SELECT * FROM public.return_review_sessions WHERE tenant_id=$1 AND id=$2 FOR UPDATE', context.tenant_id, request_id)
                if not row:
                    raise HTTPException(404, 'Return preparation not found')
                if row['requested_by'] != context.user_id:
                    raise HTTPException(403, 'Open this return with the workspace user who prepared it')
                if row['state'] != 'QUOTED':
                    if row['selected_offer_id'] and row['selected_offer_id'] != body.offer_id:
                        raise HTTPException(409, 'This return already has a selected service. Check its existing result.')
                    return public_payload(decoded(row['response']) | {'status': row['state'], 'request_id': str(request_id), 'replayed': True})
                if not row['expires_at'] or row['expires_at'] <= datetime.now(timezone.utc):
                    raise HTTPException(409, 'Return quote expired. Compare fresh return rates; no label was purchased.')
                rate = next((r for r in decoded(row['response'])['rates'] if r['offer_id'] == str(body.offer_id)), None)
                if not rate:
                    raise HTTPException(409, 'Choose a service from this return quote')
                if row['charge_bearer'] == 'CUSTOMER_PAY' and context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}:
                    raise HTTPException(403, 'An owner or administrator must create customer-paid checkout')
                valid = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.partner_shipping_offers
                    WHERE tenant_id=$1 AND offer_id=$2 AND shipment_id=$3 AND expires_at>now())''',
                    context.tenant_id, body.offer_id, row['return_shipment_id'])
                if not valid:
                    raise HTTPException(409, 'Return offer expired or changed. Compare fresh rates.')
                delivered = await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.shipments WHERE tenant_id=$1 AND id=$2 AND status='DELIVERED')", context.tenant_id, row['original_shipment_id'])
                if not delivered:
                    raise HTTPException(409, 'The original delivery status changed. Review the shipment before returning it.')
                await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'reverse:{context.tenant_id}:{row["original_shipment_id"]}')
                previous = await c.fetchval('SELECT id FROM public.reverse_logistics_requests WHERE tenant_id=$1 AND original_shipment_id=$2', context.tenant_id, row['original_shipment_id'])
                if previous:
                    raise HTTPException(409, {'message': 'A return already exists. Check its outcome instead of buying another label.', 'request_id': str(previous)})
                await c.execute('''INSERT INTO public.reverse_logistics_requests
                    (tenant_id,id,original_shipment_id,requested_by,source,charge_bearer,input_sha256,return_shipment_id)
                    VALUES($1,$2,$3,$4,'API',$5,$6,$7)''', context.tenant_id, request_id,
                    row['original_shipment_id'], context.user_id, row['charge_bearer'], row['input_sha256'], row['return_shipment_id'])
                await c.execute("UPDATE public.return_review_sessions SET state='PROCESSING',selected_offer_id=$3,updated_at=now() WHERE tenant_id=$1 AND id=$2", context.tenant_id, request_id, body.offer_id)
        # No network or payment call holds the database row lock.
        try:
            if row['charge_bearer'] == 'CUSTOMER_PAY':
                checkout = await create_cart(self.lifecycle, context, CardCart(request_id=request_id,
                    offers=[{'shipment_id': row['return_shipment_id'], 'offer_id': body.offer_id,
                             'expected_price': Decimal(rate['client_price_ex_tax']), 'currency': rate['currency']}]))
                result = {'status': 'PAYMENT_REQUIRED', 'checkout_url': checkout['url'], 'cart_id': checkout['cart_id']}
            else:
                result = await self.lifecycle.confirm(context, BookingRequest(tenant_id=context.tenant_id, offer_id=body.offer_id))
            result = public_payload(result | {'request_id': str(request_id), 'shipment_id': str(row['return_shipment_id']),
                'carrier_code': rate['carrier_code'], 'service_code': rate.get('service_code'),
                'amount': rate['client_price_ex_tax'], 'currency': rate['currency'], 'charge_bearer': row['charge_bearer']})
            status = result['status'] if result['status'] in {'BOOKED','PAYMENT_REQUIRED'} else 'REVIEW_REQUIRED'
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await c.execute('''UPDATE public.return_review_sessions SET state=$3,response=$4::jsonb,updated_at=now()
                        WHERE tenant_id=$1 AND id=$2''', context.tenant_id, request_id, status, json.dumps(result))
                    await c.execute('''UPDATE public.reverse_logistics_requests SET state=$3,response=$4::jsonb,updated_at=now()
                        WHERE tenant_id=$1 AND id=$2''', context.tenant_id, request_id, status, json.dumps(result))
            from backend.return_delivery import stage_notices
            await stage_notices(self.lifecycle, context.tenant_id, request_id, 'PAYMENT' if status == 'PAYMENT_REQUIRED' else 'LABEL')
            return await self.status(context, request_id)
        except Exception as error:
            # This is a reconciliation state, never permission to retry a purchase.
            # A process crash before this handler leaves the committed PROCESSING
            # fence intact. Native payment/carrier workers still own recovery.
            message = error.detail if isinstance(error, HTTPException) and isinstance(error.detail, str) else 'Return confirmation needs reconciliation. Check the existing payment and carrier outcome; do not pay or book again.'
            result = {'status': 'REVIEW_REQUIRED', 'request_id': str(request_id), 'shipment_id': str(row['return_shipment_id']), 'message': message}
            async with self.pool.acquire() as c:
                async with c.transaction():
                    await c.execute("UPDATE public.return_review_sessions SET state='REVIEW_REQUIRED',response=$3::jsonb,updated_at=now() WHERE tenant_id=$1 AND id=$2", context.tenant_id, request_id, json.dumps(result))
                    await c.execute("UPDATE public.reverse_logistics_requests SET state='REVIEW_REQUIRED',response=$3::jsonb,updated_at=now() WHERE tenant_id=$1 AND id=$2", context.tenant_id, request_id, json.dumps(result))
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(503, message) from None

    async def status(self, context, request_id: UUID) -> dict:
        from backend.automation_three_partners import authorize
        from backend.return_delivery import stage_notices
        authorize(context, context.tenant_id)
        await self.ready()
        async with self.pool.acquire() as c:
            row = await c.fetchrow('SELECT * FROM public.return_review_sessions WHERE tenant_id=$1 AND id=$2', context.tenant_id, request_id)
            if not row:
                raise HTTPException(404, 'Return preparation not found')
            result = decoded(row['response'])
            label, available = {}, False
            if row['charge_bearer'] == 'CUSTOMER_PAY' and row['selected_offer_id'] and row['state'] in {'PROCESSING','PAYMENT_REQUIRED'}:
                cart = await c.fetchrow('SELECT status,results FROM public.payment_carts WHERE tenant_id=$1 AND id=$2', context.tenant_id, request_id)
                if cart and cart['status'] == 'REVIEW_REQUIRED':
                    result.update(status='REVIEW_REQUIRED', message=decoded(cart['results']).get('notice') or 'Payment or carrier confirmation needs review. Check the existing payment result; do not pay again.')
                    result.pop('checkout_url', None)
                    await c.execute("UPDATE public.return_review_sessions SET state='REVIEW_REQUIRED',response=$3::jsonb,updated_at=now() WHERE tenant_id=$1 AND id=$2", context.tenant_id, request_id, json.dumps(result))
            if row['return_shipment_id'] and row['selected_offer_id']:
                child = await c.fetchrow('SELECT status,logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2', context.tenant_id, row['return_shipment_id'])
                from backend.return_delivery import label_ready
                if child and await label_ready(c, context.tenant_id, row):
                    available = True
                    label = decoded(child['logistics_metadata']).get('automation_label') or {}
                    if label.get('label_url'):
                        result.update(status='BOOKED', shipment_id=str(row['return_shipment_id']))
                        result.pop('checkout_url', None)
                        await c.execute("UPDATE public.return_review_sessions SET state='BOOKED',response=$3::jsonb,updated_at=now() WHERE tenant_id=$1 AND id=$2", context.tenant_id, request_id, json.dumps(result))
            if row['state'] == 'BOOKED' and not available:
                result = {'status': 'REVIEW_REQUIRED', 'message': 'The return document is no longer available. Review the recorded shipment and payment outcome.'}
            result.update(request_id=str(request_id), status=result.get('status') if result.get('status') in {'BOOKED','REVIEW_REQUIRED'} else row['state'])
        if result['status'] == 'BOOKED':
            await stage_notices(self.lifecycle, context.tenant_id, request_id, 'LABEL')
            result['label_path'] = f'/api/v1/shipping/{row["return_shipment_id"]}/documents/label'
            if any(label.get(key) for key in ('return_dropoff_qr_code_url','return_dropoff_qr_code_base64','return_dropoff_qr_code_svg')):
                result['qr_path'] = f'/api/v1/shipping/{row["return_shipment_id"]}/documents/return-qr'
        async with self.pool.acquire() as c:
            notices = await c.fetch('SELECT kind,channel,state,error_code FROM public.return_customer_deliveries WHERE tenant_id=$1 AND review_id=$2 ORDER BY id', context.tenant_id, request_id)
        result['notifications'] = [dict(n) for n in notices]
        return public_payload(result)


def build_router(authenticate):
    router = APIRouter()

    @router.get('/returns/{shipment_id}/preparation-context')
    async def context(shipment_id: UUID, request: Request, identity=Depends(authenticate)):
        return await ReturnReviewService(request.app.state.partner_lifecycle).context(identity, shipment_id)

    @router.post('/returns/review')
    async def review(body: ReviewRequest, request: Request, identity=Depends(authenticate)):
        return await ReturnReviewService(request.app.state.partner_lifecycle).prepare(identity, body)

    @router.post('/returns/reviews/{request_id}/select')
    async def select(request_id: UUID, body: SelectReturn, request: Request, identity=Depends(authenticate)):
        return await ReturnReviewService(request.app.state.partner_lifecycle).select(identity, request_id, body)

    @router.get('/returns/reviews/{request_id}')
    async def status(request_id: UUID, request: Request, identity=Depends(authenticate)):
        return await ReturnReviewService(request.app.state.partner_lifecycle).status(identity, request_id)

    @router.get('/returns/customer-document')
    async def document(token: str, request: Request):
        from backend.return_delivery import customer_document
        return await customer_document(request.app.state.partner_lifecycle, token)

    return router
