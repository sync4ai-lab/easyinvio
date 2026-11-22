"""Bounded guest rate estimates using platform credentials only; never buys labels."""
from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, localcontext
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

from cryptography.fernet import Fernet

from backend.agents.models import ConversationalIntent
from backend.entitlements import Plan, capabilities
from backend.integration_policy import integration_enabled
from backend.paf_lookup import PAFLookupUnavailable, uk_postcode
from backend.sendcloud_adapter import ENDPOINT, V3_ENDPOINT, quote_sendcloud, quote_sendcloud_v3

if TYPE_CHECKING:
    import httpx
    from main import Settings, RatingRequest

logger = logging.getLogger('easyinvio.public_estimates')

# Representative routing points, NOT verified customer delivery addresses.
UK_CITY_HUBS: dict[str, str] = {
    'leeds': 'LS1 1AA', 'birmingham': 'B1 1AA', 'london': 'SW1A 1AA',
    'manchester': 'M1 1AE', 'bristol': 'BS1 1AA', 'liverpool': 'L1 1AA',
    'sheffield': 'S1 1AA', 'nottingham': 'NG1 1AA', 'newcastle upon tyne': 'NE1 1AA',
    'cardiff': 'CF10 1AA', 'edinburgh': 'EH1 1AA', 'glasgow': 'G1 1AA',
}


class EstimateUnavailable(ValueError):
    """No trustworthy estimate can be returned within this turn's budget."""


class PostcodeResolver(Protocol):
    async def lookup(self, postcode: str) -> list[Any]: ...
    async def representative_postcode(self, town: str) -> str | None: ...


@dataclass(frozen=True)
class EstimateLocation:
    town: str
    postcode: str
    approximate: bool
    unmatched: bool = False


@dataclass(frozen=True)
class PublicCarrierAccount:
    id: UUID
    provider: Literal['EASYPOST', 'REGIONAL']
    base_url: str
    api_key: str = field(repr=False)
    timeout_seconds: int = 4
    upstream_account_id: str | None = None
    platform_connection_id: UUID | None = None


@dataclass(frozen=True)
class PublicRate:
    carrier: str
    service: str
    price: Decimal
    days: int | None


