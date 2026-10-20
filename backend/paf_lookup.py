"""Asynchronous licensed PAF lookup boundary. Postcode syntax is not delivery proof."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

if TYPE_CHECKING:
    from main import Address


class PAFLookupUnavailable(ValueError):
    """No validated delivery points can safely be supplied this turn."""


def uk_postcode(value: str) -> str:
    compact = re.sub(r'\s+', '', value).upper()
    if not re.fullmatch(r'(?:GIR0AA|[A-Z]{1,2}[0-9][A-Z0-9]?[0-9][A-Z]{2})', compact):
        raise ValueError('Enter a complete UK postcode.')
    return compact[:-3] + ' ' + compact[-3:]


class PAFPremise(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    udprn: str = Field(pattern=r'^\d{1,12}$')
    postcode: str
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    post_town: str = Field(min_length=1, max_length=100)
    organisation: str | None = Field(default=None, max_length=200)
    building_number: str = ''
    building_name: str = ''
    sub_building_name: str = ''
    dependent_thoroughfare: str = ''
    thoroughfare: str = ''

    def address(self, contact: str) -> Address:
        from main import Address
        return Address(name=contact, company=self.organisation, line1=self.line1,
                       line2=self.line2, city=self.post_town,
                       postal_code=uk_postcode(self.postcode), country_code='GB')

    @property
    def label(self) -> str:
        return ', '.join(value for value in (self.line1, self.line2, self.post_town, self.postcode) if value)


class PAFClient(Protocol):
    async def lookup(self, postcode: str) -> list[PAFPremise]: ...


class IdealPostcodesClient:
    """Fixed HTTPS origin, bounded pages, PAF-only delivery points, no guessed streets."""
    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr):
        self.client, self.api_key = client, api_key

    async def lookup(self, postcode: str) -> list[PAFPremise]:
        normalized = uk_postcode(postcode)
        if not self.api_key.get_secret_value():
            raise PAFLookupUnavailable('UK address lookup is not configured. Please use the web shipment form or contact support.')
        premises: list[PAFPremise] = []
        try:
            for page in range(11):
                response = await self.client.get(
                    'https://api.ideal-postcodes.co.uk/v1/postcodes/' + normalized.replace(' ', ''),
                    headers={'Authorization': 'Bearer ' + self.api_key.get_secret_value()},
                    params={'page': page, 'dataset': 'paf', 'context': 'GBR'},
                    timeout=4, follow_redirects=False)
                if response.status_code == 404:
                    return premises
                if response.status_code != 200 or len(response.content) > 2_000_000:
                    raise ValueError('Lookup refused')
                data = response.json()
                rows = data['result']
                if data['code'] != 2000 or not isinstance(rows, list) or len(rows) > 100:
                    raise ValueError('Invalid lookup envelope')
                for row in rows:
                    if (uk_postcode(row['postcode']) != normalized
                            or row.get('dataset', 'paf') != 'paf'
                            or row.get('country_iso_2', 'GB') != 'GB'
                            or not any(row.get(key) for key in ('building_number', 'building_name',
                                'sub_building_name', 'po_box', 'organisation_name'))):
                        raise ValueError('Invalid delivery point')
                    premise = PAFPremise(udprn=str(row['udprn']), postcode=normalized,
                        line1=row['line_1'], line2=', '.join(filter(None, (row.get('line_2'), row.get('line_3')))) or None,
                        post_town=row['post_town'], organisation=row.get('organisation_name') or None,
                        building_number=row.get('building_number', ''), building_name=row.get('building_name', ''),
                        sub_building_name=row.get('sub_building_name', ''),
                        dependent_thoroughfare=row.get('dependant_thoroughfare', ''), thoroughfare=row.get('thoroughfare', ''))
                    premise.address('Validation')
                    premises.append(premise)
                total = data.get('total')
                if (isinstance(total, int) and len(premises) >= total) or len(rows) < 100:
                    if len({item.udprn for item in premises}) != len(premises):
                        raise ValueError('Duplicate delivery points')
                    return premises
            raise ValueError('Too many delivery points')
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise PAFLookupUnavailable('UK address lookup is temporarily unavailable. Reply Retry or use the web shipment form.') from None
