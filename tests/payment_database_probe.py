"""Actual Supabase Checkout ledger probe; all rows/DDL are rolled back."""
import asyncio
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
from pydantic import SecretStr

from main import Settings, FinanceEngine, TopupRequest, TenantContext
from backend.database_tls import database_tls_context


class Pool:
    def __init__(self,c):self.c=c
    @asynccontextmanager
    async def acquire(self):yield self.c


async def run():
    config=Settings()
    assert config.database_environment=='SANDBOX'
    c=await asyncpg.connect(config.database_url.get_secret_value(),ssl=database_tls_context(config.database_ca_file,strict=config.database_tls_strict),timeout=15)
    tx=c.transaction();await tx.start()
    result={'real_database':True,'real_stripe_calls':0,'committed_rows':0}
    try:
        row=await c.fetchrow('''SELECT t.tenant_id,u.auth_user_id FROM public.tenants t JOIN public.users u USING(tenant_id)
            WHERE t.is_sandbox AND t.company_profile ? 'fixture_batch' AND t.billing_plan='PREPAID_WALLET'
            AND t.default_currency='GBP' AND t.workspace_status='ACTIVE' AND u.role='OWNER' AND u.is_active ORDER BY t.tenant_id LIMIT 1''')
        assert row,'Apply the sandbox fixtures before this probe'
        tenant=row['tenant_id'];context=TenantContext(tenant,row['auth_user_id'],'OWNER','controlled-context')
        customer='cus_payment_rollback_'+uuid4().hex
        await c.execute('UPDATE public.tenants SET stripe_customer_id=$2 WHERE tenant_id=$1',tenant,customer)
        config=config.model_copy(update={'stripe_secret_key':SecretStr('sk_test_controlled'), 'stripe_livemode':False})
        async def create(params,options):
            assert params['metadata']['tenant_id']==str(tenant)
            return SimpleNamespace(id='cs_test_'+params['client_reference_id'],url='https://checkout.stripe.com/c/pay/control')
        finance=FinanceEngine(Pool(c),config,SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create)))))
        before=await c.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)
        body=TopupRequest(request_id=uuid4(),amount='250.00')
        checkout=await finance.create_checkout(context,body)
        assert await c.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before
        result['checkout_does_not_credit']=True
        session={'id':checkout.checkout_session_id,'customer':customer,'mode':'payment','payment_status':'paid','livemode':False,
            'currency':'gbp','amount_total':25000,'client_reference_id':str(body.request_id),
            'metadata':{'purpose':'wallet_topup','tenant_id':str(tenant),'topup_id':str(body.request_id)}}
        assert await finance.credit_session('evt_controlled_'+uuid4().hex,session)
        assert not await finance.credit_session('evt_replayed_'+uuid4().hex,session)
        assert await c.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before+Decimal('250.00')
        assert await c.fetchval('SELECT count(*) FROM public.wallet_ledger WHERE tenant_id=$1 AND topup_id=$2',tenant,body.request_id)==1
        assert await c.fetchval('SELECT status FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2',tenant,body.request_id)=='CREDITED'
        result['decimal_credit_and_one_ledger_entry']=True;result['replay_no_double_credit']=True
        fail_body=TopupRequest(request_id=uuid4(),amount='100.00');fail_checkout=await finance.create_checkout(context,fail_body)
        await c.execute('''CREATE FUNCTION pg_temp.reject_payment_probe() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.stripe_event_id='evt_forced_payment_failure' THEN RAISE EXCEPTION 'Controlled ledger rejection'; END IF; RETURN NEW; END $$;
            CREATE TRIGGER reject_payment_probe BEFORE INSERT ON public.wallet_ledger FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_payment_probe()''')
        fail_session={**session,'id':fail_checkout.checkout_session_id,'amount_total':10000,'client_reference_id':str(fail_body.request_id),
            'metadata':{**session['metadata'],'topup_id':str(fail_body.request_id)}}
        try:
            await finance.credit_session('evt_forced_payment_failure',fail_session)
            raise AssertionError('Controlled rejection must fail')
        except asyncpg.RaiseError:pass
        assert await c.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before+Decimal('250.00')
        assert await c.fetchval('SELECT status FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2',tenant,fail_body.request_id)=='PENDING'
        result['ledger_failure_atomic_rollback']=True
    finally:
        await tx.rollback();await c.close()
    result['rolled_back']=True;print(json.dumps(result,indent=2))


if __name__=='__main__':
    try:asyncio.run(run())
    except Exception as error:
        print(json.dumps({'passed':False,'error_type':type(error).__name__,'sqlstate':getattr(error,'sqlstate',None),'committed_rows':0}))
        raise SystemExit(1) from None
