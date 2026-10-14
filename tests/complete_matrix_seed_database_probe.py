"""Validate UAT seed constraints and reruns; always roll back all fixture writes."""
import asyncio
from pathlib import Path
from uuid import uuid4

import asyncpg
import main


async def run():
    settings = main.Settings()
    if settings.database_environment != 'SANDBOX' or settings.provider_environment != 'TEST':
        raise RuntimeError('This rollback probe requires SANDBOX database and TEST providers')
    connection = await asyncpg.connect(
        settings.database_url.get_secret_value(),
        ssl=main.database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict),
        timeout=15,
    )
    transaction = connection.transaction()
    await transaction.start()
    try:
        source = Path('seeds/complete_matrix/seed.sql').read_text(encoding='utf-8')
        source = source.replace('BEGIN;\n', '', 1).rsplit('COMMIT;', 1)[0]
        alpha, beta, owner = uuid4(), uuid4(), uuid4()
        batch = 'matrix-rollback-' + str(uuid4())
        source = source.replace('easyinvio-complete-matrix-v1', batch)
        source = source.replace('a0000000-0000-0000-0000-000000000001', str(alpha))
        source = source.replace('a0000000-0000-0000-0000-000000000002', str(beta))
        source = source.replace('b0000000-0000-0000-0000-000000000001', str(owner))
        source = source.replace('uat-matrix-alpha', 'probe-' + str(alpha))
        source = source.replace('uat-matrix-beta', 'probe-' + str(beta))
        await connection.execute(source)
        assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1', alpha) == 5000
        assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1', beta) == 2500
        await connection.execute('UPDATE public.wallets SET balance=4999,reserved_balance=1 WHERE tenant_id=$1', alpha)
        # Temp tables from the first execution persist until the outer rollback.
        await connection.execute('DROP TABLE pg_temp.matrix_workspaces')
        await connection.execute(source)
        wallet = await connection.fetchrow('SELECT balance,reserved_balance FROM public.wallets WHERE tenant_id=$1', alpha)
        assert wallet['balance'] == 4999 and wallet['reserved_balance'] == 1
        assert await connection.fetchval('SELECT count(*) FROM public.users WHERE tenant_id=ANY($1::uuid[])', [alpha, beta]) == 8
        assert await connection.fetchval('SELECT count(*) FROM public.ecommerce_stores WHERE tenant_id=ANY($1::uuid[]) AND NOT is_active', [alpha, beta]) == 6
        assert await connection.fetchval('SELECT count(*) FROM public.tenant_catalog_addresses WHERE tenant_id=ANY($1::uuid[]) AND is_default', [alpha, beta]) == 8
        assert not await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.hubspot_sync_jobs WHERE tenant_id=ANY($1::uuid[]))', [alpha, beta])
        assert not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM public.carrier_accounts WHERE tenant_id=ANY($1::uuid[]) AND is_active AND (environment<>'TEST' OR NOT credential_write_locked))", [alpha, beta])
        # Collision refusal remains transactional and does not modify the tenant.
        await connection.execute("UPDATE public.tenants SET company_profile=jsonb_set(company_profile,'{fixture_batch}','\"different-batch\"') WHERE tenant_id=$1", beta)
        await connection.execute('DROP TABLE pg_temp.matrix_workspaces')
        try:
            async with connection.transaction():
                await connection.execute(source)
        except asyncpg.RaiseError as error:
            assert 'Fixture tenant ID collision' in str(error)
        else:
            raise AssertionError('Existing non-fixture tenant was accepted')
        print('PASS: exact schema, parent references, two-workspace fixtures, rerun balance preservation, CRM isolation and collision refusal')
    finally:
        await transaction.rollback()
        await connection.close()
        print('ROLLBACK: no fixture records persisted; no provider requests issued')


if __name__ == '__main__':
    asyncio.run(run())
