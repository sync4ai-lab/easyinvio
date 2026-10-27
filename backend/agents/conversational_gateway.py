"""One authenticated action dispatcher for signed WhatsApp and session-bound web chat.

Models extract proposals only. Money, carrier purchases and claim intake remain
owned by deterministic services. Durable receipts fence uncertain action retries.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from backend.whatsapp_provider import number as whatsapp_number

from contextlib import asynccontextmanager
from decimal import Decimal
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit, urljoin
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from twilio.twiml.messaging_response import MessagingResponse

from backend.agents.models import ConversationalIntent, StrictOutput
from backend.agents.conversation_context import ConversationDraft, collect_reply, explicit_quote
from backend.agents.status_guidance import status_question
from backend.agents.rag_support import documentation_question

logger = logging.getLogger('easyinvio.conversation')
ROLES = {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}
FINANCE_ROLES = {'OWNER', 'ADMIN', 'ACCOUNTANT'}
DISPATCH_ROLES = {'OWNER', 'ADMIN', 'DISPATCHER'}


class ConversationMessage(StrictOutput):
    sender_id: str | None = Field(default=None, pattern=r'^\+[1-9][0-9]{7,14}$')
    message_body: str = Field(min_length=1, max_length=2000)
    channel: Literal['WHATSAPP', 'WEB_CHAT']
    request_id: UUID = Field(default_factory=uuid4)
    media_urls: list[str] = Field(default_factory=list,max_length=1)


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def message_xml(text: str) -> str:
    """Split prose at whitespace, retaining every URL as a complete token."""
    text = re.sub(r'[ \t\r\f\v]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    response = MessagingResponse()
    chunk = ''
    for token in re.findall(r'\S+\s*', text):
        if len(token.rstrip()) > 1590:
            if token.startswith(('https://', 'http://')):
                raise ValueError('A reply link exceeds the messaging limit')
            pieces = [token[index:index + 1590] for index in range(0, len(token), 1590)]
        else:
            pieces = [token]
        for piece in pieces:
            if chunk and len(chunk + piece) > 1590:
                response.message(chunk.rstrip())
                chunk = ''
            chunk += piece
    if chunk.strip():
        response.message(chunk.rstrip())
    return str(response)


class ConversationStore:
    def __init__(self, pool):
        self.pool = pool

    @asynccontextmanager
    async def receipt(self, context, body, message_id, digest):
        # A short transaction fences delivery and thread ordering. No connection
        # or transaction is retained while a model, carrier or Stripe call runs.
        async with self.pool.acquire() as connection:
            if not await connection.fetchval("SELECT to_regclass('public.conversational_messages') IS NOT NULL"):
                raise HTTPException(503, 'Apply migration 038 before using conversational actions')
            async with connection.transaction():
                key = f'conversation:{context.tenant_id}:{context.user_id}:{body.channel}'
                await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key)
                assistance_id = getattr(context, 'assistance_session_id', None)
                if assistance_id is not None:
                    member = await connection.fetchrow('''SELECT 'OWNER' AS role
                        FROM public.admin_client_assistance_sessions a
                        JOIN public.tenants t ON t.tenant_id=a.tenant_id
                        WHERE a.tenant_id=$1 AND a.actor_auth_user_id=$2 AND a.id=$3
                        AND a.revoked_at IS NULL AND a.expires_at>now() AND t.workspace_status='ACTIVE' ''',
                        context.tenant_id, context.user_id, assistance_id)
                else:
                    member = await connection.fetchrow('''SELECT u.role FROM public.users u
                        JOIN public.tenants t ON t.tenant_id=u.tenant_id
                        WHERE u.tenant_id=$1 AND u.auth_user_id=$2 AND u.is_active
                        AND t.workspace_status='ACTIVE' ''', context.tenant_id, context.user_id)
                if member is None or member['role'] != context.role or member['role'] not in ROLES:
                    raise HTTPException(403, 'Active workspace membership required')
                row = await connection.fetchrow('''SELECT input_sha256,state,response FROM public.conversational_messages
                    WHERE tenant_id=$1 AND auth_user_id=$2 AND id=$3''', context.tenant_id, context.user_id, message_id)
                if row:
                    if row['input_sha256'] != digest:
                        raise HTTPException(409, 'This message reference was used for different content')
                    if row['state'] != 'COMPLETED':
                        raise HTTPException(409, 'The earlier action needs review. Check shipments, payments or support before sending it again.')
                else:
                    active = await connection.fetchval('''SELECT EXISTS(SELECT 1 FROM public.conversational_messages
                        WHERE tenant_id=$1 AND auth_user_id=$2 AND channel=$3 AND state='PROCESSING')''',
                        context.tenant_id, context.user_id, body.channel)
                    if active:
                        raise HTTPException(409, 'Your previous message is processing or needs reconciliation. Check your workspace before continuing.')
                    await connection.execute('''INSERT INTO public.conversational_messages
                        (id,tenant_id,auth_user_id,channel,input_sha256) VALUES($1,$2,$3,$4,$5)''',
                        message_id, context.tenant_id, context.user_id, body.channel, digest)
        try:
            yield None, decoded(row['response']) if row else None
        except BaseException:
            if row is None:
                try:
                    async with self.pool.acquire() as connection:
                        await connection.execute('''UPDATE public.conversational_messages SET state='REVIEW_REQUIRED'
                            WHERE tenant_id=$1 AND auth_user_id=$2 AND id=$3 AND state='PROCESSING' ''',
                            context.tenant_id, context.user_id, message_id)
                except (asyncpg.PostgresError, OSError, TimeoutError):
                    logger.warning('conversation_receipt_needs_reconciliation')
            raise

    async def finish(self, context, message_id, result):
        async with self.pool.acquire() as connection:
            await connection.execute('''UPDATE public.conversational_messages SET state='COMPLETED',
                response=$4::jsonb,completed_at=now() WHERE tenant_id=$1 AND auth_user_id=$2 AND id=$3''',
                context.tenant_id, context.user_id, message_id, json.dumps(result))

    async def latest_quote(self, context, channel):
        async with self.pool.acquire() as connection:
            return decoded(await connection.fetchval('''SELECT response FROM public.conversational_messages
                WHERE tenant_id=$1 AND auth_user_id=$2 AND channel=$3 AND state='COMPLETED'
                AND response->>'action_taken'='QUOTE' ORDER BY created_at DESC,id DESC LIMIT 1''',
                context.tenant_id, context.user_id, channel))

    async def latest_turn(self, context, channel):
        async with self.pool.acquire() as connection:
            return decoded(await connection.fetchval('''SELECT response FROM public.conversational_messages
                WHERE tenant_id=$1 AND auth_user_id=$2 AND channel=$3 AND state='COMPLETED'
                AND created_at>now()-interval '15 minutes'
                ORDER BY created_at DESC,id DESC LIMIT 1''', context.tenant_id, context.user_id, channel))


class ConversationalActionGateway:
    def __init__(self, request: Request, store=None):
        self.request = request
        self.state = request.app.state
        self.whatsapp = getattr(self.state, 'whatsapp', None)
        finance = getattr(self.state, 'finance', None)
        self.pool = finance.pool if finance is not None else self.whatsapp.pool if self.whatsapp else None
        self.store = store or ConversationStore(self.pool)

    @staticmethod
    def reply(action, text, *, status='COMPLETED', **details):
        return {'status': status, 'conversational_reply': text, 'action_taken': action, **details}

    async def interpret(self, context, text):
        if status_question(text) or documentation_question(text):
            return ConversationalIntent(intent='HELP')
        closing = re.fullmatch(r'\s*close\s+manifest\s+([A-Za-z0-9 _-]{1,50})\s*',text,re.I)
        if closing:
            return ConversationalIntent(intent='CLOSE_MANIFEST',target_reference_id=closing[1].strip())
        if re.fullmatch(r'\s*manifest\s+status\s*',text,re.I):
            return ConversationalIntent(intent='MANIFEST_STATUS')
        from main import parse_quote
        try:
            parsed = parse_quote(text)
            return ConversationalIntent(intent='QUOTE', weight_kg=str(parsed.weight_kg),
                origin_country=parsed.origin_country, destination_country=parsed.destination_country, route_code=parsed.route_code)
        except ValueError:
            pass
        proposal = explicit_quote(text)
        if proposal is not None:
            return proposal
        # Explicit commands continue to work without a model; these are also the
        # authorization grammar for financial actions. A model cannot invent consent.
        booking = re.fullmatch(r'\s*(?:book|confirm)\s+option\s+(10|[1-9])\s*', text, re.I)
        if booking:
            return ConversationalIntent(intent='BOOK_RESERVATION', selection_index=int(booking[1]))
        returning = re.fullmatch(r'\s*(?:create\s+a\s+return\s+for|return)(?:\s+(?:order|tracking|shipment))?(?:\s+([A-Za-z0-9_-]{1,200}))?\s*', text, re.I)
        if returning:
            return ConversationalIntent(intent='TRIGGER_RETURN', target_reference_id=returning[1])
        topup = re.fullmatch(r'\s*(?:top\s*up|topup)\s+(?:[£€$]\s*)?([0-9]+(?:[.,][0-9]{1,2})?)(?:\s+(GBP|EUR|USD))?\s*', text, re.I)
        if topup:
            return ConversationalIntent(intent='TOPUP_WALLET', monetary_amount=Decimal(topup[1].replace(',', '.')))
        tracking = re.fullmatch(r'\s*(?:track|tracking)(?:\s+(?:order|shipment|parcel|return))?\s+([A-Za-z0-9_-]{1,200})\s*', text, re.I)
        if tracking:
            return ConversationalIntent(intent='TRACK_PACKAGE', target_reference_id=tracking[1])
        if re.fullmatch(r'\s*(?:where\s+is\s+my\s+(?:order|package|parcel|shipment|refund)|when\s+should\s+my\s+parcel\s+arrive|has\s+my\s+return\s+arrived|my\s+delivery\s+is\s+delayed|track(?:\s+my\s+(?:package|parcel|shipment))?)\s*[?.!]*\s*', text, re.I):
            return ConversationalIntent(intent='TRACK_PACKAGE')
        claim = re.fullmatch(r'\s*claim\s+([A-Za-z0-9_-]{1,200})\s+(lost|damaged)\s+(.{10,1800})\s*', text, re.I | re.S)
        if claim:
            return ConversationalIntent(intent='FILE_CLAIM', target_reference_id=claim[1], description_notes=claim[3].strip())
        if re.fullmatch(r'\s*(?:my\s+)?(?:package|parcel|shipment)(?:\s+is)?\s+(?:lost|damaged)\s*[.!]?\s*', text, re.I):
            return ConversationalIntent(intent='FILE_CLAIM', description_notes=text.strip())
        if text.strip().lower() in {'help', 'hello', 'hi', 'commands'}:
            return ConversationalIntent(intent='HELP')
        engine = getattr(self.state, 'logistics_supervisor', None)
        if engine is not None and engine.runtime.available:
            try:
                async with asyncio.timeout(3):
                    return await engine.ingestion.conversation(context, text)
            except (HTTPException, ValueError, TimeoutError):
                logger.info('conversation_parser_fallback')
        return ConversationalIntent(intent='HELP')

    async def process(self, context, body: ConversationMessage, *, verified_whatsapp=False, received_at: datetime | None = None):
        if body.media_urls:
            raise HTTPException(422,'Chat input media URLs cannot authorize outbound carrier documents')
        if context.role not in ROLES or self.pool is None:
            raise HTTPException(403, 'An active registered workspace session is required')
        if body.channel == 'WHATSAPP' and not verified_whatsapp:
            raise HTTPException(403, 'WhatsApp actions require the signed Twilio webhook')
        # sender_id is never a tenant/user selector for web chat; its identity is
        # always the authenticated browser session, including assistance audit.
        message_id = uuid5(NAMESPACE_URL, f'conversation:{context.tenant_id}:{context.user_id}:{body.channel}:{body.request_id}')
        digest = hashlib.sha256(body.model_dump_json(exclude={'request_id','media_urls'}).encode()).hexdigest()
        async with self.store.receipt(context, body, message_id, digest) as (_, cached):
            if cached is not None:
                return self.public(cached)
            if body.channel == 'WHATSAPP':
                async with self.pool.acquire() as connection:
                    await connection.execute('''UPDATE public.whatsapp_bindings b SET last_inbound_at=greatest(b.last_inbound_at,coalesce($5::timestamptz,now()))
                    FROM public.users u WHERE b.tenant_id=$1 AND b.user_id=u.id AND u.tenant_id=b.tenant_id
                    AND u.auth_user_id=$2 AND b.sender_e164=$3 AND b.receiver_e164=$4 AND b.is_active AND u.is_active''',
                    context.tenant_id, context.user_id, body.sender_id, whatsapp_number(self.state.settings), received_at)
            self.draft = None
            previous = await self.store.latest_turn(context, body.channel)
            self.previous = previous or {}
            if previous and previous.get('_pending'):
                try:
                    pending = ConversationDraft.model_validate(previous['_pending'])
                    if pending.active(context):
                        self.draft = pending
                except ValueError:
                    pass
            if body.message_body.strip().lower() in {'cancel', 'cancel quote', 'start over'}:
                result = self.reply('HELP', 'Conversation draft cleared. Send a new quote, tracking reference or claim request.')
                await self.store.finish(context, message_id, result)
                return self.public(result)
            try:
                status_help = status_question(body.message_body) or documentation_question(body.message_body)
                new_command = None if ';' in body.message_body else re.search(r'\b(?:quote|rates?|track|tracking|claim|book|confirm|return|topup|help|commands|manifest)\b|\btop\s+up\b', body.message_body, re.I)
                if status_help:
                    intent = ConversationalIntent(intent='HELP')
                elif self.draft and not new_command:
                    if self.draft.action == 'QUOTE':
                        collect_reply(self.draft, body.message_body, require_paf=body.channel == 'WHATSAPP')
                    elif self.draft.waiting_for == 'reference':
                        reference = body.message_body.strip()
                        if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', reference):
                            raise ValueError('Reply with only the shipment or tracking reference.')
                        self.draft.intent = self.draft.intent.model_copy(update={'target_reference_id': reference})
                    intent = self.draft.intent
                else:
                    intent = await self.interpret(context, body.message_body)
                    self.draft = None
            except ValueError:
                result = (self.pending_reply(self.draft, 'Please check the requested values and reply in the format shown. ' + self.draft_prompt(self.draft))
                    if self.draft else self.reply('HELP', 'Please check your amount, weight or reference. Top-ups must be between 1 and 10000 in your wallet currency, with at most two decimal places.', status='NEEDS_INPUT'))
                await self.store.finish(context, message_id, result)
                return self.public(result)
            try:
                result = await self.execute(context, body, intent, message_id)
                if status_help and self.draft:
                    result['_pending'] = self.draft.model_dump(mode='json')
            except HTTPException as error:
                # Persist bounded public refusals; uncertain/crashed actions remain
                # PROCESSING so a redelivery cannot start a second operation.
                if error.status_code >= 500:
                    raise
                detail = error.detail
                text = detail.get('message', 'The action could not be completed. Check your workspace.') if isinstance(detail, dict) else str(detail)
                result = self.reply(intent.intent, text, status='REVIEW_REQUIRED')
            await self.store.finish(context, message_id, result)
        return self.public(result)

    @staticmethod
    def public(result):
        return {key: value for key, value in result.items() if not key.startswith('_')}

    def pending_reply(self, draft, text):
        return self.reply(draft.action, text, status='NEEDS_INPUT', _pending=draft.model_dump(mode='json'))

    @staticmethod
    def draft_prompt(draft):
        if draft.waiting_for == 'paf_selection':
            options = draft.paf_options[draft.paf_offset:draft.paf_offset + 8]
            return ('Choose the ' + ('pickup' if draft.paf_prefix == 'origin' else 'delivery') + ' premise number:\n'
                + '\n'.join(f'{index}: {option.label}' for index, option in enumerate(options, draft.paf_offset + 1))
                + '\nReply with a displayed number, More, Back or Cancel.')
        prompts = {
            'postcodes': 'I can check that quote for you. Please reply with Origin Postcode, Destination Postcode.',
            'countries': 'Please confirm the two countries as Origin Country, Destination Country, for example GB, FR. A postcode alone can be ambiguous.',
            'weight': 'What is the packed parcel weight in kg?',
            'dimensions': 'What are the measured parcel dimensions? Reply length x width x height in cm, for example 30 x 20 x 10.',
            'origin_address': 'Please give the pickup contact name; street address; city. Add a fourth field for state/province when required.',
            'destination_address': 'Please give the delivery contact name; street address; city. Add a fourth field for state/province when required.',
            'origin_contact': 'What is the pickup contact name for the selected premise?',
            'destination_contact': 'What is the delivery contact name for the selected premise?',
            'paf_retry': 'Reply Retry to check the UK postcode again, or Cancel to start a new quote.',
            'retry': 'Reply Retry to request rates again, or Cancel to clear the draft.',
            'reference': 'Please reply with the shipment or tracking reference. I will check only your workspace.',
        }
        return prompts[draft.waiting_for]

    async def execute(self, context, body, intent, message_id):
        if intent.intent in {'CLOSE_MANIFEST','MANIFEST_STATUS'}:
            return await self.manifest(context,body,intent,message_id)
        if intent.intent == 'TRIGGER_RETURN':
            return await self.trigger_return(context, body, intent, message_id)
        if intent.intent == 'QUOTE':
            return await self.quote(context, body, intent, message_id)
        if intent.intent == 'BOOK_RESERVATION':
            if context.role not in DISPATCH_ROLES:
                raise HTTPException(403, 'A dispatch role is required to book shipments')
            explicit = re.fullmatch(r'\s*(?:book|confirm)\s+option\s+(10|[1-9])\s*', body.message_body, re.I)
            if not explicit or int(explicit[1]) != intent.selection_index:
                return self.reply(intent.intent, 'To confirm a displayed price, send: Book option 1. Otherwise review the quote in Create a shipment.', status='NEEDS_INPUT')
            quote = await self.store.latest_quote(context, body.channel)
            choices = quote.get('_choices', []) if quote else []
            if len(choices) < intent.selection_index:
                raise HTTPException(409, 'Request a fresh quote in this conversation before choosing an option')
            choice_id = UUID(choices[intent.selection_index - 1])
            async with self.pool.acquire() as connection:
                choice = await connection.fetchrow('''SELECT selected_rate,expires_at FROM public.whatsapp_quote_choices
                    WHERE tenant_id=$1 AND auth_user_id=$2 AND id=$3 AND expires_at>now()''',
                    context.tenant_id, context.user_id, choice_id)
            if not choice:
                raise HTTPException(410, 'This option has expired. Request fresh rates.')
            if body.channel == 'WHATSAPP':
                base = self.state.settings.booking_page_url
                if not base or not self.whatsapp:
                    return self.reply(intent.intent, 'Web checkout is not configured yet. Please contact support to arrange booking. '
                        'No booking or payment was made.', status='NEEDS_INPUT')
                from urllib.parse import urlencode
                link = base + '?' + urlencode({'t': str(context.tenant_id),
                    'quote': self.whatsapp.sign_choice(context, choice_id, choice['expires_at'])})
                return self.reply(intent.intent, f'Option {intent.selection_index} selected. Open this secure link and sign in '
                    'with the same account to review shipment details, customs and payment before confirming:\n' + link +
                    '\nNo booking or payment has been made.', checkout_url=link)
            from backend.automation_three_partners import BookingRequest
            rate = decoded(choice['selected_rate'])
            result = await self.state.partner_lifecycle.confirm(context, BookingRequest(
                tenant_id=context.tenant_id, offer_id=UUID(rate['offer_id'])))
            if result.get('status') != 'BOOKED':
                return self.reply(intent.intent, 'Your booking is still being checked. View Shipments before trying again.', status='REVIEW_REQUIRED')
            label = result.get('label') or {}
            return self.reply(intent.intent, f"Shipment booked. Tracking: {label.get('tracking_number', 'awaiting confirmation')}. Open Shipments to download the label and available customs documents.", shipment_id=result['shipment_id'],booking=result,media_urls=result.get('media_urls',[]))
        if intent.intent == 'TRACK_PACKAGE':
            reference = intent.target_reference_id or getattr(self, 'previous', {}).get('_last_reference')
            if not reference:
                draft = ConversationDraft(action='TRACK_PACKAGE', intent=intent, waiting_for='reference',
                    assistance_id=str(context.assistance_session_id) if context.assistance_session_id else None)
                return self.pending_reply(draft, self.draft_prompt(draft))
            tracking_workspace = getattr(self.state,'tracking_workspace',None)
            if tracking_workspace is not None and tracking_workspace.ready:
                return self.reply(intent.intent,await tracking_workspace.chat(context,reference),_last_reference=reference)
            shipment = await self.shipment(context, reference)
            async with self.pool.acquire() as connection:
                events = await connection.fetch('''SELECT status,occurred_at FROM public.tracking_events
                    WHERE tenant_id=$1 AND shipment_id=$2 ORDER BY occurred_at DESC,id DESC LIMIT 5''',
                    context.tenant_id, shipment['id'])
            lines = [f"Shipment {shipment['customer_reference'] or shipment['tracking_number'] or shipment['id']}: {shipment['status']}."]
            if events:
                lines.append(f"Last recorded milestone: {events[0]['status']} at {events[0]['occurred_at'].isoformat()}.")
                exceptions = [event for event in events if event['status'] == 'EXCEPTION']
                if exceptions:
                    lines.append(f"An exception was recorded at {exceptions[0]['occurred_at'].isoformat()}. Open the shipment timeline for carrier details.")
            else:
                lines.append('No carrier tracking milestone has been recorded yet.')
            return self.reply(intent.intent, '\n'.join(lines), _last_reference=reference)
        if intent.intent == 'TOPUP_WALLET':
            if context.role not in FINANCE_ROLES:
                raise HTTPException(403, 'An owner, admin or accountant must arrange wallet top-ups')
            explicit = re.fullmatch(r'\s*(?:top\s*up|topup)\s+(?:([£€$])\s*)?([0-9]+(?:[.,][0-9]{1,2})?)(?:\s+(GBP|EUR|USD))?\s*', body.message_body, re.I)
            if not explicit or Decimal(explicit[2].replace(',', '.')) != intent.monetary_amount:
                return self.reply(intent.intent, 'Enter a specific amount, for example: Top up 50 GBP. You will confirm payment on Stripe.', status='NEEDS_INPUT')
            async with self.pool.acquire() as connection:
                currency = await connection.fetchval('SELECT currency FROM public.wallets WHERE tenant_id=$1', context.tenant_id)
            if currency not in {'GBP', 'EUR', 'USD'}:
                raise HTTPException(409, 'Your wallet is not configured. Ask your workspace owner to check Wallet settings.')
            requested = (explicit[3] or {'£': 'GBP', '€': 'EUR', '$': 'USD'}.get(explicit[1]) or currency).upper()
            if requested != currency or (explicit[1] and {'£': 'GBP', '€': 'EUR', '$': 'USD'}[explicit[1]] != currency):
                raise HTTPException(409, 'The amount must use your wallet currency; chat does not convert currencies')
            from main import TopupRequest
            result = await self.state.finance.create_checkout(context, TopupRequest(request_id=message_id, amount=intent.monetary_amount))
            url = urlsplit(result.checkout_url)
            if url.scheme != 'https' or url.hostname != 'checkout.stripe.com' or url.username or url.password or url.port not in (None, 443):
                raise HTTPException(502, 'The payment link could not be verified. Open Wallet to check your top-up.')
            return self.reply(intent.intent, f'Confirm your {intent.monetary_amount:.2f} {currency} top-up on Stripe. No payment has been taken by this chat.\n{result.checkout_url}')
        if intent.intent == 'FILE_CLAIM':
            return await self.claim(context, body, intent, message_id)
        engine = getattr(self.state, 'logistics_supervisor', None)
        commands = ('You can ask for a quote without a saved route; I will collect missing locations, measured packaging and addresses. '
                    'You can also track, book a displayed option, arrange a top-up, create a return or record a claim support case. Send Cancel to clear a draft.\n'
                    'Examples: Quote 4.5kg from London to Paris; Track EINVIO-00000050; Book option 1; Return order EINVIO-00000050; Top up 50 GBP; My package is lost.')
        if engine is not None and len(body.message_body.strip()) >= 3 and body.message_body.strip().lower() not in {'help', 'hello', 'hi', 'commands'}:
            answer = await engine.help.answer(context, body.message_body[:800])
            sources = answer.get('sources', [])[:6]
            excerpts = answer.get('excerpts', [])[:2]
            text = answer['answer']
            if excerpts:
                text += '\n' + '\n'.join(item['text'] for item in excerpts)
            for number, item in enumerate(sources, 1):
                url = item['url']
                if body.channel == 'WHATSAPP' and url.startswith('/help/'):
                    base = getattr(self.state.settings, 'booking_page_url', '')
                    parsed_base = urlsplit(base)
                    url = urljoin(base, url) if parsed_base.scheme == 'https' and parsed_base.hostname else ''
                text += '\n[' + str(number) + '] ' + item['title'] + (': ' + url if url else ' — open Help Centre in your workspace')
            return self.reply('HELP', text, answer_mode=answer.get('mode'), sources=sources, help_fallback_reason=answer.get('fallback_reason'))
        return self.reply('HELP', commands)

    async def quote(self, context, body, intent, message_id):
        from main import Address, Dimensions, RatingRequest, get_rates
        draft = self.draft or ConversationDraft(action='QUOTE', intent=intent,
            assistance_id=str(context.assistance_session_id) if context.assistance_session_id else None)
        self.draft = draft
        rating = None
        if intent.route_code:
            async with self.pool.acquire() as connection:
                routes = await connection.fetch('''SELECT origin_address,destination_address,dimensions,currency
                    FROM public.whatsapp_routes WHERE tenant_id=$1 AND origin_country=$2 AND destination_country=$3
                    AND is_active AND route_code=$4 ORDER BY route_code LIMIT 2''',
                    context.tenant_id, intent.origin_country, intent.destination_country, intent.route_code)
            if len(routes) == 1 and intent.weight_kg:
                route = routes[0]
                rating = RatingRequest(origin=Address.model_validate(decoded(route['origin_address'])),
                    destination=Address.model_validate(decoded(route['destination_address'])),
                    dimensions=[Dimensions.model_validate(decoded(route['dimensions']))],
                    weights_kg=[Decimal(intent.weight_kg)], currency=route['currency'])
            else:
                draft.intent = intent.model_copy(update={'route_code': None})
                intent = draft.intent
        if rating is None:
            if draft.waiting_for == 'paf_selection' and draft.paf_options:
                return self.pending_reply(draft, self.draft_prompt(draft))
            if draft.waiting_for in {'origin_contact', 'destination_contact'}:
                return self.pending_reply(draft, self.draft_prompt(draft))
            required = [
                ('postcodes', not intent.origin_postal_code or not intent.destination_postal_code),
                ('countries', not intent.origin_country or not intent.destination_country),
                ('origin_address', body.channel == 'WHATSAPP' and intent.origin_country == 'GB' and draft.origin_address is None),
                ('destination_address', body.channel == 'WHATSAPP' and intent.destination_country == 'GB' and draft.destination_address is None),
                ('weight', not intent.weight_kg),
                ('dimensions', draft.dimensions is None),
                ('origin_address', draft.origin_address is None),
                ('destination_address', draft.destination_address is None),
            ]
            for field, missing in required:
                if missing:
                    if (field in {'origin_address', 'destination_address'} and body.channel == 'WHATSAPP'
                            and getattr(intent, field.removesuffix('_address') + '_country') == 'GB'):
                        return await self.collect_uk_premise(draft, field.removesuffix('_address'))
                    draft.waiting_for = field
                    return self.pending_reply(draft, self.draft_prompt(draft))
            async with self.pool.acquire() as connection:
                currency = await connection.fetchval('SELECT currency FROM public.wallets WHERE tenant_id=$1', context.tenant_id)
            if currency not in {'GBP', 'EUR', 'USD'}:
                raise HTTPException(409, 'Ask your workspace owner to configure the wallet currency before requesting rates.')
            rating = RatingRequest.from_conversation(origin=draft.origin_address, destination=draft.destination_address,
                dimensions=draft.dimensions, weight_kg=intent.weight_kg, currency=currency)
        try:
            if body.channel == 'WHATSAPP':
                result = await self.state.rating.quote(context, rating, self.state.settings.whatsapp_provider_seconds)
                async with self.pool.acquire() as connection:
                    await connection.execute('''INSERT INTO public.partner_unbound_quotes
                        (tenant_id,request_id,request_payload,quote_payload,expires_at)
                        VALUES($1,$2,$3::jsonb,$4::jsonb,$5)''', context.tenant_id, result.request_id,
                        rating.model_dump_json(), result.model_dump_json(), result.expires_at)
            else:
                result = await get_rates(rating, self.request, context)
        except (HTTPException, TimeoutError) as error:
            if isinstance(error, HTTPException) and error.status_code < 500:
                raise
            draft.waiting_for = 'retry'
            return self.pending_reply(draft, 'Rates are temporarily unavailable for these details. No booking or payment was made. '
                'Reply Retry to check again, Cancel to clear the draft, or use Create a shipment for quote diagnostics.')
        sandbox = self.state.settings.provider_environment == 'TEST'
        lines = ['EasyInvio.com sandbox quotes' if sandbox else 'EasyInvio.com live quotes',
            f'{rating.weights_kg[0]}kg | {rating.origin.country_code} → {rating.destination.country_code}',
            'Prices exclude tax. No shipment protection is added.',
            'Send Book option N to open secure web checkout. No payment is taken in WhatsApp.' if body.channel == 'WHATSAPP'
            else 'Sending Book option N confirms the displayed option for wallet booking.']
        choices = []
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                for index, rate in enumerate(result.rates[:10], 1):
                    choice_id = uuid4()
                    await connection.execute('''INSERT INTO public.whatsapp_quote_choices
                        (id,tenant_id,auth_user_id,rating_request,selected_rate,expires_at)
                        VALUES($1,$2,$3,$4::jsonb,$5::jsonb,$6)''', choice_id, context.tenant_id, context.user_id,
                        rating.model_dump_json(), rate.model_dump_json(), result.expires_at)
                    choices.append(str(choice_id))
                    delivery = f' | estimated {rate.delivery_days} days' if rate.delivery_days is not None else ''
                    lines.append(f'{index}. {rate.carrier_code} {rate.service_code}: {rate.client_price_ex_tax:.2f} {rate.currency}{delivery}')
                    if self.whatsapp and self.state.settings.booking_page_url:
                        from urllib.parse import urlencode
                        lines.append(self.state.settings.booking_page_url + '?' + urlencode({
                            't': str(context.tenant_id), 'quote': self.whatsapp.sign_choice(context, choice_id, result.expires_at)}))
        if not choices:
            return self.reply('QUOTE', 'No eligible services returned for this route. Check the details in Create a shipment or contact support.', status='NEEDS_INPUT')
        if result.partial:
            lines.append('Some connected providers did not return an eligible rate.')
        async with self.pool.acquire() as connection:
            tenant = await connection.fetchrow('SELECT billing_plan FROM public.tenants WHERE tenant_id=$1', context.tenant_id)
            wallet = await connection.fetchrow('SELECT currency,balance,reserved_balance FROM public.wallets WHERE tenant_id=$1', context.tenant_id)
        if tenant and tenant['billing_plan'] == 'PREPAID_WALLET' and (not wallet or wallet['currency'] != rating.currency
                or wallet['balance'] - wallet['reserved_balance'] < min(rate.client_price_ex_tax for rate in result.rates[:10])):
            lines.append('Your wallet balance is too low for these options. Arrange a top-up before booking.')
        if sandbox:
            lines.append('TEST environment: no live label or live payment is promised.')
        lines.append(f'Options expire at {result.expires_at.isoformat()}. Complete packing and customs review is required for international goods.')
        return self.reply('QUOTE', '\n'.join(lines), _choices=choices)

    async def collect_uk_premise(self, draft: ConversationDraft, prefix: str):
        from backend.paf_lookup import PAFLookupUnavailable, uk_postcode
        try:
            postcode = uk_postcode(getattr(draft.intent, prefix + '_postal_code'))
            client = getattr(self.state, 'paf', None)
            if client is None:
                raise PAFLookupUnavailable('UK address lookup is not configured. Use Create a shipment or contact support.')
            options = await client.lookup(postcode)
            if not options:
                draft.waiting_for = 'postcodes'
                return self.pending_reply(draft, 'No PAF premises were found for that UK postcode. Check it and reply with Origin Postcode, Destination Postcode.')
            draft.paf_prefix, draft.paf_options, draft.paf_offset = prefix, options, 0
            draft.waiting_for = 'paf_selection'
            return self.pending_reply(draft, self.draft_prompt(draft))
        except PAFLookupUnavailable as error:
            draft.waiting_for = 'paf_retry'
            return self.pending_reply(draft, str(error))
        except ValueError:
            draft.waiting_for = 'postcodes'
            return self.pending_reply(draft, 'Enter a complete UK postcode. Reply with Origin Postcode, Destination Postcode.')

    async def trigger_return(self, context, body, intent, message_id):
        if context.role not in DISPATCH_ROLES:
            raise HTTPException(403, 'A dispatch role is required to create returns')
        if not intent.target_reference_id:
            draft = ConversationDraft(action='TRIGGER_RETURN',intent=intent,waiting_for='reference',
                assistance_id=str(context.assistance_session_id) if getattr(context,'assistance_session_id',None) else None)
            return self.pending_reply(draft,self.draft_prompt(draft))
        explicit = re.fullmatch(r'\s*(?:create\s+a\s+return\s+for|return)(?:\s+(?:order|tracking|shipment))?\s+([A-Za-z0-9_-]{1,200})\s*',body.message_body,re.I)
        draft = getattr(self,'draft',None)
        if not ((explicit and explicit[1]==intent.target_reference_id) or
                (draft and draft.action=='TRIGGER_RETURN' and body.message_body.strip()==intent.target_reference_id)):
            return self.reply('TRIGGER_RETURN','To create a retailer-paid return, send: Return order EINVIO-1024.',status='NEEDS_INPUT')
        from backend.reverse_logistics import ReverseLogisticsService, ReturnCommand
        shipment = await self.shipment(context,intent.target_reference_id)
        result = await ReverseLogisticsService(self.state.partner_lifecycle).process(context,
            ReturnCommand(idempotency_key=message_id,shipment_id=shipment['id']),source=body.channel)
        if result.get('status')!='BOOKED':
            return self.reply('TRIGGER_RETURN',result.get('message','Your return needs review. Check Shipments before trying again.'),status='REVIEW_REQUIRED',return_request=result)
        if result.get('paperless_available') and not result.get('qr_requires_workspace_login',True):
            text = (f'Return initiated for {intent.target_reference_id}. Use a participating drop-off location for the selected carrier. '
                'Display this carrier drop-off document on your phone; no printer is required:\n'+result['return_dropoff_qr_code_url'])
        else:
            text = (f'Return initiated for {intent.target_reference_id}. '+
                ('A paperless document is available in your signed-in workspace.' if result.get('paperless_available') else
                 'This service requires a printed label. Open Shipments to download it and check the selected carrier’s drop-off locations.'))
        return self.reply('TRIGGER_RETURN',text,return_request=result,media_urls=result.get('media_urls',[]))

    async def manifest(self,context,body,intent,message_id):
        if context.role not in DISPATCH_ROLES:raise HTTPException(403,'Dispatch permission required')
        service=self.state.manifests
        if intent.intent=='MANIFEST_STATUS':
            summaries=await service.get_manifestable_summary(context.tenant_id)
            async with self.pool.acquire() as connection:
                recent=await connection.fetch('''SELECT id FROM public.carrier_manifests WHERE tenant_id=$1
                  ORDER BY created_at DESC,id DESC LIMIT 5''',context.tenant_id)
            lines=[f'{s.carrier_code}: {s.total_shipments} unmanifested shipments, {s.total_weight_kg:.3f} kg, pickup {s.origin_postcode}' for s in summaries]
            for row in recent:
                result=await service.status(context.tenant_id,row['id'],context.user_id)
                lines.append(f'{result.carrier_code} manifest {result.id}: {result.status}'+('\n'+result.manifest_document_url if result.manifest_document_url else ''))
            return self.reply('MANIFEST_STATUS','\n'.join(lines) or 'No booked shipments or manifests are available.')
        explicit=re.fullmatch(r'\s*close\s+manifest\s+([A-Za-z0-9 _-]{1,50})\s*',body.message_body,re.I)
        if not explicit:raise HTTPException(422,'To close a batch, send Close manifest followed by the carrier name.')
        from backend.carrier_consolidation import carrier_identity
        matches=[s for s in await service.get_manifestable_summary(context.tenant_id) if carrier_identity(s.carrier_code)==carrier_identity(explicit[1].strip())]
        if len(matches)!=1:
            return self.reply('CLOSE_MANIFEST','No unique carrier/warehouse batch matches. Open the dispatch manifest preview to choose an account and pickup warehouse.',status='NEEDS_INPUT')
        result=await service.close_manifest(context.tenant_id,matches[0].carrier_account_id,context.user_id,
            request_id=message_id,carrier_code=matches[0].carrier_code)
        return self.reply('CLOSE_MANIFEST',f'{result.carrier_code}: {result.status}. {result.total_shipments} shipments, {result.total_weight_kg:.3f} kg.\n{result.message}'
            + ('\n'+result.manifest_document_url if result.manifest_document_url else ''),manifest=result.model_dump(mode='json'))

    async def shipment(self, context, reference):
        if not reference:
            raise HTTPException(422, 'Please provide the shipment or tracking reference')
        async with self.pool.acquire() as connection:
            rows = await connection.fetch('''SELECT id,customer_reference,tracking_number,status FROM public.shipments
                WHERE tenant_id=$1 AND (id::text=$2 OR customer_reference=$2 OR tracking_number=$2) LIMIT 2''',
                context.tenant_id, reference)
        if len(rows) != 1:
            raise HTTPException(404, 'No unique shipment with that reference was found in your workspace')
        return rows[0]

    async def claim(self, context, body, intent, message_id):
        from backend.shipment_protection import insured_shipment, require_claim_role
        require_claim_role(context)
        explicit = re.fullmatch(r'\s*claim\s+([A-Za-z0-9_-]{1,200})\s+(lost|damaged)\s+(.{10,1800})\s*', body.message_body, re.I | re.S)
        draft = getattr(self, 'draft', None)
        source = draft.intent.description_notes if draft and draft.action == 'FILE_CLAIM' else body.message_body.strip()
        short = re.fullmatch(r'(?:my\s+)?(?:package|parcel|shipment)(?:\s+is)?\s+(lost|damaged)\s*[.!]?', source or '', re.I)
        if not intent.target_reference_id and short:
            draft = ConversationDraft(action='FILE_CLAIM', intent=intent.model_copy(update={'description_notes': source}),
                waiting_for='reference', assistance_id=str(context.assistance_session_id) if context.assistance_session_id else None)
            return self.pending_reply(draft, self.draft_prompt(draft))
        if short and draft:
            reason = 'PARCEL_LOST' if short[1].lower() == 'lost' else 'PARCEL_DAMAGED'
            intent = intent.model_copy(update={'description_notes': source})
        elif explicit and explicit[1] == intent.target_reference_id and explicit[3].strip() == intent.description_notes:
            reason = 'PARCEL_LOST' if explicit[2].lower() == 'lost' else 'PARCEL_DAMAGED'
        else:
            return self.reply('FILE_CLAIM', 'To record a support case, send: Claim TRACKING123 lost Describe what happened. Use damaged for damage. Photos and insurer filing are completed in Shipment protection & claims.', status='NEEDS_INPUT')
        shipment = await self.shipment(context, intent.target_reference_id)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                _, policy = await insured_shipment(connection, context.tenant_id, shipment['id'])
                # Intake only. Do not fabricate insurer review, delivery events,
                # settlement, submission or a new shipment-status enum value.
                await connection.execute('''INSERT INTO public.insurance_claim_cases
                    (id,tenant_id,shipment_id,policy_id,reason,notes,created_by,payload_sha256,state)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,'CLAIM_INGESTED')''', message_id, context.tenant_id,
                    shipment['id'], policy['policy_id'], reason, intent.description_notes, context.user_id,
                    hashlib.sha256(body.message_body.encode()).hexdigest())
                ticket_id = uuid4()
                await connection.execute('''INSERT INTO public.support_tickets
                    (id,tenant_id,shipment_id,insurance_claim_id,status,ai_summary,ai_method,prompt_version)
                    VALUES($1,$2,$3,$4,'OPEN',$5,'CUSTOMER_CLAIM','conversation-intake-v1')''',
                    ticket_id, context.tenant_id, shipment['id'], message_id,
                    'Claim support intake only. Insurer submission is not confirmed. ' + intent.description_notes)
        link = self.claim_panel_url(message_id)
        text = ('Your claim support case has been recorded. Insurer submission, review and payment are not confirmed. '
            + ('Sign in to your workspace on your laptop to upload evidence and complete filing:\n' + link if link
               else 'Open Shipment protection & claims to supply evidence and complete insurer filing.'))
        return self.reply('FILE_CLAIM', text, claim_id=str(message_id), **({'claim_panel_url': link} if link else {}))

    def claim_panel_url(self, case_id):
        from urllib.parse import urlencode
        base = getattr(self.state.settings, 'auth_recovery_redirect_url', '')
        try:
            parsed = urlsplit(base)
            if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}))):
                return None
            return urljoin(base, '/') + '?' + urlencode({'claim_id': str(case_id)})
        except ValueError:
            return None


async def signed_whatsapp_message(request, context, form, *, conversational=True):
    """Only call after authenticated_twilio_form and resolve_sender succeed."""
    sender = form['From'].removeprefix('whatsapp:')
    gateway = ConversationalActionGateway(request)
    body = ConversationMessage(sender_id=sender, message_body=form['Body'], channel='WHATSAPP',
        request_id=uuid5(NAMESPACE_URL, 'twilio:' + form['MessageSid']))
    result = await gateway.process(context, body, verified_whatsapp=True)
    return message_xml(result['conversational_reply'])


def build_router(authenticate):
    router = APIRouter(tags=['Conversational logistics'])

    @router.post('/api/v1/conversational/process-message')
    async def process_message(body: ConversationMessage, request: Request, context=Depends(authenticate)):
        if body.channel != 'WEB_CHAT':
            raise HTTPException(403, 'Use the signed Twilio WhatsApp webhook for phone authentication')
        from main import validate_tenant_query
        validate_tenant_query(request, context.tenant_id)
        try:
            result = await ConversationalActionGateway(request).process(context, body)
        except (asyncpg.PostgresError, TimeoutError):
            logger.warning('conversation_storage_unavailable')
            raise HTTPException(503, 'The action could not be confirmed. Check your workspace before retrying.') from None
        except HTTPException:
            raise
        except Exception as error:
            logger.warning('conversation_action_unconfirmed error_type=%s', type(error).__name__)
            raise HTTPException(503, 'The action could not be confirmed. Check your workspace before retrying.') from None
        return Response(json.dumps(result), media_type='application/json', headers={'Cache-Control': 'no-store'})

    return router
