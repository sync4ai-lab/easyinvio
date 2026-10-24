"""Durable sender milestone delivery. No carrier actions or financial mutations."""
from __future__ import annotations
import asyncio
import json
import logging
import re
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class SenderNotifications(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    email: bool = True
    whatsapp: bool = False
    whatsapp_permission_confirmed: bool = False

    @model_validator(mode='after')
    def permission(self):
        if self.whatsapp and not self.whatsapp_permission_confirmed:
            raise ValueError('Confirm sender permission for WhatsApp shipment updates')
        return self

class ShipmentNotificationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', hide_input_in_errors=True)
    shipment_email_notifications_enabled: bool = False
    shipment_sendgrid_api_key: SecretStr = SecretStr('')
    shipment_email_from: str = 'operations@easyinvio.com'
    shipment_whatsapp_notifications_enabled: bool = False
    shipment_whatsapp_content_sid: str = ''
    shipment_notification_test_recipients: list[str] = Field(default_factory=list, max_length=100)

MESSAGES = {
    'BOOKED': 'Your shipping label has been created. Carrier collection or drop-off has not yet been confirmed.',
    'MANIFESTED': 'Your parcel is on a dispatch manifest. This is handover preparation, not a carrier collection scan.',
    'DISPATCHED': 'Dispatch has been recorded. Carrier scans will confirm its journey.',
    'IN_TRANSIT': 'The carrier reports that your parcel is in transit.',
    'OUT_FOR_DELIVERY': 'The carrier reports that your parcel is out for delivery.',
    'AVAILABLE_FOR_PICKUP': 'The carrier reports that your parcel is available for pickup. Check carrier instructions for its location and deadline.',
    'DELIVERED': 'The carrier has reported delivery.',
    'EXCEPTION': 'The carrier has reported a delivery issue. Review tracking for information and any action required.',
    'RETURNED_TO_SENDER': 'The carrier reports that the parcel is being returned to the sender.',
    'CANCELLED': 'The shipment has been cancelled. Do not dispatch using its previous label.',
}

def decoded(value):
    try:
        value = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}

def notice_content(row, settings) -> tuple[str, str]:
    reference = row.get('customer_reference') or str(row['shipment_id'])
    test = settings.provider_environment == 'TEST'
    heading = ('[UAT TEST] ' if test else '') + 'EasyInvio ' + row['category'].replace('_', ' ').lower() + ': ' + reference
    text = f"Shipment {reference}. {MESSAGES[row['category']]} Tracking reference: {row.get('tracking_number') or 'Not yet assigned'}."
    if test:
        text += ' This is a TEST booking. Tracking references may be placeholders; test labels must not be used for dispatch.'
    return heading, text

def target_for(row, config, settings) -> tuple[str | None, str | None]:
    if row.get('environment', settings.provider_environment) != settings.provider_environment:
        return None, 'ENVIRONMENT_MISMATCH'
    order = decoded(decoded(row.get('logistics_metadata')).get('automation_order'))
    sender = decoded(row.get('sender_address')) | {key:value for key,value in decoded(order.get('origin')).items() if value is not None}
    preferences = decoded(order.get('sender_notifications'))
    if row['channel'] == 'EMAIL':
        if preferences.get('email') is False:
            return None, 'SENDER_OPTED_OUT'
        target = sender.get('email')
        if not config.shipment_email_notifications_enabled or not config.shipment_sendgrid_api_key.get_secret_value():
            return None, 'EMAIL_NOT_CONFIGURED'
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', target or ''):
            return None, 'SENDER_EMAIL_MISSING'
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', config.shipment_email_from):
            return None, 'EMAIL_FROM_INVALID'
    else:
        if not (preferences.get('whatsapp') is True and preferences.get('whatsapp_permission_confirmed') is True):
            return None, 'WHATSAPP_PERMISSION_MISSING'
        target = sender.get('phone')
        if not (config.shipment_whatsapp_notifications_enabled and getattr(settings, 'twilio_enabled', False)
                and re.fullmatch(r'HX[0-9a-fA-F]{32}', config.shipment_whatsapp_content_sid)
                and getattr(settings, 'twilio_account_sid', '') and settings.twilio_auth_token.get_secret_value()
                and re.fullmatch(r'\+[1-9][0-9]{7,14}', getattr(settings, 'twilio_whatsapp_number', ''))):
            return None, 'WHATSAPP_NOT_CONFIGURED'
        if not re.fullmatch(r'\+[1-9][0-9]{7,14}', target or ''):
            return None, 'SENDER_PHONE_MISSING'
    if settings.provider_environment == 'TEST' and target.casefold() not in {v.casefold() for v in config.shipment_notification_test_recipients}:
        return None, 'TEST_RECIPIENT_NOT_ALLOWED'
    return target, None

