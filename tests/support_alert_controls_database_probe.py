"""Rollback-only administrative pause/resume SQL; no messages or opt-in changes persist."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import main
from backend.support_alert_controls import AlertPause, build_router
from backend.dashboard_portal import build_router as dashboard_router


async def run():
    settings = main.Settings()
    assert settings.database_environment == 'SANDBOX'
    connection = await asyncpg.connect(settings.database_url.get_secret_value(),
        ssl=main.database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict))
    transaction = connection.transaction()
    await transaction.start()

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield connection

    try:
        migration = Path('migrations/034_support_alert_controls.sql').read_text(encoding='utf-8')
        await connection.execute(migration.replace('BEGIN;', '').replace('COMMIT;', ''))
        identifier = await connection.fetchval('SELECT id FROM public.whatsapp_bindings LIMIT 1')
        assert identifier, 'A sandbox verified-binding fixture is required'
        await connection.execute('UPDATE public.whatsapp_bindings SET notification_opt_in=true,is_active=true,verified_at=now() WHERE id=$1', identifier)
        service = SimpleNamespace(settings=SimpleNamespace(twilio_enabled=False),
                                  delivery=SimpleNamespace(support_whatsapp_enabled=False))
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            finance=SimpleNamespace(pool=Pool()), support_delivery=service)))
        routes = {route.path: route.endpoint for route in build_router(lambda: None).routes}
        pause = routes['/api/v1/admin/support/whatsapp/bindings/{binding_id}']
        for value in [True, True, False, False]:
            result = await pause(identifier, AlertPause(paused=value), request, None)
            assert result['alerts_paused'] == value and not result['message_sent']
            assert await connection.fetchval('SELECT alerts_paused FROM public.whatsapp_bindings WHERE id=$1', identifier) == value
            assert await connection.fetchval('SELECT notification_opt_in FROM public.whatsapp_bindings WHERE id=$1', identifier)
        result = await routes['/api/v1/admin/support/whatsapp/bindings'](request, None)
        assert result['controls_ready'] and not result['configured']
        assert all('sender_e164' not in row for row in result['bindings'])
        tenant = await connection.fetchval("SELECT tenant_id FROM public.support_tickets WHERE automation_failure_id IS NOT NULL LIMIT 1")
        assert tenant, 'An internal processing-failure fixture is required'
        tickets = next(route.endpoint for route in dashboard_router(lambda: None).routes if route.path == '/api/v1/support/tickets')
        client_result = await tickets(request, SimpleNamespace(tenant_id=tenant))
        assert all(not ticket['automation_failure_id'] for ticket in client_result['tickets'])
        print('PASS: migration 034, pause/resume replay, consent preservation, masked admin list and client internal-failure filtering against actual SQL')
    finally:
        await transaction.rollback()
        await connection.close()
        print('All database changes rolled back; no notifications sent.')


if __name__ == '__main__':
    asyncio.run(run())
