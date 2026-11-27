"""Run actual 050/051 SQL on disposable PostgreSQL WASM; never use DATABASE_URL."""
import asyncio,os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import asyncpg,pytest,pytest_asyncio
from backend.entitlements import seed_subscription,check_quota,read_subscription
from backend.subscription_api import change_plan,PlanChange
from tests.test_tracking_workspace_postgres import Database
ROOT=Path(__file__).resolve().parents[1]

@pytest_asyncio.fixture
async def db():
    if not os.getenv('PGLITE_TEST_MODULE'):pytest.skip('Explicit disposable PostgreSQL dependency required')
    process=await asyncio.create_subprocess_exec(str(ROOT/'.venv/Lib/site-packages/playwright/driver/node.exe'),str(ROOT/'tests/pglite_tracking_bridge.cjs'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=4_000_000)
    c=Database(process)
    try:
        for file in ['tests/fixtures/subscription_baseline.sql','migrations/050_subscription_tiers_and_entitlements.sql','migrations/051_subscription_safety_followup.sql']:
            await c.command((ROOT/file).read_text(encoding='utf-8'),mode='exec')
        yield c
    finally:
        process.stdin.close();await process.wait()

async def tenant(c,plan='STARTER'):
    t=uuid4();await c.execute('INSERT INTO public.tenants(tenant_id) VALUES($1)',t)
    await seed_subscription(c,t,plan,'MONTHLY')
    return t

@pytest.mark.asyncio
async def test_zero_usage_month_end_anchor_and_private_view(db):
    t=await tenant(db)
    assert await db.fetchval('SELECT parcels FROM public.v_tenant_monthly_usage WHERE tenant_id=$1',t)==0
    row=await db.fetchrow("SELECT * FROM public.subscription_usage_period('2024-01-31 12:00Z','2024-03-01 00:00Z')")
    assert str(row['period_start']).startswith('2024-02-29') and str(row['period_end']).startswith('2024-03-31')
    assert not await db.fetchval("SELECT has_table_privilege('authenticated','public.v_tenant_monthly_usage','SELECT')")

@pytest.mark.asyncio
async def test_seats_pending_invitations_and_acceptance_use_one_slot(db):
    t=await tenant(db,'VELOCITY');owner,invitee,other=uuid4(),uuid4(),uuid4()
    for u in [owner,invitee,other]:await db.execute('INSERT INTO auth.users VALUES($1)',u)
    await db.execute('INSERT INTO public.users(tenant_id,auth_user_id) VALUES($1,$2)',t,owner)
    i=uuid4();await db.execute('INSERT INTO public.workspace_invitations(id,tenant_id,auth_user_id) VALUES($1,$2,$3)',i,t,invitee)
    await db.execute('INSERT INTO public.users(tenant_id,auth_user_id) VALUES($1,$2)',t,other)
    with pytest.raises(asyncpg.RaiseError):await db.execute('INSERT INTO public.workspace_invitations(tenant_id) VALUES($1)',t)
    # The accepted invite replaces its reserved seat rather than requiring a fourth seat.
    await db.execute('INSERT INTO public.users(tenant_id,auth_user_id) VALUES($1,$2)',t,invitee)
    await db.execute("UPDATE public.workspace_invitations SET status='ACCEPTED' WHERE id=$1",i)
    assert await db.fetchval('SELECT count(*) FROM public.users WHERE tenant_id=$1',t)==3

@pytest.mark.asyncio
async def test_store_quota_commercial_gates_and_expiry(db):
    t=await tenant(db)
    with pytest.raises(asyncpg.RaiseError):await db.execute('INSERT INTO public.ecommerce_stores(tenant_id) VALUES($1)',t)
    with pytest.raises(asyncpg.RaiseError):await db.execute('INSERT INTO public.carrier_accounts(tenant_id) VALUES($1)',t)
    # Shared platform contracts remain usable by Starter.
    await db.execute('INSERT INTO public.carrier_accounts(tenant_id,platform_connection_id) VALUES($1,$2)',t,uuid4())
    await db.execute("UPDATE public.tenants SET subscription_plan='VELOCITY',plan_status='ACTIVE' WHERE tenant_id=$1",t)
    for _ in range(2):await db.execute('INSERT INTO public.ecommerce_stores(tenant_id) VALUES($1)',t)
    with pytest.raises(asyncpg.RaiseError):await db.execute('INSERT INTO public.ecommerce_stores(tenant_id) VALUES($1)',t)
    await db.execute("UPDATE public.tenants SET subscription_plan='COMMAND' WHERE tenant_id=$1",t)
    await db.execute('INSERT INTO public.carrier_accounts(tenant_id) VALUES($1)',t)
    await db.execute("UPDATE public.tenants SET plan_status='PAST_DUE' WHERE tenant_id=$1",t)
    with pytest.raises(asyncpg.RaiseError):await db.execute('INSERT INTO public.carrier_accounts(tenant_id) VALUES($1)',t)

@pytest.mark.asyncio
async def test_holds_count_before_purchase_and_plan_change_requires_requote(db):
    t=await tenant(db);s=uuid4();s2=uuid4()
    await db.execute('INSERT INTO public.shipments(id,tenant_id,parcel_count) VALUES($1,$2,150)',s,t)
    await db.execute('INSERT INTO public.wallet_reservations(tenant_id,shipment_id) VALUES($1,$2)',t,s)
    await db.execute('INSERT INTO public.shipments(id,tenant_id) VALUES($1,$2)',s2,t)
    with pytest.raises(asyncpg.RaiseError):await db.execute('INSERT INTO public.wallet_reservations(tenant_id,shipment_id) VALUES($1,$2)',t,s2)
    await db.execute("UPDATE public.wallet_reservations SET status='RELEASED' WHERE shipment_id=$1",s)
    await db.execute('UPDATE public.tenants SET plan_version=plan_version+1 WHERE tenant_id=$1',t)
    with pytest.raises(asyncpg.RaiseError):await db.execute('INSERT INTO public.wallet_reservations(tenant_id,shipment_id) VALUES($1,$2)',t,s2)
    await db.execute('UPDATE public.shipments SET final_client_price=11 WHERE id=$1',s2)
    await db.execute('INSERT INTO public.wallet_reservations(tenant_id,shipment_id) VALUES($1,$2)',t,s2)
    assert await db.fetchval("SELECT sum(parcels) FROM public.subscription_parcel_reservations WHERE tenant_id=$1 AND state='HELD'",t)==1

@pytest.mark.asyncio
async def test_audited_plan_change_replay_and_nonce_mismatch(db):
    from types import SimpleNamespace
    t=await tenant(db);actor=SimpleNamespace(user_id=uuid4())
    body=PlanChange(request_id=uuid4(),expected_version=1,subscription_plan='VELOCITY',plan_status='TRIALING',reason='Approved bounded commercial trial')
    async with db.transaction():first=await change_plan(db,t,body,actor)
    async with db.transaction():replay=await change_plan(db,t,body,actor)
    assert first==replay and first['plan_version']==2
    assert await db.fetchval("SELECT count(*) FROM public.admin_configuration_events WHERE operation='UPDATE_SUBSCRIPTION'")==1
    assert await db.fetchval('SELECT count(*) FROM public.margin_rules WHERE tenant_id=$1 AND subscription_baseline',t)==3

@pytest.mark.asyncio
async def test_customer_cannot_edit_server_plan_fields(db):
    t=await tenant(db)
    await db.execute('GRANT UPDATE,SELECT ON public.tenants TO authenticated')
    await db.command('SET ROLE authenticated',mode='exec')
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):await db.execute("UPDATE public.tenants SET subscription_plan='COMMAND' WHERE tenant_id=$1",t)
    finally:await db.command('RESET ROLE',mode='exec')

