"""Apply or rollback-verify the complete relational seed in one transaction."""
import asyncio
import json
import sys
from pathlib import Path
import asyncpg
from main import Settings
from backend.database_tls import database_tls_context
from backend.hubspot_crm import HubSpotSettings
from cryptography.fernet import Fernet


async def run(apply=False):
    settings=Settings()
    if settings.database_environment!='SANDBOX':raise ValueError('SANDBOX database configuration required')
    if settings.stripe_enabled or settings.twilio_enabled or HubSpotSettings().hubspot_enabled:
        raise ValueError('Disable external integrations for this fixture run')
    sql=Path('seeds/rigorous_v1/all_in_one.sql').read_text(encoding='utf-8')
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict),command_timeout=150)
    transaction=connection.transaction()
    await transaction.start()
    try:
        if not apply:
            await connection.execute(sql)
            await transaction.rollback()
            print('Dry run passed: all inserts, constraints, ledger checks and RLS assertions; transaction rolled back')
            return
        await connection.execute(sql)
        await transaction.commit()
        row=await connection.fetchrow("SELECT * FROM public.fixture_seed_runs WHERE batch_tag='veloce-rigorous-v1'")
        counts={}
        for table in ['tenants','users','carrier_accounts','margin_rules','ecommerce_stores','shipments','wallets','wallet_reservations','wallet_ledger','tracking_events','support_tickets']:
            if table=='tenants':
                count=await connection.fetchval("SELECT count(*) FROM public.tenants WHERE company_profile->>'fixture_batch'='veloce-rigorous-v1'")
            else:
                count=await connection.fetchval(f"SELECT count(*) FROM public.{table} r JOIN public.tenants t ON t.tenant_id=r.tenant_id WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1'")
            counts[table]=count
        receipt={'batch_tag':row['batch_tag'],'generated_at':row['generated_at'].isoformat(),'completed':row['completed'],'counts':counts,
                 'external_integrations_excluded':['HubSpot','Twilio','Stripe'],'all_tenants_sandbox':True,'carrier_accounts_inactive':True,
                 'auth_principals_banned':True,'rls_owner_scope_verified':True,'wallet_ledger_reconciled':True}
        accounts=await connection.fetch("SELECT a.credentials_ciphertext,a.credential_key_id FROM public.carrier_accounts a JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1'")
        for account in accounts:
            clear=Fernet(settings.credential_keys[account['credential_key_id']].get_secret_value().encode()).decrypt(bytes(account['credentials_ciphertext']))
            assert json.loads(clear)['api_key']=='INACTIVE_SEED_ONLY_NOT_A_PROVIDER_KEY'
        receipt['fixture_encryption_verified']=True
        catalog={}
        selections={
            'tenants':"SELECT t.tenant_id,t.workspace_slug,t.company_name,t.default_currency,t.billing_plan,t.billing_status,t.workspace_status,w.balance,w.reserved_balance FROM public.tenants t JOIN public.wallets w USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1' ORDER BY t.workspace_slug",
            'members':"SELECT r.id,r.tenant_id,r.auth_user_id,r.role FROM public.users r JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1' ORDER BY t.workspace_slug,r.role",
            'carrier_accounts':"SELECT r.id,r.tenant_id,r.aggregator,r.environment,r.is_active FROM public.carrier_accounts r JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1' ORDER BY t.workspace_slug,r.aggregator",
            'shipments':"SELECT r.id,r.tenant_id,r.customer_reference,r.status,r.cargo_type,r.destination_country,r.currency,r.wholesale_cost,r.profit_markup,r.final_client_price FROM public.shipments r JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1' ORDER BY t.workspace_slug,r.customer_reference"}
        for name,query in selections.items():
            catalog[name]=[dict(record) for record in await connection.fetch(query)]
        Path('docs/rigorous_seed_catalog.json').write_text(json.dumps(catalog,indent=2,default=str))
        Path('docs/rigorous_seed_receipt.json').write_text(json.dumps(receipt,indent=2))
        print(json.dumps(receipt,indent=2))
    except Exception as exc:
        if connection.is_in_transaction():await connection.execute('ROLLBACK')
        # No raw database exception/payload/credentials are exposed.
        print('Seed failed and rolled back:',type(exc).__name__,'SQLSTATE:',getattr(exc,'sqlstate',None))
        raise SystemExit(1)
    finally:await connection.close()


if __name__=='__main__':asyncio.run(run('--apply' in sys.argv))
