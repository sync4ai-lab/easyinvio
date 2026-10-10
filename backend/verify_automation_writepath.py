"""Real PostgreSQL write-path probe with controlled rates and final rollback.

No HubSpot, Twilio, Stripe or carrier requests are made. Seed fixtures are
unchanged after the test transaction is rolled back.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import asyncpg
from main import Settings,RatingRequest,ClientRate
from backend.database_tls import database_tls_context
from backend.automation_freight_engine import AutomationService


class BorrowedPool:
    def __init__(self,connection):self.connection=DiagnosticConnection(connection)
    @asynccontextmanager
    async def acquire(self):yield self.connection


class DiagnosticConnection:
    def __init__(self,connection):self.connection=connection
    def __getattr__(self,name):return getattr(self.connection,name)
    async def execute(self,*args):
        try:return await self.connection.execute(*args)
        except asyncpg.PostgresError as exc:
            print('Schema diagnostic:',type(exc).__name__,exc.sqlstate,getattr(exc,'constraint_name',None),exc.message)
            raise


async def run():
    settings=Settings()
    if settings.database_environment!='SANDBOX':raise ValueError('Sandbox required')
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    tx=connection.transaction();await tx.start()
    try:
        tenant=await connection.fetchrow("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
        user=await connection.fetchrow("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER'",tenant['tenant_id'])
        account=await connection.fetchrow("SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND aggregator='REGIONAL'",tenant['tenant_id'])
        context=SimpleNamespace(tenant_id=tenant['tenant_id'],user_id=user['auth_user_id'],role='OWNER')
        async def accounts(ctx):return [SimpleNamespace(id=account['id'],provider='REGIONAL')]
        async def quote(ctx,request):
            now=datetime.now(timezone.utc)
            rate=ClientRate(provider='REGIONAL',account_id=account['id'],upstream_shipment_id='ROLLBACK-PROBE-'+uuid4().hex,upstream_rate_id='ROLLBACK-RATE-'+uuid4().hex,
                carrier_code='SEED_ONLY',service_code='ROLLBACK',currency=request.currency,client_price_ex_tax=Decimal('12.00'),delivery_days=None,
                fee_breakdown={'wholesale_total':'10.00','platform_markup':'2.00'})
            return SimpleNamespace(rates=[rate],quoted_at=now,expires_at=now+timedelta(minutes=15),partial=False,issues=[])
        service=AutomationService(BorrowedPool(connection),SimpleNamespace(quote=quote),None,SimpleNamespace(accounts=accounts),RatingRequest,None,settings)
        address={'name':'Rollback probe','line1':'1 Fixture Way','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
        results=[]
        for kind in ['LETTER','PARCEL','PALLET','OVERLAND_FREIGHT','CUSTOMS']:
            cargo={'cargo_type':kind if kind!='CUSTOMS' else 'PARCEL','actual_weight_kg':'0.100' if kind=='LETTER' else '2.500',
                   'length_cm':'40','width_cm':'30','height_cm':'20'}
            raw={'idempotency_key':str(uuid4()),'order_reference':'ROLLBACK SCHEMA PROBE '+kind,'origin':address.copy(),'destination':address.copy(),
                 'cargo':cargo,'currency':'GBP'}
            if kind=='CUSTOMS':
                raw.update(destination={**address,'country_code':'USA'},customs_signer='Synthetic reviewer',hs_codes_reviewed=True,
                           items=[{'description':'Cotton T-shirt','quantity':1,'unit_value':'12.35','unit_weight_kg':'0.200','origin_country':'GB'}])
            result=await service.process(context,raw,'QUOTE_ONLY')
            if result['status']!='QUOTED':raise ValueError('Write-path probe failed: '+result.get('error','unknown'))
            row=await connection.fetchrow("SELECT final_client_price,pricing_snapshot,customs_required,customs_reviewed_at,customs_content_type FROM public.shipments WHERE tenant_id=$1 AND id=$2",context.tenant_id,__import__('uuid').UUID(result['shipment_id']))
            assert row['final_client_price']==Decimal('12.00')
            if kind=='CUSTOMS':assert row['customs_reviewed_at'] and row['customs_content_type']=='MERCHANDISE'
            results.append({'cargo_case':kind,'status':'QUOTED','generated_total':'12.00'})
        await tx.rollback()
        report={'real_database_writepath_verified':True,'transaction_rolled_back':True,'cases':results,'external_api_calls':0,'labels_purchased':0}
        Path('docs/automation_writepath_verification.json').write_text(json.dumps(report,indent=2))
        print('Five real Supabase quote writes verified; generated prices and customs review constraints passed; all probe rows rolled back')
    except Exception as exc:
        try:await tx.rollback()
        except Exception:pass
        print('Write-path probe failed:',type(exc).__name__,'SQLSTATE:',getattr(exc,'sqlstate',None))
        raise SystemExit(1)
    finally:await connection.close()


if __name__=='__main__':asyncio.run(run())
