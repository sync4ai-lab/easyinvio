"""Sender journey queues run on disposable PostgreSQL and mocked messaging APIs."""
import json
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import SecretStr, ValidationError
from backend.shipment_notifications import (SenderNotifications, ShipmentNotificationSettings,
    ShipmentNotificationWorker, target_for, notice_content)
from test_tracking_workspace_postgres import world, ROOT


def settings():
    return SimpleNamespace(provider_environment='TEST',twilio_enabled=True,
        twilio_account_sid='AC'+'1'*32,twilio_auth_token=SecretStr('synthetic'),twilio_whatsapp_number='+14155238886')


def config(**changes):
    return ShipmentNotificationSettings(_env_file=None, **dict(email_delivery_provider='SENDGRID', shipment_email_notifications_enabled=True,
        shipment_sendgrid_api_key='synthetic',shipment_whatsapp_notifications_enabled=True,
        shipment_whatsapp_content_sid='HX'+'2'*32,
        shipment_notification_test_recipients=['sender@example.test','+447700900111'], **changes))


def payload():
    return {'automation_order':{'origin':{'name':'Sender','line1':'1 Example Street','city':'London','postal_code':'SW1A 1AA','country_code':'GB',
        'email':'sender@example.test','phone':'+447700900111'},
        'sender_notifications':{'email':True,'whatsapp':True,'whatsapp_permission_confirmed':True}}}


def test_explicit_permission_and_environment_recipient_gates():
    with pytest.raises(ValidationError):SenderNotifications(whatsapp=True)
    row={'channel':'EMAIL','environment':'TEST','logistics_metadata':payload()}
    assert target_for(row,config(),settings())==('sender@example.test',None)
    row['environment']='LIVE'
    assert target_for(row,config(),settings())[1]=='ENVIRONMENT_MISMATCH'
    row['environment']='TEST';row['logistics_metadata']['automation_order']['origin']['email']='other@example.test'
    assert target_for(row,config(),settings())[1]=='TEST_RECIPIENT_NOT_ALLOWED'
    row['channel']='WHATSAPP';row['logistics_metadata']['automation_order']['sender_notifications']['whatsapp_permission_confirmed']=False
    assert target_for(row,config(),settings())[1]=='WHATSAPP_PERMISSION_MISSING'


async def migrate(w):
    await w.db.command("ALTER TABLE public.tenants ADD COLUMN is_sandbox boolean NOT NULL DEFAULT true; ALTER TABLE public.shipments ADD COLUMN sender_address jsonb NOT NULL DEFAULT '{}'; CREATE TABLE public.return_customer_deliveries(id bigint);",mode='exec')
    await w.db.command((ROOT/'migrations/047_sender_shipment_notifications.sql').read_text(encoding='utf-8'),mode='exec')
    await w.db.command("ALTER TABLE public.shipment_sender_notifications ADD COLUMN provider text,ADD COLUMN provider_account text DEFAULT '';",mode='exec')
    await w.db.execute("UPDATE public.shipments SET logistics_metadata=$2::jsonb WHERE id=$1",w.shipments[0],json.dumps(payload()))
    await w.db.execute("UPDATE public.shipments SET status='FAILED' WHERE id=$1",w.shipments[0])
    await w.db.execute("UPDATE public.shipments SET status='BOOKED' WHERE id=$1",w.shipments[0])