def public_price(cost: Decimal) -> Decimal:
    """Same standard percentage as the Starter subscription baseline."""
    if not cost.is_finite() or cost <= 0:
        raise EstimateUnavailable('Invalid provider price')
    percent = capabilities(Plan.STARTER).default_markup_percent
    with localcontext() as context:
        context.prec = 50
        wholesale = cost.quantize(Decimal('.01'), rounding=ROUND_CEILING)
        markup = (wholesale * percent / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        return wholesale + markup


def clean_label(value: str) -> str:
    # Provider prose cannot inject links, mentions or WhatsApp formatting.
    value = re.sub(r'https?://\S+', '', value, flags=re.I)
    return re.sub(r'[^\w .+()/:-]', '', value, flags=re.UNICODE).strip()[:80]


class PublicRouteEstimates:
    def __init__(self, settings: Settings, pool: Any, client: httpx.AsyncClient, paf: PostcodeResolver):
        self.settings, self.pool, self.client, self.paf = settings, pool, client, paf
        self.cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self.locations: OrderedDict[str, tuple[float, EstimateLocation]] = OrderedDict()
        self.calls: deque[float] = deque()
        self.lock = asyncio.Lock()  # Single flight, including repeated concurrent requests.

    async def location(self, town: str | None, postcode: str | None) -> EstimateLocation:
        key = json.dumps([town, postcode])
        cached = self.locations.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        normalized_town = ' '.join((town or '').strip().split())
        unmatched = False
        if postcode:
            try:
                normalized = uk_postcode(postcode)
            except ValueError:
                unmatched = True
            else:
                # Failure to reach PAF is not evidence a customer's postcode is wrong.
                premises = await self.paf.lookup(normalized)
                if premises:
                    post_town = premises[0].post_town
                    if normalized_town and normalized_town.casefold() != post_town.casefold():
                        raise EstimateUnavailable('Town and postcode do not match; send the exact town, postcode and country for each end.')
                    result = EstimateLocation(post_town, normalized, False)
                    self.remember_location(key, result)
                    return result
                unmatched = True
        if not normalized_town:
            raise EstimateUnavailable('Send the exact pickup and delivery town, postcode and country.')
        hub = UK_CITY_HUBS.get(normalized_town.casefold())
        if hub is None:
            # One bounded licensed lookup; unknown/ambiguous towns are never geocoded by an LLM.
            hub = await self.paf.representative_postcode(normalized_town)
        if not hub:
            raise EstimateUnavailable('Please send the exact town, full postcode and country for pickup and delivery.')
        result = EstimateLocation(normalized_town, uk_postcode(hub), True, unmatched)
        self.remember_location(key, result)
        return result

    def remember_location(self, key: str, result: EstimateLocation) -> None:
        self.locations[key] = (time.monotonic() + 300, result)
        while len(self.locations) > 256:
            self.locations.popitem(last=False)

    async def accounts(self) -> list[PublicCarrierAccount]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch('''SELECT id,aggregator,api_base_url,credentials_ciphertext,
                credential_key_id,upstream_account_id,timeout_seconds FROM public.platform_carrier_connections
                WHERE is_active AND retired_at IS NULL AND environment=$1
                ORDER BY CASE WHEN api_base_url=$2 THEN 0 WHEN api_base_url=$3 THEN 1 ELSE 2 END,
                priority,id LIMIT 8''', self.settings.provider_environment, V3_ENDPOINT, ENDPOINT)
        result: list[PublicCarrierAccount] = []
        allowed = {V3_ENDPOINT, ENDPOINT, 'https://api.easypost.com/v2', 'https://api.goshippo.com'}
        for row in rows:
            endpoint = row['api_base_url'].rstrip('/')
            if endpoint not in allowed or not integration_enabled(endpoint, self.settings):
                continue
            envelope = json.loads(Fernet(self.settings.credential_keys[row['credential_key_id']].get_secret_value().encode()).decrypt(bytes(row['credentials_ciphertext'])))
            if envelope.get('platform_id') != str(row['id']) or (not isinstance(envelope.get('api_key'), str) or not envelope['api_key'].strip()):
                raise EstimateUnavailable('Platform connection configuration unavailable')
            result.append(PublicCarrierAccount(id=row['id'], provider=row['aggregator'], base_url=endpoint,
                api_key=envelope['api_key'], upstream_account_id=row['upstream_account_id'], platform_connection_id=row['id']))
            if len(result) == 2:
                break
        return result

    async def rates(self, account: PublicCarrierAccount, request: RatingRequest) -> list[PublicRate]:
        if account.base_url == V3_ENDPOINT:
            rows = await quote_sendcloud_v3(self.client, account, request)
        elif account.base_url == ENDPOINT:
            methods = self.settings.sendcloud_methods.get(account.id, [])
            # Legacy methods require administrator-verified limits and real service names.
            from backend.package_sets import package_charge
            charge = package_charge(request.dimensions, request.weights_kg)
            charged_request = request.model_copy(update={'weights_kg':[Decimal(piece['billable_weight_kg']) for piece in charge['packages']]})
            rows = await quote_sendcloud(self.client, account, charged_request, methods)
            if rows and any(not method.service_name for method in methods):
                from backend.sendcloud_adapter import sendcloud_credentials
                response = await self.client.get(ENDPOINT+'/shipping_methods', auth=sendcloud_credentials(account.api_key), timeout=3, follow_redirects=False)
                if response.status_code != 200 or len(response.content) > 1_000_000:
                    raise EstimateUnavailable('Carrier service names are unavailable')
                names = {str(method['id']):str(method['name']) for method in response.json().get('shipping_methods',[])[:1000]}
                for row in rows:
                    identity = row['upstream_rate_id']
                    if identity in names:
                        row.setdefault('execution_details',{})['display_service_name']=names[identity]
        else:
            from main import EasyPostStrategy, WholesaleRate
            from backend.automation_three_partners import NativeRateStrategy
            strategy = (EasyPostStrategy(self.client, account) if account.base_url.endswith('/v2')
                else NativeRateStrategy(self.client, account, WholesaleRate, self.settings.provider_environment))
            values = await strategy.rates(request)
            rows = [value.model_dump() for value in values]
        result: list[PublicRate] = []
        for row in rows:
            if row.get('currency') != 'GBP':
                continue
            details = row.get('execution_details') or {}
            carrier = clean_label(str(details.get('display_carrier_name') or row['carrier_code']))
            service = clean_label(str(details.get('display_service_name') or row['service_code']))
            days = row.get('delivery_days')
            if type(days) is not int or not 0 < days <= 365:
                days = None
            result.append(PublicRate(carrier, service, public_price(Decimal(str(row['wholesale_cost']))), days))
        return result

    async def estimate(self, facts: ConversationalIntent) -> str:
        from main import Address, Dimensions, RatingRequest
        from backend.whatsapp_progressive import quote_link
        handoff_link = quote_link(self.settings, facts)  # Validate the configured origin before any paid lookup.
        if facts.origin_country != 'GB' or facts.destination_country != 'GB' or facts.cargo_type != 'PARCEL':
            return 'For this service, send exact pickup and delivery town, postcode and country and continue in your workspace: '+handoff_link
        if not facts.dimensions_cm:
            return 'What is the packed box size in cm (length x width x height)? Please also provide the exact pickup and delivery town, postcode and country for the best estimate.'
        key = facts.model_dump_json(include={'weight_kg','dimensions_cm','origin_city','destination_city','origin_postal_code','destination_postal_code','origin_country','destination_country'})
        async with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            now = time.monotonic()
            while self.calls and self.calls[0] <= now - 60:
                self.calls.popleft()
            if len(self.calls) >= 12:
                return 'Live route estimates are busy. Continue with your details: '+handoff_link
            self.calls.append(now)
            try:
                async with asyncio.timeout(8):
                    origin, destination = await asyncio.gather(self.location(facts.origin_city, facts.origin_postal_code), self.location(facts.destination_city, facts.destination_postal_code))
                    addresses = [Address(name='Route estimate', line1='City-centre estimate', city=place.town, postal_code=place.postcode, country_code='GB') for place in (origin, destination)]
                    request = RatingRequest(origin=addresses[0], destination=addresses[1], weights_kg=[facts.weight_kg],
                        dimensions=[Dimensions(**dict(zip(('length_cm','width_cm','height_cm'), facts.dimensions_cm)))], currency='GBP')
                    rates: list[PublicRate] = []
                    for account in await self.accounts():
                        try:
                            async with asyncio.timeout(4):
                                rates = await self.rates(account, request)
                        except Exception as exc:
                            logger.info('guest_rate_unavailable error_type=%s', type(exc).__name__)
                        if rates:
                            break
                    if not rates:
                        raise EstimateUnavailable('Live carrier rates are unavailable right now. Please try later or use the shipment form.')
                    handoff = facts.model_copy(update={prefix+'_postal_code':None for prefix,place in [('origin',origin),('destination',destination)] if place.approximate})
                    result = format_estimate(facts, origin, destination, rates, quote_link(self.settings, handoff))
            except (EstimateUnavailable, PAFLookupUnavailable) as exc:
                result = str(exc)+'\nContinue with your details: '+handoff_link
            except Exception as exc:
                logger.info('guest_estimate_unavailable error_type=%s', type(exc).__name__)
                result = 'Live route estimates are temporarily unavailable. Continue with your details: '+handoff_link
            self.cache[key] = (time.monotonic() + 120, result)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return result


def format_estimate(facts: ConversationalIntent, origin: EstimateLocation, destination: EstimateLocation, rates: list[PublicRate], link: str) -> str:
    unique: dict[tuple[str, str], PublicRate] = {}
    for rate in sorted(rates, key=lambda r: (r.price, r.carrier, r.service)):
        unique.setdefault((rate.carrier.casefold(),rate.service.casefold()),rate)
    lines = ['\U0001f4e6 *EasyInvio Live Route Estimate*',
        f'{facts.weight_kg} kg | '+ ' x '.join(str(x) for x in facts.dimensions_cm or [])+f' cm ({origin.town} -> {destination.town})','']
    for index, rate in enumerate(list(unique.values())[:2], 1):
        transit = f'{rate.days} day'+('s' if rate.days != 1 else '') if rate.days else 'transit time not supplied'
        lines.append(f'{index}. *{rate.carrier} {rate.service}* - *\u00a3{rate.price:.2f}* excl. VAT ({transit})')
    if origin.unmatched or destination.unmatched:
        lines.append('Exact postcode match not found for '+', '.join(place.town for place in (origin,destination) if place.unmatched)+'. Using a representative town postcode for this estimate.')
    if origin.approximate or destination.approximate:
        lines.append(f'Estimated using representative postcodes: {origin.postcode} -> {destination.postcode}.')
    else:
        lines.append(f'Route postcodes: {origin.postcode} -> {destination.postcode}.')
    lines.extend(['Confirm exact pickup and delivery town, postcode, country and full addresses to check the final label price.',link])
    return '\n'.join(lines)
