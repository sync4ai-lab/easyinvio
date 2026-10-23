"""Explicit in-memory IO boundaries for the master API/component matrix.

The real rating, calibrated pricing, lifecycle and finance code executes here.
This SQL double checks tenant bindings and models transactions and advisory locks;
it does not establish PostgreSQL locking, RLS or provider integration acceptance.
"""

import asyncio
import copy
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import main


TENANT_A = UUID('10000000-0000-4000-8000-000000000001')
TENANT_B = UUID('10000000-0000-4000-8000-000000000002')
USER_A = UUID('20000000-0000-4000-8000-000000000001')


class MatrixPool:
    """Fail closed on unimplemented SQL; keep financial snapshots as Decimal."""

    def __init__(self):
        self.closed = False
        self.started = False
        self.calls = []
        self.lock = asyncio.Lock()
        self.advisory = set()
        self.contended = asyncio.Event()
        self.purchase_entered = asyncio.Event()
        self.purchase_release = asyncio.Event()
        self.commits = 0
        self.balance = Decimal('100.00')
        self.reserved = Decimal('0.00')
        self.reservation = None
        self.ledger = []
        self.quotes = []
        self.shipment_id = uuid4()
        self.idempotency_key = uuid4()
        self.account = main.CarrierAccount(
            id=uuid4(), tenant_id=TENANT_A, provider='EASYPOST',
            base_url='https://api.easypost.com/v2', upstream_account_id=None,
            timeout_seconds=5, api_key='synthetic-non-secret-fixture',
        )
        self.expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.rate = main.ClientRate(
            provider='EASYPOST', account_id=self.account.id,
            upstream_shipment_id='shp_synthetic', upstream_rate_id='rate_synthetic',
            carrier_code='UPS', service_code='Ground', currency='GBP',
            client_price_ex_tax='12.00', delivery_days=2,
            fee_breakdown={'wholesale_total': '10.00', 'platform_markup': '2.00'},
            execution_details={
                'account_endpoint': self.account.base_url,
                'account_credential_sha256': hashlib.sha256(self.account.api_key.encode()).hexdigest(),
                'account_upstream_id': None,
            },
        )
        self.shipment = {
            'id': self.shipment_id, 'status': 'QUOTED', 'currency': 'GBP',
            'final_client_price': Decimal('12.00'), 'quote_expires_at': self.expires,
            'pricing_snapshot': {}, 'logistics_metadata': {'automation_order': {
                'origin': {'name':'Synthetic sender','line1':'1 Example Street','city':'London','postal_code':'SW1A 1AA','country_code':'GB'},
                'destination': {'name':'Synthetic recipient','line1':'2 Example Street','city':'Leeds','postal_code':'LS1 2EJ','country_code':'GB'},
            }},
        }
        self.native_rows = {
            TENANT_A: [{'shipment_id': str(uuid4()), 'state': 'A_ONLY'}],
            TENANT_B: [{'shipment_id': str(uuid4()), 'state': 'B_PRIVATE'}],
        }

    @asynccontextmanager
    async def acquire(self):
        assert self.started and not self.closed, 'Pool used outside managed lifespan'
        yield MatrixConnection(self)

    async def close(self):
        assert not self.advisory, 'Advisory lock leaked'
        self.closed = True


