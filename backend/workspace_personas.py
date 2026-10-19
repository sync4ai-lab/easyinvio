"""Shared account profiles and exact consumer pricing; no parallel wallets."""
from decimal import Decimal
from types import SimpleNamespace
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.ai_engine import strict_decimal


class PersonalProfile(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    full_name: str = Field(min_length=2, max_length=200)
    billing_email: str = Field(max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    phone_e164: str = Field(pattern=r'^\+[1-9][0-9]{7,14}$')

    @field_validator('full_name')
    @classmethod
    def name_text(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError('Enter your name without control characters')
        return value


def storage_profile(profile):
    if not isinstance(profile, PersonalProfile):
        return profile
    return SimpleNamespace(company_name=profile.full_name, contact_name=profile.full_name,
        billing_email=profile.billing_email, phone_e164=profile.phone_e164,
        country_code=None, company_registration_number=None, tax_id=None,
        address_line1=None, address_line2=None, city=None, postal_code=None,
        model_dump_json=profile.model_dump_json)


async def individual_policy(connection):
    row = await connection.fetchrow('''SELECT individual_global_markup_percent,version
        FROM public.individual_pricing_settings WHERE singleton=true''')
    percent = strict_decimal(row['individual_global_markup_percent']) if row else Decimal('20.00')
    if not percent.is_finite() or percent < 0 or percent > Decimal('999.99') or percent.as_tuple().exponent < -2:
        raise ValueError('Invalid individual pricing configuration')
    return {'workspace_type': 'INDIVIDUAL', 'markup_percent': str(percent),
        'version': row['version'] if row else 0, 'source': 'GLOBAL_INDIVIDUAL' if row else 'DEFAULT_INDIVIDUAL'}
