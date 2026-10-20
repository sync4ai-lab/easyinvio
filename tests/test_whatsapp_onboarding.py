"""Signed signup contracts with synthetic SQL and mocked Auth/email providers."""
import asyncio
import copy
import json
import re
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import SecretStr

from backend.whatsapp_onboarding import ConversationalSignupManager, SupabaseSignupProvider, now


class Database:
    def __init__(self):
        self.data = {'queues': [], 'receipts': {}, 'tenants': [], 'users': [], 'wallets': {}, 'bindings': [], 'profiles': []}
        self.lock = asyncio.Lock()
        self.acquired = 0
        self.depth = 0
        self.ready = True
        self.auth_emails = set()
        self.provisional_auth = {}
        self.fail_profile = False
        self.sql = []

    @asynccontextmanager
    async def acquire(self):
        self.acquired += 1
        try:
            yield self
        finally:
            self.acquired -= 1

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            snapshot = copy.deepcopy(self.data)
            self.depth += 1
            try:
                yield self
            except BaseException:
                self.data = snapshot
                raise
            finally:
                self.depth -= 1

    def queue(self, identifier):
        return next(q for q in self.data['queues'] if q['id'] == identifier)

    async def fetchval(self, sql, *args):
        self.sql.append((sql, args))
        if 'to_regclass' in sql:
            return self.ready
        if 'count(*)>=30' in sql:
            return sum(row['phone_e164'] == args[0] for row in self.data['receipts'].values()) >= 30
        if 'FROM public.whatsapp_bindings' in sql:
            return any(row['phone_e164'] == args[0] for row in self.data['bindings'])
        if 'SELECT count(*) FROM public.whatsapp_registration_queue' in sql:
            field = 'receiver_e164' if 'WHERE receiver_e164' in sql else 'phone_e164'
            return sum(q[field] == args[0] for q in self.data['queues'])
        if 'SELECT EXISTS(SELECT 1 FROM public.tenants' in sql:
            country, reg, email, own = args
            rows = self.data['tenants'] + [q for q in self.data['queues'] if q['id'] != own and q['current_state'] not in {'EXPIRED', 'CANCELLED', 'LOCKED', 'VERIFIED'}]
            return any((reg is not None and country is not None and row.get('country_code') == country and row.get('company_reg_number') == reg) or (email and row.get('email_address') == email) for row in rows)
        if 'FROM auth.users' in sql:
            if args[0] in self.auth_emails:
                return True
            identity = self.provisional_auth.get(args[0])
            if identity is None:
                return False
            email, phone, receiver, administrators = args
            if identity.get('member') or identity.get('profile') or identity.get('metadata') or identity.get('banned') or identity.get('deleted') or identity['id'] in administrators:
                return True
            return not any(q['email_address'] == email and q['phone_e164'] == phone and q['receiver_e164'] == receiver
                and q['send_attempts'] > 0 and q['last_sent_at'] and q['auth_user_id'] is None
                and q['current_state'] in {'SENDING_EMAIL', 'PENDING_OTP', 'EXPIRED', 'CANCELLED', 'LOCKED', 'PENDING_EMAIL'}
                and q['created_at'] <= identity['created_at'] <= q['last_sent_at'] + timedelta(minutes=1)
                for q in self.data['queues'])
        if 'FROM public.users' in sql:
            return any(row['auth_user_id'] == args[0] for row in self.data['users'])
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        self.sql.append((sql, args))
        if 'FROM public.whatsapp_registration_receipts' in sql:
            row = self.data['receipts'].get(args[0])
        elif 'FROM public.whatsapp_registration_queue' in sql:
            row = self.queue(args[0]) if 'WHERE id=$1' in sql else next((q for q in self.data['queues'] if
                (q['phone_e164'], q['receiver_e164']) == args and q['current_state'] not in {'EXPIRED', 'CANCELLED', 'LOCKED'}), None)
        elif 'FROM public.wallets' in sql:
            row = self.data['wallets'].get(args[0])
        else:
            raise AssertionError(sql)
        return copy.deepcopy(row) if row else None

    async def execute(self, sql, *args):
        self.sql.append((sql, args))
        if 'pg_advisory_xact_lock' in sql or sql.startswith('LOCK TABLE'):
            return 'SELECT 1'
        if sql.startswith('INSERT INTO public.whatsapp_registration_receipts'):
            assert args[0] not in self.data['receipts']
            self.data['receipts'][args[0]] = dict(message_sid=args[0], phone_e164=args[1], receiver_e164=args[2],
                input_hmac=args[3], reply_ciphertext=None, key_id=None, created_at=now())
        elif sql.startswith('UPDATE public.whatsapp_registration_receipts'):
            self.data['receipts'][args[0]].update(reply_ciphertext=args[1], key_id=args[2])
        elif sql.startswith('INSERT INTO public.whatsapp_registration_queue'):
            self.data['queues'].append(dict(id=uuid4(), phone_e164=args[0], receiver_e164=args[1], current_state='PENDING_PERSONA', workspace_type='BUSINESS',
                company_name=None, company_reg_number=None, country_code=None, profile={}, email_address=None,
                phone_otp_hmac=None, otp_expires_at=None, attempts=0, send_attempts=0, last_sent_at=None,
                auth_user_id=None, tenant_id=uuid4(), member_id=uuid4(), busy_message_sid=None, lease_until=None,
                expires_at=now()+timedelta(minutes=30), created_at=now()))
        elif sql.startswith('UPDATE public.whatsapp_registration_queue'):
            if "current_state='EXPIRED'" in sql:
                for q in self.data['queues']:
                    if q['expires_at'] < now() and q['current_state'] not in {'VERIFIED', 'PROVISIONING', 'RECONCILIATION_REQUIRED'}:
                        q['current_state'] = 'EXPIRED'
                return 'UPDATE 1'
            q = self.queue(args[0])
            state = re.search(r"current_state='([A-Z_]+)'", sql)
            if state:
                q['current_state'] = state[1]
            elif 'current_state=$2' in sql:
                q['current_state'] = args[1]
            if "workspace_type='INDIVIDUAL'" in sql:
                q['workspace_type'] = 'INDIVIDUAL'
            if 'company_name=$2' in sql:
                q.update(company_name=args[1], company_reg_number=args[2], country_code=args[3])
            if 'profile=$2' in sql:
                q['profile'] = json.loads(args[1])
            if 'email_address=$2' in sql:
                q['email_address'] = args[1]
            if 'busy_message_sid=$2' in sql and 'SET busy_message_sid' in sql:
                q.update(busy_message_sid=args[1], lease_until=now()+timedelta(seconds=30))
            if 'SET busy_message_sid=NULL' in sql:
                q.update(busy_message_sid=None, lease_until=None)
            if 'phone_otp_hmac=$2' in sql:
                q.update(phone_otp_hmac=args[1], send_attempts=q['send_attempts']+1, last_sent_at=now(), otp_expires_at=now()+timedelta(minutes=15))
            if 'phone_otp_hmac=NULL' in sql:
                q['phone_otp_hmac'] = None
            if 'attempts=attempts+1' in sql:
                q['attempts'] += 1
            if 'auth_user_id=$2' in sql:
                q['auth_user_id'] = args[1]
        elif sql.startswith('INSERT INTO public.tenants'):
            assert self.depth == 1
            self.data['tenants'].append(dict(id=args[0], company_reg_number=args[8], country_code=args[7], email_address=args[5], sandbox=args[3],workspace_type=args[9]))
        elif sql.startswith('INSERT INTO public.wallets'):
            assert type(args[1]) is Decimal and args[1] == Decimal('0.00')
            self.data['wallets'][args[0]] = dict(currency='GBP', balance=args[1], reserved_balance=args[1])
        elif sql.startswith('INSERT INTO public.users'):
            self.data['users'].append(dict(id=args[0], tenant_id=args[1], auth_user_id=args[2]))
        elif sql.startswith('INSERT INTO public.app_user_profiles'):
            if self.fail_profile:
                raise ValueError('Synthetic profile failure')
            self.data['profiles'].append(args)
        elif sql.startswith('INSERT INTO public.whatsapp_bindings'):
            self.data['bindings'].append(dict(tenant_id=args[0], user_id=args[1], phone_e164=args[2]))
        else:
            raise AssertionError(sql)
        return 'UPDATE 1'


