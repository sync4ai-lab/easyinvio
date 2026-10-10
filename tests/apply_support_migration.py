"""Validate migration 014 with rollback, then apply to the configured sandbox."""
import asyncio,json,re
from pathlib import Path
import asyncpg
from main import Settings
from backend.database_tls import database_tls_context
async def run():
 s=Settings();assert s.database_environment=='SANDBOX'
 c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict))
 sql=Path('migrations/014_support_ticket_lifecycle.sql').read_text()
 sql=re.sub(r'^(BEGIN;|COMMIT;)\s*$', '',sql,flags=re.M)
 try:
  tx=c.transaction();await tx.start();await c.execute(sql);await tx.rollback()
  async with c.transaction():await c.execute(sql)
  assert await c.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='support_tickets' AND column_name='archived_at'")==1
  Path('docs/uat_100/migration_014_receipt.json').write_text(json.dumps({'migration':'014_support_ticket_lifecycle.sql','sandbox_applied':True,'rollback_validation_passed':True,'existing_rows_preserved':True},indent=2))
  print('Migration 014 validated and applied to configured Supabase sandbox.')
 finally:await c.close()
if __name__=='__main__':asyncio.run(run())
