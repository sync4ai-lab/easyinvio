"""Bounded typed conversation drafts and deterministic location extraction."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import pycountry

from pydantic import Field

from backend.agents.models import ConversationalIntent, StrictOutput
from backend.ai_engine import country_code, strict_decimal


def explicit_country(value):
    if value.strip().upper() == 'UK':
        return 'GB'
    try:
        return country_code(value)
    except ValueError:
        try:
            return pycountry.countries.lookup(value).alpha_2
        except LookupError:
            raise ValueError('Use a country name or ISO country code') from None


class ConversationDraft(StrictOutput):
    action: str = Field(pattern=r'^(QUOTE|TRACK_PACKAGE|FILE_CLAIM|TRIGGER_RETURN)$')
    intent: ConversationalIntent
    waiting_for: str = ''
    origin_address: dict | None = None
    destination_address: dict | None = None
    dimensions: dict | None = None
    expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=15))
    assistance_id: str | None = None

    def active(self, context):
        return (self.expires_at.tzinfo is not None and self.expires_at > datetime.now(timezone.utc)
                and self.assistance_id == (str(context.assistance_session_id) if context.assistance_session_id else None))


def location(value):
    """Extract explicit country and postcode/city; do not geocode by guessing."""
    value = value.strip().rstrip('.?!')
    try:
        return {'country': explicit_country(value)}
    except ValueError:
        pass
    country = None
    words = value.rsplit(' ', 1)
    if len(words) == 2 and re.fullmatch(r'[A-Za-z]{2,3}', words[1]):
        try:
            country = explicit_country(words[1])
            value = words[0]
        except ValueError:
            pass
    if country is None:
        first = value.split(' ', 1)
        if len(first) == 2 and re.fullmatch(r'[A-Za-z]{2,3}', first[0]):
            try:
                country, value = explicit_country(first[0]), first[1]
            except ValueError:
                pass
    postal = re.search(r'\b(?:[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}|[A-Z][0-9][A-Z]\s*[0-9][A-Z][0-9]|[0-9]{4,10}(?:-[0-9]{3,4})?)\b', value, re.I)
    if postal:
        result = {'postal_code': postal[0].upper()}
        city = (value[:postal.start()] + value[postal.end():]).strip(' ,')
        if city:
            result['city'] = city
        if country:
            result['country'] = country
        return result
    key = 'postal_code' if any(character.isdigit() for character in value) else 'city'
    if len(value) > (30 if key == 'postal_code' else 100):
        raise ValueError('Use a postcode or a short city name')
    result = {key: value.upper() if key == 'postal_code' else value}
    if country:
        result['country'] = country
    return result


def explicit_quote(text):
    if not re.search(r'\b(?:quote|rates?|shipping price)\b', text, re.I):
        return None
    values = {'intent': 'QUOTE'}
    weight = re.search(r'(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(?:kg|kilograms?)\b', text, re.I)
    if weight:
        value = strict_decimal(weight[1].replace(',', '.'))
        if value <= 0 or value > 1000 or value != value.quantize(Decimal('.001')):
            raise ValueError('Enter a positive weight up to 1000 kg, with at most three decimal places')
        values['weight_kg'] = str(value)
    route = re.search(r'\broute\s+([A-Z0-9_]{1,40})\b', text, re.I)
    if route:
        values['route_code'] = route[1].upper()
    corridor = re.search(r'\bfrom\s+(.+?)\s+to\s+(.+?)(?:\s+route\s+\w+|[?!]|$)', text, re.I)
    if corridor:
        for prefix, value in zip(('origin', 'destination'), corridor.groups()):
            for key, fact in location(value).items():
                values[prefix + '_' + key] = fact
    return ConversationalIntent(**values)


def merge_quote(draft, proposed):
    values = draft.intent.model_dump()
    for field in ('weight_kg', 'origin_country', 'destination_country', 'origin_postal_code',
                  'destination_postal_code', 'origin_city', 'destination_city', 'route_code'):
        value = getattr(proposed, field)
        if value is not None:
            values[field] = value
    for prefix in ('origin', 'destination'):
        if any(values[prefix + '_' + key] != getattr(draft.intent, prefix + '_' + key)
               for key in ('country', 'postal_code', 'city')):
            setattr(draft, prefix + '_address', None)
    draft.intent = ConversationalIntent(**values)


def collect_reply(draft, text):
    """Consume only the field format that was explicitly requested last turn."""
    from main import Address, Dimensions
    field = draft.waiting_for
    if field == 'postcodes':
        parts = [part.strip() for part in text.split(',')]
        if len(parts) != 2 or any(not value or len(value) > 30 for value in parts):
            raise ValueError('Reply with Origin Postcode, Destination Postcode.')
        merge_quote(draft, ConversationalIntent(intent='QUOTE', origin_postal_code=parts[0], destination_postal_code=parts[1]))
    elif field == 'countries':
        parts = [part.strip() for part in text.split(',')]
        if len(parts) != 2:
            raise ValueError('Reply with Origin Country, Destination Country, for example GB, FR.')
        merge_quote(draft, ConversationalIntent(intent='QUOTE', origin_country=explicit_country(parts[0]), destination_country=explicit_country(parts[1])))
    elif field == 'weight':
        weight = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*(?:kg)?\s*', text, re.I)
        if not weight:
            raise ValueError('Reply with packed weight in kg, for example 3.5 kg.')
        value = strict_decimal(weight[1].replace(',', '.'))
        if value <= 0 or value > 1000 or value != value.quantize(Decimal('.001')):
            raise ValueError('Use a positive packed weight up to 1000 kg with at most three decimal places.')
        merge_quote(draft, ConversationalIntent(intent='QUOTE', weight_kg=str(value)))
    elif field == 'dimensions':
        parts = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*[x×,]\s*(\d+(?:\.\d+)?)\s*[x×,]\s*(\d+(?:\.\d+)?)\s*(?:cm)?\s*', text, re.I)
        if not parts:
            raise ValueError('Reply with measured length x width x height in cm, for example 30 x 20 x 10.')
        draft.dimensions = Dimensions(**dict(zip(('length_cm', 'width_cm', 'height_cm'), parts.groups()))).model_dump(mode='json')
    elif field in {'origin_address', 'destination_address'}:
        prefix = field.removesuffix('_address')
        parts = [part.strip() for part in text.split(';')]
        if len(parts) not in (3, 4):
            raise ValueError('Reply with contact name; street address; city. Add any state/province after the city with a fourth semicolon-separated field.')
        address = Address(name=parts[0], line1=parts[1], city=parts[2],
            postal_code=getattr(draft.intent, prefix + '_postal_code'), country_code=getattr(draft.intent, prefix + '_country'),
            state=parts[3] if len(parts) == 4 else None)
        setattr(draft, field, address.model_dump(mode='json'))
    elif field == 'retry' and text.strip().lower() != 'retry':
        raise ValueError('Reply Retry or Cancel.')
    return draft
