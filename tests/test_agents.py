"""Agent boundaries and failures using local mocks, never paid provider calls."""
import asyncio
import csv
import io
import json
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend.agents.config import AgentSettings
from backend.agents.models import CitedAnswer, Workflow, State, QuoteIntent, HSSelection
from backend.agents.runtime import AgentRuntime, ModelResult, Cache
from backend.agents.supervisor import LogisticsSupervisor
from backend.agents.routes import build_router
from backend.agents.rag_support import HelpRetriever, redacted_question
from backend.order_csv import CSV_FIELDS
from backend.automation_three_partners import BookingRequest
from backend.invoice_upload import StatementLine, compare_line


def settings(enabled=False, **values):
    return AgentSettings.model_construct(logistics_agents_enabled=enabled,
        openai_api_key=SimpleNamespace(get_secret_value=lambda: 'test-key-not-real'), **values)


def context(role='OWNER'):
    return SimpleNamespace(tenant_id=uuid4(), user_id=uuid4(), role=role)


class AgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = context()
        self.engine = LogisticsSupervisor(settings())

    async def test_standard_message_zero_model_calls_and_no_purchase(self):
        result = await self.engine.interpret(self.context, 'Quote 4.5kg from GBR to USA')
        self.assertEqual(result['intent']['origin_country'], 'GB')
        self.assertEqual(result['workflow']['state'], 'NEEDS_INPUT')
        self.assertFalse(result['booking_authorized'])
        self.assertEqual(self.engine.runtime.usage['model_calls'], 0)

    async def test_unknown_message_disabled_fails_before_services(self):
        with self.assertRaises(HTTPException) as raised:
            await self.engine.interpret(self.context, 'Please purchase a parcel now')
        self.assertEqual(raised.exception.status_code, 503)

    async def test_invalid_role_has_no_model_cost(self):
        with self.assertRaises(HTTPException) as raised:
            await self.engine.interpret(context('VIEWER'), 'Quote 4.5kg from GBR to USA')
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(self.engine.runtime.usage['model_calls'], 0)

    async def test_extracted_invented_weight_rejected(self):
        intent = QuoteIntent(intent='QUOTE', weight_kg='9', origin_country='GB', destination_country='FR', route_code=None)
        self.engine.runtime.run = AsyncMock(return_value=ModelResult(intent.model_dump_json(), 20, 10, 0))
        with self.assertRaises(ValueError):
            await self.engine.ingestion.message(self.context, 'I have 5kg shipping from Britain to France')

    async def test_missing_measurements_are_never_invented(self):
        intent = QuoteIntent(intent='QUOTE', weight_kg=None, origin_country='GB', destination_country=None, route_code=None)
        self.engine.runtime.run = AsyncMock(return_value=ModelResult(intent.model_dump_json(), 20, 10, 0))
        result = await self.engine.interpret(self.context, 'Send my parcel from Britain')
        self.assertIsNone(result['intent']['weight_kg'])
        self.assertEqual(result['workflow']['state'], 'NEEDS_INPUT')

    async def test_csv_aliases_preserve_all_values(self):
        headers = list(CSV_FIELDS)
        headers[headers.index('weight_kg')] = 'Packed Weight KG'
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(headers)
        values = ['original-' + str(index) for index in range(len(headers))]
        writer.writerow(values)
        mapped = await self.engine.ingestion.csv_headers(self.context, output.getvalue().encode())
        rows = list(csv.reader(io.StringIO(mapped.decode())))
        self.assertEqual(rows[0], list(CSV_FIELDS))
        self.assertEqual(rows[1], values)
        self.assertEqual(self.engine.runtime.usage['model_calls'], 0)

    async def test_csv_unknown_headers_only_sent_no_customer_rows(self):
        headers = list(CSV_FIELDS)
        headers[headers.index('weight_kg')] = 'Measured kilograms'
        result = {'columns': [{'source': 'Measured kilograms', 'target': 'weight_kg'}], 'unresolved': []}
        self.engine.runtime.run = AsyncMock(return_value=ModelResult(json.dumps(result), 20, 10, 0))
        raw = (','.join(headers) + '\n' + ','.join(['PRIVATE CUSTOMER VALUE'] * len(headers))).encode()
        mapped = await self.engine.ingestion.csv_headers(self.context, raw)
        payload = self.engine.runtime.run.call_args.args[3]
        self.assertNotIn('PRIVATE CUSTOMER VALUE', json.dumps(payload))
        self.assertIn(b'PRIVATE CUSTOMER VALUE', mapped)

    async def test_csv_duplicate_targets_rejected(self):
        self.engine.runtime.run = AsyncMock(return_value=ModelResult(json.dumps({'columns': [
            {'source': 'unknown1', 'target': 'weight_kg'}, {'source': 'unknown2', 'target': 'weight_kg'}], 'unresolved': []}), 20, 10, 0))
        with self.assertRaises(HTTPException):
            await self.engine.ingestion.csv_headers(self.context, b'unknown1,unknown2\n1,2')

    async def test_customs_preserves_reviewed_facts(self):
        item = {'description': 'cotton knitted t-shirt', 'quantity': 2, 'unit_value': '30.20',
            'unit_weight_kg': '0.250', 'origin_country': 'CN', 'package_index': 2, 'hs_code': '610910'}
        result = await self.engine.customs.information(self.context, [item])
        self.assertFalse(result['customs_approved'])
        for key in ('quantity', 'origin_country', 'package_index', 'hs_code'):
            self.assertEqual(result['items'][0][key], item[key])
        self.assertEqual(Decimal(result['items'][0]['unit_value']), Decimal('30.20'))

    async def test_customs_ai_cannot_invent_national_codes(self):
        runtime = AgentRuntime(settings(True), client=SimpleNamespace())
        engine = LogisticsSupervisor(runtime=runtime)
        runtime.run = AsyncMock(return_value=ModelResult(HSSelection(hs_code='999999', explanation='invented', missing_attributes=[]), 20, 10, 0))
        with self.assertRaises(HTTPException):
            await engine.customs.suggest(self.context, 'cotton knitted t-shirt')

    async def test_customs_duplicate_descriptions_call_once(self):
        item = {'description': 'cotton knitted t-shirt', 'quantity': 2, 'unit_value': '30', 'unit_weight_kg': '.250', 'origin_country': 'CN'}
        self.engine.customs.suggest = AsyncMock(return_value={'hs_code': '610910', 'status': 'review_required'})
        await self.engine.customs.information(self.context, [item, item])
        self.engine.customs.suggest.assert_awaited_once()

    async def test_official_tariff_ranking_preserves_codes_and_source_links(self):
        runtime = AgentRuntime(settings(True), client=SimpleNamespace())
        engine = LogisticsSupervisor(runtime=runtime)
        runtime.run = AsyncMock(return_value=ModelResult(HSSelection(hs_code='6109100090', explanation='Check cotton and knitting', missing_attributes=[]), 20, 10, 0))
        candidates = [{'hs_code': '610990', 'national_code': '6109900090', 'title': 'Other textiles', 'source_url': 'https://example.test/other'},
            {'hs_code': '610910', 'national_code': '6109100090', 'title': 'Cotton', 'source_url': 'https://example.test/cotton'}]
        result = await engine.customs.rank_tariff(self.context, 'cotton knitted t-shirt', {'candidates': candidates})
        self.assertEqual(result['candidates'][0], candidates[1])
        self.assertFalse(result['agent_review']['customs_approved'])
        self.assertEqual({row['national_code'] for row in result['candidates']}, {row['national_code'] for row in candidates})

    async def test_ai_cannot_reassign_known_csv_columns(self):
        headers = list(CSV_FIELDS)
        headers[headers.index('weight_kg')] = 'Measured kilograms'
        columns = [{'source': source, 'target': target} for source, target in zip(headers, CSV_FIELDS)]
        for entry in columns:
            if entry['source'] == 'origin_city':
                entry['target'] = 'destination_city'
        self.engine.runtime.run = AsyncMock(return_value=ModelResult(json.dumps({'columns': columns, 'unresolved': []}), 20, 10, 0))
        with self.assertRaises(HTTPException):
            await self.engine.ingestion.csv_headers(self.context, (','.join(headers) + '\n').encode())

    async def test_ui_rate_worker_passes_exact_request_without_model(self):
        request = object()
        result = object()
        rating = SimpleNamespace(quote=AsyncMock(return_value=result))
        self.assertIs(await self.engine.rates(self.context, request, rating), result)
        rating.quote.assert_awaited_once_with(self.context, request)
        self.assertEqual(self.engine.runtime.usage['model_calls'], 0)

    async def test_booking_forwards_exact_context_offer_and_result(self):
        body = BookingRequest(tenant_id=self.context.tenant_id, offer_id=uuid4())
        result = {'status': 'SYNC_PENDING', 'shipment_id': str(uuid4())}
        service = SimpleNamespace(confirm=AsyncMock(return_value=result))
        self.assertIs(await self.engine.confirm(self.context, body, service), result)
        service.confirm.assert_awaited_once_with(self.context, body)
        self.assertEqual(self.engine.runtime.usage['model_calls'], 0)

    async def test_wrong_tenant_cannot_reach_booking_service(self):
        service = SimpleNamespace(confirm=AsyncMock())
        with self.assertRaises(HTTPException):
            await self.engine.confirm(self.context, BookingRequest(tenant_id=uuid4(), offer_id=uuid4()), service)
        service.confirm.assert_not_awaited()

    async def test_provider_failure_is_not_retried(self):
        service = SimpleNamespace(confirm=AsyncMock(side_effect=HTTPException(502, 'Rejected')))
        with self.assertRaises(HTTPException):
            await self.engine.confirm(self.context, BookingRequest(tenant_id=self.context.tenant_id, offer_id=uuid4()), service)
        service.confirm.assert_awaited_once()

    async def test_tracking_signature_failure_cannot_stage_ticket(self):
        native = SimpleNamespace(receive_tracking=AsyncMock(side_effect=HTTPException(401, 'Bad signature')))
        with self.assertRaises(HTTPException):
            await self.engine.support.receive_tracking(object(), native)
        self.assertEqual(self.engine.runtime.usage['model_calls'], 0)

    async def test_invoice_exact_existing_comparisons_without_model(self):
        line = StatementLine(upstream_shipment_id='original-ref', currency='GBP', invoice_weight_kg='3', wholesale_cost='12', residential_fee='0')
        shipment = {'parcel_weight_kg': Decimal('2'), 'wholesale_cost': Decimal('10'), 'currency': 'GBP', 'logistics_metadata': {}, 'multi_parcel_dimensions': []}
        self.assertEqual(self.engine.invoice.compare(line, shipment), compare_line(line, shipment))
        self.assertEqual(self.engine.runtime.usage['model_calls'], 0)

    async def test_document_fallback_citations_and_cache_are_local(self):
        response = await self.engine.help.answer(self.context, 'wallet card payment')
        self.assertEqual(response['mode'], 'DOCUMENT_EXCERPTS')
        self.assertEqual(response['fallback_reason'], 'AI_NOT_CONFIGURED')
        self.assertEqual(response['excerpts'], [])
        self.assertIn('From the EasyInvio Help Centre:', response['answer'])
        self.assertGreater(len(response['answer']), 200)
        self.assertNotIn('closest available information', response['answer'])
        self.assertTrue(response['sources'])
        self.assertTrue(all(source['url'].startswith('/help/') for source in response['sources']))
        cached = await self.engine.help.answer(self.context, 'wallet card payment')
        self.assertTrue(cached['cached'])
        another = await self.engine.help.answer(context(), 'wallet card payment')
        self.assertFalse(another['cached'])

    async def test_no_evidence_has_no_fabricated_answer(self):
        response = await self.engine.help.answer(self.context, 'zzqqqzzzxxxx')
        self.assertEqual(response['mode'], 'NO_EVIDENCE')
        self.assertEqual(response['sources'], [])

    async def test_unknown_generated_citation_falls_back(self):
        runtime = AgentRuntime(settings(True), client=SimpleNamespace())
        retriever = HelpRetriever(runtime)
        chunks, version = retriever.corpus()
        retriever.index = AsyncMock(return_value=[[1.] + [0.] * 255 for _ in chunks])
        runtime.embed = AsyncMock(return_value=[[1.] + [0.] * 255])
        runtime.run = AsyncMock(return_value=ModelResult(CitedAnswer(answer='invented', chunk_ids=['nonexistent'], insufficient_evidence=False), 20, 10, 0))
        response = await retriever.answer(self.context, 'wallet payment')
        self.assertNotEqual(response['answer'], 'invented')
        self.assertNotEqual(response['mode'], 'AI_CITED_ANSWER')
        self.assertEqual(response['fallback_reason'], 'UNSUPPORTED_CITATIONS')

    async def test_html_guides_have_section_citations_and_complete_wallet_rule(self):
        chunks, version = self.engine.help.corpus()
        wallet = next(chunk for chunk in chunks if chunk.url == '/help/booking-payments#wallet-charge')
        self.assertIn('only after the shipping service confirms', wallet.text)
        self.assertIn('first reserves', wallet.text)
        self.assertNotIn('Two ways to pay', wallet.text)
        from html.parser import HTMLParser
        from backend.help_center import GUIDES
        class IDs(HTMLParser):
            def __init__(self):
                super().__init__()
                self.values = set()
            def handle_starttag(self, tag, attrs):
                identity = dict(attrs).get('id')
                if identity:
                    self.values.add(identity)
        for chunk in chunks:
            if chunk.source_file is None and '#' in chunk.url:
                slug, fragment = chunk.url.removeprefix('/help/').split('#', 1)
                parser = IDs()
                parser.feed(GUIDES[slug].body)
                self.assertIn(fragment, parser.values)

    async def test_embedding_outage_still_generates_from_retrieved_docs(self):
        runtime = AgentRuntime(settings(True), client=SimpleNamespace())
        retriever = HelpRetriever(runtime)
        retriever.index = AsyncMock(side_effect=HTTPException(503, 'Unavailable'))
        async def generate(tenant, worker, instructions, payload, output_type=None):
            identity = payload['chunks'][0]['id']
            return ModelResult(CitedAnswer(answer='Credit is reserved first and charged after label confirmation.',
                chunk_ids=[identity], insufficient_evidence=False), 20, 10, 0)
        runtime.run = AsyncMock(side_effect=generate)
        response = await retriever.answer(self.context, 'When is my wallet charged?')
        self.assertEqual(response['mode'], 'AI_CITED_ANSWER')
        self.assertEqual(response['retrieval'], 'KEYWORD')
        self.assertIsNone(response['fallback_reason'])
        runtime.run.assert_awaited_once()

    async def test_failed_generation_is_not_cached_over_recovery(self):
        runtime = AgentRuntime(settings(True), client=SimpleNamespace())
        retriever = HelpRetriever(runtime)
        retriever.index = AsyncMock(side_effect=HTTPException(503, 'Unavailable'))
        runtime.run = AsyncMock(side_effect=HTTPException(503, 'Temporarily unavailable'))
        result = await retriever.answer(self.context, 'When is my wallet charged?')
        self.assertEqual(result['fallback_reason'], 'ANSWER_UNAVAILABLE')
        await retriever.answer(self.context, 'When is my wallet charged?')
        self.assertEqual(runtime.run.await_count, 2)

    async def test_insufficient_evidence_is_not_misreported_as_bad_citation(self):
        runtime = AgentRuntime(settings(True), client=SimpleNamespace())
        retriever = HelpRetriever(runtime)
        retriever.index = AsyncMock(side_effect=HTTPException(503, 'Unavailable'))
        runtime.run = AsyncMock(return_value=ModelResult(CitedAnswer(answer='Not enough evidence',
            chunk_ids=[], insufficient_evidence=True), 20, 10, 0))
        result = await retriever.answer(self.context, 'wallet payments')
        self.assertEqual(result['fallback_reason'], 'INSUFFICIENT_EVIDENCE')
        self.assertNotEqual(result['mode'], 'AI_CITED_ANSWER')

    async def test_public_index_cache_has_no_customer_questions(self):
        runtime = AgentRuntime(settings(True), client=SimpleNamespace())
        async def vectors(tenant, texts):
            return [[1.] + [0.] * 255 for _ in texts]
        runtime.embed = AsyncMock(side_effect=vectors)
        with tempfile.TemporaryDirectory() as directory:
            retriever = HelpRetriever(runtime, directory)
            chunks, version = retriever.corpus()
            await retriever.index(self.context.tenant_id, chunks, version)
            await retriever.index(context().tenant_id, chunks, version)
            runtime.embed.assert_awaited_once()
            from pathlib import Path
            payload = json.loads(next(Path(directory).glob('*.json')).read_text())
            self.assertEqual(set(payload), {'ids', 'vectors'})

    async def test_sdk_has_one_turn_no_tracing_no_purchase_tools_and_cache(self):
        runtime = AgentRuntime(settings(True), client=SimpleNamespace())
        usage = SimpleNamespace(input_tokens=30, output_tokens=10, input_tokens_details=SimpleNamespace(cached_tokens=5))
        returned = CitedAnswer(answer='Read the guide', chunk_ids=['known'], insufficient_evidence=False)
        fake = SimpleNamespace(final_output=returned, context_wrapper=SimpleNamespace(usage=usage))
        with patch('backend.agents.runtime.Runner.run', new=AsyncMock(return_value=fake)) as runner:
            result = await runtime.run(self.context.tenant_id, 'Help', 'Only docs', {'query': 'wallet'}, output_type=CitedAnswer)
            cached = await runtime.run(self.context.tenant_id, 'Help', 'Only docs', {'query': 'wallet'}, output_type=CitedAnswer)
            runner.assert_awaited_once()
            agent = runner.call_args.args[0]
            self.assertEqual(agent.tools, [])
            self.assertFalse(agent.model_settings.store)
            self.assertTrue(runner.call_args.kwargs['run_config'].tracing_disabled)
            self.assertEqual(runner.call_args.kwargs['max_turns'], 1)
            self.assertEqual((result.input_tokens, result.output_tokens, cached.input_tokens), (30, 10, 0))
            self.assertEqual(runtime.usage['cached_input_tokens'], 5)

    async def test_sdk_failure_is_bounded_and_no_retry(self):
        runtime = AgentRuntime(settings(True), client=SimpleNamespace())
        with patch('backend.agents.runtime.Runner.run', new=AsyncMock(side_effect=RuntimeError('private content'))) as runner:
            with self.assertRaises(HTTPException) as raised:
                await runtime.run(self.context.tenant_id, 'Help', 'Only docs', {'query': 'wallet'}, output_type=CitedAnswer)
            self.assertNotIn('private content', raised.exception.detail)
            runner.assert_awaited_once()

    async def test_rate_limit_rejects_before_sdk(self):
        runtime = AgentRuntime(settings(True, logistics_agent_requests_per_minute=1), client=SimpleNamespace())
        runtime.reserve(self.context.tenant_id, 1)
        with patch('backend.agents.runtime.Runner.run', new=AsyncMock()) as runner:
            with self.assertRaises(HTTPException) as raised:
                await runtime.run(self.context.tenant_id, 'Help', 'Only docs', {'query': 'wallet'})
            self.assertEqual(raised.exception.status_code, 429)
            runner.assert_not_awaited()

    async def test_real_sdk_executes_one_read_only_tool_with_mock_http(self):
        import httpx2
        from openai import AsyncOpenAI
        requests = []
        intent = {'intent': 'QUOTE', 'weight_kg': '5', 'origin_country': 'GB', 'destination_country': 'FR', 'route_code': None}
        def respond(request):
            payload = json.loads(request.content)
            requests.append(payload)
            return httpx2.Response(200, json={'id': 'resp_test', 'object': 'response', 'created_at': 1,
                'model': 'gpt-4o-mini', 'status': 'completed',
                'output': [{'id': 'fc_test', 'type': 'function_call', 'call_id': 'call_test', 'name': 'submit_quote_intent',
                    'arguments': json.dumps({'intent': intent}), 'status': 'completed'}],
                'usage': {'input_tokens': 30, 'output_tokens': 10, 'total_tokens': 40,
                    'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}})
        client = AsyncOpenAI(api_key='test-only', max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)))
        runtime = AgentRuntime(settings(True), client=client)
        try:
            engine = LogisticsSupervisor(runtime=runtime)
            result = await engine.ingestion.message(self.context, 'I have 5kg to send from Britain to France')
            self.assertEqual(result.weight_kg, '5')
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]['tool_choice'], 'required')
            self.assertFalse(requests[0]['store'])
            self.assertEqual([tool['name'] for tool in requests[0]['tools']], ['submit_quote_intent'])
            self.assertEqual(runtime.usage['input_tokens'], 30)
        finally:
            await runtime.close()

    async def test_real_sdk_structured_answer_with_mock_http(self):
        import httpx2
        from openai import AsyncOpenAI
        requests = []
        def respond(request):
            payload = json.loads(request.content)
            requests.append(payload)
            answer = {'answer': 'Review the guide.', 'chunk_ids': ['known'], 'insufficient_evidence': False}
            return httpx2.Response(200, json={'id': 'resp_test', 'object': 'response', 'created_at': 1,
                'model': 'gpt-4o-mini', 'status': 'completed',
                'output': [{'id': 'msg_test', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                    'content': [{'type': 'output_text', 'text': json.dumps(answer), 'annotations': []}]}],
                'usage': {'input_tokens': 30, 'output_tokens': 10, 'total_tokens': 40,
                    'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}})
        client = AsyncOpenAI(api_key='test-only', max_retries=0,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)))
        runtime = AgentRuntime(settings(True), client=client)
        try:
            result = await runtime.run(self.context.tenant_id, 'Help', 'Use the guide', {'question': 'wallet'}, output_type=CitedAnswer)
            self.assertEqual(result.value.chunk_ids, ['known'])
            self.assertEqual(requests[0]['text']['format']['type'], 'json_schema')
            self.assertTrue(requests[0]['text']['format']['strict'])
        finally:
            await runtime.close()


class BoundaryTests(unittest.TestCase):
    def test_invalid_transition_and_redaction(self):
        with self.assertRaises(ValueError):
            Workflow().move(State.EXECUTING)
        value = redacted_question('Email person@example.com +447123456789 ' + str(uuid4()))
        self.assertNotIn('person@example.com', value)
        self.assertNotIn('+447123456789', value)

    def test_missing_auth_does_not_call_agent(self):
        async def auth():
            raise HTTPException(401, 'Sign in')
        app = FastAPI()
        from main import RatingRequest
        app.include_router(build_router(auth, RatingRequest, auth))
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/v1/help/search-agent', json={'query': 'wallet payments'}).status_code, 401)
            self.assertEqual(client.get('/api/v1/admin/agents/metrics').status_code, 401)


if __name__ == '__main__':
    unittest.main()
