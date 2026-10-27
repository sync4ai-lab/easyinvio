"""Migration/queue tests in existing synthetic PGlite fixture, not hosted schema certification.
Actual migration files are applied. Missing pre-migration base dependencies below
are deliberately synthetic test prerequisites, never production DDL instructions.
"""
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4
import json
import httpx
import pytest
import asyncpg
from cryptography.fernet import Fernet
from fastapi import FastAPI,HTTPException
from pydantic import SecretStr
from backend.gupshup_ingress import GupshupQueue,parse_event
from backend.whatsapp_queue import OutboundPart
from backend.whatsapp_dispatch import reconcile_events,send_selected
from backend.shipment_notifications import ShipmentNotificationWorker,ShipmentNotificationSettings
from backend.support_delivery import SupportDelivery,DeliverySettings
from backend.return_delivery import ReturnDeliveryWorker,ReturnDeliverySettings
from test_tracking_workspace_postgres import world,ROOT
from test_return_review_postgres import setup as return_setup
from test_gupshup_provider import settings,event,TESTER,SOURCE

async def prepare(w):
    x=await return_setup(w)
    # return_setup exposes post-049 columns to its independent regression suite;
    # remove those fixture-only columns before testing the actual migration.
    await w.db.command("""ALTER TABLE public.return_customer_deliveries DROP COLUMN provider,DROP COLUMN provider_account;
      ALTER TABLE public.tenants ADD COLUMN is_sandbox boolean DEFAULT true;
      ALTER TABLE public.shipments ADD COLUMN sender_address jsonb DEFAULT '{}',ADD COLUMN final_client_price numeric,ADD COLUMN profit_markup numeric;
      ALTER TABLE public.wallet_topups ADD COLUMN created_at timestamptz,ADD COLUMN currency text,ADD COLUMN amount numeric;
      ALTER TABLE public.support_tickets ADD COLUMN created_at timestamptz;
      CREATE TABLE public.whatsapp_bindings(id uuid PRIMARY KEY,tenant_id uuid,user_id uuid,
        sender_e164 text,receiver_e164 text,is_active boolean DEFAULT true,verified_at timestamptz,
        notification_opt_in boolean DEFAULT false,last_inbound_at timestamptz);
      ALTER TABLE public.support_message_outbox ADD COLUMN recipient_e164 text,ADD COLUMN body text;
    """,mode='exec')
    for filename in ['017_support_delivery_and_monitoring.sql','039_whatsapp_onboarding.sql','047_sender_shipment_notifications.sql']:
        await w.db.command((ROOT/'migrations'/filename).read_text(encoding='utf-8'),mode='exec')
    # Representative existing records before schema change.
    old=await w.db.fetchval("""INSERT INTO public.whatsapp_inbound_queue(message_sid,sender_e164,receiver_e164,input_sha256,payload_ciphertext,key_id,state)
      VALUES($1,$2,$3,$4,decode($5,'hex'),'v1','ACCEPTED') RETURNING id""",'SM'+'a'*32,TESTER,SOURCE,'a'*64,b'legacy-encrypted-bytes'.hex())
    await w.db.execute("INSERT INTO public.whatsapp_reply_outbox(inbound_id,part_index,payload_ciphertext,key_id,state,provider_message_sid) VALUES($1,0,decode($2,'hex'),'v1','ACCEPTED',$3)",old,b'legacy-reply-bytes'.hex(),'SM'+'c'*32)
    await w.db.execute("INSERT INTO public.support_message_outbox(tenant_id,status) VALUES($1,'STAGED')",w.tenants[0])
    await w.db.command((ROOT/'migrations/049_whatsapp_providers.sql').read_text(encoding='utf-8'),mode='exec')
    # Extend the disposable JSON bridge to represent asyncpg bytea correctly.
    original=w.db.command
    async def command(sql,args=(),mode='query'):
        args=tuple({'__bytea_hex__':a.hex()} if isinstance(a,bytes) else a for a in args)
        rows=await original(sql,args,mode)
        for row in rows:
            for name,value in list(row.items()):
                if name.endswith('ciphertext') and isinstance(value,dict) and '__bytea_hex__' in value:row[name]=bytes.fromhex(value['__bytea_hex__'])
        return rows
    w.db.command=command
    s=settings(gupshup_templates={name:{'provider_id':'approved-'+name,'language':'en_GB','parameters':params}
        for name,params in [('SUPPORT',['body']),('SHIPMENT',['reference','body','tracking']),('RETURN',['heading','body','link'])]})
    s=SimpleNamespace(**dict(s),credential_keys={'v1':SecretStr(Fernet.generate_key().decode())},
        database_environment='SANDBOX',provider_environment='TEST',whatsapp_onboarding_enabled=False,
        platform_admin_user_ids=[],quote_link_secret=SecretStr('synthetic-link-secret-32-characters-long'),booking_page_url='https://app.example.test')
    app=FastAPI();app.state.settings=s;app.state.rating=SimpleNamespace(client=SimpleNamespace(post=AsyncMock()))
    class Pool:
        def acquire(self,**kwargs):return w.db.acquire()
    q=GupshupQueue(Pool(),s,app);app.state.whatsapp_queue=q
    return x,s,q,old

