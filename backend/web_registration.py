"""Email-verified public account creation; passwords and OTPs are never stored locally."""
import hashlib
import hmac
import json
import secrets
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator, field_validator

from backend.admin_portal import CompanyProfile
from backend.workspace_personas import PersonalProfile, storage_profile
from backend.whatsapp_onboarding import SupabaseSignupProvider


class RegistrationStart(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    workspace_type: Literal['BUSINESS', 'INDIVIDUAL']
    profile: CompanyProfile | PersonalProfile

    @model_validator(mode='after')
    def match_profile(self):
        if (self.workspace_type == 'INDIVIDUAL') != isinstance(self.profile, PersonalProfile):
            raise ValueError('Profile must match your selected account type')
        return self


class RegistrationVerify(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    registration_id: UUID
    registration_secret: SecretStr = Field(min_length=32, max_length=100)
    code: SecretStr
    password: SecretStr = Field(min_length=12, max_length=128)


    @field_validator('code')
    @classmethod
    def numeric_code(cls, value):
        if not re.fullmatch(r'[0-9]{6,10}', value.get_secret_value()):
            raise ValueError('Enter the full numeric email code (6 to 10 digits)')
        return value


async def start_registration(body: RegistrationStart, request: Request):
    from backend.identity import recovery_limit
    await recovery_limit(request)
    settings, pool = request.app.state.settings, request.app.state.finance.pool
    email = body.profile.billing_email.casefold()
    profile = body.profile.model_copy(update={'billing_email': email})
    secret = secrets.token_urlsafe(32)
    async with pool.acquire() as c:
        async with c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'register-email:' + email)
            blocked = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM auth.users WHERE lower(email)=$1)
                OR EXISTS(SELECT 1 FROM public.tenants WHERE lower(billing_email)=$1)
                OR EXISTS(SELECT 1 FROM public.web_registration_sessions WHERE lower(email_address)=$1
                    AND state NOT IN ('VERIFIED') AND expires_at>now())''', email)
            if blocked:
                raise HTTPException(409, 'Use your existing verification session or sign in. Contact support if setup was interrupted.')
            row = await c.fetchrow('''INSERT INTO public.web_registration_sessions
                (secret_sha256,email_address,workspace_type,profile,state) VALUES($1,$2,$3,$4::jsonb,'SENDING_EMAIL')
                RETURNING id''', hashlib.sha256(secret.encode()).hexdigest(), email, body.workspace_type, profile.model_dump_json())
    async with httpx.AsyncClient(trust_env=False) as client:
        await SupabaseSignupProvider(settings, client).send_code(email)
    async with pool.acquire() as c:
        await c.execute("UPDATE public.web_registration_sessions SET state='PENDING_OTP' WHERE id=$1 AND state='SENDING_EMAIL'", row['id'])
    return {'registration_id': str(row['id']), 'registration_secret': secret,
        'message': 'Check your email and enter the full numeric verification code (6 to 10 digits).'}


async def verify_registration(body: RegistrationVerify, request: Request):
    from backend.identity import recovery_limit
    await recovery_limit(request)
    settings, pool = request.app.state.settings, request.app.state.finance.pool
    async with pool.acquire() as c:
        async with c.transaction():
            row = await c.fetchrow('SELECT * FROM public.web_registration_sessions WHERE id=$1 FOR UPDATE', body.registration_id)
            if not row or not hmac.compare_digest(row['secret_sha256'], hashlib.sha256(body.registration_secret.get_secret_value().encode()).hexdigest()):
                raise HTTPException(400, 'Invalid verification session')
            if row['state'] == 'VERIFIED':
                return {'message': 'Account already activated. Sign in with your email and password.'}
            if row['state'] != 'PENDING_OTP' or row['attempts'] >= 5 or row['expires_at'] <= datetime.now(timezone.utc):
                raise HTTPException(409, 'Verification expired or requires review. Contact support before restarting.')
            await c.execute("UPDATE public.web_registration_sessions SET state='RECONCILIATION_REQUIRED',attempts=attempts+1 WHERE id=$1", row['id'])
    async with httpx.AsyncClient(trust_env=False) as client:
        provider = SupabaseSignupProvider(settings, client)
        user_id = await provider.verify(row['email_address'], body.code.get_secret_value())
        if user_id is None:
            async with pool.acquire() as c:
                await c.execute("UPDATE public.web_registration_sessions SET state='PENDING_OTP' WHERE id=$1", row['id'])
            raise HTTPException(400, 'The email verification code was rejected or expired')
        if user_id in settings.platform_admin_user_ids:
            raise HTTPException(409, 'This identity requires administrator review')
        async with pool.acquire() as c:
            blocked = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)
                OR EXISTS(SELECT 1 FROM public.app_user_profiles WHERE auth_user_id=$1)
                OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id=$1 AND created_at>=$2
                  AND lower(email)=$3 AND (banned_until IS NULL OR banned_until<now())
                  AND raw_app_meta_data->>'role' IS NULL AND raw_app_meta_data->>'tenant_id' IS NULL)''',
                user_id, row['created_at'], row['email_address'])
        if blocked:
            raise HTTPException(409, 'This identity is already associated with an account; contact support')
        sandbox = settings.database_environment == 'SANDBOX'
        if settings.provider_environment != ('TEST' if sandbox else 'LIVE'):
            raise HTTPException(403, 'Account environment requires administrator configuration')
        await provider.bind_workspace(user_id, row['tenant_id'], row['email_address'])
        await provider.request('PUT', 'admin/users/' + str(user_id), {'password': body.password.get_secret_value()}, admin=True)
    raw = json.loads(row['profile']) if isinstance(row['profile'], str) else row['profile']
    model = PersonalProfile.model_validate(raw) if row['workspace_type'] == 'INDIVIDUAL' else CompanyProfile.model_validate(raw)
    profile = storage_profile(model)
    async with pool.acquire() as c:
        async with c.transaction():
            await c.execute('LOCK TABLE public.tenants IN SHARE ROW EXCLUSIVE MODE')
            await c.execute('LOCK TABLE public.users IN SHARE ROW EXCLUSIVE MODE')
            current = await c.fetchrow('SELECT state FROM public.web_registration_sessions WHERE id=$1 FOR UPDATE', row['id'])
            if current['state'] != 'RECONCILIATION_REQUIRED':
                raise HTTPException(409, 'Registration state changed. Contact support.')
            if await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)
                OR EXISTS(SELECT 1 FROM public.tenants WHERE lower(billing_email)=$2
                   OR ($3::text IS NOT NULL AND company_registration_number=$3 AND country_code=$4))''',
                    user_id, row['email_address'], profile.company_registration_number, profile.country_code):
                raise HTTPException(409, 'Account details are already in use')
            await c.execute('''INSERT INTO public.tenants
                (tenant_id,company_name,company_profile,billing_plan,default_currency,workspace_status,billing_status,is_sandbox,
                 workspace_slug,workspace_name,legal_company_name,billing_email,billing_address,country_code,company_registration_number,
                 vat_registration_number,onboarding_source,workspace_type)
                VALUES($1,$2,$3::jsonb,'PREPAID_WALLET','GBP','ACTIVE','ACTIVE',$4,$5,$2,
                  CASE WHEN $11='BUSINESS' THEN $2 END,$6,$7::jsonb,$8,$9,$10,'WEB_PORTAL',$11)''',
                row['tenant_id'], profile.company_name, model.model_dump_json(), sandbox, 'tenant-' + row['tenant_id'].hex,
                row['email_address'], json.dumps({'line1': profile.address_line1, 'city': profile.city,
                    'postal_code': profile.postal_code, 'country_code': profile.country_code}), profile.country_code,
                profile.company_registration_number, profile.tax_id, row['workspace_type'])
            await c.execute("INSERT INTO public.wallets(tenant_id,currency,balance,reserved_balance) VALUES($1,'GBP',0,0) ON CONFLICT(tenant_id) DO NOTHING", row['tenant_id'])
            wallet = await c.fetchrow('SELECT currency,balance,reserved_balance FROM public.wallets WHERE tenant_id=$1 FOR UPDATE', row['tenant_id'])
            if not wallet or wallet['currency'] != 'GBP' or wallet['balance'] != 0 or wallet['reserved_balance'] != 0:
                raise HTTPException(409, 'Wallet provisioning requires reconciliation')
            await c.execute("INSERT INTO public.users(tenant_id,auth_user_id,role,full_name,is_active) VALUES($1,$2,'OWNER',$3,true)", row['tenant_id'], user_id, profile.contact_name)
            await c.execute('INSERT INTO public.app_user_profiles(auth_user_id,full_name,phone_e164) VALUES($1,$2,$3)', user_id, profile.contact_name, getattr(profile, 'phone_e164', None))
            await c.execute("UPDATE public.web_registration_sessions SET state='VERIFIED',auth_user_id=$2 WHERE id=$1", row['id'], user_id)
    return {'message': 'Your account is activated with a GBP 0.00 wallet. Sign in with your email and password.'}
