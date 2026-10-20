"""Durable WhatsApp ingress and REST delivery; no carrier work in the HTTP ack."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import NAMESPACE_URL, uuid5

import asyncpg
from cryptography.fernet import Fernet
from defusedxml.ElementTree import fromstring
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import FormData
from twilio.base.exceptions import TwilioRestException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

logger = logging.getLogger('easyinvio.whatsapp_queue')
if TYPE_CHECKING:
    from main import Settings


class OutboundPart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body: str = Field(min_length=1, max_length=1590)
    media_url: str | None = None


def inbound_digest(raw: bytes) -> str:
    """All signed field values/counts, independent of equivalent form field order."""
    fields = sorted(parse_qsl(raw.decode('utf-8'), keep_blank_values=True, max_num_fields=150))
    return hashlib.sha256(json.dumps(fields, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def reply_parts(xml: str, media_url: str | None = None) -> list[OutboundPart]:
    parts = [OutboundPart(body=node.text or '') for node in fromstring(xml).findall('Message')]
    if not parts or len(parts) > 32:
        raise ValueError('Invalid reply part count')
    if media_url:
        parts.append(OutboundPart(body='Your carrier return drop-off document. Use only the locations supported by this service.', media_url=media_url))
    return parts


def return_media(result: dict[str, Any], settings: Settings) -> str | None:
    data = result.get('return_request') or {}
    if (result.get('action_taken') != 'TRIGGER_RETURN' or data.get('status') != 'BOOKED'
            or not data.get('paperless_available') or data.get('qr_requires_workspace_login', True)):
        return None
    value = data.get('return_dropoff_qr_code_url', '')
    parsed = urlsplit(value)
    base = urlsplit(settings.booking_page_url or settings.auth_recovery_redirect_url)
    if (parsed.scheme != 'https' or parsed.netloc != base.netloc or parsed.username or parsed.password
            or parsed.path != '/api/v1/shipping/return-dropoff' or parsed.fragment):
        return None
    from backend.return_documents import verify_dropoff_token
    token = dict(parse_qsl(parsed.query)).get('token', '')
    try:
        _, shipment_id = verify_dropoff_token(settings, token)
    except HTTPException:
        return None
    if str(shipment_id) != str(data.get('shipment_id')):
        return None
    return value


async def process_inbound(request: Request, form: FormData, received_at: datetime | None = None) -> list[OutboundPart]:
    """Re-resolve membership at execution; never trust queued caller-supplied IDs."""
    from backend.whatsapp_onboarding import onboarding_manager
    from backend.agents.conversational_gateway import ConversationalActionGateway, ConversationMessage, message_xml
    state = request.app.state
    signup = await onboarding_manager(request)
    if signup is not None:
        cached = await signup.replay(form)
        if cached is not None:
            return reply_parts(cached)
    sender, receiver = (form[name].removeprefix('whatsapp:') for name in ('From', 'To'))
    context = await state.whatsapp.resolve_sender(sender, receiver)
    if context is None:
        if signup is not None and form['NumMedia'] == '0':
            return reply_parts(await signup.handle(form))
        return reply_parts(message_xml('This number is not registered to an active EasyInvio workspace. Ask your owner to verify it, or send Register.'))
    if form['NumMedia'] != '0':
        return reply_parts(message_xml('Please send text, for example: Quote 4.5kg from GB to US.'))
    result = await ConversationalActionGateway(request).process(context, ConversationMessage(
        sender_id=sender, message_body=form['Body'], channel='WHATSAPP',
        request_id=uuid5(NAMESPACE_URL, 'twilio:' + form['MessageSid'])), verified_whatsapp=True, received_at=received_at)
    return reply_parts(message_xml(result['conversational_reply']), return_media(result, state.settings))


class WhatsAppQueue:
    def __init__(self, pool: asyncpg.Pool, settings: Settings, application: FastAPI, client: Client | None = None):
        self.pool, self.settings, self.application = pool, settings, application
        if not settings.credential_keys:
            raise ValueError('WhatsApp queue requires CREDENTIAL_KEYS for encrypted inbound messages and OTP replies')
        self.key_id = sorted(settings.credential_keys)[0]
        self.ciphers = {key: Fernet(value.get_secret_value().encode()) for key, value in settings.credential_keys.items()}
        self.client = client or Client(settings.twilio_account_sid, settings.twilio_auth_token.get_secret_value(),
            http_client=TwilioHttpClient(timeout=10, max_retries=0))

    def encrypt(self, value: bytes) -> bytes:
        return self.ciphers[self.key_id].encrypt(value)

    async def enqueue(self, raw: bytes, form: FormData) -> None:
        digest = inbound_digest(raw)
        async with self.pool.acquire(timeout=.1) as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL lock_timeout='80ms'")
                await connection.execute("SET LOCAL statement_timeout='200ms'")
                row = await connection.fetchrow('''INSERT INTO public.whatsapp_inbound_queue
                    (message_sid,sender_e164,receiver_e164,input_sha256,payload_ciphertext,key_id)
                    VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(message_sid) DO UPDATE
                    SET message_sid=EXCLUDED.message_sid RETURNING input_sha256''',
                    form['MessageSid'], form['From'].removeprefix('whatsapp:'), form['To'].removeprefix('whatsapp:'),
                    digest, self.encrypt(raw), self.key_id)
                if row['input_sha256'] != digest:
                    raise HTTPException(409, 'MessageSid already used for different content')

    async def claim(self) -> asyncpg.Record | None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow('''SELECT q.* FROM public.whatsapp_inbound_queue q
                    WHERE q.state IN ('STAGED','READY') AND NOT EXISTS(
                      SELECT 1 FROM public.whatsapp_inbound_queue earlier
                      WHERE earlier.receiver_e164=q.receiver_e164 AND earlier.sender_e164=q.sender_e164
                      AND earlier.id<q.id AND earlier.state NOT IN ('ACCEPTED','FAILED'))
                    ORDER BY q.id LIMIT 1 FOR UPDATE OF q SKIP LOCKED''')
                if row:
                    await connection.execute("UPDATE public.whatsapp_inbound_queue SET state='PROCESSING',updated_at=now() WHERE id=$1", row['id'])
                return row

    async def mark(self, inbound_id: int, state: Literal['READY', 'ACCEPTED', 'FAILED', 'REVIEW_REQUIRED'], code: str | None = None) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute('UPDATE public.whatsapp_inbound_queue SET state=$2,error_code=$3,updated_at=now() WHERE id=$1', inbound_id, state, code)

    async def stage(self, inbound_id: int, parts: list[OutboundPart]) -> None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                for index, part in enumerate(parts):
                    await connection.execute('''INSERT INTO public.whatsapp_reply_outbox
                        (inbound_id,part_index,payload_ciphertext,key_id) VALUES($1,$2,$3,$4)''',
                        inbound_id, index, self.encrypt(part.model_dump_json().encode()), self.key_id)
                await connection.execute("UPDATE public.whatsapp_inbound_queue SET state='READY',updated_at=now() WHERE id=$1", inbound_id)

    async def dispatch(self, row: asyncpg.Record) -> None:
        async with self.pool.acquire() as connection:
            parts = await connection.fetch('SELECT * FROM public.whatsapp_reply_outbox WHERE inbound_id=$1 ORDER BY part_index', row['id'])
        for item in parts:
            if item['state'] == 'ACCEPTED':
                continue
            if item['state'] != 'STAGED':
                await self.mark(row['id'], 'REVIEW_REQUIRED', 'UNCERTAIN_SEND')
                return
            part = OutboundPart.model_validate_json(self.ciphers[item['key_id']].decrypt(bytes(item['payload_ciphertext'])))
            async with self.pool.acquire() as connection:
                claimed = await connection.fetchval("UPDATE public.whatsapp_reply_outbox SET state='SENDING',updated_at=now() WHERE id=$1 AND state='STAGED' RETURNING id", item['id'])
            if claimed is None:
                await self.mark(row['id'], 'REVIEW_REQUIRED', 'SEND_STATE_CONFLICT')
                return
            try:
                kwargs: dict[str, Any] = {'from_': 'whatsapp:' + row['receiver_e164'],
                    'to': 'whatsapp:' + row['sender_e164'], 'body': part.body}
                if part.media_url:
                    kwargs['media_url'] = [part.media_url]
                sent = await asyncio.to_thread(self.client.messages.create, **kwargs)
                if not re.fullmatch(r'SM[0-9a-fA-F]{32}', sent.sid or ''):
                    raise ValueError('Invalid outbound SID')
            except TwilioRestException as error:
                definite = error.status in {400, 401, 403, 404, 413, 422, 429}
                await self.send_failure(row['id'], item['id'], definite)
                return
            except Exception:
                await self.send_failure(row['id'], item['id'], False)
                return
            async with self.pool.acquire() as connection:
                await connection.execute("UPDATE public.whatsapp_reply_outbox SET state='ACCEPTED',provider_message_sid=$2,updated_at=now() WHERE id=$1 AND state='SENDING'", item['id'], sent.sid)
        await self.mark(row['id'], 'ACCEPTED')

    async def send_failure(self, inbound_id: int, part_id: int, definite: bool) -> None:
        state = 'FAILED' if definite else 'REVIEW_REQUIRED'
        async with self.pool.acquire() as connection:
            await connection.execute('UPDATE public.whatsapp_reply_outbox SET state=$2,error_code=$3,updated_at=now() WHERE id=$1',
                                     part_id, state, 'TWILIO_REJECTED' if definite else 'UNCERTAIN_SEND')
        await self.mark(inbound_id, state, 'TWILIO_REJECTED' if definite else 'UNCERTAIN_SEND')

    async def drain(self) -> bool:
        row = await self.claim()
        if row is None:
            return False
        try:
            if row['created_at'] < datetime.now(timezone.utc) - timedelta(hours=23, minutes=59):
                await self.mark(row['id'], 'FAILED', 'SERVICE_WINDOW_EXPIRED')
                return True
            raw = self.ciphers[row['key_id']].decrypt(bytes(row['payload_ciphertext']))
            form = FormData(parse_qsl(raw.decode(), keep_blank_values=True))
            if (inbound_digest(raw) != row['input_sha256'] or form['MessageSid'] != row['message_sid']
                    or form['AccountSid'] != self.settings.twilio_account_sid
                    or form['To'] != 'whatsapp:' + self.settings.twilio_whatsapp_number
                    or form['To'] != 'whatsapp:' + row['receiver_e164']
                    or form['From'] != 'whatsapp:' + row['sender_e164']):
                raise ValueError('Queued identity mismatch')
            if row['state'] == 'STAGED':
                request = Request({'type': 'http', 'app': self.application, 'method': 'POST', 'path': '/internal/whatsapp-worker', 'headers': []})
                async with asyncio.timeout(180):
                    parts = await process_inbound(request, form, row['created_at'])
                await self.stage(row['id'], parts)
            await self.dispatch(row)
        except asyncio.CancelledError:
            raise  # Durable PROCESSING/SENDING fences survive shutdown.
        except Exception as error:
            logger.warning('whatsapp_job_needs_review id=%s error_type=%s', row['id'], type(error).__name__)
            await self.mark(row['id'], 'REVIEW_REQUIRED', 'PROCESSING_UNCONFIRMED')
        return True

    async def worker(self) -> None:
        while True:
            try:
                if await self.drain():
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning('whatsapp_queue_unavailable error_type=%s', type(error).__name__)
            await asyncio.sleep(.25)


async def accept_whatsapp(request: Request) -> Response:
    from backend.sandbox_hooks import authenticated_twilio_form
    if not request.app.state.settings.twilio_enabled:
        raise HTTPException(503, 'Twilio integration is disabled')
    try:
        async with asyncio.timeout(.45):
            form = await authenticated_twilio_form(request)
            queue = getattr(request.app.state, 'whatsapp_queue', None)
            if queue is None:
                raise HTTPException(503, 'WhatsApp queue is unavailable; apply migration 043 and restart')
            await queue.enqueue(request.state.twilio_raw_body, form)
    except (TimeoutError, asyncpg.PostgresError):
        raise HTTPException(503, 'WhatsApp ingress is busy; retry the same MessageSid') from None
    return Response('<Response/>', media_type='application/xml')
