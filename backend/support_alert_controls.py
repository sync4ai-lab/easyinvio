"""Platform delivery controls separate from the recipient's verified consent."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


class AlertPause(BaseModel):
    model_config = ConfigDict(extra='forbid')
    paused: bool = Field(strict=True)


def build_router(authenticate_platform_owner):
    router = APIRouter(prefix='/api/v1/admin/support/whatsapp', tags=['Notification operations'])

    @router.get('/bindings')
    async def bindings(request: Request, owner=Depends(authenticate_platform_owner)):
        service = request.app.state.support_delivery
        configured = bool(service.settings.twilio_enabled and service.delivery.support_whatsapp_enabled)
        async with request.app.state.finance.pool.acquire() as connection:
            ready = await connection.fetchval("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='whatsapp_bindings' AND column_name='alerts_paused')")
            rows = await connection.fetch('''SELECT b.id,b.tenant_id,t.company_name,t.is_sandbox,
                right(b.sender_e164,4) AS number_suffix,b.is_active,b.notification_opt_in,
                b.verified_at IS NOT NULL AS verified,
                coalesce((to_jsonb(b)->>'alerts_paused')::boolean,false) AS alerts_paused
                FROM public.whatsapp_bindings b JOIN public.tenants t ON t.tenant_id=b.tenant_id
                ORDER BY t.company_name,b.id LIMIT 500''')
        return {'configured': configured, 'controls_ready': ready,
                'setup': 'Delivery requires a verified phone binding, recipient opt-in, Twilio sender, approved template or active messaging window, and public HTTPS callbacks. Internal processing failures never trigger merchant alerts.',
                'bindings': [{**dict(row), 'id': str(row['id']), 'tenant_id': str(row['tenant_id'])} for row in rows]}

    @router.patch('/bindings/{binding_id}')
    async def pause(binding_id: UUID, body: AlertPause, request: Request, owner=Depends(authenticate_platform_owner)):
        async with request.app.state.finance.pool.acquire() as connection:
            if not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='whatsapp_bindings' AND column_name='alerts_paused')"):
                raise HTTPException(503, 'Apply migration 034 to enable administrative alert controls')
            async with connection.transaction():
                row = await connection.fetchrow('SELECT id,is_active,notification_opt_in,verified_at FROM public.whatsapp_bindings WHERE id=$1 FOR UPDATE', binding_id)
                if row is None:
                    raise HTTPException(404, 'Verified phone binding not found')
                if not body.paused and (not row['is_active'] or not row['notification_opt_in'] or not row['verified_at']):
                    raise HTTPException(409, 'Resume requires an active verified binding and the recipient’s opt-in. Administrators cannot grant consent for a recipient.')
                await connection.execute('UPDATE public.whatsapp_bindings SET alerts_paused=$2 WHERE id=$1', binding_id, body.paused)
        return {'id': str(binding_id), 'alerts_paused': body.paused, 'message_sent': False}

    return router
