# EasyInvio.com operations prototype

The current [application manual](docs/platform_overview/overview.html) is the consolidated functional/technical architecture and onboarding reference through migration 045. It includes all agent responsibilities, generated API schemas, integrations, security/financial invariants and operational recovery procedures. Its [source index](docs/platform_overview/README.md) explains how to rebuild the `EasyInvio-Architecture` folder and downloadable ZIP. Older feature/UAT reports below retain their original evidence scope.

The product is branded **EasyInvio.com**. Existing `veloce_*` database/CRM identifiers, webhook headers, token issuers, browser storage keys and fixture IDs remain compatible with deployed data and integrations. The local project folder and configured Git remote keep their existing names.

The [CSV orders v2 guide](docs/bulk_csv/REPORT.md) covers the 21-column client template,
per-order persistence, cargo routing, customs review and optional storefront associations.

See [core pillar verification](docs/core_pillars/REPORT.md) for supported workflows and live integration requirements. The [Git setup guide](docs/GIT_SETUP.md) covers uploads, branch maintenance, secret exclusions and the missing original database baseline.

The [24-customer relational seed pack](seeds/rigorous_v1/README.md) is applied to the Supabase sandbox, with complete ordered SQL scripts, constraint/RLS verification and a fixture catalog for subsequent tests.

The [automation/freight engine](docs/automation_freight.md) adds cargo-aware rating, customs bundles, bounded bulk fulfillment, failure tickets and purchase reconciliation. Real label purchasing remains disabled in the configured sandbox.

The [dual-role dashboard](docs/dashboard_portal.md) retains operational workflows and adds server-authorized owner/client analytics, mobile navigation, box profiles and support actions.

See [tracking, delivery proof, support and analytics setup](docs/tracking_and_support.md) for signed aggregator callbacks, migration 011, support staging and financial reporting.

For the Supabase session pooler, `DATABASE_CA_FILE=certs/supabase-root-2021.crt` trusts the downloaded public Supabase root CA. This project's observed legacy intermediate lacks Key Usage, so Python 3.14 requires `DATABASE_TLS_STRICT=false`; CA signatures, validity and hostname checks remain enabled. Restore strict mode when Supabase serves a conforming chain. Connection failures are reported without printing credential values.

Supabase-only operation is supported: leave `STRIPE_ENABLED=false` and `TWILIO_ENABLED=false` until those credentials are available. Start configured mode with `.venv/Scripts/python.exe main.py` after database settings validate. The read-only connection probe is `.venv/Scripts/python.exe -m backend.verify_supabase`.

Optional [HubSpot CRM setup](docs/hubspot_crm.md) covers migration 010, custom properties, private-app credentials, durable tenant synchronization and shipping upsell milestones.

Python 3.12+; verified locally with Python 3.14. Credentials remain in `.env`, which is excluded from source control.

```powershell
py -3.14 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe main.py --self-test
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe main.py --local-preview
```

Open **http://127.0.0.1:8000/** for the complete UI, or `/docs` for the API. The optional separate frontend server still works:

```powershell
.venv/Scripts/python.exe serve_frontend.py
```

Its UI at http://127.0.0.1:5500 calls port 8000. Explicit local CORS origins are configured by default. Use `FRONTEND_ALLOWED_ORIGINS` for other deployments; it is a JSON array, not a wildcard. Serving through the backend avoids cross-origin setup. No CDN assets are required by the UI.

## Implemented modules

- `backend/ai_engine.py`: explainable HS suggestions with simulated confidence and abstention, Decimal historical-delay analysis, invoice comparison and unsent dispute drafting.
- `backend/advanced_logistics.py`: volumetric pricing, reviewed CN22/CN23 and commercial-invoice JSON metadata, concurrent CSV quoting, tenant manifest and wallet reads.
- `backend/admin_portal.py`: platform-owner tenant registration, persistent margin calibration and the database-backed evaluator used by every live pricing request. Apply migration 007 and configure `PLATFORM_ADMIN_USER_IDS`; see [admin setup and request examples](docs/admin_portal.md).
- `backend/sandbox_hooks.py`: real Stripe test-token top-ups, zero-balance label checks, hardened Twilio Sandbox webhook parsing and platform-owner phone/route setup. Apply migration 008 and follow [sandbox setup](docs/sandbox_integrations.md); test credits require marked sandbox tenants in a sandbox database.
- `index.html`: Dispatch, Manifest, Wallet and Customs Tools; Supabase password login; live/preview rate requests and fee disclosures; batch upload/export; invoice auditing; declaration download; sample ZPL and mock AirPrint notifications.
- `main.py`: mounts both routers, applies dimensional weight to all provider requests and pricing rules, serves public configuration and the frontend, and retains existing JWT, tenant, wallet and webhook controls.

The weight formula is length × width × height / 5000 in cm/kg, rounded **up** to 0.001 kg, then compared with actual weight. Providers receive the higher weight; quoted shipments are limited to 1000 kg billable weight. Carrier-specific dimensional divisors may differ; this prototype implements the requested fixed divisor.

Live fee breakdowns show provider-reported components only. Regional providers may return `fee_breakdown` with decimal-string `base_cost`, `fuel_surcharge`, `residential_fee` and `remote_area_fee`; all four are required and must sum exactly to `wholesale_cost`. Otherwise the UI shows the quoted carrier total and platform markup while individual fees remain “Not reported.” EasyPost's current adapter returns aggregate rates, not individual fee components.

