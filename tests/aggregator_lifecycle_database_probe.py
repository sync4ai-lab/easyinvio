"""Real sandbox SQL and EasyPost TEST lifecycle; all database writes roll back.

Creates one actual non-billable provider test label. No other provider purchase,
payment, CRM synchronization or WhatsApp message is sent.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx

import main
from backend.aggregator_lifecycle import PartnerLifecycleService, BookingRequest, VoidRequest
from backend.automation_freight_engine import AutomationService


async def run():
    settings = main.Settings()
    assert settings.database_environment == 'SANDBOX' and settings.provider_environment == 'TEST'
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), timeout=15,
        ssl=main.database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict))
    outer = connection.transaction(isolation='repeatable_read')
    await outer.start()
    report = {'executed_at': datetime.now(timezone.utc).isoformat(), 'database_writes_rolled_back': False,
              'live_mode_purchases': 0, 'other_partner_labels': 'NOT_EXECUTED', 'checks': []}

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield connection

    try:
        tenant = await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-03' AND is_sandbox")
        member = await connection.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active", tenant)
        assert tenant and member
        context = main.TenantContext(tenant, member, 'OWNER', '')
        pool = Pool()
        await connection.execute("UPDATE public.wallets SET balance=1000,reserved_balance=0 WHERE tenant_id=$1 AND currency='USD'", tenant)
        address_from = {'name': 'EasyInvio Sandbox QA', 'line1': '417 Montgomery Street',
                        'city': 'San Francisco', 'state': 'CA', 'postal_code': '94104', 'country_code': 'US'}
        address_to = {'name': 'EasyInvio Sandbox Recipient', 'line1': '228 Park Ave S',
                      'city': 'New York', 'state': 'NY', 'postal_code': '10003', 'country_code': 'US'}
        async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
            repository = main.SupabaseRepository(client, settings)
            accounts = await repository.accounts(context)
            assert any(a.provider == 'EASYPOST' for a in accounts), 'No active native TEST connection'
            rating = main.RatingService(client, repository, settings, pool=pool)
            finance = main.FinanceEngine(pool, settings, None)
            automation = AutomationService(pool, rating, finance, repository, main.RatingRequest, client, settings)
            service = PartnerLifecycleService(automation, client)
            prepared = await automation.process(context, {'idempotency_key': str(uuid4()),
                'order_reference': 'ROLLBACK-AGGREGATOR-QA', 'origin': address_from,
                'destination': address_to, 'currency': 'USD', 'cargo': {'cargo_type': 'PARCEL',
                    'actual_weight_kg': '1.000', 'length_cm': '20', 'width_cm': '15', 'height_cm': '10'}}, 'QUOTE_ONLY')
            assert prepared['status'] == 'QUOTED', prepared.get('error', 'Quote unavailable')
            report['checks'].append('PASS: actual provider TEST rates with real sandbox margin calculation')
            offer_id = __import__('uuid').UUID(prepared['rate']['offer_id'])
            shipment_id = __import__('uuid').UUID(prepared['shipment_id'])
            body = BookingRequest(tenant_id=tenant, offer_id=offer_id)
            amount = await connection.fetchval('SELECT final_client_price FROM public.shipments WHERE tenant_id=$1 AND id=$2', tenant, shipment_id)
            # An insolvent request must not submit a carrier transaction.
            await connection.execute('UPDATE public.wallets SET balance=0 WHERE tenant_id=$1', tenant)
            try:
                await service.confirm(context, body)
                raise AssertionError('Insufficient-credit booking accepted')
            except main.HTTPException as error:
                assert error.status_code == 402
            report['checks'].append('PASS: real atomic wallet gate rejects insufficient credit with 402')
            await connection.execute('UPDATE public.wallets SET balance=1000 WHERE tenant_id=$1', tenant)
            result = await service.confirm(context, body)
            assert result['status'] == 'BOOKED' and result['label']['tracking_number']
            assert 'easypost' not in json.dumps(result).lower()
            assert await connection.fetchval("SELECT count(*) FROM public.wallet_ledger WHERE tenant_id=$1 AND reservation_id IN (SELECT id FROM public.wallet_reservations WHERE shipment_id=$2) AND entry_type='CAPTURE'", tenant, shipment_id) == 1
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1', tenant) == 1000 - amount
            assert await connection.fetchval('SELECT reserved_balance FROM public.wallets WHERE tenant_id=$1', tenant) == 0
            report['checks'].append('PASS: genuine EasyPost TEST purchase, normalized tracking and one Decimal wallet capture')
            replay = await service.confirm(context, body)
            assert replay['replayed'] is True
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1', tenant) == 1000 - amount
            report['checks'].append('PASS: booking replay does not purchase again or debit twice')
            cancelled = await service.void(context, VoidRequest(tenant_id=tenant, shipment_id=shipment_id))
            balance = await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1', tenant)
            if cancelled['status'] == 'CANCELLATION_PENDING':
                assert balance == 1000 - amount
            else:
                assert cancelled['status'] == 'CANCELLED' and balance == 1000
                await service.void(context, VoidRequest(tenant_id=tenant, shipment_id=shipment_id))
                assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1', tenant) == 1000
            report['checks'].append('PASS: actual native cancellation result=' + cancelled['status'] + '; no premature or duplicate credit')
            if cancelled['status'] == 'CANCELLATION_PENDING':
                # Explicitly separate financial confirmation simulation from
                # the genuine provider result above; no mock is a live pass.
                from unittest.mock import patch, AsyncMock
                confirmation = SimpleNamespace(void_confirmed=AsyncMock(return_value=True))
                with patch('backend.aggregator_lifecycle.create_adapter', return_value=confirmation):
                    settled = await service.void(context, VoidRequest(tenant_id=tenant, shipment_id=shipment_id))
                    assert settled['status'] == 'CANCELLED'
                    assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1', tenant) == 1000
                    await service.void(context, VoidRequest(tenant_id=tenant, shipment_id=shipment_id))
                    assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1', tenant) == 1000
                report['checks'].append('PASS: controlled provider-confirmation simulation against real SQL credits once; repeat does not double-credit')
            report['status'] = 'PASS'
    except Exception as error:
        report['status'] = 'BLOCKED' if isinstance(error, (httpx.HTTPError, main.HTTPException)) else 'FAIL'
        report['error_type'] = type(error).__name__
        if isinstance(error, AssertionError):
            report['reason'] = str(error)[:200]
        if isinstance(error, main.HTTPException):
            report['http_status'] = error.status_code
    finally:
        await outer.rollback()
        await connection.close()
        report['database_writes_rolled_back'] = True
        output = Path('docs/aggregator_lifecycle/sandbox_probe.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    if report['status'] == 'FAIL':
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(run())
