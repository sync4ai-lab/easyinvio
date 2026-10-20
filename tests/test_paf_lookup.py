"""Licensed lookup contract, premise selection and draft boundaries, using fake HTTP."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from backend.paf_lookup import IdealPostcodesClient, PAFPremise, PAFLookupUnavailable, uk_postcode
from backend.agents.conversation_context import ConversationDraft, collect_reply, merge_quote
from backend.agents.models import ConversationalIntent
from backend.agents.conversational_gateway import ConversationalActionGateway, ConversationMessage
from test_conversational_gateway import fixture


def premise(index=1):
    return PAFPremise(udprn=str(index),postcode='SW1A 2AA',line1=f'Flat {index}, 10 Downing Street',
        line2='Dependent thoroughfare',post_town='LONDON',building_number='10',sub_building_name=f'Flat {index}',
        dependent_thoroughfare='Dependent thoroughfare',thoroughfare='Downing Street')


def draft():
    return ConversationDraft(action='QUOTE',intent=ConversationalIntent(intent='QUOTE',weight_kg='3',
        origin_country='GB',destination_country='FR',origin_postal_code='SW1A 2AA',destination_postal_code='75001'),
        waiting_for='paf_selection',paf_prefix='origin',paf_options=[premise(i) for i in range(1,11)])


@pytest.mark.asyncio
async def test_lookup_uses_header_secret_and_preserves_paf_components():
    async def server(request):
        assert request.url.host=='api.ideal-postcodes.co.uk' and request.url.path.endswith('/SW1A2AA')
        assert request.headers['authorization']=='Bearer synthetic-key'
        assert 'api_key' not in request.url.params
        return httpx.Response(200,json={'code':2000,'total':1,'result':[dict(udprn=12345,postcode='SW1A 2AA',
            line_1='Flat 1, 10 Downing Street',line_2='Dependent thoroughfare',line_3='Westminster',post_town='LONDON',
            building_number='10',sub_building_name='Flat 1',dependant_thoroughfare='Dependent thoroughfare',thoroughfare='Downing Street')]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http:
        options=await IdealPostcodesClient(http,SecretStr('synthetic-key')).lookup('sw1a2aa')
    address=options[0].address('Actual recipient')
    assert address.postal_code=='SW1A 2AA' and address.city=='LONDON'
    assert address.line2=='Dependent thoroughfare, Westminster' and options[0].building_number=='10'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,data',[(401,{}),(200,{'code':2000,'result':[{}]}),
    (200,{'code':2000,'result':[{'postcode':'LS1 2TW'}]})])
async def test_failed_or_invalid_lookup_never_fabricates_an_address(status,data):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(status,json=data))) as http:
        with pytest.raises(PAFLookupUnavailable):
            await IdealPostcodesClient(http,SecretStr('synthetic')).lookup('SW1A 2AA')


def test_selection_is_display_scoped_and_preserves_ttl_across_serialization():
    value=draft();expires=value.expires_at
    with pytest.raises(ValueError):collect_reply(value,'9',require_paf=True)
    collect_reply(value,'More',require_paf=True)
    value=ConversationDraft.model_validate_json(value.model_dump_json())
    collect_reply(value,'9',require_paf=True)
    assert value.waiting_for=='origin_contact' and value.paf_selected=={'origin':'9'}
    collect_reply(value,'Alex Sender',require_paf=True)
    assert value.origin_address['line1']=='Flat 9, 10 Downing Street'
    assert value.origin_address['name']=='Alex Sender' and value.origin_address['city']=='LONDON'
    assert value.expires_at==expires
    merge_quote(value,ConversationalIntent(intent='QUOTE',origin_postal_code='LS1 2TW'))
    assert value.origin_address is None and not value.paf_selected
    value.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    assert not value.active(SimpleNamespace(assistance_session_id=None))


@pytest.mark.asyncio
async def test_gateway_lists_then_selects_without_relooking_up_and_replays_receipt(fixture):
    context,storage,state,gateway,app=fixture
    original=storage.execute
    async def execute(sql,*args):
        if 'UPDATE public.whatsapp_bindings' in sql:return 'UPDATE 1'
        return await original(sql,*args)
    storage.execute=execute
    state.settings.twilio_whatsapp_number='+14155238886'
    state.paf=SimpleNamespace(lookup=AsyncMock(return_value=[premise(i) for i in range(1,11)]))
    state.rating=SimpleNamespace(quote=AsyncMock())
    gateway.draft=draft()
    def body(text):return ConversationMessage(channel='WHATSAPP',sender_id='+447700900123',message_body=text)
    first=await gateway.process(context,body('Quote 3kg from SW1A 2AA GB to 75001 FR'),verified_whatsapp=True)
    assert '1: Flat 1' in first['conversational_reply']
    expires=list(storage.rows.values())[-1]['response']
    replay=body('More')
    next_page=await ConversationalActionGateway(gateway.request).process(context,replay,verified_whatsapp=True)
    assert '9: Flat 9' in next_page['conversational_reply']
    assert next_page==await gateway.process(context,replay,verified_whatsapp=True)
    selected=await gateway.process(context,body('9'),verified_whatsapp=True)
    assert 'pickup contact' in selected['conversational_reply']
    final=await gateway.process(context,body('Alex Sender'),verified_whatsapp=True)
    assert 'dimensions' in final['conversational_reply']
    state.paf.lookup.assert_awaited_once_with('SW1A 2AA')
    state.rating.quote.assert_not_awaited()


@pytest.mark.parametrize('value',['','SW1A','12345','SW1A 2AA; 10 Fake Road'])
def test_postcode_is_only_a_lookup_key(value):
    with pytest.raises(ValueError):uk_postcode(value)


@pytest.mark.asyncio
async def test_both_uk_ends_use_selected_premises_before_rating(fixture):
    from test_conversation_context import quote_result
    context,storage,state,gateway,_=fixture
    original=storage.execute
    async def execute(sql,*args):
        if 'UPDATE public.whatsapp_bindings' in sql:return 'UPDATE 1'
        return await original(sql,*args)
    storage.execute=execute
    state.settings.twilio_whatsapp_number='+14155238886'
    destination=premise(2).model_copy(update={'postcode':'LS1 1AA','post_town':'LEEDS'})
    state.paf=SimpleNamespace(lookup=AsyncMock(side_effect=[[premise(1)],[destination]]))
    state.rating=SimpleNamespace(quote=AsyncMock(return_value=quote_result()))
    for text in ['Quote 3kg from SW1A 2AA GB to LS1 1AA GB','1','Alice Sender','1','Bob Recipient','30 x 20 x 10']:
        result=await ConversationalActionGateway(gateway.request).process(context,ConversationMessage(
            channel='WHATSAPP',sender_id='+447700900123',message_body=text),verified_whatsapp=True)
    assert result['status']=='COMPLETED'
    rating=state.rating.quote.await_args.args[1]
    assert rating.origin.line1==premise(1).line1 and rating.origin.name=='Alice Sender'
    assert rating.destination.line1==destination.line1 and rating.destination.city=='LEEDS'
    assert rating.destination.name=='Bob Recipient'
    assert [call.args[0] for call in state.paf.lookup.await_args_list]==['SW1A 2AA','LS1 1AA']
