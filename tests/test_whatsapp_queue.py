"""Offline ingress/worker tests: no Twilio, carrier, PAF or customer DB requests."""
import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from pydantic import SecretStr
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator

from backend.whatsapp_queue import WhatsAppQueue, OutboundPart, accept_whatsapp, reply_parts, return_media, inbound_digest


class Connection:
    def __init__(self):
        self.inbound = {}; self.parts = []; self.claimed = set(); self.calls = []; self.depth = 0

    async def __aenter__(self): self.depth += 1; return self
    async def __aexit__(self, *args): self.depth -= 1; return False
    def transaction(self): return self
    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if 'INSERT INTO public.whatsapp_reply_outbox' in sql:
            if len(args)==5 and any(p.get('fallback_for')==args[4] for p in self.parts):return 'INSERT 0 0'
            self.parts.append(dict(id=len(self.parts)+1,inbound_id=args[0],part_index=args[1],payload_ciphertext=args[2],key_id=args[3],state='STAGED',fallback_for=args[4] if len(args)==5 else None,provider_message_sid=None,delivery_status=None))
        if 'UPDATE public.whatsapp_reply_outbox' in sql:
            part = next(p for p in self.parts if p['id']==args[0])
            if "state='ACCEPTED'" in sql:
                part['state']='ACCEPTED'
                if len(args)>1:part['provider_message_sid']=args[1]
            elif "state='FAILED'" in sql:part.update(state='FAILED',delivery_status='rejected')
            elif 'delivery_status=CASE' in sql:part.update(provider_message_sid=args[1],delivery_status=args[2])
            else: part['state']=args[1]
        return 'UPDATE 1'
    async def fetchrow(self, sql, *args):
        self.calls.append((sql,args))
        if 'INSERT INTO public.whatsapp_inbound_queue' in sql:
            self.inbound.setdefault(args[0], dict(input_sha256=args[3],payload_ciphertext=args[4],key_id=args[5]))
            return self.inbound[args[0]]
        if 'FROM public.whatsapp_inbound_queue WHERE id=$1 FOR UPDATE' in sql:return {'id':args[0]}
        if 'JOIN public.whatsapp_inbound_queue q' in sql:
            part=next((p for p in self.parts if p['id']==args[0]),None)
            return part|{'sender_e164':'+447700900123','receiver_e164':'+14155238886'} if part else None
        raise AssertionError(sql)
    async def fetch(self, sql, *args): return [p for p in self.parts if p['inbound_id']==args[0]]
    async def fetchval(self, sql, *args):
        if "state='STAGED'" in sql and 'EXISTS' in sql:return any(p['inbound_id']==args[0] and p['state']=='STAGED' for p in self.parts)
        if 'fallback_for=$2' in sql:return next((p['id'] for p in self.parts if p['inbound_id']==args[0] and p.get('fallback_for')==args[1]),None)
        if args[0] in self.claimed: return None
        self.claimed.add(args[0]);return args[0]


@pytest.fixture
def queue():
    connection=Connection()
    config=SimpleNamespace(credential_keys={'v1':SecretStr(Fernet.generate_key().decode())},
        twilio_account_sid='AC'+'a'*32,twilio_auth_token=SecretStr('synthetic-token'),
        twilio_whatsapp_number='+14155238886',twilio_enabled=True,
        twilio_webhook_url='https://hooks.example/api/v1/integrations/whatsapp/webhook',
        twilio_whatsapp_sandbox_enabled=True,whatsapp_onboarding_enabled=False)
    app=FastAPI()
    pool=SimpleNamespace(acquire=lambda **kwargs:connection)
    def send(**kwargs):
        assert connection.depth == 0, 'DB connection retained during Twilio call'
        from uuid import uuid4
        return SimpleNamespace(sid='SM'+uuid4().hex)
    client=SimpleNamespace(messages=SimpleNamespace(create=Mock(side_effect=send)))
    instance=WhatsAppQueue(pool,config,app,client)
    app.state.settings=config;app.state.whatsapp_queue=instance
    app.state.twilio_validator=RequestValidator(config.twilio_auth_token.get_secret_value())
    app.post('/api/v1/integrations/whatsapp/webhook')(accept_whatsapp)
    return instance,connection,app