@pytest.fixture
def signup():
    database = Database()
    settings = SimpleNamespace(quote_link_secret=SecretStr('s'*40), credential_keys={'test': SecretStr(Fernet.generate_key().decode())},
        platform_admin_user_ids=[], database_environment='SANDBOX', provider_environment='TEST', whatsapp_onboarding_daily_limit=100)
    provider = SimpleNamespace(send_code=AsyncMock(), verify=AsyncMock(), bind_workspace=AsyncMock(), password_email=AsyncMock(return_value=True))
    async def check_io(*args):
        assert database.depth == 0 and database.acquired == 0
    provider.send_code.side_effect = check_io
    provider.bind_workspace.side_effect = check_io
    manager = ConversationalSignupManager(database, settings, provider)
    return manager, database, provider


def form(text, sid=None, phone='+447700900123'):
    return {'Body': text, 'MessageSid': sid or 'SM'+uuid4().hex, 'From': 'whatsapp:'+phone, 'To': 'whatsapp:+14155238886'}


async def reach_codes(manager, database):
    for text in ('Register', '1', 'Example Ltd, 12345678, GB', 'Alex Example; 1 Example Road; Leeds; LS1 1AA; YES'):
        await manager.handle(form(text))
    response = await manager.handle(form('alex@example.com'))
    code = re.search(r'WhatsApp code is ([0-9]{6})', response)[1]
    return database.data['queues'][-1], code, response


