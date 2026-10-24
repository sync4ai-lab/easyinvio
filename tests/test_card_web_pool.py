"""Card web requests use the small pool; only the durable worker books labels."""
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import asyncio
import pytest
from pydantic import SecretStr
from fastapi import HTTPException
from backend.card_checkout import CardCart,create_cart,complete_cart

class Pool:
    def __init__(self,row=None):self.row=row;self.active=0;self.peak=0;self.statements=[]
    def get_max_size(self):return 2
    @asynccontextmanager
    async def acquire(self):
        self.active+=1;self.peak=max(self.peak,self.active)
        assert self.active<=2,'web request exhausted its bounded pool'
        try:yield self
        finally:self.active-=1
    @asynccontextmanager
    async def transaction(self):yield self
    async def fetch(self,*args):return []
    async def fetchrow(self,sql,*args):self.statements.append((sql,args));return self.row
    async def execute(self,*args):self.statements.append(args)


def service(row=None):
    pool=Pool(row)
    settings=SimpleNamespace(runtime_role='WEB',db_pool_max_size=2,stripe_enabled=True,stripe_livemode=False,
        stripe_secret_key=SecretStr('sk_test_synthetic'),database_environment='SANDBOX',provider_environment='TEST')
    finance=SimpleNamespace(pool=pool,settings=settings,create_checkout=AsyncMock())
    return SimpleNamespace(pool=pool,finance=finance,automation=SimpleNamespace(repository=SimpleNamespace(accounts=AsyncMock(return_value=[]))),
                           client=None,card_limiter=asyncio.Semaphore(1),confirm=AsyncMock())


@pytest.mark.asyncio
async def test_web_can_create_stripe_cart_with_two_connections(monkeypatch):
    svc=service();context=SimpleNamespace(role='OWNER',tenant_id=uuid4(),user_id=uuid4())
    body=CardCart(request_id=uuid4(),offers=[dict(shipment_id=uuid4(),offer_id=uuid4(),expected_price='12.50',currency='GBP')])
    monkeypatch.setattr('backend.card_checkout.validate_checkout',AsyncMock(return_value=([],Decimal('12.50'),{'GBP'})))
    monkeypatch.setattr('backend.card_checkout.checkout_return_base',lambda *args:'https://app.example.test/')
    async def customer(*args):assert svc.pool.active==0
    monkeypatch.setattr('backend.card_checkout.ensure_customer',customer)
    async def checkout(*args,**kwargs):
        assert svc.pool.active==0
        return SimpleNamespace(topup_id=body.request_id,checkout_url='https://checkout.stripe.com/c/pay/synthetic')
    svc.finance.create_checkout.side_effect=checkout
    result=await create_cart(svc,context,body)
    assert result['url'].startswith('https://checkout.stripe.com/')
    assert svc.pool.peak==1 and svc.finance.create_checkout.await_count==1
    svc.confirm.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('paid',[False,True])
async def test_web_releases_connection_before_reconciliation_and_never_purchases(monkeypatch,paid):
    svc=service({'status':'AWAITING_PAYMENT'})
    context=SimpleNamespace(role='ADMIN',tenant_id=uuid4(),user_id=uuid4())
    async def reconcile(*args):
        assert svc.pool.active==0
        async with svc.pool.acquire():return {'status':'CREDITED' if paid else 'PENDING'}
    monkeypatch.setattr('backend.card_checkout.reconcile_topup',reconcile)
    monkeypatch.setattr('backend.card_checkout.checkout_orders',AsyncMock(side_effect=AssertionError('web must not purchase')))
    result=await complete_cart(svc,context,uuid4())
    assert result['status']==('BOOKING' if paid else 'AWAITING_PAYMENT')
    assert svc.pool.peak==1
    svc.confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_replays_terminal_result_and_keeps_tenant_scope(monkeypatch):
    svc=service({'status':'COMPLETED','amount':Decimal('12.50'),'currency':'GBP','results':{'results':[]}})
    context=SimpleNamespace(role='OWNER',tenant_id=uuid4(),user_id=uuid4());cart_id=uuid4()
    reconcile=AsyncMock();monkeypatch.setattr('backend.card_checkout.reconcile_topup',reconcile)
    assert (await complete_cart(svc,context,cart_id))['replayed']
    reconcile.assert_not_awaited()
    assert svc.pool.statements[0][1]==(context.tenant_id,cart_id)
    svc.pool.row=None
    with pytest.raises(HTTPException) as error:await complete_cart(svc,context,cart_id)
    assert error.value.status_code==404
