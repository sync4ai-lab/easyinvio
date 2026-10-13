"""Migration 035 validation with full rollback; no attached-prompt implementation."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import asyncpg
import main


async def run():
    settings = main.Settings()
    assert settings.database_environment == 'SANDBOX' and settings.provider_environment == 'TEST'
    connection = await asyncpg.connect(settings.database_url.get_secret_value(),
        ssl=main.database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict))
    outer = connection.transaction()
    await outer.start()
    checks = []

    async def rejects(sql, *args, code):
        savepoint = connection.transaction()
        await savepoint.start()
        try:
            await connection.execute(sql, *args)
        except asyncpg.PostgresError as error:
            assert error.sqlstate == code, error.sqlstate
        else:
            raise AssertionError('Invalid mutation was accepted')
        finally:
            await savepoint.rollback()

    try:
        migration = Path('migrations/035_packages_goods_returns_and_credential_locks.sql').read_text(encoding='utf-8')
        # Exactly the outer migration transaction is removed; PL/pgSQL BEGIN stays.
        migration = migration.replace('BEGIN;\nSET LOCAL', 'SET LOCAL', 1).rsplit('COMMIT;', 1)[0]
        try:
            await connection.execute(migration)
        except asyncpg.PostgresError as error:
            print('Migration diagnostic',error.position,error.internal_position,error.internal_query)
            raise
        await connection.execute(migration)
        checks.append('migration applies and is rerunnable')
        assert await connection.fetchval("SELECT public.valid_multi_parcel_dimensions('[]'::jsonb)")
        boxes = [{'box_index': 1, 'length_cm': 30, 'width_cm': 20, 'height_cm': 10, 'actual_weight_kg': 3},
                 {'box_index': 2, 'length_cm': 60, 'width_cm': 40, 'height_cm': 40, 'actual_weight_kg': 2.5}]
        assert await connection.fetchval('SELECT public.valid_multi_parcel_dimensions($1::jsonb)', json.dumps(boxes))
        for invalid in [None, {}, [{**boxes[0], 'box_index': 2}], [{**boxes[0], 'actual_weight_kg': -1}],
                        [{key: value for key, value in boxes[0].items() if key != 'actual_weight_kg'}]]:
            assert not await connection.fetchval('SELECT public.valid_multi_parcel_dimensions($1::jsonb)', json.dumps(invalid))
        checks.append('different box dimensions and weights accepted; missing, negative and unordered packages rejected')
        shipment = await connection.fetchrow("""SELECT s.id,s.tenant_id FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
            WHERE t.workspace_slug LIKE 'seed24-%' AND s.booked_at IS NULL AND s.cargo_type='PARCEL'
            AND s.status='QUOTED' AND NOT s.customs_required AND NOT EXISTS(SELECT 1 FROM public.ecommerce_tracking_outbox o WHERE o.shipment_id=s.id)
            LIMIT 1 FOR UPDATE OF s""")
        assert shipment, 'A sandbox quoted parcel fixture is required'
        tenant, identifier = shipment['tenant_id'], shipment['id']
        await connection.execute('UPDATE public.shipments SET parcel_count=2,parcel_length_cm=30,parcel_width_cm=20,parcel_height_cm=10,parcel_weight_kg=3,multi_parcel_dimensions=$2::jsonb WHERE id=$1', identifier, json.dumps(boxes))
        await connection.execute("INSERT INTO public.shipment_goods_items(tenant_id,shipment_id,item_index,package_index,description,quantity,unit_weight_kg,unit_value,currency,hs_code,origin_country) VALUES($1,$2,1,1,'Rollback test goods',2,0.200,10,'GBP','850980','GB')", tenant, identifier)
        await connection.execute('SET CONSTRAINTS ALL IMMEDIATE')
        await rejects('UPDATE public.shipment_goods_items SET unit_weight_kg=4 WHERE tenant_id=$1 AND shipment_id=$2', tenant, identifier, code='23514')
        await rejects('UPDATE public.shipment_goods_items SET package_index=3 WHERE tenant_id=$1 AND shipment_id=$2', tenant, identifier, code='23514')
        await rejects('UPDATE public.shipments SET parcel_count=3 WHERE id=$1', identifier, code='23514')
        await rejects("INSERT INTO public.shipment_goods_items(tenant_id,shipment_id,item_index,description,quantity,unit_weight_kg,unit_value,currency,origin_country) VALUES($1,$2,2,'Cross-tenant test',1,0.1,1,'GBP','GB')", uuid4(), identifier, code='23503')
        await connection.execute("UPDATE public.shipments SET status='BOOKING' WHERE id=$1", identifier)
        await rejects("UPDATE public.shipment_goods_items SET description='Changed after submission' WHERE tenant_id=$1 AND shipment_id=$2", tenant, identifier, code='23514')
        await rejects("UPDATE public.shipments SET multi_parcel_dimensions=jsonb_set(multi_parcel_dimensions,'{0,height_cm}','11'::jsonb) WHERE id=$1", identifier, code='23514')
        await connection.execute("UPDATE public.shipments SET status='QUOTED' WHERE id=$1", identifier)
        checks.append('goods mass, per-box allocation and parcel-count mismatch rejected by PostgreSQL')
        checks.append('cross-tenant goods rejected and submitted goods/package snapshots frozen')
        store = await connection.fetchval('SELECT id FROM public.ecommerce_stores WHERE tenant_id=$1 LIMIT 1', tenant)
        assert store, 'A sandbox storefront fixture is required'
        await connection.execute("UPDATE public.shipments SET tracking_lifecycle_type='RETURN_SHIPMENT',logistics_metadata=jsonb_set(logistics_metadata,'{automation_order}','{\"is_return\":true}'::jsonb) WHERE id=$1", identifier)
        await connection.execute("INSERT INTO public.ecommerce_tracking_outbox(tenant_id,shipment_id,store_id,store_order_id,payload) VALUES($1,$2,$3,'ROLLBACK-RETURN-035','{}'::jsonb)", tenant, identifier, store)
        job = await connection.fetchrow('SELECT tracking_lifecycle_type,status,store_sync_error_code FROM public.ecommerce_tracking_outbox WHERE tenant_id=$1 AND shipment_id=$2', tenant, identifier)
        assert dict(job) == {'tracking_lifecycle_type': 'RETURN_SHIPMENT', 'status': 'RECONCILIATION_REQUIRED', 'store_sync_error_code': 'RETURN_ADAPTER_UPGRADE_REQUIRED'}
        checks.append('legacy forward worker cannot pick up a new return job')
        standalone = await connection.fetchval('SELECT id FROM public.carrier_accounts WHERE platform_connection_id IS NULL LIMIT 1')
        assert standalone
        await rejects('UPDATE public.carrier_accounts SET credential_write_locked=false WHERE id=$1', standalone, code='42501')
        await rejects("UPDATE public.carrier_accounts SET credentials_ciphertext=credentials_ciphertext||decode('00','hex') WHERE id=$1", standalone, code='42501')
        await connection.execute('UPDATE public.carrier_accounts SET is_active=is_active WHERE id=$1', standalone)
        checks.append('standalone credential overwrite and unlocking rejected; operational edits preserved')
        shared = await connection.fetchrow('SELECT id,platform_connection_id FROM public.carrier_accounts WHERE platform_connection_id IS NOT NULL LIMIT 1')
        assert shared
        await rejects("UPDATE public.carrier_accounts SET credentials_ciphertext=credentials_ciphertext||decode('00','hex') WHERE id=$1", shared['id'], code='42501')
        await connection.execute("UPDATE public.platform_carrier_connections SET credentials_ciphertext=credentials_ciphertext||decode('00','hex') WHERE id=$1", shared['platform_connection_id'])
        assert await connection.fetchval('''SELECT a.credentials_ciphertext=p.credentials_ciphertext FROM public.carrier_accounts a
            JOIN public.platform_carrier_connections p ON p.id=a.platform_connection_id WHERE a.id=$1''', shared['id'])
        checks.append('direct shared-account tampering rejected; trusted catalog synchronization preserved')
        assert not await connection.fetchval("SELECT has_table_privilege('authenticated','public.shipment_goods_items','SELECT')")
        checks.append('goods rows remain private to backend service role')
        print(json.dumps({'checks': checks, 'persistent_changes': False, 'provider_calls': 0}))
    finally:
        await outer.rollback()
        await connection.close()
        print('All migration and fixture writes rolled back.')


if __name__ == '__main__':
    asyncio.run(run())