@pytest.mark.asyncio
async def test_full_signup_requires_both_codes_and_provisions_only_native_identity(signup):
    manager, database, provider = signup
    queue, phone_code, response = await reach_codes(manager, database)
    assert queue['current_state'] == 'PENDING_OTP' and queue['phone_otp_hmac'] != phone_code
    assert not database.data['tenants'] and not database.data['wallets']
    assert all(phone_code.encode() not in row['reply_ciphertext'] for row in database.data['receipts'].values())
    provider.verify.return_value = user_id = uuid4()
    verified = form('123456 '+phone_code)
    assert 'Reply Continue' in await manager.handle(verified)
    assert queue['current_state'] == 'PROVISIONING'
    provider.verify.assert_awaited_once_with('alex@example.com', '123456')
    assert not database.data['tenants']
    assert await manager.handle(verified) == await manager.replay(verified)
    activation = form('Continue')
    reply = await manager.handle(activation)
    assert 'GBP 0.00' in reply and 'password setup email' in reply
    assert queue['current_state'] == 'VERIFIED'
    assert len(database.data['tenants']) == len(database.data['users']) == len(database.data['bindings']) == 1
    assert database.data['users'][0]['auth_user_id'] == user_id
    assert database.data['tenants'][0]['sandbox'] is True
    assert database.data['wallets'][queue['tenant_id']]['balance'] == Decimal('0.00')
    assert await manager.handle(activation) == reply
    provider.bind_workspace.assert_awaited_once()
    assert not any('password_reset_token' in sql or 'INSERT INTO auth.users' in sql for sql, _ in database.sql)


@pytest.mark.asyncio
async def test_phone_code_alone_and_expired_email_never_create_accounts(signup):
    manager, database, provider = signup
    queue, code, _ = await reach_codes(manager, database)
    for text in (code, '123456 999999' if code != '999999' else '123456 888888'):
        await manager.handle(form(text))
    provider.verify.assert_not_awaited()
    provider.verify.return_value = None
    await manager.handle(form('123456 '+code))
    assert queue['current_state'] == 'PENDING_OTP' and queue['attempts'] == 2
    queue['otp_expires_at'] = now()-timedelta(seconds=1)
    await manager.handle(form('123456 '+code))
    assert queue['current_state'] == 'LOCKED' and not database.data['tenants']


@pytest.mark.asyncio
async def test_attempt_limit_resend_cooldown_and_provider_failure(signup):
    manager, database, provider = signup
    queue, code, _ = await reach_codes(manager, database)
    assert 'one minute' in await manager.handle(form('Resend'))
    assert provider.send_code.await_count == 1
    for _ in range(5):
        await manager.handle(form('123456 999999' if code != '999999' else '123456 888888'))
    assert queue['current_state'] == 'LOCKED' and queue['phone_otp_hmac'] is None
    assert not database.data['tenants']


