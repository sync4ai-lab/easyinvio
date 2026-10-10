# Warehouse dispatcher journey verification

Validated on 10 October 2026. The configured backend is running at
http://127.0.0.1:8000. This report describes this journey; it does not replace
the earlier 100-case UAT report or mark unrelated cases as passed.

## Implemented connections

Dispatchers now have **Marketplace Workspace**, Speed Quote Matrix, Box Profiles
and Manifest & Labels. They cannot access financial ledgers, store credential
management or platform administration. Client owners/admins can also use the
operational workspace; accountants retain their existing financial views.

The workspace provides:

1. **Sync Marketplace Orders** and a paginated, tenant-scoped inbox. Signed
   Shopify/WooCommerce webhooks and the existing Amazon adapter gateway remain
   available. An explicitly enabled Shopify connector can also poll open,
   wholly unfulfilled orders through GraphQL, up to 1,000 per sync invocation,
   with a continuation cursor. Invalid orders do not discard successful imports.
   Other stores refresh their webhook inbox; they are not presented as having
   an implemented native polling adapter.
2. Per-order packing/customs review. Enter measured packed dimensions, gross
   weight and cargo class; review both addresses, phone/state, goods origin,
   unit values, net weight, HS suggestions and signer. Imports do not invent
   packed dimensions or manufacturing origin. International HS review requires
   explicit codes. The form exposes the complete goods array and addresses
   as editable JSON, with separate packing and review controls.
3. Parallel quotes using the existing router, database margin selection and
   cheapest-rate selection. Preparing an order fetches quotes without buying.
   Select up to 100 prepared orders for each processing run; additional pages
   allow further runs. The existing global concurrency limiter is shared.
4. Explicit label purchase through the existing atomic reserve/submit/capture
   workflow. Sandbox/live gates remain in force. Uncertain carrier purchases
   require reconciliation; the workspace never blindly buys a replacement.
5. A unified PDF download after successful bookings, with a manual retry button.
   Original carrier PDF label sizes are preserved, reviewed commercial invoices
   are rendered and carrier forms are appended. Missing documents fail the
   download without changing a successful booking into a failed purchase.
   Actual carrier CN22/CN23 forms are required when requested; the commercial
   invoice is not falsely labelled as an official postal declaration.
6. Visible tracking push-back state from the existing durable outbox. A pending
   or simulated delivery is not labelled as a successful remote store update.

## Verification results

| Check | Result and evidence boundary |
|---|---|
| Backend/application regressions | **PASS — 102 tests**, including freight, customs, tenant rules, imports, tracking, dashboard, security and new workspace/PDF checks. Expected error-path logs occurred during negative tests. |
| Hundred-order execution with one unprepared order | **PASS** — 99 proceed, one stays review-required; the shared limiter permits at most four concurrent operations. Controlled service responses, not live carriers. |
| Shopify polling adapter | **PASS** — controlled official-shape GraphQL responses: cursor pagination, address/phone and Decimal unit values; oversized/partial item data isolated for review. No merchant account was contacted. |
| Actual Supabase import/preparation | **PASS** — 100 international orders inserted, each replayed without duplication, HS suggestions reviewed, packing and customs stored, database pricing used and quotes persisted. Controlled carrier rates. |
| Tenant and role boundaries | **PASS** — another tenant's order returns 404; accountant dispatch is denied; internal fee breakdowns are suppressed for dispatchers. Configured backend rejects unsigned requests with 401. |
| Sandbox purchase boundary | **PASS** — all 100 purchase attempts rejected by the environment fence; no carrier label bought. |
| Wallet locking | **PASS** — two independent real PostgreSQL sessions: the second competing wallet lock is blocked; balances remain unchanged. This validates the actual row-lock mechanism, not a live 100-purchase stress test. |
| Wallet settlement | **PASS** — actual PostgreSQL reserve/capture with controlled receipts: 20.00, 12.33 and 100.00 debits reconcile precisely; the next dispatch at zero credit is rejected with 402 and remains QUOTED. |
| Tracking outbox | **PASS** — three clearly controlled tracking handoffs staged in the real database; no messages or store mutations sent. Existing Shopify delivery/reconciliation tests continue to pass. |
| PDF generation | **PASS** — preserved 4×6 carrier-label page, separate A4 invoice, exact 24.70 declared value, escaped item text and reviewed signer; invoice page rendered and visually inspected. Unsafe/unapproved URLs, non-PDF input, unpaid labels and missing postal forms rejected. |
| Dispatcher UI | **PASS** — actual Chromium interactions with controlled workspace API responses: navigation, sync, packing/HS review, quote selection, logout cleanup; no page errors or horizontal overflow at 375/768/1366 pixels. This is not a real Supabase login test. |
| Existing UI/CSV workflows | **PASS** — enterprise owner/client navigation, contrast and exception actions; actual downloaded CSV upload and customs-review round trip; 65 preview HTTP paths verified by the CSV browser harness. |

