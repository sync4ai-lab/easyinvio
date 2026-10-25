# HubSpot CRM integration

The client uses `https://api.hubapi.com` with CRM v3 company, contact, optional deal and association paths. Account authentication, the required seven company properties, remote company/contact writes and Supabase queue/link mappings have been verified. Sync is operator-enabled; optional upsell deals and signed Closed Won provisioning remain disabled. See the UAT acceptance workflow below for the supported tests and current limitations.

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

Initial preparation used controlled HTTP tests. The October 2026 live verification subsequently exercised actual company/contact creation, readback, stable identities and client-summary synchronization. These are separate from browser purchase testing and from the optional inbound webhook workflow.

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
PRODUCTION syncs non-sandbox tenants plus explicitly allowlisted UAT tenants; seeded fixtures are excluded. Do not mix synthetic fixture tenants
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

The local account mode has been corrected to PRODUCTION. The operator confirmed HUBSPOT_ENABLED=true and HUBSPOT_ENVIRONMENT=PRODUCTION in Vercel and the worker environment; the local flags now match. The operator subsequently explicitly approved normal client CRM synchronization and deployment. In this integration PRODUCTION means a STANDARD HubSpot account; non-sandbox EasyInvio client data and explicitly allowlisted UAT workspaces are eligible; it does not switch shipping providers to LIVE. SANDBOX requires an actual HubSpot SANDBOX/DEVELOPER_TEST account and processes only sandbox client data. Do not remove these environment checks or export seeded UAT companies to the ordinary business CRM.

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

The property helper creates only missing matching EasyInvio definitions and refuses incompatible existing definitions. HubSpot enforces subscription/property quotas; the helper never removes another integration's properties or buys an upgrade. The test helper creates two clearly labelled [EASYINVIO TEST] companies and reserved-domain contacts, sends synthetic aggregate updates, and repeats upserts to verify stable IDs. These are CRM fixtures, not real shipping/payment transactions. It creates no Supabase shipments/wallet movements and starts no automatic worker. Deterministic fixture identities allow retry without duplicate companies. The standard-account flag explicitly permits these fixtures in the configured STANDARD account; account identity/schema checks still apply. Live fixture testing subsequently passed: two labelled companies and two associated contacts were created and read back successfully. Repeated upserts reused the company IDs. Each fixture reports 3 parcels, 2 distinct shipments, GBP 12.34 spend and GBP 50 wallet balance; these are synthetic CRM values only. Fixture company IDs in portal 149519962 are 456864863466 and 457056398548. After explicit approval, Alpha Global Retail and Beta Electronics Hub synced successfully through the normal service; company/contact mappings were saved and both queue jobs completed. Their HubSpot company IDs are 456759539941 and 457076796644 respectively. The live account sync exposed a company street-address mapping error: HubSpot uses the built-in company property address, not street. Both outbound sync and optional inbound provisioning now use address, with regression fixtures corrected to match the real API. At that stage five sandbox jobs were excluded. The subsequent explicit UAT allowlist allows the selected Mavuri Consultancy workspace to sync without changing its sandbox flag.

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


## UAT acceptance workflow and blank-record diagnosis (25 October 2026)

### Two different meanings of environment

HUBSPOT_ENVIRONMENT checks the HubSpot account type, not whether the EasyInvio hostname contains uat. This account reports STANDARD, so keep HUBSPOT_ENVIRONMENT=PRODUCTION. EasyInvio workspace is_sandbox controls shipping/payment test behavior and must not be changed to enable CRM.

A STANDARD HubSpot account can receive explicitly selected sandbox workspaces:

```dotenv
HUBSPOT_ENABLED=true
HUBSPOT_ENVIRONMENT=PRODUCTION
HUBSPOT_UAT_TENANT_IDS=["b9f5260c-3f03-42d5-8753-84690af5f647"]
```

