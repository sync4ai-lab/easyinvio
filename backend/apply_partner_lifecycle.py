"""Explicit sandbox-only migration runner; contains no credentials or seed data."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from main import Settings, database_tls_context


async def run(migration="023_partner_lifecycle.sql"):
    if migration not in {"023_partner_lifecycle.sql","024_native_partner_orders_and_webhooks.sql","026_support_review_activity.sql","027_workspace_invitations_and_disputes.sql"}:
        raise ValueError("Unsupported migration")
    settings = Settings()
    if settings.database_environment != 'SANDBOX':
        raise RuntimeError('This runner is restricted to the configured SANDBOX database')
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), timeout=15,
        ssl=database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict))
    try:
        await connection.execute((Path('migrations') / migration).read_text(encoding='utf-8'))
        await connection.execute((Path('migrations') / migration).read_text(encoding='utf-8'))
        tables = ('partner_shipping_offers', 'partner_unbound_quotes', 'partner_cancellations') if migration.startswith('023') else ('partner_provider_options','partner_order_jobs')
        if migration.startswith('026'):tables=('support_ticket_activity',)
        if migration.startswith('027'):tables=('workspace_invitations','shipment_dispute_drafts')
        for table in tables:
            assert await connection.fetchval('''SELECT relrowsecurity FROM pg_class
                WHERE oid=$1::regclass''', 'public.' + table)
            for role in ('anon', 'authenticated'):
                assert not await connection.fetchval('SELECT has_table_privilege($1,$2,$3)', role, 'public.' + table, 'SELECT')
        receipt = {'migration': migration, 'environment': 'SANDBOX',
            'applied_at': datetime.now(timezone.utc).isoformat(), 'idempotent_rerun': True,
            'private_tables_browser_access_denied': True, 'external_api_calls': 0}
        output = Path('docs/aggregator_lifecycle/migration_receipt.json' if migration.startswith('023') else 'docs/three_partners/migration_receipt.json')
        if migration.startswith('026'):output=Path('docs/support_workflow/migration_receipt.json')
        if migration.startswith('027'):output=Path('docs/workspace_settings/migration_receipt.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print('PASS: ' + migration + ' applied twice; private tables deny browser access.')
    finally:
        await connection.close()


if __name__ == '__main__':
    import sys
    asyncio.run(run(sys.argv[1] if len(sys.argv)>1 else "023_partner_lifecycle.sql"))
