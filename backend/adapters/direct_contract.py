"""Typed internal contract for certified direct transports, not a carrier wire schema."""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol, TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from main import RatingRequest, WholesaleRate


class DirectModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class PAFDeliveryAddress(DirectModel):
    premise: str = Field(min_length=1, max_length=200)
    thoroughfare: str = Field(min_length=1, max_length=200)
    dependent_thoroughfare: str = Field(default='', max_length=200)
    post_town: str = Field(min_length=1, max_length=100)
    postcode: str = Field(pattern=r'^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$')
    udprn: str = Field(pattern=r'^[0-9]{1,8}$')


class DirectParcel(DirectModel):
    weight_grams: int = Field(gt=0)
    length_cm: Decimal = Field(gt=0, allow_inf_nan=False)
    width_cm: Decimal = Field(gt=0, allow_inf_nan=False)
    height_cm: Decimal = Field(gt=0, allow_inf_nan=False)
    packaging_format: Literal['Parcel', 'LargeLetter']

    @classmethod
    def from_rating(cls, request: RatingRequest) -> DirectParcel:
        from main import ProviderFailure
        if (request.origin.country_code != 'GB' or request.destination.country_code != 'GB'
                or request.cargo_type not in {'PARCEL', 'LETTER'}
                or len(request.weights_kg) != 1 or len(request.dimensions) != 1):
            raise ProviderFailure('DIRECT_DOMESTIC_SINGLE_PIECE_REQUIRED')
        grams = request.weights_kg[0] * Decimal(1000)
        if grams != grams.to_integral_value():
            raise ProviderFailure('DIRECT_WEIGHT_GRAM_PRECISION_REQUIRED')
        box = request.dimensions[0]
        return cls(weight_grams=int(grams), length_cm=box.length_cm, width_cm=box.width_cm,
                   height_cm=box.height_cm,
                   packaging_format='LargeLetter' if request.cargo_type == 'LETTER' else 'Parcel')


class DirectLabel(DirectModel):
    tracking_number: str = Field(min_length=1, max_length=200)
    provider_reference: str = Field(min_length=1, max_length=200)
    format: Literal['PDF', 'ZPL']
    document: bytes = Field(min_length=1, max_length=5_000_000)

    @model_validator(mode='after')
    def document_format(self):
        if self.format == 'PDF' and not self.document.startswith(b'%PDF-'):
            raise ValueError('Carrier label must contain the declared PDF format')
        if self.format == 'ZPL' and not (self.document.lstrip().startswith(b'^XA') and self.document.rstrip().endswith(b'^XZ')):
            raise ValueError('Carrier label must contain the declared ZPL format')
        return self


class DirectManifest(DirectModel):
    provider_reference: str = Field(min_length=1, max_length=200)
    document_pdf: bytes = Field(min_length=5, max_length=5_000_000)

    @field_validator('document_pdf')
    @classmethod
    def pdf_header(cls, value: bytes) -> bytes:
        if not value.startswith(b'%PDF-'):
            raise ValueError('Carrier manifest must contain a PDF')
        return value


class DirectCarrierContract(Protocol):
    """Implemented only against an account's issued specification and sandbox fixtures.

    Transport owns verified authentication, negotiated service mapping, surcharges,
    bounded HTTP responses and purchase uncertainty. No automatic mutation replay.
    """

    async def quote(self, request: RatingRequest, parcel: DirectParcel) -> list[WholesaleRate]: ...

    async def purchase_label(self, shipment_data: dict) -> DirectLabel: ...

    async def create_manifest(self, shipping_account_id: str) -> DirectManifest: ...
