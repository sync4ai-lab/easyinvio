"""Native signed intake and opt-in Shopify fulfillment delivery.

Credentials remain server configuration. Amazon intake is a signed adapter
gateway, not a claim to implement Amazon SP-API/SNS authentication.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.ecommerce_sync import ImportPayload
from backend.ai_engine import strict_decimal


class StoreConnector(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, hide_input_in_errors=True)
    tenant_id: UUID
    auth_user_id: UUID
    platform: Literal['SHOPIFY','WOOCOMMERCE','AMAZON']
    webhook_secret: SecretStr
    shop_domain: str | None = None
    access_token: SecretStr | None = None
    client_id: str | None = None
    client_secret: SecretStr | None = None
    api_version: str = Field(default='2026-10', pattern=r'^20\d{2}-(01|04|07|10)$')
    live_delivery: bool = Field(default=False, strict=True)
    live_import: bool = Field(default=False, strict=True)
    # Woo/Amazon order payloads often omit physical weights; use verified SKU data.
    sku_unit_grams: dict[str, Decimal] = Field(default_factory=dict)
    cargo_type: Literal['LETTER', 'PARCEL', 'PALLET', 'OVERLAND_FREIGHT'] = 'PARCEL'
    amazon_region: Literal['na', 'eu', 'fe'] = 'eu'
    amazon_seller_id: str | None = Field(default=None, max_length=100)
    amazon_marketplace_ids: list[str] = Field(default_factory=list, max_length=50)
    amazon_client_id: str | None = None
    amazon_client_secret: SecretStr | None = None
    amazon_refresh_token: SecretStr | None = None

    @field_validator('webhook_secret')
    @classmethod
    def secret_length(cls, value):
        if len(value.get_secret_value()) < 32:
            raise ValueError('Webhook secret must contain at least 32 characters')
        return value

    @field_validator('shop_domain')
    @classmethod
    def domain(cls, value):
        if value is not None and not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.myshopify\.com', value):
            raise ValueError('Use the exact canonical myshopify.com hostname')
        return value

    @model_validator(mode='after')
    def configured(self):
        if self.platform == 'SHOPIFY' and not self.shop_domain:
            raise ValueError('Shopify requires shop_domain for webhook identity verification')
        if self.live_delivery and (self.platform != 'SHOPIFY' or not self.access_token or not self.access_token.get_secret_value().strip()):
            raise ValueError('Live delivery currently requires a Shopify access token')
        if bool(self.client_id) != bool(self.client_secret):
            raise ValueError('Supply both Shopify client credentials')
        if self.live_import and (self.platform != 'SHOPIFY' or not (self.access_token and self.access_token.get_secret_value().strip() or self.client_id and self.client_secret)):
            raise ValueError('Live polling currently requires a Shopify access token')
        if self.platform == 'AMAZON' and self.amazon_seller_id and not all((self.amazon_marketplace_ids,self.amazon_client_id,self.amazon_client_secret,self.amazon_refresh_token)):
            raise ValueError('Native Amazon intake requires complete seller authorization')
        if any(not weight.is_finite() or weight <= 0 or weight > 1000000 for weight in self.sku_unit_grams.values()):
            raise ValueError('SKU weights must be positive finite grams')
        return self


class StoreConnectorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', hide_input_in_errors=True)
    ecommerce_connectors: dict[UUID, StoreConnector] = Field(default_factory=dict)


def single_header(request: Request, name: str) -> str:
    values = request.headers.getlist(name)
    if len(values) != 1 or not values[0] or len(values[0]) > 500:
        raise HTTPException(401, 'Invalid webhook authentication')
    return values[0]


async def receive_store_webhook(request: Request, store_id: UUID, *, initial_status='PENDING_IMPORT'):
    service = request.app.state.ecommerce
    from backend.store_connections import resolve_connector
    config = await resolve_connector(service, store_id)
    if config is None:
        raise HTTPException(401, 'Unconfigured storefront webhook')
    if request.headers.get('content-type','').split(';')[0].lower() != 'application/json':
        raise HTTPException(415, 'Use application/json')
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1048576:
            raise HTTPException(413, 'Order payload is limited to 1 MB')
    secret = config.webhook_secret.get_secret_value().encode()
    if config.platform == 'SHOPIFY':
        signature = single_header(request, 'x-shopify-hmac-sha256')
        expected = base64.b64encode(hmac.digest(secret, raw, 'sha256')).decode()
        if not hmac.compare_digest(single_header(request, 'x-shopify-shop-domain'), config.shop_domain):
            raise HTTPException(401, 'Invalid storefront identity')
        topic = single_header(request, 'x-shopify-topic')
        if topic not in {'orders/create','orders/paid'}:
            raise HTTPException(422, 'Unsupported Shopify order topic')
    elif config.platform == 'WOOCOMMERCE':
        signature = single_header(request, 'x-wc-webhook-signature')
        expected = base64.b64encode(hmac.digest(secret, raw, 'sha256')).decode()
        if single_header(request, 'x-wc-webhook-topic') not in {'order.created','order.updated'}:
            raise HTTPException(422, 'Unsupported WooCommerce order topic')
        topic = 'orders/create'
    else:
        signature = single_header(request, 'x-veloce-signature')
        timestamp = single_header(request, 'x-veloce-timestamp')
        try:
            if abs(time.time()-int(timestamp)) > 300:
                raise ValueError()
        except ValueError:
            raise HTTPException(401, 'Expired adapter signature') from None
        expected = hmac.new(secret, timestamp.encode()+b'.'+str(store_id).encode()+b'.'+raw, hashlib.sha256).hexdigest()
        topic = 'orders/create'
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, 'Invalid webhook signature')
    try:
        data = json.loads(raw, parse_float=Decimal)
        if not isinstance(data, dict):
            raise ValueError('Object required')
        if config.platform == 'SHOPIFY':
            data = normalize_shopify(data, config)
        elif config.platform == 'WOOCOMMERCE':
            data = normalize_woocommerce(data, config)
        # Amazon's trusted SP-API adapter sends the normalized StoreOrder shape.
        payload = ImportPayload.model_validate({'store_id':store_id,'platform':config.platform,'topic':topic,'order':data,'cargo_type':data.get('cargo_type',config.cargo_type)})
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, 'Invalid order or missing verified item weights') from None
    context = SimpleNamespace(tenant_id=config.tenant_id,user_id=config.auth_user_id,role='DISPATCHER')
    if initial_status == "PENDING_IMPORT":
        return await service.import_order(context, payload)
    return await service.import_order(context, payload, initial_status=initial_status)


def normalize_shopify(data: dict, config: StoreConnector) -> dict:
    """Current native orders: nullable address fields and verified SKU weights."""
    shipping = data['shipping_address']
    items = []
    for line in data['line_items']:
        if line.get('requires_shipping') is False:
            continue
        grams = line.get('grams')
        if grams is None or strict_decimal(str(grams)) <= 0:
            grams = config.sku_unit_grams.get(str(line.get('sku', '')))
        if grams is None:
            raise ValueError('Configure verified SKU weight')
        item = {**line, 'grams': str(grams)}
        if item.get('unit_value') is None and line.get('price') is not None:
            item['unit_value'] = str(line['price'])
        items.append(item)
    normalized = {**data, 'line_items': items, 'shipping_address': {**shipping,
        'address2': shipping.get('address2') or '', 'phone': shipping.get('phone') or '',
        'province': shipping.get('province_code') or shipping.get('province') or ''}}
    return normalized


def normalize_woocommerce(data: dict, config: StoreConnector) -> dict:
    if data.get('status') not in {'pending','on-hold','processing'}:
        raise ValueError('Order is not pending fulfillment')
    shipping = data['shipping']
    items = []
    for line in data['line_items']:
        sku = str(line.get('sku',''))
        if sku not in config.sku_unit_grams:
            raise ValueError('Missing verified SKU weight')
        items.append({'title':line['name'],'quantity':line['quantity'],'grams':str(config.sku_unit_grams[sku])})
    return {'id':data['id'],'name':'#'+str(data.get('number',data['id'])),'currency':data['currency'],
            'shipping_address':{'name':(shipping['first_name']+' '+shipping['last_name']).strip(),
                'address1':shipping['address_1'],'address2':shipping.get('address_2',''),
                'city':shipping['city'],'zip':shipping['postcode'],'country_code':shipping['country'],
                'province':shipping.get('state','')},'line_items':items}


async def shopify_access_token(client, config):
    """Renew short-lived own-organization tokens; never store or log responses."""
    if config.client_id and config.client_secret:
        try:
            response = await client.post(f'https://{config.shop_domain}/admin/oauth/access_token',
                data={'grant_type': 'client_credentials', 'client_id': config.client_id,
                      'client_secret': config.client_secret.get_secret_value()},
                timeout=20, follow_redirects=False)
            token = response.json().get('access_token') if response.status_code == 200 else None
            if not isinstance(token, str) or not token.strip():
                raise ValueError()
            return token
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise HTTPException(503, 'Shopify authorization failed. Check installation and app ownership, or contact support.') from None
    if not config.access_token:
        raise HTTPException(409, 'Connect a Shopify Admin API account first')
    return config.access_token.get_secret_value()


class ShopifyFulfillment:
    """Whole-order/single-location fulfillment; never invent item allocation."""
    def __init__(self, client: httpx.AsyncClient, config: StoreConnector):
        self.client, self.config = client, config

    async def graphql(self, query, variables):
        response = await self.client.post(
            f'https://{self.config.shop_domain}/admin/api/{self.config.api_version}/graphql.json',
            headers={'X-Shopify-Access-Token':await shopify_access_token(self.client, self.config)},
            json={'query':query,'variables':variables},timeout=20,follow_redirects=False)
        if response.status_code != 200:
            raise HTTPException(503, 'Store fulfillment requires reconciliation')
        data = response.json()
        if data.get('errors') or not isinstance(data.get('data'),dict):
            raise HTTPException(503, 'Store fulfillment requires reconciliation')
        return data['data']

    async def deliver(self, body, *, verify_only=False):
        order_id = body['store_order_id']
        if not re.fullmatch(r'[1-9][0-9]{0,30}',order_id):
            raise HTTPException(422, 'Shopify requires its numeric order ID')
        data = await self.graphql('''query EasyInvioOrder($id:ID!) { order(id:$id) {
            fulfillments(first:250) { id status trackingInfo { number } }
            fulfillmentOrders(first:100) { pageInfo { hasNextPage } nodes {
                id status assignedLocation { location { id } } } } } }''',
            {'id':'gid://shopify/Order/'+order_id})
        order = data.get('order')
        if not order:
            raise HTTPException(404, 'Store order not found')
        numbers=body.get('tracking_numbers') or [body['tracking_number']]
        if not numbers or len(numbers)>100 or len(numbers)!=len(set(numbers)):
            raise HTTPException(422,'Unique tracking numbers are required for all packages')
        for fulfillment in order['fulfillments']:
            if fulfillment['status'] == 'SUCCESS' and set(numbers).issubset({t['number'] for t in fulfillment['trackingInfo']}):
                return {'fulfillment_state':'SHIPPED','fulfillment_id':fulfillment['id'],'replayed':True,'simulated':False}
        if verify_only:
            raise HTTPException(409, 'No confirmed matching fulfillment; keep reconciliation hold')
        if len(order['fulfillments'])>=250:
            raise HTTPException(409, 'Fulfillment history requires explicit reconciliation')
        orders = order['fulfillmentOrders']
        eligible = [o for o in orders['nodes'] if o['status']=='OPEN']
        locations = {o['assignedLocation']['location']['id'] for o in eligible if o['assignedLocation'].get('location')}
        if orders['pageInfo']['hasNextPage'] or len(locations)!=1 or not eligible or len(eligible)!=len(orders['nodes']) or any(not o['assignedLocation'].get('location') for o in eligible):
            raise HTTPException(409, 'Split or partial fulfillment requires explicit allocation')
        info = {'company':body['carrier_name'],**({'numbers':numbers} if len(numbers)>1 else {'number':numbers[0]})}
        if len(numbers)==1 and body.get('tracking_url'):
            info['url'] = body['tracking_url']
        result = await self.graphql('''mutation EasyInvioShip($fulfillment:FulfillmentInput!) {
            fulfillmentCreate(fulfillment:$fulfillment) { fulfillment { id status } userErrors { field message } } }''',
            {'fulfillment':{'lineItemsByFulfillmentOrder':[{'fulfillmentOrderId':o['id']} for o in eligible],
                            'trackingInfo':info,'notifyCustomer':False}})
        created = result['fulfillmentCreate']
        if created.get('userErrors') or not created.get('fulfillment') or created['fulfillment']['status']!='SUCCESS':
            raise HTTPException(503, 'Store fulfillment requires reconciliation')
        return {'fulfillment_state':'SHIPPED','fulfillment_id':created['fulfillment']['id'],'simulated':False}
