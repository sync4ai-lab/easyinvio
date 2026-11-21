"""Public guidance must never turn a phone number into workspace authority."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
import pytest
from starlette.datastructures import FormData
from backend.whatsapp_concierge import answer,social
from test_conversational_gateway import fixture as gateway_fixture


def setup(text,count=1):
    db=AsyncMock();db.fetchval.return_value=count;db.__aenter__.return_value=db
    state=NS(settings=NS(booking_page_url='https://app.example.test',whatsapp_provider='GUPSHUP',gupshup_app_id='synthetic'),
        whatsapp_queue=NS(pool=NS(acquire=lambda:db)))
    return NS(app=NS(state=state)),FormData({'Body':text,'From':'whatsapp:+447700900123','To':'whatsapp:+447700900321','NumMedia':'0'})


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['hello','Hi!','Good morning','help','menu','what can you do'])
async def test_welcome_lists_three_paths_without_model_or_tracking_demand(text):
    request,form=setup(text)
    with patch('backend.agents.supervisor.supervisor') as engine:
        result=await answer(request,form)
    engine.assert_not_called()
    assert 'welcome to EasyInvio' in result and result.count('•')==3
    assert 'What would you like' in result and 'token' not in result
    assert len(result)<500


@pytest.mark.asyncio
async def test_verified_greeting_and_thanks_are_local():
    request,form=setup('hello')
    assert 'welcome back' in await answer(request,form,known=True)
    request,form=setup('thanks')
    assert 'welcome' in (await answer(request,form)).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['track my parcel','my wallet balance','my parcel arrived damaged','refund my order'])
async def test_private_requests_cannot_reach_rag(text):
    request,form=setup(text)
    with patch('backend.agents.supervisor.supervisor') as engine:
        result=await answer(request,form)
    engine.assert_not_called()
    assert 'secure' in result or '/workspace' in result


@pytest.mark.asyncio
async def test_booking_requires_verified_workspace_and_paid_plan():
    request,form=setup('Quote 2.5kg from GB to GB')
    result=await answer(request,form)
    assert 'Velocity or Command' in result and 'verified' in result


@pytest.mark.asyncio
async def test_rag_uses_public_context_no_external_search_and_one_short_reply():
    request,form=setup('How do I connect Shopify?')
    helper=AsyncMock(return_value={'answer':'Useful instructions. '*100,'sources':[{'url':'https://evil.example/path'},{'url':'/help/connect-shopify'}]})
    with patch('backend.agents.supervisor.supervisor',return_value=NS(help=NS(answer=helper))):
        result=await answer(request,form)
    args,kwargs=helper.call_args
    assert args[0].role=='PUBLIC' and args[0].tenant_id=='public-documentation'
    assert kwargs=={'allow_web':False,'concise':True}
    assert len(result)<=1500 and 'evil.example' not in result
    assert 'https://app.example.test/help/connect-shopify' in result


@pytest.mark.asyncio
async def test_guidance_budget_does_not_pay_for_endless_limit_replies():
    for count in (21,31,32):
        request,form=setup('How do I connect Shopify?',count)
        with patch('backend.agents.supervisor.supervisor') as engine:
            result=await answer(request,form)
        engine.assert_not_called()
        assert (result is None)==(count==32)


def test_greeting_classifier_does_not_swallow_a_real_request():
    assert social('hello track my parcel') is None
    assert social('Confirm return') is None


@pytest.mark.asyncio
async def test_registered_greeting_bypasses_model_without_authorizing_actions(gateway_fixture):
    from backend.whatsapp_queue import process_inbound
    from starlette.requests import Request
    context,_,state,_,app=gateway_fixture
    state.settings.whatsapp_consumer_cx_enabled=False
    state.settings.whatsapp_uat_mode=False;state.settings.whatsapp_outbound_paused=False
    state.settings.twilio_enabled=True
    state.whatsapp=NS(resolve_sender=AsyncMock(return_value=context))
    _,form=setup('hello')
    form=FormData(dict(form)|{'MessageSid':'synthetic-greeting','AccountSid':'synthetic'})
    db=AsyncMock();db.__aenter__.return_value=db;db.fetchval.return_value=1
    state.whatsapp_queue=NS(pool=NS(acquire=lambda:db))
    with patch('backend.whatsapp_onboarding.onboarding_manager',AsyncMock(return_value=None)),patch('backend.agents.conversational_gateway.ConversationalActionGateway.process',AsyncMock()) as gateway:
        parts=await process_inbound(Request({'type':'http','app':app,'headers':[]}),form)
    gateway.assert_not_awaited()
    assert 'welcome back' in parts[0].body
