"""Execute only the bounded return authority explicitly granted by a merchant."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from typing import TYPE_CHECKING, Callable
from asyncpg import Record
from fastapi import HTTPException
from backend.agents.conversation_context import ConsumerDraft
from backend.dispatch_workspace import decoded
if TYPE_CHECKING:
    from backend.whatsapp_consumer import ConsumerCX
    from backend.whatsapp_queue import OutboundPart


async def authority(service: ConsumerCX, draft: ConsumerDraft) -> tuple[Record, Record]:
    await service.scope(draft)
    async with service.pool.acquire() as c:
        policy=await c.fetchrow('''SELECT p.*,u.role FROM public.whatsapp_consumer_return_policies p
          JOIN public.users u ON u.tenant_id=p.tenant_id AND u.auth_user_id=p.authorized_by
          JOIN public.tenants t ON t.tenant_id=p.tenant_id
          WHERE p.tenant_id=$1 AND p.enabled AND u.is_active AND u.role IN ('OWNER','ADMIN')
            AND t.workspace_status='ACTIVE' ''',draft.tenant_id)
        row=await c.fetchrow('''SELECT s.*,(SELECT max(e.occurred_at) FROM public.tracking_events e
          WHERE e.tenant_id=s.tenant_id AND e.shipment_id=s.id AND e.status='DELIVERED') AS delivered_at
          FROM public.shipments s WHERE s.tenant_id=$1 AND s.id=$2''',draft.tenant_id,draft.shipment_id)
    if not policy or not row:
        raise HTTPException(409,'The retailer must review this return; automatic returns have not been authorized.')
    if (row['status']!='DELIVERED' or not row['delivered_at'] or row['delivered_at']>datetime.now(timezone.utc)
            or row['delivered_at']<datetime.now(timezone.utc)-timedelta(days=policy['window_days'])):
        raise HTTPException(409,'The parcel is not within the retailer’s recorded delivery/return window.')
    if (row.get('parcel_count') or 1)!=1:
        raise HTTPException(409,'Grouped parcels need separately measured return packaging and retailer review.')
    order=decoded(row['logistics_metadata']).get('automation_order') or {}
    if (order.get('destination',{}).get('phone')!=draft.sender_e164
            or order.get('destination',{}).get('country_code')!='GB'
            or order.get('origin',{}).get('country_code')!='GB' or row['currency']!='GBP'):
        raise HTTPException(409,'Recipient verification or international/customs review is required by the retailer.')
    if order.get('origin',{}).get('country_code') not in policy.get('allowed_countries',['GB']) or order.get('destination',{}).get('country_code') not in policy.get('allowed_countries',['GB']):
        raise HTTPException(409,'This route is outside the merchant return policy')
    return policy,row


async def execute_return(service: ConsumerCX, draft: ConsumerDraft, request_id: UUID, ticket_id: UUID,
                         reply_parts: Callable[..., list[OutboundPart]], message_xml: Callable[[str], str]) -> list[OutboundPart]:
    from main import TenantContext
    from backend.return_review import ReturnReviewService, ReviewRequest, ReturnEdits, ReturnDelivery, SelectReturn, ordered_rates
    from backend.return_documents import public_return_links
    from backend.logistics_media import publish_return_media
    from backend.return_delivery import signed_document
    try:
        policy,_=await authority(service,draft)
        # This is the named merchant policy author, not the consumer. Revalidate
        # authority before selection; downstream finance rechecks membership too.
        actor=TenantContext(draft.tenant_id,policy['authorized_by'],policy['role'],'')
        from backend.entitlements import guard_feature
        await guard_feature(service.pool,service.settings,draft.tenant_id,'paperless_qr_returns')
        review=ReturnReviewService(service.state.partner_lifecycle)
        facts=await review.context(actor,draft.shipment_id)
        if facts['destination']['country_code']!='GB':
            raise HTTPException(409,'An international return warehouse requires retailer customs review.')
        body=ReviewRequest(request_id=request_id,shipment_id=draft.shipment_id,
            charge_bearer=policy['charge_bearer'],paperless_requested=policy.get('paperless_preferred',True),edits=ReturnEdits.model_validate(facts['edits']),
            delivery=ReturnDelivery(whatsapp=True,customer_permission_confirmed=True))
        prepared=await review.prepare(actor,body)
        rates=ordered_rates(prepared.get('rates',[]))
        if (prepared.get('partial') or not rates or rates[0]['currency']!='GBP'
                or Decimal(str(rates[0]['client_price_ex_tax']))>Decimal(str(policy['maximum_price_gbp']))):
            raise HTTPException(409,'Return rates need retailer review or exceed the authorized postage cap; nothing has been purchased.')
        current,_=await authority(service,draft)
        if current['version']!=policy['version']:
            raise HTTPException(409,'The retailer return policy changed. Ask the retailer to review this request.')
        await guard_feature(service.pool,service.settings,draft.tenant_id,'paperless_qr_returns')
        result=await review.select(actor,request_id,SelectReturn(offer_id=UUID(rates[0]['offer_id'])),expected_policy_version=policy['version'])
        if result['status']=='PAYMENT_REQUIRED':
            from backend.payment_gateway import safe_checkout_url
            url=safe_checkout_url(result['checkout_url'])
            return reply_parts(message_xml(f'Return case {ticket_id}. Confirm the return price on secure Stripe checkout: {url}\nNo return label is available until payment and carrier confirmation. We will send its document notice through the configured WhatsApp channel.'))
        if result['status']!='BOOKED':
            raise HTTPException(409,'Return confirmation needs review. Do not pay or book again.')
        result=public_return_links(service.settings,actor,dict(result,paperless_available=bool(result.get('qr_path'))))
        result=await publish_return_media(service.state.partner_lifecycle,actor,result)
        from backend.whatsapp_queue import return_media,return_image
        view=return_media(dict(action_taken='TRIGGER_RETURN',return_request=result),service.settings)
        fallback=view or signed_document(service.state.partner_lifecycle,draft.tenant_id,request_id)
        text=f'Return case {ticket_id}. '+('Use this carrier-issued paperless document at supported drop-off points.' if view else 'This service requires a printed label unless the carrier document states otherwise.')+'\n'+fallback
        image=return_image({'return_request':result},service.settings,draft.tenant_id) if view else None
        if image:
            return reply_parts(message_xml(text),image,fallback_view_url=fallback)
        # Never attach an extensionless browser endpoint as a pretend image/PDF.
        return reply_parts(message_xml(text))
    except HTTPException as error:
        if error.status_code>=500:
            raise
        detail=error.detail if isinstance(error.detail,str) else 'The retailer must review this return.'
        return reply_parts(message_xml(f'Return case {ticket_id}: {detail} Check the existing request with your retailer before trying again.'))