@pytest.mark.asyncio
async def test_uncertain_auth_response_is_fenced_from_retry(signup):
    manager, database, provider = signup
    queue, code, _ = await reach_codes(manager, database)
    provider.verify.side_effect = HTTPException(503, 'Verification needs review')
    await manager.handle(form('123456 '+code))
    assert queue['current_state'] == 'RECONCILIATION_REQUIRED'
    await manager.handle(form('123456 '+code))
    provider.verify.assert_awaited_once()
    assert not database.data['tenants']


@pytest.mark.asyncio
async def test_email_send_failure_and_expired_provisioning_do_not_activate(signup):
    manager, database, provider = signup
    provider.send_code.side_effect = HTTPException(503, 'Delivery not confirmed')
    for text in ('Register', '1', 'Example Ltd, 12345678, GB', 'Alex; 1 Test Road; Leeds; LS1 1AA; YES', 'alex@example.com'):
        await manager.handle(form(text))
    queue = database.data['queues'][0]
    assert queue['current_state'] == 'SENDING_EMAIL'
    assert 'not been confirmed' in await manager.handle(form('Status'))
    assert not database.data['tenants']
    queue.update(current_state='PROVISIONING', auth_user_id=uuid4(), expires_at=now()-timedelta(seconds=1))
    assert 'setup window has expired' in await manager.handle(form('Continue'))
    assert queue['current_state'] == 'RECONCILIATION_REQUIRED'
    provider.bind_workspace.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_company_existing_identity_and_inactive_phone_are_not_taken_over(signup):
    manager, database, provider = signup
    database.data['bindings'].append({'phone_e164': '+447700900999', 'active': False})
    assert 'cannot reactivate' in await manager.handle(form('Register', phone='+447700900999'))
    assert not database.data['queues']
    await manager.handle(form('Register'))
    await manager.handle(form('1'))
    database.data['tenants'].append({'id': uuid4(), 'company_reg_number': '12345678', 'country_code': 'GB'})
    assert 'already linked' in await manager.handle(form('Example Ltd, 12345678, GB'))
    assert database.data['queues'][0]['current_state'] == 'PENDING_COMPANY'
    database.data['tenants'].clear()
    await manager.handle(form('Example Ltd, 12345678, GB'))
    await manager.handle(form('Alex; 1 Test Road; Leeds; LS1 1AA; YES'))
    database.auth_emails.add('existing@example.com')
    assert 'cannot take over' in await manager.handle(form('existing@example.com'))
    provider.send_code.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_database_provision_rolls_back_and_can_resume(signup):
    manager, database, provider = signup
    queue, code, _ = await reach_codes(manager, database)
    provider.verify.return_value = uuid4()
    await manager.handle(form('123456 '+code))
    database.fail_profile = True
    await manager.handle(form('Continue'))
    assert not database.data['tenants'] and not database.data['wallets'] and not database.data['users']
    assert database.data['queues'][0]['current_state'] == 'PROVISIONING'
    database.fail_profile = False
    assert 'workspace has been created' in await manager.handle(form('Continue'))
    assert len(database.data['tenants']) == 1


@pytest.mark.asyncio
async def test_delivery_replays_do_not_advance_and_changed_content_is_rejected(signup):
    manager, database, provider = signup
    body = form('Hello')
    results = await asyncio.gather(manager.handle(body), manager.handle(body))
    assert results[0] == results[1] and len(database.data['queues']) == 1
    with pytest.raises(HTTPException) as error:
        await manager.handle({**body, 'Body': 'different'})
    assert error.value.status_code == 403
    assert 'cancelled' in await manager.handle(form('Cancel'))
    assert not database.data['tenants']


@pytest.mark.parametrize('text', ['Some company only', 'Example, 12345678', 'Example, <bad>, GB'])
def test_company_parser_never_invents_legal_facts(text):
    with pytest.raises(ValueError):
        ConversationalSignupManager.company(text)