The user selected Mavuri Consultancy Services Limited only. Save the allowlist in the web application and worker environments and restart/redeploy with this code. The operator configured local .env and confirmed saving the same allowlist in Vercel before deployment. An empty list restores the default exclusion of sandbox workspaces. The allowlist is only valid in PRODUCTION HubSpot account mode. It is server configuration, not a permission a client can grant itself.

Allowed sandbox companies are named [UAT] followed by their stored company name. Canonical EasyInvio tenant UUIDs still identify them, and shipping/payment sandbox flags remain unchanged. Seeded profiles carrying fixture_batch are excluded even if explicitly listed. The ordinary worker queue and the direct sync processor enforce the same boundaries. UAT and production in one HubSpot account are not isolated databases: a shared billing email identifies the same contact, so use deliberate test identities and do not treat UAT metrics as live revenue. No extra custom property is required for this mode.

The selected UAT company was successfully created through the normal service and its queue completed: portal 149519962, company 456857630908, contact 901405242581. Live company readback and worker deployment/configuration should be checked separately; a manual successful service run does not prove that a separately deployed worker received its configuration.

### Why there are extra or blank companies

Read-only source metadata confirmed these records were created by HubSpot's own Create and associate companies with contacts setting, not by EasyInvio's company upsert:

- Company 456817406194: blank name, example.com domain; associated with the two deliberate CRM fixture contacts.
- Company 457015794891: blank name, betaelec.co.uk domain; associated with the Beta billing contact.
- Company 456830229739: Alpha Retail, alpharetail.co.uk domain; additional to the explicitly linked Alpha Global Retail company.
- The original HubSpot company also reports the same automatic setting as its source.

Disable automatic domain-based company creation at HubSpot Settings > Data Management > Objects > Companies > Automation > Create and associate companies with contacts. EasyInvio already creates explicit associations using unique workspace IDs. Turning the setting off does not remove existing records. For a clean integration view, filter companies where EasyInvio Tenant ID / veloce_tenant_id is known; then separately filter name starting [UAT] or [EASYINVIO TEST]. Review associations and history before archiving anything. No existing company/contact was deleted by this change. No owner and an empty phone column are unassigned/missing properties, not extra records; company phone and HubSpot salesperson ownership are not currently populated by this sync.

Reference: https://knowledge.hubspot.com/object-settings/automatically-create-and-associate-companies-with-contacts

### Tests the owner can perform in EasyInvio

Use the selected Mavuri Consultancy workspace, either as its client OWNER or through the platform's audited Assist a client function. A platform owner should not book under their own platform identity. Before each test, record the HubSpot company ID, current metric values and count of matching companies. In HubSpot add columns for the seven EasyInvio properties; the defaults such as Last activity date and Company owner do not show metric sync results.

| Action | Expected evidence | What does not happen |
|---|---|---|
| First sync of selected existing workspace | One [UAT] company, its billing contact association, address and seven summary fields; platform Client Accounts shows Linked / UAT test account and Open HubSpot account | No new shipment, payment or invitation is created |
| Speed Quote Matrix: request rates only | Company shipment/spend totals remain unchanged | A quote is not a booked shipment or sales deal |
| Buy one supported TEST label from the selected workspace | Shipping receipt/label succeeds; after background sync, distinct shipments increases by one, parcels increases by the shipment parcel count, booked spend increases by final client price, and wallet reflects the actual payment method | Card payments need not reduce wallet; pending/failed bookings do not count; no shipment-by-shipment HubSpot timeline note is created |
| Repeat the booking workflow with a second shipment | Same company ID; cumulative counts change again, without duplicate company/contact creation | Do not retry a successful paid booking just to test CRM retries |
| Wallet & Billing: complete an available TEST wallet top-up | HubSpot wallet balance matches the resulting Supabase wallet; shipment count and booked shipping spend do not increase | Merely opening/abandoning a top-up does not credit the wallet |
| Return to Platform Owner > Client Accounts > Refresh clients | Linked company opens the same HubSpot record; excluded seed clients remain Not enabled for CRM or Test fixture excluded | Refresh clients is a read, not a backfill/sync button |
| User Profile: edit a login user's full name/phone | Login profile changes only | This is not the workspace billing-contact profile; current sync does not mirror all login users |
| Settings: add a parcel recipient/address | Address book is updated in EasyInvio | End recipients are not automatically imported as sales contacts |

