"""Offline self-service contract/security tests. No provider or hosted DB calls."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import httpx
import pytest
from fastapi import FastAPI,HTTPException,Request
from pydantic import ValidationError,SecretStr
from cryptography.fernet import Fernet
from backend.whatsapp_provider import (WhatsAppProviderSettings,TemplateBinding,GupshupAdapter,
    authenticate_gupshup_origin,recipient_error,enabled)
from backend.gupshup_ingress import parse_event,GupshupQueue,build_router
from backend.whatsapp_dispatch import send_selected
from backend.whatsapp_bot import initialize_whatsapp

TESTER='+447700900123'
SOURCE='+447700900321'

def settings(**changes):
    values=dict(whatsapp_provider='GUPSHUP',gupshup_enabled=True,gupshup_api_key='synthetic-not-real',
        gupshup_app_name='OfflineApp',gupshup_app_id='offline-app',gupshup_source_number=SOURCE,
        gupshup_webhook_url='https://app.example.test/api/v1/integrations/whatsapp/gupshup/webhook',
        gupshup_webhook_auth_mode='SOURCE_IP',gupshup_callback_ips_confirmed=True,gupshup_callback_ips=['192.0.2.10'],
        whatsapp_uat_mode=True,whatsapp_test_recipients=[TESTER],whatsapp_outbound_paused=False)
    values.update(changes)
    config=WhatsAppProviderSettings(_env_file=None,**values)
    # No Twilio credentials at all. Match real main.Settings plus non-messaging app settings.
    return config

def event(**changes):
    value={'app':'OfflineApp','version':2,'timestamp':int(datetime.now(timezone.utc).timestamp()*1000),
        'type':'message','payload':{'id':'gs-offline-1','source':TESTER[1:],'type':'text','payload':{'text':'help'},'sender':{'phone':TESTER[1:]}}}
    value.update(changes);return value

def test_safe_defaults_and_no_twilio_requirement():
    s=WhatsAppProviderSettings(_env_file=None)
    assert not enabled(s) and s.whatsapp_outbound_paused and s.whatsapp_uat_mode
    s=settings();assert enabled(s) and initialize_whatsapp(s)
    assert not hasattr(s,'twilio_account_sid')
    with pytest.raises(ValidationError):settings(gupshup_callback_ips_confirmed=False)
    with pytest.raises(ValidationError):settings(gupshup_webhook_url='https://app.example.test/wrong')
    with pytest.raises(ValidationError):settings(gupshup_callback_ips=['0.0.0.0/0'])
    with pytest.raises(ValidationError):settings(gupshup_product='PARTNER')

@pytest.mark.parametrize('kind',['CHAT','SUPPORT','SHIPMENT','RETURN'])
@pytest.mark.asyncio
async def test_every_path_blocks_unlisted_or_paused_before_any_io(kind):
    for s,recipient in [(settings(),'+447700900999'),(settings(whatsapp_outbound_paused=True),TESTER)]:
        client=SimpleNamespace(post=AsyncMock());pool=SimpleNamespace(acquire=lambda:pytest.fail('No DB or network allowed'))
        with pytest.raises(HTTPException):
            await send_selected(s,pool,client,{'To':'whatsapp:'+recipient,'Body':'test'},logical_key='x',kind=kind,target_id=1)
        client.post.assert_not_awaited()

def request(ip,headers=()):
    return Request({'type':'http','method':'POST','path':'/','headers':headers,'client':(ip,1)})

def test_origin_authentication_rejects_forgery_and_wrong_forwarding(monkeypatch):
    s=settings();monkeypatch.delenv('VERCEL',raising=False)
    authenticate_gupshup_origin(request('192.0.2.10'),s)
    with pytest.raises(HTTPException):authenticate_gupshup_origin(request('192.0.2.20',[(b'x-vercel-forwarded-for',b'192.0.2.10')]),s)
    monkeypatch.setenv('VERCEL','1')
    authenticate_gupshup_origin(request('127.0.0.1',[(b'x-vercel-forwarded-for',b'192.0.2.10')]),s)
    for headers in [[],[(b'x-forwarded-for',b'192.0.2.10')],[(b'x-vercel-forwarded-for',b'192.0.2.10, 192.0.2.20')],[(b'x-vercel-forwarded-for',b'192.0.2.10')]*2]:
        with pytest.raises(HTTPException):authenticate_gupshup_origin(request('127.0.0.1',headers),s)

def test_inbound_normalization_account_binding_and_media_conflict():
    s=settings();kind,form,external,stamp=parse_event(event(),s)
    assert kind=='message' and form['To']=='whatsapp:'+SOURCE and form['MessageSid'].startswith('gs:')
    assert external=='gs-offline-1' and form['Body']=='help' and stamp.tzinfo
    for changes in [{'app':'other'},{'version':1},{'timestamp':0},{'phone':'447700900999'}]:
        with pytest.raises(ValueError):parse_event(event(**changes),s)
    value=event();value['payload']['sender']['phone']='447700900999'
    with pytest.raises(ValueError):parse_event(value,s)
    value=event();value['payload'].update(type='image',payload={'url':'https://example.test/a.png'})
    first=parse_event(value,s)[1];value['payload']['payload']['url']='https://example.test/b.png'
    assert first['ProviderContentHash']!=parse_event(value,s)[1]['ProviderContentHash']
    assert first['NumMedia']=='1'
    assert parse_event(event(type='user-event',payload={'type':'sandbox-start'}),s)[0]=='ignored'

@pytest.mark.parametrize('status,expected',[('enqueued','ACCEPTED'),('sent','SENT'),('delivered','DELIVERED'),('read','READ'),('failed','FAILED')])
def test_receipt_external_and_whatsapp_id_mapping(status,expected):
    p={'id':'wa-id' if status in {'sent','delivered','read'} else 'gs-id','type':status,'destination':TESTER[1:]}
    if status in {'sent','delivered','read'}:p['gsId']='gs-id'
    _,receipt,_,_=parse_event(event(type='message-event',payload=p),settings())
    assert receipt['external']=='gs-id' and receipt['status']==expected

@pytest.mark.asyncio
async def test_text_template_and_media_official_wire_contract():
    captured=[]
    async def send(url,**kwargs):
        captured.append((url,kwargs));return httpx.Response(202,json={'status':'submitted','messageId':'external-id'})
    adapter=GupshupAdapter(settings(),SimpleNamespace(post=send));now=datetime.now(timezone.utc)
    result=await adapter.send(TESTER,'hello',received_at=now)
    assert result.outcome=='ACCEPTED'
    url,k=captured[-1];assert url=='https://api.gupshup.io/wa/api/v1/msg'
    assert k['data']['source']==SOURCE[1:] and k['data']['destination']==TESTER[1:]
    assert json.loads(k['data']['message'])=={'type':'text','text':'hello'} and not k['follow_redirects']
    binding=TemplateBinding(provider_id='approved-id',language='en_GB',parameters=['body'])
    await adapter.send(TESTER,'',binding=binding,parameters={'body':'notice'})
    assert captured[-1][0].endswith('/template/msg')
    assert json.loads(captured[-1][1]['data']['template'])=={'id':'approved-id','params':['notice']}
    for path,type_ in [('document.pdf','file'),('image.png','image')]:
        await adapter.send(TESTER,'document',media_url='https://example.test/'+path,received_at=now)
        assert json.loads(captured[-1][1]['data']['message'])['type']==type_
    count=len(captured)
    assert (await adapter.send(TESTER,'late',received_at=now-timedelta(hours=24))).code=='SESSION_WINDOW_REQUIRED'
    assert (await adapter.send(TESTER,'',binding=binding,parameters={})).code=='TEMPLATE_PARAMETERS_MISSING'
    assert len(captured)==count

@pytest.mark.parametrize('status,body,expected',[(401,{},'REJECTED'),(429,{},'REJECTED'),(500,{},'UNCERTAIN'),(202,{},'UNCERTAIN'),(202,[],'UNCERTAIN'),(202,{'status':'submitted','messageId':12},'UNCERTAIN')])
@pytest.mark.asyncio
async def test_no_unsafe_retries_or_failover(status,body,expected):
    post=AsyncMock(return_value=httpx.Response(status,json=body))
    result=await GupshupAdapter(settings(),SimpleNamespace(post=post)).send(TESTER,'test',received_at=datetime.now(timezone.utc))
    assert result.outcome==expected and post.await_count==1

@pytest.mark.asyncio
async def test_timeout_is_uncertain():
    post=AsyncMock(side_effect=httpx.ReadTimeout('synthetic timeout'))
    result=await GupshupAdapter(settings(),SimpleNamespace(post=post)).send(TESTER,'test',received_at=datetime.now(timezone.utc))
    assert result.outcome=='UNCERTAIN' and post.await_count==1

@pytest.mark.asyncio
async def test_ack_only_persists_and_never_executes_business_actions(monkeypatch):
    monkeypatch.delenv('VERCEL',raising=False)
    app=FastAPI();app.state.settings=settings();app.include_router(build_router())
    q=GupshupQueue.__new__(GupshupQueue);q.enqueue_event=AsyncMock();app.state.whatsapp_queue=q
    transport=httpx.ASGITransport(app=app,client=('192.0.2.10',1))
    async with httpx.AsyncClient(transport=transport,base_url='https://app.example.test') as client:
        response=await client.post('/api/v1/integrations/whatsapp/gupshup/webhook',json=event())
        assert response.status_code==200 and response.content==b'' and q.enqueue_event.await_count==1
        for raw,code in [(b'{"app":"a","app":"b"}',422),(b'x'*32769,413)]:
            response=await client.post('/api/v1/integrations/whatsapp/gupshup/webhook',content=raw,headers={'content-type':'application/json'})
            assert response.status_code==code
        wrong=event();wrong['app']='wrong'
        assert (await client.post('/api/v1/integrations/whatsapp/gupshup/webhook',json=wrong)).status_code==422
        assert q.enqueue_event.await_count==1


def test_configured_custom_header_origin_from_self_service_dashboard():
    # The supplied self-service UI explicitly supports custom key/value headers.
    s=settings(gupshup_webhook_auth_mode='HEADER',gupshup_webhook_token='synthetic-random-header-token-over-32-bytes',
        gupshup_callback_ips_confirmed=False,gupshup_callback_ips=[])
    header=(b'x-easyinvio-webhook-token',b'synthetic-random-header-token-over-32-bytes')
    authenticate_gupshup_origin(request('192.0.2.20',[header]),s)
    for headers in [[],[(header[0],b'wrong')],[header,header]]:
        with pytest.raises(HTTPException):authenticate_gupshup_origin(request('192.0.2.20',headers),s)
    with pytest.raises(ValidationError):settings(gupshup_webhook_auth_mode='HEADER',gupshup_webhook_token='short')


@pytest.mark.asyncio
async def test_original_gupshup_receipts_survive_explicit_twilio_rollback(monkeypatch):
    monkeypatch.delenv('VERCEL',raising=False)
    app=FastAPI();app.state.settings=settings(whatsapp_provider='TWILIO');app.include_router(build_router())
    q=GupshupQueue.__new__(GupshupQueue);q.enqueue_event=AsyncMock()
    c=AsyncMock();c.__aenter__.return_value=c
    q.pool=SimpleNamespace(acquire=lambda **_:c);app.state.whatsapp_queue=q
    transport=httpx.ASGITransport(app=app,client=('192.0.2.10',1))
    async with httpx.AsyncClient(transport=transport,base_url='https://app.example.test') as client:
        receipt=event(type='message-event',payload={'type':'delivered','id':'wa-legacy','gsId':'gs-legacy','destination':TESTER[1:]})
        assert (await client.post('/api/v1/integrations/whatsapp/gupshup/webhook',json=receipt)).status_code==200
        assert c.execute.call_args.args[1]=='offline-app'
        assert (await client.post('/api/v1/integrations/whatsapp/gupshup/webhook',json=event())).status_code==503
        q.enqueue_event.assert_not_awaited()


def test_whatsapp_receipt_ids_allow_documented_base64_characters():
    value=event(type='message-event',payload={'type':'delivered','id':'wamid.HBg/+opaque==','gsId':'gs-id','destination':TESTER[1:]})
    receipt=parse_event(value,settings())[1]
    assert receipt['whatsapp']=='wamid.HBg/+opaque==' and receipt['external']=='gs-id'