@pytest.mark.asyncio
async def test_native_supabase_contract_does_not_expose_session_tokens():
    user_id, tenant_id = uuid4(), uuid4()
    calls = []
    async def server(request):
        calls.append(request)
        path = request.url.path
        if path.endswith('/otp'):
            assert json.loads(request.content) == {'email': 'alex@example.com', 'create_user': True}
            return httpx.Response(200, json={})
        if path.endswith('/verify'):
            return httpx.Response(200, json={'user': {'id': str(user_id), 'email': 'alex@example.com', 'email_confirmed_at': '2026-10-16'}, 'access_token': 'private-access', 'refresh_token': 'private-refresh'})
        if '/admin/users/' in path:
            assert request.headers['authorization'] == 'Bearer synthetic-service'
            metadata = {'provider': 'email'} if request.method == 'GET' else json.loads(request.content)['app_metadata']
            return httpx.Response(200, json={'id': str(user_id), 'email': 'alex@example.com', 'email_confirmed_at': '2026-10-16', 'app_metadata': metadata})
        if path.endswith('/recover'):
            assert request.url.params['redirect_to'] == 'https://app.example.com/'
            return httpx.Response(200, json={})
        raise AssertionError(path)
    settings = SimpleNamespace(supabase_url='https://synthetic.supabase.co', supabase_publishable_key=SecretStr('synthetic-public'),
        supabase_service_role_key=SecretStr('synthetic-service'), auth_recovery_redirect_url='https://app.example.com/')
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        provider = SupabaseSignupProvider(settings, client)
        await provider.send_code('alex@example.com')
        assert await provider.verify('alex@example.com', '123456') == user_id
        await provider.bind_workspace(user_id, tenant_id, 'alex@example.com')
        assert await provider.password_email('alex@example.com') is True
    assert len(calls) == 5


@pytest.mark.parametrize('path', ['/webhooks/twilio/whatsapp', '/api/v1/integrations/whatsapp/webhook'])
def test_opt_in_hooks_only_enrol_signed_unregistered_senders(path):
    import main
    from test_sandbox_hooks import WhatsAppTests
    from urllib.parse import urlencode
    from starlette.datastructures import FormData
    original = dict(main.app.state._state)
    try:
        harness = WhatsAppTests(methodName='test_invalid_signature_never_reads_tenant_data')
        harness.setUp()
        harness.settings.whatsapp_onboarding_enabled = True
        harness.settings.twilio_webhook_url = 'https://sandbox.example.com' + path
        manager = SimpleNamespace(replay=AsyncMock(return_value=None), handle=AsyncMock(return_value='<Response><Message>Register here</Message></Response>'))
        main.app.state.whatsapp_onboarding = manager
        fields = harness.fields(From='whatsapp:+447700900999', Body='Register')
        def post(fields, signature=None):
            signed = signature or main.app.state.twilio_validator.compute_signature(harness.settings.twilio_webhook_url, FormData(fields))
            response = harness.client.post(path, content=urlencode(fields), headers={'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': signed})
            return harness.complete_response(response, fields)
        assert post(fields, signature='bad').status_code == 403
        manager.handle.assert_not_awaited()
        assert 'Register here' in post(fields).text
        manager.handle.assert_awaited_once()
        assert not harness.observed
        manager.handle.reset_mock()
        registered = harness.fields(MessageSid='SM'+uuid4().hex)
        assert post(registered).status_code == 200
        manager.handle.assert_not_awaited()
        assert len(harness.observed) == 1
    finally:
        main.app.state._state.clear()
        main.app.state._state.update(original)


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['12345', '12345678901', '１２３４５６', '123 456', 123456, None])
async def test_email_verification_rejects_invalid_numeric_input_without_provider_io(code):
    client = SimpleNamespace(post=AsyncMock())
    provider = SupabaseSignupProvider(SimpleNamespace(), client)
    assert await provider.verify('alex@example.com', code) is None
    client.post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('redirect', [
    'http://localhost:5000/set-password',
    'http://127.0.0.1:8000/set-password',
    'https://easyinvio.com/set-password',
])
async def test_password_email_uses_configured_destination_without_returning_credential(redirect):
    async def server(request):
        assert request.url.path == '/auth/v1/recover'
        assert request.url.params['redirect_to'] == redirect
        assert json.loads(request.content) == {'email': 'alex@example.com'}
        return httpx.Response(200, json={})
    settings = SimpleNamespace(supabase_url='https://synthetic.supabase.co',
        supabase_publishable_key=SecretStr('synthetic-public'), auth_recovery_redirect_url=redirect)
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        assert await SupabaseSignupProvider(settings, client).password_email('alex@example.com') is True


