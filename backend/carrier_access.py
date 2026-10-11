"""Historical carrier access is limited to a verified shipment lifecycle."""
import json
from fastapi import HTTPException


async def verified_return_parent(connection, tenant_id, shipment_id, origin, destination):
    row=await connection.fetchrow('''SELECT carrier_account_id,logistics_metadata FROM public.shipments
        WHERE tenant_id=$1 AND id=$2 AND status IN ('BOOKED','IN_TRANSIT','EXCEPTION','DELIVERED')''',tenant_id,shipment_id)
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
    if actual_origin!=expected_origin or actual_destination!=expected_destination:
        raise HTTPException(403,'Return must reverse the authenticated original shipment')
    return row['carrier_account_id']
