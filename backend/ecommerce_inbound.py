"""Authenticated Shopify intake and Amazon AWS API-destination order notifications."""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import logging
import re
from types import SimpleNamespace
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, HTTPException, Request

from backend.ecommerce_sync import ImportPayload
from backend.store_connections import resolve_connector


def amazon_order(body, config, expected_id):
    order = body['order']
    if order['orderId'] != expected_id or order['salesChannel']['marketplaceId'] not in config.amazon_marketplace_ids:
        raise ValueError('Order identity mismatch')
    fulfillment = order['fulfillment']
    if fulfillment['fulfilledBy'] != 'MERCHANT' or fulfillment['fulfillmentStatus'] != 'UNSHIPPED':
        return None
    address = order['recipient']['deliveryAddress']
    items = []
    currency = None
    for item in order['orderItems']:
        if item['fulfillment']['quantityUnfulfilled'] != item['quantityOrdered']:
            raise ValueError('Partial allocation requires review')
        product = item['product']
        weight = config.sku_unit_grams.get(product['sellerSku'])
        if weight is None:
            raise ValueError('Verified SKU weight required')
        price = product['price']['unitPrice']
        if currency is not None and currency != price['currencyCode']:
            raise ValueError('Mixed currency')
        currency = price['currencyCode']
        items.append({'title': product['title'], 'quantity': item['quantityOrdered'],
            'grams': str(weight), 'unit_value': str(price['amount'])})
    return {'id': expected_id, 'name': expected_id, 'currency': currency,
        'shipping_address': {'name': address['name'], 'address1': address['addressLine1'],
            'address2': ' '.join(part for part in (address.get('addressLine2'), address.get('addressLine3')) if part),
            'city': address['city'], 'zip': address['postalCode'], 'country_code': address['countryCode'],
            'province': address.get('stateOrRegion') or '', 'phone': address.get('phone') or ''},
        'line_items': items}


async def fetch_amazon_order(client, config, order_id):
    if not all((config.amazon_client_id, config.amazon_client_secret, config.amazon_refresh_token,
                config.amazon_seller_id, config.amazon_marketplace_ids)):
        raise HTTPException(409, 'Configure an authorized Amazon seller app, marketplaces and SKU weights')
    try:
        token_response = await client.post('https://api.amazon.com/auth/o2/token',
            data={'grant_type': 'refresh_token', 'refresh_token': config.amazon_refresh_token.get_secret_value(),
                'client_id': config.amazon_client_id, 'client_secret': config.amazon_client_secret.get_secret_value()},
            timeout=20, follow_redirects=False)
        if token_response.status_code != 200:
            raise HTTPException(503, 'Amazon seller authorization needs attention')
        token = token_response.json()['access_token']
        if not isinstance(token, str) or not token.strip():
            raise ValueError()
        root = {'na': 'https://sellingpartnerapi-na.amazon.com', 'eu': 'https://sellingpartnerapi-eu.amazon.com',
                'fe': 'https://sellingpartnerapi-fe.amazon.com'}[config.amazon_region]
        response = await client.get(root + '/orders/2026-01-01/orders/' + order_id,
            headers={'x-amz-access-token': token}, params={'includedData': 'RECIPIENT,FULFILLMENT,PROCEEDS'},
            timeout=20, follow_redirects=False)
        if response.status_code != 200:
            raise HTTPException(503, 'Amazon order access unavailable; verify seller permissions and retry')
        return json.loads(response.content, parse_float=Decimal)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HTTPException(503, 'Amazon returned an invalid order response') from None


