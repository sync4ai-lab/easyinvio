"""Read-only connection/schema probe. Never log credentials or raw server errors."""
import asyncio
import json
import ssl
from pathlib import Path

import asyncpg
import httpx

from main import Settings
from backend.database_tls import database_tls_context


async def run():
    settings = Settings()
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        public = await client.get(settings.supabase_url + "/auth/v1/settings", headers={"apikey": settings.supabase_publishable_key.get_secret_value()})
        print("Supabase public key check HTTP:", public.status_code)
        key = settings.supabase_service_role_key.get_secret_value()
        headers = {"apikey": key}
        if not key.startswith("sb_secret_"):
            headers["Authorization"] = "Bearer " + key
        rest = await client.get(settings.supabase_url + "/rest/v1/tenants", params={"select": "tenant_id", "limit": "0"}, headers=headers)
        print("Supabase server key/table check HTTP:", rest.status_code)
        tables = ["tenants", "users", "carrier_accounts", "margin_rules", "shipments", "wallets",
                  "wallet_topups", "wallet_reservations", "wallet_ledger", "whatsapp_bindings", "whatsapp_routes",
                  "whatsapp_quote_choices", "whatsapp_receipts", "admin_configuration_events",
                  "ecommerce_stores", "ecommerce_tracking_outbox", "hubspot_sync_jobs", "hubspot_tenant_links"]
        async def check_table(table):
            response = await client.get(settings.supabase_url + "/rest/v1/" + table,
                                        params={"select": "*", "limit": "0"}, headers=headers)
            return table, response.status_code
        statuses = dict(await asyncio.gather(*(check_table(table) for table in tables)))
        print("REST migration table checks:", statuses)
        schema = await client.get(settings.supabase_url + "/rest/v1/", headers={**headers, "Accept": "application/openapi+json"})
        if schema.status_code == 200:
            definitions = schema.json().get("definitions", {})
            report = {"api_verified": public.status_code == 200 and rest.status_code == 200,
                      "table_statuses": statuses, "table_definitions": {name: definitions.get(name, {}) for name in tables}}
            Path("docs/supabase_rest_schema_verified.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print("Schema-only REST report saved; no application rows retrieved or written")
    connection = await asyncpg.connect(settings.database_url.get_secret_value(), ssl=database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict), timeout=15)
    try:
        role = await connection.fetchrow("SELECT rolsuper OR rolbypassrls AS bypass,pg_has_role(current_user,'authenticated','MEMBER') AS can_set_role FROM pg_roles WHERE rolname=current_user")
        tables = await connection.fetch("SELECT table_name,column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema='public' AND table_name=ANY($1::text[]) ORDER BY table_name,ordinal_position", ["tenants", "wallets", "shipments", "margin_rules", "carrier_accounts"])
        report = {"database_connected": True, "trusted_role": dict(role), "columns": [dict(row) for row in tables]}
        Path("docs/supabase_schema_verified.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("PostgreSQL connection verified; trusted role:", dict(role))
        print("Schema-only report saved to docs/supabase_schema_verified.json")
    finally:
        await connection.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:
        print("Verification failed:", type(exc).__name__, "SQLSTATE:", getattr(exc, "sqlstate", None))
        raise SystemExit(1)
