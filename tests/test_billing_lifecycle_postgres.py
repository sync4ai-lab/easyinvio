"""Actual migrations and financial services against disposable PostgreSQL. No providers."""
import asyncio,json,os
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import UUID,uuid4
import asyncpg,pytest,pytest_asyncio
from fastapi import HTTPException
from backend.entitlements import seed_subscription,read_subscription
from backend.subscription_lifecycle import SubscriptionLifecycle,ChangeRequest,decoded
from backend.statements import StatementService,statement_csv,statement_pdf
from tests.test_tracking_workspace_postgres import Database

ROOT=Path(__file__).resolve().parents[1]

@pytest_asyncio.fixture
async def world():
    if not os.getenv('PGLITE_TEST_MODULE'):pytest.skip('Explicit disposable PostgreSQL dependency required')
    process=await asyncio.create_subprocess_exec(str(ROOT/'.venv/Lib/site-packages/playwright/driver/node.exe'),str(ROOT/'tests/pglite_tracking_bridge.cjs'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=4_000_000)
    c=Database(process)
    try:
        for file in ['tests/fixtures/subscription_baseline.sql','tests/fixtures/billing_baseline_extension.sql','migrations/050_subscription_tiers_and_entitlements.sql','migrations/051_subscription_safety_followup.sql','migrations/052_subscription_lifecycle_and_statements.sql']:
            await c.command((ROOT/file).read_text(encoding='utf-8'),mode='exec')
        t,u=uuid4(),uuid4();await c.execute('INSERT INTO auth.users VALUES($1)',u)
        await c.execute('INSERT INTO public.tenants(tenant_id) VALUES($1)',t);await seed_subscription(c,t,'VELOCITY','MONTHLY')
        now=datetime.now(timezone.utc).replace(microsecond=0)
        await c.execute("UPDATE public.tenants SET plan_status='ACTIVE',plan_period_start=$2,plan_period_end=$3 WHERE tenant_id=$1",t,now-timedelta(days=6),now+timedelta(days=24))
        await c.execute('INSERT INTO public.wallets(tenant_id,balance,reserved_balance) VALUES($1,100,50)',t)
        settings=NS(billing_lifecycle_enabled=True,subscription_tiers_enabled=True,stripe_enabled=False,stripe_livemode=False,subscription_price_ids={},subscription_wallet_tax_percent=Decimal(0))
        service=SubscriptionLifecycle(NS(pool=c,stripe=None),settings)
        yield NS(db=c,t=t,u=u,context=NS(tenant_id=t,user_id=u,role='OWNER',assistance_session_id=None),service=service,settings=settings,now=now)
    finally:process.stdin.close();await process.wait()

async def preview(w,action,target=None):
    body=ChangeRequest(request_id=uuid4(),target_plan=target,funding='WALLET')
    result=await w.service.command(w.context,action,body)
    return body,result

@pytest.mark.asyncio
async def test_receipt_reconciliation_repair_handles_older_052_and_reapplication(world):
    w=world
    await w.db.execute('ALTER TABLE public.subscription_invoice_receipts DROP COLUMN reconciliation_attempted_at')
    repair=(ROOT/'migrations/054_subscription_receipt_reconciliation_repair.sql').read_text(encoding='utf-8')
    for _ in range(2):
        await w.db.command(repair,mode='exec')
    await w.db.fetch('SELECT reconciliation_attempted_at FROM public.subscription_invoice_receipts LIMIT 0')
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0

async def confirm(w,action,body,result):
    return await w.service.command(w.context,action,body.model_copy(update={'confirm':True,'quote_sha256':result['payload_sha256']}))

@pytest.mark.asyncio
async def test_paid_wallet_upgrade_is_atomic_and_replay_safe(world):
    w=world;body,quote=await preview(w,'UPGRADE','COMMAND')
    assert quote['amount']=='40.00' and quote['state']=='PREVIEW'
    assert Decimal(await w.db.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',w.t))==100
    result=await confirm(w,'UPGRADE',body,quote)
    assert result['state']=='APPLIED'
    await confirm(w,'UPGRADE',body,quote)
    assert Decimal(await w.db.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',w.t))==60
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==1
    assert (await read_subscription(w.db,w.t)).subscription_plan=='COMMAND'
    assert Decimal(await w.db.fetchval('SELECT reserved_balance FROM public.wallets WHERE tenant_id=$1',w.t))==50

@pytest.mark.asyncio
async def test_insufficient_available_wallet_fails_without_future_retry(world):
    w=world;await w.db.execute('UPDATE public.wallets SET reserved_balance=90 WHERE tenant_id=$1',w.t)
    body,q=await preview(w,'UPGRADE','COMMAND')
    with pytest.raises(HTTPException) as exc:await confirm(w,'UPGRADE',body,q)
    assert exc.value.status_code==402
    assert await w.db.fetchval('SELECT state FROM public.subscription_operations WHERE id=$1',UUID(q['id']))=='FAILED'
    await w.db.execute('UPDATE public.wallets SET balance=1000 WHERE tenant_id=$1',w.t)
    await w.service.execute(UUID(q['id']))
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0

@pytest.mark.asyncio
async def test_downgrade_retains_features_until_boundary(world):
    w=world;body,q=await preview(w,'DOWNGRADE','STARTER');await confirm(w,'DOWNGRADE',body,q)
    sub=await read_subscription(w.db,w.t)
    assert sub.subscription_plan=='VELOCITY' and sub.pending_plan=='STARTER'
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0
    await w.db.execute("UPDATE public.tenants SET pending_plan_effective_at=now()-interval '1 second' WHERE tenant_id=$1",w.t)
    await w.service.settle_due(w.t,w.now+timedelta(seconds=2))
    child=await w.db.fetchval("SELECT id FROM public.subscription_operations WHERE action='DOWNGRADE_RENEWAL'")
    await w.service.execute(child)
    assert (await read_subscription(w.db,w.t)).subscription_plan=='STARTER'

@pytest.mark.asyncio
async def test_finance_roles_cannot_authorize_owner_changes(world):
    w=world
    for role in ['ADMIN','ACCOUNTANT','DISPATCHER']:
        ctx=NS(**{**vars(w.context),'role':role})
        with pytest.raises(HTTPException) as exc:await w.service.command(ctx,'CANCEL',ChangeRequest(request_id=uuid4(),funding='WALLET'))
        assert exc.value.status_code==403
    with pytest.raises(HTTPException):await w.service.command(NS(**{**vars(w.context),'assistance_session_id':uuid4()}),'CANCEL',ChangeRequest(request_id=uuid4(),funding='WALLET'))

@pytest.mark.asyncio
async def test_preview_hash_and_version_are_required(world):
    w=world;body,q=await preview(w,'UPGRADE','COMMAND')
    with pytest.raises(HTTPException):await confirm(w,'UPGRADE',body,{**q,'payload_sha256':'0'*64})
    await w.db.execute('UPDATE public.tenants SET plan_version=plan_version+1 WHERE tenant_id=$1',w.t)
    with pytest.raises(HTTPException):await confirm(w,'UPGRADE',body,q)
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0

@pytest.mark.asyncio
async def test_notice_wallet_tax_is_charged_once_and_pinned_to_confirmation(world):
    w=world;w.settings.subscription_wallet_tax_percent=Decimal('20')
    body,q=await preview(w,'CANCEL');await confirm(w,'CANCEL',body,q)
    net=Decimal(q['payload']['net_amount']);gross=Decimal(q['amount'])
    assert gross==net+Decimal(q['payload']['wallet_tax_amount'])
    assert Decimal(await w.db.fetchval('SELECT final_notice_prorated_amount FROM public.tenants WHERE tenant_id=$1',w.t))==net
    # Simulate processing after a worker outage and a changed tax configuration.
    w.settings.subscription_wallet_tax_percent=Decimal('99')
    await w.service.settle_due(w.t,w.now+timedelta(days=31))
    op=await w.db.fetchrow("SELECT * FROM public.subscription_operations WHERE action='NOTICE_CHARGE'")
    assert Decimal(op['amount'])==gross
    await w.service.execute(op['id'])
    assert Decimal(await w.db.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',w.t))==100-gross
    assert (await read_subscription(w.db,w.t)).subscription_plan=='STARTER'

@pytest.mark.asyncio
async def test_trial_cancellation_does_not_charge_or_extend_access(world):
    w=world;await w.db.execute("UPDATE public.tenants SET plan_status='TRIALING',plan_period_start=$2,plan_period_end=$3 WHERE tenant_id=$1",w.t,w.now-timedelta(days=1),w.now+timedelta(days=13))
    body,q=await preview(w,'CANCEL');await confirm(w,'CANCEL',body,q)
    assert q['amount']=='0.00'
    assert (await read_subscription(w.db,w.t)).cancellation_effective_at==w.now+timedelta(days=13)
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0

@pytest.mark.asyncio
async def test_statements_are_private_immutable_and_repeatable(world):
    w=world;s=StatementService(w.db,w.settings)
    first=await s.generate(w.context);again=await s.generate(w.context)
    assert first==again and first['opening_balance']=='100.00' and first['closing_balance']=='100.00'
    data=await s.detail(w.context,UUID(first['id']));assert data==first
    assert statement_csv(data).startswith(b'\xef\xbb\xbf')
    assert statement_pdf(data).startswith(b'%PDF-')
    with pytest.raises(HTTPException) as exc:await s.detail(NS(tenant_id=uuid4(),role='ACCOUNTANT'),UUID(first['id']))
    assert exc.value.status_code==404
    with pytest.raises(HTTPException) as exc:await s.list(NS(tenant_id=w.t,role='DISPATCHER'))
    assert exc.value.status_code==403
    with pytest.raises(asyncpg.InsufficientPrivilegeError):await w.db.execute("UPDATE public.billing_statements SET gross_total=999")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):await w.db.execute('DELETE FROM public.subscription_change_events') if await w.db.fetchval('SELECT count(*) FROM public.subscription_change_events') else await w.db.execute('UPDATE public.billing_statements SET gross_total=999')

@pytest.mark.asyncio
async def test_statement_only_access_does_not_enable_plan_mutations(world):
    w=world;w.settings.billing_lifecycle_enabled=False;w.settings.billing_statements_enabled=True
    status=await w.service.status(w.context)
    assert status['can_manage'] is False
    service=StatementService(w.db,w.settings)
    result=await service.generate(w.context,preview=True)
    assert result['preview'] is True
    result=await service.generate(w.context)
    assert result['id'] and len((await service.list(w.context))['statements'])==1
    with pytest.raises(HTTPException) as exc:await w.service.command(w.context,'UPGRADE',ChangeRequest(request_id=uuid4(),target_plan='COMMAND',funding='WALLET'))
    assert exc.value.status_code==503 and exc.value.detail['code']=='BILLING_LIFECYCLE_DISABLED'
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0

@pytest.mark.asyncio
async def test_plan_management_describes_valid_directions_and_unbounded_access(world):
    w=world
    status=await w.service.status(w.context)
    assert status['management']['upgrade_targets']==['COMMAND']
    assert status['management']['downgrade_targets']==['STARTER']
    assert status['management']['can_cancel'] is True
    assert [p['plan'] for p in status['plans']]==['STARTER','VELOCITY','COMMAND']
    await w.db.execute("UPDATE public.tenants SET subscription_plan='COMMAND',plan_period_end=NULL,subscription_complimentary=true WHERE tenant_id=$1",w.t)
    status=await w.service.status(w.context)
    assert status['management']['access_type']=='COMPLIMENTARY'
    assert 'No paid subscription' in status['management']['reason']
    assert status['management']['activation_targets']==['VELOCITY','COMMAND']
    assert status['management']['upgrade_targets']==[] and not status['management']['can_cancel']
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0

@pytest.mark.asyncio
async def test_command_to_velocity_is_a_downgrade_and_cancellation_has_confirmation(world):
    w=world;await w.db.execute("UPDATE public.tenants SET subscription_plan='COMMAND' WHERE tenant_id=$1",w.t)
    data=await w.service.status(w.context)
    assert data['management']['upgrade_targets']==[] and data['management']['downgrade_targets']==['STARTER','VELOCITY']
    body,q=await preview(w,'DOWNGRADE','VELOCITY')
    assert q['state']=='PREVIEW' and (await read_subscription(w.db,w.t)).subscription_plan=='COMMAND'
    result=await confirm(w,'DOWNGRADE',body,q)
    assert result['state']=='SCHEDULED' and (await read_subscription(w.db,w.t)).pending_plan=='VELOCITY'
    assert (await read_subscription(w.db,w.t)).subscription_plan=='COMMAND'

@pytest.mark.asyncio
async def test_new_event_does_not_weaken_old_ledger_shapes(world):
    w=world
    with pytest.raises(asyncpg.CheckViolationError):await w.db.execute("INSERT INTO public.wallet_ledger(tenant_id,entry_type,balance_delta,reserved_delta) VALUES($1,'TOPUP',-5,0)",w.t)
    with pytest.raises(asyncpg.CheckViolationError):await w.db.execute("INSERT INTO public.wallet_ledger(tenant_id,entry_type,balance_delta,reserved_delta) VALUES($1,'SUBSCRIPTION_DEBIT',-5,0)",w.t)
    assert not await w.db.fetchval("SELECT has_table_privilege('authenticated','public.billing_statements','SELECT')")
    await w.db.execute('GRANT UPDATE,SELECT ON public.tenants TO authenticated');await w.db.command('SET ROLE authenticated',mode='exec')
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):await w.db.execute('UPDATE public.tenants SET cancellation_requested_at=now() WHERE tenant_id=$1',w.t)
    finally:await w.db.command('RESET ROLE',mode='exec')

@pytest.mark.asyncio
async def test_annual_cancellation_original_card_refund_and_replay(world,monkeypatch):
    from backend import subscription_lifecycle as module
    from backend.subscription_math import add_cycle
    w=world;now=datetime(2026,11,15,tzinfo=timezone.utc);start=now-timedelta(days=6);end=add_cycle(start,'ANNUAL')
    monkeypatch.setattr(module,'utcnow',lambda:now)
    await w.db.execute("UPDATE public.tenants SET billing_cycle='ANNUAL',stripe_subscription_id='sub_test',stripe_customer_id='cus_test',is_sandbox=true,plan_period_start=$2,plan_period_end=$3 WHERE tenant_id=$1",w.t,start,end)
    await w.db.execute('''INSERT INTO public.subscription_invoice_receipts(stripe_invoice_id,stripe_subscription_id,stripe_event_id,tenant_id,amount_paid_gbp,paid_at,created_at,invoice_net_gbp,invoice_tax_gbp,invoice_gross_gbp,invoice_payment_intent_id)
     VALUES('in_original','sub_test','evt_original',$1,288.00,$2,$2,240,48.00,288.00,'pi_original')''',w.t,start)
    price={'id':'price_velocity','livemode':False,'currency':'gbp','active':True,'unit_amount':24000,'recurring':{'interval':'year','interval_count':1},'billing_scheme':'per_unit'}
    subscription={'id':'sub_test','customer':'cus_test','livemode':False,'status':'active','items':{'data':[{'id':'si_test','quantity':1,'price':price,'current_period_start':int(start.timestamp()),'current_period_end':int(end.timestamp())}]}}
    calls=[]
    async def retrieve(*args,**kwargs):return subscription
    async def update(*args,**kwargs):calls.append(('subscription',args));return subscription
    async def payment(*args,**kwargs):return {'id':'pi_original','customer':'cus_test','currency':'gbp','livemode':False,'latest_charge':{'amount':28800,'amount_refunded':0}}
    async def refund(params,**kwargs):
        calls.append(('refund',params));return {'id':'re_once','payment_intent':'pi_original','amount':params['amount'],'currency':'gbp','livemode':False,'status':'succeeded'}
    w.settings.stripe_enabled=True;w.settings.subscription_price_ids={'VELOCITY:ANNUAL':'price_velocity'}
    w.service.finance.stripe=NS(v1=NS(subscriptions=NS(retrieve_async=retrieve,update_async=update),payment_intents=NS(retrieve_async=payment),refunds=NS(create_async=refund)))
    body=ChangeRequest(request_id=uuid4(),funding='STRIPE')
    quote=await w.service.command(w.context,'CANCEL',body)
    annual=quote['payload']['breakdown']['annual_clawback']
    assert annual['net_refund']=='210.16' and quote['amount']=='0.00'
    confirmed=await w.service.command(w.context,'CANCEL',body.model_copy(update={'confirm':True,'quote_sha256':quote['payload_sha256']}))
    await w.service.execute(UUID(confirmed['id']))
    sub=await read_subscription(w.db,w.t)
    assert sub.plan_status=='PENDING_CANCELLATION' and sub.cancellation_effective_at==now+timedelta(days=30)
    await w.service.settle_due(w.t,now+timedelta(days=30,seconds=1))
    rid=await w.db.fetchval("SELECT id FROM public.subscription_operations WHERE action='ANNUAL_REFUND'")
    await w.service.execute(rid);await w.service.execute(rid)
    assert len([c for c in calls if c[0]=='refund'])==1
    assert [c for c in calls if c[0]=='refund'][0][1]['amount']==25219
    assert await w.db.fetchval('SELECT state FROM public.subscription_refunds')=='SUCCEEDED'
    assert Decimal(await w.db.fetchval('SELECT invoice_refunded_gbp FROM public.subscription_invoice_receipts'))==Decimal('252.19')
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0
    assert (await read_subscription(w.db,w.t)).subscription_plan=='STARTER'

@pytest.mark.asyncio
@pytest.mark.parametrize('tamper',[False,True])
@pytest.mark.parametrize('funding',['STRIPE','WALLET','WALLET_ZERO'])
@pytest.mark.parametrize('taxed',[False,True])
async def test_stripe_upgrade_requires_matching_paid_invoice_before_access(world,tamper,funding,taxed):
    zero=funding=='WALLET_ZERO';funding='WALLET' if zero else funding
    if taxed:world.settings.subscription_tax_percent=Decimal('20');world.settings.subscription_stripe_tax_rate_id='txr_uk_vat'
    w=world;sub=await read_subscription(w.db,w.t)
    if zero:await w.db.execute('UPDATE public.tenants SET subscription_complimentary=true WHERE tenant_id=$1',w.t)
    await w.db.execute("UPDATE public.tenants SET stripe_subscription_id='sub_test',stripe_customer_id='cus_test',is_sandbox=true WHERE tenant_id=$1",w.t)
    def price(name,amount):return {'id':name,'active':True,'livemode':False,'currency':'gbp','unit_amount':amount,'recurring':{'interval':'month','interval_count':1},'billing_scheme':'per_unit'}
    old,new=price('price_velocity',2500),price('price_command',7500)
    subscription={'id':'sub_test','customer':'cus_test','livemode':False,'status':'active','items':{'data':[{'id':'si_test','quantity':1,'price':old,'current_period_start':int(sub.plan_period_start.timestamp()),'current_period_end':int(sub.plan_period_end.timestamp())}]}}
    invoice={};calls=[]
    async def retrieve_sub(*args,**kwargs):return subscription
    async def get_price(*args,**kwargs):return new
    async def update_sub(*args,**kwargs):calls.append('update');subscription['items']['data'][0]['price']=new;return subscription
    async def create(params,**kwargs):invoice.update(id='in_change',status='draft',customer='cus_test',currency='gbp',livemode=False,metadata=params['metadata']);return dict(invoice)
    async def item(params,**kwargs):invoice.update(subtotal=params['amount'],total=params['amount'],total_excluding_tax=params['amount']);return {'id':'ii_test'}
    async def finalize(*args,**kwargs):
        invoice.update(status='paid' if zero else 'open',hosted_invoice_url='https://invoice.stripe.com/i/test')
        if taxed:invoice['total']=invoice['subtotal']+int((Decimal(invoice['subtotal'])*Decimal('.20')).quantize(Decimal('1')))
        if zero:invoice.update(amount_paid=0,amount_remaining=0,paid_out_of_band=False)
        return dict(invoice)
    async def get_invoice(*args,**kwargs):return dict(invoice)
    async def pay(invoice_id,params,**kwargs):
        assert params=={'paid_out_of_band':True};calls.append('wallet-paid');invoice.update(status='paid',paid_out_of_band=True,amount_paid=invoice['total'],amount_remaining=0);return dict(invoice)
    w.settings.stripe_enabled=True;w.settings.subscription_price_ids={'VELOCITY:MONTHLY':'price_velocity','COMMAND:MONTHLY':'price_command'}
    async def get_tax(*args,**kwargs):return {'active':True,'livemode':False,'inclusive':False,'percentage':20,'country':'GB'}
    w.service.finance.stripe=NS(v1=NS(tax_rates=NS(retrieve_async=get_tax),subscriptions=NS(retrieve_async=retrieve_sub,update_async=update_sub),prices=NS(retrieve_async=get_price),invoices=NS(create_async=create,finalize_invoice_async=finalize,retrieve_async=get_invoice,pay_async=pay),invoice_items=NS(create_async=item)))
    body=ChangeRequest(request_id=uuid4(),target_plan='COMMAND',funding=funding);q=await w.service.command(w.context,'UPGRADE',body)
    if taxed:
        assert q['payload']['tax_amount']==('0.00' if zero else '8.00')
        assert q['amount']==('0.00' if zero else '48.00')
    result=await w.service.command(w.context,'UPGRADE',body.model_copy(update={'confirm':True,'quote_sha256':q['payload_sha256']}));opid=UUID(result['id'])
    if funding=='WALLET' and tamper:
        # Tax changes after authorization must not debit the wallet.
        original_finalize=finalize
        async def changed_tax(*args,**kwargs):
            result=await original_finalize(*args,**kwargs);invoice['total']+=1;return dict(invoice)
        w.service.finance.stripe.v1.invoices.finalize_invoice_async=changed_tax
    await w.service.execute(opid)
    if funding=='WALLET':
        assert (await read_subscription(w.db,w.t)).subscription_plan==('VELOCITY' if tamper else 'COMMAND')
        assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==(0 if tamper or zero else 1)
        assert calls==([] if tamper else ['update'] if zero else ['wallet-paid','update'])
        await w.service.execute(opid)
        assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==(0 if tamper or zero else 1)
        return
    assert (await read_subscription(w.db,w.t)).subscription_plan=='VELOCITY' and not calls
    invoice.update(status='paid',amount_paid=invoice['total'],amount_remaining=0)
    if tamper:invoice['subtotal']+=1
    await w.db.execute('UPDATE public.subscription_operations SET lease_until=NULL WHERE id=$1',opid)
    await w.service.execute(opid)
    current=await read_subscription(w.db,w.t)
    assert current.subscription_plan==('VELOCITY' if tamper else 'COMMAND')
    assert await w.db.fetchval('SELECT state FROM public.subscription_operations WHERE id=$1',opid)==('REVIEW' if tamper else 'APPLIED')
    assert await w.db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0


@pytest.mark.asyncio
async def test_custom_activity_stays_unsaved_after_auditor_tables_are_retired(world):
    w=world
    await w.db.command((ROOT/'migrations/059_retire_carrier_bill_auditor.sql').read_text(),mode='exec')
    service=StatementService(w.db,w.settings)
    before=await w.db.fetchval('SELECT count(*) FROM billing_statements')
    end=datetime.now(timezone.utc);start=end-timedelta(days=90)
    data=await service.generate(w.context,start,end,preview=True)
    assert data['preview'] and data['period_start']==start.isoformat() and data['period_end']==end.isoformat()
    assert await w.db.fetchval('SELECT count(*) FROM billing_statements')==before
    first=await service.generate(w.context)
    assert first['display_reference'].startswith('EI-01')
    assert await service.detail(w.context,UUID(first['id']))==first


@pytest.mark.asyncio
async def test_registration_date_limits_all_activity_and_monthly_statements(world):
    w=world;service=StatementService(w.db,w.settings)
    # Preserve an old snapshot to prove pre-registration artifacts are also hidden.
    old=await service.generate(w.context)
    registered=datetime.now(timezone.utc)-timedelta(hours=1)
    await w.db.execute('UPDATE public.tenants SET created_at=$2 WHERE tenant_id=$1',w.t,registered)
    assert (await service.list(w.context))['statements']==[]
    with pytest.raises(HTTPException) as error:await service.detail(w.context,UUID(old['id']))
    assert error.value.status_code==404
    with pytest.raises(HTTPException) as error:await service.generate(w.context)
    assert error.value.status_code==422
    before=registered.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=1)
    with pytest.raises(HTTPException) as error:await service.generate(w.context,before,datetime.now(timezone.utc),preview=True)
    assert error.value.status_code==422
    current=await service.generate(w.context,preview=True)
    assert current['period_start'][:10]==registered.isoformat()[:10]
    # A first partial month becomes eligible once that calendar month ends.
    start=datetime.fromisoformat(old['period_start']);end=datetime.fromisoformat(old['period_end'])
    await w.db.execute('UPDATE public.tenants SET created_at=$2 WHERE tenant_id=$1',w.t,start+timedelta(days=10))
    assert (await service.generate(w.context,start,end))['id']==old['id']
    assert len((await service.list(w.context))['statements'])==1


@pytest.mark.asyncio
@pytest.mark.parametrize('country',['GB','US'])
async def test_initial_checkout_attaches_exclusive_vat_before_creating_receipt(world,country):
    from backend.subscription_billing import checkout,SubscriptionCheckout
    w=world;await w.db.execute('UPDATE public.tenants SET is_sandbox=true,country_code=$2,billing_email=$3 WHERE tenant_id=$1',w.t,country,'owner@example.invalid')
    w.settings.stripe_enabled=True;w.settings.subscription_tax_percent=Decimal(20)
    w.settings.subscription_stripe_tax_rate_id='txr_test_uk';w.settings.booking_page_url='https://workspace.example.invalid'
    w.settings.subscription_price_ids={'COMMAND:MONTHLY':'price_command'};calls=[]
    async def price(*args):return {'active':True,'livemode':False,'currency':'gbp','unit_amount':7500,'recurring':{'interval':'month','interval_count':1},'billing_scheme':'per_unit','tax_behavior':'exclusive'}
    async def rate(*args):return {'active':True,'livemode':False,'inclusive':False,'percentage':20,'country':'GB'}
    async def create(params,**kwargs):calls.append(params);return {'id':'cs_test_vat','url':'https://checkout.stripe.com/c/test'}
    w.service.finance.stripe=NS(v1=NS(prices=NS(retrieve_async=price),tax_rates=NS(retrieve_async=rate),checkout=NS(sessions=NS(create_async=create))))
    request=NS(app=NS(state=NS(settings=w.settings,finance=w.service.finance)))
    body=SubscriptionCheckout(request_id=uuid4(),plan='COMMAND')
    if country!='GB':
        with pytest.raises(HTTPException):await checkout(request,w.context,body)
        assert not calls and await w.db.fetchval('SELECT count(*) FROM public.subscription_checkout_receipts')==0
    else:
        await checkout(request,w.context,body)
        assert calls[0]['subscription_data']=={'default_tax_rates':['txr_test_uk']}
        assert calls[0]['billing_address_collection']=='required'
        assert calls[0]['line_items']==[{'price':'price_command','quantity':1}]