@pytest.mark.asyncio
async def test_actual_migration_preserves_legacy_rows_and_private_rls(world):
    w=world;_,s,q,old=await prepare(w)
    row=await w.db.fetchrow('SELECT * FROM public.whatsapp_inbound_queue WHERE id=$1',old)
    assert row['provider']=='TWILIO' and bytes(row['payload_ciphertext'])==b'legacy-encrypted-bytes'
    assert await w.db.fetchval('SELECT provider FROM public.support_message_outbox')=='TWILIO'
    assert await w.db.fetchval("SELECT bool_and(relrowsecurity) FROM pg_class WHERE oid IN ('public.whatsapp_delivery_attempts'::regclass,'public.whatsapp_delivery_events'::regclass)")
    await w.db.command('SET ROLE authenticated',mode='exec')
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):await w.db.fetch('SELECT * FROM public.whatsapp_delivery_attempts')
    finally:await w.db.command('RESET ROLE',mode='exec')
    assert not await q.claim() # Old Twilio inbox cannot be consumed by Gupshup.

@pytest.mark.asyncio
async def test_duplicate_ingress_business_action_once_and_receipt_race(world):
    w=world;_,s,q,_=await prepare(w)
    _,form,external,stamp=parse_event(event(),s)
    await q.enqueue_event(form,external,stamp);await q.enqueue_event(form,external,stamp)
    assert await w.db.fetchval("SELECT count(*) FROM public.whatsapp_inbound_queue WHERE provider='GUPSHUP'")==1
    changed=event();changed['payload']['payload']['text']='different'
    with pytest.raises(HTTPException):await q.enqueue_event(parse_event(changed,s)[1],external,stamp)
    calls=[]
    async def send(url,**kwargs):
        # Receipt arrives before the HTTP acceptance response is saved.
        assert await w.db.fetchval("SELECT state FROM public.whatsapp_delivery_attempts")=='SENDING'
        assert await w.db.fetchval("SELECT state FROM public.whatsapp_reply_outbox WHERE provider='GUPSHUP'")=='SENDING'
        await w.db.execute("INSERT INTO public.whatsapp_delivery_events(provider,provider_account,event_sha256,external_id,whatsapp_id,recipient_e164,status,occurred_at) VALUES('GUPSHUP',$1,$2,'external-race','wa-race',$3,'READ',now())",s.gupshup_app_id,'f'*64,TESTER)
        calls.append(kwargs);return httpx.Response(202,json={'status':'submitted','messageId':'external-race'})
    q.http=SimpleNamespace(post=send)
    business=AsyncMock(return_value=[OutboundPart(body='Your secure quote link')])
    with patch('backend.gupshup_ingress.process_inbound',business):
        assert await q.drain();await q.enqueue_event(form,external,stamp)
        assert await q.drain()  # Receipt reconciliation resumes reply completion, not the business action.
        assert not await q.drain()
    assert business.await_count==1 and len(calls)==1
    assert await w.db.fetchval("SELECT delivery_status FROM public.whatsapp_reply_outbox WHERE provider='GUPSHUP'")=='read'
    # Later sent/failed events cannot downgrade a read receipt or trigger duplicate media fallback.
    for n,status in enumerate(['SENT','FAILED']):
        await w.db.execute("INSERT INTO public.whatsapp_delivery_events(provider,provider_account,event_sha256,external_id,recipient_e164,status,occurred_at) VALUES('GUPSHUP',$1,$2,'external-race',$3,$4,now())",s.gupshup_app_id,str(n)*64,TESTER,status)
    await reconcile_events(q)
    assert await w.db.fetchval('SELECT delivery_status FROM public.whatsapp_delivery_attempts')=='READ'
    assert await w.db.fetchval('SELECT cost_state FROM public.whatsapp_delivery_attempts')=='UNKNOWN'
    assert await w.db.fetchval('SELECT monetary_cost FROM public.whatsapp_delivery_attempts') is None

