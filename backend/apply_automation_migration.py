"""Apply the additive freight/support compatibility migration in sandbox."""
import asyncio
from pathlib import Path
import asyncpg
from main import Settings
from backend.database_tls import database_tls_context


async def run():
    settings=Settings()
    if settings.database_environment!='SANDBOX': raise ValueError('Sandbox required')
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    try:
        await connection.execute(Path('migrations/013_automation_freight.sql').read_text())
        print('Migration 013 applied; no funds or labels created')
    finally: await connection.close()


if __name__=='__main__':
    try: asyncio.run(run())
    except Exception as exc:
        print('Migration failed:',type(exc).__name__,'SQLSTATE:',getattr(exc,'sqlstate',None))
        raise SystemExit(1)
