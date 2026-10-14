# Running the repaired master UAT matrix

The master suite now enters FastAPI lifespan explicitly, restores the original authentication overrides and app state after every HTTP test, and uses synthetic tenant identities instead of an existing company account. The default suite executes the real rating, calibrated pricing, booking lifecycle, FinanceEngine and deterministic ingestion code with controlled database/provider IO. It requires no seed data, real API credentials, database connection or model tokens.

## Default API and component checks

From the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_easyinvio_complete_matrix.py -v -p no:cacheprovider
```

To retain machine-readable evidence without overwriting the earlier user-supplied log:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_easyinvio_complete_matrix.py -v -p no:cacheprovider --junitxml=output/uat_master_matrix.xml
```

The suite contains 281 collected executions: the original seven calculator cases repeated 36 times, plus 28 additional executions and one opt-in configured-startup smoke check. Repetition is reported separately from distinct coverage. Expected default result: 280 passes and one skip. This is API/component verification, not 280 unique end-to-end scenarios or a load test.

Verification on 14 October 2026: the complete repository run, including this repaired matrix, finished with **763 passed, one skipped and 14 subtests passed in 59.17 seconds**. The skip was the configured-startup smoke check. The existing `TestTopupInput` Pydantic class produced one pytest collection warning because its name starts with `Test`; it did not fail the run. Command: `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`. The configured real database/worker smoke mode was not executed during this verification.

The HTTP fixture enters the application's actual outer lifespan, including supervisor creation and shutdown. It replaces only the database/provider service startup context with managed synthetic services. `RatingService`, `NativePartnerService`, `PartnerLifecycleService`, `FinanceEngine` and the margin calculation execute production code; the fixture does not start global database workers. The in-memory SQL boundary rejects unimplemented queries, verifies tenant bindings, models financial transactions and lock contention, and closes at teardown. It cannot certify PostgreSQL RLS, real row locks, database constraints or external carrier behavior.

The checked flows include:

- Exact premium strings, rounding thresholds, input rejection and unavailable-protection disclosures.
- Three synthetic provider pipelines, twelve duplicate tiers each, deterministic highest-profit selection, customer-price sorting, ten-offer cap and fewer-than-ten results.
- Public removal of aggregator/account/upstream identifiers while private quote snapshots retain booking references.
- Direct tenant-query validation, HTTP 403 before data access, and context-bound native-order queries excluding a foreign sentinel row. JWT verification is explicitly replaced by fixture authentication; the production query guard still runs.
- Two concurrent HTTP booking requests for the same prepared offer. The offer's stored shipment idempotency key drives the existing production advisory lock. One request finishes; the overlapping request returns 409. Exactly one provider boundary call and one reserve/capture pair occur, leaving GBP 88.00 from GBP 100.00 and no reserved balance.
- An additional completed-booking retry returns the existing successful result with `replayed=true`, with no second purchase or debit. This preserves the current API's idempotent retry contract; a completed retry is not required to return 409.
- Volumetric weight through both the weight endpoint and rate response: 50 x 40 x 30 cm / 5000 = 12.000 kg, exceeding the actual 1.500 kg.
- Comma decimals through `/api/v1/agents/interpret` with AI disabled, including `4,5kg from GB to US`. The anchored parser accepts either decimal separator, an optional `Quote` prefix, and the existing ISO country/route format. Mixed separators, multiple separators, invalid countries and out-of-range values remain rejected.

No new endpoint or financial schema is introduced. The booking endpoint receives `tenant_id` and `offer_id`; it reads the authoritative idempotency key from the prepared shipment, not a new client-supplied header.

## Optional configured-startup smoke test

This separate mode executes the unmodified configured application lifespan: real database pools, configured registries and background workers start and stop. It requires a dedicated UAT database with all migrations applied, `DATABASE_ENVIRONMENT=SANDBOX`, `PROVIDER_ENVIRONMENT=TEST`, and live Stripe mode disabled. Starting workers can process existing queued sandbox jobs. Do not point this mode at a shared customer or production database.

Create a dedicated active sandbox tenant and active dispatch-authorized membership through the application's supported onboarding/fixture process. The membership identifier below is `auth.users.id`, matching `public.users.auth_user_id`. The existing Mavuri tenant is explicitly rejected. No arbitrary user/tenant foreign keys or fake encrypted carrier credentials are seeded by this suite.

Set these variables in the terminal that runs the test, using the IDs from those actual sandbox records:

```powershell
$env:EASYINVIO_UAT_LIVE_LIFESPAN = '1'
$env:EASYINVIO_UAT_TENANT_ID = '<dedicated-sandbox-tenant-uuid>'
$env:EASYINVIO_UAT_AUTH_USER_ID = '<sandbox-auth-user-uuid>'
.\.venv\Scripts\python.exe -m pytest tests/test_easyinvio_complete_matrix.py -k configured_lifespan_mounts_native_services -v -p no:cacheprovider
```

The fixture validates environment and membership before entering startup. It then checks mounted services, configured health and native-order retrieval. Authentication uses an explicitly scoped test context; this smoke check does not verify JWT issuance or renewal. It does not purchase a label, reset a wallet or claim provider integration acceptance. All startup-owned workers and pools use the application's existing teardown. Clear the opt-in after the run:

```powershell
Remove-Item Env:EASYINVIO_UAT_LIVE_LIFESPAN -ErrorAction SilentlyContinue
Remove-Item Env:EASYINVIO_UAT_TENANT_ID -ErrorAction SilentlyContinue
Remove-Item Env:EASYINVIO_UAT_AUTH_USER_ID -ErrorAction SilentlyContinue
```

The [revision 3 audit](uat_master_suite_audit_2026-10-14_revision_3.md) remains historical evidence for the earlier failed run. Passing the repaired component matrix does not retrospectively change it or grant full application UAT approval. Real sandbox provider acceptance, database financial reconciliation, authenticated tenant/RLS verification and defined load targets remain separate release gates.