@pytest.mark.asyncio
async def test_all_proactive_workers_select_gupshup_and_match_receipts(world):
    w=world;x,s,q,_=await prepare(w)
    await w.db.execute('DELETE FROM public.support_message_outbox')
    member=await w.db.fetchval('SELECT id FROM public.users WHERE tenant_id=$1',w.tenants[0])
    await w.db.execute("INSERT INTO public.whatsapp_bindings(id,tenant_id,user_id,sender_e164,receiver_e164,is_active,verified_at,notification_opt_in) VALUES($1,$2,$3,$4,$5,true,now(),true)",uuid4(),w.tenants[0],member,TESTER,SOURCE)
    ticket=uuid4()
    await w.db.execute("UPDATE public.shipments SET status='EXCEPTION' WHERE id=$1",w.shipments[0])
    await w.db.execute("INSERT INTO public.support_tickets(id,tenant_id,shipment_id,status) VALUES($1,$2,$3,'OPEN')",ticket,w.tenants[0],w.shipments[0])
    await w.db.execute("INSERT INTO public.support_message_outbox(tenant_id,ticket_id,status,recipient_e164,body) VALUES($1,$2,'STAGED',$3,'Exception notice')",w.tenants[0],ticket,TESTER)
    metadata={'automation_order':{'origin':{'phone':TESTER},'sender_notifications':{'email':False,'whatsapp':True,'whatsapp_permission_confirmed':True}}}
    await w.db.execute('UPDATE public.shipments SET logistics_metadata=$2::jsonb WHERE id=$1',w.shipments[0],json.dumps(metadata))
    await w.db.execute("INSERT INTO public.shipment_sender_notifications(tenant_id,shipment_id,category,channel,environment) VALUES($1,$2,'EXCEPTION','WHATSAPP','TEST')",w.tenants[0],w.shipments[0])
    # A legitimate prepared return session, with an existing signed checkout URL.
    await w.db.execute("UPDATE public.shipments SET logistics_metadata=$2::jsonb WHERE id=$1",w.shipments[1],json.dumps({'automation_order':{'destination':{'phone':TESTER}}}))
    request_id=uuid4()
    await w.db.execute("""INSERT INTO public.return_review_sessions(tenant_id,id,original_shipment_id,requested_by,input_sha256,charge_bearer,state,delivery,response)
       VALUES($1,$2,$3,$4,$5,'CUSTOMER_PAY','PAYMENT_REQUIRED',$6::jsonb,$7::jsonb)""",w.tenants[0],request_id,w.shipments[0],w.actors[0],'a'*64,
       json.dumps({'whatsapp':True,'customer_permission_confirmed':True}),json.dumps({'checkout_url':'https://checkout.stripe.com/c/pay/synthetic'}))
    # Customer lookup is scoped to the original shipment; preserve sender metadata too.
    metadata['automation_order']['destination']={'phone':TESTER}
    await w.db.execute('UPDATE public.shipments SET logistics_metadata=$2::jsonb WHERE id=$1',w.shipments[0],json.dumps(metadata))
    await w.db.execute("INSERT INTO public.return_customer_deliveries(tenant_id,review_id,kind,channel) VALUES($1,$2,'PAYMENT','WHATSAPP')",w.tenants[0],request_id)
    calls=[]
    async def post(url,**kwargs):
        assert url=='https://api.gupshup.io/wa/api/v1/template/msg'
        calls.append(kwargs);return httpx.Response(202,json={'status':'submitted','messageId':'out-'+str(len(calls))})
    client=SimpleNamespace(post=post)
    life=SimpleNamespace(pool=w.db,automation=SimpleNamespace(settings=s),client=client,
        return_delivery_settings=ReturnDeliverySettings(_env_file=None,return_whatsapp_enabled=True))
    support=SupportDelivery(w.db,client,s,DeliverySettings(_env_file=None,whatsapp_provider='GUPSHUP',support_whatsapp_enabled=True))
    assert await support.drain()==1
    shipment_worker=ShipmentNotificationWorker(life,ShipmentNotificationSettings(_env_file=None,shipment_whatsapp_notifications_enabled=True))
    for _ in range(5):
        if not await shipment_worker.drain():break
    assert await ReturnDeliveryWorker(life).drain()
    assert len(calls)==3,await w.db.fetch('SELECT state,error_code FROM public.return_customer_deliveries')
    assert  {json.loads(c['data']['template'])['id'] for c in calls}=={'approved-SUPPORT','approved-SHIPMENT','approved-RETURN'}
    attempts=await w.db.fetch('SELECT * FROM public.whatsapp_delivery_attempts ORDER BY kind')
    assert len(attempts)==3 and all(a['tenant_id']==w.tenants[0] and a['state']=='ACCEPTED' for a in attempts)
    for n,a in enumerate(attempts):
        await w.db.execute("INSERT INTO public.whatsapp_delivery_events(provider,provider_account,event_sha256,external_id,recipient_e164,status,occurred_at) VALUES('GUPSHUP',$1,$2,$3,$4,'DELIVERED',now())",s.gupshup_app_id,str(n)*64,a['external_id'],TESTER)
    await reconcile_events(q)
    assert await w.db.fetchval('SELECT status FROM public.support_message_outbox')=='DELIVERED'
    assert await w.db.fetchval("SELECT delivery_status FROM public.shipment_sender_notifications WHERE channel='WHATSAPP'")=='DELIVERED'
    assert await w.db.fetchval('SELECT delivery_status FROM public.return_customer_deliveries')=='DELIVERED'


