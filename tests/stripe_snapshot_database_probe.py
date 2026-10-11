"""Apply migration 019 and test real SQL in a transaction that is rolled back."""
import asyncio
import json
import re
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import asyncpg
from pydantic import SecretStr
from main import Settings,FinanceEngine,TopupRequest,TenantContext
from backend.database_tls import database_tls_context
from backend.payment_gateway import SnapshotWebhookService
from tests.payment_database_probe import Pool


async def run():
    # This Stripe-only probe does not depend on optional Twilio activation.
    config=Settings(twilio_enabled=False,twilio_whatsapp_sandbox_enabled=False);assert config.database_environment=='SANDBOX'
    c=await asyncpg.connect(config.database_url.get_secret_value(),ssl=database_tls_context(config.database_ca_file,strict=config.database_tls_strict),timeout=15)
    tx=c.transaction();await tx.start()
    checks={'real_database':True,'real_stripe_calls':0,'committed_rows':0}
    try:
        sql=re.sub(r'^(BEGIN;|COMMIT;)\s*$','',Path('migrations/019_stripe_snapshot_reconciliation.sql').read_text(encoding='utf-8'),flags=re.M)
        await c.execute(sql);await c.execute(sql);checks['migration_idempotent']=True
        row=await c.fetchrow('''SELECT t.tenant_id,u.auth_user_id FROM public.tenants t JOIN public.users u USING(tenant_id)
            WHERE t.is_sandbox AND t.company_profile ? 'fixture_batch' AND t.billing_plan='PREPAID_WALLET'
            AND t.default_currency='GBP' AND t.workspace_status='ACTIVE' AND u.role='OWNER' AND u.is_active ORDER BY t.tenant_id LIMIT 1''')
        assert row
        tenant=row['tenant_id'];customer='cus_snapshot_'+uuid4().hex
        await c.execute('UPDATE public.tenants SET stripe_customer_id=$2 WHERE tenant_id=$1',tenant,customer)
        config=config.model_copy(update={'stripe_secret_key':SecretStr('sk_test_controlled'),'stripe_livemode':False})
        async def create(params,options):
            return SimpleNamespace(id='cs_test_'+params['client_reference_id'],url='https://checkout.stripe.com/c/pay/controlled')
        finance=FinanceEngine(Pool(c),config,SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create)))))
        service=SnapshotWebhookService(finance);context=TenantContext(tenant,row['auth_user_id'],'OWNER','controlled-context')
        opening=await c.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)
        body=TopupRequest(request_id=uuid4(),amount='100.00');checkout=await finance.create_checkout(context,body)
        intent='pi_'+uuid4().hex
        session={'object':'checkout.session','id':checkout.checkout_session_id,'customer':customer,'payment_intent':intent,
            'mode':'payment','payment_status':'paid','livemode':False,'currency':'gbp','amount_total':10000,'client_reference_id':str(body.request_id),
            'metadata':{'purpose':'wallet_topup','tenant_id':str(tenant),'topup_id':str(body.request_id)}}
        async def dispatch(kind,obj,event_id=None):
            event={'id':event_id or 'evt_'+uuid4().hex,'type':kind,'livemode':False,'api_version':'2026-09-30.endive','data':{'object':obj}}
            return await service.process(await service.register(event))
        assert (await dispatch('checkout.session.completed',session))['credited']
        assert await c.fetchval('SELECT transaction_state FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2',tenant,body.request_id)=='SUCCESS'
        assert await c.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==opening+Decimal('100.00')
        checks['success_trace_and_atomic_credit']=True
        try:
            async with c.transaction():
                await finance.append_ledger(c,tenant_id=tenant,currency='GBP',entry_type='TOPUP',balance_delta=Decimal('1.00'),
                    reserved_delta=Decimal('0'),balance_after=opening+Decimal('101.00'),reserved_after=Decimal('0'),
                    topup_id=body.request_id,stripe_session_id='cs_duplicate_probe',stripe_event_id='evt_duplicate_probe')
                raise AssertionError('Duplicate funding credit must be rejected')
        except asyncpg.UniqueViolationError:pass
        checks['funding_credit_remains_unique']=True
        charge={'object':'charge','id':'ch_'+uuid4().hex,'customer':customer,'payment_intent':intent,'metadata':session['metadata'],
            'currency':'gbp','amount':10000,'amount_refunded':2000,'status':'succeeded','paid':True,'livemode':False}
        event_id='evt_'+uuid4().hex
        assert (await dispatch('charge.refunded',charge,event_id))['refund_debited']=='20.00'
        assert (await dispatch('charge.refunded',charge,event_id))['replayed']
        assert (await dispatch('charge.refunded',{**charge,'amount_refunded':6000}))['refund_debited']=='40.00'
        assert (await dispatch('charge.refunded',charge))['refund_debited']=='0.00'
        assert await c.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==opening+Decimal('40.00')
        assert await c.fetchval("SELECT count(*) FROM public.wallet_ledger WHERE tenant_id=$1 AND topup_id=$2 AND entry_type='REFUND_DEBIT'",tenant,body.request_id)==2
        checks['partial_refunds_replay_and_out_of_order']=True
        assert (await dispatch('charge.failed',{**charge,'status':'failed','paid':False}))['ignored']
        assert await c.fetchval('SELECT status FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2',tenant,body.request_id)=='CREDITED'
        checks['late_failure_cannot_undo_credit']=True
        pending=TopupRequest(request_id=uuid4(),amount='100.00');pending_checkout=await finance.create_checkout(context,pending)
        failed={**charge,'id':'ch_'+uuid4().hex,'payment_intent':'pi_'+uuid4().hex,'status':'failed','paid':False,
            'metadata':{**session['metadata'],'topup_id':str(pending.request_id)}}
        assert (await dispatch('charge.failed',failed))['failed']
        assert await c.fetchval('SELECT status FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2',tenant,pending.request_id)=='FAILED'
        checks['pending_charge_failed_mapping']=True
        # Ledger rejection must roll back the debit/checkpoint, retaining a durable retry.
        await c.execute('''CREATE FUNCTION pg_temp.reject_snapshot_probe() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.stripe_event_id='evt_forced_snapshot_failure' THEN RAISE EXCEPTION 'Controlled ledger rejection'; END IF; RETURN NEW; END $$;
            CREATE TRIGGER reject_snapshot_probe BEFORE INSERT ON public.wallet_ledger FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_snapshot_probe()''')
        assert (await dispatch('charge.refunded',{**charge,'amount_refunded':8000},'evt_forced_snapshot_failure'))['deferred']
        assert await c.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==opening+Decimal('40.00')
        assert await c.fetchval("SELECT status FROM public.stripe_webhook_events WHERE event_id='evt_forced_snapshot_failure'")=='PENDING'
        checks['failed_debit_rollback_and_durable_retry']=True
        assert not await c.fetchval("SELECT has_table_privilege('authenticated','public.stripe_webhook_events','SELECT')")
        checks['private_queue_grants']=True
    finally:
        await tx.rollback();await c.close()
    checks['rolled_back']=True;print(json.dumps(checks,indent=2))


if __name__=='__main__':
    try:asyncio.run(run())
    except Exception as error:
        print(json.dumps({'passed':False,'error_type':type(error).__name__,'sqlstate':getattr(error,'sqlstate',None),'committed_rows':0}))
        raise SystemExit(1) from None
