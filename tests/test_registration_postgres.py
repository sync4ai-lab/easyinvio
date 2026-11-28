"""Registration state transitions on disposable Postgres; no remote Auth/email calls."""
import json
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException, Request
from tests.test_entitlements_postgres import db
from backend.web_registration import RegistrationStart, RegistrationVerify, start_registration, verify_registration


@pytest_asyncio.fixture
async def registration(db):
    await db.command("""
    ALTER TABLE auth.users ADD COLUMN email text UNIQUE, ADD COLUMN created_at timestamptz DEFAULT now(),
      ADD COLUMN email_confirmed_at timestamptz, ADD COLUMN banned_until timestamptz,
      ADD COLUMN deleted_at timestamptz, ADD COLUMN raw_app_meta_data jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE public.tenants ADD COLUMN company_profile jsonb,ADD COLUMN billing_status text,
      ADD COLUMN workspace_slug text,ADD COLUMN workspace_name text,ADD COLUMN legal_company_name text,
      ADD COLUMN billing_address jsonb,ADD COLUMN country_code text,ADD COLUMN company_registration_number text,
      ADD COLUMN vat_registration_number text,ADD COLUMN onboarding_source text;
    ALTER TABLE public.users ADD COLUMN full_name text;
    CREATE TABLE public.app_user_profiles(auth_user_id uuid PRIMARY KEY REFERENCES auth.users,
      full_name text,phone_e164 text);
    ALTER TABLE public.wallets ADD COLUMN reserved_balance numeric NOT NULL DEFAULT 0;
    ALTER TABLE public.web_registration_sessions ALTER COLUMN id SET DEFAULT gen_random_uuid(),
      ADD COLUMN secret_sha256 text NOT NULL, ADD COLUMN email_address text NOT NULL,
      ADD COLUMN workspace_type text NOT NULL, ADD COLUMN profile jsonb NOT NULL,
      ADD COLUMN state text NOT NULL, ADD COLUMN attempts integer NOT NULL DEFAULT 0,
      ADD COLUMN tenant_id uuid NOT NULL DEFAULT gen_random_uuid(), ADD COLUMN auth_user_id uuid REFERENCES auth.users,
      ADD COLUMN created_at timestamptz NOT NULL DEFAULT now(),
      ADD COLUMN expires_at timestamptz NOT NULL DEFAULT now()+interval '15 minutes';
    """,mode='exec')
    original_fetchrow=db.fetchrow
    async def native_decimals(sql,*args):
        row=await original_fetchrow(sql,*args)
        if row and 'FROM public.wallets' in sql:
            for key in ('balance','reserved_balance'):
                if key in row:row[key]=Decimal(str(row[key]))
        return row
    db.fetchrow=native_decimals
    user=uuid4()
    settings=NS(platform_admin_user_ids=[],database_environment='SANDBOX',provider_environment='TEST',subscription_trial_days=14)
    request=Request({'type':'http','app':NS(state=NS(settings=settings,finance=NS(pool=db))),'headers':[],'path':'/api/v1/auth/token','scheme':'https','server':('app.example.test',443),'query_string':b''})
    body=RegistrationStart(workspace_type='INDIVIDUAL', profile={
        'full_name':'Synthetic Customer','billing_email':'customer@example.test','phone_e164':'+447700900123'})
    async def send(email):
        await db.execute('INSERT INTO auth.users(id,email) VALUES($1,$2) ON CONFLICT(email) DO NOTHING',user,email)
    async def verified(email,code):
        if code!='87654321':return None
        await db.execute('UPDATE auth.users SET email_confirmed_at=now() WHERE id=$1',user)
        return user
    async def bind(user_id,tenant,email):
        await db.execute('UPDATE auth.users SET raw_app_meta_data=$2::jsonb WHERE id=$1',user_id,json.dumps({'tenant_id':str(tenant),'role':'OWNER'}))
    provider=NS(send_code=AsyncMock(side_effect=send),verify=AsyncMock(side_effect=verified),
        bind_workspace=AsyncMock(side_effect=bind),request=AsyncMock())
    with patch('backend.identity.recovery_limit',AsyncMock()),patch('backend.web_registration.SupabaseSignupProvider',return_value=provider):
        yield db,request,body,provider,user


def verification(receipt,code='87654321'):
    return RegistrationVerify(registration_id=receipt['registration_id'],registration_secret=receipt['registration_secret'],
        code=code,password='synthetic-password-only')


