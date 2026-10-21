"""Published status knowledge, grounded answers and non-action chat routing."""
import json
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.help_center import router
from backend.agents.config import AgentSettings
from backend.agents.supervisor import LogisticsSupervisor
from backend.agents.runtime import AgentRuntime, ModelResult
from backend.agents.rag_support import HelpRetriever
from backend.agents.models import CitedAnswer
from backend.agents.status_guidance import status_question
from backend.agents.conversational_gateway import ConversationalActionGateway, ConversationMessage
from test_conversational_gateway import fixture, message


def engine():
    return LogisticsSupervisor(AgentSettings(_env_file=None,logistics_agents_enabled=False))


@pytest.mark.parametrize('query,expected',[
    ('What does quote expired mean?',True),('Why is my wallet RESERVED?',True),
    ('My return says received but no refund',True),('What does pending mean?',True),
    ('What should I do about claim ACTION_REQUIRED?',True),('Explain booking failed',True),
    ('PENDING',True),('FAILED',True),
    ('Book option 3',False),('Confirm option 1',False),('Top up 50 GBP',False),
    ('Track TEST123',False),('Return order FAILED',False),('Manifest status',False),
    ('Claim DPD-7712 lost The box was lost in transit',False),('My package is lost',False),
    ('Quote 3kg from GB to FR',False),('Close manifest Royal Mail',False),
])
def test_questions_do_not_replace_explicit_native_commands(query,expected):
    assert status_question(query)==expected


@pytest.mark.asyncio
@pytest.mark.parametrize('query,contains',[
    ('What does quote expired mean?','Requote'),('Why is my wallet reserved?','not yet'),
    ('My return says received but no refund','retailer'),('What does pending mean?','screen'),
    ('What should I do about claim ACTION_REQUIRED?','requested'),
    ('What does INSURER_PAYMENT_REPORTED mean?','does not prove'),
])
async def test_offline_answers_include_real_next_steps_and_status_guide_citations(query,contains):
    service=engine();context=SimpleNamespace(tenant_id=uuid4(),user_id=uuid4(),role='OWNER')
    result=await service.help.answer(context,query)
    assert contains.lower() in result['answer'].lower(),result
    assert result['answer'].startswith('General guidance: ')
    assert result['sources'][0]['url'].startswith('/help/status-guide#')
    assert service.runtime.usage['model_calls']==0
    assert (await service.help.answer(context,query))['cached']


def test_published_guide_is_searchable_downloadable_and_every_citation_anchor_exists():
    app=FastAPI();app.include_router(router);client=TestClient(app)
    body=client.get('/help/status-guide')
    assert body.status_code==200 and 'In this guide' in body.text
    assert '/help/status-guide' in client.get('/help').text
    assert any(item['url']=='/help/status-guide' for item in client.get('/help/search-index.json').json()['guides'])
    assert client.get('/help/source/status-guide').status_code==200
    for value in ['QUOTE_EXPIRED','RESERVED','CREDITED','UNAVAILABLE','CLAIM_INGESTED','INSURER_PAYMENT_REPORTED','REFUND_APPROVED_AND_CREDITED','SIMULATED_DELIVERED','RECONCILIATION_REQUIRED','PENDING_OTP']:
        assert value in body.text
    class Anchors(HTMLParser):
        def __init__(self):super().__init__();self.ids=set()
        def handle_starttag(self,tag,attrs):
            values=dict(attrs)
            if 'id' in values:self.ids.add(values['id'])
    anchors=Anchors();anchors.feed(body.text)
    chunks,_=engine().help.corpus()
    assert len(chunks)<=160
    for chunk in chunks:
        if chunk.source_file=='docs/status_reference.md' and '#' in chunk.url:
            assert chunk.url.split('#',1)[1] in anchors.ids


@pytest.mark.asyncio
async def test_agent_interpreter_routes_status_help_without_authorizing_booking():
    service=engine();context=SimpleNamespace(tenant_id=uuid4(),user_id=uuid4(),role='ACCOUNTANT')
    result=await service.interpret(context,'What does label created mean?')
    assert result['intent']['intent']=='HELP' and not result['booking_authorized']
    assert result['help']['sources'][0]['url'].startswith('/help/status-guide#')
    assert service.runtime.usage['model_calls']==0


@pytest.mark.asyncio
async def test_ai_status_answer_receives_grounded_sections_and_safe_recovery_instructions():
    from test_agents import settings
    runtime=AgentRuntime(settings(True),client=SimpleNamespace())
    retriever=HelpRetriever(runtime)
    retriever.index=AsyncMock(side_effect=HTTPException(503,'Offline vector fixture'))
    async def generate(tenant,worker,instructions,payload,output_type=None):
        assert 'Never recommend repeating a purchase' in instructions
        assert any('Quote expired' in chunk['title'] for chunk in payload['chunks'])
        return ModelResult(CitedAnswer(answer='Use Requote, review the saved details and compare fresh rates.',
            chunk_ids=[payload['chunks'][0]['id']],insufficient_evidence=False),20,10,0)
    runtime.run=AsyncMock(side_effect=generate)
    result=await retriever.answer(SimpleNamespace(tenant_id=uuid4()),'What does quote expired mean?')
    assert result['mode']=='AI_CITED_ANSWER' and result['sources'][0]['url'].startswith('/help/status-guide#')
    runtime.run.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('channel',['WEB_CHAT','WHATSAPP'])
async def test_status_question_preserves_pending_draft_ttl_and_message_receipts(fixture,channel):
    context,storage,state,gateway,_=fixture
    state.logistics_supervisor=engine();state.settings.twilio_whatsapp_number='+14155238886'
    state.settings.booking_page_url='https://app.example.test'
    body=lambda text:ConversationMessage(channel=channel,message_body=text,sender_id='+447700900123' if channel=='WHATSAPP' else None)
    await gateway.process(context,body('Quote 3kg from London to Paris'),verified_whatsapp=channel=='WHATSAPP')
    before=json.loads(list(storage.rows.values())[-1]['response'])['_pending']
    question=body('What does quote expired mean?')
    result=await ConversationalActionGateway(gateway.request).process(context,question,verified_whatsapp=channel=='WHATSAPP')
    assert result['action_taken']=='HELP' and 'Requote' in result['conversational_reply']
    assert ('https://app.example.test/help/status-guide' if channel=='WHATSAPP' else '/help/status-guide') in result['conversational_reply']
    after=json.loads(list(storage.rows.values())[-1]['response'])['_pending']
    assert after==before
    assert result==await gateway.process(context,question,verified_whatsapp=channel=='WHATSAPP')
    state.partner_lifecycle.confirm.assert_not_awaited();state.finance.create_checkout.assert_not_awaited()
    assert not any('insurance_claim_cases' in sql for sql,_ in storage.writes)
