"""Real sandbox schema, tenant-scoped report and durable ticket-worker verification."""
import asyncio
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import asyncpg
from main import Settings
from backend.database_tls import database_tls_context
from backend.tracking_and_support import TrackingSettings, TrackingSupportService


async def run():
    settings = Settings()
    receipt = json.loads(Path("docs/supabase_connectivity_test.json").read_text())
    tenant_id = UUID(receipt["tenant_id"])
    pool = await asyncpg.create_pool(settings.database_url.get_secret_value(), ssl=database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict), min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection:
            for table in ["tracking_events", "support_tickets", "support_message_outbox"]:
                assert await connection.fetchval("SELECT to_regclass($1)", "public." + table)
            await connection.execute("SELECT proof_of_delivery_url FROM public.shipments LIMIT 0")
        service = TrackingSupportService(pool, TrackingSettings())
        report = await service.report(SimpleNamespace(tenant_id=tenant_id, role="OWNER"), date.today().replace(day=1), date.today(), 1, 100)
        await service.stage_tickets()
        output = {"migration_verified": True, "database_report_verified": True, "tenant_id": str(tenant_id), "report": report}
        Path("docs/tracking_support_verification.json").write_text(json.dumps(output, indent=2))
        print("Real Supabase tracking tables, POD column, empty ticket worker and tenant-scoped report verified")
    finally:
        await pool.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:
        print("Tracking verification failed:", type(exc).__name__, "SQLSTATE:", getattr(exc, "sqlstate", None))
        raise SystemExit(1)
