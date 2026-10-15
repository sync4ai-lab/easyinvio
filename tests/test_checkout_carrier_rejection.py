"""Exercise actual lifecycle/finance compensation with synthetic IO boundaries."""
from decimal import Decimal
from unittest.mock import AsyncMock
import pytest
import main
from backend.automation_freight_engine import PurchaseRejected
from backend.automation_three_partners import EasyPostAdapter, FactoryPurchaseBridge
from tests.test_easyinvio_complete_matrix import (
    authenticated_client, matrix_context, matrix_pool, matrix_repository, provider_matrix,
)
from tests.uat_matrix_support import TENANT_A


@pytest.mark.asyncio
async def test_unavailable_carrier_releases_reservation_and_retires_offer(authenticated_client, matrix_pool, monkeypatch):
    purchase = AsyncMock(side_effect=PurchaseRejected('SHIPPO_CARRIER_UNAVAILABLE'))
    async def buy(bridge, account, rate):return await purchase(account, rate)
    monkeypatch.setattr(FactoryPurchaseBridge, 'buy', buy)
    monkeypatch.setattr('backend.automation_three_partners.create_adapter',
        lambda *args, **kwargs: object.__new__(EasyPostAdapter))
    fail_ticket = AsyncMock()
    main.app.state.partner_lifecycle.automation.fail_ticket = fail_ticket
    body = {'tenant_id': str(TENANT_A), 'offer_id': str(matrix_pool.rate.offer_id)}
    response = await authenticated_client.post('/api/v1/shipping/confirm-booking', json=body)
    assert response.status_code == 502, response.text
    error = response.json()['detail']
    assert error['code'] == 'CARRIER_UNAVAILABLE'
    assert error['retry_requires_fresh_quote'] is True
    assert error['reserved_credit_released'] is True
    assert matrix_pool.balance == Decimal('100.00')
    assert matrix_pool.reserved == Decimal('0.00')
    assert matrix_pool.reservation['status'] == 'RELEASED'
    assert matrix_pool.shipment['status'] == 'FAILED'
    assert [entry['type'] for entry in matrix_pool.ledger] == ['RESERVE', 'RELEASE']
    assert sum((entry['balance_delta'] for entry in matrix_pool.ledger), Decimal(0)) == 0
    assert sum((entry['reserved_delta'] for entry in matrix_pool.ledger), Decimal(0)) == 0
    assert fail_ticket.await_args.args[-1] == 'SHIPPO_CARRIER_UNAVAILABLE'
    repeated = await authenticated_client.post('/api/v1/shipping/confirm-booking', json=body)
    assert repeated.status_code == 409, repeated.text
    purchase.assert_awaited_once()
    assert len(matrix_pool.ledger) == 2
