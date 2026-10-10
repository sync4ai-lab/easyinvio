"""Operational marketplace inbox. No credentials or financial ledger are exposed.

Webhooks are the default ingestion path. Explicitly enabled Shopify polling is
read-only; packing/customs preparation and purchase remain separate actions.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from backend.ai_engine import predict_hs_code
from backend.automation_freight_engine import Order
from backend.ecommerce_sync import ImportPayload

ROLES = {'OWNER', 'ADMIN', 'DISPATCHER'}


def permitted(context):
    if context.role not in ROLES:
        raise HTTPException(403, 'Warehouse dispatch permission required')


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value or {}


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    shipment_ids: list[UUID] = Field(min_length=1, max_length=100)
    mode: Literal['QUOTE_ONLY', 'FULFILL'] = 'QUOTE_ONLY'


SHOPIFY_ORDERS = '''query WarehouseOrders($after:String) {
 orders(first:100,after:$after,query:"status:open fulfillment_status:unfulfilled",sortKey:CREATED_AT) {
  pageInfo { hasNextPage endCursor }
  nodes { id name currencyCode cancelledAt displayFulfillmentStatus
   shippingAddress { name address1 address2 city zip countryCodeV2 provinceCode phone }
   lineItems(first:100) { pageInfo { hasNextPage } nodes {
    title sku quantity unfulfilledQuantity requiresShipping originalUnitPriceSet { shopMoney { amount currencyCode } }
   } }
  }
 }
}'''


async def poll_shopify(service, context, store_id, config, *, after=None):
    """Bounded cursor polling; each invalid order fails independently, never buys."""
    if service.client is None:
        raise HTTPException(503, 'Marketplace client unavailable')
    results, cursor, seen = [], after, set()
    more = False
    for _ in range(10):
        try:
            response = await service.client.post(
                f'https://{config.shop_domain}/admin/api/{config.api_version}/graphql.json',
                headers={'X-Shopify-Access-Token': config.access_token.get_secret_value()},
                json={'query': SHOPIFY_ORDERS, 'variables': {'after': cursor}}, timeout=30,
                follow_redirects=False)
            if response.status_code != 200:
                raise HTTPException(503, 'Marketplace polling unavailable; retry later')
            body = response.json()
            if body.get('errors'):
                raise HTTPException(503, 'Marketplace query rejected; check scopes and configuration')
            page = body['data']['orders']
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Marketplace returned an invalid response') from None
        for node in page['nodes']:
            reference = str(node.get('name', 'Unknown'))[:100]
            try:
                if node.get('cancelledAt') or node['displayFulfillmentStatus'] != 'UNFULFILLED':
                    raise ValueError('Only wholly unfulfilled orders are supported')
                if node['lineItems']['pageInfo']['hasNextPage']:
                    raise ValueError('Over 100 items; manual review required')
                items = []
                for item in node['lineItems']['nodes']:
                    if not item['requiresShipping']:
                        continue
                    if item['unfulfilledQuantity'] != item['quantity']:
                        raise ValueError('Partial fulfillment requires reconciliation')
                    grams = config.sku_unit_grams.get(item['sku'])
                    if grams is None:
                        raise ValueError('Configure verified SKU weights before polling')
                    price = item['originalUnitPriceSet']['shopMoney']
                    if price['currencyCode'] != node['currencyCode']:
                        raise ValueError('Mixed currency')
                    items.append({'title': item['title'], 'quantity': item['quantity'],
                                  'grams': str(grams), 'unit_value': price['amount']})
                address = node['shippingAddress']
                payload = ImportPayload.model_validate({'store_id': store_id, 'platform': 'SHOPIFY',
                    'order': {'id': node['id'].rsplit('/', 1)[-1], 'name': reference,
                              'currency': node['currencyCode'], 'line_items': items,
                              'shipping_address': {'name': address['name'], 'address1': address['address1'],
                               'address2': address.get('address2') or '', 'city': address['city'], 'zip': address['zip'],
                               'country_code': address['countryCodeV2'], 'province': address.get('provinceCode') or '',
                               'phone': address.get('phone') or ''}}})
                result = await service.import_order(context, payload)
                results.append({'order_reference': reference, 'status': result['status'],
                                'shipment_id': result['shipment_id'], 'replayed': result['replayed']})
            except (ValueError, KeyError, TypeError, HTTPException):
                results.append({'order_reference': reference, 'status': 'REVIEW_REQUIRED',
                                'error': 'Check shipping address, SKU weights and unfulfilled item data'})
        more = page['pageInfo']['hasNextPage']
        if not more:
            break
        cursor = page['pageInfo']['endCursor']
        if not cursor or cursor in seen:
            raise HTTPException(502, 'Invalid marketplace pagination')
        seen.add(cursor)
    return {'source': 'SHOPIFY_API', 'results': results, 'more_available': more, 'next_cursor': cursor if more else None}


def suggested_order(row):
    metadata = decoded(row['logistics_metadata'])
    if metadata.get('automation_order'):
        return metadata['automation_order']
    source = metadata.get('ecommerce', {})
    items = []
    for item in source.get('line_items', []):
        code = item.get('hs_code') or predict_hs_code(item['title']).get('hs_code')
        items.append({'description': item['title'], 'quantity': item['quantity'],
                      'unit_value': item.get('unit_value'), 'origin_country': item.get('origin_country'),
                      'unit_weight_kg': str(Decimal(item['grams']) / 1000), 'hs_code': code})
    return {'idempotency_key': str(row['idempotency_key']), 'order_reference': row['customer_reference'],
            'platform': row['platform'], 'store_id': str(row['ecommerce_store_id']), 'store_order_id': row['store_order_id'],
            'origin': decoded(row['sender_address']), 'destination': decoded(row['recipient_address']),
            'currency': row['currency'], 'cargo': {'cargo_type': row['cargo_type'],
            'actual_weight_kg': str(row['parcel_weight_kg']), 'length_cm': None, 'width_cm': None, 'height_cm': None},
            'items': items, 'hs_codes_reviewed': False, 'customs_signer': None}


async def selected_rows(service, context, ids):
    if len(set(ids)) != len(ids):
        raise HTTPException(422, 'Duplicate shipments in selection')
    async with service.pool.acquire() as connection:
        rows = await connection.fetch('''SELECT s.*,e.platform FROM public.shipments s
            JOIN public.ecommerce_stores e ON e.tenant_id=s.tenant_id AND e.id=s.ecommerce_store_id
            WHERE s.tenant_id=$1 AND s.id=ANY($2::uuid[]) AND e.is_active''', context.tenant_id, ids)
    if len(rows) != len(ids):
        raise HTTPException(404, 'One or more workspace orders not found')
    by_id = {row['id']: row for row in rows}
    return [by_id[id_] for id_ in ids]


def build_router(authenticate):
    router = APIRouter(prefix='/api/v1/dispatch-workspace', tags=['Dispatcher workspace'])

    @router.get('/orders')
    async def inbox(request: Request, offset: int = 0, context: Any = Depends(authenticate)):
        permitted(context)
        if offset < 0 or offset > 100000:
            raise HTTPException(422, 'Invalid offset')
        service = request.app.state.ecommerce
        async with service.pool.acquire() as connection:
            stores = await connection.fetch('SELECT id,display_name,platform FROM public.ecommerce_stores WHERE tenant_id=$1 AND is_active ORDER BY display_name', context.tenant_id)
            rows = await connection.fetch('''SELECT s.id,s.customer_reference,s.status,s.cargo_type,
                e.display_name,e.platform,o.status AS tracking_sync_status
                FROM public.shipments s JOIN public.ecommerce_stores e ON e.tenant_id=s.tenant_id AND e.id=s.ecommerce_store_id
                LEFT JOIN public.ecommerce_tracking_outbox o ON o.tenant_id=s.tenant_id AND o.shipment_id=s.id
                WHERE s.tenant_id=$1 AND e.is_active ORDER BY s.created_at DESC,s.id DESC LIMIT 101 OFFSET $2''', context.tenant_id, offset)
        return {'stores': [{'id': str(s['id']), 'display_name': s['display_name'], 'platform': s['platform'],
                           'polling_enabled': bool((service.connectors.get(s['id'])) and service.connectors[s['id']].live_import)} for s in stores],
                'orders': [dict(row) for row in rows[:100]], 'more_available': len(rows) > 100, 'offset': offset}

    @router.post('/sync/{store_id}')
    async def sync(store_id: UUID, request: Request, after: str | None = None, context: Any = Depends(authenticate)):
        permitted(context)
        if after is not None and (not after or len(after) > 1000):
            raise HTTPException(422, 'Invalid polling cursor')
        service = request.app.state.ecommerce
        async with service.pool.acquire() as connection:
            store = await connection.fetchrow('SELECT platform FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2 AND is_active', context.tenant_id, store_id)
        if not store:
            raise HTTPException(404, 'Store not found')
        config = service.connectors.get(store_id)
        if not config or not config.live_import:
            return {'source': 'WEBHOOK_INBOX', 'results': [], 'more_available': False,
                    'notice': 'Inbox refreshed. Remote polling is not configured; signed webhooks import orders independently.'}
        if config.tenant_id != context.tenant_id or config.platform != store['platform']:
            raise HTTPException(409, 'Store connector identity mismatch')
        return await poll_shopify(service, context, store_id, config, after=after)

    @router.get('/orders/{shipment_id}')
    async def prepare(shipment_id: UUID, request: Request, context: Any = Depends(authenticate)):
        permitted(context)
        row = (await selected_rows(request.app.state.ecommerce, context, [shipment_id]))[0]
        return {'order': suggested_order(row), 'status': row['status'],
                'notice': 'Enter measured packed dimensions and weight; confirm goods origins, values, HS codes and signer. Suggestions are not regulatory verification.'}

    @router.post('/orders/{shipment_id}/prepare')
    async def save_preparation(shipment_id: UUID, order: Order, request: Request, context: Any = Depends(authenticate)):
        permitted(context)
        row = (await selected_rows(request.app.state.ecommerce, context, [shipment_id]))[0]
        if (order.idempotency_key != row['idempotency_key'] or order.store_id != row['ecommerce_store_id']
            or order.store_order_id != row['store_order_id'] or order.platform != row['platform']):
            raise HTTPException(409, 'Imported order identity cannot be changed')
        service = request.app.state.automation_freight
        if order.hs_codes_reviewed and any(not item.hs_code for item in order.items):
            raise HTTPException(422, 'Reviewed customs items require explicit confirmed HS codes')
        async with service.order_limiter:
            return await service.process(context, order.model_dump(mode='json'), 'QUOTE_ONLY')

    @router.post('/process')
    async def process(selection: Selection, request: Request, context: Any = Depends(authenticate)):
        permitted(context)
        rows = await selected_rows(request.app.state.ecommerce, context, selection.shipment_ids)
        service = request.app.state.automation_freight
        async def run(row):
            prepared = decoded(row['logistics_metadata']).get('automation_order')
            if not prepared:
                return {'shipment_id': str(row['id']), 'status': 'REVIEW_REQUIRED', 'error': 'Complete packing and customs preparation first'}
            async with service.order_limiter:
                return await service.process(context, prepared, selection.mode)
        results = await asyncio.gather(*(run(row) for row in rows))
        return {'mode': selection.mode, 'results': results}

    @router.post('/print-bundle')
    async def print_bundle(selection: Selection, request: Request, context: Any = Depends(authenticate)):
        permitted(context)
        from backend.dispatch_pdf import bundle_shipments
        rows = await selected_rows(request.app.state.ecommerce, context, selection.shipment_ids)
        data = await bundle_shipments(rows)
        return Response(data, media_type='application/pdf', headers={
            'Content-Disposition': 'attachment; filename="easyinvio-dispatch-bundle.pdf"', 'Cache-Control': 'no-store'})

    return router
