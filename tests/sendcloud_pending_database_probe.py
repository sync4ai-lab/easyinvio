"""Actual sandbox SQL; controlled Sendcloud HTTP; all fixture changes rolled back."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import httpx
from cryptography.fernet import Fernet

import main
from backend.automation_freight_engine import AutomationService
from backend.automation_three_partners import BookingRequest, PartnerLifecycleService


async def run():
    original=main.Settings()
    assert original.database_environment=='SANDBOX' and original.provider_environment=='TEST'
    connection=await asyncpg.connect(original.database_url.get_secret_value(),timeout=15,
        ssl=main.database_tls_context(original.database_ca_file,strict=original.database_tls_strict))
    transaction=connection.transaction(isolation='repeatable_read');await transaction.start()
    report={'executed_at':datetime.now(timezone.utc).isoformat(),'database':'actual Supabase SANDBOX',
            'provider_responses':'controlled MockTransport','external_api_calls':0,'checks':[]}
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield connection
    try:
        seed=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
        assert seed, 'Apply rigorous fixtures first'
        seed_member=await connection.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active",seed)
        tenant,member=uuid4(),uuid4()
        async def clone(table,data):
            columns=await connection.fetchval('''SELECT string_agg(quote_ident(attname),',' ORDER BY attnum)
                FROM pg_attribute WHERE attrelid=$1::regclass AND attnum>0 AND NOT attisdropped AND attgenerated='' ''',table)
            selected=','.join('x.'+value for value in columns.split(','))
            await connection.execute(f'INSERT INTO {table}({columns}) SELECT {selected} FROM jsonb_populate_record(NULL::{table},$1::jsonb) x',json.dumps(data))
        data=json.loads(await connection.fetchval('SELECT to_jsonb(t)::text FROM public.tenants t WHERE tenant_id=$1',seed))
        data.update(tenant_id=str(tenant),workspace_slug='rollback-sc-'+tenant.hex,workspace_name='ROLLBACK SC Async',
                    is_sandbox=False,billing_email='rollback-sc@example.invalid')
        await clone('public.tenants',data)
        data=json.loads(await connection.fetchval('SELECT to_jsonb(u)::text FROM auth.users u WHERE id=$1',seed_member))
        data.update(id=str(member),email='rollback-'+member.hex+'@example.invalid',
                    raw_app_meta_data={'fixture_batch':'rollback-sendcloud','tenant_id':str(tenant)})
        await clone('auth.users',data)
        data=json.loads(await connection.fetchval('SELECT to_jsonb(u)::text FROM public.users u WHERE tenant_id=$1 AND auth_user_id=$2',seed,seed_member))
        data.update(id=str(uuid4()),tenant_id=str(tenant),auth_user_id=str(member))
        await clone('public.users',data)
        # Only in the rollback transaction: simulate a LIVE-capable workspace.
        # Every provider call below is intercepted; no real billing is possible.
        settings=original.model_copy(update={'provider_environment':'LIVE','database_environment':'LIVE','automation_purchase_enabled':True})
        await connection.execute('UPDATE public.wallets SET balance=500,reserved_balance=0 WHERE tenant_id=$1',tenant)
        pid=uuid4();key_id=sorted(settings.credential_keys)[0]
        secret=json.dumps({'public_key':'synthetic','secret_key':'synthetic'})
        cipher=Fernet(settings.credential_keys[key_id].get_secret_value().encode()).encrypt(json.dumps({'platform_id':str(pid),'api_key':secret}).encode())
        await connection.execute('''INSERT INTO public.platform_carrier_connections
            (id,account_name,aggregator,api_base_url,regional_provider_code,environment,credentials_ciphertext,
             credential_key_id,is_active,priority,timeout_seconds)
            VALUES($1,'ROLLBACK Sendcloud Async','REGIONAL','https://panel.sendcloud.sc/api/v3','SENDCLOUD_V3',
                'LIVE',$2,$3,true,10,30)''',pid,cipher,key_id)
        account_id=await connection.fetchval('SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND platform_connection_id=$2',tenant,pid)
        account=main.CarrierAccount(account_id,tenant,'REGIONAL','https://panel.sendcloud.sc/api/v3',None,30,secret,pid)
        class Repository:
            async def accounts(self,ctx,*,historical_account_id=None):
                assert ctx.tenant_id==tenant
                active=await connection.fetchval('SELECT is_active FROM public.carrier_accounts WHERE tenant_id=$1 AND id=$2',tenant,account_id)
                return [account] if active or historical_account_id==account_id else []
        calls=[];ready=False
        def transport(req):
            calls.append((req.method,req.url.path))
            if req.url.path.endswith('/shipping-options'):
                return httpx.Response(200,json={'data':[{'code':'dpd:home','carrier':{'code':'DPD'},'quotes':[
                    {'price':{'total':{'currency':'GBP','value':'10.00'}}}]}]})
            if req.method=='POST':
                assert req.url.path=='/api/v3/shipments'
                return httpx.Response(202,json={'data':{'id':'pending-1'}})
            assert req.method=='GET' and req.url.path=='/api/v3/shipments/pending-1'
            return httpx.Response(200,json={'data':{'id':'pending-1','parcels':[{
                'status':{'code':'ANNOUNCED' if ready else 'ANNOUNCING'},
                'tracking_number':'TRACK-PENDING-1' if ready else '',
                'documents':[{'type':'label','link':'https://panel.sendcloud.sc/synthetic.pdf'}] if ready else []}]}})
        pool=Pool();finance=main.FinanceEngine(pool,settings,None);context=main.TenantContext(tenant,member,'OWNER','')
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            repository=Repository();rating=main.RatingService(client,repository,settings,pool=pool)
            automation=AutomationService(pool,rating,finance,repository,main.RatingRequest,client,settings)
            service=PartnerLifecycleService(automation,client)
            address={'name':'Test Warehouse','line1':'1 Fixture Way','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
            raw={'idempotency_key':str(uuid4()),'order_reference':'ROLLBACK-SC-PENDING','origin':address,'destination':address,
                 'currency':'GBP','cargo':{'cargo_type':'PARCEL','actual_weight_kg':'1','length_cm':'20','width_cm':'15','height_cm':'10'}}
            quoted=await automation.process(context,raw,'QUOTE_ONLY');assert quoted['status']=='QUOTED',quoted
            sid=UUID(quoted['shipment_id']);body=BookingRequest(tenant_id=tenant,offer_id=quoted['rate']['offer_id'])
            result=await service.confirm(context,body);assert result['status']=='SYNC_PENDING',result
            amount=await connection.fetchval('SELECT amount FROM public.wallet_reservations WHERE tenant_id=$1 AND shipment_id=$2',tenant,sid)
            wallet=await connection.fetchrow('SELECT balance,reserved_balance FROM public.wallets WHERE tenant_id=$1',tenant)
            assert wallet['balance']==Decimal('500') and wallet['reserved_balance']==amount
            assert await connection.fetchval('SELECT tracking_number FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,sid) is None
            report['checks'].append('PASS: accepted announcement persists native ID, holds exact Decimal reservation and creates no final label/tracking')
            assert not await service.poll_and_finalize_sendcloud_label(sid)
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==Decimal('500')
            report['checks'].append('PASS: unfinished GET poll does not debit or release credit')
            await connection.execute('UPDATE public.platform_carrier_connections SET is_active=false WHERE id=$1',pid)
            ready=True
            assert await service.poll_and_finalize_sendcloud_label(sid)
            assert not await service.poll_and_finalize_sendcloud_label(sid)
            replay=await service.confirm(context,body);assert replay['replayed'] and replay['label_status']=='LABEL_CREATED'
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==Decimal('500')-amount
            assert await connection.fetchval('SELECT reserved_balance FROM public.wallets WHERE tenant_id=$1',tenant)==0
            assert await connection.fetchval("SELECT count(*) FROM public.wallet_ledger l JOIN public.wallet_reservations r ON r.tenant_id=l.tenant_id AND r.id=l.reservation_id WHERE r.shipment_id=$1 AND l.entry_type='CAPTURE'",sid)==1
            assert sum(method=='POST' and path=='/api/v3/shipments' for method,path in calls)==1
            report['checks'].append('PASS: disabled provider finishes accepted label; atomic capture, reservation release and replay produce exactly one debit and one POST')
        report['status']='PASS'
    finally:
        await transaction.rollback();await connection.close();report['database_writes_rolled_back']=True
    path=Path('docs/dispatch_safety/database_probe.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(run())
