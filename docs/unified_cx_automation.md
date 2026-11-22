# Unified customer experience automation

This upgrade shares policy, claims, tracking and plan services between the web portal and WhatsApp. It is implemented on the feature branch. Migration 056 is prepared and tested on a disposable PostgreSQL engine; it has **not** been applied to the shared Supabase database. No provider registrations, labels, messages, payments or deployments were made during implementation.

## What changes

| Feature | Behaviour | Records to inspect |
|---|---|---|
| Public tracking | New workspaces permit status-only reference lookup. Existing opt-outs remain unchanged; owners can change the choice in Settings. No names, addresses, document links or recipient details appear. | `tenants.public_status_lookup_enabled`, `tracking_events` |
| Plans | Starter, Velocity and Command checks always apply, including grandfathered workspaces. Sandbox remains complimentary but uses its selected plan. | `tenants.plan_code`, `plan_enforcement_enabled`, existing usage records |
| Return defaults | An active owner/admin causes a missing policy to be seeded: enabled, 14 days, customer pays, GB, GBP10 cap, delivered only, paperless preferred. Existing choices are preserved except caps above GBP50 are reduced. | `whatsapp_consumer_return_policies` |
| Policy copilot | Owner/admin drafts plain-English rules; structured bounds are checked, then an expiring proposal needs separate confirmation. A changed policy invalidates stale proposals. | `cx_policy_proposals` |
| Tracking setup | Active platform connectors enter a durable setup queue. Supported native registrations are reconciled before creation. Uncertain outcomes are held for review rather than blindly retried. | `connector_tracking_setup`, `partner_provider_options` |
| Tracking recovery | Nonterminal aggregator shipments without a scan for more than four hours are eligible for refresh. Only real provider scan data changes shipment status. | existing tracking refresh jobs, `tracking_events`, `cx_worker_heartbeats` |
| Delay support | No first scan after 48 hours, in-transit stall after 72 hours, or exception creates a deduplicated support incident. Existing open delay cases are reused. Opted-in support recipients use the existing outbox. | `cx_delay_incidents`, `support_tickets`, `support_message_outbox` |
| Claims | Fresh shipment ownership or an active capability is required. Missing description/value/damage photos are requested together. Private evidence and a structured dossier remain available when XCover is off. | `cx_claim_dossiers`, `cx_claim_evidence`, `support_tickets.claim_dossier` |

Tenant creation precedes the real owner account in existing onboarding. The safe return policy is therefore seeded when the first active owner/admin is attached, rather than inventing an authorizing user. Migration 056 also fills missing policies for existing eligible owners.

Photos are checked as actual JPEG/PNG images, not accepted as proof of damage or liability. An insured, complete merchant dossier can enter the existing `insurance_claim_cases` table as `CLAIM_INGESTED`; intake does not submit the claim, approve it or move money. Later dossier updates refresh only that unsubmitted state. Consumer cases remain available for merchant review even after their tracking capability expires.

## Enable locally in order

1. Review and apply `migrations/056_unified_cx_automation.sql` after migrations 050?055. It changes the shared database for every environment, including stricter plan enforcement. Do this deliberately before enabling the new paths.
2. In `.env.local`, set the following. Keep actual keys in your private file.

   ```dotenv
   CX_AUTOMATION_ENABLED=true
   TRACKING_POLLING_ENABLED=true
   SUBSCRIPTION_TIERS_ENABLED=true
   CX_DELAY_LLM_ENABLED=false
   TRACKING_WEBHOOK_BASE_URL=https://YOUR-ACTIVE-NGROK-DOMAIN
   WHATSAPP_EVIDENCE_ALLOWED_HOSTS=["filemanager.gupshup.io"]
   ```

   Use only the origin in `TRACKING_WEBHOOK_BASE_URL`; EasyInvio builds the callback path. `BOOKING_PAGE_URL` still controls booking links. An explicit `TRACKING_POLLING_ENABLED=false` in a private file overrides the new default. Setting the legacy subscription flag false no longer disables entitlement checks.
3. Pause hosted WhatsApp consumers and tracking/CX workers that use the same app, environment and shared queue. Keep one active testing consumer.
4. Stop your old local server, then run from the local-development folder:

   ```powershell
   .\.venv\Scripts\python.exe scripts/dev.py --whatsapp --cx-automation --hosted-whatsapp-paused --public-url https://YOUR-ACTIVE-NGROK-DOMAIN
   ```

   Keep ngrok and the server running. The ordinary `--whatsapp` command starts WhatsApp processing only; `--cx-automation` explicitly adds tracking refresh, connector setup, delay detection and support delivery. It does not start billing or store automation jobs.
5. Open the authenticated platform-owner health endpoint below and resolve its reported issues. Polling readiness uses a shared environment-specific worker heartbeat no older than 90 seconds.
6. For a later deliberate UAT deployment, configure the same flags in Preview with `TRACKING_WEBHOOK_BASE_URL=https://uat.easyinvio.com`. Hosted dedicated background jobs require the existing `ALL` job mode; do not run them alongside the local consumer. Deploying code alone does not change private environment values.

No Production merge, domain change or deployment is part of this upgrade. The existing private environment files have not been changed.

## Provider setup limits

