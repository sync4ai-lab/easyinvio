"""Server-owned UK delivery-point checks shared by quotes and label purchases."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable

import httpx
from fastapi import HTTPException
from pydantic import SecretStr
from backend.paf_lookup import IdealPostcodesClient, PAFLookupUnavailable

if TYPE_CHECKING:
    from main import Address, Settings


def configured(settings: Settings) -> bool:
    key = getattr(settings, 'ideal_postcodes_api_key', SecretStr(''))
    return bool(key.get_secret_value())


def comparable(value: str | None) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[,.]', ' ', value or '')).strip().casefold()


async def verify_shipping_addresses(client: httpx.AsyncClient, settings: Settings,
                                    addresses: Iterable[tuple[str, Address]]) -> None:
    """Never trust a browser's verified flag. Match complete addresses to PAF.

    TEST without credentials permits synthetic fixtures; LIVE never falls back
    to syntax checks for UK addresses. Call before reserve/submit, never during
    reconciliation of an already submitted carrier purchase.
    """
    uk = [(label, address) for label, address in addresses if address.country_code == 'GB']
    if not uk:
        return
    if not configured(settings):
        if getattr(settings, 'provider_environment', 'TEST') == 'LIVE':
            raise HTTPException(503, 'UK address verification is not configured. Live UK booking is blocked until the platform administrator enables PAF lookup.')
        return
    lookup = IdealPostcodesClient(client, settings.ideal_postcodes_api_key)
    options_by_postcode = {}
    for label, address in uk:
        try:
            if address.postal_code not in options_by_postcode:
                options_by_postcode[address.postal_code] = await lookup.lookup(address.postal_code)
            options = options_by_postcode[address.postal_code]
        except PAFLookupUnavailable:
            raise HTTPException(503, f'{label} address verification is unavailable. Retry before booking; no new label has been purchased.') from None
        if not any(comparable(address.line1) == comparable(option.line1)
                   and comparable(address.line2) == comparable(option.line2)
                   and comparable(address.city) == comparable(option.post_town) for option in options):
            raise HTTPException(422, f'{label} address does not match a Royal Mail PAF delivery point for {address.postal_code}. Use Find UK address and select the exact building or flat, including its post town.')
