"""Signed normalized return commands from merchant and marketplace gateways.

Native refunds are deliberately not label-purchase commands. A merchant backend
must explicitly submit the reviewed full-parcel return and its charge bearer.
"""
import hashlib
import hmac
import time
from types import SimpleNamespace
from uuid import UUID

from fastapi import HTTPException
from pydantic import TypeAdapter

from backend.ecommerce_connectors import single_header
from backend.reverse_logistics import ReturnCommand


async def receive_return_webhook(request, store_id: UUID):
    ecommerce = request.app.state.ecommerce
    from backend.store_connections import resolve_connector
    config = await resolve_connector(ecommerce, store_id)
    if config is None or not config.live_returns:
        raise HTTPException(403, 'Return automation is not enabled for this storefront')
    if request.headers.get('content-type','').split(';')[0].lower() != 'application/json':
        raise HTTPException(415, 'Use application/json')
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 262144:
            raise HTTPException(413, 'Return commands are limited to 256 KB')
    timestamp = single_header(request, 'x-easyinvio-timestamp')
    signature = single_header(request, 'x-easyinvio-return-signature')
    try:
        if not timestamp.isdigit() or abs(time.time()-int(timestamp)) > 300:
            raise ValueError()
    except ValueError:
        raise HTTPException(401, 'Expired return signature') from None
    expected = hmac.new(config.webhook_secret.get_secret_value().encode(),
        timestamp.encode()+b'.'+str(store_id).encode()+b'.'+raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, 'Invalid return signature')
    try:
        commands = TypeAdapter(list[ReturnCommand]).validate_json(raw)
    except ValueError:
        raise HTTPException(422, 'Invalid return command array') from None
    # Resolve an actual active member, rather than inventing a privileged role
    # from possession of a store secret. Every original shipment is store-bound.
    async with ecommerce.pool.acquire() as connection:
        member = await connection.fetchrow('''SELECT u.role FROM public.users u
            JOIN public.tenants t ON t.tenant_id=u.tenant_id
            JOIN public.ecommerce_stores s ON s.tenant_id=u.tenant_id AND s.id=$3 AND s.is_active
            WHERE u.tenant_id=$1 AND u.auth_user_id=$2 AND u.is_active
            AND t.workspace_status='ACTIVE' AND t.billing_status='ACTIVE' ''',
            config.tenant_id, config.auth_user_id, store_id)
    if member is None or member['role'] not in {'OWNER','ADMIN','DISPATCHER'}:
        raise HTTPException(403, 'Store return operator must be an active dispatch member')
    context = SimpleNamespace(tenant_id=config.tenant_id,user_id=config.auth_user_id,
        role=member['role'],bearer_token='',assistance_session_id=None)
    return await ecommerce.prepare_returns(request.app.state.partner_lifecycle, context, store_id, commands,
        source='MARKETPLACE' if config.platform=='AMAZON' else 'STOREFRONT')
