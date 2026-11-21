"""Actual migration and service SQL on disposable PGlite, never hosted DB."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4,UUID
from unittest.mock import AsyncMock,patch
import hashlib
import json
import asyncpg
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.datastructures import FormData
from backend.whatsapp_consumer import ConsumerCX
from backend.agents.conversation_context import ConsumerDraft
from backend.tracking_workspace import ShareRequest,CustomerRequest
from backend.support_delivery import SupportDelivery,DeliverySettings
from backend.consumer_returns import authority
from backend.return_delivery import ReturnDeliverySettings
from test_tracking_workspace_postgres import world,ROOT,UUID_FIELDS
from test_gupshup_postgres import prepare
from test_gupshup_provider import TESTER,SOURCE


async def setup(w):
    x,s,q,_=await prepare(w)
    UUID_FIELDS.update({'share_link_id','authorized_by','tracking_customer_request_id'})
    await w.db.command('''ALTER TABLE public.support_tickets ADD COLUMN automation_failure_id uuid,
       ADD COLUMN insurance_claim_id uuid,ADD COLUMN ai_summary text,ADD COLUMN ai_method text,ADD COLUMN prompt_version text;
      ALTER TABLE public.support_tickets ADD CONSTRAINT support_ticket_source CHECK(true);
      ALTER TABLE public.support_message_outbox ADD COLUMN message_kind text DEFAULT 'CARRIER_EXCEPTION'
        CHECK(message_kind IN ('CARRIER_EXCEPTION','INSURANCE_SETTLEMENT'));
      ALTER TABLE public.support_message_outbox ADD CONSTRAINT support_message_recipient UNIQUE(tenant_id,ticket_id,recipient_e164);
    ''',mode='exec')
    await w.db.command((ROOT/'migrations/053_whatsapp_consumer_cx.sql').read_text(),mode='exec')
    q.application.state.whatsapp_queue=q
    q.application.state.tracking_workspace=w.engine
    q.application.state.partner_lifecycle=x.lifecycle
    q.application.state.settings=s
    link=await w.engine.share(w.scope,w.shipments[0],ShareRequest())
    token=link['url'].split('#')[1]
    cx=ConsumerCX(Request({'type':'http','app':q.application,'headers':[]}))
    return x,s,q,cx,link,token


def form(text,sid=None,sender=TESTER):
    return FormData({'From':'whatsapp:'+sender,'To':'whatsapp:'+SOURCE,'AccountSid':'offline-app',
        'MessageSid':sid or 'gs:'+uuid4().hex,'Body':text,'NumMedia':'0'})


@pytest.mark.asyncio
async def test_real_migration_encryption_isolation_expiry_and_revocation(world):
    w=world;_,s,q,cx,link,token=await setup(w)
    first=form('Track link '+token)
    parts=await cx.handle(first)
    assert 'ORDER-0' in parts[0].body and 'ORDER-1' not in parts[0].body
    row=await w.db.fetchrow('SELECT * FROM public.whatsapp_consumer_sessions')
    assert token.encode() not in row['payload_ciphertext']
    assert row['token_sha256']==hashlib.sha256(token.encode()).hexdigest()
    assert await cx.load('+447700900999',SOURCE) is None
    assert await cx.load(TESTER,'+447700900999') is None
    assert (await cx.handle(first))[0].body==parts[0].body
    await w.db.execute("UPDATE public.whatsapp_consumer_sessions SET expires_at=now()-interval '1 second'")
    assert await cx.load(TESTER,SOURCE) is None
    with pytest.raises(HTTPException):await cx.handle(first)
    await cx.handle(form('Track link '+token))
    await w.db.execute('UPDATE public.tracking_share_links SET revoked_at=now() WHERE id=$1',UUID(link['id']))
    with pytest.raises(HTTPException):await cx.load(TESTER,SOURCE)
    await w.db.command('SET ROLE authenticated',mode='exec')
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):await w.db.fetch('SELECT * FROM public.whatsapp_consumer_sessions')
    finally:await w.db.command('RESET ROLE',mode='exec')


@pytest.mark.asyncio
async def test_unbound_greeting_replays_without_creating_parcel_authority(world):
    w=world;_,s,q,cx,_,_=await setup(w)
    greeting=form('hello')
    first=await cx.handle(greeting)
    assert 'welcome to EasyInvio' in first[0].body
    assert first==await cx.handle(greeting)
    assert await w.db.fetchval('SELECT count(*) FROM public.whatsapp_consumer_sessions')==0
    assert await w.db.fetchval('SELECT count(*) FROM public.support_tickets WHERE cx_request_id IS NOT NULL')==0


@pytest.mark.asyncio
async def test_complaint_transaction_stages_admin_alert_and_duplicate_cannot_repeat(world):
    w=world;_,s,q,cx,_,token=await setup(w)
    await w.db.execute('DELETE FROM public.support_message_outbox')
    member=await w.db.fetchval('SELECT id FROM public.users WHERE tenant_id=$1',w.tenants[0])
    await w.db.execute('''INSERT INTO public.whatsapp_bindings(id,tenant_id,user_id,sender_e164,receiver_e164,verified_at,notification_opt_in)
      VALUES($1,$2,$3,$4,$5,now(),true)''',uuid4(),w.tenants[0],member,TESTER,SOURCE)
    await cx.handle(form('Track link '+token))
    complaint=form('My parcel arrived damaged')
    one=await cx.handle(complaint);two=await cx.handle(complaint)
    assert one==two and 'support case' in one[0].body
    assert await w.db.fetchval('SELECT count(*) FROM public.support_tickets WHERE cx_kind=\'COMPLAINT\'')==1
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_customer_requests')==1
    assert await w.db.fetchval("SELECT count(*) FROM public.support_message_outbox WHERE message_kind='CUSTOMER_CX'")==1
    delivery=SupportDelivery(q.pool,q.http,s,DeliverySettings(_env_file=None,support_whatsapp_enabled=True,
        support_whatsapp_status_url='https://app.example.test/api/v1/support/whatsapp/status'))
    # Shipment is DELIVERED: complaint alerts must not require EXCEPTION status.
    q.http.post.return_value=__import__('httpx').Response(202,json={'status':'submitted','messageId':'cx-alert'})
    assert await delivery.drain()==1
    assert q.http.post.await_count==1
    assert await w.db.fetchval("SELECT status FROM public.support_message_outbox WHERE message_kind='CUSTOMER_CX'")=='ACCEPTED'


@pytest.mark.asyncio
async def test_selected_foreign_parcel_and_idempotency_scope_are_rejected(world):
    w=world;_,_,_,cx,_,token=await setup(w)
    await cx.handle(form('Track link '+token))
    d=await cx.load(TESTER,SOURCE)
    with pytest.raises(HTTPException):await cx.scope(d.model_copy(update={'tenant_id':w.tenants[1]}))
    with pytest.raises(HTTPException):await cx.scope(d.model_copy(update={'shipment_id':w.shipments[1]}))
    with pytest.raises(HTTPException):
        await w.engine.customer_request(CustomerRequest(token=token,request_id=uuid4(),note='My parcel arrived damaged'),shipment_id=w.shipments[1])
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_customer_requests')==0


@pytest.mark.asyncio
async def test_auto_return_requires_policy_live_actor_recipient_and_window(world):
    w=world;_,_,_,cx,_,token=await setup(w)
    await cx.handle(form('Track link '+token));d=await cx.load(TESTER,SOURCE)
    with pytest.raises(HTTPException):await authority(cx,d)
    await w.db.execute('''INSERT INTO public.whatsapp_consumer_return_policies
      (tenant_id,enabled,authorized_by,window_days,charge_bearer,maximum_price_gbp) VALUES($1,true,$2,30,'RETAILER_PAY',10)''',w.tenants[0],w.actors[0])
    await w.db.execute('''INSERT INTO public.tracking_events(tenant_id,shipment_id,integration_key_id,event_id,body_sha256,status,occurred_at,response)
      VALUES($1,$2,'synthetic','delivered',$3,'DELIVERED',now()-interval '2 days','{}')''',w.tenants[0],w.shipments[0],'a'*64)
    # A shared tracking capability alone cannot authorize merchant spending.
    with pytest.raises(HTTPException):await authority(cx,d)
    await w.db.execute("UPDATE public.shipments SET logistics_metadata=jsonb_set(logistics_metadata,'{automation_order,destination,phone}',to_jsonb($2::text)) WHERE id=$1",w.shipments[0],TESTER)
    policy,_=await authority(cx,d)
    assert policy['charge_bearer']=='RETAILER_PAY'
    await w.db.execute('UPDATE public.whatsapp_consumer_return_policies SET window_days=1 WHERE tenant_id=$1',w.tenants[0])
    with pytest.raises(HTTPException):await authority(cx,d)
    await w.db.execute('UPDATE public.whatsapp_consumer_return_policies SET window_days=30 WHERE tenant_id=$1',w.tenants[0])
    await w.db.execute('UPDATE public.users SET is_active=false WHERE auth_user_id=$1',w.actors[0])
    with pytest.raises(HTTPException):await authority(cx,d)


@pytest.mark.asyncio
@pytest.mark.parametrize('payer',['RETAILER_PAY','CUSTOMER_PAY'])
async def test_confirmed_consumer_return_reuses_review_and_stages_label_notice(world,payer):
    w=world;x,s,q,cx,_,token=await setup(w)
    x.lifecycle.automation.settings=s
    x.lifecycle.return_delivery_settings=ReturnDeliverySettings(_env_file=None,return_whatsapp_enabled=True)
    await w.db.execute('''INSERT INTO public.whatsapp_consumer_return_policies
      (tenant_id,enabled,authorized_by,window_days,charge_bearer,maximum_price_gbp) VALUES($1,true,$2,30,$3,10)''',w.tenants[0],w.actors[0],payer)
    await w.db.execute("UPDATE public.shipments SET logistics_metadata=jsonb_set(logistics_metadata,'{automation_order,destination,phone}',to_jsonb($2::text)) WHERE id=$1",w.shipments[0],TESTER)
    await w.db.execute('''INSERT INTO public.tracking_events(tenant_id,shipment_id,integration_key_id,event_id,body_sha256,status,occurred_at,response)
      VALUES($1,$2,'synthetic','delivered',$3,'DELIVERED',now()-interval '2 days','{}')''',w.tenants[0],w.shipments[0],'a'*64)
    await cx.handle(form('Track link '+token))
    proposed=await cx.handle(form('I want to return this parcel'))
    assert 'Confirm return' in proposed[0].body
    x.lifecycle.confirm.assert_not_awaited()
    confirmation=form('Confirm return')
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote), \
         patch('backend.card_checkout.create_cart',AsyncMock(return_value={'url':'https://checkout.stripe.com/c/pay/synthetic','cart_id':str(uuid4())})):
        result=await cx.handle(confirmation)
        replay=await cx.handle(confirmation)
    assert result==replay
    if payer=='CUSTOMER_PAY':
        assert 'checkout.stripe.com' in result[0].body and not any(p.media_url for p in result)
        x.lifecycle.confirm.assert_not_awaited()
        assert await w.db.fetchval("SELECT count(*) FROM public.return_customer_deliveries WHERE kind='LABEL'")==0
        request_id=await w.db.fetchval('SELECT id FROM public.return_review_sessions')
        # Simulate verified card-worker settlement and carrier confirmation. The
        # delivery worker uses this same status reconciliation, never a new buy.
        await w.db.execute("INSERT INTO public.wallet_topups(tenant_id,id,status) VALUES($1,$2,'CREDITED')",w.tenants[0],request_id)
        await x.lifecycle.confirm(x.context,None)
        await x.service.status(x.context,request_id)
    else:
        assert 'printed label' in result[0].body
    x.lifecycle.confirm.assert_awaited_once()
    assert await w.db.fetchval("SELECT count(*) FROM public.return_customer_deliveries WHERE kind='LABEL'")==1


@pytest.mark.asyncio
async def test_review_claim_rechecks_policy_version_inside_transaction(world):
    w=world;x,_,_,_,_,_=await setup(w)
    from backend.return_review import SelectReturn
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote):
        await x.service.prepare(x.context,x.body)
    with pytest.raises(HTTPException):
        await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]),expected_policy_version=1)
    x.lifecycle.confirm.assert_not_awaited()
    assert await w.db.fetchval('SELECT state FROM public.return_review_sessions')=='QUOTED'


@pytest.mark.asyncio
async def test_product_refund_reports_return_scan_without_claiming_payment(world):
    w=world;_,_,_,cx,_,token=await setup(w)
    returned=uuid4()
    await w.db.execute('''INSERT INTO public.shipments(id,tenant_id,carrier_account_id,customer_reference,
      status,return_of_shipment_id,tracking_lifecycle_type) VALUES($1,$2,$3,'RETURN-TEST','IN_TRANSIT',$4,'RETURN_SHIPMENT')''',
      returned,w.tenants[0],w.accounts[0],w.shipments[0])
    await cx.handle(form('Track link '+token))
    transit=await cx.handle(form('Where is my product refund?'))
    assert 'in transit' in transit[0].body and 'must be confirmed by the retailer' in transit[0].body
    await w.db.execute("UPDATE public.shipments SET status='DELIVERED' WHERE id=$1",returned)
    await w.db.execute('''INSERT INTO public.tracking_events(tenant_id,shipment_id,integration_key_id,event_id,body_sha256,status,occurred_at,response)
      VALUES($1,$2,'synthetic','return-delivered',$3,'DELIVERED',now(),'{}')''',w.tenants[0],returned,'a'*64)
    delivered=await cx.handle(form('Where is my product refund?'))
    assert 'Carrier-reported return delivery:' in delivered[0].body
    assert 'does not confirm merchant inspection or a product refund' in delivered[0].body
    assert await w.db.fetchval("SELECT count(*) FROM public.support_tickets WHERE cx_kind='REFUND_INQUIRY'")==2
