"""Historical carrier access is limited to a verified shipment lifecycle."""
import json
from fastapi import HTTPException


async def verified_return_parent(connection, tenant_id, shipment_id, origin, destination, *, warehouse_id=None, warehouse_version=None):
    row=await connection.fetchrow('''SELECT carrier_account_id,logistics_metadata FROM public.shipments
        WHERE tenant_id=$1 AND id=$2 AND status='DELIVERED' ''',tenant_id,shipment_id)
    if row is None:
        raise HTTPException(404,'Original return shipment not found in this workspace')
    metadata=json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'],str) else row['logistics_metadata']
    original=(metadata or {}).get('automation_order') or {}
    if not original or original.get('is_return'):
        raise HTTPException(422,'An original outbound shipment is required')
    from main import Address
    try:
        expected_origin=Address.model_validate(original['destination']).model_dump(mode='json')
        expected_destination=Address.model_validate(original['origin']).model_dump(mode='json')
        actual_origin=Address.model_validate(origin).model_dump(mode='json')
        actual_destination=Address.model_validate(destination).model_dump(mode='json')
    except (ValueError,KeyError,TypeError):
        raise HTTPException(422,'Return addresses require review') from None
    if actual_origin!=expected_origin:
        raise HTTPException(403,'Return must reverse the authenticated original shipment')
    if warehouse_id is not None:
        warehouse = await connection.fetchrow('''SELECT address,version FROM public.tenant_catalog_addresses
            WHERE tenant_id=$1 AND id=$2 AND address_role='RETURN' AND archived_at IS NULL''', tenant_id, warehouse_id)
        if warehouse is None or warehouse['version'] != warehouse_version:
            raise HTTPException(409, 'Return warehouse changed; review the prepared return before purchase')
        try:
            stored = json.loads(warehouse['address']) if isinstance(warehouse['address'],str) else warehouse['address']
            expected_destination = Address.model_validate(stored).model_dump(mode='json')
        except (ValueError,TypeError):
            raise HTTPException(422, 'Return warehouse address requires review') from None
    if actual_destination!=expected_destination:
        raise HTTPException(403,'Return destination must match the authenticated warehouse')
    return row['carrier_account_id']


async def return_accounts(repository, context, parent_account_id, *, all_active=False):
    if not all_active:
        return await repository.accounts(context, historical_account_id=parent_account_id)
    # New headless returns use current tenant-approved connections. A retired
    # connection is deliberately not re-enabled by the network selection flag.
    return await repository.accounts(context)
