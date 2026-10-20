"""Route-free chat turns use real domain boundaries and isolated fake providers."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

import main
from test_conversational_gateway import fixture, message
from backend.agents.conversational_gateway import ConversationalActionGateway, ConversationMessage
from backend.agents.conversation_context import ConversationDraft, explicit_quote
from backend.agents.models import ConversationalIntent
from backend.conversational_claims import complete_conversational_claim


def quote_result():
    now = datetime.now(timezone.utc)
    return main.RatingResponse(request_id=uuid4(), currency='GBP', quoted_at=now,
        expires_at=now + timedelta(minutes=5), partial=False, issues=[], rates=[main.ClientRate(
            provider='EASYPOST', account_id=uuid4(), upstream_shipment_id='private-shipment',
            upstream_rate_id='private-rate', carrier_code='TEST', service_code='PARCEL',
            currency='GBP', client_price_ex_tax='12.50', delivery_days=2)])


@pytest.mark.asyncio
@pytest.mark.parametrize('channel', ['WEB_CHAT', 'WHATSAPP'])
async def test_complete_dynamic_quote_survives_gateway_recreation_and_has_no_invented_data(fixture, channel):
    context, storage, state, gateway, app = fixture
    state.settings.twilio_whatsapp_number = '+14155238886'
    state.rating = SimpleNamespace(quote=AsyncMock(return_value=quote_result()))
    from backend.paf_lookup import PAFPremise
    state.paf = SimpleNamespace(lookup=AsyncMock(return_value=[PAFPremise(udprn='12345', postcode='LS1 2TW',
        line1='1 Real Road', post_town='Leeds', building_number='1')]))
    original_execute = storage.execute
    async def execute(sql, *args):
        if 'UPDATE public.whatsapp_bindings' in sql:
            return 'UPDATE 1'
        return await original_execute(sql, *args)
    storage.execute = execute
    def turn(text):
        return ConversationMessage(channel=channel, message_body=text,
            sender_id='+447700900123' if channel == 'WHATSAPP' else None)
    async def process(gateway, body):
        return await gateway.process(context, body, verified_whatsapp=channel == 'WHATSAPP')
    original = turn('Get a quote for a 3kg parcel from London to Paris')
    with patch('main.get_rates', AsyncMock(return_value=quote_result())) as rates:
        first = await process(gateway, original)
        assert first['status'] == 'NEEDS_INPUT' and 'Origin Postcode' in first['conversational_reply']
        assert '_pending' not in first
        assert first == await process(gateway, original)
        turns = [('LS1 2TW, 75001', 'countries')]
        turns += ([('GB, FR', 'premise number'), ('1', 'pickup contact'), ('Alex', 'dimensions'), ('30 x 20 x 10', 'delivery contact')]
            if channel == 'WHATSAPP' else [('GB, FR', 'dimensions'), ('30 x 20 x 10', 'pickup contact'), ('Alex; 1 Real Road; Leeds', 'delivery contact')])
        for text, prompt in turns:
            gateway = ConversationalActionGateway(gateway.request)
            result = await process(gateway, turn(text))
            assert prompt in result['conversational_reply']
            rates.assert_not_awaited()
        result = await process(gateway, turn('Jean; 2 Real Street; Paris'))
    rating = rates.await_args.args[0] if channel == 'WEB_CHAT' else state.rating.quote.await_args.args[1]
    assert rating.origin.line1 == '1 Real Road' and rating.destination.line1 == '2 Real Street'
    assert rating.origin.city == 'Leeds' and rating.destination.country_code == 'FR'
    assert rating.weights_kg == [Decimal('3')]
    assert rating.dimensions[0].length_cm == Decimal('30')
    assert not any('FROM public.whatsapp_routes' in sql for sql, _ in storage.calls)
    assert '12.50 GBP' in result['conversational_reply']
    assert '_choices' not in result and 'private-' not in json.dumps(result)
    state.partner_lifecycle.confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_postcodes_do_not_guess_countries_and_invalid_dimensions_keep_draft(fixture):
    context, storage, state, gateway, _ = fixture
    await gateway.process(context, message('Quote 5kg from LS1 2TW to 10115'))
    pending = json.loads(list(storage.rows.values())[-1]['response'])['_pending']
    assert pending['waiting_for'] == 'countries'
    assert pending['intent']['origin_country'] is None
    await gateway.process(context, message('GB, DE'))
    result = await gateway.process(context, message('0 x 20 x 10'))
    assert result['status'] == 'NEEDS_INPUT' and 'dimensions' in result['conversational_reply']
    pending = json.loads(list(storage.rows.values())[-1]['response'])['_pending']
    assert pending['intent']['weight_kg'] == '5' and pending['dimensions'] is None
    assert not storage.choices


@pytest.mark.asyncio
async def test_cancellation_expiry_and_channel_isolation_never_reuse_a_draft(fixture):
    context, storage, state, gateway, _ = fixture
    await gateway.process(context, message('Quote 3kg from London to Paris'))
    result = await gateway.process(context, message('Cancel'))
    assert 'cleared' in result['conversational_reply']
    assert (await gateway.process(context, message('LS1 2TW, 75001')))['action_taken'] == 'HELP'
    await gateway.process(context, message('Quote 3kg from London to Paris'))
    row = list(storage.rows.values())[-1]
    payload = json.loads(row['response'])
    payload['_pending']['expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    row['response'] = json.dumps(payload)
    assert (await gateway.process(context, message('LS1 2TW, 75001')))['action_taken'] == 'HELP'
    await gateway.process(context, message('Quote 3kg from London to Paris'))
    state.settings.twilio_whatsapp_number = '+14155238886'
    storage.writes.clear()
    # A separate signed-channel turn cannot consume the browser's draft.
    original_execute = storage.execute
    async def execute(sql, *args):
        if 'UPDATE public.whatsapp_bindings' in sql:
            return 'UPDATE 1'
        return await original_execute(sql, *args)
    storage.execute = execute
    result = await gateway.process(context, ConversationMessage(channel='WHATSAPP',
        sender_id='+447700900123', message_body='LS1 2TW, 75001'), verified_whatsapp=True)
    assert result['action_taken'] == 'HELP'


@pytest.mark.asyncio
async def test_tracking_and_claims_collect_references_without_rag_or_guessing(fixture):
    context, storage, state, gateway, _ = fixture
    result = await gateway.process(context, message('Where is my package?'))
    assert result['status'] == 'NEEDS_INPUT' and 'reference' in result['conversational_reply']
    result = await gateway.process(context, message('TEST123'))
    assert 'EXCEPTION' in result['conversational_reply']
    assert 'EXCEPTION' in (await gateway.process(context, message('Where is my package?')))['conversational_reply']
    state.settings.auth_recovery_redirect_url = 'https://easyinvio.com/set-password'
    await gateway.process(context, message('My package is lost'))
    body = message('TEST123')
    result = await gateway.process(context, body)
    assert result == await gateway.process(context, body)
    assert result['claim_panel_url'] == 'https://easyinvio.com/?claim_id=' + result['claim_id']
    assert len([sql for sql, _ in storage.writes if 'INSERT INTO public.insurance_claim_cases' in sql]) == 1
    assert not any('UPDATE public.shipments' in sql or 'wallet_ledger' in sql for sql, _ in storage.writes)


@pytest.mark.parametrize('text,weight,origin,destination', [
    ('Quote 5kg from LS1 2TW to 10115', '5', None, None),
    ('Get a quote for 3,5kg from London GB to Paris FR', '3.5', 'GB', 'FR'),
    ('Quote from UK to France', None, 'GB', 'FR'),
])
def test_explicit_location_extraction(text, weight, origin, destination):
    intent = explicit_quote(text)
    assert intent.weight_kg == weight and intent.origin_country == origin and intent.destination_country == destination


@pytest.mark.asyncio
async def test_chat_case_upgrade_checks_actor_and_cannot_replace_processed_evidence():
    context = main.TenantContext(uuid4(), uuid4(), 'OWNER', 'synthetic')
    connection = SimpleNamespace(fetchval=AsyncMock(side_effect=[context.user_id, None]), execute=AsyncMock())
    values = dict(case_id=uuid4(), shipment_id=uuid4(), policy_id='TEST', reason='PARCEL_LOST',
        notes='A reviewed loss description', old_digest='a'*64, digest='b'*64, state='SUBMISSION_PENDING',
        submission_payload={'reviewed': True}, photos=[(b'synthetic-image', 'image/png')])
    with patch('backend.shipment_protection.insured_shipment', AsyncMock()):
        assert not await complete_conversational_claim(connection, context, **values)
        connection.execute.assert_not_awaited()
        sql, args = connection.fetchval.await_args.args[0], connection.fetchval.await_args.args[1:]
        for boundary in ('c.tenant_id=$1', 'c.created_by=$5', 'upstream_claim_id IS NULL',
                         'NOT EXISTS', 'conversation-intake-v1', 'payload_sha256=$11'):
            assert boundary in sql
        assert args[0] == context.tenant_id and args[4] == context.user_id
        connection.fetchval.side_effect = [context.user_id, values['case_id']]
        assert await complete_conversational_claim(connection, context, **values)
    statements = [call.args[0] for call in connection.execute.await_args_list]
    assert sum('INSERT INTO public.insurance_claim_evidence' in sql for sql in statements) == 1
    assert any('conversation-completed-v1' in sql for sql in statements)
    assert not any('wallet' in sql for sql in statements)


@pytest.mark.asyncio
async def test_rate_outage_is_a_completed_readonly_turn_and_requires_explicit_retry(fixture):
    context, storage, state, gateway, _ = fixture
    intent = ConversationalIntent(intent='QUOTE', weight_kg='3', origin_country='GB', destination_country='GB',
        origin_postal_code='LS1 2TW', destination_postal_code='LS1 1AA')
    address = dict(name='Actual contact', line1='1 Real Road', city='Leeds', country_code='GB', postal_code='LS1 2TW')
    draft = ConversationDraft(action='QUOTE', intent=intent, waiting_for='retry', origin_address=address,
        destination_address={**address, 'postal_code': 'LS1 1AA'}, dimensions={'length_cm':'30','width_cm':'20','height_cm':'10'})
    storage.rows[uuid4()] = {'scope':(context.tenant_id,context.user_id,'WEB_CHAT'),'state':'COMPLETED',
        'response':json.dumps({'action_taken':'QUOTE','_pending':draft.model_dump(mode='json')})}
    with patch('main.get_rates', AsyncMock(side_effect=HTTPException(503, 'synthetic provider outage'))) as rates:
        body = message('Retry')
        result = await gateway.process(context, body)
        assert result['status'] == 'NEEDS_INPUT' and 'Reply Retry' in result['conversational_reply']
        assert result == await gateway.process(context, body)
        rates.assert_awaited_once()
    assert not any(row['state'] == 'PROCESSING' for row in storage.rows.values())
    with patch('main.get_rates', AsyncMock(return_value=quote_result())):
        assert (await gateway.process(context, message('Retry')))['status'] == 'COMPLETED'
    state.partner_lifecycle.confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_completion_refuses_an_inactive_actor_before_any_update():
    context = main.TenantContext(uuid4(), uuid4(), 'OWNER', 'synthetic')
    connection = SimpleNamespace(fetchval=AsyncMock(return_value=None), execute=AsyncMock())
    with patch('backend.shipment_protection.insured_shipment', AsyncMock()):
        with pytest.raises(HTTPException) as error:
            await complete_conversational_claim(connection, context, case_id=uuid4(), shipment_id=uuid4(), policy_id='TEST',
                reason='PARCEL_LOST', notes='A reviewed loss description', old_digest='a'*64, digest='b'*64,
                state='SUBMISSION_PENDING', submission_payload={}, photos=[])
    assert error.value.status_code == 403
    connection.execute.assert_not_awaited()
    connection.fetchval.assert_awaited_once()
