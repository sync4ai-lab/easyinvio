# HubSpot CRM integration

The client uses `https://api.hubapi.com`, HubSpot's documented API host, with the CRM v3 company, contact, deal and association paths. `https://hubapi.com/companies` is not the documented CRM API endpoint. No API calls have been made to your HubSpot account, and migration 010 has not been applied remotely.

## Activation

Apply `migrations/010_hubspot_crm.sql` after 009. It adds private job/mapping tables and database triggers for tenant creation/profile changes and confirmed shipment updates. It does not require the optional HubSpot worker to be running; jobs remain pending until enabled. Existing tenants can be queued using the endpoint below.

In a separate HubSpot developer/test account, create a private app with company, contact and deal read/write permissions and access to read CRM property definitions and deal pipelines. Set these server-only `.env` values:

```dotenv
HUBSPOT_ENABLED=true
HUBSPOT_ACCESS_TOKEN=pat-YOUR_ACCOUNT_TOKEN
HUBSPOT_UPSELL_PIPELINE_ID=YOUR_PIPELINE_INTERNAL_ID
HUBSPOT_UPSELL_STAGE_ID=YOUR_HIGH_VOLUME_UPSELL_STAGE_INTERNAL_ID
```

`pat-...` is an accepted private-app credential, not a test-mode switch. The token writes to its issuing account. Never put it in frontend configuration. The client also accepts OAuth bearer tokens, but token refresh/rotation is managed externally. HubSpot remains disabled by default, including local preview.

Create the following custom properties in HubSpot before enabling sync:

| Object | Internal property name | Type / field type | Unique |
|---|---|---|---|
| Company | `veloce_tenant_id` | string / text | Yes |
| Company | `veloce_vat_number` | string / text | No |
| Company | `veloce_package_count` | number / number | No |
| Company | `veloce_total_spend` | number / number | No |
| Company | `veloce_currency` | string / text | No |
| Deal | `veloce_milestone_id` | string / text | Yes |

For unique properties, use the properties API with `hasUniqueValue: true`. Example `POST https://api.hubapi.com/crm/v3/properties/companies`, with Authorization Bearer token:

```json
{
  "groupName": "companyinformation",
  "name": "veloce_tenant_id",
  "label": "Veloce Tenant ID",
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

It returns HTTP 202 and QUEUED; it does not claim remote completion. Company name, billing email and VAT (`company_profile.tax_id`, empty when absent) come from the saved tenant profile. Another tenant's UUID is forbidden. To see delivery or repair a blocked job, inspect the server-owned `hubspot_sync_jobs` and `hubspot_tenant_links` tables in the SQL editor. A successful job is removed and the company/deal IDs and sync timestamp are retained. Resubmitting the endpoint resets attempts and unblocks the job after configuration has been corrected.

## Behavior and reliability

The background worker creates or updates a company using its unique Veloce tenant UUID, creates/updates a contact by email, and calls `/crm/v3/associations/contacts/companies/batch/create`. Equal company display names never merge tenants. HubSpot contacts are email identities: the same email may legitimately be associated with multiple companies.

On confirmed BOOKED/DELIVERED shipment events, the worker recomputes cumulative shipment count and exact customer spend from tenant-scoped database rows. One shipment represents one package in the current schema. Count 50 does not create an upsell; count 51 or more creates one deal in the configured stage and associates it with the company. A unique milestone property prevents duplicate deals after retries and ambiguous create timeouts. No speculative deal amount is assigned. Mixed-currency totals are blocked instead of summing unlike currencies; implement an explicit conversion policy before syncing such accounts. Counts/spend exclude failed bookings, pending imports and unbooked quotes. The totals are operational booked spend, not tax/accounting revenue.

Automatic enqueue happens in the same database transaction as the tenant/shipment change. CRM enqueue exceptions are caught so they cannot roll back a paid label; after such a database failure, use manual sync to reconstruct state. Remote HTTP never occurs in rating or label settlement. Durable jobs survive restarts. Tenant-specific session advisory locks serialize workers, revisions preserve events arriving during sync, and updates retain rate-limit retry deadlines. Use the application's existing direct/session-pool database connection configuration, not transaction pooling for session advisory locks.

429 and server errors use bounded exponential backoff with jitter and respect Retry-After. Long waits are deferred to the durable scheduler. Authentication/property configuration errors block the job immediately; transient jobs block after twelve attempts. Failure codes contain no token, company email or remote response body. Successful create requests are recovered through unique properties on retry, avoiding reliance on an unsupported generic HTTP idempotency header. HubSpot search indexing can delay conflict recovery, so a 409 retains the job for a later attempt.

The exported async utilities preserve the requested signatures:

```python
await sync_tenant_to_hubspot(tenant_id, company_name, email, vat_number)
await log_shipping_activity(company_name, package_count, total_spend)
```

They validate stored tenant data and queue background work. Shipping activity rejects ambiguous company names and caller totals that differ from confirmed database values. They are trusted backend utilities, not public unauthenticated endpoints.

## Verification

Run `.venv/Scripts/python.exe -m unittest discover -s tests`. HubSpot tests use httpx MockTransport, exercise the complete outbound wire payloads and verify company isolation, replay, count 50/51, exact spend, rate limits, authentication failures and endpoint authorization. No real CRM records are created by tests. The SQL migration still requires validation against your deployed Supabase base schema.

References: [Companies](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/companies/guide), [Deals](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/deals/guide), [Custom and unique properties](https://developers.hubspot.com/docs/api-reference/legacy/crm/properties/guide), [API usage limits](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines), [Private apps](https://developers.hubspot.com/docs/apps/legacy-apps/private-apps/overview).
