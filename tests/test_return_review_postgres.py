"""Real SQL/receipt tests on explicitly disposable PostgreSQL; providers mocked."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4, UUID

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from starlette.responses import Response

from backend.return_review import ReturnReviewService, ReviewRequest, SelectReturn, assert_review_purchase
from backend.return_delivery import (ReturnDeliverySettings, ReturnDeliveryWorker, customer_document,
    signed_document, stage_notices)
from test_tracking_workspace_postgres import world, ROOT, UUID_FIELDS


async def setup(w, payer='RETAILER_PAY', notifications=False):
    UUID_FIELDS.update({'original_shipment_id','return_shipment_id','selected_offer_id','review_id'})
    await w.db.command('''ALTER TABLE public.shipments ADD COLUMN currency text DEFAULT 'GBP',
        ADD COLUMN quote_expires_at timestamptz DEFAULT now()+interval '5 minutes', ADD COLUMN pricing_snapshot jsonb DEFAULT '{}';
        CREATE TABLE public.partner_shipping_offers(tenant_id uuid,offer_id uuid,shipment_id uuid,expires_at timestamptz);
        CREATE TABLE public.wallet_topups(tenant_id uuid,id uuid,status text);
        CREATE TABLE public.payment_carts(tenant_id uuid,id uuid,status text,results jsonb DEFAULT '{}');
        CREATE TABLE public.tenant_catalog_addresses(id uuid,tenant_id uuid,address_role text,is_default boolean,
            archived_at timestamptz,address jsonb,version integer);
    ''', mode='exec')
    await w.db.command((ROOT/'migrations/042_headless_returns.sql').read_text(), mode='exec')
    await w.db.command((ROOT/'migrations/046_return_review_and_delivery.sql').read_text(), mode='exec')
    address = dict(name='Synthetic customer',line1='10 Test Road',city='London',postal_code='SW1A 1AA',
        country_code='GB',phone='+447700900000',email='customer@example.test')
    cargo = dict(cargo_type='PARCEL',actual_weight_kg='1.500',length_cm='24',width_cm='16',height_cm='8',stackable=True)
    goods = [dict(description='Cotton shirt',quantity=1,unit_value='12.00',unit_weight_kg='0.500',origin_country='GB',hs_code='610910')]
    order = dict(idempotency_key=str(uuid4()),order_reference='SYNTHETIC-ORDER',origin=address|{'name':'Merchant'},destination=address,cargo=cargo,items=goods)
    await w.db.execute("UPDATE public.shipments SET status='DELIVERED',logistics_metadata=$2::jsonb WHERE id=$1", w.shipments[0], json.dumps({'automation_order':order}))
    await w.db.execute("INSERT INTO public.tenant_catalog_addresses VALUES($1,$2,'RETURN',true,NULL,$3::jsonb,1)",uuid4(),w.tenants[0],json.dumps(address|{'name':'Return warehouse'}))
    config = ReturnDeliverySettings(_env_file=None,email_delivery_provider='SENDGRID',return_email_enabled=notifications,
        return_sendgrid_api_key=SecretStr('SYNTHETIC-NOT-A-REAL-KEY'))
    settings = SimpleNamespace(booking_page_url='https://app.example.test',quote_link_secret=SecretStr('synthetic-secret-for-return-documents-12345'),twilio_enabled=False)
    lifecycle = SimpleNamespace(pool=w.db,automation=SimpleNamespace(settings=settings),return_delivery_settings=config,
        client=None,confirm=AsyncMock())
    context = SimpleNamespace(tenant_id=w.tenants[0],user_id=w.actors[0],role='OWNER')
    child, offers = uuid4(), [uuid4(),uuid4()]
    async def quote(service, identity, body, **kwargs):
        await w.db.execute("INSERT INTO public.shipments(id,tenant_id,carrier_account_id,customer_reference) VALUES($1,$2,$3,'RETURN-SYNTHETIC')",child,w.tenants[0],w.accounts[0])
        await w.db.execute("UPDATE public.shipments SET status='FAILED',booked_at=NULL,tracking_number=NULL WHERE id=$1",child)
        for offer in offers:
            await w.db.execute("INSERT INTO public.partner_shipping_offers VALUES($1,$2,$3,now()+interval '5 minutes')",w.tenants[0],offer,child)
        return {'status':'QUOTED','shipment_id':str(child),'all_rates':[
            {'offer_id':str(offers[0]),'carrier_code':'UPS','service_code':'STANDARD','client_price_ex_tax':'8.00','currency':'GBP'},
            {'offer_id':str(offers[1]),'carrier_code':'EVRI','service_code':'STANDARD','client_price_ex_tax':'4.25','currency':'GBP'}]}
    async def confirm(identity, selected):
        await asyncio.sleep(.01)
        async with w.db.acquire() as c:
            await c.execute("UPDATE public.shipments SET status='BOOKED',booked_at=now(),tracking_number='RETURN-1',logistics_metadata=$2::jsonb WHERE id=$1",child,
                json.dumps({'automation_label':{'label_url':'https://carrier.example.test/label.pdf'}}))
            await c.execute('UPDATE public.shipments SET pricing_snapshot=$2::jsonb WHERE id=$1',child,
                json.dumps({'selected_rate':{'offer_id':str(offers[1])}}))
        return {'status':'BOOKED','shipment_id':str(child)}
    lifecycle.confirm.side_effect = confirm
    body = ReviewRequest(request_id=uuid4(),shipment_id=w.shipments[0],charge_bearer=payer,
        edits={'cargo':cargo,'items':goods},delivery={'email':notifications,'customer_permission_confirmed':notifications})
    return SimpleNamespace(service=ReturnReviewService(lifecycle),lifecycle=lifecycle,context=context,body=body,
        quote=quote,child=child,offers=offers)


@pytest.mark.asyncio
async def test_prepare_is_non_purchasing_and_concurrent_selection_buys_once(world):
    x = await setup(world)
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote) as quote:
        result = await x.service.prepare(x.context,x.body)
        assert result['rates'][0]['carrier_code']=='EVRI'
        assert await world.db.fetchval("SELECT logistics_metadata->>'return_review_id' FROM public.shipments WHERE id=$1",x.child)==str(x.body.request_id)
        with pytest.raises(HTTPException):
            await assert_review_purchase(world.db,x.context.tenant_id,x.child,x.body.request_id,x.offers[1])
        assert not x.lifecycle.confirm.called
        repeated = await x.service.prepare(x.context,x.body)
        assert repeated['replayed'] and quote.call_count==1
    selected=SelectReturn(offer_id=x.offers[1])
    results=await asyncio.gather(x.service.select(x.context,x.body.request_id,selected),x.service.select(x.context,x.body.request_id,selected))
    assert x.lifecycle.confirm.await_count==1
    assert any(r['status']=='BOOKED' for r in results)
    assert await world.db.fetchval('SELECT count(*) FROM public.reverse_logistics_requests')==1
    assert (await x.service.status(x.context,x.body.request_id))['label_path'].endswith('/documents/label')
    changed=SelectReturn(offer_id=x.offers[0])
    with pytest.raises(HTTPException):await x.service.select(x.context,x.body.request_id,changed)


@pytest.mark.asyncio
async def test_expired_or_forged_offer_and_other_tenant_cannot_purchase(world):
    x=await setup(world)
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote):
        await x.service.prepare(x.context,x.body)
    with pytest.raises(HTTPException):await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=uuid4()))
    other=SimpleNamespace(tenant_id=world.tenants[1],user_id=world.actors[1],role='OWNER')
    with pytest.raises(HTTPException):await x.service.select(other,x.body.request_id,SelectReturn(offer_id=x.offers[1]))
    await world.db.execute("UPDATE public.return_review_sessions SET expires_at=now()-interval '1 second'")
    with pytest.raises(HTTPException):await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]))
    assert not x.lifecycle.confirm.called
    assert await world.db.fetchval('SELECT count(*) FROM public.reverse_logistics_requests')==0


@pytest.mark.asyncio
async def test_customer_payment_gates_documents_and_notifications_then_releases_once(world):
    x=await setup(world,'CUSTOMER_PAY',True)
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote):
        await x.service.prepare(x.context,x.body)
    with patch('backend.card_checkout.create_cart',AsyncMock(return_value={'url':'https://checkout.stripe.com/c/pay/synthetic','cart_id':str(x.body.request_id)})) as checkout:
        result=await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]))
    assert checkout.await_count==1 and result['status']=='PAYMENT_REQUIRED'
    assert not x.lifecycle.confirm.called and 'label_path' not in result
    with pytest.raises(HTTPException):
        await assert_review_purchase(world.db,x.context.tenant_id,x.child,x.body.request_id,x.offers[1])
    notices=await world.db.fetch('SELECT * FROM public.return_customer_deliveries')
    assert len(notices)==1 and notices[0]['kind']=='PAYMENT'
    token=signed_document(x.lifecycle,x.context.tenant_id,x.body.request_id).split('token=')[1]
    with pytest.raises(HTTPException) as error:await customer_document(x.lifecycle,token)
    assert error.value.status_code==409
    # A booked child alone is insufficient: the customer payment must be verified.
    await x.lifecycle.confirm(x.context,None)
    with pytest.raises(HTTPException):await customer_document(x.lifecycle,token)
    await world.db.execute("INSERT INTO public.wallet_topups VALUES($1,$2,'CREDITED')",x.context.tenant_id,x.body.request_id)
    await assert_review_purchase(world.db,x.context.tenant_id,x.child,x.body.request_id,x.offers[1])
    result=await x.service.status(x.context,x.body.request_id)
    assert result['status']=='BOOKED' and 'checkout_url' not in result
    await x.service.status(x.context,x.body.request_id)
    assert await world.db.fetchval("SELECT count(*) FROM public.return_customer_deliveries WHERE kind='LABEL'")==1
    with patch('backend.automation_three_partners.carrier_document',AsyncMock(return_value=Response(b'%PDF-synthetic',media_type='application/pdf'))):
        assert (await customer_document(x.lifecycle,token)).body.startswith(b'%PDF')
    await world.db.execute("UPDATE public.shipments SET status='CANCELLED' WHERE id=$1",x.child)
    with pytest.raises(HTTPException):await customer_document(x.lifecycle,token)
    assert 'label_path' not in await x.service.status(x.context,x.body.request_id)


@pytest.mark.asyncio
async def test_outbound_timeout_is_fenced_and_never_resent(world):
    x=await setup(world,notifications=True)
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote):
        await x.service.prepare(x.context,x.body)
    await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]))
    requests=[]
    def failing(request):
        requests.append(request)
        raise httpx.ReadTimeout('synthetic timeout')
    async with httpx.AsyncClient(transport=httpx.MockTransport(failing)) as client:
        x.lifecycle.client=client
        worker=ReturnDeliveryWorker(x.lifecycle)
        assert await worker.drain()
        assert not await worker.drain()
    assert len(requests)==1
    row=await world.db.fetchrow('SELECT state,error_code FROM public.return_customer_deliveries')
    assert row['state']=='REVIEW_REQUIRED'
    assert row['error_code']=='SEND_OUTCOME_UNCERTAIN'


@pytest.mark.asyncio
async def test_customer_payment_notices_send_safe_link_only_on_both_configured_channels(world):
    x=await setup(world,'CUSTOMER_PAY',True)
    config=x.lifecycle.return_delivery_settings
    config.return_whatsapp_enabled=True
    config.return_whatsapp_content_sid='HX'+'1'*32
    config.return_whatsapp_messaging_service_sid='MG'+'2'*32
    settings=x.lifecycle.automation.settings
    settings.twilio_enabled=True;settings.twilio_account_sid='AC'+'3'*32
    settings.twilio_auth_token=SecretStr('synthetic-test-token');settings.twilio_whatsapp_number='+447700900001'
    x.body.delivery.whatsapp=True
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote):
        await x.service.prepare(x.context,x.body)
    with patch('backend.card_checkout.create_cart',AsyncMock(return_value={'url':'https://checkout.stripe.com/c/pay/synthetic','cart_id':str(x.body.request_id)})):
        await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]))
    requests=[]
    def accept(request):
        requests.append(request)
        return httpx.Response(202,headers={'x-message-id':'synthetic-mail'}) if request.url.host=='api.sendgrid.com' else httpx.Response(201,json={'sid':'SM'+'4'*32})
    async with httpx.AsyncClient(transport=httpx.MockTransport(accept)) as client:
        x.lifecycle.client=client;worker=ReturnDeliveryWorker(x.lifecycle)
        assert await worker.drain() and await worker.drain()
        assert not await worker.drain()
    from urllib.parse import parse_qs
    email=json.loads(requests[0].content)
    twilio=parse_qs(requests[1].content.decode())
    variables=json.loads(twilio['ContentVariables'][0])
    assert email['personalizations'][0]['to'][0]['email']=='customer@example.test'
    assert variables['3']=='https://checkout.stripe.com/c/pay/synthetic'
    assert twilio['To']==['whatsapp:+447700900000']
    assert 'customer-document' not in json.dumps(email)+json.dumps(variables)
    assert await world.db.fetchval("SELECT count(*) FROM public.return_customer_deliveries WHERE state='ACCEPTED'")==2


@pytest.mark.asyncio
async def test_uncertain_purchase_is_not_replayed_and_late_native_confirmation_is_delivered(world):
    x=await setup(world,notifications=True)
    native_confirmation=x.lifecycle.confirm.side_effect
    x.lifecycle.confirm.side_effect=TimeoutError('synthetic uncertain purchase')
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote):
        await x.service.prepare(x.context,x.body)
    with pytest.raises(HTTPException) as error:
        await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]))
    assert error.value.status_code==503
    result=await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]))
    assert result['status']=='REVIEW_REQUIRED' and x.lifecycle.confirm.await_count==1
    # Existing native reconciliation supplies the late outcome. The notification
    # worker observes it and sends instructions without attempting another buy.
    await native_confirmation(x.context,None)
    requests=[]
    def accept(request):
        requests.append(request)
        return httpx.Response(202,headers={'x-message-id':'synthetic-mail'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(accept)) as client:
        x.lifecycle.client=client
        with patch('backend.return_delivery.asyncio.sleep',AsyncMock(side_effect=asyncio.CancelledError)):
            with pytest.raises(asyncio.CancelledError):await ReturnDeliveryWorker(x.lifecycle).worker()
    assert len(requests)==1 and x.lifecycle.confirm.await_count==1
    assert await world.db.fetchval("SELECT state FROM public.return_review_sessions WHERE id=$1",x.body.request_id)=='BOOKED'


@pytest.mark.asyncio
@pytest.mark.parametrize('state',['BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION','CANCELLED','FAILED'])
async def test_return_context_rejects_not_delivered_and_preserves_forward_record(world,state):
    x=await setup(world)
    await world.db.execute('UPDATE public.shipments SET status=$2 WHERE id=$1',world.shipments[0],state)
    with pytest.raises(HTTPException) as error:await x.service.context(x.context,world.shipments[0])
    assert error.value.status_code==409
    assert await world.db.fetchval('SELECT count(*) FROM public.return_review_sessions')==0


@pytest.mark.asyncio
async def test_return_tables_are_private_and_tenant_foreign_keys_reject_cross_workspace(world):
    x=await setup(world)
    assert await world.db.fetchval("SELECT bool_and(relrowsecurity) FROM pg_class WHERE oid IN ('public.return_review_sessions'::regclass,'public.return_customer_deliveries'::regclass)")
    await world.db.command('SET ROLE authenticated',mode='exec')
    try:
        with pytest.raises(Exception):await world.db.fetch('SELECT * FROM public.return_review_sessions')
    finally:await world.db.command('RESET ROLE',mode='exec')
    with pytest.raises(Exception):
        await world.db.execute('''INSERT INTO public.return_review_sessions
            (tenant_id,id,original_shipment_id,requested_by,input_sha256,charge_bearer,state)
            VALUES($1,$2,$3,$4,$5,'RETAILER_PAY','PREPARING')''',world.tenants[0],uuid4(),world.shipments[1],world.actors[0],'0'*64)

@pytest.mark.asyncio
@pytest.mark.parametrize('payer',['RETAILER_PAY','CUSTOMER_PAY'])
async def test_hostinger_return_notices_keep_payment_and_document_gates(world,monkeypatch,payer):
    from backend.email_delivery import EmailReceipt
    x=await setup(world,payer,True)
    cfg=x.lifecycle.return_delivery_settings;cfg.email_delivery_provider='HOSTINGER_SMTP'
    cfg.smtp_username='support@easyinvio.com';cfg.smtp_password=SecretStr('synthetic')
    with patch('backend.automation_three_partners.prepare_return_quote',side_effect=x.quote):
        await x.service.prepare(x.context,x.body)
    with patch('backend.card_checkout.create_cart',AsyncMock(return_value={'url':'https://checkout.stripe.com/c/pay/synthetic','cart_id':str(x.body.request_id)})):
        await x.service.select(x.context,x.body.request_id,SelectReturn(offer_id=x.offers[1]))
    calls=[]
    async def smtp(client,config,**message):
        assert await world.db.fetchval('SELECT state FROM public.return_customer_deliveries')=='SENDING'
        assert message['sender']=='support@easyinvio.com' and message['recipient']=='customer@example.test'
        if payer=='CUSTOMER_PAY':
            assert 'https://checkout.stripe.com/c/pay/synthetic' in message['text']
            assert 'customer-document' not in message['text']+message['html_body']
            assert not x.lifecycle.confirm.called
        else:
            assert 'customer-document' in message['text'] and 'Document links expire in 24 hours.' in message['text']
        calls.append(message)
        return EmailReceipt('ACCEPTED','synthetic-smtp-id')
    monkeypatch.setattr('backend.return_delivery.send_notification_email',smtp)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:pytest.fail('SMTP must not call SendGrid'))) as client:
        x.lifecycle.client=client;worker=ReturnDeliveryWorker(x.lifecycle)
        assert await worker.drain() and not await worker.drain()
    assert len(calls)==1
    assert await world.db.fetchval('SELECT state FROM public.return_customer_deliveries')=='ACCEPTED'
