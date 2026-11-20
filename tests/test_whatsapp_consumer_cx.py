"""Offline tests only: synthetic data, fake provider endpoints, disposable SQL."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4, UUID
import hashlib
import json
import pytest
from fastapi import HTTPException
from backend.agents.conversation_context import ConsumerDraft
from backend.whatsapp_consumer import ConsumerCX, tracking_token
from backend.cx_intents import cx_intent
from backend.consumer_returns import execute_return
from backend.whatsapp_queue import reply_parts
from backend.whatsapp_queue import return_image
from backend.agents.conversational_gateway import message_xml
from test_conversational_gateway import fixture, message


def draft(**changes):
    values=dict(token='a'*43,token_sha256=hashlib.sha256(('a'*43).encode()).hexdigest(),
        sender_e164='+447700900123',receiver_e164='+447700900321',tenant_id=uuid4(),shipment_id=uuid4())
    return ConsumerDraft(**(values|changes))


def test_draft_expires_and_cannot_replace_token_hash():
    assert draft().active()
    assert not draft(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)).active()
    assert not draft(token_sha256='b'*64).active()
    assert not draft(expires_at=datetime.now()).active()


def test_qr_attachment_refuses_other_tenants_hosts_and_path_traversal():
    d=draft();settings=SimpleNamespace(supabase_url='https://storage.example.test',logistics_media_bucket='private-media')
    prefix=f'https://storage.example.test/storage/v1/object/sign/private-media/{d.tenant_id}/{d.shipment_id}/'
    result={'return_request':{'shipment_id':str(d.shipment_id),'media_urls':[prefix+'qr.png?token=synthetic']}}
    assert return_image(result,settings,d.tenant_id)
    assert return_image(result,settings,uuid4()) is None
    for url in (prefix+'../other/qr.png?token=synthetic',prefix.replace('storage.example.test','evil.example')+'qr.png?token=synthetic'):
        result['return_request']['media_urls']=[url]
        assert return_image(result,settings,d.tenant_id) is None


def test_plain_capability_and_our_https_link_are_accepted_but_other_hosts_are_not():
    token='a'*43
    assert tracking_token('Track link '+token+' my parcel arrived damaged','https://app.example.test')==(token,'my parcel arrived damaged')
    assert tracking_token('https://app.example.test/track#'+token,'https://app.example.test')[0]==token
    assert tracking_token('https://evil.example/track#'+token,'https://app.example.test')[0] is None
    assert tracking_token('My parcel arrived damaged '+token,'https://app.example.test')==(token,'My parcel arrived damaged')


@pytest.mark.parametrize('text,action,category',[
    ('My parcel arrived damaged','COMPLAINT','DAMAGED'),
    ('Driver missed delivery','COMPLAINT','MISSING_DELAYED'),
    ('Please change my address','SERVICE_REQUEST','ADDRESS_CHANGE'),
    ('Where is my product refund?','REFUND_INQUIRY','BILLING_OTHER')])
def test_deterministic_intents(text,action,category):
    result=cx_intent(text)
    assert result.intent==action and result.issue_category==category


@pytest.mark.asyncio
async def test_scope_rejects_expiry_before_any_database_or_resolver_call():
    service=object.__new__(ConsumerCX)
    service.workspace=SimpleNamespace(resolve=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await service.scope(draft(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
    assert exc.value.status_code==410
    service.workspace.resolve.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('payer,status',[('RETAILER_PAY','BOOKED'),('CUSTOMER_PAY','PAYMENT_REQUIRED')])
async def test_return_reuses_review_and_attaches_qr_only_after_booking(payer,status):
    d=draft();actor=uuid4();offer=uuid4();child=uuid4();ticket=uuid4()
    policy=dict(authorized_by=actor,role='OWNER',version=1,charge_bearer=payer,maximum_price_gbp=10)
    facts={'destination':{'country_code':'GB'},'edits':{'cargo':dict(cargo_type='PARCEL',actual_weight_kg='1.5',length_cm='24',width_cm='16',height_cm='8'),
                    'items':[]}}
    review=SimpleNamespace(context=AsyncMock(return_value=facts),prepare=AsyncMock(return_value={
        'rates':[dict(offer_id=str(offer),carrier_code='EVRI',currency='GBP',client_price_ex_tax='4.25')]}),
        select=AsyncMock(return_value=dict(status=status,shipment_id=str(child),qr_path='/document',checkout_url='https://checkout.stripe.com/c/pay/synthetic')))
    settings=SimpleNamespace(booking_page_url='https://app.example.test',supabase_url='https://storage.example.test',logistics_media_bucket='private-logistics')
    service=SimpleNamespace(pool=object(),settings=settings,state=SimpleNamespace(partner_lifecycle=object()))
    image=f'https://storage.example.test/storage/v1/object/sign/private-logistics/{d.tenant_id}/{child}/verified.png?token=synthetic'
    with patch('backend.consumer_returns.authority',AsyncMock(return_value=(policy,{}))), \
         patch('backend.return_review.ReturnReviewService',return_value=review), \
         patch('backend.return_documents.public_return_links',side_effect=lambda s,a,r:r), \
         patch('backend.logistics_media.publish_return_media',AsyncMock(return_value=dict(status='BOOKED',shipment_id=str(child),media_urls=[image]))), \
         patch('backend.whatsapp_queue.return_media',return_value='https://app.example.test/return?token=synthetic'):
        parts=await execute_return(service,d,uuid4(),ticket,reply_parts,message_xml)
    review.select.assert_awaited_once()
    body=' '.join(p.body for p in parts)
    if status=='BOOKED':
        assert parts[-1].media_url==image and parts[-1].fallback_view_url
    else:
        assert all(p.media_url is None for p in parts)
        assert 'checkout.stripe.com' in body and 'until payment' in body


@pytest.mark.asyncio
async def test_policy_cap_stops_selection():
    d=draft()
    review=SimpleNamespace(context=AsyncMock(return_value={'destination':{'country_code':'GB'},'edits':{'cargo':dict(cargo_type='PARCEL',actual_weight_kg='1',length_cm='10',width_cm='10',height_cm='10'),'items':[]}}),
        prepare=AsyncMock(return_value={'rates':[dict(offer_id=str(uuid4()),carrier_code='EVRI',currency='GBP',client_price_ex_tax='12')]}),select=AsyncMock())
    policy=dict(authorized_by=uuid4(),role='OWNER',version=1,charge_bearer='RETAILER_PAY',maximum_price_gbp=10)
    service=SimpleNamespace(pool=object(),settings=SimpleNamespace(),state=SimpleNamespace(partner_lifecycle=object()))
    with patch('backend.consumer_returns.authority',AsyncMock(return_value=(policy,{}))),patch('backend.return_review.ReturnReviewService',return_value=review):
        parts=await execute_return(service,d,uuid4(),uuid4(),reply_parts,message_xml)
    review.select.assert_not_awaited()
    assert 'cap' in parts[0].body


def install_support_storage(storage, status='BOOKED', manifest=None):
    fetchrow,fetchval,execute=storage.fetchrow,storage.fetchval,storage.execute
    async def row(sql,*args):
        if 'SELECT status,manifest_id' in sql:
            return {'status':status,'manifest_id':manifest}
        return await fetchrow(sql,*args)
    async def val(sql,*args):
        if 'INSERT INTO public.support_tickets' in sql:
            storage.writes.append(('CASE',args));return args[0]
        return await fetchval(sql,*args)
    async def write(sql,*args):
        if 'INSERT INTO public.support_message_outbox' in sql:
            storage.writes.append(('ALERT',args));return 'INSERT 1'
        return await execute(sql,*args)
    storage.fetchrow,storage.fetchval,storage.execute=row,val,write


@pytest.mark.asyncio
async def test_merchant_complaint_collects_reference_and_summary_without_insurance(fixture):
    context,storage,state,gateway,_=fixture
    state.settings.whatsapp_consumer_cx_enabled=True
    install_support_storage(storage)
    first=await gateway.process(context,message('Complaint'))
    assert first['status']=='NEEDS_INPUT'
    second=await gateway.process(context,message('TEST123'))
    assert second['status']=='NEEDS_INPUT'
    completed=await gateway.process(context,message('The parcel packaging arrived crushed'))
    assert completed['action_taken']=='COMPLAINT' and completed['ticket_id']
    assert len([x for x in storage.writes if x[0]=='CASE'])==1
    state.partner_lifecycle.confirm.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,manifest,allowed',[
    ('BOOKED',None,True),('MANIFESTED',None,False),('DELIVERED',None,False),('BOOKED',uuid4(),False)])
async def test_label_refund_is_review_only_and_refuses_dispatch_or_manifest(fixture,status,manifest,allowed):
    context,storage,state,gateway,_=fixture
    state.settings.whatsapp_consumer_cx_enabled=True
    install_support_storage(storage,status,manifest)
    result=await gateway.process(context,message('Please void shipment TEST123 and review my label refund'))
    assert bool(result.get('ticket_id'))==allowed
    if allowed:
        assert 'only after the carrier confirms' in result['conversational_reply']
    state.partner_lifecycle.confirm.assert_not_awaited()
    state.finance.create_checkout.assert_not_awaited()