- EasyPost and Shippo support native webhook creation/listing. The setup worker preserves existing configured callbacks and holds them for review instead of hijacking them. An interrupted or uncertain registration enters `REVIEW_REQUIRED`; inspect the provider dashboard before reconciling it. Do not delete its record and blindly repeat a POST.
- Sendcloud uses its documented dashboard callback setup. The worker prepares the receiver/signing configuration and reports `MANUAL_REQUIRED`. Set the exact callback displayed by owner health, including `?source=<connection UUID>`, in Sendcloud. A correctly authenticated native delivery marks it verified. LIVE Sendcloud v3 also requires the integration ID in existing provider options.
- Sendcloud TEST label purchases remain blocked. Verified non-billable TEST purchase contracts are EasyPost/Shippo only. An integration ID does not remove that restriction.
- Shippo refresh retrieves an existing purchased transaction and tracker; it does not create a billable tracker. Sendcloud refresh accepts an actual carrier scan and timestamp from its existing shipment resource. If unavailable in that response, the adapter rejects it as `TRACKING_CARRIER_SCAN_NOT_AVAILABLE_IN_RESOURCE` (the job is held as `UNSUPPORTED_OR_REJECTED`); native signed webhooks remain necessary. It never turns a label announcement into an in-transit scan.
- Royal Mail and Evri direct switches remain insufficient without the certified injected carrier contracts. Use supported aggregator services until those contracts are available.
- A configured key and heartbeat are pre-flight checks, not proof of a successful end-to-end carrier delivery. Test a signed callback and confirm the resulting `tracking_events` row.

Provider contracts: [EasyPost webhooks](https://docs.easypost.com/guides/webhooks-guide), [Shippo creation](https://docs.goshippo.com/tracking/creating-webhooks), [Shippo security](https://docs.goshippo.com/tracking/webhook-security), [Sendcloud dashboard setup](https://support.sendcloud.com/hc/en-gb/articles/12455997971220-What-are-webhooks-and-how-to-set-them-up-in-Sendcloud), [Gupshup media](https://docs.gupshup.io/docs/media).

## Web APIs and phone checks

All authenticated routes use the existing Bearer session; no access token belongs in a URL. Example IDs below are placeholders.

| Action | Route or exact WhatsApp message | Expected result |
|---|---|---|
| Public reference | Web `/track`, or POST `/api/v1/public/tracking/status` with `{"text":"YOURTRACKINGREF"}` | Status-only projection, opt-out and existing public rate budget preserved |
| Public choice | GET/PUT `/api/v1/settings/public-tracking`; PUT `{"enabled":false}` | Fresh owner/admin only; existing opt-out is not silently reset |
| Draft rules | `Set a 30-day free return policy for UK orders, maximum GBP 10` | Proposal summary; no policy saved yet |
| Confirm rules | `Confirm policy <proposal UUID>` | Actor-bound, version-checked, idempotent save |
| Web draft | POST `/api/v1/settings/return-policy/proposals` with `{"text":"Set a 30-day free return policy for UK orders, maximum GBP 10"}` | Same proposal as chat |
| Web confirm | POST `/api/v1/settings/return-policy/proposals/<UUID>/confirm` | Same guarded confirmation |
| Start claim | `Claim YOURREF damaged The box was crushed and the glass broke; GBP 25` | One scoped case; asks for missing photo |
| Update claim | `Claim update <dossier UUID> The item was broken inside crushed packaging; GBP 25` | Updates that authorized dossier |
| Photo | Send one JPEG/PNG up to 5 MB after opening a claim | Validated, private, hash-deduplicated attachment. Ambiguous recent cases use the secure form |
| Web claim | Shipments ? report lost/damaged parcel, or POST `/api/v1/agents/claims/intake` | Same dossier and financial guardrails; retries reuse request identity |
| Review | GET `/api/v1/agents/claims/<UUID>` and `/evidence/<evidence UUID>` | Fresh authorized merchant staff only; private downloads, no public evidence URLs |
| Health | GET `/api/v1/admin/connectors/health` | Platform-owner only, configuration gaps and worker readiness, no raw credentials |

A buyer first opens their secure tracking capability link and selects the parcel before claiming or requesting a return. Return booking retains delivered status, recipient verification, policy window, country, cost-cap and customer-payment checks. A policy proposal or photo does not grant purchase authority. Ordinary claims intake works without the optional model. Common policy commands are parsed without model tokens; other wording uses the bounded existing agent runtime when available. Delay explanations are deterministic by default, avoiding ongoing model spend.

## Three clean plan workspaces

Create three disposable test Auth users using Supabase Authentication. They must not belong to other workspaces. As platform owner, POST `/api/v1/admin/uat/plan-fixtures`:

```json
{"owner_auth_user_ids":["STARTER-USER-UUID","VELOCITY-USER-UUID","COMMAND-USER-UUID"],"reset":false}
```

The order is Starter, Velocity, Command. The utility creates fixed sandbox workspaces, enforced plans and zero-credit wallets; it does not create passwords, charge subscriptions or give free shipping money. Repeating without reset preserves plan versions. Reset refuses workspaces with shipment history and never deletes financial records. The endpoint requires both SANDBOX database mode and TEST providers. Use separate users to exercise plan gates in both the portal and bound WhatsApp sessions.

## Offline verification

No live database or provider is needed for unit tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_unified_cx.py tests/test_unified_cx_api.py -q
.\.venv\Scripts\python.exe scripts/check_connectors_offline.py
```

`tests/test_unified_cx_postgres.py` additionally runs the actual migration and service SQL against disposable PGlite when `PGLITE_TEST_MODULE` identifies its local `index.cjs`. It tests default/opt-out preservation, enforced plans, policy confirmation and stale versions, cross-user/capability rejection, claims/evidence idempotency, insurer intake without submission, incident deduplication and the three sandbox plans. It has no live database fallback.

`tests/unified_cx_browser.py` uses a mobile-sized Edge page and mocked HTTP responses to verify policy confirmation, publication choice, claim retry identity and session cleanup. Provider registration tests use synthetic HTTP responses. The offline self-test verifies guardrails, not actual provider availability.
