"""Explicitly pair the platform owner's verified phone to Harbor Commerce 01.

This writes a least-privilege dispatcher membership, verified sandbox binding and
saved fixture route. It sends no messages and enables no carrier credentials.
"""
import asyncio
import json
import base64
from urllib.parse import parse_qsl
from uuid import UUID, uuid4

import asyncpg
import httpx
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator
from dotenv import dotenv_values
from main import Settings, database_tls_context

TENANT = UUID('11de776d-4faf-f071-eb53-76d35aa619db')
ACTOR = UUID('117d268d-b034-4a74-ad4d-050813bf67ac')
RECEIVER = '+14155238886'


async def run():
    config = Settings()
    assert config.twilio_enabled and config.twilio_whatsapp_sandbox_enabled
    assert config.database_environment == 'SANDBOX' and config.provider_environment == 'TEST'
    assert ACTOR in config.platform_admin_user_ids
    phone = (dotenv_values('.env').get('TWILIO_SANDBOX_TEST_PHONE') or '').removeprefix('whatsapp:')
    import re
    assert re.fullmatch(r'\+[1-9][0-9]{7,14}', phone), 'Save your actual test phone in .env'
    # Verify that the locally saved number really sent a message to this account.
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        response = await client.get('https://api.twilio.com/2010-04-01/Accounts/' + config.twilio_account_sid + '/Messages.json',
            params={'From': 'whatsapp:' + phone, 'To': 'whatsapp:' + RECEIVER, 'PageSize': 5},
            auth=(config.twilio_account_sid, config.twilio_auth_token.get_secret_value()))
        response.raise_for_status()
        messages = response.json().get('messages', [])
        verified = any(m.get('direction') == 'inbound' and m.get('from') == 'whatsapp:' + phone
                   and m.get('to') == 'whatsapp:' + RECEIVER for m in messages)
        if not verified:
            # A Sandbox callback may be visible locally before it appears in the
            # account's Message list. Validate the original recorded signature;
            # never trust the inspector's sender fields alone.
            captured = await client.get('http://127.0.0.1:4040/api/requests/http')
            captured.raise_for_status()
            validator = RequestValidator(config.twilio_auth_token.get_secret_value())
            for record in captured.json().get('requests', []):
                raw = base64.b64decode(record.get('request', {}).get('raw', '')).decode('utf-8')
                headers, separator, body = raw.partition('\r\n\r\n')
                if not separator:
                    continue
                form = FormData(parse_qsl(body, keep_blank_values=True))
                signature = [line.split(':', 1)[1].strip() for line in headers.split('\r\n')[1:]
                             if line.lower().startswith('x-twilio-signature:')]
                if (len(signature) == 1 and form.get('From') == 'whatsapp:' + phone
                        and form.get('To') == 'whatsapp:' + RECEIVER
                        and form.get('AccountSid') == config.twilio_account_sid
                        and form.get('MessageSid') not in {'SM'+'e'*32,'SM'+'f'*32}
                        and validator.validate(config.twilio_webhook_url, form, signature[0])):
                    verified = True
                    break
        assert verified, 'No signed inbound callback or provider message from saved phone'
    connection = await asyncpg.connect(config.database_url.get_secret_value(),
        ssl=database_tls_context(config.database_ca_file, strict=config.database_tls_strict), timeout=15)
    try:
        async with connection.transaction():
            await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'sandbox-pair:' + phone)
            tenant = await connection.fetchrow('SELECT company_name,is_sandbox,workspace_status FROM public.tenants WHERE tenant_id=$1 FOR SHARE', TENANT)
            assert tenant and tenant['is_sandbox'] and tenant['workspace_status'] == 'ACTIVE'
            assert tenant['company_name'] == 'SEED24 - Harbor Commerce 01'
            assert await connection.fetchval('SELECT EXISTS(SELECT 1 FROM auth.users WHERE id=$1 AND (banned_until IS NULL OR banned_until<now()))', ACTOR)
            members = await connection.fetch('SELECT id,tenant_id,role,is_active FROM public.users WHERE auth_user_id=$1 FOR UPDATE', ACTOR)
            assert len(members) <= 1, 'Ambiguous identity membership requires review'
            if members:
                member = members[0]
                assert member['tenant_id'] == TENANT and member['is_active'] and member['role'] in ('OWNER','ADMIN','DISPATCHER')
                user_id = member['id']
            else:
                user_id = uuid4()
                await connection.execute("INSERT INTO public.users(id,tenant_id,auth_user_id,role,full_name,is_active) VALUES($1,$2,$3,'DISPATCHER','WhatsApp Sandbox Tester',true)", user_id,TENANT,ACTOR)
            bindings = await connection.fetch('SELECT id,tenant_id,user_id FROM public.whatsapp_bindings WHERE sender_e164=$1 AND receiver_e164=$2 FOR UPDATE',phone,RECEIVER)
            assert len(bindings) <= 1, 'Ambiguous phone binding requires review'
            if bindings:
                binding = bindings[0]
                assert binding['tenant_id'] == TENANT and binding['user_id'] == user_id, 'Phone already belongs to another workspace'
                await connection.execute('UPDATE public.whatsapp_bindings SET is_active=true,verified_at=now() WHERE id=$1',binding['id'])
            else:
                await connection.execute('INSERT INTO public.whatsapp_bindings(tenant_id,user_id,sender_e164,receiver_e164,is_active,verified_at) VALUES($1,$2,$3,$4,true,now())',TENANT,user_id,phone,RECEIVER)
            source = await connection.fetchrow("SELECT sender_address,recipient_address,parcel_length_cm,parcel_width_cm,parcel_height_cm,currency FROM public.shipments WHERE tenant_id=$1 AND customer_reference='SEED24-1-3'",TENANT)
            assert source, 'Required sandbox route fixture missing'
            dimensions = json.dumps({'length_cm':str(source['parcel_length_cm']),'width_cm':str(source['parcel_width_cm']),'height_cm':str(source['parcel_height_cm'])})
            count = await connection.fetchval("SELECT count(*) FROM public.whatsapp_routes WHERE tenant_id=$1 AND route_code='EXPORT_US'",TENANT)
            assert count <= 1, 'Ambiguous saved route requires review'
            if not count:
                await connection.execute("INSERT INTO public.whatsapp_routes(tenant_id,route_code,origin_country,destination_country,origin_address,destination_address,dimensions,currency,is_active) VALUES($1,'EXPORT_US','GB','US',$2::jsonb,$3::jsonb,$4::jsonb,$5,true)",TENANT,source['sender_address'],source['recipient_address'],dimensions,source['currency'])
        print('PAIRED: SEED24 - Harbor Commerce 01; dispatcher membership; verified phone; EXPORT_US fixture route. No labels, wallet changes or external CRM writes.')
    finally:
        await connection.close()


if __name__ == '__main__':
    asyncio.run(run())
