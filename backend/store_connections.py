"""Write-only merchant setup; encrypted envelopes are bound to tenant and store."""
import json
import secrets
from typing import Any, Literal
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from backend.ecommerce_connectors import StoreConnector


class ConnectionSetup(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    shop_domain: str | None = None
    access_token: SecretStr | None = Field(default=None, max_length=4096)
    client_id: str | None = Field(default=None, max_length=200)
    client_secret: SecretStr | None = Field(default=None, max_length=4096)
    authorization_mode: Literal['TOKEN', 'CLIENT_CREDENTIALS'] | None = None
    webhook_secret: SecretStr | None = Field(default=None, max_length=4096)
    live_import: bool = True
    live_returns: bool = Field(default=False,strict=True)
    sku_unit_grams: dict[str, str] = Field(default_factory=dict, max_length=1000)
    cargo_type: Literal['LETTER','PARCEL','PALLET','OVERLAND_FREIGHT'] = 'PARCEL'
    amazon_region: Literal['na','eu','fe'] = 'eu'
    amazon_seller_id: str | None = Field(default=None,max_length=100)
    amazon_marketplace_ids: list[str] = Field(default_factory=list,max_length=50)
    amazon_client_id: str | None = Field(default=None,max_length=200)
    amazon_client_secret: SecretStr | None = Field(default=None,max_length=4096)
    amazon_refresh_token: SecretStr | None = Field(default=None,max_length=4096)


async def resolve_connector(service, store_id):
    if not getattr(service, 'credential_keys', None):
        return service.connectors.get(store_id)
    async with service.pool.acquire() as connection:
        row = await connection.fetchrow('SELECT * FROM public.workspace_store_connections WHERE store_id=$1', store_id)
    if not row:
        return service.connectors.get(store_id)
    try:
        key = service.credential_keys[row['credential_key_id']].get_secret_value().encode()
        body = json.loads(Fernet(key).decrypt(bytes(row['credentials_ciphertext'])))
        if body.pop('store_id') != str(store_id) or body['tenant_id'] != str(row['tenant_id']):
            raise ValueError('Envelope identity mismatch')
        return StoreConnector.model_validate(body)
    except (KeyError, ValueError, TypeError, InvalidToken):
        raise HTTPException(503, 'Store credentials unavailable; contact support') from None


def public_settings(config):
    return {'configured': config is not None, 'shop_domain': config.shop_domain if config else '',
            'live_import': bool(config and config.live_import),
            'live_returns': bool(config and config.live_returns),
            'sku_unit_grams': {k: str(v) for k, v in config.sku_unit_grams.items()} if config else {},
            'has_access_token': bool(config and config.access_token),
            'has_client_credentials': bool(config and config.client_secret), 'client_id': config.client_id if config else '',
            'has_webhook_secret': bool(config and config.webhook_secret),
            'cargo_type': config.cargo_type if config else 'PARCEL',
            'amazon_region': config.amazon_region if config else 'eu',
            'amazon_seller_id': config.amazon_seller_id if config else '',
            'amazon_marketplace_ids': config.amazon_marketplace_ids if config else [],
            'amazon_client_id': config.amazon_client_id if config else '',
            'has_amazon_credentials': bool(config and config.amazon_refresh_token)}


def build_router(authenticate):
    router = APIRouter(prefix='/api/v1/workspace/stores', tags=['Store connections'])

    async def scoped_store(request, context, store_id):
        if context.role not in {'OWNER', 'ADMIN'}:
            raise HTTPException(403, 'Workspace owner or administrator required')
        async with request.app.state.ecommerce.pool.acquire() as connection:
            store = await connection.fetchrow('SELECT platform,is_active FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2', context.tenant_id, store_id)
        if not store:
            raise HTTPException(404, 'Workspace store not found')
        return store

    @router.get('/{store_id}/connection')
    async def read(store_id: UUID, request: Request, context: Any = Depends(authenticate)):
        await scoped_store(request, context, store_id)
        config = await resolve_connector(request.app.state.ecommerce, store_id)
        if config and config.tenant_id != context.tenant_id:
            raise HTTPException(409, 'Store configuration identity mismatch')
        return public_settings(config)

    @router.put('/{store_id}/connection')
    async def save(store_id: UUID, body: ConnectionSetup, request: Request, context: Any = Depends(authenticate)):
        store = await scoped_store(request, context, store_id)
        if store['platform'] not in {'SHOPIFY', 'WOOCOMMERCE', 'AMAZON'}:
            raise HTTPException(422, 'This platform requires assisted integration')
        service = request.app.state.ecommerce
        if not getattr(service, 'credential_keys', None):
            raise HTTPException(503, 'Server credential encryption unavailable')
        async with service.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'store-settings:' + str(store_id))
                row = await connection.fetchrow('SELECT credentials_ciphertext,credential_key_id FROM public.workspace_store_connections WHERE tenant_id=$1 AND store_id=$2', context.tenant_id, store_id)
                previous = {}
                legacy = service.connectors.get(store_id)
                if not row and legacy:
                    if legacy.tenant_id != context.tenant_id or legacy.platform != store['platform']:
                        raise HTTPException(409, 'Store configuration identity mismatch')
                    previous = legacy.model_dump(mode='json')
                    for name in ('access_token', 'client_secret', 'webhook_secret', 'amazon_client_secret', 'amazon_refresh_token'):
                        secret = getattr(legacy, name)
                        previous[name] = secret.get_secret_value() if secret else None
                if row:
                    try:
                        key = service.credential_keys[row['credential_key_id']].get_secret_value().encode()
                        previous = json.loads(Fernet(key).decrypt(bytes(row['credentials_ciphertext'])))
                        if previous.pop('store_id') != str(store_id) or previous['tenant_id'] != str(context.tenant_id):
                            raise ValueError()
                    except (KeyError, ValueError, InvalidToken):
                        raise HTTPException(503, 'Existing store credentials unavailable') from None
                values = body.model_dump(exclude={'access_token', 'client_secret', 'webhook_secret', 'amazon_client_secret', 'amazon_refresh_token', 'authorization_mode'})
                for field in ('cargo_type','amazon_region','amazon_seller_id','amazon_marketplace_ids','amazon_client_id','live_returns'):
                    if field not in body.model_fields_set and field in previous:
                        values[field] = previous[field]
                if body.client_id is None:
                    values['client_id'] = previous.get('client_id')
                for name in ('access_token', 'client_secret', 'webhook_secret', 'amazon_client_secret', 'amazon_refresh_token'):
                    supplied = getattr(body, name)
                    values[name] = supplied.get_secret_value() if supplied and supplied.get_secret_value().strip() else previous.get(name)
                if body.authorization_mode == 'TOKEN':
                    values['client_id'] = values['client_secret'] = None
                elif body.authorization_mode == 'CLIENT_CREDENTIALS':
                    values['access_token'] = None
                if not values['webhook_secret']:
                    if store['platform'] in {'WOOCOMMERCE','AMAZON'}:
                        raise HTTPException(422, 'Save the same signing secret or AWS API-destination key configured at the platform')
                    values['webhook_secret'] = secrets.token_urlsafe(32)
                try:
                    config = StoreConnector.model_validate({**values, 'tenant_id': context.tenant_id,
                        'auth_user_id': context.user_id, 'platform': store['platform'], 'live_delivery': previous.get('live_delivery', False)})
                except ValueError:
                    raise HTTPException(422, 'Use a canonical Shopify hostname and valid token or app credentials. Supply positive SKU weights in grams. WooCommerce uses signed webhooks. Amazon requires seller app credentials, marketplaces and an AWS destination key.') from None
                key_id = sorted(service.credential_keys)[0]
                key = service.credential_keys[key_id].get_secret_value().encode()
                envelope = config.model_dump(mode='json')
                for name in ('webhook_secret', 'access_token', 'client_secret', 'amazon_client_secret', 'amazon_refresh_token'):
                    secret = getattr(config, name)
                    envelope[name] = secret.get_secret_value() if secret else None
                envelope['store_id'] = str(store_id)
                cipher = Fernet(key).encrypt(json.dumps(envelope).encode())
                await connection.execute('''INSERT INTO public.workspace_store_connections(tenant_id,store_id,credentials_ciphertext,credential_key_id,updated_by)
                    VALUES($1,$2,$3,$4,$5) ON CONFLICT(tenant_id,store_id) DO UPDATE SET
                    credentials_ciphertext=excluded.credentials_ciphertext,credential_key_id=excluded.credential_key_id,
                    updated_by=excluded.updated_by,updated_at=now()''', context.tenant_id, store_id, cipher, key_id, context.user_id)
        return public_settings(config)

    @router.get('/{store_id}/notifications')
    async def notifications(store_id: UUID, request: Request, context: Any = Depends(authenticate)):
        await scoped_store(request, context, store_id)
        async with request.app.state.ecommerce.pool.acquire() as connection:
            rows = await connection.fetch('''SELECT id,order_id,status,attempts,last_error_code,created_at
                FROM public.amazon_order_notifications WHERE tenant_id=$1 AND store_id=$2
                ORDER BY created_at DESC LIMIT 100''', context.tenant_id, store_id)
        return {'notifications': [dict(row) for row in rows]}

    @router.post('/{store_id}/notifications/{notification_id}/retry')
    async def retry(store_id: UUID, notification_id: UUID, request: Request, context: Any = Depends(authenticate)):
        store = await scoped_store(request, context, store_id)
        if not store['is_active']:
            raise HTTPException(409, 'Enable the store before retrying its notification')
        async with request.app.state.ecommerce.pool.acquire() as connection:
            row = await connection.fetchrow('''UPDATE public.amazon_order_notifications SET status='RECEIVED',
                attempts=0,next_attempt_at=now(),last_error_code=NULL WHERE tenant_id=$1 AND store_id=$2 AND id=$3
                AND status='REVIEW_REQUIRED' RETURNING id''', context.tenant_id, store_id, notification_id)
        if row is None:
            raise HTTPException(409, 'Only a notification requiring review can be retried')
        return {'id': str(row['id']), 'status': 'RECEIVED'}

    return router