@pytest.mark.asyncio
@pytest.mark.parametrize('redirect', [
    'http://easyinvio.com/set-password', 'https://user:password@easyinvio.com/',
    'https://easyinvio.com/#token_hash=secret', 'https://easyinvio.com/?redirect=https://foreign.example',
    'https://easyinvio.com:bad/', 'https://[broken/', 'https://easyinvio.com:0/',
    'https://easyinvio.com/\n', 'https://easyinvio.com\\@foreign.example/', None,
])
async def test_bad_recovery_configuration_never_dispatches_email(redirect):
    client = SimpleNamespace(request=AsyncMock())
    provider = SupabaseSignupProvider(SimpleNamespace(auth_recovery_redirect_url=redirect), client)
    assert await provider.password_email('alex@example.com') is False
    client.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_password_alias_serves_the_existing_spa_without_caching():
    from fastapi import FastAPI
    from main import frontend
    app = FastAPI()
    app.add_api_route('/set-password', frontend, methods=['GET'])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/set-password')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert 'identityRecoveryHash' in response.text


@pytest.mark.asyncio
async def test_malformed_email_code_does_not_consume_verification_attempt(signup):
    manager, database, provider = signup
    queue, code, _ = await reach_codes(manager, database)
    assert 'expected format' in await manager.handle(form('12345678901 ' + code))
    assert queue['attempts'] == 0
    provider.verify.assert_not_awaited()
    assert queue['current_state'] == 'PENDING_OTP'
    assert not database.data['tenants']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [429, 500, 'timeout'])
