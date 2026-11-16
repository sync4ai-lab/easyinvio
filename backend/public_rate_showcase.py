"""Cached public marketing examples. GET never calls a provider or selects customer accounts."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()
logger = logging.getLogger(__name__)
# Public venue locations are fixed examples, never sender/recipient records.
PLACES = {
    'london': ('London', 'Great Russell Street', 'WC1B 3DG', 'GB'),
    'manchester': ('Manchester', "St Peter's Square", 'M2 5PD', 'GB'),
    'birmingham': ('Birmingham', 'Centenary Square', 'B1 2ND', 'GB'),
    'edinburgh': ('Edinburgh', '7-9 George IV Bridge', 'EH1 1EG', 'GB'),
    'bristol': ('Bristol', 'College Green', 'BS1 5TL', 'GB'),
    'leeds': ('Leeds', 'Calverley Street', 'LS1 3AB', 'GB'),
    'paris': ('Paris', 'Rue de Rivoli', '75001', 'FR'),
    'berlin': ('Berlin', 'Schlossplatz', '10178', 'DE'),
    'amsterdam': ('Amsterdam', 'Museumstraat 1', '1071 XX', 'NL'),
}
# Stable public IDs are the only route hints accepted by onboarding; no addresses in URLs.
SCENARIOS = (
    ('uk-small', 'london', 'manchester', '0.5', (20, 15, 5)),
    ('uk-everyday', 'london', 'birmingham', '1', (25, 20, 10)),
    ('uk-medium', 'london', 'edinburgh', '2.5', (30, 20, 10)),
    ('uk-large', 'manchester', 'bristol', '5', (40, 30, 20)),
    ('uk-heavy', 'leeds', 'london', '10', (50, 35, 25)),
    ('fr-small', 'london', 'paris', '1', (25, 20, 10)),
    ('fr-large', 'london', 'paris', '5', (40, 30, 20)),
    ('de-medium', 'london', 'berlin', '2.5', (30, 20, 10)),
    ('nl-small', 'london', 'amsterdam', '1', (25, 20, 10)),
    ('nl-heavy', 'manchester', 'amsterdam', '10', (50, 35, 25)),
)


def catalog():
    return [{'id': key, 'origin': PLACES[origin][0], 'destination': PLACES[destination][0],
             'destination_country': PLACES[destination][3], 'weight_kg': weight,
             'dimensions_cm': list(size), 'parcel_type': 'PARCEL', 'currency': 'GBP',
             'status': 'pending', 'price_ex_tax': None, 'carrier': None, 'service': None,
             'delivery_days': None, 'transport_mode': None, 'checked_at': None}
            for key, origin, destination, weight, size in SCENARIOS]


def configuration(settings):
    if not getattr(settings, 'public_rate_showcase_enabled', False):
        return None
    tenant = getattr(settings, 'public_rate_showcase_tenant_id', None)
    accounts = getattr(settings, 'public_rate_showcase_account_ids', [])
    # Explicit publication opt-in and live credentials required, never inferred from a user session.
    if not tenant or not accounts or getattr(settings, 'provider_environment', None) != 'LIVE':
        return None
    tenant, accounts = UUID(str(tenant)), frozenset(UUID(str(value)) for value in accounts)
    key = hashlib.sha256(('v1|' + str(tenant) + '|' + '|'.join(sorted(map(str, accounts)))).encode()).hexdigest()
    return tenant, accounts, key


class ApprovedRepository:
    def __init__(self, repository, tenant, account_ids):
        self.repository, self.tenant, self.account_ids = repository, tenant, account_ids

    async def accounts(self, context, **kwargs):
        if context.tenant_id != self.tenant:
            raise ValueError('Public example tenant mismatch')
        accounts = await self.repository.accounts(context, **kwargs)
        selected = [account for account in accounts if account.id in self.account_ids and account.tenant_id == self.tenant]
        # Missing/reassigned accounts fail closed instead of quietly broadening the comparison.
        if {account.id for account in selected} != self.account_ids:
            raise ValueError('Approved public example connections unavailable')
        return selected

    async def load(self, context, currency):
        if context.tenant_id != self.tenant:
            raise ValueError('Public example tenant mismatch')
        return await self.repository.load(context, currency)


def publish_price(example, result, checked_at):
    candidates = [rate for rate in result.rates
                  if rate.currency == 'GBP' and rate.label_purchase_available
                  and Decimal(rate.client_price_ex_tax).is_finite() and Decimal(rate.client_price_ex_tax) > 0]
    if not candidates:
        return {**example, 'status': 'unavailable', 'checked_at': checked_at.isoformat()}
    selected = min(candidates, key=lambda rate: Decimal(rate.client_price_ex_tax))
    details = getattr(selected, 'execution_details', {}) or {}
    mode = details.get('transport_mode')
    # Never guess transport mode from a carrier/service name or destination.
    return {**example, 'status': 'available', 'price_ex_tax': str(selected.client_price_ex_tax),
            'carrier': str(selected.carrier_code)[:100], 'service': str(selected.service_code)[:120],
            'delivery_days': selected.delivery_days, 'transport_mode': mode if mode in {'ROAD', 'AIR', 'SEA'} else None,
            'checked_at': checked_at.isoformat()}


class PublicRateShowcase:
    def __init__(self, pool, rating, settings, *, now=None):
        self.pool, self.rating, self.settings = pool, rating, settings
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._read_lock = asyncio.Lock()
        self._memo = None
        self._memo_until = self.now()

    async def read(self):
        config = configuration(self.settings)
        if config is None:
            return {'status': 'unconfigured', 'examples': catalog()}
        async with self._read_lock:
            if self._memo is not None and self.now() < self._memo_until:
                return self._memo
            try:
                async with asyncio.timeout(4):
                    async with self.pool.acquire() as connection:
                        row = await connection.fetchrow('SELECT payload FROM public.public_rate_showcase_cache WHERE source_key=$1', config[2])
                payload = json.loads(row['payload']) if row and isinstance(row['payload'], str) else row['payload'] if row else None
                examples = payload.get('examples', []) if isinstance(payload, dict) else []
                # Project into a fixed public schema; even a corrupt cache cannot publish unknown fields.
                safe = []
                for base in catalog():
                    stored = next((item for item in examples if item.get('id') == base['id']), {})
                    item = {key: stored.get(key, value) for key, value in base.items()}
                    item.update({key: base[key] for key in ('id', 'origin', 'destination', 'destination_country', 'weight_kg', 'dimensions_cm', 'parcel_type', 'currency')})
                    if item['price_ex_tax'] is not None:
                        value = Decimal(str(item['price_ex_tax']))
                        if not value.is_finite() or value <= 0 or value > 100000:
                            raise ValueError('Invalid public price')
                    checked = datetime.fromisoformat(item['checked_at']) if item['checked_at'] else None
                    if checked and (checked.date() != self.now().date() or checked > self.now()):
                        item.update(status='stale', price_ex_tax=None, carrier=None, service=None, delivery_days=None, transport_mode=None)
                    safe.append(item)
                ready = sum(item['status'] == 'available' and item['price_ex_tax'] is not None for item in safe)
                result = {'status': 'ready' if ready == 10 else 'partial' if ready else 'pending', 'examples': safe}
            except (asyncpg.PostgresError, TimeoutError, ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
                result = {'status': 'pending', 'examples': catalog()}
            self._memo = result
            midnight=(self.now()+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
            self._memo_until = min(self.now()+timedelta(seconds=60),midnight)
            return result

    async def refresh(self):
        config = configuration(self.settings)
        if config is None:
            return False
        tenant, accounts, key = config
        # A session advisory lock and durable attempt timestamp bound provider work across replicas.
        async with self.pool.acquire() as connection:
            locked = await connection.fetchval("SELECT pg_try_advisory_lock(hashtextextended($1,0))", 'public-rate-showcase:' + key)
            if not locked:
                return False
            try:
                row = await connection.fetchrow('SELECT attempted_at,payload FROM public.public_rate_showcase_cache WHERE source_key=$1', key)
                now = self.now()
                if row and row['attempted_at'] > now - timedelta(hours=1):
                    return False
                old = json.loads(row['payload']) if row and isinstance(row['payload'], str) else row['payload'] if row else {}
                existing = {item['id']: item for item in (old or {}).get('examples', [])}
                if existing and all(item.get('status') == 'available' and str(item.get('checked_at', ''))[:10] == now.date().isoformat() for item in existing.values()) and len(existing) == 10:
                    return False
                await connection.execute("""INSERT INTO public.public_rate_showcase_cache(source_key,attempted_at,payload)
                    VALUES($1,$2,$3::jsonb) ON CONFLICT(source_key) DO UPDATE SET attempted_at=EXCLUDED.attempted_at""", key, now, json.dumps(old or {}))
                from main import RatingService, RatingRequest, TenantContext
                repository = ApprovedRepository(self.rating.repository, tenant, accounts)
                # Validate the entire opt-in set before making any upstream request.
                context = TenantContext(tenant, UUID(int=0), 'OWNER', '')
                await repository.accounts(context)
                rating = RatingService(self.rating.client, repository, self.settings, pool=self.rating.pool)
                semaphore = asyncio.Semaphore(2)
                async def quote(spec, example):
                    prior = existing.get(example['id'])
                    if prior and prior.get('status') == 'available' and str(prior.get('checked_at',''))[:10] == now.date().isoformat():
                        return prior
                    _, origin, destination, weight, size = spec
                    def address(place):
                        city, line1, postcode, country = PLACES[place]
                        return {'name': 'EasyInvio public rate example', 'line1': line1, 'city': city, 'postal_code': postcode, 'country_code': country}
                    body = RatingRequest(origin=address(origin), destination=address(destination), weights_kg=[weight],
                                         dimensions=[dict(zip(('length_cm','width_cm','height_cm'), size))], currency='GBP')
                    async with semaphore:
                        try:
                            async with asyncio.timeout(50):
                                result = await rating.quote(context, body, provider_deadline=35)
                            return publish_price(example, result, self.now())
                        except Exception:
                            logger.warning('Public rate example unavailable scenario=%s', example['id'])
                            return {**example, 'status': 'unavailable', 'checked_at': self.now().isoformat()}
                examples = await asyncio.gather(*(quote(spec, item) for spec, item in zip(SCENARIOS, catalog(), strict=True)))
                await connection.execute('UPDATE public.public_rate_showcase_cache SET payload=$2::jsonb WHERE source_key=$1', key, json.dumps({'examples': examples}))
                self._memo = None
                return True
            finally:
                await connection.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', 'public-rate-showcase:' + key)

    async def worker(self):
        while True:
            try:
                await self.refresh()
            except Exception:
                logger.warning('Public rate refresh deferred; verify publication configuration and migration 050')
            await asyncio.sleep(300)


@router.get('/api/v1/public/rate-showcase')
async def public_rates(request: Request, response: Response):
    if request.query_params:
        raise HTTPException(400, 'This endpoint serves fixed public examples only')
    now=datetime.now(timezone.utc)
    midnight=(now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    response.headers['Cache-Control'] = 'public, max-age='+str(min(60,max(0,int((midnight-now).total_seconds()))))
    if getattr(request.app.state, 'local_preview', False):
        return {'status': 'local-preview', 'examples': catalog()}
    service = getattr(request.app.state, 'public_rate_showcase', None)
    return await service.read() if service else {'status': 'pending', 'examples': catalog()}


async def refresh_once():
    """Operator command: rates only, no queue consumers, label purchases or session bootstrap."""
    import httpx
    from main import Settings, RatingService, SupabaseRepository, configure_pricing_pool
    from backend.database_tls import database_tls_context
    settings = Settings()
    if configuration(settings) is None:
        raise RuntimeError('Configure approved LIVE marketing workspace and account IDs first')
    pool = await asyncpg.create_pool(settings.database_url.get_secret_value(), min_size=1, max_size=5,
        ssl=database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict), command_timeout=20)
    try:
        configure_pricing_pool(pool)
        async with httpx.AsyncClient(trust_env=False, timeout=35) as client:
            service = PublicRateShowcase(pool, RatingService(client, SupabaseRepository(client, settings), settings, pool=pool), settings)
            await service.refresh()
    finally:
        configure_pricing_pool(None)
        await pool.close()


if __name__ == '__main__':
    asyncio.run(refresh_once())