def fields():
    return {'AccountSid':'AC'+'a'*32,'MessageSid':'SM'+'b'*32,'From':'whatsapp:+447700900123',
        'To':'whatsapp:+14155238886','Body':'Quote 3kg from GB to FR','NumMedia':'0'}


@pytest.mark.asyncio
async def test_ack_is_empty_signed_durable_encrypted_and_deduplicated(queue):
    instance,storage,app=queue
    form=fields();raw=urlencode(form).encode()
    signature=app.state.twilio_validator.compute_signature(app.state.settings.twilio_webhook_url,FormData(form))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://hooks.example') as client:
        with patch('backend.whatsapp_queue.process_inbound',AsyncMock()) as action:
            start=asyncio.get_running_loop().time()
            for _ in range(2):
                result=await client.post('/api/v1/integrations/whatsapp/webhook',content=raw,
                    headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':signature})
                assert result.status_code==200 and result.text=='<Response/>'
            assert asyncio.get_running_loop().time()-start < .5
            action.assert_not_awaited()
    assert len(storage.inbound)==1
    row=storage.inbound[form['MessageSid']]
    assert row['input_sha256']==inbound_digest(raw)
    assert raw not in row['payload_ciphertext']
    assert instance.ciphers[row['key_id']].decrypt(row['payload_ciphertext'])==raw
    await instance.enqueue(raw,FormData(form))
    await instance.enqueue(urlencode(list(reversed(list(form.items())))).encode(),FormData(form))
    assert len(storage.inbound)==1
    with pytest.raises(HTTPException) as conflict:
        await instance.enqueue(urlencode(form|{'Body':'Different content'}).encode(),FormData(form))
    assert conflict.value.status_code==409


@pytest.mark.asyncio
async def test_invalid_signature_never_enqueues_and_storage_delay_fails_within_budget(queue):
    instance,storage,app=queue;form=fields();raw=urlencode(form)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://hooks.example') as client:
        headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':'bad'}
        assert (await client.post('/api/v1/integrations/whatsapp/webhook',content=raw,headers=headers)).status_code==403
        assert not storage.inbound
        headers['X-Twilio-Signature']=app.state.twilio_validator.compute_signature(app.state.settings.twilio_webhook_url,FormData(form))
        async def slow(*args):await asyncio.sleep(2)
        instance.enqueue=slow
        start=asyncio.get_running_loop().time()
        result=await client.post('/api/v1/integrations/whatsapp/webhook',content=raw,headers=headers)
        assert result.status_code==503
        assert asyncio.get_running_loop().time()-start < .7


@pytest.mark.asyncio
async def test_worker_stages_result_before_send_with_real_media_argument(queue):
    instance,storage,app=queue
    raw=urlencode(fields()).encode();row=dict(id=1,state='STAGED',created_at=datetime.now(timezone.utc),
        message_sid=fields()['MessageSid'],input_sha256=inbound_digest(raw),
        payload_ciphertext=instance.encrypt(raw),key_id='v1',receiver_e164='+14155238886',sender_e164='+447700900123')
    instance.claim=AsyncMock(return_value=row);instance.mark=AsyncMock()
    output=[OutboundPart(body='Quote options'),OutboundPart(body='Carrier document',media_url='https://safe.example/qr.png')]
    with patch('backend.whatsapp_queue.process_inbound',AsyncMock(return_value=output)) as process:
        assert await instance.drain()
        assert process.await_args.args[2]==row['created_at']
    assert [p['state'] for p in storage.parts]==['ACCEPTED','ACCEPTED']
    assert instance.client.messages.create.call_args.kwargs['media_url']==['https://safe.example/qr.png']
    assert 'media_url' not in instance.client.messages.create.call_args_list[0].kwargs
    assert all(len(p['payload_ciphertext'])>0 for p in storage.parts)
    assert any('UPDATE public.whatsapp_inbound_queue SET state=$2' in sql and args==(1,'ACCEPTED') for sql,args in storage.calls)


@pytest.mark.asyncio
async def test_unknown_send_is_fenced_and_never_replayed(queue):
    instance,storage,app=queue
    await instance.stage(1,[OutboundPart(body='Sensitive confirmation')])
    row=dict(id=1,receiver_e164='+14155238886',sender_e164='+447700900123')
    instance.client.messages.create.side_effect=TimeoutError('unknown remote outcome')
    instance.mark=AsyncMock()
    await instance.dispatch(row)
    assert storage.parts[0]['state']=='REVIEW_REQUIRED'
    await instance.dispatch(row)
    instance.client.messages.create.assert_called_once()
    assert instance.mark.await_args.args==(1,'REVIEW_REQUIRED','UNCERTAIN_SEND')


@pytest.mark.asyncio
async def test_expired_window_and_interrupted_action_do_not_send_or_rerun(queue):
    instance,storage,app=queue
    row=dict(id=1,state='STAGED',created_at=datetime.now(timezone.utc)-timedelta(days=2))
    instance.claim=AsyncMock(return_value=row);instance.mark=AsyncMock()
    with patch('backend.whatsapp_queue.process_inbound',AsyncMock()) as process:
        await instance.drain();process.assert_not_awaited()
    instance.mark.assert_awaited_once_with(1,'FAILED','SERVICE_WINDOW_EXPIRED')
    instance.client.messages.create.assert_not_called()


def test_chunking_retains_links_and_unverified_media_is_not_dispatched():
    from backend.agents.conversational_gateway import message_xml
    url='https://safe.example/?token='+'x'*1200
    parts=reply_parts(message_xml('Read this\n'+url+'\n'+('a '*1200)))
    assert all(len(p.body)<=1590 for p in parts)
    assert any(url in p.body for p in parts)
    assert return_media({'action_taken':'TRIGGER_RETURN','return_request':{'status':'BOOKED',
        'paperless_available':True,'qr_requires_workspace_login':True}},SimpleNamespace()) is None


@pytest.mark.asyncio
async def test_ready_recovery_sends_only_unsent_parts_without_executing_the_action(queue):
    instance,storage,app=queue
    await instance.stage(1,[OutboundPart(body='Already accepted'),OutboundPart(body='Remaining')])
    storage.parts[0]['state']='ACCEPTED'
    raw=urlencode(fields()).encode()
    row=dict(id=1,state='READY',created_at=datetime.now(timezone.utc),message_sid=fields()['MessageSid'],
        input_sha256=inbound_digest(raw),payload_ciphertext=instance.encrypt(raw),key_id='v1',
        receiver_e164='+14155238886',sender_e164='+447700900123')
    instance.claim=AsyncMock(return_value=row);instance.mark=AsyncMock()
    with patch('backend.whatsapp_queue.process_inbound',AsyncMock()) as process:
        await instance.drain();process.assert_not_awaited()
    instance.client.messages.create.assert_called_once()
    assert instance.client.messages.create.call_args.kwargs['body']=='Remaining'


@pytest.mark.asyncio
async def test_definite_twilio_rejection_is_recorded_without_automatic_retries(queue):
    from twilio.base.exceptions import TwilioRestException
    instance,storage,_=queue
    await instance.stage(1,[OutboundPart(body='A reply')])
    instance.client.messages.create.side_effect=TwilioRestException(429,'/Messages')
    instance.mark=AsyncMock()
    await instance.dispatch(dict(id=1,receiver_e164='+14155238886',sender_e164='+447700900123'))
    assert storage.parts[0]['state']=='FAILED'
    instance.mark.assert_awaited_once_with(1,'FAILED','TWILIO_REJECTED')
    instance.client.messages.create.assert_called_once()


def test_media_requires_our_scoped_https_document_token_for_the_same_shipment():
    from uuid import uuid4
    from backend.return_documents import public_return_links
    config=SimpleNamespace(quote_link_secret=SecretStr('x'*40),booking_page_url='https://app.example/',auth_recovery_redirect_url='')
    context=SimpleNamespace(tenant_id=uuid4())
    data=public_return_links(config,context,dict(status='BOOKED',paperless_available=True,shipment_id=uuid4()))
    result=dict(action_taken='TRIGGER_RETURN',return_request=data)
    assert return_media(result,config)==data['return_dropoff_qr_code_url']
    assert return_media(result|{'return_request':data|{'shipment_id':uuid4()}},config) is None
    assert return_media(result|{'return_request':data|{'return_dropoff_qr_code_url':'https://evil.example/qr.png'}},config) is None


@pytest.mark.asyncio
async def test_rejected_media_falls_back_once_to_text_without_replaying_action(queue):
    from twilio.base.exceptions import TwilioRestException
    instance,storage,_=queue
    await instance.stage(1,[OutboundPart(body='Carrier QR',media_urls=['https://safe.example/image.png'],fallback_view_url='https://app.example/view')])
    row=dict(id=1,receiver_e164='+14155238886',sender_e164='+447700900123')
    instance.client.messages.create.side_effect=TwilioRestException(400,'/Messages')
    await instance.dispatch(row)
    assert storage.parts[0]['state']=='FAILED' and len(storage.parts)==2
    instance.client.messages.create.side_effect=None
    instance.client.messages.create.return_value=SimpleNamespace(sid='SM'+'e'*32)
    await instance.dispatch(row)
    assert len(storage.parts)==2 and storage.parts[1]['state']=='ACCEPTED'
    sent=instance.client.messages.create.call_args.kwargs
    assert 'media_url' not in sent and 'https://app.example/view' in sent['body']


@pytest.mark.asyncio
async def test_signed_media_delivery_failure_stages_one_fallback_and_rejects_forgery(queue):
    from backend.whatsapp_queue import build_media_status_router
    instance,storage,app=queue
    app.include_router(build_media_status_router())
    await instance.stage(1,[OutboundPart(body='Carrier QR',media_urls=['https://safe.example/image.png'],fallback_view_url='https://app.example/view')])
    storage.parts[0].update(state='ACCEPTED',provider_message_sid='SM'+'d'*32)
    form={'AccountSid':instance.settings.twilio_account_sid,'MessageSid':'SM'+'d'*32,'MessageStatus':'failed',
        'From':'whatsapp:+14155238886','To':'whatsapp:+447700900123'}
    signature=app.state.twilio_validator.compute_signature(instance.status_url(1),FormData(form))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://hooks.example') as client:
        url='/api/v1/integrations/whatsapp/outbound-status/1'
        headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':'bad'}
        assert (await client.post(url,content=urlencode(form),headers=headers)).status_code==403
        assert len(storage.parts)==1
        headers['X-Twilio-Signature']=signature
        for _ in range(2):assert (await client.post(url,content=urlencode(form),headers=headers)).status_code==200
    assert len(storage.parts)==2 and storage.parts[1]['fallback_for']==1


@pytest.mark.asyncio
async def test_signed_failed_callback_can_resolve_an_uncertain_media_send_without_replaying_it(queue):
    from backend.whatsapp_queue import build_media_status_router
    instance,storage,app=queue;app.include_router(build_media_status_router())
    await instance.stage(1,[OutboundPart(body='Carrier QR',media_urls=['https://safe.example/image.png'],fallback_view_url='https://app.example/view')])
    storage.parts[0].update(state='REVIEW_REQUIRED',provider_message_sid=None)
    form={'AccountSid':instance.settings.twilio_account_sid,'MessageSid':'SM'+'d'*32,'MessageStatus':'failed','From':'whatsapp:+14155238886','To':'whatsapp:+447700900123'}
    signature=app.state.twilio_validator.compute_signature(instance.status_url(1),FormData(form))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://hooks.example') as client:
        result=await client.post('/api/v1/integrations/whatsapp/outbound-status/1',content=urlencode(form),
            headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':signature})
    assert result.status_code==200 and storage.parts[0]['state']=='ACCEPTED'
    assert len(storage.parts)==2 and storage.parts[1]['fallback_for']==1
    instance.client.messages.create.assert_not_called()