async def cooldown(db):
    await db.execute("UPDATE public.web_registration_sessions SET expires_at=now()+interval '13 minutes'")


@pytest.mark.asyncio
async def test_pending_and_wrong_code_never_create_customer_records(registration):
    db,request,body,provider,user=registration
    receipt=await start_registration(body,request)
    assert await db.fetchval('SELECT count(*) FROM public.tenants')==0
    assert await db.fetchval('SELECT count(*) FROM public.users')==0
    assert await db.fetchval('SELECT count(*) FROM public.wallets')==0
    with pytest.raises(HTTPException):await verify_registration(verification(receipt,'11111111'),request)
    assert await db.fetchval('SELECT state FROM public.web_registration_sessions')=='PENDING_OTP'
    assert await db.fetchval('SELECT count(*) FROM public.tenants')==0
    provider.bind_workspace.assert_not_awaited();provider.request.assert_not_awaited()
    await verify_registration(verification(receipt),request)
    assert await db.fetchval('SELECT state FROM public.web_registration_sessions')=='VERIFIED'
    assert await db.fetchval('SELECT count(*) FROM public.users')==1
    assert Decimal(str(await db.fetchval('SELECT balance FROM public.wallets')))==0
    with pytest.raises(HTTPException):await start_registration(body,request)


@pytest.mark.asyncio
async def test_restart_reuses_only_provisional_identity_and_rotates_secret(registration):
    db,request,body,provider,user=registration
    first=await start_registration(body,request)
    with pytest.raises(HTTPException) as error:await start_registration(body,request)
    assert error.value.status_code==429
    await cooldown(db)
    fresh=await start_registration(body,request)
    assert fresh['registration_id']==first['registration_id']
    assert fresh['registration_secret']!=first['registration_secret']
    with pytest.raises(HTTPException):await verify_registration(verification(first),request)
    provider.verify.assert_not_awaited()
    await verify_registration(verification(fresh),request)
    assert await db.fetchval('SELECT count(*) FROM public.tenants')==1


@pytest.mark.asyncio
async def test_failed_provision_requires_fresh_otp_even_with_confirmed_identity(registration):
    db,request,body,provider,user=registration
    first=await start_registration(body,request)
    await db.command("CREATE FUNCTION fail_wallet() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic failure'; END $$; CREATE TRIGGER fail_wallet BEFORE INSERT ON public.wallets FOR EACH ROW EXECUTE FUNCTION fail_wallet();",mode='exec')
    with pytest.raises(asyncpg.RaiseError):await verify_registration(verification(first),request)
    assert await db.fetchval('SELECT state FROM public.web_registration_sessions')=='RECONCILIATION_REQUIRED'
    assert await db.fetchval('SELECT count(*) FROM public.tenants')==0
    assert await db.fetchval('SELECT count(*) FROM public.users')==0
    with pytest.raises(HTTPException):await verify_registration(verification(first),request)
    assert provider.verify.await_count==1
    # Model Auth's non-transactional metadata/password side effect after the database rollback.
    tenant=await db.fetchval('SELECT tenant_id FROM public.web_registration_sessions')
    await db.execute('UPDATE auth.users SET raw_app_meta_data=$2::jsonb,email_confirmed_at=now() WHERE id=$1',user,json.dumps({'tenant_id':str(tenant),'role':'OWNER'}))
    await cooldown(db)
    fresh=await start_registration(body,request)
    with pytest.raises(HTTPException):await verify_registration(verification(fresh,'11111111'),request)
    assert await db.fetchval('SELECT count(*) FROM public.tenants')==0
    await db.command('DROP TRIGGER fail_wallet ON public.wallets',mode='exec')
    await verify_registration(verification(fresh),request)
    assert await db.fetchval('SELECT count(*) FROM public.tenants')==1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['unrelated','banned','foreign_metadata','administrator','existing_profile'])
async def test_restart_cannot_claim_existing_or_protected_identities(registration,kind):
    db,request,body,provider,user=registration
    if kind=='unrelated':
        await db.execute('INSERT INTO auth.users(id,email) VALUES($1,$2)',user,'customer@example.test')
    else:
        await start_registration(body,request)
        await cooldown(db)
        if kind=='banned':await db.execute("UPDATE auth.users SET banned_until=now()+interval '1 day'")
        if kind=='foreign_metadata':await db.execute('UPDATE auth.users SET raw_app_meta_data=$1::jsonb',json.dumps({'tenant_id':str(uuid4()),'role':'OWNER'}))
        if kind=='administrator':request.app.state.settings.platform_admin_user_ids=[user]
        if kind=='existing_profile':await db.execute('INSERT INTO public.app_user_profiles(auth_user_id) VALUES($1)',user)
    sent=provider.send_code.await_count
    with pytest.raises(HTTPException) as error:await start_registration(body,request)
    assert error.value.status_code==409
    assert provider.send_code.await_count==sent
    assert await db.fetchval('SELECT count(*) FROM public.tenants')==0