class MatrixConnection:
    def __init__(self, pool):
        self.pool = pool

    @asynccontextmanager
    async def transaction(self, **options):
        async with self.pool.lock:
            fields = ('balance', 'reserved', 'reservation', 'ledger', 'shipment')
            before = {field: copy.deepcopy(getattr(self.pool, field)) for field in fields}
            try:
                yield
            except BaseException:
                for field, value in before.items():
                    setattr(self.pool, field, value)
                raise
            else:
                if not options.get('readonly'):
                    self.pool.commits += 1

    def record(self, sql, args):
        normalized = ' '.join(sql.split())
        self.pool.calls.append((normalized, args))
        return normalized

    @staticmethod
    def tenant(args):
        assert args and args[0] == TENANT_A, 'Unverified or foreign tenant SQL binding'

    async def fetch(self, sql, *args):
        query = self.record(sql, args)
        self.tenant(args)
        if 'FROM public.partner_order_jobs' in query:
            assert 'WHERE tenant_id=$1' in query
            return copy.deepcopy(self.pool.native_rows[args[0]])
        if 'FROM public.shipments s JOIN public.carrier_accounts' in query:
            return []
        raise AssertionError(f'Unexpected fetch SQL: {query}')

    async def fetchval(self, sql, *args):
        query = self.record(sql, args)
        if 'pg_try_advisory_lock' in query:
            key = args[0]
            assert key == f'automation:{TENANT_A}:{self.pool.idempotency_key}'
            if key in self.pool.advisory:
                self.pool.contended.set()
                return False
            self.pool.advisory.add(key)
            return True
        self.tenant(args)
        if 'SELECT EXISTS' in query and 'public.partner_shipping_offers' in query:
            return args[1] == self.pool.rate.offer_id
        raise AssertionError(f'Unexpected fetchval SQL: {query}')

    async def fetchrow(self, sql, *args):
        query = self.record(sql, args)
        self.tenant(args)
        pool = self.pool
        if 'FROM public.tenants' in query:
            return {'tenant_id': TENANT_A, 'workspace_status': 'ACTIVE',
                    'billing_status': 'ACTIVE', 'billing_plan': 'PREPAID_WALLET',
                    'default_currency': 'GBP', 'stripe_customer_id': None, 'is_sandbox': True}
        if 'FROM public.users' in query:
            assert args[1] == USER_A
            return {'role': 'OWNER'}
        if 'FROM public.margin_rules' in query:
            return {'tenant_id': TENANT_A, 'markup_type': 'PERCENTAGE',
                    'markup_value': Decimal('20.00'), 'minimum_markup': Decimal('0.00'),
                    'maximum_markup': None}
        if 'FROM public.wallets' in query:
            assert 'FOR UPDATE' in query
            return {'tenant_id': TENANT_A, 'currency': 'GBP',
                    'balance': pool.balance, 'reserved_balance': pool.reserved}
        if 'FROM public.partner_shipping_offers o' in query:
            if args[1] != pool.rate.offer_id:
                return None
            return {'shipment_id': pool.shipment_id, 'rate_snapshot': pool.rate.model_dump(mode='json'),
                    'expires_at': pool.expires, 'idempotency_key': pool.idempotency_key}
        if 'FROM public.shipments' in query:
            assert args[1] == pool.shipment_id
            return copy.deepcopy(pool.shipment)
        if 'FROM public.wallet_reservations' in query:
            return copy.deepcopy(pool.reservation)
        if 'INSERT INTO public.wallet_reservations' in query:
            assert pool.reservation is None
            pool.reservation = {'id': uuid4(), 'tenant_id': args[0], 'shipment_id': args[1],
                                'billing_plan': args[2], 'amount': args[3],
                                'currency': args[4], 'status': 'RESERVED'}
            return {'id': pool.reservation['id']}
        raise AssertionError(f'Unexpected fetchrow SQL: {query}')

    async def execute(self, sql, *args):
        query = self.record(sql, args)
        pool = self.pool
        if 'pg_advisory_unlock' in query:
            pool.advisory.remove(args[0])
            return 'SELECT 1'
        self.tenant(args)
        if 'INSERT INTO public.partner_unbound_quotes' in query:
            pool.quotes.append(json.loads(args[3]))
        elif 'UPDATE public.wallets SET reserved_balance=' in query:
            pool.reserved = args[1]
        elif 'UPDATE public.wallets SET balance=' in query:
            pool.balance, pool.reserved = args[1:3]
        elif 'INSERT INTO public.wallet_ledger' in query:
            assert all(isinstance(value, Decimal) for value in args[3:7])
            pool.ledger.append({'type': args[2], 'balance_delta': args[3],
                                'reserved_delta': args[4], 'reservation_id': args[7]})
        elif 'UPDATE public.wallet_reservations' in query:
            pool.reservation['status'] = 'SUBMITTED' if "status='SUBMITTED'" in query else args[2]
        elif 'UPDATE public.shipments SET carrier_account_id=' in query:
            assert args[3] + args[4] == pool.shipment['final_client_price']
            pool.shipment['pricing_snapshot'] = json.loads(args[6])
        elif "UPDATE public.shipments SET status='BOOKING'" in query:
            pool.shipment['status'] = 'BOOKING'
        elif "UPDATE public.shipments SET status='BOOKED'" in query:
            pool.shipment.update(status='BOOKED', tracking_number=args[2], label_storage_path=args[3])
            pool.shipment['logistics_metadata'].update(json.loads(args[4]))
        elif "UPDATE public.shipments SET status='FAILED'" in query:
            pool.shipment['status'] = 'FAILED'
        else:
            raise AssertionError(f'Unexpected execute SQL: {query}')
        return 'UPDATE 1'


class MatrixRepository:
    def __init__(self, pool):
        self.pool = pool
        self.account_list = [pool.account]
        for index in range(2):
            self.account_list.append(main.CarrierAccount(
                id=uuid4(), tenant_id=TENANT_A, provider='REGIONAL',
                base_url='https://api.goshippo.com' if index == 0 else 'https://panel.sendcloud.sc/api/v2',
                upstream_account_id=None, timeout_seconds=5, api_key='synthetic-non-secret-fixture',
            ))

    async def accounts(self, context, **kwargs):
        assert context.tenant_id == TENANT_A
        return self.account_list


def wholesale_matrix(repository, count=12):
    """Each pipeline returns the same tiers; larger 20% profit must win."""
    return {
        account.id: [main.WholesaleRate(
            provider=account.provider, account_id=account.id,
            upstream_shipment_id=f'private_ship_{pipeline}_{tier}',
            upstream_rate_id=f'private_rate_{pipeline}_{tier}',
            carrier_code='UPS', service_code=f'Tier{tier:02d}', currency='GBP',
            wholesale_cost=Decimal(10 + tier + pipeline), delivery_days=2 + tier,
        ) for tier in range(count)]
        for pipeline, account in enumerate(repository.account_list)
    }
