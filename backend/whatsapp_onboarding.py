"""Signed-phone registration with separate email proof and native Auth identities.

No model handles identity or verification codes. Provider IO occurs outside SQL
transactions. An uncertain Auth verification is fenced for operator review.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from backend.admin_portal import CompanyProfile
from backend.workspace_personas import PersonalProfile, storage_profile
from backend.ai_engine import country_code
from backend.whatsapp_bot import xml_message

PERSONA_PROMPT = ("Welcome to EasyInvio! Are you registering as a Business or an Individual? "
    "Please reply with '1' for Business or '2' for Individual.")

TERMINAL = {'EXPIRED', 'CANCELLED', 'LOCKED'}
COMPANY_PROMPT = ('Welcome to EasyInvio. To register, reply with your legal company name, registration number and country, '
    'separated by commas. Example: Example Trading Ltd, 12345678, GB. Company details are recorded, not independently verified. '
    'Reply Cancel at any time before activation.')
PROFILE_PROMPT = ('Please reply with your full name; billing street address; city; postal code; YES '
    '(separate each part with a semicolon). YES confirms you are authorised to register this company. '
    'Example: Alex Smith; 1 Example Road; Leeds; LS1 1AA; YES')
OTP_PROMPT = ('Reply here in WhatsApp with the full numeric code from your EMAIL (6 to 10 digits), then a space, '
    'then the separate six-digit WHATSAPP code. Example format: 12345678 654321. '
    'Do not reply by email or click an email verification link. Codes expire after 15 minutes. '
    'Never send a password. Reply Resend for new codes.')


def now():
    return datetime.now(timezone.utc)


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


class SupabaseSignupProvider:
    """Use supported GoTrue endpoints; never write directly to auth.users."""
    def __init__(self, settings, client):
        self.settings, self.client = settings, client

    async def request(self, method, path, payload, *, admin=False, params=None):
        key = (self.settings.supabase_service_role_key if admin else self.settings.supabase_publishable_key).get_secret_value()
        headers = {'apikey': key}
        if admin:
            headers['Authorization'] = 'Bearer ' + key
        try:
            response = await self.client.request(method, self.settings.supabase_url + '/auth/v1/' + path,
                headers=headers, json=payload, params=params, timeout=5, follow_redirects=False)
        except httpx.HTTPError:
            raise HTTPException(503, 'Email verification could not be confirmed. Reply Status or contact support.') from None
        if response.status_code == 429:
            raise HTTPException(429, 'Email delivery is rate limited. Wait before trying again.')
        if response.status_code not in (200, 201, 204):
            raise HTTPException(503, 'The authentication provider could not complete registration. Contact support.')
        if response.status_code == 204:
            return {}
        try:
            return response.json()
        except ValueError:
            raise HTTPException(503, 'The authentication response could not be verified.') from None

    async def send_code(self, email):
        """Supabase issues the OTP and uses its configured SendGrid SMTP/template.

        Sender identity and SMTP credentials are project-level Auth configuration,
        not fields accepted by the public OTP endpoint. Never generate or email a
        competing local email code or insert a fabricated identity into auth.users.
        """
        await self.request('POST', 'otp', {'email': email, 'create_user': True})

    async def verify(self, email, code):
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6,10}', code):
            return None
        # Invalid codes and provider outages are deliberately distinct outcomes.
        key = self.settings.supabase_publishable_key.get_secret_value()
        try:
            response = await self.client.post(self.settings.supabase_url + '/auth/v1/verify',
                headers={'apikey': key}, json={'email': email, 'token': code, 'type': 'email'}, timeout=5)
        except httpx.HTTPError:
            raise HTTPException(503, 'Verification outcome is uncertain. Contact support; do not start another registration.') from None
        if response.status_code in (400, 401, 403, 422):
            return None
        if response.status_code != 200:
            raise HTTPException(503, 'Verification could not be confirmed. Contact support.')
        try:
            user = response.json()['user']
            user_id = UUID(user['id'])
            if user.get('email', '').casefold() != email or not user.get('email_confirmed_at'):
                raise ValueError()
            # Discard the returned access/refresh tokens; WhatsApp is not a web login.
            return user_id
        except (KeyError, TypeError, ValueError):
            raise HTTPException(503, 'Verified identity did not match this registration.') from None

    async def bind_workspace(self, user_id, tenant_id, email):
        user = await self.request('GET', 'admin/users/' + str(user_id), None, admin=True)
        if UUID(user['id']) != user_id or user.get('email', '').casefold() != email or not user.get('email_confirmed_at'):
            raise HTTPException(409, 'Account identity requires operator review')
        metadata = user.get('app_metadata') or {}
        if metadata.get('tenant_id') not in (None, str(tenant_id)):
            raise HTTPException(409, 'This identity already belongs to a workspace. Contact support.')
        result = await self.request('PUT', 'admin/users/' + str(user_id),
            {'app_metadata': {**metadata, 'tenant_id': str(tenant_id), 'role': 'OWNER'}}, admin=True)
        if str(result.get('id')) != str(user_id) or (result.get('app_metadata') or {}).get('tenant_id') != str(tenant_id):
            raise HTTPException(503, 'Workspace identity update needs reconciliation')

    async def password_email(self, email):
        """Ask Auth to generate and email a single-use recovery credential.

        The configured Reset Password template maps RedirectTo and TokenHash to
        the SPA's fragment contract. No recovery credential is returned to chat.
        """
        redirect = self.settings.auth_recovery_redirect_url
        try:
            if not isinstance(redirect, str) or any(character.isspace() or ord(character) < 32 for character in redirect):
                return False
            parsed = urlsplit(redirect)
            port = parsed.port
            local = parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'}
            if (not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query
                    or '\\' in redirect or (port is not None and port == 0)
                    or (parsed.scheme != 'https' and not local)):
                return False
        except ValueError:
            return False
        try:
            await self.request('POST', 'recover', {'email': email}, params={'redirect_to': redirect})
            return True
        except HTTPException:
            return False


class ConversationalSignupManager:
    def __init__(self, pool, settings, provider):
        self.pool, self.settings, self.provider = pool, settings, provider
        self.secret = settings.quote_link_secret.get_secret_value().encode()
        if len(self.secret) < 32:
            raise ValueError('Registration requires a strong configured signing secret')
        if not settings.credential_keys:
            raise ValueError('Registration requires a configured encryption key ring')
        self.key_id = sorted(settings.credential_keys)[0]
        self.cipher = Fernet(settings.credential_keys[self.key_id].get_secret_value().encode())

    def digest(self, purpose, text):
        return hmac.new(self.secret, ('signup:' + purpose + ':' + text).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def company(text):
        parts = [part.strip() for part in text.rsplit(',', 2)]
        if len(parts) != 3 or not 1 <= len(parts[0]) <= 200 or any(ord(ch) < 32 for ch in parts[0]):
            raise ValueError('Reply with company name, registration number, country. Example: Example Ltd, 12345678, GB')
        registration = re.sub(r'[ -]', '', parts[1]).upper()
        if not re.fullmatch(r'[A-Z0-9]{2,100}', registration):
            raise ValueError('Use the registration number as shown on the company register, using letters and digits.')
        return parts[0], registration, country_code(parts[2])

    @staticmethod
    def profile(text):
        parts = [part.strip() for part in text.split(';')]
        limits = (200, 200, 100, 30)
        if len(parts) != 5 or parts[-1].upper() != 'YES' or any(not 1 <= len(value) <= limit or any(ord(ch) < 32 for ch in value) for value, limit in zip(parts[:4], limits)):
            raise ValueError(PROFILE_PROMPT)
        return dict(zip(('contact_name', 'address_line1', 'city', 'postal_code'), parts[:4]))

    async def ready(self, c):
        if not await c.fetchval("SELECT to_regclass('public.whatsapp_registration_queue') IS NOT NULL AND to_regclass('public.whatsapp_registration_receipts') IS NOT NULL"):
            raise HTTPException(503, 'Conversational registration is awaiting database migration 039')

    async def replay(self, form):
        sender, receiver = self.phones(form)
        async with self.pool.acquire() as c:
            await self.ready(c)
            row = await c.fetchrow('SELECT * FROM public.whatsapp_registration_receipts WHERE message_sid=$1', form['MessageSid'])
        if not row:
            return None
        return self.receipt_reply(form, row)

    def receipt_reply(self, form, row):
        sender, receiver = self.phones(form)
        if row['phone_e164'] != sender or row['receiver_e164'] != receiver or not hmac.compare_digest(row['input_hmac'], self.digest('input', form['Body'])):
            raise HTTPException(403, 'Registration delivery identity does not match')
        if not row['reply_ciphertext']:
            return xml_message('This registration step is processing or needs review. Reply Status before sending codes again.')
        if row['created_at'] < now() - timedelta(minutes=15):
            return xml_message('This earlier registration response has expired. Reply Status for the current step.')
        try:
            key = self.settings.credential_keys[row['key_id']].get_secret_value().encode()
            return Fernet(key).decrypt(bytes(row['reply_ciphertext'])).decode()
        except (KeyError, InvalidToken, UnicodeError):
            raise HTTPException(503, 'Registration receipt needs operator review') from None

    @staticmethod
    def phones(form):
        sender, receiver = (form[key].removeprefix('whatsapp:') for key in ('From', 'To'))
        if any(not re.fullmatch(r'\+[1-9][0-9]{7,14}', value) for value in (sender, receiver)):
            raise HTTPException(403, 'Verified international phone numbers required')
        return sender, receiver

    async def handle(self, form):
        """Called only after signature validation and failed active binding lookup."""
        cached = await self.replay(form)
        if cached:
            return cached
        sender, receiver = self.phones(form)
        text, sid = form['Body'].strip(), form['MessageSid']
        queue = None
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'signup:' + sender + ':' + receiver)
                prior = await c.fetchrow('SELECT * FROM public.whatsapp_registration_receipts WHERE message_sid=$1', sid)
                if prior:
                    return self.receipt_reply(form, prior)
                if await c.fetchval('''SELECT count(*)>=30 FROM public.whatsapp_registration_receipts
                    WHERE phone_e164=$1 AND created_at>now()-interval '1 hour' ''', sender):
                    return xml_message('Too many registration messages. Wait an hour or contact support.')
                # An inactive/ambiguous existing account is never a new signup.
                if await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.whatsapp_bindings WHERE sender_e164=$1)', sender):
                    return xml_message('This number is already linked to an account. Ask your workspace owner or support to check its access. Registration cannot reactivate it.')
                await c.execute("UPDATE public.whatsapp_registration_queue SET current_state='EXPIRED',phone_otp_hmac=NULL WHERE expires_at<now() AND current_state NOT IN ('VERIFIED','PROVISIONING','RECONCILIATION_REQUIRED','EXPIRED','CANCELLED','LOCKED') AND (lease_until IS NULL OR lease_until<now())")
                queue = await c.fetchrow("SELECT * FROM public.whatsapp_registration_queue WHERE phone_e164=$1 AND receiver_e164=$2 AND current_state NOT IN ('EXPIRED','CANCELLED','LOCKED') FOR UPDATE", sender, receiver)
                if queue and queue['lease_until'] and queue['lease_until'] > now():
                    return xml_message('Your previous registration step is processing. Wait before replying.')
                await c.execute('INSERT INTO public.whatsapp_registration_receipts(message_sid,phone_e164,receiver_e164,input_hmac) VALUES($1,$2,$3,$4)',
                    sid, sender, receiver, self.digest('input', form['Body']))
                if queue is None:
                    if text.casefold() not in {'hello', 'hi', 'register', 'start'}:
                        answer = 'This number is not registered. Reply Register to start a new account signup, or contact your existing workspace owner.'
                    else:
                        await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'signup-start:' + receiver)
                        count = await c.fetchval("SELECT count(*) FROM public.whatsapp_registration_queue WHERE phone_e164=$1 AND created_at>now()-interval '1 day'", sender)
                        total = await c.fetchval("SELECT count(*) FROM public.whatsapp_registration_queue WHERE receiver_e164=$1 AND created_at>now()-interval '1 day'", receiver)
                        if count >= 3 or total >= self.settings.whatsapp_onboarding_daily_limit:
                            answer = 'Registration limit reached. Contact support or try again tomorrow.'
                        else:
                            await c.execute("INSERT INTO public.whatsapp_registration_queue(phone_e164,receiver_e164,current_state) VALUES($1,$2,'PENDING_PERSONA')", sender, receiver)
                            answer = PERSONA_PROMPT
                    await self.finish(c, sid, answer)
                    return xml_message(answer)
                if text.casefold() == 'cancel':
                    if queue['current_state'] in {'PROVISIONING', 'RECONCILIATION_REQUIRED', 'VERIFIED'}:
                        answer = 'Account setup has reached verification. Contact support to review it; this command cannot delete an identity or workspace.'
                    else:
                        await c.execute("UPDATE public.whatsapp_registration_queue SET current_state='CANCELLED',phone_otp_hmac=NULL,updated_at=now() WHERE id=$1", queue['id'])
                        answer = 'Registration cancelled. No company workspace has been activated.'
                    await self.finish(c, sid, answer)
                    return xml_message(answer)
                await c.execute("UPDATE public.whatsapp_registration_queue SET busy_message_sid=$2,lease_until=now()+interval '30 seconds',updated_at=now() WHERE id=$1", queue['id'], sid)
        try:
            answer = await self.advance(dict(queue), text)
        except (ValueError, HTTPException) as error:
            answer = str(error.detail) if isinstance(error, HTTPException) else str(error)
        except asyncpg.UniqueViolationError:
            answer = 'These company or email details are already in use or awaiting verification. Use the existing account or contact support.'
        except (asyncpg.PostgresError, KeyError, TypeError):
            answer = 'Registration storage needs review. Reply Status or contact support; no successful activation is confirmed.'
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute('UPDATE public.whatsapp_registration_queue SET busy_message_sid=NULL,lease_until=NULL,updated_at=now() WHERE id=$1 AND busy_message_sid=$2', queue['id'], sid)
                await self.finish(c, sid, answer)
        return xml_message(answer)

    async def finish(self, c, sid, answer):
        await c.execute('UPDATE public.whatsapp_registration_receipts SET reply_ciphertext=$2,key_id=$3 WHERE message_sid=$1', sid, self.cipher.encrypt(xml_message(answer).encode()), self.key_id)

    async def duplicate(self, c, registration, country, email=None, own_id=None):
        return await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.tenants WHERE
            ((country_code=$1 OR country_code IS NULL) AND regexp_replace(upper(company_registration_number),'[^A-Z0-9]','','g')=$2)
            OR ($3::text IS NOT NULL AND lower(billing_email)=$3)) OR EXISTS(
            SELECT 1 FROM public.whatsapp_registration_queue WHERE id<>$4
            AND current_state NOT IN ('EXPIRED','CANCELLED','LOCKED','VERIFIED') AND
            ((country_code=$1 AND company_reg_number=$2) OR ($3::text IS NOT NULL AND lower(email_address)=$3)))''', country, registration, email, own_id)

    async def email_identity_blocked(self, c, email, queue):
        """Only resume our own unfinished Auth creation, never an existing account.

        Auth creates a provisional identity before email verification. Prior signed
        signup evidence must tie its creation time to this phone/receiver's send.
        Both fresh codes are still required; no identity is deleted or overwritten.
        """
        return await c.fetchval('''SELECT EXISTS(SELECT 1 FROM auth.users u WHERE lower(u.email)=$1 AND (
            u.deleted_at IS NOT NULL OR u.banned_until>now() OR u.id=ANY($4::uuid[])
            OR u.raw_app_meta_data->>'tenant_id' IS NOT NULL OR u.raw_app_meta_data->>'role' IS NOT NULL
            OR EXISTS(SELECT 1 FROM public.users m WHERE m.auth_user_id=u.id)
            OR EXISTS(SELECT 1 FROM public.app_user_profiles p WHERE p.auth_user_id=u.id)
            OR NOT EXISTS(SELECT 1 FROM public.whatsapp_registration_queue q
                WHERE lower(q.email_address)=$1 AND q.phone_e164=$2 AND q.receiver_e164=$3
                AND q.send_attempts>0 AND q.last_sent_at IS NOT NULL
                AND q.auth_user_id IS NULL
                AND q.current_state IN ('SENDING_EMAIL','PENDING_OTP','EXPIRED','CANCELLED','LOCKED','PENDING_EMAIL')
                AND u.created_at>=q.created_at AND u.created_at<=q.last_sent_at+interval '1 minute')
            ))''', email, queue['phone_e164'], queue['receiver_e164'], list(self.settings.platform_admin_user_ids))

    async def advance(self, queue, text):
        state = queue['current_state']
        if state == 'PROVISIONING' and queue['expires_at'] <= now():
            async with self.pool.acquire() as c:
                await c.execute("UPDATE public.whatsapp_registration_queue SET current_state='RECONCILIATION_REQUIRED' WHERE id=$1", queue['id'])
            return 'Your verified setup window has expired. Contact support to complete this registration securely.'
        if state == 'PENDING_PERSONA':
            if text.strip().casefold() in {'1', 'business'}:
                async with self.pool.acquire() as c:
                    await c.execute("UPDATE public.whatsapp_registration_queue SET workspace_type='BUSINESS',current_state='PENDING_COMPANY',updated_at=now() WHERE id=$1", queue['id'])
                return COMPANY_PROMPT
            if text.strip().casefold() in {'2', 'individual', 'personal'}:
                async with self.pool.acquire() as c:
                    await c.execute("UPDATE public.whatsapp_registration_queue SET workspace_type='INDIVIDUAL',current_state='PENDING_EMAIL',updated_at=now() WHERE id=$1", queue['id'])
                return 'Please reply with your personal Email Address to receive your verification code. The email code can contain 6 to 10 digits.'
            return PERSONA_PROMPT
        if state == 'PENDING_COMPANY':
            if text.casefold() in {'hello', 'register', 'status', 'hi'}:
                return COMPANY_PROMPT
            name, registration, country = self.company(text)
            async with self.pool.acquire() as c:
                async with c.transaction():
                    if await self.duplicate(c, registration, country, own_id=queue['id']):
                        return 'These company details are already linked to an account or registration. Contact the workspace owner or support.'
                    await c.execute("UPDATE public.whatsapp_registration_queue SET company_name=$2,company_reg_number=$3,country_code=$4,current_state='PENDING_PROFILE',updated_at=now() WHERE id=$1", queue['id'], name, registration, country)
            return 'Company details recorded. ' + PROFILE_PROMPT
        if state == 'PENDING_PROFILE':
            if text.casefold() == 'status':
                return PROFILE_PROMPT
            profile = self.profile(text)
            async with self.pool.acquire() as c:
                await c.execute("UPDATE public.whatsapp_registration_queue SET profile=$2::jsonb,current_state='PENDING_EMAIL',updated_at=now() WHERE id=$1", queue['id'], json.dumps(profile))
            return 'Please reply with your billing email address. We will send an email verification code. You must have access to that inbox.'
        if state == 'PENDING_EMAIL':
            email = text.casefold()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(email) > 254:
                return 'Enter your email address, for example alex@example.com.'
            async with self.pool.acquire() as c:
                async with c.transaction():
                    if await self.duplicate(c, queue['company_reg_number'], queue['country_code'], email, queue['id']) or await self.email_identity_blocked(c, email, queue):
                        return 'These details are already associated with an account or registration. Sign in on the website or contact support; this chat cannot take over an existing account.'
                    await c.execute('UPDATE public.whatsapp_registration_queue SET email_address=$2 WHERE id=$1', queue['id'], email)
            queue['email_address'] = email
            return await self.send_codes(queue)
        if state in {'PENDING_OTP', 'SENDING_EMAIL'}:
            if text.casefold() in {'resend', queue['email_address']}:
                return await self.send_codes(queue)
            if state == 'SENDING_EMAIL':
                return 'Email delivery has not been confirmed. Wait one minute, then reply Resend, or contact support.'
            if text.casefold() == 'status':
                return OTP_PROMPT
            if not queue['otp_expires_at'] or queue['otp_expires_at'] <= now() or queue['attempts'] >= 5:
                await self.lock(queue)
                return 'Verification expired or the attempt limit was reached. Contact support or start again later.'
            codes = re.fullmatch(r'([0-9]{6,10})\s+([0-9]{6})', text)
            if not codes:
                return 'Please send both codes in the expected format. ' + OTP_PROMPT
            async with self.pool.acquire() as c:
                await c.execute('UPDATE public.whatsapp_registration_queue SET attempts=attempts+1 WHERE id=$1 AND attempts<5', queue['id'])
            if not hmac.compare_digest(self.digest(str(queue['id']), codes[2]), queue['phone_otp_hmac'] or ''):
                if queue['attempts'] + 1 >= 5:
                    await self.lock(queue)
                return 'The verification codes did not match. ' + OTP_PROMPT
            # Write-ahead uncertainty fence before a one-time external verification.
            async with self.pool.acquire() as c:
                await c.execute("UPDATE public.whatsapp_registration_queue SET current_state='RECONCILIATION_REQUIRED' WHERE id=$1", queue['id'])
            user_id = await self.provider.verify(queue['email_address'], codes[1])
            if user_id is None:
                async with self.pool.acquire() as c:
                    await c.execute("UPDATE public.whatsapp_registration_queue SET current_state=$2 WHERE id=$1", queue['id'], 'LOCKED' if queue['attempts'] + 1 >= 5 else 'PENDING_OTP')
                return 'The email code was rejected or expired. ' + OTP_PROMPT
            if user_id in self.settings.platform_admin_user_ids:
                raise HTTPException(409, 'This identity requires administrator review')
            async with self.pool.acquire() as c:
                await c.execute("UPDATE public.whatsapp_registration_queue SET auth_user_id=$2,current_state='PROVISIONING',phone_otp_hmac=NULL,updated_at=now() WHERE id=$1", queue['id'], user_id)
            queue['auth_user_id'] = user_id
            return ('Both codes are verified. Reply with your full name to finish creating your personal workspace.' if queue.get('workspace_type') == 'INDIVIDUAL'
                else 'Both codes are verified. Reply Continue to finish creating your workspace. No funds or shipping labels have been created.')
        if state == 'PROVISIONING':
            if queue.get('workspace_type') == 'INDIVIDUAL' and not decoded(queue['profile']).get('full_name'):
                if text.strip().casefold() in {'continue','status','hello','register'}:
                    return 'Please reply with your full name to finish your personal account setup.'
                profile = PersonalProfile(full_name=text, billing_email=queue['email_address'], phone_e164=queue['phone_e164'])
                queue['profile'] = profile.model_dump(mode='json')
                async with self.pool.acquire() as c:
                    await c.execute('UPDATE public.whatsapp_registration_queue SET profile=$2::jsonb WHERE id=$1', queue['id'], profile.model_dump_json())
            return await self.provision(queue)
        if state == 'VERIFIED':
            return 'Registration was completed. Ask support to check your WhatsApp binding if workspace access is unavailable.'
        return 'This registration requires support review. No automatic activation or retry is allowed.'

    async def send_codes(self, queue):
        if queue['send_attempts'] >= 3 or queue['attempts'] >= 5:
            await self.lock(queue)
            return 'Verification limit reached. Contact support or try registration again later.'
        if queue['last_sent_at'] and now() - queue['last_sent_at'] < timedelta(seconds=60):
            return 'Wait at least one minute before requesting another code.'
        code = f'{secrets.randbelow(1000000):06d}'
        async with self.pool.acquire() as c:
            await c.execute("UPDATE public.whatsapp_registration_queue SET current_state='SENDING_EMAIL',phone_otp_hmac=$2,otp_expires_at=now()+interval '15 minutes',expires_at=now()+interval '15 minutes',send_attempts=send_attempts+1,last_sent_at=now(),updated_at=now() WHERE id=$1",
                queue['id'], self.digest(str(queue['id']), code))
        await self.provider.send_code(queue['email_address'])
        async with self.pool.acquire() as c:
            await c.execute("UPDATE public.whatsapp_registration_queue SET current_state='PENDING_OTP' WHERE id=$1", queue['id'])
        return 'The email provider accepted a verification email for delivery. Your separate WhatsApp code is ' + code + '. ' + OTP_PROMPT

    async def lock(self, queue):
        async with self.pool.acquire() as c:
            await c.execute("UPDATE public.whatsapp_registration_queue SET current_state='LOCKED',phone_otp_hmac=NULL WHERE id=$1", queue['id'])

    async def provision(self, queue):
        user_id, tenant_id = queue['auth_user_id'], queue['tenant_id']
        async with self.pool.acquire() as c:
            if await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)', user_id):
                raise HTTPException(409, 'This identity already has a membership. Account setup needs support review.')
        individual = queue.get('workspace_type') == 'INDIVIDUAL'
        profile = storage_profile(PersonalProfile.model_validate(decoded(queue['profile']))) if individual else CompanyProfile(
            company_name=queue['company_name'], billing_email=queue['email_address'], country_code=queue['country_code'],
            company_registration_number=queue['company_reg_number'], **decoded(queue['profile']))
        sandbox = self.settings.database_environment == 'SANDBOX'
        if (sandbox and self.settings.provider_environment != 'TEST') or (not sandbox and self.settings.provider_environment != 'LIVE'):
            raise HTTPException(403, 'Registration environment requires administrator configuration')
        await self.provider.bind_workspace(user_id, tenant_id, queue['email_address'])
        async with self.pool.acquire() as c:
            async with c.transaction():
                # Prevent a concurrent admin/CRM tenant insertion during the final
                # duplicate check. This lock is short and contains no provider IO.
                await c.execute('LOCK TABLE public.tenants IN SHARE ROW EXCLUSIVE MODE')
                await c.execute('LOCK TABLE public.users IN SHARE ROW EXCLUSIVE MODE')
                await c.execute('LOCK TABLE public.whatsapp_bindings IN SHARE ROW EXCLUSIVE MODE')
                current = await c.fetchrow('SELECT current_state,auth_user_id FROM public.whatsapp_registration_queue WHERE id=$1 FOR UPDATE', queue['id'])
                if current['current_state'] != 'PROVISIONING' or current['auth_user_id'] != user_id:
                    raise HTTPException(409, 'Registration state changed; contact support')
                if await self.duplicate(c, queue['company_reg_number'], queue['country_code'], queue['email_address'], queue['id']):
                    raise HTTPException(409, 'Company details are already in use. Contact support.')
                if await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.whatsapp_bindings WHERE sender_e164=$1)', queue['phone_e164']):
                    raise HTTPException(409, 'The phone is already linked; contact support')
                if await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)', user_id):
                    raise HTTPException(409, 'This identity acquired another membership. Contact support.')
                await c.execute('''INSERT INTO public.tenants
                    (tenant_id,company_name,company_profile,billing_plan,default_currency,workspace_status,billing_status,is_sandbox,
                    workspace_slug,workspace_name,legal_company_name,billing_email,billing_address,country_code,company_registration_number,onboarding_source,workspace_type)
                    VALUES($1,$2,$3::jsonb,'PREPAID_WALLET','GBP','ACTIVE','ACTIVE',$4,$5,$2,CASE WHEN $10='BUSINESS' THEN $2 END,$6,$7::jsonb,$8,$9,'WHATSAPP_INGRESS',$10)''',
                    tenant_id, profile.company_name, profile.model_dump_json(), sandbox, 'tenant-' + tenant_id.hex,
                    profile.billing_email, json.dumps({'line1': profile.address_line1, 'city': profile.city,
                        'postal_code': profile.postal_code, 'country_code': profile.country_code}), profile.country_code, profile.company_registration_number, queue.get('workspace_type','BUSINESS'))
                await c.execute('INSERT INTO public.wallets(tenant_id,currency,balance,reserved_balance) VALUES($1,\'GBP\',$2,$2) ON CONFLICT(tenant_id) DO NOTHING', tenant_id, Decimal('0.00'))
                wallet = await c.fetchrow('SELECT currency,balance,reserved_balance FROM public.wallets WHERE tenant_id=$1', tenant_id)
                if not wallet or wallet['currency'] != 'GBP' or wallet['balance'] != 0 or wallet['reserved_balance'] != 0:
                    raise HTTPException(409, 'Wallet creation needs reconciliation')
                await c.execute("INSERT INTO public.users(id,tenant_id,auth_user_id,role,full_name,is_active) VALUES($1,$2,$3,'OWNER',$4,true)", queue['member_id'], tenant_id, user_id, profile.contact_name)
                await c.execute('''INSERT INTO public.app_user_profiles(auth_user_id,full_name,phone_e164) VALUES($1,$2,$3)
                    ON CONFLICT(auth_user_id) DO UPDATE SET full_name=excluded.full_name,phone_e164=excluded.phone_e164,updated_at=now()''',
                    user_id, profile.contact_name, queue['phone_e164'])
                await c.execute('''INSERT INTO public.whatsapp_bindings(tenant_id,user_id,sender_e164,receiver_e164,is_active,verified_at)
                    VALUES($1,$2,$3,$4,true,now())''', tenant_id, queue['member_id'], queue['phone_e164'], queue['receiver_e164'])
                await c.execute("UPDATE public.whatsapp_registration_queue SET current_state='VERIFIED',phone_otp_hmac=NULL,updated_at=now() WHERE id=$1", queue['id'])
        try:
            async with asyncio.timeout(1):
                delivered = await self.provider.password_email(queue['email_address'])
        except TimeoutError:
            delivered = False
        return ('Your EasyInvio workspace has been created. Your prepaid wallet balance is GBP 0.00; no free credit or carrier booking has been added. '
            + ('A password setup email was accepted for delivery. ' if delivered else 'Use Forgot password on the EasyInvio sign-in screen to request a password setup email. ')
            + 'Choose your password through that email, then sign in. Add your shipping addresses and arrange carrier and wallet funding setup before dispatching. Never send your password in WhatsApp.')


async def onboarding_manager(request):
    settings = request.app.state.settings
    if not getattr(settings, 'whatsapp_onboarding_enabled', False):
        return None
    existing = getattr(request.app.state, 'whatsapp_onboarding', None)
    if existing is not None:
        return existing
    client = request.app.state.whatsapp.rating.client
    manager = ConversationalSignupManager(request.app.state.finance.pool, settings, SupabaseSignupProvider(settings, client))
    request.app.state.whatsapp_onboarding = manager
    return manager
