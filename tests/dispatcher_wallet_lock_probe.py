"""Prove actual cross-session PostgreSQL wallet locks, without changing funds."""
import asyncio
import json
from pathlib import Path
import asyncpg
from main import Settings, FinanceEngine
from backend.database_tls import database_tls_context


async def run():
    settings=Settings();assert settings.database_environment=='SANDBOX'
    kwargs={'ssl':database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict)}
    first=await asyncpg.connect(settings.database_url.get_secret_value(),**kwargs)
    second=None;tx=None;other=None
    try:
        second=await asyncpg.connect(settings.database_url.get_secret_value(),**kwargs)
        tenant=await first.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
        assert tenant
        tx=first.transaction();await tx.start()
        engine=FinanceEngine(None,settings,None)
        before=await engine.lock_wallet(first,tenant)
        other=second.transaction();await other.start()
        await second.execute("SET LOCAL lock_timeout='250ms'")
        try:await engine.lock_wallet(second,tenant)
        except asyncpg.LockNotAvailableError:pass
        else:raise AssertionError('Concurrent session bypassed wallet row lock')
        await other.rollback();other=None
        await tx.rollback();tx=None
        after=await engine.lock_wallet(second,tenant)
        assert dict(before)==dict(after)
    finally:
        if other:await other.rollback()
        if tx:await tx.rollback()
        if second:await second.close()
        await first.close()
    result={'actual_supabase':True,'independent_database_sessions':2,'competing_wallet_lock_blocked':True,'balances_unchanged':True,'external_calls':0}
    Path('docs/dispatcher_journey').mkdir(parents=True,exist_ok=True)
    Path('docs/dispatcher_journey/wallet_lock_evidence.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':asyncio.run(run())