All database test inserts, updates, tickets, reservations and staged tracking
events were rolled back. Existing seed data and wallet balances were preserved.
No Stripe, Twilio, HubSpot or carrier purchases were exercised. No new tables
or migrations were required: existing schema through migration 016 supports
the workflow. No SQL needs to be run for this change.

## Activation requirements still outstanding

The complete **live** purchase/print/store-update journey is not certified as
passed. The configured environment remains a sandbox, seeded carrier accounts
are inactive, and real storefront/carrier purchase credentials were not used.

- Configure active tenant carrier accounts and verified regional purchase
  adapters. Sendcloud currently supports configured rating, not native label
  purchase. Freight tariffs and coverage must come from the carrier contract.
- For Shopify polling, configure the existing server-only `ECOMMERCE_CONNECTORS`
  entry with matching tenant/store IDs, a scoped access token, canonical shop
  hostname, `live_import: true`, and verified `sku_unit_grams`. This does not
  enable purchases or tracking mutations. Set `live_delivery: true` separately
  only when fulfillment permissions and the store's allocation rules are ready.
  Existing Shopify outbound support is whole-order/single-location; split
  allocations, WooCommerce outbound and Amazon SP-API still require adapters.
- Keep goods values and pricing currencies accurate. The existing EasyPost
  customs integration requires USD declarations; it does not silently convert
  GBP/EUR goods values. Unsupported lanes/providers are not fabricated.
- Configure `CARRIER_PDF_HOSTS` as a JSON array of exact trusted public HTTPS
  carrier/storage hostnames. Default `[]` denies remote downloads. Redirects,
  credentials in URLs, unexpected formats and oversized PDFs are rejected.
  Carrier forms must be printable PDFs; interactive forms require an upstream
  flattened print version. PDF downloads are limited to 100 selected bookings,
  5 MB per carrier document, 50 MB combined inputs and 1,000 pages.
- Only a deliberately configured live environment, non-sandbox tenant and
  `AUTOMATION_PURCHASE_ENABLED` can buy labels. Do not enable these merely to
  turn a sandbox test green. Browser download/printing is supported; physical
  printer delivery and paper output have not been verified.

The polling query uses the [Shopify orders API](https://shopify.dev/docs/api/admin-graphql/latest/queries/orders).
EasyPost shipment creation now requests PDF using its documented
[shipment options](https://docs.easypost.com/docs/shipments/options).

## Repeatable checks

Use the project's virtual environment and set `PYTHONPATH` to the project root
plus its `tests` directory for the standalone probe scripts.

- `python -m unittest tests.test_dispatch_workspace -q`
- `python tests/test_dispatcher_browser.py`
- `python tests/test_enterprise_browser.py` (configured backend running)
- `python tests/test_csv_browser.py` (isolated preview server)
- `python tests/dispatcher_database_probe.py` (sandbox; final rollback)
- `python tests/dispatcher_wallet_lock_probe.py` (sandbox; no balance changes)
- `python tests/uat_finance_capture_probe.py` (sandbox; controlled receipts and final rollback)

Local receipts: `database_evidence.json`, `wallet_lock_evidence.json` and
`docs/uat_100/finance_capture_evidence.json`. Environment-specific receipts are
excluded from Git. The synthetic print sample is available locally at
`output/pdf/dispatcher-journey-test.pdf`; its carrier label is explicitly
controlled test content, not a purchased shipping label.
