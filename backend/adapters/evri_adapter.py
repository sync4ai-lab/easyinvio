"""Evri direct provision; no guessed enterprise endpoint, signing or QR generation."""
from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from backend.adapters.direct_contract import DirectModel, DirectParcel
from backend.adapters.royal_mail_adapter import RoyalMailStrategy


class EvriDropoffBarcode(DirectModel):
    barcode: str = Field(pattern=r'^[0-9]{16}$')
    qr_image: bytes = Field(min_length=1, max_length=5_000_000)


class EvriStrategy(RoyalMailStrategy):
    carrier_code = 'EVRI'
    policy_code = 'evri'

    @staticmethod
    def postable_height_candidate(parcel: DirectParcel) -> bool:
        # Height alone is not evidence of contractual Postable eligibility.
        return parcel.height_cm <= Decimal('3')

    @staticmethod
    def extract_dropoff_barcode(barcode: str, qr_image: bytes) -> EvriDropoffBarcode:
        from main import ProviderFailure
        from backend.logistics_media import normalize_image
        try:
            image, _ = normalize_image(qr_image)
            return EvriDropoffBarcode(barcode=barcode, qr_image=image)
        except (ValueError, TypeError, OSError):
            raise ProviderFailure('INVALID_CARRIER_DROPOFF_ASSET') from None