For healthy small queues allow approximately 5–30 seconds; this is not a guaranteed delivery SLA. Authentication/schema errors block jobs, throttling and temporary failures delay them. Refresh the HubSpot record and inspect EasyInvio Tenant ID and numeric fields; Last activity date is not proof that property updates failed. CRM failures must not invalidate paid labels.

A new signup queues a record, but a new sandbox workspace is excluded until its UUID is explicitly allowlisted for UAT; the current pilot setting does not auto-approve every new signup. A genuine non-sandbox production signup is eligible automatically. Historical accounts require queue/backfill; enabling the integration is not a blanket scan/import.

Read-only SQL evidence (Supabase SQL editor, trusted backend operator):

```sql
SELECT t.company_name, t.is_sandbox, l.portal_id, l.company_id, l.contact_id,
       l.last_synced_at, j.attempts, j.blocked, j.last_error, j.next_attempt_at
FROM public.tenants t
LEFT JOIN public.hubspot_tenant_links l USING (tenant_id)
LEFT JOIN public.hubspot_sync_jobs j USING (tenant_id)
WHERE t.tenant_id = 'b9f5260c-3f03-42d5-8753-84690af5f647'::uuid;
```

A mapped company with last_synced_at and no queue row means the latest completed job succeeded. A company ID alone does not prove future worker processing. Compare the timestamp/metrics after the next app booking. A trusted OWNER/ADMIN can explicitly request POST /api/v1/crm/sync-tenant with their own tenant_id; it returns QUEUED, not a guarantee of remote completion. This is an API, not an existing UI button.

### HubSpot to EasyInvio: current limits and optional test

There is no general two-way profile synchronization. Editing a HubSpot contact/company, adding a sales note or creating an ordinary deal does not update EasyInvio. Supabase-owned billing fields may overwrite CRM edits on the next outbound sync. No ordinary app action should be presented as proof of this unsupported direction.

The implemented inbound path is specifically Closed Won onboarding, currently disabled. To test it, first configure a supported HubSpot app's signed dealstage webhook, its app ID/client secret/public HTTPS endpoint, company/contact/deal read permissions, and actual Closed Won stage IDs; then deliberately enable HUBSPOT_PROVISIONING_ENABLED. A Service Key alone cannot subscribe to webhooks. Do this with a separate test portal/database for inbound onboarding: the current STANDARD-account inbound path creates non-sandbox workspaces and is not changed by the outbound UAT allowlist.

Once separately configured, create a clearly labelled test company with full address/country ISO and an associated contact with name/email. Associate exactly that company and contact to one deal, then move it to the configured Closed Won stage. Expected evidence: a verified webhook queues one activation job; the worker creates one mapped EasyInvio workspace and a zero-balance wallet. Replayed events or another won deal for the linked company must not create duplicates or reset the wallet. Missing data/invalid signatures must be rejected. Login invitations, wallet funding and label purchases are not part of that inbound workflow. Controlled database/HTTP tests cover this path; live inbound webhook acceptance has not been claimed.

### Production acceptance

Keep fixtures and the UAT pilot identifiable; clear HUBSPOT_UAT_TENANT_IDS in a production-only worker, or deliberately retain the selected pilot if sharing the same app/database. Verify expected portal/token/scopes/property readiness, then test one genuine non-sandbox signup and one supported confirmed booking, compare the CRM totals against Supabase, and confirm the same IDs after a second event. There must be no queue errors left unresolved. A production deployment is not fully accepted just because two test companies were created. Optional deal automation and inbound provisioning need their own explicit acceptance tests before enabling them.
