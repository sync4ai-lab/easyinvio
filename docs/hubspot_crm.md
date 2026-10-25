# HubSpot CRM integration

The client uses `https://api.hubapi.com` with CRM v3 company, contact, optional deal and association paths. The configured Supabase CRM queue/link tables and canonical mapping columns have been verified. Service-key authentication has been checked separately. Deployment still requires the matching environment, CRM properties and migration 018; no synchronization is enabled automatically.

## Activation

For a new deployment, apply `migrations/010_hubspot_crm.sql` after 009. Apply `migrations/018_hubspot_activation_and_metrics.sql` after 017 for this extension. It adds private job/mapping tables and database triggers for tenant creation/profile changes and confirmed shipment updates. Jobs remain pending until enabled. Existing tenants can be queued using the endpoint below.

In the selected account, create a Service Key (or use an existing private-app access token) with Companies/Contacts read and write access, property-schema read access and account-details read access. Deal read/write, deal-schema read and pipeline access are needed only for optional upsells. Set these server-only `.env` values (the fields have been added locally with empty token/account slots):

```dotenv
HUBSPOT_ENABLED=false
HUBSPOT_ACCESS_TOKEN=YOUR_RAW_SERVICE_KEY
HUBSPOT_EXPECTED_PORTAL_ID=YOUR_NUMERIC_SANDBOX_ACCOUNT_ID
HUBSPOT_ENVIRONMENT=SANDBOX
HUBSPOT_UPSELL_ENABLED=false
HUBSPOT_UPSELL_PIPELINE_ID=YOUR_PIPELINE_INTERNAL_ID
HUBSPOT_UPSELL_STAGE_ID=YOUR_HIGH_VOLUME_UPSELL_STAGE_INTERNAL_ID
```

`pat-...` is an accepted private-app credential, not a test-mode switch. The token writes to its issuing account. Never put it in frontend configuration. The client also accepts OAuth bearer tokens, but token refresh/rotation is managed externally. HubSpot remains disabled by default, including local preview.

Paste only the raw token, without `Bearer `, and the numeric HubSpot account ID.
Account ID comes from the developer **test account**, not its parent developer
portal. Before writes, the client checks `/account-info/v3/details` against the
expected ID. SANDBOX mode additionally requires HubSpot account type SANDBOX or
DEVELOPER_TEST and only processes sandbox tenant jobs. PRODUCTION must be selected
deliberately for production tenants. This blocks accidentally sending production
customer profiles to a test account.

Run the read-only preflight from the project root:

```powershell
.\.venv\Scripts\python.exe -m backend.check_hubspot
```

It validates account identity, required schema and company/contact read access.
It prints no token, customer names/emails or remote response bodies, performs no
record writes and does not activate the worker. Exit code 2 means not ready.
Write permissions must still be confirmed in the private app's scope settings.
Only after a successful preflight set `HUBSPOT_ENABLED=true` and restart the backend.

Create the following custom properties in HubSpot before enabling sync:

| Object | Internal property name | Type / field type | Unique |
|---|---|---|---|
| Company | `veloce_tenant_id` | string / text | Yes |
| Company | `veloce_vat_number` | string / text | No |
| Company | `veloce_package_count` | number / number | No |
| Company | `veloce_total_shipments` | number / number | No |
| Company | `veloce_wallet_balance` | number / number | No |
| Company | `veloce_total_spend` | number / number | No |
| Company | `veloce_currency` | string / text | No |
| Deal | `veloce_milestone_id` | string / text | Yes |

The seven company properties are required. The deal property and pipeline/stage
IDs are optional while `HUBSPOT_UPSELL_ENABLED=false`; provisioning Sales Hub or
Operations Hub does not create EasyInvio's custom properties automatically. Complete
creation payloads are in `config/hubspot_properties.json`. The worker checks types,
writability and unique tenant identity rather than silently changing CRM schema.

For unique properties, use the properties API with `hasUniqueValue: true`. Example `POST https://api.hubapi.com/crm/v3/properties/companies`, with Authorization Bearer token:

