"""Export only schema metadata needed for relational sandbox fixtures."""
import asyncio
import json
from pathlib import Path
import asyncpg
from main import Settings
from backend.database_tls import database_tls_context


async def run():
    s=Settings()
    c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict))
    try:
        tables=['tenants','users','carrier_accounts','margin_rules','shipments','wallets','wallet_ledger','wallet_reservations','ecommerce_stores','tracking_events','support_tickets','automation_failures']
        columns=await c.fetch("SELECT table_schema,table_name,column_name,data_type,udt_name,is_nullable,column_default,is_generated,generation_expression FROM information_schema.columns WHERE (table_schema='public' AND table_name=ANY($1::text[])) OR (table_schema='auth' AND table_name='users') ORDER BY table_schema,table_name,ordinal_position",tables)
        constraints=await c.fetch("SELECT n.nspname AS schema,t.relname AS table_name,k.conname,pg_get_constraintdef(k.oid) AS definition FROM pg_constraint k JOIN pg_class t ON t.oid=k.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname IN ('public','auth') AND t.relname=ANY($1::text[]) ORDER BY n.nspname,t.relname,k.conname",tables)
        triggers=await c.fetch("SELECT n.nspname AS schema,t.relname AS table_name,g.tgname,pg_get_triggerdef(g.oid) AS definition FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE NOT g.tgisinternal AND n.nspname IN ('public','auth') AND t.relname=ANY($1::text[]) ORDER BY n.nspname,t.relname",tables)
        out={'columns':[dict(r) for r in columns],'constraints':[dict(r) for r in constraints],'triggers':[dict(r) for r in triggers]}
        out['customs_validator']=await c.fetchval('SELECT pg_get_functiondef($1::regprocedure)','veloce_private.valid_customs_items(jsonb)')
        Path('docs/seed_schema_verified.json').write_text(json.dumps(out,indent=2))
        print('Schema-only seed metadata exported; no customer records read')
    finally:await c.close()


if __name__=='__main__':asyncio.run(run())
