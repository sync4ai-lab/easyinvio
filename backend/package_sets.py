"""Exact physical package snapshots; carrier APIs receive individual boxes."""
from decimal import Decimal, ROUND_CEILING, localcontext
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.ai_engine import strict_decimal


class PackageInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    box_index: int = Field(strict=True, ge=1, le=100)
    length_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)
    width_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)
    height_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)
    actual_weight_kg: Decimal = Field(gt=0, le=1000, decimal_places=3)

    @field_validator('length_cm', 'width_cm', 'height_cm', 'actual_weight_kg', mode='before')
    @classmethod
    def decimal(cls, value):
        return strict_decimal(value)


def package_charge(dimensions, weights):
    with localcontext() as context:
        context.prec = 50
        pieces = []
        for index, (box, actual) in enumerate(zip(dimensions, weights, strict=True), 1):
            volumetric = box.length_cm * box.width_cm * box.height_cm / Decimal('5000')
            billable = max(actual, volumetric).quantize(Decimal('.001'), rounding=ROUND_CEILING)
            pieces.append({'box_index': index, 'actual_weight_kg': str(actual),
                           'volumetric_weight_kg': str(volumetric), 'billable_weight_kg': str(billable)})
        return {'packages': pieces, 'actual_weight_kg': str(sum(weights, Decimal(0))),
                'billable_weight_kg': str(sum((Decimal(piece['billable_weight_kg']) for piece in pieces), Decimal(0)))}


def validate_goods_allocation(items, weights):
    total = sum((item.quantity * item.unit_weight_kg for item in items), Decimal(0))
    if total > sum(weights, Decimal(0)):
        raise ValueError('Goods net weight cannot exceed total packed weight')
    allocated = {}
    for item in items:
        if item.package_index is not None:
            if item.package_index > len(weights):
                raise ValueError('Goods refer to an unknown package')
            allocated[item.package_index] = allocated.get(item.package_index, Decimal(0)) + item.quantity * item.unit_weight_kg
    if any(weight > weights[index - 1] for index, weight in allocated.items()):
        raise ValueError('Allocated goods exceed their box packed weight')
    if len(weights) > 1 and items and any(item.package_index is None for item in items):
        raise ValueError('Allocate each goods line to a box before quoting multi-piece goods')


async def persist_package_goods(connection, tenant_id, shipment_id, order):
    packages = order.packages or [order.cargo]
    arrays = [{'box_index': index, **{field: format(getattr(box, field), 'f')
               for field in ('length_cm', 'width_cm', 'height_cm', 'actual_weight_kg')}}
              for index, box in enumerate(packages, 1)] if order.cargo.cargo_type == 'PARCEL' else []
    import json
    async with connection.transaction():
        await connection.execute('DELETE FROM public.shipment_goods_items WHERE tenant_id=$1 AND shipment_id=$2', tenant_id, shipment_id)
        await connection.execute('''UPDATE public.shipments SET multi_parcel_dimensions=$3::jsonb,parcel_count=$4,
            tracking_lifecycle_type=$5,return_of_shipment_id=$6 WHERE tenant_id=$1 AND id=$2''',
            tenant_id, shipment_id, json.dumps(arrays), len(packages),
            'RETURN_SHIPMENT' if order.is_return else 'FORWARD_SHIPMENT', order.return_of_shipment_id)
        for index, item in enumerate(order.items, 1):
            await connection.execute('''INSERT INTO public.shipment_goods_items
                (tenant_id,shipment_id,item_index,package_index,description,quantity,unit_weight_kg,unit_value,currency,sku,hs_code,origin_country)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)''', tenant_id, shipment_id, index,
                item.package_index, item.description, item.quantity, item.unit_weight_kg, item.unit_value,
                order.customs_currency or order.currency, item.sku, item.hs_code, item.origin_country)
