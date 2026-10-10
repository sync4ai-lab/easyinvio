# Platform administration and tenant pricing

The complete implementation is in `backend/admin_portal.py` and is mounted by `main.py`. These are real database controllers; preview mode returns 503 instead of simulating admin writes.

## Activation

1. Apply `migrations/007_admin_configuration.sql` in Supabase SQL Editor after the existing migrations. It adds company-profile fields, a private idempotency/audit table and a pricing index. It ensures `markup_value` uses exact PostgreSQL numeric storage and restricts pricing/billing changes to trusted backend roles while retaining read policies.
2. In Supabase Authentication → Users, copy the **Auth user UUID** of your platform-owner account. Configure its UUID in the local `.env`:

```dotenv
PLATFORM_ADMIN_USER_IDS=["YOUR_REAL_SUPABASE_AUTH_USER_UUID"]
```

3. Complete the other `.env` settings, then start configured mode:

```powershell
.venv/Scripts/python.exe -m backend.check_setup
.venv/Scripts/python.exe main.py
```

4. Sign in with that Supabase Auth account. Send its access token in `Authorization: Bearer <access_token>` to the endpoints, or authorize in `/docs`.

Platform authorization verifies the token signature through JWKS, issuer, audience, expiry, role and subject, then checks the subject against the server-side allowlist. Customer `OWNER` roles and client metadata do not grant platform access. The platform owner does not need tenant membership or a `tenant_id` token claim, so the first tenant can be created.

The trusted database role must have the schema/table privileges used by the original backend, including access to `auth.users.id` if binding existing Auth users, and permission to insert/read `admin_configuration_events`. Supabase's trusted postgres connection is compatible with the original backend's required BYPASSRLS/SET ROLE contract. This implementation does not call the Supabase Auth admin API or send invitations.

## Register a company

`POST /api/v1/admin/tenants` returns HTTP 201 with the generated UUID and saved profile:

```json
{
  "request_id": "11111111-1111-4111-8111-111111111111",
  "company_profile": {
    "company_name": "Northstar Trading Ltd",
    "contact_name": "Alex Smith",
    "billing_email": "billing@example.com",
    "address_line1": "10 Business Road",
    "city": "London",
    "postal_code": "SW1A 1AA",
    "country_code": "GB"
  },
  "billing_plan": "PREPAID_WALLET",
  "default_currency": "GBP"
}
```

Also supports `POSTPAID_30_DAY`, optional `owner_auth_user_id` for an **existing** Supabase Auth user, and optional existing `stripe_customer_id`. Registration creates an ACTIVE workspace/billing account, a zero-balance wallet, optional OWNER membership and an admin audit event atomically. It creates no Stripe customer and moves no money. With no owner Auth UUID, create/provision the membership before customer login; existing tenant-claim hooks remain necessary for customer endpoints.

Supply the same `request_id` and payload when retrying. The server takes a transaction-scoped advisory lock and returns the stored response instead of duplicating records. Reusing the ID with a different payload returns 409. Omitting it creates a new request ID, so distinct retries without an ID cannot be deduplicated.

## Create a margin rule

`POST /api/v1/admin/margins`:

```json
{
  "request_id": "22222222-2222-4222-8222-222222222222",
  "tenant_id": "REPLACE_WITH_REGISTERED_TENANT_UUID",
  "destination_country": "USA",
  "carrier_code": "DHL",
  "markup_type": "PERCENTAGE",
  "markup_value": "17.125",
  "priority": 10
}
```

Use `FLAT_RATE` and a value such as `"2.50"` for a fixed monetary markup. Decimal strings are recommended; floating-point JSON numbers and nonfinite/negative values are rejected. Percentage values accept up to six decimal places; flat amounts and monetary clamps accept at most two. Alpha-3 country inputs such as USA are stored as alpha-2 US to match the existing application. Carrier/service codes are uppercase. Currency defaults to the target tenant's default currency, so flat amounts are never silently applied across currencies.

The full model also supports origin, service, tenant-owned carrier account, lower/upper weight and wholesale-cost bounds, minimum/maximum markup, enabled state and timezone-aware validity windows. Upper weight/cost bounds are exclusive. Cross-tenant carrier-account IDs are rejected. The existing base schema must support `FLAT_RATE`/`PERCENTAGE` in `margin_rules.markup_type`, as expected by the original main.py adapter. Legacy `FIXED` rows remain readable by the evaluator.

## Dynamic evaluator

```python
from decimal import Decimal
from uuid import UUID
from backend.admin_portal import get_client_calibrated_rate

price = await get_client_calibrated_rate(
    UUID("YOUR_TENANT_UUID"), Decimal("10.00"), "DHL", "USA"
)
```

The application binds its asyncpg pool during startup and clears it on shutdown. This function is **async** to query PostgreSQL without blocking FastAPI. It reads tenant status/currency and the matching rule in a read-only repeatable-read transaction. The rule query is explicitly tenant-scoped and filters carrier, destination, currency, validity, cost bounds and any additional selectors available in the task-local pricing scope.

Lower priority numbers win. Equal priority is resolved by more specific rules, then oldest creation timestamp, then UUID. A missing rule retains the original 20% default; malformed stored configuration or database errors fail closed instead of silently dropping the markup. Configured rules use the existing two-decimal half-up rounding/clamp behavior; the fallback rounds markup upward to cents.

The live `RatingService.quote` now calls this utility with task-local currency, carrier account, origin, service and billable weight. Single quotes, batch quotes and WhatsApp quotes therefore share the same tenant-specific database pricing. A four-argument standalone call uses the tenant's default currency and excludes rules requiring account/service/origin/weight selectors it cannot supply.

## Verification and schema limits

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Tests exercise actual JWT verification with local EC keys, platform-vs-customer authorization, registration atomicity/rollback, idempotent retries, Decimal writes, country normalization, account ownership, pricing scope isolation and existing rating integration. Database calls use test doubles; the migration and writes have **not** been executed against your Supabase instance. The original SQL files remain absent from this workspace. Extra NOT NULL fields or custom triggers in your deployed base schema may require corresponding schema integration; database failures are returned without exposing credentials or SQL details.

References: [asyncpg transactions, pools and Decimal mapping](https://magicstack.github.io/asyncpg/current/usage.html), [Supabase JWT verification](https://supabase.com/docs/guides/auth/jwts).
