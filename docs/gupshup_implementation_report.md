# Gupshup implementation and verification record

27 October 2026 ? original checkout, branch `feat/gupshup-controlled-messaging`, starting commit `eedb7d8`.

Local source, migration, documentation and allowlisted worker artifacts are prepared. Private `.env` was not changed. No push, deployment, hosted database mutation, provider account/number migration, test message or billable provider call was performed. Unrelated starting modifications were preserved and excluded from the task commit.

## Implemented

- Self-service v2 Gupshup text, approved utility template and private document/image transport. Existing Twilio SDK/REST compatibility paths remain behind the provider boundary.
- Encrypted durable ingress, provider/app-scoped opaque IDs, identity/content conflict rejection, existing per-thread ordering and commit-before-send fences. Gupshup HTTP acknowledgement never invokes AI, a carrier or checkout.
- Both supported configured-header authentication (confirmed in the supplied self-service dashboard) and optional confirmed-source-IP modes. Duplicate/missing/wrong headers fail; no fabricated provider signature algorithm.
- Chat/signup, opted-in support, sender milestone and return notices select the configured transport. One UAT phone allowlist and outbound pause apply across paths and fallback. Proactive paths require approved logical templates.
- New migration 049 preserves existing Twilio records, scopes external IDs, adds private attempt/event tables, and leaves unknown financial cost NULL/UNKNOWN. Existing pending proactive rows remain Twilio-bound; no automatic provider transfer or uncertain failover.
- Receipt persistence before matching, WhatsApp/Gupshup aliases, monotonic delivery states, race reconciliation, deduplicated media fallback and original-provider callback support during rollback.
- Existing auth, merchant binding/roles, restricted public tracking capabilities, onboarding proofs, signed authenticated checkout, email and financial services remain in charge of business actions. Carrier/payment TEST modes remain independent of real message transport.

## Tests and checks

All tests use mock/synthetic providers and explicitly disposable local PGlite PostgreSQL. No hosted schema or live handset/provider acceptance is certified.

**Before changes:**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_whatsapp_queue.py tests/test_whatsapp_bot.py tests/test_whatsapp_ingress.py tests/test_whatsapp_onboarding.py tests/test_sender_notifications.py tests/test_email_delivery.py tests/test_runtime_hosting.py tests/test_conversational_gateway.py tests/test_headless_returns.py tests/test_identity.py tests/test_payment_gateway.py -q --basetemp <fresh-local-test-directory>
```

203 passed, 9 skipped, 3 subtests passed, 1 failed. The nine skipped cases needed the explicit disposable PostgreSQL dependency, not production credentials.

**Expanded regression run:**

Use a fresh local TEMP/TMP directory and `--basetemp` for each run. For PostgreSQL tests, this machine used the existing local package with:

```powershell
$env:PGLITE_TEST_MODULE='C:\Projects\easyinvio\tmp\tracking045-pglite\package\dist\index.js'
```

This is a local optional test dependency, not a database connection string. The repository's bridge starts an in-memory database without a server socket. A fresh checkout needs the PGlite test prerequisite installed separately. Missing base production DDL was not reconstructed or applied to Supabase.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_gupshup_provider.py tests/test_gupshup_postgres.py tests/test_whatsapp_queue.py tests/test_whatsapp_bot.py tests/test_whatsapp_ingress.py tests/test_whatsapp_onboarding.py tests/test_sender_notifications.py tests/test_return_review_postgres.py tests/test_email_delivery.py tests/test_runtime_hosting.py tests/test_conversational_gateway.py tests/test_headless_returns.py tests/test_identity.py tests/test_payment_gateway.py tests/test_payment_recovery.py tests/test_stripe_snapshots.py tests/test_stripe_listener_setup.py tests/test_tracking_workspace.py tests/test_tracking_workspace_postgres.py tests/test_tracking_and_support.py tests/test_support_monitoring.py tests/test_xcover_protection.py tests/test_xclaim.py tests/test_card_web_pool.py tests/test_quote_integrity.py tests/test_quote_support.py tests/test_automation_freight.py -q --basetemp <fresh-local-test-directory> --junitxml <local-results.xml>
```

**352 passed, 0 skipped, 3 subtests passed, 1 failed**, 154.51 seconds. The remaining failure is the same baseline case:

`tests/test_headless_returns.py::test_foreign_tenant_store_and_financial_role_denied_before_purchase`, line 197. Its DISPATCHER CUSTOMER_PAY case expects HTTP 403; current implementation proceeds to the original-delivery guard and returns 409. No financial role policy or test assertion was weakened to hide this. Resolve the policy/test mismatch separately before live financial operation.

Final changes were also verified with focused runs:

- `pytest tests/test_whatsapp_bot.py tests/test_whatsapp_ingress.py tests/test_runtime_hosting.py -q --basetemp <fresh-local-test-directory>`: **45 passed** after provider-independent quote test labels.
- With the PGlite dependency: `pytest tests/test_gupshup_provider.py tests/test_gupshup_postgres.py tests/test_runtime_hosting.py -q --basetemp <fresh-local-test-directory>`: **50 passed** after opaque WhatsApp receipt-ID support, including migration/real-SQL queues and all three proactive workers.
- `pytest tests/test_gupshup_provider.py -q --basetemp <fresh-local-test-directory>`: **24 passed** after the optional business-source callback check.
- `pytest tests/test_support_monitoring.py tests/test_gupshup_provider.py -q --basetemp <fresh-local-test-directory>`: **27 passed** on final source after provider-specific support diagnostics.

Production modules passed syntax compilation. `git diff --check` passed. The actual worker build commands both passed on final source:

```powershell
.venv\Scripts\python.exe scripts/build_vercel.py --bundle
.venv\Scripts\python.exe scripts/build_vercel.py
```

22 public assets and 132 allowlisted worker source files. Private `.env` and private keys are excluded. A private-value scan against local secret settings found no matches in task text files or the worker archive; values were not printed. `.env.example` has no duplicate variable names and contains placeholders for secrets/tester data.

## Limitations and required manual work

See [gupshup_deployment.md](gupshup_deployment.md) for precise steps for the actual Add Webhook screen, variables, migration prerequisites, verified bindings, templates, phased acceptance and rollback.

The account/app and API-key creation are confirmed by screenshots. The correct App ID comes from Settings, not Namespace. The app is currently Sandbox. The local `.env` does not yet contain Gupshup settings. Activation remains disabled by default and the common pause defaults true. Hosted migration, app/source credentials, header secret, tester access, proactive template approval, binding re-verification, matching web/daemon deployment and paid/manual handset acceptance remain outstanding.

The supplied dashboard announces API-key deprecation on 31 March 2027. Current apikey transport is implemented; automated Customer Access/App Token renewal and bearer APIs require a separate verified migration before that deadline. Existing API keys are not silently treated as short-lived tokens.

No new agent inbox, recipient identity system, automatic refund authority, tenant budget enforcement or reconciled billing engine was introduced. No BSUID-only identity support. Delivery may be uncertain; there is no exactly-once promise. Restore configuration on this dual-provider build for rollback; do not assume a shared Twilio sandbox can serve as the new owned number.

## Exact task files

- `.env.example`
- `main.py`
- `backend/whatsapp_provider.py`
- `backend/whatsapp_dispatch.py`
- `backend/gupshup_ingress.py`
- `backend/whatsapp_queue.py`
- `backend/whatsapp_bot.py`
- `backend/whatsapp_onboarding.py`
- `backend/support_delivery.py`
- `backend/shipment_notifications.py`
- `backend/return_delivery.py`
- `backend/check_whatsapp.py`
- `backend/sandbox_hooks.py`
- `backend/support_alert_controls.py`
- `backend/tracking_workspace.py`
- `backend/agents/conversational_gateway.py`
- `backend/test_supabase_transaction.py`
- `backend/seed_rigorous_data.py`
- `migrations/049_whatsapp_providers.sql`
- `docs/gupshup_deployment.md`
- `tests/test_gupshup_provider.py`
- `tests/test_gupshup_postgres.py`
- `tests/pglite_tracking_bridge.cjs`
- `tests/test_runtime_hosting.py`
- `tests/test_sender_notifications.py`
- `tests/test_return_review_postgres.py`
- `tests/test_tracking_workspace.py`
- `tests/test_whatsapp_onboarding.py`
- `deployment/worker/runtime.tar.gz`
- `deployment/worker/source_manifest.json`
- `docs/gupshup_implementation_report.md` (this record)
