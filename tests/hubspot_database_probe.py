"""Real sandbox SQL with controlled CRM HTTP; migration and rows are rolled back."""
import asyncio
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import httpx

from main import Settings
from backend.database_tls import database_tls_context
from backend.hubspot_crm import HubSpotClient, HubSpotService
from backend.hubspot_provisioning import provision
from tests.test_hubspot_crm import Merchant, settings


class Pool:
    def __init__(self,connection): self.connection=connection
    @asynccontextmanager
    async def acquire(self): yield self.connection


async def run():
    config=Settings()
    if config.database_environment != 'SANDBOX':
        raise RuntimeError('This rollback probe requires DATABASE_ENVIRONMENT=SANDBOX')
    connection=await asyncpg.connect(config.database_url.get_secret_value(),
        ssl=database_tls_context(config.database_ca_file,strict=config.database_tls_strict),timeout=15)
    result={'real_database':True,'real_crm_calls':0,'committed_rows':0}
    tx=connection.transaction(isolation='repeatable_read');await tx.start()
    try:
        sql=Path('migrations/018_hubspot_activation_and_metrics.sql').read_text(encoding='utf-8')
        sql=re.sub(r'^(BEGIN;|COMMIT;)\s*$','',sql,flags=re.M)
        await connection.execute(sql)
        await connection.execute(sql)  # Migration rerun is idempotent.
        result['migration_idempotent']=True
        merchant=Merchant()
        merchant.records['companies']=[{'id':'987654321098765432','properties':{'name':'Rollback CRM Fixture',
            'address':'1 Fixture Way','city':'London','zip':'SW1A 1AA','country':'GB'},
            'associations':{'contacts':{'results':[{'id':'987654321098765433'}]}}}]
        merchant.records['contacts']=[{'id':'987654321098765433','properties':
            {'email':'rollback-crm@example.invalid','firstname':'Rollback','lastname':'Fixture'}}]
        def transport(request):
            path=request.url.path
            if path.startswith('/crm/v3/objects/deals/') and request.method=='GET':
                return httpx.Response(200,json={'id':path.split('/')[-1],
                    'properties':{'dealstage':'closedwon','hs_is_closed_won':'true'},
                    'associations':{'companies':{'results':[{'id':merchant.records['companies'][0]['id']}]},
                                    'contacts':{'results':[{'id':merchant.records['contacts'][0]['id']}]}}})
            for kind in ['companies','contacts']:
                if path==f"/crm/v3/objects/{kind}/{merchant.records[kind][0]['id']}" and request.method=='GET':
                    return httpx.Response(200,json=merchant.records[kind][0])
            return merchant(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            service=HubSpotService(Pool(connection),HubSpotClient(http,settings()))
            for deal in ['987654321098765434','987654321098765435']:
                await connection.execute('INSERT INTO public.hubspot_activation_jobs(portal_id,deal_id) VALUES(12345,$1)',deal)
                await provision(service,connection,12345,deal)
            ids=await connection.fetch('SELECT tenant_id FROM public.hubspot_activation_jobs WHERE portal_id=12345 AND deal_id=ANY($1::text[])',
                ['987654321098765434','987654321098765435'])
            assert len(ids)==2 and ids[0]['tenant_id']==ids[1]['tenant_id']
            tenant_id=ids[0]['tenant_id']
            result['duplicate_company_reuses_workspace']=True
            row=await connection.fetchrow('''SELECT t.is_sandbox,t.workspace_status,t.billing_plan,w.balance,w.reserved_balance
                FROM public.tenants t JOIN public.wallets w USING(tenant_id) WHERE tenant_id=$1''',tenant_id)
            assert row['is_sandbox'] and row['workspace_status']=='ACTIVE' and row['billing_plan']=='PREPAID_WALLET'
            assert row['balance']==0 and row['reserved_balance']==0
            result['atomic_tenant_and_zero_wallet']=True
            await service.enqueue(tenant_id)
            await service.process(tenant_id)
            await service.process(tenant_id) # Metadata trigger's new revision is retained, then consumed.
            assert len(merchant.records['companies'])==1
            result['inbound_company_reused_on_outbound_sync']=True
            profile=await connection.fetchval("SELECT company_profile->'hubspot' FROM public.tenants WHERE tenant_id=$1",tenant_id)
            if isinstance(profile,str):profile=json.loads(profile)
            assert profile=={'portal_id':'12345','company_id':'987654321098765432','contact_id':'987654321098765433'}
            result['company_and_contact_metadata_saved']=True
            p=merchant.records['companies'][0]['properties']
            assert p['veloce_total_shipments']=='0' and p['veloce_total_spend']=='0.00' and p['veloce_wallet_balance']=='0.00'
            result['empty_ledger_decimal_metrics']=True
            assert not await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.hubspot_sync_jobs WHERE tenant_id=$1)',tenant_id)
            result['durable_job_completion']=True
            assert await connection.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid='public.hubspot_activation_jobs'::regclass")
            assert not await connection.fetchval("SELECT has_table_privilege('authenticated','public.hubspot_activation_jobs','SELECT')")
            result['activation_queue_rls_and_private_grants']=True
    finally:
        await tx.rollback()
        await connection.close()
    result['rolled_back']=True
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    try: asyncio.run(run())
    except Exception as error:
        print(json.dumps({'passed':False,'error_type':type(error).__name__,'sqlstate':getattr(error,'sqlstate',None),'committed_rows':0}))
        raise SystemExit(1) from None
