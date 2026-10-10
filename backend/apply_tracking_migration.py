"""Apply only the additive tracking/support migration to configured Supabase."""
import asyncio
from pathlib import Path
import asyncpg
from main import Settings
from backend.database_tls import database_tls_context


async def run():
    settings = Settings()
    if settings.database_environment != "SANDBOX":
        raise ValueError("Automatic tracking migration restricted to configured sandbox")
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), ssl=database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict))
    try:
        sql = Path("migrations/011_tracking_and_support.sql").read_text(encoding="utf-8")
        prefix, rest = sql.split("END $$;", 1)
        await connection.execute(prefix + "END $$;")
        await connection.execute(rest)
        print("Migration 011 applied to configured Supabase sandbox")
    finally:
        await connection.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:
        print("Migration failed:", type(exc).__name__, "SQLSTATE:", getattr(exc, "sqlstate", None))
        raise SystemExit(1)
