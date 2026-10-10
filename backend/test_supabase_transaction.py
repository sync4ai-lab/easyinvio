"""Explicit, persisted sandbox connectivity test. Creates no payments or labels."""
import asyncio
import json
import ssl
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg

from main import Settings
from backend.database_tls import database_tls_context
from backend.admin_portal import configure_pricing_pool, get_client_calibrated_rate


async def run():
    settings = Settings()
    if settings.database_environment != "SANDBOX":
        raise ValueError("The connectivity transaction requires SANDBOX configuration")
    if settings.stripe_enabled or settings.twilio_enabled:
        raise ValueError("Disable external payment/messaging integrations for this test")
    tenant_id, rule_id = uuid4(), uuid4()
    label = "VELOCE CONNECTIVITY TEST " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    address = {"line1": "Sandbox test only", "city": "London", "postal_code": "SW1A 1AA", "country_code": "GB"}
    profile = {"company_name": label, "billing_email": "connectivity-test@example.invalid", "test_record": True,
               "purpose": "Verify a real committed Supabase transaction; no funds or dispatch"}
    pool = await asyncpg.create_pool(settings.database_url.get_secret_value(),
                                    ssl=database_tls_context(settings.database_ca_file, strict=settings.database_tls_strict), min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("""INSERT INTO public.tenants
                    (tenant_id,workspace_slug,workspace_name,legal_company_name,billing_email,billing_address,
                     company_name,company_profile,billing_plan,billing_status,workspace_status,default_currency,is_sandbox)
                    VALUES($1,$2,$3,$3,$4,$5::jsonb,$3,$6::jsonb,'PREPAID_WALLET','ACTIVE','ACTIVE','GBP',true)""",
                    tenant_id, "connectivity-test-" + tenant_id.hex, label, profile["billing_email"], json.dumps(address), json.dumps(profile))
                await connection.execute("""INSERT INTO public.wallets(tenant_id,currency,balance,reserved_balance)
                    VALUES($1,'GBP',0,0) ON CONFLICT(tenant_id) DO NOTHING""", tenant_id)
                await connection.execute("""INSERT INTO public.margin_rules
                    (id,tenant_id,rule_name,currency,markup_type,markup_value,minimum_markup,priority,is_active)
                    VALUES($1,$2,'CONNECTIVITY TEST ONLY','GBP','PERCENTAGE',$3,0,10,true)""", rule_id, tenant_id, Decimal("20"))
        receipt = {"tenant_id": str(tenant_id), "company_name": label, "margin_rule_id": str(rule_id),
                   "committed": True, "wallet_balance": "0.00", "money_processed": False, "labels_purchased": False}
        Path("docs/supabase_connectivity_test.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        configure_pricing_pool(pool)
        price = await get_client_calibrated_rate(tenant_id, Decimal("10.00"), "DHL", "USA")
        assert price == Decimal("12.00"), "Database pricing test failed"
        async with pool.acquire() as connection:
            assert await connection.fetchval("SELECT balance FROM public.wallets WHERE tenant_id=$1", tenant_id) == Decimal(0)
        receipt["verified_customer_price"] = str(price)
        receipt["verified"] = True
        Path("docs/supabase_connectivity_test.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
    finally:
        configure_pricing_pool(None)
        await pool.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:
        print("Sandbox transaction check failed:", type(exc).__name__, "SQLSTATE:", getattr(exc, "sqlstate", None))
        raise SystemExit(1)
