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
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit, urljoin
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from twilio.twiml.messaging_response import MessagingResponse

from backend.agents.models import ConversationalIntent, StrictOutput

logger = logging.getLogger('easyinvio.conversation')
ROLES = {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}
FINANCE_ROLES = {'OWNER', 'ADMIN', 'ACCOUNTANT'}
DISPATCH_ROLES = {'OWNER', 'ADMIN', 'DISPATCHER'}


class ConversationMessage(StrictOutput):
    sender_id: str | None = Field(default=None, pattern=r'^\+[1-9][0-9]{7,14}$')
    message_body: str = Field(min_length=1, max_length=2000)
    channel: Literal['WHATSAPP', 'WEB_CHAT']
    request_id: UUID = Field(default_factory=uuid4)


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
        from main import parse_quote
        try:
            parsed = parse_quote(text)
            return ConversationalIntent(intent='QUOTE', weight_kg=str(parsed.weight_kg),
                origin_country=parsed.origin_country, destination_country=parsed.destination_country, route_code=parsed.route_code)
        except ValueError:
            pass
        # Explicit commands continue to work without a model; these are also the
        # authorization grammar for financial actions. A model cannot invent consent.
        booking = re.fullmatch(r'\s*(?:book|confirm)\s+option\s+(10|[1-9])\s*', text, re.I)
        if booking:
            return ConversationalIntent(intent='BOOK_RESERVATION', selection_index=int(booking[1]))
        topup = re.fullmatch(r'\s*(?:top\s*up|topup)\s+(?:[£€$]\s*)?([0-9]+(?:[.,][0-9]{1,2})?)(?:\s+(GBP|EUR|USD))?\s*', text, re.I)
        if topup:
            return ConversationalIntent(intent='TOPUP_WALLET', monetary_amount=Decimal(topup[1].replace(',', '.')))
        tracking = re.fullmatch(r'\s*(?:track|tracking)\s+([A-Za-z0-9_-]{1,200})\s*', text, re.I)
        if tracking:
            return ConversationalIntent(intent='TRACK_PACKAGE', target_reference_id=tracking[1])
        claim = re.fullmatch(r'\s*claim\s+([A-Za-z0-9_-]{1,200})\s+(lost|damaged)\s+(.{10,1800})\s*', text, re.I | re.S)
        if claim:
            return ConversationalIntent(intent='FILE_CLAIM', target_reference_id=claim[1], description_notes=claim[3].strip())
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

    async def process(self, context, body: ConversationMessage, *, verified_whatsapp=False):
        if context.role not in ROLES or self.pool is None:
            raise HTTPException(403, 'An active registered workspace session is required')
        if body.channel == 'WHATSAPP' and not verified_whatsapp:
            raise HTTPException(403, 'WhatsApp actions require the signed Twilio webhook')
        # sender_id is never a tenant/user selector for web chat; its identity is
        # always the authenticated browser session, including assistance audit.
        message_id = uuid5(NAMESPACE_URL, f'conversation:{context.tenant_id}:{context.user_id}:{body.channel}:{body.request_id}')
        digest = hashlib.sha256(body.model_dump_json(exclude={'request_id'}).encode()).hexdigest()
        async with self.store.receipt(context, body, message_id, digest) as (_, cached):
            if cached is not None:
                return self.public(cached)
            if body.channel == 'WHATSAPP':
                async with self.pool.acquire() as connection:
                    await connection.execute('''UPDATE public.whatsapp_bindings b SET last_inbound_at=now()
                    FROM public.users u WHERE b.tenant_id=$1 AND b.user_id=u.id AND u.tenant_id=b.tenant_id
                    AND u.auth_user_id=$2 AND b.sender_e164=$3 AND b.receiver_e164=$4 AND b.is_active AND u.is_active''',
                    context.tenant_id, context.user_id, body.sender_id, self.state.settings.twilio_whatsapp_number)
            try:
                intent = await self.interpret(context, body.message_body)
            except ValueError:
                result = self.reply('HELP', 'Please check your amount, weight or reference. Top-ups must be between 1 and 10000 in your wallet currency, with at most two decimal places.', status='NEEDS_INPUT')
                await self.store.finish(context, message_id, result)
                return self.public(result)
            try:
                result = await self.execute(context, body, intent, message_id)
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

    async def execute(self, context, body, intent, message_id):
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
                choice = await connection.fetchrow('''SELECT selected_rate FROM public.whatsapp_quote_choices
                    WHERE tenant_id=$1 AND auth_user_id=$2 AND id=$3 AND expires_at>now()''',
                    context.tenant_id, context.user_id, choice_id)
            if not choice:
                raise HTTPException(410, 'This option has expired. Request fresh rates.')
            from backend.automation_three_partners import BookingRequest
            rate = decoded(choice['selected_rate'])
            result = await self.state.partner_lifecycle.confirm(context, BookingRequest(
                tenant_id=context.tenant_id, offer_id=UUID(rate['offer_id'])))
            if result.get('status') != 'BOOKED':
                return self.reply(intent.intent, 'Your booking is still being checked. View Shipments before trying again.', status='REVIEW_REQUIRED')
            label = result.get('label') or {}
            return self.reply(intent.intent, f"Shipment booked. Tracking: {label.get('tracking_number', 'awaiting confirmation')}. Open Shipments to download the label and available customs documents.", shipment_id=result['shipment_id'])
        if intent.intent == 'TRACK_PACKAGE':
            shipment = await self.shipment(context, intent.target_reference_id)
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
            return self.reply(intent.intent, '\n'.join(lines))
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
        commands = ('You can ask for a quote using a saved route, track a shipment, book a displayed option, arrange a wallet top-up, or record a claim support case.\n'
                    'Examples: Quote 4.5kg from GB to US; Track EINVIO-00000050; Book option 1; Top up 50 GBP; Claim TRACKING123 damaged Describe what happened.')
        if engine is not None and len(body.message_body.strip()) >= 3 and body.message_body.strip().lower() not in {'help', 'hello', 'commands'}:
            answer = await engine.help.answer(context, body.message_body[:800])
            sources = answer.get('sources', [])[:3]
            excerpts = answer.get('excerpts', [])[:2]
            text = answer['answer']
            if excerpts:
                text += '\n' + '\n'.join(item['text'] for item in excerpts)
            for item in sources:
                url = item['url']
                if body.channel == 'WHATSAPP' and url.startswith('/help/'):
                    base = getattr(self.state.settings, 'booking_page_url', '')
                    parsed_base = urlsplit(base)
                    url = urljoin(base, url) if parsed_base.scheme == 'https' and parsed_base.hostname else ''
                text += '\n' + item['title'] + (': ' + url if url else ' — open Help Centre in your workspace')
            return self.reply('HELP', text + '\n\n' + commands)
        return self.reply('HELP', commands)

    async def quote(self, context, body, intent, message_id):
        from main import Address, Dimensions, ParsedQuote, RatingRequest, get_rates
        if any(getattr(intent, field) is None for field in ('weight_kg', 'origin_country', 'destination_country')):
            return self.reply('QUOTE', 'Please include the weight in kg and both countries. Add a saved route code if you have more than one route.', status='NEEDS_INPUT')
        parsed = ParsedQuote(Decimal(intent.weight_kg), intent.origin_country, intent.destination_country, intent.route_code)
        async with self.pool.acquire() as connection:
            routes = await connection.fetch('''SELECT origin_address,destination_address,dimensions,currency
                FROM public.whatsapp_routes WHERE tenant_id=$1 AND origin_country=$2 AND destination_country=$3
                AND is_active AND ($4::text IS NULL OR route_code=$4) ORDER BY route_code LIMIT 2''',
                context.tenant_id, parsed.origin_country, parsed.destination_country, parsed.route_code)
        if len(routes) != 1:
            return self.reply('QUOTE', 'No unique saved route matches. Ask your admin to save the full addresses and measured packaging, or use Create a shipment. Nothing has been booked.', status='NEEDS_INPUT')
        route = routes[0]
        rating = RatingRequest(origin=Address.model_validate(decoded(route['origin_address'])),
            destination=Address.model_validate(decoded(route['destination_address'])),
            dimensions=[Dimensions.model_validate(decoded(route['dimensions']))],
            weights_kg=[parsed.weight_kg], currency=route['currency'])
        if body.channel == 'WHATSAPP':
            result = await self.state.rating.quote(context, rating, self.state.settings.whatsapp_provider_seconds)
            async with self.pool.acquire() as connection:
                await connection.execute('''INSERT INTO public.partner_unbound_quotes
                    (tenant_id,request_id,request_payload,quote_payload,expires_at)
                    VALUES($1,$2,$3::jsonb,$4::jsonb,$5)''', context.tenant_id, result.request_id,
                    rating.model_dump_json(), result.model_dump_json(), result.expires_at)
        else:
            result = await get_rates(rating, self.request, context)
        sandbox = self.state.settings.provider_environment == 'TEST'
        lines = ['EasyInvio.com sandbox quotes' if sandbox else 'EasyInvio.com live quotes',
            f'{parsed.weight_kg}kg | {parsed.origin_country} → {parsed.destination_country}',
            'Prices exclude tax. No shipment protection is added. Sending Book option N confirms the displayed option for wallet booking.']
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
        if not explicit or explicit[1] != intent.target_reference_id or explicit[3].strip() != intent.description_notes:
            return self.reply('FILE_CLAIM', 'To record a support case, send: Claim TRACKING123 lost Describe what happened. Use damaged for damage. Photos and insurer filing are completed in Shipment protection & claims.', status='NEEDS_INPUT')
        shipment = await self.shipment(context, intent.target_reference_id)
        reason = 'PARCEL_LOST' if explicit[2].lower() == 'lost' else 'PARCEL_DAMAGED'
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
        return self.reply('FILE_CLAIM', 'Your claim support case has been recorded. Insurer submission, review and payment are not confirmed. Open Shipment protection & claims to supply evidence and complete insurer filing.', claim_id=str(message_id))


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