class AmazonInbound:
    def __init__(self, ecommerce):
        self.ecommerce = ecommerce
        self.pool = ecommerce.pool

    async def receive(self, request, store_id, config):
        values = request.headers.getlist('x-easyinvio-amazon-key')
        if len(values) != 1 or not hmac.compare_digest(values[0].encode(), config.webhook_secret.get_secret_value().encode()):
            raise HTTPException(401, 'Invalid Amazon notification authentication')
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/json':
            raise HTTPException(415, 'Use application/json for the AWS API destination')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1048576:
                raise HTTPException(413, 'Notification is limited to 1 MB')
        try:
            envelope = json.loads(raw)
            notification = envelope.get('detail', envelope)
            if notification['NotificationType'] != 'ORDER_CHANGE':
                return {'status': 'IGNORED', 'reason': 'Not an order change'}
            change = notification['Payload']['OrderChangeNotification']
            if change['SellerId'] != config.amazon_seller_id or change['Summary']['MarketplaceId'] not in config.amazon_marketplace_ids:
                raise HTTPException(401, 'Amazon seller or marketplace does not match the connection')
            notification_id = notification['NotificationMetadata']['NotificationId']
            order_id = change['AmazonOrderId']
            if not isinstance(notification_id, str) or not 1 <= len(notification_id) <= 150:
                raise ValueError()
            if not re.fullmatch(r'[0-9]{3}-[0-9]{7}-[0-9]{7}', order_id):
                raise ValueError()
            published = datetime.fromisoformat(notification['NotificationMetadata']['PublishTime'].replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            if published.tzinfo is None or published > now + timedelta(minutes=5) or published < now - timedelta(days=7):
                raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(422, 'Invalid Amazon ORDER_CHANGE notification') from None
        digest = hashlib.sha256(json.dumps(notification,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                active = await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2 AND platform=\'AMAZON\' AND is_active)', config.tenant_id, store_id)
                if not active:
                    raise HTTPException(404, 'Active Amazon store not found')
                await connection.execute('''INSERT INTO public.amazon_order_notifications(tenant_id,store_id,notification_id,order_id,body_sha256)
                    VALUES($1,$2,$3,$4,$5) ON CONFLICT(tenant_id,store_id,notification_id) DO NOTHING''',
                    config.tenant_id, store_id, notification_id, order_id, digest)
                receipt = await connection.fetchrow('SELECT id,body_sha256,status FROM public.amazon_order_notifications WHERE tenant_id=$1 AND store_id=$2 AND notification_id=$3', config.tenant_id, store_id, notification_id)
                if receipt['body_sha256'] != digest:
                    raise HTTPException(409, 'Notification identity was reused with different content')
        return {'status': receipt['status'], 'receipt_id': str(receipt['id']),
            'notice': 'Accepted durably. Authorized order details will be retrieved before a shipment is created.'}

    async def process_one(self):
        async with self.pool.acquire() as lock:
            await lock.execute("UPDATE public.amazon_order_notifications SET status='REVIEW_REQUIRED',last_error_code='RETRY_LIMIT' WHERE status='RECEIVED' AND attempts>=30")
            row = await lock.fetchrow("SELECT * FROM public.amazon_order_notifications WHERE status='RECEIVED' AND next_attempt_at<=now() AND attempts<30 ORDER BY next_attempt_at,id LIMIT 1")
            if row is None:
                return False
            key = 'amazon-intake:' + str(row['id'])
            if not await lock.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key):
                return False
            try:
                row = await lock.fetchrow("SELECT * FROM public.amazon_order_notifications WHERE id=$1 AND status='RECEIVED' AND next_attempt_at<=now() AND attempts<30", row['id'])
                if row is None:
                    return True
                await lock.execute("UPDATE public.amazon_order_notifications SET attempts=attempts+1,next_attempt_at=now()+make_interval(secs=>$2) WHERE id=$1", row['id'], min(3600, 2 ** min(row['attempts'] + 1, 12)))
                active = await lock.fetchval('SELECT EXISTS(SELECT 1 FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2 AND is_active)', row['tenant_id'], row['store_id'])
                if not active:
                    raise ValueError('Store is disabled')
                config = await resolve_connector(self.ecommerce, row['store_id'])
                if not config or config.platform != 'AMAZON' or config.tenant_id != row['tenant_id']:
                    raise ValueError('Invalid connection')
                body = await fetch_amazon_order(self.ecommerce.client, config, row['order_id'])
                normalized = amazon_order(body, config, row['order_id'])
                if normalized is None:
                    state = 'IGNORED'
                else:
                    payload = ImportPayload.model_validate({'store_id': row['store_id'], 'platform': 'AMAZON',
                        'cargo_type': config.cargo_type, 'order': normalized})
                    context = SimpleNamespace(tenant_id=config.tenant_id, user_id=config.auth_user_id, role='DISPATCHER')
                    await self.ecommerce.import_order(context, payload, initial_status='UNFULFILLED')
                    state = 'IMPORTED'
                await lock.execute('UPDATE public.amazon_order_notifications SET status=$2,last_error_code=NULL WHERE id=$1', row['id'], state)
            except (ValueError, KeyError, TypeError):
                await lock.execute("UPDATE public.amazon_order_notifications SET status='REVIEW_REQUIRED',last_error_code='ORDER_DATA_REVIEW' WHERE id=$1", row['id'])
            except HTTPException as error:
                state = 'REVIEW_REQUIRED' if error.status_code in {403, 404, 409, 422} or row['attempts'] >= 29 else 'RECEIVED'
                await lock.execute("UPDATE public.amazon_order_notifications SET status=$2,last_error_code='ORDER_ACCESS_OR_IMPORT_FAILED' WHERE id=$1", row['id'], state)
            finally:
                await lock.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)
        return True

    async def worker(self):
        while True:
            try:
                if await self.process_one():
                    continue
            except (asyncpg.PostgresError, httpx.HTTPError):
                logging.getLogger(__name__).warning('Amazon intake deferred; durable notification retained')
            await asyncio.sleep(2)


def build_router():
    router = APIRouter(prefix='/api/v1/integrations/ecommerce', tags=['Inbound marketplace orders'])

    @router.post('/orders-sync')
    async def orders(request: Request, store_id: UUID):
        service = request.app.state.ecommerce
        config = await resolve_connector(service, store_id)
        if config is None:
            raise HTTPException(401, 'Store connector is not configured')
        try:
            if config.platform == 'AMAZON' and request.headers.get('x-easyinvio-amazon-key'):
                from fastapi.responses import JSONResponse
                return JSONResponse(await request.app.state.amazon_inbound.receive(request, store_id, config), status_code=202)
            from backend.ecommerce_connectors import receive_store_webhook
            return await receive_store_webhook(request, store_id, initial_status='UNFULFILLED')
        except asyncpg.PostgresError:
            raise HTTPException(503, 'Order import was not committed; retry the same notification') from None

    return router