@pytest.mark.asyncio
async def test_revenue_queries_separate_environments_and_exclude_trials(db):
    from types import SimpleNamespace as NS
    from backend.subscription_api import build_router
    t=await tenant(db,'VELOCITY')
    await db.execute("UPDATE public.tenants SET plan_status='ACTIVE',plan_period_end=NULL WHERE tenant_id=$1",t)
    sandbox=await tenant(db,'COMMAND')
    await db.execute('UPDATE public.tenants SET is_sandbox=true,subscription_complimentary=true WHERE tenant_id=$1',sandbox)
    request=NS(app=NS(state=NS(settings=NS(subscription_tiers_enabled=True),finance=NS(pool=db))))
    async def auth():pass
    route=next(r for r in build_router(auth,auth).routes if r.path.endswith('/revenue/overview'))
    data=await route.endpoint(request,actor=NS(),environment='PRODUCTION',start=None,end=None,after=None,limit=50)
    assert Decimal(data['contracted_mrr_gbp'])==Decimal('25') and len(data['tenants'])==1
    assert data['tenants'][0]['monthly_parcel_allowance']==2000
    assert data['tenants'][0]['parcels_this_month']==0

@pytest.mark.asyncio
async def test_subscription_invoice_replay_and_current_state_never_credit_wallet(db):
    from types import SimpleNamespace as NS
    from datetime import datetime,timezone
    from backend.subscription_billing import receive_verified_event
    t=await tenant(db,'VELOCITY');now=int(datetime.now(timezone.utc).timestamp())
    await db.execute("UPDATE public.tenants SET is_sandbox=true,stripe_subscription_id='sub_synthetic',stripe_customer_id='cus_synthetic' WHERE tenant_id=$1",t)
    await db.execute('INSERT INTO public.wallets(tenant_id,balance) VALUES($1,123.45)',t)
    current={'id':'sub_synthetic','livemode':False,'customer':'cus_synthetic','status':'active','current_period_start':now-60,'current_period_end':now+86400,
        'items':{'data':[{'quantity':1,'price':{'id':'price_synthetic','livemode':False,'currency':'gbp','active':True,'unit_amount':2500,'recurring':{'interval':'month'},'billing_scheme':'per_unit'}}]}}
    observations=[]
    async def retrieve(identifier):observations.append(identifier);return current
    settings=NS(subscription_tiers_enabled=True,stripe_livemode=False,subscription_price_ids={'VELOCITY:MONTHLY':'price_synthetic'})
    finance=NS(pool=db,stripe=NS(v1=NS(subscriptions=NS(retrieve_async=retrieve))))
    request=NS(app=NS(state=NS(settings=settings,finance=finance)))
    invoice={'id':'in_synthetic','subscription':'sub_synthetic','amount_paid':2500,'currency':'gbp','status_transitions':{'paid_at':now}}
    event={'id':'evt_synthetic_invoice','created':now,'type':'invoice.paid','data':{'object':invoice}}
    assert await receive_verified_event(request,event)
    assert await receive_verified_event(request,event)
    assert len(observations)==1
    assert await db.fetchval('SELECT count(*) FROM public.subscription_invoice_receipts')==1
    assert str(await db.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',t))=='123.45'
    # An old event body must not reactivate an account now cancelled at Stripe.
    current['status']='canceled'
    assert await receive_verified_event(request,{'id':'evt_synthetic_old','created':now-600,'type':'customer.subscription.updated','data':{'object':{'id':'sub_synthetic','status':'active'}}})
    assert (await read_subscription(db,t)).effective().value=='STARTER'

@pytest.mark.asyncio
async def test_first_quote_uses_tier_margin_and_expired_trial_uses_starter(db):
    from decimal import Decimal
    from types import SimpleNamespace as NS
    from backend.admin_portal import configure_pricing_pool,get_client_calibrated_rate
    configure_pricing_pool(db,NS(subscription_tiers_enabled=True))
    try:
        starter=await tenant(db)
        velocity=await tenant(db,'VELOCITY')
        expired=await tenant(db,'COMMAND')
        await db.execute("UPDATE public.tenants SET plan_status='PAST_DUE' WHERE tenant_id=$1",expired)
        for t,expected in [(starter,'11.80'),(velocity,'10.90'),(expired,'11.80')]:
            result=await get_client_calibrated_rate(t,Decimal('10.00'),'ROYALMAIL','GBR')
            assert result==Decimal(expected) and isinstance(result,Decimal)
    finally:configure_pricing_pool(None)
