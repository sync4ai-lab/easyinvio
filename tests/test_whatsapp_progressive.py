"""Offline progressive-disclosure tests: no providers, purchases or hosted DB."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
import jwt,pytest
from pydantic import SecretStr
from fastapi import HTTPException
from backend.agents.shipping_intents import classify
from backend.agents.logistics_advisor import guidance
from backend.whatsapp_progressive import ballpark,quote_link,verify_quote,GuestDraft,GuestShippingAssistant
from backend.whatsapp_progressive import requested_feature,feature_handoff
from backend.whatsapp_bot import format_reply
from backend.whatsapp_queue import reply_parts
from backend.agents.conversational_gateway import message_xml,ConversationMessage
from test_conversational_gateway import fixture


def settings():return NS(booking_page_url='https://app.example.test',quote_link_secret=SecretStr('synthetic-public-prefill-secret-32-characters'))


@pytest.mark.parametrize('text,intent,kind',[
 ('Quote to London','QUOTE',None),('Book 1','BOOK_SELECTION',None),('Select option 2','BOOK_SELECTION',None),
 ('Track my parcel','TRACK',None),('change delivery address','CHANGE_ADDRESS',None),
 ('return my parcel','RETURN_REQUEST',None),('my parcel is damaged','REFUND_OR_CLAIM',None),
 ('missed collection support','COMPLAINT_OR_SUPPORT',None),
 ('How do I connect Shopify?','KNOWLEDGE_QUERY','APP_FAQ'),
 ('How do I pack fragile glass?','KNOWLEDGE_QUERY','LOGISTICS_ADVICE')])
def test_taxonomy(text,intent,kind):
    result=classify(text);assert (result.intent,result.knowledge_kind)==(intent,kind)


def test_natural_send_request_has_no_login_wall_before_estimate():
    facts=classify('I want to send a parcel 2kg from Leeds GB to London GB').facts
    assert facts and facts.weight_kg=='2' and facts.origin_city=='Leeds'
    assert 'Sample option' in ballpark(settings(),facts)


@pytest.mark.parametrize('message',['Quote 0kg from GB to GB','Quote 1001kg from GB to GB','Quote 2kg from GB to GB 0x20x10 cm'])
def test_invalid_quote_facts_cannot_create_a_signed_estimate(message):
    with pytest.raises(ValueError):classify(message)


@pytest.mark.asyncio
@pytest.mark.parametrize('command,feature,upgrade',[
 ('Build an HS code','customs_hs_builder','Command'),
 ('Set custom margin rules','custom_margin_rules','Command'),
 ('Use my own carrier contract','byoc_carrier_accounts','Command'),
 ('Use carrier advisor','ai_carrier_advisor','Velocity')])
async def test_contextual_feature_handoff_respects_existing_policy(command,feature,upgrade):
    request=NS(app=NS(state=NS(settings=settings(),whatsapp=NS(pool=object()))))
    context=NS(tenant_id='synthetic')
    with patch('backend.entitlements.guard_feature',AsyncMock(side_effect=HTTPException(402,'plan'))):
        assert upgrade in await feature_handoff(request,context,command)
    with patch('backend.entitlements.guard_feature',AsyncMock()) as guard:
        assert '/workspace' in await feature_handoff(request,context,command)
        assert guard.call_args.args[-1]==feature


def test_missing_slots_batched_and_instant_sample_link_preserves_facts():
    text=ballpark(settings(),classify('Quote to London').facts)
    assert all(x in text for x in ['weight','pickup','country'])
    facts=classify('Quote 2.5kg from Leeds GB to London GB, 30x20x10 cm').facts
    result=ballpark(settings(),facts)
    assert result.count('Sample option')==2 and 'excl. VAT' in result and 'not live' in result.lower()
    from urllib.parse import urlsplit,parse_qs
    token=parse_qs(urlsplit(quote_link(settings(),facts)).query)['quick_quote'][0]
    decoded=verify_quote(settings(),token)
    assert decoded['weight_kg']=='2.5' and decoded['origin_city']=='Leeds' and decoded['dimensions_cm']==['30','20','10']
    assert 'tenant_id' not in decoded
    with pytest.raises(HTTPException):verify_quote(settings(),token[:-8]+'tampered')


def test_expired_and_wrong_purpose_quick_quote_links_rejected():
    for data in [dict(exp=datetime.now(timezone.utc)-timedelta(seconds=1),purpose='PREFILL_ONLY'),dict(exp=datetime.now(timezone.utc)+timedelta(minutes=5),purpose='PURCHASE')]:
        token=jwt.encode({'aud':'easyinvio-quick-quote','iat':datetime.now(timezone.utc)-timedelta(minutes=2),'facts':{},**data},settings().quote_link_secret.get_secret_value(),algorithm='HS256')
        with pytest.raises(HTTPException):verify_quote(settings(),token)


@pytest.mark.parametrize('text',['how to pack fragile glass','can I send batteries','how does volumetric weight work','customs advice'])
def test_advice_is_three_short_bullets_with_no_price_or_guarantee(text):
    reply=guidance(text)
    assert len(reply)<700 and reply.count('•')==3
    assert '£' not in reply and 'guaranteed delivery' not in reply.lower()


def test_one_message_budget_keeps_whole_action_link():
    url='https://app.example.test/login?quick_quote='+('a'*600)
    parts=reply_parts(message_xml('Useful shipping information. '*250+'\n'+url))
    assert len(parts)==1 and len(parts[0].body)<1450 and url in parts[0].body
    assert len(format_reply('x'*2000))<1450


@pytest.mark.asyncio
async def test_public_status_projection_never_includes_extra_record_fields():
    db=AsyncMock();db.__aenter__.return_value=db
    db.fetch.side_effect=[[{'id':'synthetic','tenant_id':'synthetic','status':'IN_TRANSIT','carrier_code':'EVRI','recipient_name':'PRIVATE NAME','address':'PRIVATE STREET','price':'PRIVATE PRICE'}],
        [{'status':'DELIVERED','occurred_at':datetime.now(timezone.utc),'location':'PRIVATE STREET'}]]
    helper=GuestShippingAssistant.__new__(GuestShippingAssistant);helper.pool=NS(acquire=lambda:db);helper.settings=settings()
    result=await helper.public_status('TRACK12345678')
    assert 'Delivered' in result and 'Evri' in result and 'PRIVATE' not in result
    assert 'public_status_lookup_enabled' in db.fetch.call_args_list[0].args[0]


@pytest.mark.asyncio
async def test_guest_tracking_retry_keeps_same_expiry():
    from starlette.datastructures import FormData
    db=AsyncMock();db.__aenter__.return_value=db;db.fetchval.return_value=1
    helper=GuestShippingAssistant.__new__(GuestShippingAssistant);helper.pool=NS(acquire=lambda:db)
    helper.settings=NS(**vars(settings()),whatsapp_provider='GUPSHUP',gupshup_app_id='synthetic')
    expires=datetime.now(timezone.utc)+timedelta(minutes=10)
    helper.load=AsyncMock(return_value=GuestDraft(state='AWAITING_TRACKING_REF',expires_at=expires))
    helper.save=AsyncMock();helper.public_status=AsyncMock(return_value='Not publicly available; please retry')
    form=FormData({'From':'whatsapp:+447700900123','To':'whatsapp:+447700900321','Body':'INVALID1234'})
    assert 'retry' in await helper.handle(form)
    assert helper.save.call_args.args[1].expires_at==expires


@pytest.mark.asyncio
async def test_starter_tracking_not_blocked_by_whatsapp_booking_gate(fixture):
    context,storage,state,gateway,_=fixture
    state.settings.whatsapp_progressive_enabled=True
    state.settings.booking_page_url='https://app.example.test'
    state.settings.quote_link_secret=settings().quote_link_secret
    gateway.execute=AsyncMock(return_value=gateway.reply('TRACK_PACKAGE','Your own parcel is in transit'))
    with patch('backend.entitlements.guard_feature',AsyncMock(side_effect=HTTPException(402,'upgrade'))) as guard:
        result=await gateway.process(context,ConversationMessage(channel='WHATSAPP',message_body='Track TRACK12345678'),verified_whatsapp=True)
    assert 'in transit' in result['conversational_reply'];guard.assert_not_awaited()


@pytest.mark.asyncio
async def test_starter_quote_offers_prefill_link_but_never_live_execution(fixture):
    context,_,state,gateway,_=fixture
    state.settings.whatsapp_progressive_enabled=True;state.settings.booking_page_url='https://app.example.test';state.settings.quote_link_secret=settings().quote_link_secret
    gateway.execute=AsyncMock()
    with patch('backend.entitlements.guard_feature',AsyncMock(side_effect=HTTPException(402,'upgrade'))):
        result=await gateway.process(context,ConversationMessage(channel='WHATSAPP',message_body='Quote 2kg from GB to GB'),verified_whatsapp=True)
    gateway.execute.assert_not_awaited()
    assert 'quick_quote=' in result['conversational_reply'] and '/pricing' in result['conversational_reply']


@pytest.mark.asyncio
@pytest.mark.parametrize('assisted,active',[(True,True),(False,False)])
async def test_public_lookup_opt_in_rejects_assistance_and_stale_membership(assisted,active):
    import httpx
    from fastapi import FastAPI
    from backend.whatsapp_progressive import build_router
    db=AsyncMock();db.__aenter__.return_value=db;db.fetchval.return_value=active
    async def actor():return NS(role='OWNER',tenant_id='synthetic',user_id='synthetic',assistance_session_id='synthetic' if assisted else None)
    app=FastAPI();app.state.settings=NS(whatsapp_progressive_enabled=True);app.state.whatsapp_queue=NS(pool=NS(acquire=lambda:db))
    app.include_router(build_router(actor))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://app.example.test') as client:
        response=await client.put('/api/v1/whatsapp/public-status-policy',json={'enabled':True})
    assert response.status_code==403;db.execute.assert_not_awaited()


@pytest.mark.parametrize('box', ['25x25x10', '25X25X10', '25\u00d725\u00d710', '25 x 25 x 10 cm', '25\u00d725\u00d710 CM'])
def test_phone_dimensions_do_not_become_destination_text(box):
    facts=classify('Quote 2kg from leeds gb to london gb '+box).facts
    assert (facts.origin_country,facts.destination_country)==('GB','GB')
    assert (facts.origin_city,facts.destination_city)==('leeds','london')
    assert facts.destination_postal_code is None
    assert facts.dimensions_cm==[Decimal('25'),Decimal('25'),Decimal('10')]
    result=ballpark(settings(),facts)
    assert result.count('Sample option ')==2
    assert '25 x 25 x 10 cm' in result and 'I still need' not in result


@pytest.mark.parametrize('box', ['25x25x10 inches','25x25x10 mm','-25x25x10','25x0x10'])
def test_phone_dimensions_do_not_silently_treat_other_units_or_negative_sizes_as_cm(box):
    with pytest.raises(ValueError):
        classify('Quote 2kg from leeds gb to london gb '+box)


def guest_conversation():
    db=AsyncMock();db.__aenter__.return_value=db;db.fetchval.return_value=1
    helper=GuestShippingAssistant.__new__(GuestShippingAssistant);helper.pool=NS(acquire=lambda:db)
    helper.settings=NS(**vars(settings()),whatsapp_provider='GUPSHUP',gupshup_app_id='synthetic')
    state={'draft':None}
    async def load(form):return state['draft']
    async def save(form,draft):state['draft']=draft
    async def clear(form):state['draft']=None
    helper.load=AsyncMock(side_effect=load);helper.save=AsyncMock(side_effect=save);helper.clear=AsyncMock(side_effect=clear)
    from starlette.datastructures import FormData
    def form(text):return FormData({'From':'whatsapp:+447700900123','To':'whatsapp:+447700900321','Body':text})
    return helper,state,form


@pytest.mark.asyncio
async def test_reported_two_turn_quote_finishes_without_paid_rating_calls():
    helper,state,form=guest_conversation()
    with patch('main.get_rates',AsyncMock()) as live_rates:
        first=await helper.handle(form('Shipping quote for 4.5 kg from leeds to london..'))
        assert 'Which countries' in first and '4.5 kg' in first
        assert 'leeds' in first and 'london' in first
        result=await helper.handle(form('Quote 2kg from leeds gb to london gb 25\u00d725\u00d710'))
        assert result.count('Sample option ')==2 and 'Examples only' in result
        token=result.split('quick_quote=',1)[1].split()[0]
        facts=verify_quote(helper.settings,token)
        assert facts['weight_kg']=='2' and facts['destination_country']=='GB'
        assert facts['dimensions_cm']==['25','25','10']
        assert state['draft'] is None
        live_rates.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('answer',['Both UK','both are GB','GB to GB','GB, GB'])
async def test_country_only_followup_keeps_weight_and_cities(answer):
    helper,state,form=guest_conversation()
    await helper.handle(form('Shipping quote for 4.5 kg from leeds to london'))
    result=await helper.handle(form(answer))
    assert result.count('Sample option ')==2 and '4.5 kg' in result
    token=result.split('quick_quote=',1)[1].split()[0]
    facts=verify_quote(helper.settings,token)
    assert facts['origin_city']=='leeds' and facts['destination_city']=='london'
    assert state['draft'] is None


@pytest.mark.asyncio
async def test_corrected_route_discards_corrupt_postcode_from_previous_parser():
    from backend.agents.models import ConversationalIntent
    helper,state,form=guest_conversation()
    state['draft']=GuestDraft(state='QUOTE',quote=ConversationalIntent(intent='QUOTE',weight_kg='2',origin_country='GB',origin_city='leeds',destination_postal_code='LONDON GB 25x25x10'))
    result=await helper.handle(form('Quote 2kg from leeds gb to london gb 25x25x10'))
    facts=verify_quote(helper.settings,result.split('quick_quote=',1)[1].split()[0])
    assert facts['destination_city']=='london'
    assert 'destination_postal_code' not in facts


@pytest.mark.asyncio
async def test_single_missing_country_accepts_country_only_reply():
    helper,state,form=guest_conversation()
    first=await helper.handle(form('Quote 2kg from leeds GB to london'))
    assert 'delivery country' in first and 'pickup country' not in first
    assert (await helper.handle(form('GB'))).count('Sample option ')==2
