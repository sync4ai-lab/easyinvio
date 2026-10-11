"""Explicit sandbox-only migration runner; contains no credentials or seed data."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from main import Settings, database_tls_context


async def run():
    settings = Settings()
    if settings.database_environment != 'SANDBOX':
        raise RuntimeError('This runner is restricted to the configured SANDBOX database')
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), timeout=15,
        ssl=database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict))
    try:
        await connection.execute(Path('migrations/023_partner_lifecycle.sql').read_text(encoding='utf-8'))
        await connection.execute(Path('migrations/023_partner_lifecycle.sql').read_text(encoding='utf-8'))
        for table in ('partner_shipping_offers', 'partner_unbound_quotes', 'partner_cancellations'):
            assert await connection.fetchval('''SELECT relrowsecurity FROM pg_class
                WHERE oid=$1::regclass''', 'public.' + table)
            for role in ('anon', 'authenticated'):
                assert not await connection.fetchval('SELECT has_table_privilege($1,$2,$3)', role, 'public.' + table, 'SELECT')
        receipt = {'migration': '023_partner_lifecycle.sql', 'environment': 'SANDBOX',
            'applied_at': datetime.now(timezone.utc).isoformat(), 'idempotent_rerun': True,
            'private_tables_browser_access_denied': True, 'external_api_calls': 0}
        output = Path('docs/aggregator_lifecycle/migration_receipt.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        print('PASS: migration 023 applied twice; private offers/cancellations enforce browser access boundaries.')
    finally:
        await connection.close()


if __name__ == '__main__':
    asyncio.run(run())
