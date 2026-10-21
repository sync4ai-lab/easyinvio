"""Offline safety contracts. These fixtures are not carrier certification evidence."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from main import CarrierAccount, ClientRate, ProviderFailure, RatingRequest, RatingService, WholesaleRate
from backend.adapters import DirectRegistration
from backend.adapters.direct_contract import DirectParcel
from backend.adapters.royal_mail_adapter import RoyalMailStrategy
from backend.adapters.evri_adapter import EvriStrategy
from backend.automation_freight_engine import EasyPostPurchase, PurchaseRejected, PurchaseUncertain
from backend.automation_three_partners import EasyPostAdapter
from backend.carrier_consolidation import consolidate_rates
from backend.integration_policy import IntegrationSettings, integration_enabled
from backend.label_availability import label_availability
from backend.provider_routing import run_tiered_providers
from tests.test_logistics import payload


DIRECT_ENDPOINT = 'https://certified-carrier.example.test'


def request():
    body = payload()
    body['destination'] = {**body['origin'], 'name': 'Recipient'}
    return RatingRequest.model_validate(body)


def account(endpoint=DIRECT_ENDPOINT):
    return CarrierAccount(uuid4(), uuid4(), 'REGIONAL', endpoint, None, 5, 'offline-only')


def wholesale(owner, carrier='ROYALMAIL', service='TRACKED48'):
    return WholesaleRate(provider='REGIONAL', account_id=owner.id,
                         upstream_shipment_id='test-shipment', upstream_rate_id='test-rate',
                         carrier_code=carrier, service_code=service, currency='GBP', wholesale_cost='2.40')


def registration():
    return patch('backend.adapters.DIRECT_REGISTRATIONS',
                 (DirectRegistration('royal_mail', DIRECT_ENDPOINT, RoyalMailStrategy),))


def test_defaults_and_sendcloud_versions_share_switch():
    policy = IntegrationSettings(_env_file=None)
    assert not policy.integration_royal_mail_enabled
    assert not policy.integration_evri_enabled
    policy.integration_sendcloud_enabled = False
    for version in ('v2', 'v3'):
        assert not integration_enabled(f'https://panel.sendcloud.sc/api/{version}', policy)
    assert integration_enabled('https://api.easypost.com/v2', policy)
    assert not integration_enabled('https://api.royalmail.net/shipping/v3', policy)
    assert not integration_enabled('https://api.evri.com', policy)
    with registration():
        assert not integration_enabled(DIRECT_ENDPOINT, policy)


@pytest.mark.asyncio
async def test_disabled_adapters_and_enabled_without_contract_never_call_http():
    client = SimpleNamespace(stream=AsyncMock())
    for strategy_type in (RoyalMailStrategy, EvriStrategy):
        strategy = strategy_type(client, account(), settings=IntegrationSettings(_env_file=None))
        with pytest.raises(ProviderFailure, match='DIRECT_CARRIER_DISABLED'):
            await strategy.rates(request())
        setattr(strategy.settings, f'integration_{strategy.policy_code}_enabled', True)
        with pytest.raises(ProviderFailure, match='CONTRACT_NOT_CONFIGURED'):
            await strategy.rates(request())
    client.stream.assert_not_called()


@pytest.mark.asyncio
async def test_native_transport_identity_and_physical_mass():
    owner = account()
    contract = SimpleNamespace(quote=AsyncMock(return_value=[wholesale(owner)]))
    strategy = RoyalMailStrategy(None, owner, settings=SimpleNamespace(integration_royal_mail_enabled=True), contract=contract)
    rates = await strategy.rates(request())
    assert rates[0].execution_details['direct_carrier'] == 'ROYALMAIL'
    parcel = contract.quote.call_args.args[1]
    assert parcel.weight_grams == 2500
    assert parcel.length_cm == Decimal('40')
    contract.quote.return_value = [wholesale(account())]
    with pytest.raises(ProviderFailure, match='IDENTITY_MISMATCH'):
        await strategy.rates(request())


@pytest.mark.asyncio
async def test_native_label_rejects_missing_paf_without_purchase():
    contract = SimpleNamespace(purchase_label=AsyncMock())
    strategy = RoyalMailStrategy(None, account(), settings=SimpleNamespace(integration_royal_mail_enabled=True), contract=contract)
    with pytest.raises(ProviderFailure, match='PAF_RECIPIENT_REQUIRED'):
        await strategy.purchase_label({'destination': request().destination.model_dump()})
    contract.purchase_label.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_post_submission_documents_preserve_unknown_outcome():
    contract = SimpleNamespace(
        purchase_label=AsyncMock(return_value={'tracking_number': 'real-reference', 'provider_reference': 'receipt',
                                               'format': 'PDF', 'document': b'not a PDF'}),
        create_manifest=AsyncMock(return_value={'provider_reference': 'receipt', 'document_pdf': b'not a PDF'}),
    )
    strategy = RoyalMailStrategy(None, account(), settings=SimpleNamespace(integration_royal_mail_enabled=True), contract=contract)
    paf = {'premise': '10', 'thoroughfare': 'Downing Street', 'post_town': 'LONDON',
           'postcode': 'SW1A 2AA', 'udprn': '12345678'}
    with pytest.raises(PurchaseUncertain, match='DIRECT_LABEL_RESPONSE_REQUIRES_RECONCILIATION'):
        await strategy.purchase_label({'recipient_paf': paf})
    with pytest.raises(PurchaseUncertain, match='DIRECT_MANIFEST_RESPONSE_REQUIRES_RECONCILIATION'):
        await strategy.create_manifest('issued-account')
    contract.purchase_label.assert_awaited_once()
    contract.create_manifest.assert_awaited_once()


def test_international_and_missing_dimensions_fail_closed():
    with pytest.raises(ProviderFailure, match='DOMESTIC_SINGLE_PIECE_REQUIRED'):
        DirectParcel.from_rating(RatingRequest.model_validate(payload()))
    parcel = DirectParcel.from_rating(request())
    assert not EvriStrategy.postable_height_candidate(parcel)
    assert EvriStrategy.postable_height_candidate(parcel.model_copy(update={'height_cm': Decimal('3')}))
    with pytest.raises(ProviderFailure, match='INVALID_CARRIER_DROPOFF_ASSET'):
        EvriStrategy.extract_dropoff_barcode('1234567890123456', b'not a carrier image')


@pytest.mark.asyncio
async def test_disabled_provider_blocks_legacy_and_native_writes_but_allows_recovery_reads(monkeypatch):
    monkeypatch.setenv('INTEGRATION_EASYPOST_ENABLED', 'false')
    calls = []
    def handle(req):
        calls.append(req.method)
        return httpx.Response(200, json={'id': 'historical'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = EasyPostAdapter(client, 'offline', environment='TEST')
        legacy = EasyPostPurchase(client)
        with pytest.raises(PurchaseRejected, match='PROVIDER_DISABLED'):
            await adapter.request('POST', '/shipments', {})
        with pytest.raises(PurchaseRejected, match='PROVIDER_DISABLED'):
            await legacy.request(account('https://api.easypost.com/v2'), '/shipments/x/buy', 'POST', {})
        assert await adapter.request('GET', '/shipments/historical') == {'id': 'historical'}
    assert calls == ['GET']


def test_disabled_cached_quote_is_not_payable():
    rate = SimpleNamespace(execution_details={'account_endpoint': 'https://panel.sendcloud.sc/api/v3'})
    available, notice = label_availability(SimpleNamespace(integration_sendcloud_enabled=False), rate)
    assert not available and 'disabled' in notice


@pytest.mark.asyncio
async def test_direct_first_budget_then_retains_other_aggregator_services():
    direct = SimpleNamespace(account=account())
    fallback = SimpleNamespace(account=account('https://api.easypost.com/v2'))
    physical, billed = request(), object()
    order = []
    async def run(strategy, received, deadline):
        assert received is physical
        order.append(strategy)
        if strategy is direct:
            assert deadline == 2.2
            return [wholesale(direct.account)], None
        assert order == [direct, fallback]
        return [wholesale(fallback.account), wholesale(fallback.account, 'EVRI', 'STANDARD')], None
    with registration():
        results = await run_tiered_providers([fallback, direct], physical, billed, run, 7)
    assert [r.carrier_code for rates, _ in results for r in rates] == ['ROYALMAIL', 'EVRI']


@pytest.mark.asyncio
async def test_real_run_provider_timeout_then_fallback():
    direct = SimpleNamespace(account=account(), rates=AsyncMock(side_effect=lambda _: asyncio.sleep(10)))
    async def slow(_):
        await asyncio.sleep(10)
    direct.rates = slow
    fallback = SimpleNamespace(account=account('https://api.easypost.com/v2'), rates=AsyncMock(return_value=[]))
    service = RatingService(None, None, SimpleNamespace(max_parallel_provider_requests=2, integration_royal_mail_enabled=True))
    async def short(strategy, req, deadline):
        return await service.run_provider(strategy, req, min(deadline, 0.01))
    with registration():
        results = await run_tiered_providers([direct, fallback], request(), request(), short, 5)
    assert results[0][1].code == 'UPSTREAM_TIMEOUT'
    fallback.rates.assert_awaited_once()


def test_native_equal_price_wins_only_for_registered_endpoint_in_any_order():
    def rate(endpoint, cost):
        return ClientRate(provider='REGIONAL', account_id=uuid4(), upstream_shipment_id='fixture',
                          upstream_rate_id=str(uuid4()), carrier_code='ROYALMAIL', service_code='TRACKED48',
                          currency='GBP', client_price_ex_tax='4.00', delivery_days=2, fee_breakdown={'wholesale_total': cost},
                          execution_details={'account_endpoint': endpoint, 'direct_carrier': 'ROYALMAIL'})
    native, broker = rate(DIRECT_ENDPOINT, '3.00'), rate('https://api.easypost.com/v2', '2.00')
    with registration():
        assert consolidate_rates([native, broker]) == [native]
        assert consolidate_rates([broker, native]) == [native]
    assert consolidate_rates([native, broker]) == [broker]