```json
{
  "groupName": "companyinformation",
  "name": "veloce_tenant_id",
  "label": "EasyInvio Tenant ID",
  "type": "string",
  "fieldType": "text",
  "hasUniqueValue": true
}
```

Use `dealinformation` for the deal property, and omit `hasUniqueValue` for the nonunique properties. These are account setup changes; the worker verifies definitions rather than silently modifying the CRM schema. Retrieve pipeline/stage IDs using `GET /crm/v3/pipelines/deals`, or copy the internal IDs from HubSpot settings. A display label such as High-Volume Upsell is not a stage ID. The worker checks the selected stage belongs to the selected pipeline.

Restart the configured backend after changing `.env`. Send `POST /api/v1/crm/sync-tenant` with your tenant OWNER/ADMIN JWT and this JSON body:

```json
{"tenant_id": "YOUR_TENANT_UUID"}
```

It returns HTTP 202 and QUEUED; it does not claim remote completion. Company name, canonical billing email and VAT registration come from stored tenant columns, with legacy company-profile fallbacks. Stored billing address maps to company street/city/zip/country. Contacts map by exact billing email; company display names never identify a tenant. Another tenant's UUID is forbidden. To see delivery or repair a blocked job, inspect the server-owned `hubspot_sync_jobs` and `hubspot_tenant_links` tables. A successful job is removed and the company/deal IDs and sync timestamp are retained. Resubmitting resets attempts and unblocks the job after configuration has been corrected.

## Behavior and reliability

The background worker creates or updates a company using its unique EasyInvio tenant UUID, creates/updates a contact by email, and calls `/crm/v3/associations/contacts/companies/batch/create`. Equal company display names never merge tenants. HubSpot contacts are email identities: the same email may legitimately be associated with multiple companies.

On confirmed shipment events, the worker recomputes package count using `sum(parcel_count)` and exact customer spend from tenant-scoped rows. With upsells enabled, count 50 does not create a deal; count 51 or more creates one deal in the configured stage and associates it with the company. A unique milestone property prevents duplicate deals after retries and ambiguous create timeouts. No speculative deal amount is assigned. Mixed-currency totals are blocked rather than summing unlike currencies. Counts/spend exclude failed bookings, pending imports and unbooked quotes. Totals are operational booked spend, not net accounting revenue.

Automatic enqueue happens in the same database transaction as the tenant/shipment change. CRM enqueue exceptions are caught so they cannot roll back a paid label; after such a database failure, use manual sync to reconstruct state. Remote HTTP never occurs in rating or label settlement. Durable jobs survive restarts. Tenant-specific session advisory locks serialize workers, revisions preserve events arriving during sync, and updates retain rate-limit retry deadlines. Use the application's existing direct/session-pool database connection configuration, not transaction pooling for session advisory locks.

429 and safe-to-repeat requests use bounded backoff and respect Retry-After. Long waits are deferred to the durable scheduler. A 5xx/transport failure during record creation is not blindly retried inline; the durable job recovers through unique identities. Authentication, account and property configuration errors block the job; transient jobs block after twelve attempts. Failure codes contain no token, email or remote response body. Search indexing can delay conflict recovery, so 409 retains the job for a later attempt.

Deployment preparation checks: **15 HubSpot tests passed**, covering company/contact
mapping without deal configuration, account mismatch/type fencing, schema mismatch,
secret redaction, ambiguous create handling, associations, retries and job revisions.
These use controlled HTTP responses; real token authentication and remote writes
remain unverified until the empty local fields are completed.

The exported async utilities preserve the requested signatures:

```python
await sync_tenant_to_hubspot(tenant_id, company_name, email, vat_number)
await log_shipping_activity(company_name, package_count, total_spend)
```

They validate stored tenant data and queue background work. Shipping activity rejects ambiguous company names and caller totals that differ from confirmed database values. They are trusted backend utilities, not public unauthenticated endpoints.

## Verification