@pytest.mark.asyncio
async def test_in_flight_verification_cannot_finalize_after_restart(registration):
    db,request,body,provider,user=registration
    receipt=await start_registration(body,request)
    original=provider.verify.side_effect
    async def rotated(email,code):
        result=await original(email,code)
        await db.execute("UPDATE public.web_registration_sessions SET secret_sha256=repeat('f',64),state='PENDING_OTP'")
        return result
    provider.verify.side_effect=rotated
    with pytest.raises(HTTPException):await verify_registration(verification(receipt),request)
    provider.bind_workspace.assert_not_awaited();provider.request.assert_not_awaited()
    assert await db.fetchval('SELECT count(*) FROM public.tenants')==0


@pytest.mark.asyncio
async def test_signin_requires_confirmed_email_and_completed_workspace_but_allows_invited_members(registration):
    import httpx
    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    from fastapi import Response
    from backend.identity import token, Login
    from backend.entitlements import seed_subscription
    db,request,body,provider,user=registration
    native_execute=db.execute
    async def bytea_parameters(sql,*args):
        return await native_execute(sql,*({'__bytea_hex__':value.hex()} if isinstance(value,bytes) else value for value in args))
    db.execute=bytea_parameters
    await db.command("""
        CREATE TABLE public.app_login_limits(bucket text PRIMARY KEY, attempts integer NOT NULL,
            window_start timestamptz NOT NULL DEFAULT now());
        CREATE TABLE public.app_auth_sessions(id uuid PRIMARY KEY,auth_user_id uuid NOT NULL,
            tenant_id uuid,provider_token bytea,key_id text,expires_at timestamptz);
    """,mode='exec')
    settings=request.app.state.settings
    settings.auth_jwt_secret=SecretStr('s'*48)
    settings.credential_keys={'test':SecretStr(Fernet.generate_key().decode())}
    settings.supabase_url='https://auth.example.test'
    settings.supabase_publishable_key=SecretStr('synthetic-public-key')
    receipt=await start_registration(body,request)
    real_client=httpx.AsyncClient
    current={'id':user,'email':'customer@example.test','confirmed':False}
    def response(req):
        if req.url.path.endswith('/token'):
            return httpx.Response(200,json={'access_token':'synthetic-provider-token','expires_in':3600})
        return httpx.Response(200,json={'id':str(current['id']),'email':current['email'],
            'email_confirmed_at':'2026-11-28T00:00:00Z' if current['confirmed'] else None})
    async def login():
        with patch('backend.identity.httpx.AsyncClient',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(response),**kw)),patch('backend.identity.platform_role',AsyncMock(return_value=None)):
            return await token(Login(email=current['email'],password='synthetic-password-only'),request,Response())
    with pytest.raises(HTTPException) as error:await login()
    assert error.value.status_code==403
    current['confirmed']=True
    with pytest.raises(HTTPException):await login()  # Confirmed Auth alone is insufficient.
    await verify_registration(verification(receipt),request)
    result=await login()
    assert result['bootstrap']['profile']['workspace_role']=='OWNER'
    await db.execute("UPDATE public.web_registration_sessions SET state='RECONCILIATION_REQUIRED'")
    with pytest.raises(HTTPException):await login()  # Reject even a mistaken partial membership.
    await db.execute("UPDATE public.web_registration_sessions SET state='VERIFIED'")
    tenant=await db.fetchval('SELECT tenant_id FROM public.web_registration_sessions')
    await seed_subscription(db,tenant,'VELOCITY','MONTHLY')
    member=uuid4()
    await db.execute('INSERT INTO auth.users(id,email,email_confirmed_at) VALUES($1,$2,now())',member,'member@example.test')
    await db.execute("INSERT INTO public.users(tenant_id,auth_user_id,role) VALUES($1,$2,'DISPATCHER')",tenant,member)
    current.update(id=member,email='member@example.test')
    result=await login()
    assert result['bootstrap']['profile']['workspace_role']=='DISPATCHER'
