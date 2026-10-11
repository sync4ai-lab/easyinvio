# TC-032 and integration remediation

TC-032 is fixed in the shared authenticated tenant dependency and defended again at the manifest endpoint. A supplied `tenant_id` must be a single valid UUID equal to the verified session tenant. Foreign, malformed, empty and duplicate values return 403 before tenant repository reads. No tenant values or raw bearer data are echoed into security logs. Unauthenticated requests still return 401. Platform-admin cross-tenant endpoints retain their separate explicit owner authorization.

HubSpot HTTP 403 is a permanent, non-retryable configuration error with a safe warning. Existing durable CRM jobs retain its error code and blocked state; the optional background wrapper prevents this from halting logistics. `GET /api/v1/admin/integrations/alerts` gives authorized platform owners remediation summaries from those jobs. These are explicitly deterministic integration alerts, not fabricated shipment support tickets or remote AI output. No new database table or migration is needed.

The private `.env` now has `HUBSPOT_ENVIRONMENT=SANDBOX`. **The actual token still identifies a STANDARD account**, verified through the account-details API. Companies access still returns 403. Changing an environment label cannot convert that account into a developer test account or grant access, so `HUBSPOT_ENABLED` remains false pending verified configuration. This protects the real account from unintended test writes.

## HubSpot action required

Create/use a private app in a genuine developer test account. Grant:

- `crm.objects.companies.read` and `crm.objects.companies.write`
- `crm.objects.contacts.read` and `crm.objects.contacts.write`
- `crm.schemas.companies.read` and `crm.schemas.contacts.read` for the existing property validation
- Schema write permissions only if you also provision properties through APIs; deal permissions only if the optional upsell feature is enabled.

Save that app's token as `HUBSPOT_ACCESS_TOKEN` and its account ID as `HUBSPOT_EXPECTED_PORTAL_ID` locally. Keep `HUBSPOT_ENABLED=false` until the account, scopes and required properties verify. The worker expects the existing `veloce_*` custom properties documented in `docs/hubspot_crm.md`. Closed-won activation additionally needs its configured webhook app credentials and verified signature URL.

HubSpot reference: https://developers.hubspot.com/blog/generate-dummy-data-using-postman-with-hubspot-apis

## Stripe and Twilio

Both integrations are already enabled with genuine credentials. Stripe Checkout uses the actual official SDK, and the snapshot receiver verifies real raw webhook signatures before durable atomic reconciliation. Twilio uses the official validator and calls the real tenant-scoped parallel rating service. There are no `MockTransport` or canned-price providers in these deployed modules to remove; mocks are in isolated tests.

Account credentials authenticate successfully, but zero active TEST carrier accounts are configured. Add the EasyPost TEST credential via Super-Admin → Carrier Connectors → EasyPost → Set Up. The token remains server-encrypted and shared through the platform-owned connector model, never disclosed to tenants.

Signature verification, tenant matching, TEST/LIVE fences, Stripe idempotency and wallet locks remain intact. They protect real money and dispatches and are not mock constraints. Native sandbox label purchase remains an explicitly unsupported workflow; completing it needs a separate safe test-mode booking implementation, not removal of financial safety checks. Existing UAT cases requiring genuine card completion, WhatsApp delivery, carrier labels or marketplace pushback cannot honestly pass from credential validation alone.

The refreshed UAT report has 72 PASS, 0 FAIL, 88 PARTIAL and 40 BLOCKED. TC-032 returns 403 in the real running backend using a disposable password-verified user. Regression and owner-alert tests verify scope-error containment and permissions. No genuine provider payment, carrier purchase or phone delivery has been claimed for this remediation.