class ShipmentNotificationWorker:
    def __init__(self, lifecycle, config: ShipmentNotificationSettings):
        self.lifecycle, self.config = lifecycle, config

    async def drain(self) -> bool:
        service, config = self.lifecycle, self.config
        async with service.pool.acquire() as c:
            async with c.transaction():
                row = await c.fetchrow("""SELECT n.*,s.customer_reference,s.tracking_number,s.sender_address,s.logistics_metadata
                    FROM public.shipment_sender_notifications n JOIN public.shipments s
                    ON s.tenant_id=n.tenant_id AND s.id=n.shipment_id
                    WHERE n.state='READY' AND n.next_attempt_at<=now() AND n.attempts<3 AND NOT EXISTS(SELECT 1 FROM public.shipment_sender_notifications earlier
                      WHERE earlier.tenant_id=n.tenant_id AND earlier.shipment_id=n.shipment_id AND earlier.id<n.id AND earlier.state IN ('READY','SENDING'))
                    ORDER BY n.id LIMIT 1 FOR UPDATE OF n SKIP LOCKED""")
                if row is None:
                    return False
                row = dict(row)
                target, reason = target_for(row, config, service.automation.settings)
                if reason:
                    await c.execute("UPDATE public.shipment_sender_notifications SET state='SKIPPED',error_code=$2,updated_at=now() WHERE id=$1", row['id'], reason)
                    return True
                # Commit SENDING before external IO; ambiguous sends never replay.
                await c.execute("UPDATE public.shipment_sender_notifications SET state='SENDING',attempts=attempts+1,updated_at=now() WHERE id=$1", row['id'])
        heading, text = notice_content(row, service.automation.settings)
        try:
            if row['channel'] == 'EMAIL':
                response = await service.client.post('https://api.sendgrid.com/v3/mail/send',
                    headers={'Authorization':'Bearer '+config.shipment_sendgrid_api_key.get_secret_value()},
                    json={'personalizations':[{'to':[{'email':target}]}], 'from':{'email':config.shipment_email_from,'name':'EasyInvio'},
                          'subject':heading,'content':[{'type':'text/plain','value':text}],
                          'tracking_settings':{'click_tracking':{'enable':False,'enable_text':False}}}, timeout=15, follow_redirects=False)
                accepted = response.status_code == 202
                reference = response.headers.get('x-message-id', '')[:200] or None if accepted else None
            else:
                settings = service.automation.settings
                response = await service.client.post(f'https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json',
                    auth=httpx.BasicAuth(settings.twilio_account_sid, settings.twilio_auth_token.get_secret_value()),
                    data={'From':'whatsapp:'+settings.twilio_whatsapp_number,'To':'whatsapp:'+target,
                          'ContentSid':config.shipment_whatsapp_content_sid,
                          'ContentVariables':json.dumps({'1':str(row.get('customer_reference') or row['shipment_id']),
                                                        '2':text,'3':str(row.get('tracking_number') or 'Not yet assigned')})},
                    timeout=15, follow_redirects=False)
                accepted = response.status_code == 201
                reference = response.json().get('sid') if accepted else None
                if accepted and not re.fullmatch(r'SM[0-9a-fA-F]{32}', reference or ''):
                    raise ValueError('Invalid provider receipt')
            state = 'ACCEPTED' if accepted else 'FAILED' if 400 <= response.status_code < 500 else 'REVIEW_REQUIRED'
            reason = None if accepted else 'PROVIDER_REJECTED' if state == 'FAILED' else 'PROVIDER_OUTCOME_UNCERTAIN'
            if response.status_code == 429 and row['attempts'] + 1 < 3:
                state, reason = 'READY', 'PROVIDER_RATE_LIMITED'
            async with service.pool.acquire() as c:
                await c.execute("""UPDATE public.shipment_sender_notifications SET state=$2,provider_reference=$3,error_code=$4,updated_at=now(),
                    next_attempt_at=CASE WHEN $2='READY' THEN now()+interval '1 minute' ELSE next_attempt_at END
                    WHERE id=$1 AND state='SENDING'""", row['id'], state, reference, reason)
        except Exception:
            async with service.pool.acquire() as c:
                await c.execute("UPDATE public.shipment_sender_notifications SET state='REVIEW_REQUIRED',error_code='SEND_OUTCOME_UNCERTAIN',updated_at=now() WHERE id=$1 AND state='SENDING'",row['id'])
        return True

    async def worker(self):
        while True:
            try:
                async with self.lifecycle.pool.acquire() as c:
                    await c.execute("UPDATE public.shipment_sender_notifications SET state='REVIEW_REQUIRED',error_code='SEND_INTERRUPTED',updated_at=now() WHERE state='SENDING' AND updated_at<now()-interval '2 minutes'")
                if await self.drain():
                    continue
            except Exception:
                logging.getLogger(__name__).warning('Sender notification deferred; durable receipts retained')
            await asyncio.sleep(3)

def build_router(authenticate):
    router = APIRouter(tags=['Sender shipment notifications'])
    @router.get('/api/v1/shipping/{shipment_id}/sender-notifications')
    async def status(shipment_id: UUID, request: Request, user=Depends(authenticate)):
        async with request.app.state.finance.pool.acquire() as c:
            if not await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.shipments WHERE tenant_id=$1 AND id=$2)',user.tenant_id,shipment_id):
                raise HTTPException(404, 'Shipment not found')
            if not await c.fetchval("SELECT to_regclass('public.shipment_sender_notifications') IS NOT NULL"):
                return {'available':False,'items':[],'notice':'Sender notifications require migration 047 and delivery configuration.'}
            rows = await c.fetch('''SELECT category,channel,state,error_code,created_at,updated_at FROM public.shipment_sender_notifications
                WHERE tenant_id=$1 AND shipment_id=$2 ORDER BY id''', user.tenant_id, shipment_id)
        return {'available':True,'items':[dict(row) for row in rows],
                'notice':'ACCEPTED means provider acceptance; it is not proof of inbox or handset delivery.'}
    return router
