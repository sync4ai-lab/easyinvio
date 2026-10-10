"""Persist one clearly identified invalid-order support test; no carrier calls."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID,uuid5,NAMESPACE_URL
import asyncpg
from main import Settings,RatingRequest
from backend.database_tls import database_tls_context
from backend.automation_freight_engine import AutomationService


async def run():
    settings=Settings()
    if settings.database_environment!='SANDBOX':raise ValueError('Sandbox required')
    receipt=json.loads(Path('docs/supabase_connectivity_test.json').read_text())
    tenant_id=UUID(receipt['tenant_id'])
    pool=await asyncpg.create_pool(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict),min_size=1,max_size=2)
    try:
        service=AutomationService(pool,None,None,None,RatingRequest,None,settings)
        raw={'idempotency_key':str(uuid5(NAMESPACE_URL,str(tenant_id)+':automation-validation-test')),
             'order_reference':'AUTOMATION VALIDATION TEST - NO DISPATCH',
             'origin':{'name':'Sandbox','line1':'Test only','city':'London','postal_code':'SW1A 1AA','country_code':'GB'},
             'destination':{'name':'Sandbox','line1':'Test only','city':'London','postal_code':'SW1A 1AA','country_code':'INVALID'},
             'cargo':{'cargo_type':'LETTER','actual_weight_kg':'0.100'}}
        result=await service.process(SimpleNamespace(tenant_id=tenant_id,user_id=tenant_id,role='OWNER'),raw,'QUOTE_ONLY')
        assert result['status']=='FAILED' and result['support_ticket_recorded']
        async with pool.acquire() as connection:
            ticket=await connection.fetchrow("""SELECT t.id FROM public.support_tickets t JOIN public.automation_failures f
                ON f.id=t.automation_failure_id AND f.tenant_id=t.tenant_id
                WHERE t.tenant_id=$1 AND f.order_reference=$2""",tenant_id,raw['order_reference'])
            assert ticket is not None
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant_id)==0
        output={'tenant_id':str(tenant_id),'support_ticket_id':str(ticket['id']),'result':result,'wallet_unchanged':True,'carrier_calls':0,'labels_created':0}
        Path('docs/automation_sandbox_verification.json').write_text(json.dumps(output,indent=2))
        print('Real sandbox invalid-order failure and support ticket persisted; wallet unchanged; no carrier calls')
    finally:await pool.close()


if __name__=='__main__':
    try:asyncio.run(run())
    except Exception as exc:
        print('Automation verification failed:',type(exc).__name__,'SQLSTATE:',getattr(exc,'sqlstate',None))
        raise SystemExit(1)
