"""Payment-gated customer return documents and durable transactional notices."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlencode, urljoin, urlsplit
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict
from backend.email_delivery import EmailDeliverySettings, email_configured, send_notification_email

from backend.dispatch_workspace import decoded


class ReturnDeliverySettings(EmailDeliverySettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', hide_input_in_errors=True)
    return_email_enabled: bool = False
    return_sendgrid_api_key: SecretStr = SecretStr('')
    return_email_from: str = 'support@easyinvio.com'
    return_whatsapp_enabled: bool = False
    return_whatsapp_content_sid: str = ''
    return_whatsapp_messaging_service_sid: str = ''


def configuration(lifecycle) -> ReturnDeliverySettings:
    return getattr(lifecycle, 'return_delivery_settings', None) or ReturnDeliverySettings()


def document_base(lifecycle) -> tuple[str, str]:
    settings = lifecycle.automation.settings
    secret = getattr(settings, 'quote_link_secret', SecretStr('')).get_secret_value()
    base = getattr(settings, 'booking_page_url', '')
    url = urlsplit(base)
    if len(secret) < 32 or url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise HTTPException(503, 'Customer return documents require an HTTPS BOOKING_PAGE_URL and a QUOTE_LINK_SECRET of at least 32 characters')
    return base, secret


def delivery_capabilities(lifecycle) -> dict:
    config = configuration(lifecycle)
    settings = lifecycle.automation.settings
    try:
        document_base(lifecycle)
        documents = True
    except HTTPException:
        documents = False
    return {'email': documents and config.return_email_enabled and email_configured(config,config.return_email_from,config.return_sendgrid_api_key)
            and bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', config.return_email_from)),
            'whatsapp': documents and config.return_whatsapp_enabled and bool(getattr(settings, 'twilio_enabled', False))
            and bool(re.fullmatch(r'HX[0-9a-fA-F]{32}', config.return_whatsapp_content_sid))
            and bool(re.fullmatch(r'MG[0-9a-fA-F]{32}', config.return_whatsapp_messaging_service_sid)),
            'notice': 'Customer notifications use the configured email server and approved Twilio templates. Provider acceptance is not proof of delivery.'}


def validate_delivery(lifecycle, preferences, customer: dict) -> None:
    available = delivery_capabilities(lifecycle)
    if (preferences.email or preferences.whatsapp) and not preferences.customer_permission_confirmed:
        raise HTTPException(422, 'Confirm customer permission to receive return instructions')
    for channel in ('email', 'whatsapp'):
        if getattr(preferences, channel) and not available[channel]:
            raise HTTPException(409, f'Customer {channel} delivery is not configured. Disable this notification or configure the channel.')
    if preferences.email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', customer.get('email') or ''):
        raise HTTPException(422, 'The original customer has no valid email address')
    if preferences.whatsapp and not re.fullmatch(r'\+[1-9][0-9]{7,14}', customer.get('phone') or ''):
        raise HTTPException(422, 'The original customer has no valid international phone number')


async def label_ready(c, tenant_id, row) -> bool:
    if not row['return_shipment_id'] or not row['selected_offer_id']:
        return False
    if row['charge_bearer'] == 'CUSTOMER_PAY':
        paid = await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2 AND status='CREDITED')", tenant_id, row['id'])
        if not paid:
            return False
    return bool(await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.shipments WHERE tenant_id=$1 AND id=$2
        AND status IN ('BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED')
        AND booked_at IS NOT NULL AND tracking_number IS NOT NULL
        AND pricing_snapshot->'selected_rate'->>'offer_id'=$3
        AND logistics_metadata->'automation_label'->>'label_url' IS NOT NULL)''', tenant_id, row['return_shipment_id'], str(row['selected_offer_id'])))


def signed_document(lifecycle, tenant_id, request_id, document='label') -> str:
    base, secret = document_base(lifecycle)
    now = datetime.now(timezone.utc)
    token = jwt.encode({'iss': 'easyinvio-return-delivery', 'aud': 'customer-return-document',
        't': str(tenant_id), 'r': str(request_id), 'd': document,
        'iat': int(now.timestamp()), 'exp': int((now + timedelta(hours=24)).timestamp())}, secret, algorithm='HS256')
    return urljoin(base, '/api/v1/shipping/returns/customer-document') + '?' + urlencode({'token': token})


async def customer_document(lifecycle, token: str):
    _, secret = document_base(lifecycle)
    try:
        if len(token) > 2000:
            raise ValueError()
        claim = jwt.decode(token, secret, algorithms=['HS256'], issuer='easyinvio-return-delivery',
            audience='customer-return-document', options={'require': ['t','r','d','iat','exp']})
        if claim['d'] not in {'label', 'return-qr'} or not 0 < claim['exp']-claim['iat'] <= 86400:
            raise ValueError()
        tenant_id, request_id = UUID(claim['t']), UUID(claim['r'])
    except (ValueError, TypeError, KeyError, jwt.PyJWTError):
        raise HTTPException(401, 'Invalid or expired return document link') from None
    async with lifecycle.pool.acquire() as c:
        row = await c.fetchrow('SELECT * FROM public.return_review_sessions WHERE tenant_id=$1 AND id=$2', tenant_id, request_id)
        if not row or not await label_ready(c, tenant_id, row):
            raise HTTPException(409, 'The return label is unavailable until payment and carrier confirmation are recorded')
    from backend.automation_three_partners import carrier_document
    response = await carrier_document(row['return_shipment_id'], claim['d'], lifecycle,
        SimpleNamespace(tenant_id=tenant_id, role='DISPATCHER'))
    response.headers.update({'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})
    return response


async def stage_notices(lifecycle, tenant_id, request_id, kind: str) -> None:
    async with lifecycle.pool.acquire() as c:
        row = await c.fetchrow('SELECT * FROM public.return_review_sessions WHERE tenant_id=$1 AND id=$2', tenant_id, request_id)
        if not row:
            return
        if kind == 'LABEL' and not await label_ready(c, tenant_id, row):
            return
        if kind == 'PAYMENT' and row['state'] != 'PAYMENT_REQUIRED':
            return
        prefs = decoded(row['delivery'])
        if not prefs.get('customer_permission_confirmed'):
            return
        for channel in ('EMAIL', 'WHATSAPP'):
            if prefs.get(channel.lower()):
                await c.execute('''INSERT INTO public.return_customer_deliveries(tenant_id,review_id,kind,channel)
                    VALUES($1,$2,$3,$4) ON CONFLICT(tenant_id,review_id,kind,channel) DO NOTHING''', tenant_id, request_id, kind, channel)


class ReturnDeliveryWorker:
    def __init__(self, lifecycle):
        self.lifecycle = lifecycle

    async def drain(self) -> bool:
        service = self.lifecycle
        config = configuration(service)
        async with service.pool.acquire() as c:
            async with c.transaction():
                notice = await c.fetchrow('''SELECT d.* FROM public.return_customer_deliveries d
                    JOIN public.return_review_sessions r ON r.tenant_id=d.tenant_id AND r.id=d.review_id
                    JOIN public.tenants t ON t.tenant_id=r.tenant_id AND t.workspace_status='ACTIVE'
                    JOIN public.users u ON u.tenant_id=r.tenant_id AND u.auth_user_id=r.requested_by
                      AND u.is_active AND u.role IN ('OWNER','ADMIN','DISPATCHER')
                    WHERE d.state='READY' ORDER BY d.id LIMIT 1 FOR UPDATE OF d SKIP LOCKED''')
                if not notice:
                    return False
                row = await c.fetchrow('SELECT * FROM public.return_review_sessions WHERE tenant_id=$1 AND id=$2', notice['tenant_id'], notice['review_id'])
                if notice['kind'] == 'LABEL' and not await label_ready(c, notice['tenant_id'], row):
                    await c.execute("UPDATE public.return_customer_deliveries SET state='FAILED',error_code='LABEL_NOT_AVAILABLE',updated_at=now() WHERE id=$1", notice['id'])
                    return True
                parent = await c.fetchrow('SELECT logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2', notice['tenant_id'], row['original_shipment_id'])
                customer = decoded(parent['logistics_metadata'])['automation_order']['destination']
                prefs = decoded(row['delivery'])
                if not prefs.get('customer_permission_confirmed') or not prefs.get(notice['channel'].lower()):
                    raise ValueError('Missing return delivery permission')
                available = delivery_capabilities(service)[notice['channel'].lower()]
                if not available:
                    await c.execute("UPDATE public.return_customer_deliveries SET state='FAILED',error_code='CHANNEL_DISABLED',updated_at=now() WHERE id=$1", notice['id'])
                    return True
                # Fence *before* network I/O. Interrupted/ambiguous requests cannot resend.
                await c.execute("UPDATE public.return_customer_deliveries SET state='SENDING',updated_at=now() WHERE id=$1", notice['id'])
        try:
            payment = notice['kind'] == 'PAYMENT'
            if payment:
                # A delayed payment notice must not advertise a stale checkout after
                # successful payment; the separately staged label notice owns delivery.
                async with service.pool.acquire() as c:
                    paid = await label_ready(c, notice['tenant_id'], row)
                if paid:
                    raise ValueError('PAYMENT_ALREADY_COMPLETED')
                from backend.payment_gateway import safe_checkout_url
                link = safe_checkout_url(decoded(row['response'])['checkout_url'])
                heading = 'Pay for your return'
                text = 'Choose secure card payment to complete your return. Your label will be available only after verified payment and carrier confirmation.'
            else:
                link = signed_document(service, notice['tenant_id'], row['id'])
                heading = 'Your return label is ready'
                text = 'Download the carrier label and follow the selected carrier instructions. Use a printer unless a carrier-issued paperless code is available.'
                async with service.pool.acquire() as c:
                    child = await c.fetchrow('SELECT logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2', notice['tenant_id'], row['return_shipment_id'])
                label = decoded(child['logistics_metadata']).get('automation_label') or {}
                if any(label.get(key) for key in ('return_dropoff_qr_code_url','return_dropoff_qr_code_base64','return_dropoff_qr_code_svg')):
                    text += ' Paperless code (participating locations for this carrier only): ' + signed_document(service, notice['tenant_id'], row['id'], 'return-qr')
                text += ' Document links expire in 24 hours.'
            outcome = decoded(row['response'])
            order = decoded(parent['logistics_metadata']).get('automation_order') or {}
            details = 'Return for ' + str(order.get('order_reference') or row['original_shipment_id'])
            details += '. Service: ' + str(outcome.get('carrier_code') or '') + ' ' + str(outcome.get('service_code') or '')
            details += '. Price: ' + str(outcome.get('amount') or '') + ' ' + str(outcome.get('currency') or '') + '.'
            text = details + ' ' + text
            content = heading + '. ' + text + '\n' + link
            if notice['channel'] == 'EMAIL':
                html_body = '<!doctype html><html><body><main style="max-width:600px;margin:auto;font:16px/1.6 sans-serif;padding:24px"><h1>' + html.escape(heading) + '</h1><p>' + html.escape(text) + '</p><p><a href="' + html.escape(link, quote=True) + '">' + html.escape(heading) + '</a></p><p>EasyInvio Operations</p></main></body></html>'
                receipt = await send_notification_email(service.client,config,
                    sender=config.return_email_from,recipient=customer['email'],subject=heading,text=content,
                    html_body=html_body,message_key='return:'+str(notice['tenant_id'])+':'+str(notice['id']),
                    api_key=config.return_sendgrid_api_key)
                state = 'FAILED' if receipt.state=='RETRYABLE' else receipt.state
                reference, error_code = receipt.reference, receipt.error_code
            else:
                settings = service.automation.settings
                response = await service.client.post(f'https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json',
                    auth=httpx.BasicAuth(settings.twilio_account_sid, settings.twilio_auth_token.get_secret_value()),
                    data={'From': 'whatsapp:' + settings.twilio_whatsapp_number, 'To': 'whatsapp:' + customer['phone'],
                          'MessagingServiceSid': config.return_whatsapp_messaging_service_sid,
                          'ContentSid': config.return_whatsapp_content_sid,
                          'ContentVariables': json.dumps({'1': heading, '2': text, '3': link})}, timeout=15, follow_redirects=False)
                accepted = response.status_code == 201
                reference = response.json().get('sid') if accepted else None
                if accepted and not re.fullmatch(r'SM[0-9a-fA-F]{32}', reference or ''):
                    raise ValueError('Invalid provider receipt')
                state = 'ACCEPTED' if accepted else 'FAILED' if 400 <= response.status_code < 500 else 'REVIEW_REQUIRED'
                error_code = None if accepted else 'PROVIDER_REJECTED' if state == 'FAILED' else 'PROVIDER_OUTCOME_UNCERTAIN'
            async with service.pool.acquire() as c:
                await c.execute('''UPDATE public.return_customer_deliveries SET state=$2,provider_reference=$3,
                    error_code=$4,updated_at=now() WHERE id=$1 AND state='SENDING' ''', notice['id'], state, reference,
                    error_code)
        except Exception:
            async with service.pool.acquire() as c:
                await c.execute("UPDATE public.return_customer_deliveries SET state='REVIEW_REQUIRED',error_code='SEND_OUTCOME_UNCERTAIN',updated_at=now() WHERE id=$1 AND state='SENDING'", notice['id'])
        return True

    async def worker(self) -> None:
        while True:
            try:
                # Reconciliation reads existing child outcomes; it never purchases a
                # label. The existing card worker is solely responsible for payment.
                async with self.lifecycle.pool.acquire() as c:
                    await c.execute("UPDATE public.return_customer_deliveries SET state='REVIEW_REQUIRED',error_code='SEND_INTERRUPTED',updated_at=now() WHERE state='SENDING' AND updated_at<now()-interval '2 minutes'")
                    rows = await c.fetch('''SELECT r.tenant_id,r.id,r.requested_by FROM public.return_review_sessions r
                        WHERE state IN ('PROCESSING','PAYMENT_REQUIRED') OR (state='REVIEW_REQUIRED' AND EXISTS(
                          SELECT 1 FROM public.shipments s WHERE s.tenant_id=r.tenant_id AND s.id=r.return_shipment_id
                          AND s.status IN ('BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED')))
                        ORDER BY r.updated_at LIMIT 20''')
                from backend.return_review import ReturnReviewService
                for row in rows:
                    await ReturnReviewService(self.lifecycle).status(SimpleNamespace(
                        tenant_id=row['tenant_id'], user_id=row['requested_by'], role='DISPATCHER'), row['id'])
                    async with self.lifecycle.pool.acquire() as c:
                        await c.execute("UPDATE public.return_review_sessions SET updated_at=now() WHERE tenant_id=$1 AND id=$2 AND state IN ('PROCESSING','PAYMENT_REQUIRED')", row['tenant_id'], row['id'])
                if await self.drain():
                    continue
            except Exception:
                logging.getLogger(__name__).warning('Return delivery deferred; durable receipts retained. Check migration 046 and delivery configuration.')
            await asyncio.sleep(3)
