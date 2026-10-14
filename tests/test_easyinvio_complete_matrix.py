"""Master API/component matrix with isolated lifespan and explicit live smoke opt-in.

Default runs use production orchestration and financial arithmetic with synthetic
SQL/provider boundaries. They do not certify PostgreSQL RLS or carrier acceptance.
Set EASYINVIO_UAT_LIVE_LIFESPAN=1 only against a dedicated SANDBOX database to
run the additional configured-startup smoke test with real background workers.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException, Request

import main
from backend.agents.config import AgentSettings
from backend.automation_three_partners import (
    EasyPostAdapter, FactoryPurchaseBridge, NativePartnerService, PartnerLifecycleService,
)
from backend.shipment_protection import calculate_xcover_premium
from tests.uat_matrix_support import (
    MatrixPool, MatrixRepository, TENANT_A, TENANT_B, USER_A, wholesale_matrix,
)


FINANCIAL_SLABS = [
    ('20.00', '1.20', False),
    ('120.00', '1.20', False),
    ('120.50', '1.21', False),
    ('5000.00', '50.00', False),
    ('5000.01', '0.00', True),
    ('0.00', '0.00', True),
    ('-10.00', '0.00', True),
]
# Report seven distinct cases and 36 repetitions, not 252 distinct scenarios.
STRESS_TEST_MATRIX = FINANCIAL_SLABS * 36


@pytest.fixture
def valid_parcel_payload():
    return {
        'origin': {
            'name': 'Synthetic UAT Warehouse', 'company': 'Synthetic UAT Company',
            'line1': '1 Example Street', 'city': 'London',
            'postal_code': 'SW1A 1AA', 'country_code': 'GB',
        },
        'destination': {
            'name': 'Synthetic UAT Recipient', 'line1': '100 Example Avenue',
            'city': 'New York', 'state': 'NY', 'postal_code': '10001',
            'country_code': 'US',
        },
        'dimensions': [{'length_cm': '30.00', 'width_cm': '20.00', 'height_cm': '10.00'}],
        'weights_kg': ['2.000'], 'currency': 'GBP', 'cargo_type': 'PARCEL',
        'shipment_items': [{
            'description': 'Cotton T-shirt', 'quantity': 1,
            'unit_weight_kg': '1.000', 'unit_value': '15.00',
            'origin_country': 'GB', 'hs_code': '610910',
        }],
        'goods_currency': 'GBP',
    }


@pytest.fixture
def matrix_context():
    return main.TenantContext(TENANT_A, USER_A, 'OWNER', 'synthetic-test-context')


@pytest.fixture
def matrix_pool():
    return MatrixPool()


@pytest.fixture
def matrix_repository(matrix_pool):
    return MatrixRepository(matrix_pool)


@pytest.fixture
def provider_matrix(matrix_repository):
    return wholesale_matrix(matrix_repository)


@asynccontextmanager
async def db_pool_lifespan_context(application):
    """Enter the installed FastAPI lifespan explicitly; ASGITransport does not."""
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def authenticated_client(monkeypatch, matrix_pool, matrix_repository,
                               provider_matrix, matrix_context):
    """Execute real outer lifespan with controlled database/provider IO boundaries.

    No shared auth overrides or app state survive teardown, including assertion
    failures. The dedicated live smoke fixture below runs configured startup.
    """
    original_state = main.app.state._state.copy()
    original_overrides = main.app.dependency_overrides.copy()
    settings = SimpleNamespace(
        provider_environment='TEST', database_environment='SANDBOX',
        automation_purchase_enabled=True, provider_deadline_seconds=5,
        quote_ttl_seconds=300, max_parallel_provider_requests=3,
    )
    # Disable external model clients even if the developer's .env enables AI.
    def offline_agent_settings():
        return AgentSettings(_env_file=None, logistics_agents_enabled=False, openai_api_key='')

    monkeypatch.setattr('backend.agents.config.AgentSettings', offline_agent_settings)

    @asynccontextmanager
    async def controlled_services(application):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(599, json={'error': 'Unexpected provider IO'}))) as http:
            matrix_pool.started = True
            try:
                application.state.local_preview = False
                application.state.settings = settings
                application.state.repository = matrix_repository
                application.state.rating = main.RatingService(http, matrix_repository, settings, pool=matrix_pool)
                application.state.finance = main.FinanceEngine(matrix_pool, settings, None)
                automation = SimpleNamespace(
                    pool=matrix_pool, finance=application.state.finance,
                    repository=matrix_repository, settings=settings,
                    order_limiter=asyncio.Semaphore(2), native_orders=None,
                )
                application.state.partner_lifecycle = PartnerLifecycleService(automation, http)
                application.state.native_partners = NativePartnerService(automation, http, None)
                yield
            finally:
                await matrix_pool.close()

    async def provider_results(service, strategy, body, deadline):
        await asyncio.sleep(0)
        return provider_matrix[strategy.account.id], None

    async def verified_fixture_context(request: Request):
        # Deliberately exercise the real query guard while isolating JWT IO.
        main.validate_tenant_query(request, matrix_context.tenant_id)
        request.state.workspace_role = matrix_context.role
        return matrix_context

    monkeypatch.setattr(main, 'deterministic_lifespan', controlled_services)
    monkeypatch.setattr(main.RatingService, 'run_provider', provider_results)
    try:
        async with db_pool_lifespan_context(main.app) as managed_app:
            managed_app.dependency_overrides[main.authenticate] = verified_fixture_context
            async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=managed_app), base_url='http://test') as client:
                yield client
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(original_overrides)
        main.app.state._state.clear()
        main.app.state._state.update(original_state)
        assert matrix_pool.closed, 'Managed services did not tear down'


@pytest.mark.asyncio
@pytest.mark.parametrize('declared_val,expected_premium,should_raise', STRESS_TEST_MATRIX)
async def test_xcover_insurance_quantization_and_liability_matrix(declared_val, expected_premium, should_raise):
    value = Decimal(declared_val)
    if should_raise:
        with pytest.raises(HTTPException) as error:
            await calculate_xcover_premium(value)
        assert error.value.status_code == 400
        expected_message = 'maximum system protection liability cap' if value > 5000 else 'greater than zero'
        assert expected_message in error.value.detail
        return
    result = await calculate_xcover_premium(value)
    assert result['currency'] == 'GBP'
    assert result['premium_estimate'] == expected_premium
    assert Decimal(result['premium_estimate']).as_tuple().exponent == -2
    assert result['insured'] is False
    assert result['available'] is False
    assert result['wholesale_cost'] is None
    assert result['profit_margin'] is None
    assert result['tax_assessed'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [True, False, 120.5, 'NaN', 'Infinity', '-Infinity', 'bad'])
async def test_estimator_rejects_invalid_decimal_inputs(value):
    with pytest.raises(HTTPException) as error:
        await calculate_xcover_premium(value)
    assert error.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize('value,premium', [('119.99', '1.20'), ('120.49', '1.20'), ('120.51', '1.21')])
async def test_distinct_rounding_boundaries(value, premium):
    assert (await calculate_xcover_premium(Decimal(value)))['premium_estimate'] == premium


def assert_public_rates(value):
    private = {
        'provider', 'aggregator', 'account_id', 'carrier_account_id',
        'platform_connection_id', 'upstream_shipment_id', 'upstream_rate_id',
        'execution_details', 'wholesale_total', 'platform_markup',
    }
    if isinstance(value, dict):
        assert not private.intersection(value), f'Private keys disclosed: {private.intersection(value)}'
        for child in value.values():
            assert_public_rates(child)
    elif isinstance(value, list):
        for child in value:
            assert_public_rates(child)


@pytest.mark.asyncio
async def test_top_10_profit_maximizer_route_ingestion(authenticated_client, valid_parcel_payload,
                                                       matrix_pool, matrix_repository, provider_matrix):
    main.RatingRequest.model_validate(valid_parcel_payload)
    response = await authenticated_client.post('/v1/rates', json=valid_parcel_payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert_public_rates(data)
    assert 0 < len(data['rates']) <= 10
    assert len(data['rates']) == 10
    identities = [(rate['carrier_code'], rate['service_code'], rate['currency']) for rate in data['rates']]
    assert len(set(identities)) == len(identities)
    prices = [Decimal(rate['client_price_ex_tax']) for rate in data['rates']]
    assert prices == sorted(prices)
    # Every account supplied the same 12 tiers. A 20% margin means the most
    # expensive wholesale duplicate has the greatest absolute contribution.
    winning_account = matrix_repository.account_list[-1]
    expected = [Decimal(12 + index) * Decimal('1.20') for index in range(10)]
    assert prices == expected
    assert len(matrix_pool.quotes) == 1
    private_rates = matrix_pool.quotes[0]['rates']
    assert all(rate['account_id'] == str(winning_account.id) for rate in private_rates)
    assert all(rate['upstream_rate_id'].startswith('private_rate_2_') for rate in private_rates)
    assert [rate['service_code'] for rate in private_rates] == [f'TIER{index:02d}' for index in range(10)]
    assert all(rate['recommendation_badge'] is None for rate in data['rates'])
    assert main.app.state.logistics_supervisor.runtime.usage['model_calls'] == 0


@pytest.mark.asyncio
async def test_fewer_than_ten_offers_are_all_retained(authenticated_client, valid_parcel_payload, provider_matrix):
    for rates in provider_matrix.values():
        del rates[2:]
    response = await authenticated_client.post('/v1/rates', json=valid_parcel_payload)
    assert response.status_code == 200, response.text
    assert len(response.json()['rates']) == 2


@pytest.mark.asyncio
async def test_cross_tenant_parameter_tampering_isolation_fence(authenticated_client, matrix_pool):
    before = len(matrix_pool.calls)
    response = await authenticated_client.get(f'/api/v1/shipping/native-orders?tenant_id={TENANT_B}')
    assert response.status_code == 403, response.text
    assert len(matrix_pool.calls) == before, 'Rejected query reached the database'


@pytest.mark.parametrize('query', [f'tenant_id={TENANT_B}', 'tenant_id=not-a-uuid',
                                 f'tenant_id={TENANT_A}&tenant_id={TENANT_A}'])
def test_validate_tenant_query_directly(query):
    request = Request({'type': 'http', 'query_string': query.encode(), 'headers': []})
    with pytest.raises(HTTPException) as error:
        main.validate_tenant_query(request, TENANT_A)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_native_orders_only_use_verified_tenant(authenticated_client, matrix_pool):
    response = await authenticated_client.get(f'/api/v1/shipping/native-orders?tenant_id={TENANT_A}')
    assert response.status_code == 200, response.text
    assert response.json()['orders'] == matrix_pool.native_rows[TENANT_A]
    assert 'B_PRIVATE' not in response.text
    native_calls = [(sql, args) for sql, args in matrix_pool.calls if 'public.partner_order_jobs' in sql]
    assert len(native_calls) == 1
    assert native_calls[0][1] == (TENANT_A,)


@pytest.mark.asyncio
async def test_concurrent_booking_commits_once(authenticated_client, matrix_pool, monkeypatch):
    pool = matrix_pool
    # The provider boundary is blocked until the second request actually
    # contends on the production lifecycle's stored idempotency/advisory key.
    async def buy(bridge, account, rate):
        assert rate.offer_id == pool.rate.offer_id
        pool.purchase_entered.set()
        await pool.purchase_release.wait()
        return {'tracking_number': 'SYNTHETIC-UAT-TRACK',
                'label_url': 'https://files.example.invalid/label.pdf', 'carrier_forms': []}

    purchase = AsyncMock(side_effect=buy)
    async def purchase_boundary(bridge, account, rate):
        return await purchase(bridge, account, rate)
    monkeypatch.setattr(FactoryPurchaseBridge, 'buy', purchase_boundary)
    monkeypatch.setattr('backend.automation_three_partners.create_adapter',
                        lambda *args, **kwargs: object.__new__(EasyPostAdapter))
    queue = AsyncMock(return_value=None)
    monkeypatch.setattr(main.EcommerceService, 'queue_confirmed_tracking', queue)
    payload = {'tenant_id': str(TENANT_A), 'offer_id': str(pool.rate.offer_id)}
    first = asyncio.create_task(authenticated_client.post('/api/v1/shipping/confirm-booking', json=payload))
    second = None
    try:
        async with asyncio.timeout(5):
            await pool.purchase_entered.wait()
            second = asyncio.create_task(authenticated_client.post('/api/v1/shipping/confirm-booking', json=payload))
            await pool.contended.wait()
            conflict = await second
            assert conflict.status_code == 409, conflict.text
            pool.purchase_release.set()
            success = await first
    finally:
        pool.purchase_release.set()
        pending = [task for task in (first, second) if task is not None]
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    assert success.status_code == 200, success.text
    assert success.json()['status'] == 'BOOKED'
    assert purchase.await_count == 1
    assert pool.reservation['status'] == 'CAPTURED'
    assert pool.balance == Decimal('88.00')
    assert pool.reserved == Decimal('0.00')
    assert [entry['type'] for entry in pool.ledger] == ['RESERVE', 'CAPTURE']
    assert sum((entry['balance_delta'] for entry in pool.ledger), Decimal(0)) == Decimal('-12.00')
    assert sum((entry['reserved_delta'] for entry in pool.ledger), Decimal(0)) == 0
    assert len({entry['reservation_id'] for entry in pool.ledger}) == 1
    assert pool.commits == 3  # reserve, submitted, captured; not a second booking
    assert not pool.advisory
    queue.assert_awaited_once()
    retry = await authenticated_client.post('/api/v1/shipping/confirm-booking', json=payload)
    assert retry.status_code == 200, retry.text
    assert retry.json()['replayed'] is True
    assert purchase.await_count == 1
    assert pool.balance == Decimal('88.00')
    assert len(pool.ledger) == 2


@pytest.mark.asyncio
async def test_volumetric_weight_overrides_actual_mass(authenticated_client, valid_parcel_payload):
    response = await authenticated_client.post('/api/v1/logistics/weight', json={
        'length_cm': '50', 'width_cm': '40', 'height_cm': '30', 'actual_weight_kg': '1.5',
    })
    assert response.status_code == 200, response.text
    assert Decimal(response.json()['billable_weight_kg']) == Decimal('12.000')
    valid_parcel_payload['dimensions'] = [{'length_cm': '50', 'width_cm': '40', 'height_cm': '30'}]
    valid_parcel_payload['weights_kg'] = ['1.500']
    quote = await authenticated_client.post('/v1/rates', json=valid_parcel_payload)
    assert quote.status_code == 200, quote.text
    assert Decimal(quote.json()['weight']['billable_weight_kg']) == Decimal('12.000')
    for rate in quote.json()['rates']:
        assert Decimal(rate['package_weight_summary']['billable_weight_kg']) == Decimal('12.000')


@pytest.mark.asyncio
@pytest.mark.parametrize('message', ['4,5kg from GB to US', 'Quote 4,5kg from GBR to USA',
                                    'Quote 4.5kg from GB to US'])
async def test_comma_normalizer_uses_deterministic_parser(authenticated_client, message):
    response = await authenticated_client.post('/api/v1/agents/interpret', json={'text': message})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['intent']['intent'] == 'QUOTE'
    assert Decimal(result['intent']['weight_kg']) == Decimal('4.5')
    assert result['intent']['origin_country'] == 'GB'
    assert result['intent']['destination_country'] == 'US'
    assert result['booking_authorized'] is False
    assert main.app.state.logistics_supervisor.runtime.usage['model_calls'] == 0


@pytest.mark.parametrize('message', ['4,500.5kg from GB to US', '4,5,6kg from GB to US',
                                    '-4,5kg from GB to US', '0,0kg from GB to US',
                                    '1000,001kg from GB to US', '4,5kg from XX to US'])
def test_comma_normalizer_rejects_ambiguous_or_invalid_input(message):
    with pytest.raises(ValueError):
        main.parse_quote(message)


@pytest_asyncio.fixture
async def configured_lifespan_client():
    """Explicit opt-in: run actual pools, registry and configured background workers.

    This may process pre-existing sandbox queues. It is not used by the synthetic
    financial matrix and must only target a dedicated UAT database.
    """
    if os.getenv('EASYINVIO_UAT_LIVE_LIFESPAN') != '1':
        pytest.skip('Configured lifespan smoke requires EASYINVIO_UAT_LIVE_LIFESPAN=1')
    settings = main.Settings()
    assert settings.database_environment == 'SANDBOX', 'Dedicated SANDBOX database required'
    assert settings.provider_environment == 'TEST', 'TEST carrier environment required'
    assert not settings.stripe_livemode, 'Live Stripe mode is forbidden in UAT'
    tenant = UUID(os.environ['EASYINVIO_UAT_TENANT_ID'])
    user = UUID(os.environ['EASYINVIO_UAT_AUTH_USER_ID'])
    assert tenant != UUID('b9f5260c-3f03-42d5-8753-84690af5f647'), 'Use a dedicated UAT tenant'
    # Validate fixtures before startup can run any background workers.
    import asyncpg
    connection = await asyncpg.connect(
        settings.database_url.get_secret_value(),
        ssl=main.database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict),
    )
    try:
        row = await connection.fetchrow('''SELECT t.is_sandbox,t.workspace_status,u.role
            FROM public.tenants t JOIN public.users u ON u.tenant_id=t.tenant_id
            WHERE t.tenant_id=$1 AND u.auth_user_id=$2 AND u.is_active''', tenant, user)
        assert row and row['is_sandbox'] and row['workspace_status'] == 'ACTIVE'
        assert row['role'] in main.DISPATCH_ROLES
    finally:
        await connection.close()
    original_state = main.app.state._state.copy()
    original_overrides = main.app.dependency_overrides.copy()
    async def fixture_auth(request: Request):
        main.validate_tenant_query(request, tenant)
        return main.TenantContext(tenant, user, row['role'], 'synthetic-live-harness-context')
    try:
        async with db_pool_lifespan_context(main.app) as managed_app:
            managed_app.dependency_overrides[main.authenticate] = fixture_auth
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=managed_app),
                                         base_url='http://test') as client:
                yield client
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(original_overrides)
        main.app.state._state.clear()
        main.app.state._state.update(original_state)


@pytest.mark.asyncio
async def test_configured_lifespan_mounts_native_services(configured_lifespan_client):
    for name in ('rating', 'native_partners', 'finance', 'partner_lifecycle', 'logistics_supervisor'):
        assert getattr(main.app.state, name) is not None
    health = await configured_lifespan_client.get('/health')
    assert health.status_code == 200, health.text
    assert health.json()['mode'] == 'configured'
    orders = await configured_lifespan_client.get('/api/v1/shipping/native-orders')
    assert orders.status_code == 200, orders.text
    assert isinstance(orders.json()['orders'], list)