@pytest.mark.asyncio
async def test_transactional_milestones_duplicates_stale_events_and_rls(world):
    w=world;await migrate(w)
    assert await w.db.fetchval('SELECT count(*) FROM public.shipment_sender_notifications')==2
    await w.db.execute("UPDATE public.shipments SET status='BOOKED' WHERE id=$1",w.shipments[0])
    assert await w.db.fetchval('SELECT count(*) FROM public.shipment_sender_notifications')==2
    async def event(milestone,applied=True):
        await w.db.execute("INSERT INTO public.tracking_events(tenant_id,shipment_id,integration_key_id,event_id,body_sha256,status,occurred_at,response) VALUES($1,$2,'synthetic',$3,$4,'IN_TRANSIT',now(),$5::jsonb)",
            w.tenants[0],w.shipments[0],str(uuid4()),'a'*64,json.dumps({'applied':applied,'tracking_detail':{'milestone':milestone}}))
    await event('OUT_FOR_DELIVERY',False)
    assert await w.db.fetchval('SELECT count(*) FROM public.shipment_sender_notifications')==2
    await event('OUT_FOR_DELIVERY');await event('OUT_FOR_DELIVERY')
    assert await w.db.fetchval('SELECT count(*) FROM public.shipment_sender_notifications')==4
    await event('DELIVERED')
    assert await w.db.fetchval('SELECT count(*) FROM public.shipment_sender_notifications')==4
    await w.db.execute("UPDATE public.shipments SET status='DELIVERED' WHERE id=$1",w.shipments[0]);await event('DELIVERED')
    assert await w.db.fetchval('SELECT count(*) FROM public.shipment_sender_notifications')==6
    with pytest.raises(RuntimeError):
        async with w.db.transaction():
            await w.db.execute("UPDATE public.shipments SET status='CANCELLED' WHERE id=$1",w.shipments[0])
            raise RuntimeError('rollback synthetic booking')
    assert await w.db.fetchval('SELECT count(*) FROM public.shipment_sender_notifications')==6
    await w.db.command('SET ROLE authenticated',mode='exec')
    try:
        with pytest.raises(Exception):await w.db.fetch('SELECT * FROM public.shipment_sender_notifications')
    finally:await w.db.command('RESET ROLE',mode='exec')


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome',['accepted','rejected','ambiguous'])
async def test_delivery_commits_intent_and_never_replays_ambiguous_sends(world,outcome):
    w=world;await migrate(w);calls=[]
    async def server(request):
        calls.append(request)
        state=await w.db.fetchval('SELECT state FROM public.shipment_sender_notifications ORDER BY id LIMIT 1')
        assert state=='SENDING'
        assert request.url.host=='api.sendgrid.com'
        if outcome=='ambiguous':raise httpx.ReadTimeout('synthetic')
        return httpx.Response(202 if outcome=='accepted' else 400,headers={'x-message-id':'synthetic-receipt'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        lifecycle=SimpleNamespace(pool=w.db,client=client,automation=SimpleNamespace(settings=settings()))
        worker=ShipmentNotificationWorker(lifecycle,config())
        assert await worker.drain()
        state=await w.db.fetchval('SELECT state FROM public.shipment_sender_notifications ORDER BY id LIMIT 1')
        assert state=={'accepted':'ACCEPTED','rejected':'FAILED','ambiguous':'REVIEW_REQUIRED'}[outcome]
        # Isolate the email: the WhatsApp row remains a separate delivery.
        await w.db.execute("UPDATE public.shipment_sender_notifications SET state='SKIPPED' WHERE channel='WHATSAPP'")
        assert not await worker.drain()
        assert len(calls)==1
        assert '[UAT TEST]' in json.loads(calls[0].content)['subject']


@pytest.mark.asyncio
async def test_whatsapp_uses_approved_template_not_free_form(world):
    w=world;await migrate(w)
    await w.db.execute("UPDATE public.shipment_sender_notifications SET state='SKIPPED' WHERE channel='EMAIL'")
    calls=[]
    async def server(request):
        from urllib.parse import parse_qs
        body=parse_qs(request.content.decode());calls.append(body)
        assert body['ContentSid']==['HX'+'2'*32] and 'Body' not in body and 'MediaUrl' not in body
        return httpx.Response(201,json={'sid':'SM'+'3'*32})
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        worker=ShipmentNotificationWorker(SimpleNamespace(pool=w.db,client=client,automation=SimpleNamespace(settings=settings())),config())
        assert await worker.drain()
        assert not await worker.drain()
    assert len(calls)==1


@pytest.mark.asyncio
async def test_live_placeholder_reference_cannot_capture_financial_settlement():
    from main import FinanceEngine
    engine=object.__new__(FinanceEngine)
    engine.settings=SimpleNamespace(provider_environment='LIVE')
    with pytest.raises(ValueError, match='placeholder'):
        await engine.finish_booking(None,'SUCCESS',tracking_number='000000000000',label_storage_path='https://example.test/label.pdf')


@pytest.mark.asyncio
async def test_explicit_rate_limit_retries_are_bounded_and_backed_off(world):
    w=world;await migrate(w)
    await w.db.execute("UPDATE public.shipment_sender_notifications SET state='SKIPPED' WHERE channel='WHATSAPP'")
    calls=[]
    def server(request):
        calls.append(request);return httpx.Response(429)
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        worker=ShipmentNotificationWorker(SimpleNamespace(pool=w.db,client=client,automation=SimpleNamespace(settings=settings())),config())
        for attempt in range(3):
            assert await worker.drain()
            if attempt<2:
                assert not await worker.drain()
                await w.db.execute("UPDATE public.shipment_sender_notifications SET next_attempt_at=now()-interval '1 second' WHERE channel='EMAIL'")
        assert not await worker.drain()
    assert len(calls)==3
    row=await w.db.fetchrow("SELECT state,attempts FROM public.shipment_sender_notifications WHERE channel='EMAIL'")
    assert row['state']=='FAILED' and row['attempts']==3

@pytest.mark.asyncio
@pytest.mark.parametrize('outcome',['accepted','temporary','uncertain'])
async def test_hostinger_worker_commits_before_send_and_preserves_retry_fences(world,monkeypatch,outcome):
    from backend.email_delivery import EmailReceipt
    w=world;await migrate(w)
    await w.db.execute("UPDATE public.shipment_sender_notifications SET state='SKIPPED' WHERE channel='WHATSAPP'")
    cfg=config();cfg.email_delivery_provider='HOSTINGER_SMTP'
    cfg.smtp_username='support@easyinvio.com';cfg.smtp_password=SecretStr('synthetic')
    calls=[]
    async def smtp(client,config,**message):
        assert await w.db.fetchval("SELECT state FROM public.shipment_sender_notifications WHERE channel='EMAIL'")=='SENDING'
        assert message['sender']=='support@easyinvio.com' and message['recipient']=='sender@example.test'
        calls.append(message)
        return {'accepted':EmailReceipt('ACCEPTED','synthetic-smtp-id'),
                'temporary':EmailReceipt('RETRYABLE',error_code='SMTP_TEMPORARY_REFUSAL'),
                'uncertain':EmailReceipt('REVIEW_REQUIRED',error_code='SMTP_SEND_OUTCOME_UNCERTAIN')}[outcome]
    monkeypatch.setattr('backend.shipment_notifications.send_notification_email',smtp)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:pytest.fail('SMTP must not call an HTTP email provider'))) as client:
        worker=ShipmentNotificationWorker(SimpleNamespace(pool=w.db,client=client,automation=SimpleNamespace(settings=settings())),cfg)
        for attempt in range(3 if outcome=='temporary' else 1):
            assert await worker.drain()
            assert not await worker.drain()
            if outcome=='temporary' and attempt<2:
                await w.db.execute("UPDATE public.shipment_sender_notifications SET next_attempt_at=now()-interval '1 second' WHERE channel='EMAIL'")
        row=await w.db.fetchrow("SELECT state,attempts FROM public.shipment_sender_notifications WHERE channel='EMAIL'")
    assert row['state']=={'accepted':'ACCEPTED','temporary':'FAILED','uncertain':'REVIEW_REQUIRED'}[outcome]
    assert row['attempts']==len(calls)==(3 if outcome=='temporary' else 1)
    assert len({call['message_key'] for call in calls})==1
