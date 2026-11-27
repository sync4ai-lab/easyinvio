"""Buyer routing on the existing durable SHIPMENT delivery queue."""
from __future__ import annotations
import json
from typing import Any
from urllib.parse import urlencode,urlsplit
from uuid import UUID
from backend.post_purchase import obj, contact_digest, BuyerPolicy, branding

CATEGORIES={'IN_TRANSIT','OUT_FOR_DELIVERY','AVAILABLE_FOR_PICKUP','DELIVERED','EXCEPTION'}

async def stage_recipient_notifications(c: Any,tenant_id: UUID,shipment_id: UUID,category: str) -> None:
    if category not in CATEGORIES:return
    if not await c.fetchval("SELECT to_regclass('public.shipment_recipient_preferences') IS NOT NULL"):return
    row=await c.fetchrow('''SELECT s.recipient_address,s.status::text AS status,s.booked_at,p.email,p.whatsapp,p.contact_sha256,
        st.buyer_notification_policy,t.is_sandbox FROM public.shipments s
        JOIN public.tenants t ON t.tenant_id=s.tenant_id AND t.workspace_status='ACTIVE'
        JOIN public.ecommerce_stores st ON st.tenant_id=s.tenant_id AND st.id=s.ecommerce_store_id AND st.is_active
        JOIN public.shipment_recipient_preferences p ON p.tenant_id=s.tenant_id AND p.shipment_id=s.id
        WHERE s.tenant_id=$1 AND s.id=$2''',tenant_id,shipment_id)
    if not row or not row['booked_at'] or row['contact_sha256']!=contact_digest(row):return
    if category=='DELIVERED' and row['status']!='DELIVERED':return
    try:policy=BuyerPolicy.model_validate(obj(row['buyer_notification_policy']))
    except ValueError:return
    if category not in policy.categories:return
    for channel,enabled in [('EMAIL',policy.email and row['email']),('WHATSAPP',policy.whatsapp and row['whatsapp'])]:
        if enabled:
            await c.execute('''INSERT INTO public.shipment_sender_notifications(tenant_id,shipment_id,category,channel,environment,audience,state)
                VALUES($1,$2,$3,$4,$5,'RECIPIENT','BUYER_READY') ON CONFLICT(tenant_id,shipment_id,category,channel,audience) DO NOTHING''',
                tenant_id,shipment_id,category,channel,'TEST' if row['is_sandbox'] else 'LIVE')

async def prepare_recipient(c: Any,row: dict[str,Any],config: Any,settings: Any) -> tuple[str | None,str | None]:
    if not getattr(config,'shipment_recipient_notifications_enabled',False):return None,'BUYER_CHANNELS_DISABLED'
    try:tracking_origin(settings)
    except ValueError:return None,'TRACKING_ORIGIN_REQUIRED'
    current=await c.fetchrow('''SELECT p.*,st.buyer_notification_policy,st.brand_display_name,st.display_name,
        t.workspace_status FROM public.shipment_recipient_preferences p
        JOIN public.shipments s ON s.tenant_id=p.tenant_id AND s.id=p.shipment_id
        JOIN public.tenants t ON t.tenant_id=s.tenant_id
        JOIN public.ecommerce_stores st ON st.tenant_id=s.tenant_id AND st.id=s.ecommerce_store_id AND st.is_active
        WHERE p.tenant_id=$1 AND p.shipment_id=$2''',row['tenant_id'],row['shipment_id'])
    if not current or current['workspace_status']!='ACTIVE' or current['contact_sha256']!=contact_digest(row):return None,'RECIPIENT_PERMISSION_MISSING'
    try:policy=BuyerPolicy.model_validate(obj(current['buyer_notification_policy']))
    except ValueError:return None,'BUYER_POLICY_INVALID'
    key=row['channel'].lower()
    if not current[key] or not getattr(policy,key) or row['category'] not in policy.categories:return None,'RECIPIENT_OPTED_OUT'
    address=obj(row['recipient_address'])
    # Reuse all sender-worker provider/template/recipient safeguards, with explicit
    # verified buyer permission and the original stored recipient contact.
    from backend.shipment_notifications import target_for
    synthetic={**row,'sender_address':address,'logistics_metadata':{'automation_order':{'sender_notifications':{'email':True,'whatsapp':True,'whatsapp_permission_confirmed':True}}}}
    row['buyer_brand_name']=branding(current)['display_name']
    return target_for(synthetic,config,settings)

def tracking_origin(settings: Any) -> str:
    url=urlsplit(getattr(settings,'booking_page_url',''))
    if url.scheme not in {'http','https'} or not url.netloc or url.username or url.password:raise ValueError('Configured booking origin required')
    if url.scheme!='https' and url.hostname not in {'localhost','127.0.0.1'}:raise ValueError('HTTPS tracking origin required')
    return f'{url.scheme}://{url.netloc}'

def recipient_content(row: Any,settings: Any,messages: dict[str,str]) -> tuple[str,str]:
    origin=tracking_origin(settings)
    reference=row.get('tracking_number') or str(row['shipment_id'])
    link=origin+'/track?'+urlencode({'q':reference})
    brand=row.get('buyer_brand_name') or 'EasyInvio'
    heading=('[UAT TEST] ' if settings.provider_environment=='TEST' else '')+brand+' · '+row['category'].replace('_',' ').title()
    return heading,f"{brand}: {messages[row['category']]} Track your parcel: {link}"