async def test_smtp_upstream_failure_never_reports_delivery_accepted(failure):
    async def server(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic provider timeout', request=request)
        return httpx.Response(failure, json={'message': 'synthetic provider rejection'})
    settings = SimpleNamespace(supabase_url='https://synthetic.supabase.co',
        supabase_publishable_key=SecretStr('synthetic-public'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        with pytest.raises(HTTPException) as error:
            await SupabaseSignupProvider(settings, client).send_code('alex@example.com')
    assert error.value.status_code == (429 if failure == 429 else 503)


@pytest.mark.asyncio
@pytest.mark.parametrize('email_code', ['012345', '0123456', '01234567', '012345678', '0123456789'])
async def test_all_supported_email_lengths_preserve_exact_code_and_require_both_proofs(signup, email_code):
    manager, database, provider = signup
    queue, phone_code, _ = await reach_codes(manager, database)
    provider.verify.return_value = uuid4()
    assert 'Reply Continue' in await manager.handle(form(email_code + ' ' + phone_code))
    provider.verify.assert_awaited_once_with('alex@example.com', email_code)
    assert queue['current_state'] == 'PROVISIONING'
    assert not database.data['tenants']


@pytest.mark.asyncio
@pytest.mark.parametrize('email_code', ['012345', '0123456', '01234567', '012345678', '0123456789'])
async def test_native_provider_passes_full_numeric_code_to_auth(email_code):
    user_id = uuid4()
    async def server(request):
        assert json.loads(request.content)['token'] == email_code
        return httpx.Response(200, json={'user': {'id': str(user_id), 'email': 'alex@example.com', 'email_confirmed_at': '2026-10-19'}})
    settings = SimpleNamespace(supabase_url='https://synthetic.supabase.co', supabase_publishable_key=SecretStr('synthetic-public'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        assert await SupabaseSignupProvider(settings, client).verify('alex@example.com', email_code) == user_id


@pytest.mark.asyncio
async def test_same_phone_can_restart_own_cancelled_provisional_email_without_account_deletion(signup):
    manager, database, provider = signup
    old, _, _ = await reach_codes(manager, database)
    database.provisional_auth['alex@example.com'] = dict(id=uuid4(), created_at=old['last_sent_at'])
    await manager.handle(form('Cancel'))
    new, phone_code, reply = await reach_codes(manager, database)
    assert old['current_state'] == 'CANCELLED' and new['current_state'] == 'PENDING_OTP'
    assert 'accepted a verification email' in reply
    assert provider.send_code.await_count == 2
    provider.verify.assert_not_awaited()
    assert not database.data['tenants'] and not database.data['users']
    provider.verify.return_value = database.provisional_auth['alex@example.com']['id']
    assert 'Both codes are verified' in await manager.handle(form('01234567 ' + phone_code))
    assert not any('DELETE FROM auth.users' in sql for sql, _ in database.sql)


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['phone', 'receiver', 'earlier_identity', 'late_identity', 'member', 'profile',
    'metadata', 'banned', 'deleted', 'administrator', 'uncertain_verification', 'checkpointed_identity'])
async def test_provisional_reuse_never_claims_another_identity(signup, reason):
    manager, database, provider = signup
    old, _, _ = await reach_codes(manager, database)
    identity = dict(id=uuid4(), created_at=old['last_sent_at'])
    database.provisional_auth['alex@example.com'] = identity
    current = dict(old)
    if reason in {'phone', 'receiver'}:
        current[reason + '_e164'] = '+447700900999'
    elif reason == 'earlier_identity':
        identity['created_at'] = old['created_at'] - timedelta(seconds=1)
    elif reason == 'late_identity':
        identity['created_at'] = old['last_sent_at'] + timedelta(minutes=2)
    elif reason == 'administrator':
        manager.settings.platform_admin_user_ids = [identity['id']]
    elif reason == 'uncertain_verification':
        old['current_state'] = 'RECONCILIATION_REQUIRED'
    elif reason == 'checkpointed_identity':
        old['auth_user_id'] = identity['id']
    else:
        identity[reason] = True
    async with database.acquire() as c:
        assert await manager.email_identity_blocked(c, 'alex@example.com', current)
    sql, args = database.sql[-1]
    assert args[:3] == ('alex@example.com', current['phone_e164'], current['receiver_e164'])
    for fence in ('public.users', 'public.app_user_profiles', 'raw_app_meta_data', 'q.auth_user_id IS NULL', 'u.created_at>=q.created_at'):
        assert fence in sql


@pytest.mark.asyncio
async def test_repeating_same_pending_email_uses_resend_limits(signup):
    manager, database, provider = signup
    queue, _, _ = await reach_codes(manager, database)
    assert 'one minute' in await manager.handle(form('ALEX@EXAMPLE.COM'))
    assert provider.send_code.await_count == 1
    queue['last_sent_at'] = now() - timedelta(seconds=61)
    assert 'accepted a verification email' in await manager.handle(form('alex@example.com'))
    assert provider.send_code.await_count == 2
    assert queue['current_state'] == 'PENDING_OTP' and queue['attempts'] == 0


@pytest.mark.asyncio
async def test_individual_persona_skips_company_and_activates_only_after_both_proofs(signup):
    manager, database, provider = signup
    hello = form('Register')
    assert "Business or an Individual" in await manager.handle(hello)
    assert 'Business or an Individual' in await manager.handle(hello)
    assert database.data['queues'][0]['current_state'] == 'PENDING_PERSONA'
    assert 'personal Email' in await manager.handle(form('2'))
    queue = database.data['queues'][0]
    assert queue['workspace_type'] == 'INDIVIDUAL' and queue['current_state'] == 'PENDING_EMAIL'
    reply = await manager.handle(form('personal@example.com'))
    code = re.search(r'WhatsApp code is ([0-9]{6})', reply)[1]
    assert not database.data['tenants']
    provider.verify.return_value = uuid4()
    assert 'full name' in await manager.handle(form('12345678 '+code))
    assert not database.data['tenants']
    assert 'full name' in await manager.handle(form('Continue'))
    assert 'GBP 0.00' in await manager.handle(form('Alex Consumer'))
    assert queue['current_state'] == 'VERIFIED'
    tenant = database.data['tenants'][0]
    assert tenant['workspace_type'] == 'INDIVIDUAL'
    assert tenant['company_reg_number'] is None and tenant['country_code'] is None
    assert database.data['wallets'][queue['tenant_id']]['balance'] == Decimal('0.00')
    assert len(database.data['users']) == len(database.data['bindings']) == 1
