"""Route-scoped package guidance; reference limits never certify carrier eligibility."""
from decimal import Decimal
from typing import Literal

import pycountry
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.ai_engine import strict_decimal
from backend.aggregator_registry import identify_aggregator
from backend.automation_freight_engine import Goods


class PackageDimensions(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    length_cm: Decimal = Field(gt=0, le=1500, decimal_places=2)
    width_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)
    height_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)

    @field_validator('length_cm', 'width_cm', 'height_cm', mode='before')
    @classmethod
    def decimal(cls, value):
        return strict_decimal(value)


class PackageCheck(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    origin_country: str
    destination_country: str
    cargo_type: Literal['LETTER', 'PARCEL', 'PALLET', 'OVERLAND_FREIGHT']
    actual_weight_kg: Decimal = Field(gt=0, le=30000, decimal_places=3)
    dimensions: PackageDimensions | None = None
    shipment_items: list[Goods] = Field(default_factory=list, max_length=100)

    @field_validator('origin_country', 'destination_country')
    @classmethod
    def country(cls, value):
        if pycountry.countries.get(alpha_2=value) is None:
            raise ValueError('Choose a valid country')
        return value

    @field_validator('actual_weight_kg', mode='before')
    @classmethod
    def weight(cls, value):
        return strict_decimal(value)

    @model_validator(mode='after')
    def dimensions_required(self):
        if self.cargo_type != 'LETTER' and self.dimensions is None:
            raise ValueError('Enter all three outside dimensions of the packed shipment')
        return self


# A service-specific reference, scoped to UK-origin international parcels.
# Additional verified services can be added without changing quote orchestration.
PARCEL_RULES = ({
    'id': 'DPD_UK_INTERNATIONAL_PARCEL', 'service': 'DPD UK international parcel',
    'origin_countries': ('GB',), 'excluded_destinations': ('GB', 'GG', 'JE', 'IM'),
    'max_weight_kg': Decimal('31'), 'max_longest_cm_exclusive': Decimal('175'),
    'max_combined_cm_exclusive': Decimal('300'),
    'source': 'https://myportal.drivers.dpd.co.uk/terms', 'verified_on': '2026-10-13',
},)


def evaluate_package(body, accounts=None):
    messages = []
    measurements = {'actual_weight_kg': str(body.actual_weight_kg)}
    def add(code, severity, text, suggestion, source=None):
        messages.append({'code': code, 'severity': severity, 'text': text,
                         'suggestion': suggestion, 'source': source})
    net = sum((item.quantity * item.unit_weight_kg for item in body.shipment_items), Decimal(0))
    if net > body.actual_weight_kg:
        add('GOODS_EXCEED_PACKED_WEIGHT', 'ERROR', f'Goods weigh {net} kg, but packed weight is {body.actual_weight_kg} kg.',
            'Weigh the complete packed shipment and correct the goods quantities or weights if entered incorrectly.')
    if body.cargo_type == 'LETTER':
        if body.actual_weight_kg >= Decimal('.5'):
            add('LETTER_WEIGHT_LIMIT', 'ERROR', 'EasyInvio document-letter quotes require a packed weight below 0.5 kg.',
                'Use Standard Parcel for heavier items and enter the actual packed dimensions.')
        if body.shipment_items:
            add('LETTER_CONTENT_REVIEW', 'WARNING', 'Goods have been entered for a document-letter shipment.',
                'Use Standard Parcel for merchandise. Document-letter service eligibility is verified by the provider.')
    elif body.dimensions is not None:
        d = body.dimensions
        longest, middle, shortest = sorted([d.length_cm, d.width_cm, d.height_cm], reverse=True)
        combined = longest + 2 * (middle + shortest)
        measurements.update(longest_side_cm=str(longest), combined_length_girth_cm=str(combined))
        from backend.automation_freight_engine import Cargo, calculate_cargo_charge
        try:
            cargo = Cargo(cargo_type=body.cargo_type, actual_weight_kg=body.actual_weight_kg,
                          length_cm=d.length_cm, width_cm=d.width_cm, height_cm=d.height_cm)
            if body.cargo_type == 'PARCEL' and Decimal(calculate_cargo_charge(cargo)['billable_weight_kg']) > 1000:
                raise ValueError('Package exceeds the supported parcel calculation range')
        except ValueError:
            add('PACKAGE_OUTSIDE_SUPPORTED_RANGE', 'ERROR', 'These measurements exceed the supported range for this cargo type.',
                'Check units and weigh the packed shipment. If these measurements are correct, ask support to arrange a suitable large-cargo service.')
        if body.cargo_type == 'PARCEL':
            for rule in PARCEL_RULES:
                if body.origin_country not in rule['origin_countries'] or body.destination_country in rule['excluded_destinations']:
                    continue
                exceeded = []
                if combined >= rule['max_combined_cm_exclusive']:
                    exceeded.append(f"combined length and girth is {combined} cm; this service requires below {rule['max_combined_cm_exclusive']} cm")
                if longest >= rule['max_longest_cm_exclusive']:
                    exceeded.append(f"longest side is {longest} cm; this service requires below {rule['max_longest_cm_exclusive']} cm")
                if body.actual_weight_kg > rule['max_weight_kg']:
                    exceeded.append(f"packed weight is {body.actual_weight_kg} kg; this service allows up to {rule['max_weight_kg']} kg")
                if exceeded:
                    add(rule['id'], 'WARNING', 'Your package is larger or heavier than this standard parcel service allows.',
                        'Open Packaging sizes for guidance. Check the sealed package measurements; repack or split the goods if practical. If the measurements are correct, you can check other carriers or contact support for a suitable service. '
                        + rule['service'] + ' reference: ' + '; '.join(exceeded) + '.', rule['source'])
    if accounts is not None:
        if not accounts:
            add('NO_ACTIVE_CONNECTIONS', 'ERROR', 'No rate connections are enabled for this workspace.',
                'Contact support to enable a shipping connection before requesting rates.')
        elif body.cargo_type in {'PALLET', 'OVERLAND_FREIGHT'} and all(identify_aggregator(a.base_url) for a in accounts):
            add('FREIGHT_NOT_CONFIGURED', 'ERROR', 'Freight quoting is not configured on the connected parcel integrations.',
                'Contact support to arrange a verified freight carrier contract. Keep the measured pallet dimensions and weight.')
        elif body.cargo_type == 'LETTER' and all(identify_aggregator(a.base_url) and 'easypost.com' not in a.base_url for a in accounts):
            add('LETTER_NOT_CONFIGURED', 'ERROR', 'The enabled connections do not have a supported document-letter service.',
                'Use a Standard Parcel service with accurate package dimensions, or contact support for document shipping.')
    return {'blocking': any(m['severity'] == 'ERROR' for m in messages), 'messages': messages,
            'measurements': measurements, 'origin_country': body.origin_country, 'destination_country': body.destination_country,
            'scope': 'Verified reference rules are service-specific and coverage is partial. Live carrier quotes check account, route, postcode, package and currency eligibility. A passed reference check does not guarantee a rate.',
            'measurement_help': 'Measure the longest outside side and the two remaining sides of the sealed package in centimetres. Weigh the complete package in kilograms. Combined length and girth = longest side + 2 × each other side.'}


def build_router(authenticate):
    router = APIRouter(tags=['Package guidance'])

    @router.post('/api/v1/logistics/package-guidance')
    async def public_guidance(body: PackageCheck):
        return evaluate_package(body)

    @router.post('/api/v1/shipping/package-check')
    async def workspace_check(body: PackageCheck, request: Request, context=Depends(authenticate)):
        if context.role not in {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}:
            raise HTTPException(403, 'Workspace shipping permission required')
        accounts = await request.app.state.rating.repository.accounts(context)
        return evaluate_package(body, accounts)

    return router
