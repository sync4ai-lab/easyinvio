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
    plan: Literal['STARTER','VELOCITY','COMMAND'] = 'STARTER'
    cycle: Literal['MONTHLY','ANNUAL'] = 'MONTHLY'
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
            # A provisional Auth identity is expected after requesting an email code.
            # Reuse only an identity tied to this app's unfinished registration; never
            # delete Auth users or replace an existing customer's credentials/profile.
            blocked = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.tenants WHERE lower(billing_email)=$1)
                OR EXISTS(SELECT 1 FROM auth.users a WHERE lower(a.email)=$1 AND (
                    a.id=ANY($2::uuid[]) OR a.banned_until>now() OR (to_jsonb(a)->>'deleted_at') IS NOT NULL
                    OR EXISTS(SELECT 1 FROM public.users u WHERE u.auth_user_id=a.id)
                    OR EXISTS(SELECT 1 FROM public.app_user_profiles p WHERE p.auth_user_id=a.id)
                    OR NOT EXISTS(SELECT 1 FROM public.web_registration_sessions w
                        WHERE lower(w.email_address)=$1 AND w.state<>'VERIFIED'
                        AND a.created_at BETWEEN w.created_at AND w.expires_at
                        AND NOT EXISTS(SELECT 1 FROM public.tenants t WHERE t.tenant_id=w.tenant_id)
                        AND ((a.raw_app_meta_data->>'role' IS NULL AND a.raw_app_meta_data->>'tenant_id' IS NULL)
                          OR (a.raw_app_meta_data->>'role'='OWNER' AND a.raw_app_meta_data->>'tenant_id'=w.tenant_id::text)))))''',
                email, settings.platform_admin_user_ids)
            if blocked:
                raise HTTPException(409, 'An account already exists or needs review. Sign in or contact support.')
            previous = await c.fetchrow('''SELECT * FROM public.web_registration_sessions
                WHERE lower(email_address)=$1 ORDER BY created_at DESC LIMIT 1 FOR UPDATE''', email)
            if previous:
                if previous['state'] == 'VERIFIED':
                    raise HTTPException(409, 'An account already exists. Sign in or contact support.')
                # The expiry is set to 15 minutes at each send; enforce a one-minute resend cooldown.
                if (previous['expires_at'] - datetime.now(timezone.utc)).total_seconds() > 14 * 60:
                    raise HTTPException(429, 'Wait a minute before requesting a new email code.', headers={'Retry-After':'60'})
                row = previous
                await c.execute('''UPDATE public.web_registration_sessions SET secret_sha256=$2,
                    workspace_type=$3,profile=$4::jsonb,state='SENDING_EMAIL',attempts=0,
                    expires_at=now()+interval '15 minutes',auth_user_id=NULL WHERE id=$1''',
                    row['id'], hashlib.sha256(secret.encode()).hexdigest(), body.workspace_type, profile.model_dump_json())
            else:
                row = await c.fetchrow('''INSERT INTO public.web_registration_sessions
                    (secret_sha256,email_address,workspace_type,profile,state) VALUES($1,$2,$3,$4::jsonb,'SENDING_EMAIL')
                    RETURNING id''', hashlib.sha256(secret.encode()).hexdigest(), email, body.workspace_type, profile.model_dump_json())
            from backend.entitlements import enabled
            if enabled(settings):
                await c.execute('UPDATE public.web_registration_sessions SET requested_plan=$2,requested_cycle=$3 WHERE id=$1',row['id'],body.plan,body.cycle)
    async with httpx.AsyncClient(trust_env=False) as client:
        await SupabaseSignupProvider(settings, client).send_code(email)
    async with pool.acquire() as c:
        await c.execute("UPDATE public.web_registration_sessions SET state='PENDING_OTP' WHERE id=$1 AND state='SENDING_EMAIL' AND secret_sha256=$2", row['id'], hashlib.sha256(secret.encode()).hexdigest())
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
                raise HTTPException(409, 'Registration is unfinished. Start again to request a new email code.')
            # Commit the attempt before contacting Auth, including uncertain outcomes.
            await c.execute("UPDATE public.web_registration_sessions SET state='RECONCILIATION_REQUIRED',attempts=attempts+1 WHERE id=$1", row['id'])
    async with httpx.AsyncClient(trust_env=False) as client:
        provider = SupabaseSignupProvider(settings, client)
        user_id = await provider.verify(row['email_address'], body.code.get_secret_value())
        if user_id is None:
            async with pool.acquire() as c:
                await c.execute("UPDATE public.web_registration_sessions SET state='PENDING_OTP' WHERE id=$1 AND secret_sha256=$2 AND state='RECONCILIATION_REQUIRED'", row['id'], row['secret_sha256'])
            raise HTTPException(400, 'The email verification code was rejected or expired')
        if user_id in settings.platform_admin_user_ids:
            raise HTTPException(409, 'This identity requires administrator review')
        async with pool.acquire() as c:
            blocked = await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)
                OR EXISTS(SELECT 1 FROM public.app_user_profiles WHERE auth_user_id=$1)
                OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id=$1 AND created_at>=$2
                  AND lower(email)=$3 AND (banned_until IS NULL OR banned_until<now())
                  AND email_confirmed_at IS NOT NULL
                  AND ((raw_app_meta_data->>'role' IS NULL AND raw_app_meta_data->>'tenant_id' IS NULL)
                    OR (raw_app_meta_data->>'role'='OWNER'
                        AND raw_app_meta_data->>'tenant_id'=$4::text)))''',
                user_id, row['created_at'], row['email_address'], str(row['tenant_id']))
        if blocked:
            raise HTTPException(409, 'This identity is already associated with an account; contact support')
        sandbox = settings.database_environment == 'SANDBOX'
        if settings.provider_environment != ('TEST' if sandbox else 'LIVE'):
            raise HTTPException(403, 'Account environment requires administrator configuration')
    raw = json.loads(row['profile']) if isinstance(row['profile'], str) else row['profile']
    model = PersonalProfile.model_validate(raw) if row['workspace_type'] == 'INDIVIDUAL' else CompanyProfile.model_validate(raw)
    profile = storage_profile(model)
    async with pool.acquire() as c:
        async with c.transaction():
            current = await c.fetchrow('SELECT state,secret_sha256 FROM public.web_registration_sessions WHERE id=$1 FOR UPDATE', row['id'])
            if not current or current['state'] != 'RECONCILIATION_REQUIRED' or not hmac.compare_digest(current['secret_sha256'], row['secret_sha256']):
                raise HTTPException(409, 'Registration state changed. Contact support.')
            await c.execute('LOCK TABLE public.tenants IN SHARE ROW EXCLUSIVE MODE')
            await c.execute('LOCK TABLE public.users IN SHARE ROW EXCLUSIVE MODE')
            if await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)
                OR EXISTS(SELECT 1 FROM public.tenants WHERE lower(billing_email)=$2
                   OR ($3::text IS NOT NULL AND company_registration_number=$3 AND country_code=$4))''',
                    user_id, row['email_address'], profile.company_registration_number, profile.country_code):
                raise HTTPException(409, 'Account details are already in use')
            # Hold the registration row lock across identity mutation and finalization.
            # A concurrent restart cannot replace the profile/secret or overwrite an
            # activated customer's password with an older in-flight request.
            async with httpx.AsyncClient(trust_env=False) as client:
                provider = SupabaseSignupProvider(settings, client)
                await provider.bind_workspace(user_id, row['tenant_id'], row['email_address'])
                await provider.request('PUT', 'admin/users/' + str(user_id), {'password': body.password.get_secret_value()}, admin=True)
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
            from backend.entitlements import enabled,seed_subscription
            if enabled(settings):
                await seed_subscription(c,row['tenant_id'],row['requested_plan'],row['requested_cycle'],sandbox=sandbox,trial_days=settings.subscription_trial_days)
    return {'message': 'Your account is activated with a GBP 0.00 wallet. Sign in with your email and password.'}