@pytest.mark.asyncio
async def test_timeout_fence_cannot_resend_and_media_fallback_is_deduplicated(world):
    w=world;_,s,q,_=await prepare(w)
    post=AsyncMock(side_effect=httpx.ReadTimeout('synthetic'))
    payload={'To':'whatsapp:'+TESTER,'Body':'notice'}
    arguments=dict(logical_key='support:uncertain',kind='SUPPORT',target_id=uuid4(),tenant_id=w.tenants[0],parameters={'body':'notice'})
    with pytest.raises(httpx.HTTPError):await send_selected(s,q.pool,SimpleNamespace(post=post),payload,**arguments)
    with pytest.raises(HTTPException):await send_selected(s,q.pool,SimpleNamespace(post=post),payload,**arguments)
    assert post.await_count==1
    assert await w.db.fetchval("SELECT state FROM public.whatsapp_delivery_attempts")=='REVIEW_REQUIRED'
    _,form,external,stamp=parse_event(event(),s);await q.enqueue_event(form,external,stamp)
    q.http=SimpleNamespace(post=AsyncMock(side_effect=[httpx.Response(400,json={'status':'error'}),httpx.Response(202,json={'status':'submitted','messageId':'fallback-id'})]))
    media=OutboundPart(body='Return document',media_url='https://app.example.test/document.pdf',fallback_view_url='https://app.example.test/secure-document')
    business=AsyncMock(return_value=[media])
    with patch('backend.gupshup_ingress.process_inbound',business):
        assert await q.drain();assert await q.drain();assert not await q.drain()
    assert business.await_count==1 and q.http.post.await_count==2
    assert await w.db.fetchval('SELECT count(*) FROM public.whatsapp_reply_outbox WHERE fallback_for IS NOT NULL')==1
    assert 'secure-document' in json.loads(q.http.post.call_args.kwargs['data']['message'])['text']