HS suggestions use a small curated HS-2022 rule set. They require material/construction review and destination-specific tariff verification. Confidence is simulated, not calibrated ML. See [UK tariff lookup](https://www.gov.uk/trade-tariff) and [footwear classification guidance](https://www.gov.uk/guidance/classifying-footwear). Declaration output is JSON metadata, not an officially submitted or signed customs form. Select CN22/CN23 according to your postal operator's eligibility rules.

## Supabase and configured mode

Copy `.env.example` to `.env` **only if `.env` does not already exist**. Fill all required variables. The backend accepts a legacy service-role JWT or a modern `sb_secret_` key in `SUPABASE_SERVICE_ROLE_KEY`; privileged keys never reach the frontend. The public config endpoint returns only the project URL and publishable key.

```powershell
.venv/Scripts/python.exe -m backend.check_setup
.venv/Scripts/python.exe main.py
```

The setup check prints invalid variable names without printing their values. Configured startup checks database connectivity, trusted-role capabilities and the original required tables. Supabase tokens require a top-level `tenant_id` claim and ES256/RS256 signing compatible with `JWT_ALGORITHM`. Enable the appropriate Custom Access Token Hook, provision an active tenant membership, and configure carrier accounts and wallet records. App tokens remain in memory, renew during activity and are cleared on refresh/sign-out. Fifteen minutes of inactivity or the eight-hour work-session limit requires sign-in again. Editable forms are cleared at session boundaries; see [session lifecycle](docs/session_lifecycle.md).

## Migration and recorded audit data

Run **`migrations/006_logistics_metadata.sql` in Supabase SQL Editor after your original migrations**. It adds `shipments.logistics_metadata` and a trigger restricting changes to trusted superuser/BYPASSRLS backend roles. It preserves existing table grants and RLS. This migration was prepared locally and has not been applied to your Supabase account.

Audits read shipment records by both tenant ID and shipment ID. Only OWNER, ADMIN or ACCOUNTANT users can audit or read wallet balances. Uploaded invoices cannot replace stored baselines. Baselines should be recorded from confirmed carrier quote/booking data using `record_invoice_baseline(connection, tenant_id, shipment_id, baseline)` inside trusted booking code:

```json
{
  "currency": "GBP",
  "billable_weight_kg": "4.800",
  "base_cost": "16.00",
  "fuel_surcharge": "1.92",
  "residential_fee": "1.50",
  "remote_area_fee": "0.00"
}
```

These values live under `logistics_metadata.invoice_baseline`. Shipments without complete baselines report `baseline_missing_or_invalid`; unknown/cross-tenant shipment IDs report `shipment_not_found`. Weight discrepancies are flagged but not assigned invented monetary penalties. Component overcharges are summed separately by currency; they require reconciliation before sending a dispute.

Routing reads the shipment `origin_country` and `destination_country` columns and `tracking: {"provider":"EASYPOST","delay_days":"2.00"}` from tenant shipment records. Store actual observed delivery delays via your tracking ingestion process. Missing history produces an unknown risk, not fabricated observations. At least five records per provider are needed for a recommendation.

The original startup tables remain: tenants, users, carrier_accounts, margin_rules, shipments, wallets, wallet_topups, wallet_reservations, wallet_ledger, whatsapp_bindings, whatsapp_routes, whatsapp_quote_choices and whatsapp_receipts. The original SQL referenced as Steps 2, 4 and 5 is not stored in this workspace.

## CSV interface

`POST /api/v1/shipments/batch` accepts a raw UTF-8 CSV upload with `Content-Type: text/csv` and a Supabase Bearer token. Download the exact header/template from Dispatch. The limit is 1000 rows / 5 MB. Duplicate references, malformed addresses and invalid amounts become row errors. At most eight orders run concurrently; the existing global provider semaphore also caps carrier requests. Each result preserves its order reference and input row. Uploading rates orders and creates **zero bookings**.

## Preview and operational limits

`--local-preview` enables explicit fixture endpoints for rates, batch, audit and routing. Live integration endpoints return 503 in preview; fixture endpoints return 404 in configured mode. Preview wallet/manifest changes exist only in the browser session. Supabase, Stripe, Twilio, customs submission and printer broadcasts are not called by preview operations.

Real carrier label purchase remains outside the original backend and this requested feature matrix; the live quote review explains this. ZPL outputs are visibly marked sample/non-carrier labels, and AirPrint is a notification simulation. `record_invoice_baseline` is ready for the trusted booking integration; existing shipments are not automatically backfilled with guessed fees. Real tracking ingestion must populate history. This is a functional production-oriented prototype, not a certified production logistics service.

## Verification

Offline tests cover exact money, rounding, provider billable-weight propagation, fee reconciliation, invoice overcharges, tenant query scope, role checks, CSV limits, partial row handling, bounded concurrency and preview/live endpoint separation. `tests/frontend_contract.cjs` runs actual inline controllers against a lightweight DOM test double to check state/event behavior; it does not replace browser rendering tests. No browser is connected in the current environment. Actual Supabase/carrier/payment/printer integration verification requires configured services.
# E-commerce integration

See [store import and simulated tracking setup](docs/ecommerce_sync.md) for migration 009, store provisioning, the authenticated order payload and confirmed-label callback behavior.


See [Tracking 2.0 implementation and rollout](docs/tracking_2_implementation.md) for the shared workspace, customer links, channel security, read-only reconciliation and verification limits.
