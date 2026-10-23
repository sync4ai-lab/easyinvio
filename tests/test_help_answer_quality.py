"""Answer quality and read-only web fallback; no real API calls or customer data."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from backend.agents.config import AgentSettings
from backend.agents.models import CitedAnswer
from backend.agents.runtime import AgentRuntime, ModelResult
from backend.agents.rag_support import HelpRetriever, Chunk
from backend.agents.supervisor import LogisticsSupervisor
from backend.agents.web_help import public_search_query, safe_source_url, search_public_help
from backend.agents.conversational_gateway import ConversationalActionGateway, ConversationMessage, message_xml
from tests.test_conversational_gateway import fixture

AMAZON = 'how to integrate with amazon platform. give me detailed steps with examples'


def engine(enabled=False, client=None):
    settings = AgentSettings(_env_file=None, logistics_agents_enabled=enabled, openai_api_key=SecretStr('synthetic'))
    return LogisticsSupervisor(runtime=AgentRuntime(settings, client=client or SimpleNamespace()))


def context():
    return SimpleNamespace(tenant_id=uuid4(), user_id=uuid4(), role='OWNER')


def web_result(url='https://www.trade.gov/incoterms'):
    text = 'Consult the official Incoterms guidance [source].'
    start = text.index('[source]')
    annotation = SimpleNamespace(type='url_citation', url=url, title='Official guidance', start_index=start, end_index=start+8)
    return SimpleNamespace(status='completed', usage=SimpleNamespace(input_tokens=80,output_tokens=50), output=[
        SimpleNamespace(type='web_search_call'), SimpleNamespace(type='message', content=[
            SimpleNamespace(type='output_text',text=text,annotations=[annotation])])])


@pytest.mark.asyncio
async def test_amazon_question_has_complete_specific_steps_without_any_ai_configuration():
    service = engine()
    result = await service.help.answer(context(), AMAZON)
    text = result['answer']
    for expected in ['1. Sign in', '6. After', 'Store Integrations', 'Seller ID', 'SKU', 'MUG-BLUE = 350',
                     'ORDER_CHANGE', 'EventBridge', 'x-easyinvio-amazon-key', 'Marketplace Workspace']:
        assert expected in text
    assert result['retrieval'] == 'TOPIC'
    assert all(source['url'].startswith('/help/connect-amazon#') for source in result['sources'])
    assert 'pricing rules' not in text and 'closest available' not in text and not result['excerpts']
    assert service.runtime.usage['model_calls'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('query,expected',[
    ('How do I connect Shopify?', 'myshopify.com'),
    ('How do I connect WooCommerce?', 'x-wc-webhook-signature'),
    ('How do I connect eBay?', 'still need implementation'),
    ('How do I connect Etsy?', 'not implemented'),
    ('How do I invite a colleague?', 'invitation'),
    ('When is my wallet charged?', 'reserves'),
    ('What does quote expired mean?', 'Requote'),
    ('How do tracking notification preferences work?', 'future'),
])
async def test_common_questions_select_relevant_local_help(query,expected):
    result = await engine().help.answer(context(),query)
    assert expected.lower() in result['answer'].lower(), result
    assert result['sources'] and result['mode'] != 'NO_EVIDENCE'


@pytest.mark.asyncio
async def test_amazon_model_receives_only_relevant_sources_and_can_give_detailed_steps():
    service = engine(True)
    async def answer(tenant,worker,instructions,payload,output_type=None):
        assert worker == 'HelpSupportAgent'
        assert 'complete numbered steps' in instructions
        assert all('Connect Amazon' in chunk['title'] for chunk in payload['chunks'])
        return ModelResult(CitedAnswer(answer='1. Open Store Integrations. 2. Save authorised Amazon credentials. 3. Configure AWS notifications.',
                          chunk_ids=[payload['chunks'][0]['id']], insufficient_evidence=False),100,100,0)
    service.runtime.run = AsyncMock(side_effect=answer)
    service.runtime.embed = AsyncMock(side_effect=AssertionError('Known setup topic needs no cold corpus embedding'))
    result = await service.help.answer(context(),AMAZON)
    assert result['mode']=='AI_CITED_ANSWER'
    service.runtime.embed.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_outage_keeps_complete_amazon_steps_without_caching_failure():
    service = engine(True)
    service.runtime.run = AsyncMock(side_effect=HTTPException(503,'Synthetic outage'))
    member=context()
    for _ in range(2):
        result=await service.help.answer(member,AMAZON)
        assert '6. After' in result['answer'] and 'EventBridge' in result['answer']
        assert result['fallback_reason']=='ANSWER_UNAVAILABLE'
    assert service.runtime.run.await_count==2


@pytest.mark.asyncio
@pytest.mark.parametrize('role',['OWNER','ADMIN','DISPATCHER','ACCOUNTANT'])
@pytest.mark.parametrize('channel',['WEB_CHAT','WHATSAPP'])
async def test_both_channels_answer_without_command_spam_and_preserve_draft_receipts(fixture,role,channel):
    member,storage,state,gateway,_ = fixture
    member = replace(member, role=role)
    storage.context=member;storage.role=role
    state.logistics_supervisor=engine()
    state.settings.booking_page_url='https://app.example.test'
    state.settings.twilio_whatsapp_number='+14155238886'
    body=ConversationMessage(channel=channel,message_body=AMAZON,
        sender_id='+447700900123' if channel=='WHATSAPP' else None)
    result=await gateway.process(member,body,verified_whatsapp=channel=='WHATSAPP')
    assert 'Seller ID' in result['conversational_reply'] and '6. After' in result['conversational_reply']
    assert 'Send Cancel' not in result['conversational_reply'] and 'Top up 50 GBP' not in result['conversational_reply']
    assert result==await gateway.process(member,body,verified_whatsapp=channel=='WHATSAPP')
    if channel=='WHATSAPP':
        assert 'https://app.example.test/help/connect-amazon' in result['conversational_reply']
        from xml.etree import ElementTree
        assert all(len(node.text or '')<=1600 for node in ElementTree.fromstring(message_xml(result['conversational_reply'])).findall('Message/Body'))
    state.partner_lifecycle.confirm.assert_not_awaited();state.finance.create_checkout.assert_not_awaited()


@pytest.mark.asyncio
async def test_general_question_uses_only_read_only_web_tool_and_verified_citations():
    create=AsyncMock(return_value=web_result())
    service=engine(True,SimpleNamespace(responses=SimpleNamespace(create=create)))
    result=await service.help.answer(context(),'What are Incoterms?')
    assert result['mode']=='WEB_CITED_ANSWER', result
    assert result['answer'].startswith('General web guidance, not verified EasyInvio setup.')
    assert '[1]' in result['answer'] and result['sources'][0]['url']=='https://www.trade.gov/incoterms'
    request=create.call_args.kwargs
    assert request['tools']==[{'type':'web_search','search_context_size':'low'}]
    assert request['tool_choice']=='required' and request['max_tool_calls']==1 and not request['store']
    assert 'tenant' not in request['input'].lower() and 'token' not in request['input'].lower()


@pytest.mark.asyncio
async def test_web_failure_or_disabled_flag_does_not_invent_an_answer():
    create=AsyncMock(side_effect=RuntimeError('Synthetic outage'))
    service=engine(True,SimpleNamespace(responses=SimpleNamespace(create=create)))
    result=await service.help.answer(context(),'What are Incoterms?')
    assert result['mode']=='NO_EVIDENCE' and not result['sources']
    service.runtime.settings.logistics_help_web_search_enabled=False
    await service.help.answer(context(),'What are Incoterms?')
    assert create.await_count==1


@pytest.mark.parametrize('query',[
    'Shipping question for alice@example.invalid', 'Shipping address is 10 Private Road',
    'Shipping for my order EINVIO-1234', 'Shipping from SW1A 2AA',
    'Shipping: api_key=some-private-value', 'Shipping question +447700900123',
    'Shipping for '+str(uuid4()), 'What is my wallet balance?',
])
def test_private_questions_never_become_public_searches(query):
    assert public_search_query(query) is None


@pytest.mark.parametrize('url',['http://example.com','https://127.0.0.1/a','https://localhost/a',
    'https://user:secret@example.com/a','https://example.com:8443/a','https://private.internal/a'])
@pytest.mark.asyncio
async def test_bad_or_uncited_web_sources_are_rejected(url):
    assert not safe_source_url(url)
    create=AsyncMock(return_value=web_result(url))
    service=engine(True,SimpleNamespace(responses=SimpleNamespace(create=create)))
    assert await search_public_help(service.runtime,uuid4(),'What are Incoterms?') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('channel',['WEB_CHAT','WHATSAPP'])
async def test_setup_question_during_a_quote_preserves_exact_draft_deadline(fixture,channel):
    member,storage,state,gateway,_=fixture
    state.logistics_supervisor=engine();state.settings.twilio_whatsapp_number='+14155238886'
    state.settings.booking_page_url='https://app.example.test'
    def body(text):
        return ConversationMessage(channel=channel,message_body=text,
            sender_id='+447700900123' if channel=='WHATSAPP' else None)
    await gateway.process(member,body('Quote 3kg from London to Paris'),verified_whatsapp=channel=='WHATSAPP')
    before=json.loads(list(storage.rows.values())[-1]['response'])['_pending']
    result=await ConversationalActionGateway(gateway.request).process(member,body(AMAZON),verified_whatsapp=channel=='WHATSAPP')
    after=json.loads(list(storage.rows.values())[-1]['response'])['_pending']
    assert before==after and 'Seller ID' in result['conversational_reply']


@pytest.mark.asyncio
@pytest.mark.parametrize('query',['Can you quote 3kg from London to Paris?',
    'Give me rates for 3kg from London to Paris', 'What is the shipping rate for 3kg from London to Paris?'])
async def test_polite_rate_requests_remain_native_quote_intents(fixture,query):
    member,storage,state,gateway,_=fixture
    state.logistics_supervisor=engine()
    assert (await gateway.interpret(member,query)).intent=='QUOTE'