Run `.venv/Scripts/python.exe -m unittest discover -s tests`. HubSpot tests use httpx MockTransport, exercise the complete outbound wire payloads and verify company isolation, replay, count 50/51, exact spend, rate limits, authentication failures and endpoint authorization. No real CRM records are created by tests. The SQL migration still requires validation against your deployed Supabase base schema.

References: [Companies](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/companies/guide), [Deals](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/deals/guide), [Custom and unique properties](https://developers.hubspot.com/docs/api-reference/legacy/crm/properties/guide), [API usage limits](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines), [Private apps](https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview).


## Lifecycle, metrics and inbound activation extension

`sync_new_tenant_to_crm(tenant_id, company_name, email)` validates inputs against
Supabase, queues durable work and attempts it in an async background context.
`sync_tenant_metrics_to_crm(tenant_id)` queues and processes canonical data. Bulk
fulfillment schedules this through FastAPI BackgroundTasks after confirmed
booking; database triggers also retain work across process crashes, profile
updates and wallet changes. Failed CRM operations never roll back label purchases.
Only confirmed shipments count toward lifetime parcel volume and spend. Quotes,
failed orders and unconfirmed purchases are excluded. Values use Decimal and
currency mismatch blocks synchronization instead of inventing conversion rates.

Onboarding upserts by the unique tenant UUID, creates/updates the email contact
and associates it. Successful association saves both IDs and the portal ID in
`tenants.company_profile.hubspot`, and retains a server-owned mapping in
`hubspot_tenant_links`. The admin-only Client Accounts Hub displays a safe
`https://app.hubspot.com/contacts/{portal}/record/0-2/{company}` timeline link;
unsynchronized clients show that state explicitly. Client roles do not receive
these fields through the admin API. Browser database updates cannot forge CRM references.

### Credentials and actual account type

Keep the current Service Key in HUBSPOT_ACCESS_TOKEN. Personal Access Keys are
for the CLI; Developer API Keys do not authenticate this CRM data sync. The
verified account reports STANDARD: use HUBSPOT_ENVIRONMENT=PRODUCTION if that is
your intended CRM. This describes account type, not subscription price. SANDBOX
requires a real SANDBOX/DEVELOPER_TEST account and only syncs sandbox tenants;
PRODUCTION only syncs non-sandbox tenants. Do not mix synthetic fixture tenants
with a production CRM. Existing records do not get activated or funded by this change.

### Inbound webhook setup

Service keys do not create HubSpot webhook subscriptions. Configure a
project-based HubSpot app's deal property-change subscription separately,
including deal/company/contact read access, and supply its **client secret**
for signature verification. It is different from the Service Key. The inbound
endpoint uses HubSpot v3 HMAC-SHA256 signatures over the exact request body,
public HTTPS URL and timestamp, constant-time comparison and a five-minute time
window. Unsigned requests and legacy v1/v2 signatures are rejected; there is no
shared-secret-header bypass. This matches
[HubSpot's current signature documentation](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/request-validation).
[HubSpot's Service Key guide](https://developers.hubspot.com/blog/hubspot-service-keys-the-right-api-credential-for-data-integrations)
explains the separate subscription requirement.

```dotenv
HUBSPOT_PROVISIONING_ENABLED=false
HUBSPOT_WEBHOOK_CLIENT_SECRET=
HUBSPOT_WEBHOOK_APP_ID=
HUBSPOT_WEBHOOK_URL=https://YOUR_PUBLIC_HOST/api/v1/integrations/hubspot-webhook
HUBSPOT_CLOSED_WON_STAGE_IDS=["closedwon"]
```

Use actual internal stage IDs, not the displayed CLOSED_WON label. The worker
re-fetches the deal and requires hs_is_closed_won=true as well as the configured
stage. It requires exactly one associated company and contact, an existing
contact-company association, a valid email/contact name and full company street,
city, postal code and country ISO. Missing/ambiguous data is blocked with a
sanitized diagnostic, not replaced with invented customer information.

Signed events are stored durably in hubspot_activation_jobs before returning
202. The worker rechecks the account and canonical associations, then uses a
company advisory lock and a transaction to create one active workspace and its
GBP prepaid wallet with exactly zero credits. Sandbox accounts produce sandbox
workspaces; STANDARD production mode produces non-sandbox workspaces. Duplicate
won deals for a linked company reuse its tenant without resetting its wallet.
No password, Auth user, login invitation, Stripe payment or external message is
created. Assign an existing Supabase Auth owner through the normal owner-managed
membership workflow before the customer can log in. Supabase remains authoritative.

Events are deduplicated by portal/deal ID. Replays do not reset retry budgets.
A corrected blocked job can be retried by a trusted operator resetting its
blocked flag/attempts/next_attempt_at; never mutate completed jobs. This workflow
stores no raw webhook body or contact email in the activation queue.

### Validation

Run `python -m unittest tests.test_hubspot_crm tests.test_hubspot_activation -q`.
`python -m tests.hubspot_database_probe` validates migration/provisioning on the
configured SANDBOX database with controlled HubSpot responses, and **rolls back
the entire transaction**, including migration 018. It makes no real CRM writes.
Apply migration 018 separately for deployment. Provision the seven company
properties from config/hubspot_properties.json, then run the read-only
`python -m backend.check_hubspot`. Synchronization/provisioning stay disabled until
operator configuration is complete and the backend is restarted.


## Current integration review and free-account setup (25 October 2026)

The recent Platform Owner UI changes expose CRM state; they do not activate CRM synchronization. The live read-only review established that the saved credential identifies the expected STANDARD HubSpot account. Local sync was disabled and local account mode was SANDBOX. Companies, contacts, schema and pipeline reads returned HTTP 403/MISSING_SCOPES. This is a credential-permission problem, not evidence that the free edition cannot hold client records. After the operator saved the missing permissions, readiness passed and all seven required company properties were created successfully.

The local account mode has been corrected to PRODUCTION. The operator confirmed HUBSPOT_ENABLED=true and HUBSPOT_ENVIRONMENT=PRODUCTION in Vercel and the worker environment; the local flags now match. Normal client-data export and deployment are pending explicit confirmation after automatic approval review separated synthetic testing from real-client sync. In this integration PRODUCTION means a STANDARD HubSpot account and non-sandbox EasyInvio client data; it does not switch shipping providers to LIVE. SANDBOX requires an actual HubSpot SANDBOX/DEVELOPER_TEST account and processes only sandbox client data. Do not remove these environment checks or export seeded UAT companies to the ordinary business CRM.

In HubSpot, open Settings → Integrations → Service Keys, or Development → Keys → Service Keys. Select the EasyInvio key and add object read/write scopes for companies and contacts, schema read scopes for companies and contacts, and retain working account-details read access. Creating the required company properties additionally requires crm.schemas.companies.write. Optional opportunity/deal work requires deal read/write and deal-schema read; optional milestone-property creation additionally requires deal-schema write. Legacy private apps have their own scope-editing screen. A Service Key does not provide webhook subscriptions: optional inbound Closed Won provisioning requires the supported signed app-webhook setup separately.

Keep the key server-side. If rotated, update HUBSPOT_ACCESS_TOKEN locally and in the deployed application/worker environments. Set HUBSPOT_ENVIRONMENT=PRODUCTION for the verified standard account in each deployed environment. Keep HUBSPOT_ENABLED=false until readiness and the isolated test pass. Then deliberately enable automatic sync and redeploy/restart the app and worker. Local .env changes do not change Vercel configuration.

Readiness and controlled tests from the project root:

```powershell
.\.venv\Scripts\python.exe -m backend.check_hubspot
.\.venv\Scripts\python.exe -m scripts.setup_hubspot_properties
# After reviewing the property plan and granting schema-write access:
.\.venv\Scripts\python.exe -m scripts.setup_hubspot_properties --apply
.\.venv\Scripts\python.exe -m scripts.hubspot_test_transactions --run --allow-standard-account
```

The property helper creates only missing matching EasyInvio definitions and refuses incompatible existing definitions. HubSpot enforces subscription/property quotas; the helper never removes another integration's properties or buys an upgrade. The test helper creates two clearly labelled [EASYINVIO TEST] companies and reserved-domain contacts, sends synthetic aggregate updates, and repeats upserts to verify stable IDs. These are CRM fixtures, not real shipping/payment transactions. It creates no Supabase shipments/wallet movements and starts no automatic worker. Deterministic fixture identities allow retry without duplicate companies. The standard-account flag explicitly permits these fixtures in the configured STANDARD account; account identity/schema checks still apply. Live fixture testing subsequently passed: two labelled companies and two associated contacts were created and read back successfully. Repeated upserts reused the company IDs. Each fixture reports 3 parcels, 2 distinct shipments, GBP 12.34 spend and GBP 50 wallet balance; these are synthetic CRM values only. Fixture company IDs in portal 149519962 are 456864863466 and 457056398548. The two queued non-sandbox business profiles passed stored-profile readiness checks but have not yet been exported by this test; normal client sync requires the separately requested confirmation. Five sandbox sync jobs remain outside the STANDARD account data boundary.

### What is implemented

- Company upsert keyed by the unique EasyInvio tenant UUID; contact upsert keyed by billing email; contact/company association.
- Stored company address and VAT data, with canonical billing email. Stored contact name and international phone now enrich standard contact fields when present.
- Confirmed package count, distinct shipment count, cumulative shipping spend, currency and current wallet balance. Multi-parcel shipments previously inflated the total-shipment property; it now uses shipment count while package count remains separate.
- Database queues triggered by relevant account, shipment and wallet changes; bounded retries, permanent-error blocking and mapping IDs/timestamps. A manual request can requeue work after configuration repair.
- Optional one-time high-volume upsell deal above 50 packages, disabled until pipeline/stage/property configuration is verified.
- Optional signed Closed Won webhook onboarding that creates a mapped EasyInvio workspace/zero-balance wallet when valid company/contact data is available. This is disabled by default and does not provision or email an Auth user automatically.
- Separate lead-discovery tooling writes reviewed lead candidates and unsent drafts; it does not currently import these automatically into HubSpot.

### Business role and next enhancements

Supabase remains the operational and financial source for orders, labels, tracking, payments, wallet ledgers, returns and support. HubSpot is the sales and relationship workspace: prospects, people, companies, opportunities, follow-up tasks and a concise account-health summary.

On the free edition, start with Contacts and Companies lifecycle/lead-status fields, associated Deals and the existing sales pipeline. A practical proposed deal process is Qualified → Discovery → Trial → Proposal → Closed Won or Closed Lost; changing the stage labels is an administrator choice and not performed by this sync. A newly registered account and a won opportunity are different business events. Routine customer signups do not currently create acquisition deals automatically. The optional high-volume upsell is not a general sales pipeline.

Recommended next work is to map business lifecycle explicitly (prospect, trial, paying customer, dormant), sync the primary client contact and owner, expose selected account-health totals with a link back to EasyInvio, and add deduplicated summary notes/tasks for first paid shipment, inactivity and open support. Keep parcel recipients and individual shipping/financial events in Supabase. Current sync updates company properties and links; it does not create a shipment-by-shipment CRM activity timeline.

HubSpot's current free-tools catalog lists ten total custom properties and up to two free users. The present mapping uses seven company properties and optionally one deal property. Prefer built-in lifecycle, contact, company, deal and task fields before spending the remaining custom-property allowance. The separate Leads object/Sales Workspace lead-management functionality requires Sales Hub Professional/Enterprise; free-plan prospect tracking can use contact lifecycle/lead status and deals. Richer custom reporting/automation may require paid subscriptions, but missing CRM scopes will not be fixed by buying an upgrade alone.

Primary references checked: https://developers.hubspot.com/changelog/service-keys ; https://developers.hubspot.com/blog/hubspot-service-keys-the-right-api-credential-for-data-integrations ; https://legal.hubspot.com/hubspot-product-and-services-catalog/free-tools ; https://knowledge.hubspot.com/records/use-lifecycle-stages ; https://knowledge.hubspot.com/records/create-leads .
