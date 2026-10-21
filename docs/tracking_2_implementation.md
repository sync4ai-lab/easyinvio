# Tracking 2.0: implementation, operating manual and acceptance boundaries

## Implementation assessment

The repository is a FastAPI/asyncpg modular application with a vanilla JavaScript
SPA, not a collection of independently deployed tracking microservices. This
implementation extends its existing domain owners and keeps tracking visibility
included for business and individual workspaces. No subscription check, wallet
debit or premium widget entitlement was introduced.

| Existing component | Reused or extended behavior |
| --- | --- |
| `shipments`, package labels and package-tracking metadata | Authoritative shipment and per-parcel identities; no replacement order or shipment database |
| `tracking_and_support.TrackingSupportService` | Existing signed, tenant/account-bound ingest, event receipts, replay conflicts, terminal-state protection and support staging |
| `automation_three_partners.NativePartnerService` | Existing native EasyPost, Sendcloud and Shippo signature validation, environment/source binding and provider normalization |
| `tracking_events` | Canonical receipt/history store; richer source facts are stored in its response JSON, with immutable facts and separate occurred/received timestamps |
| Existing return links and store lifecycle fields | Returns remain independent of forward delivery, warehouse receipt and merchandise refunds |
| `ConversationalActionGateway`, `WhatsAppQueue` | Existing authenticated merchant actions, encrypted inbox/outbox, stable message receipts and REST dispatch; no second WhatsApp account or webhook |
| `FinanceEngine`, Stripe and booking lifecycles | Unchanged monetary ownership. Wallet/label refunds are never presented as merchandise refunds |
| `SupportDelivery` and consent bindings | Existing opted-in support alerts remain separate; no new paid tracking messages are silently enabled |
| Existing platform-owner authentication and assistance | Server authorization for cross-tenant access; client-side persona switches confer no permission |

`TrackingWorkspace` is the shared read/projection service for retailer, admin,
customer and conversational tracking. `TrackingRefreshWorker` owns bounded,
read-only carrier reconciliation. Neither can purchase a label, initiate a refund,
create a tracker or overwrite a carrier event through an administrative UI.

No private environment values, live credentials, tenant exports or customer
records were inspected to claim that a provider is production-ready. Runtime
capability discovery reports installed adapters, configured connection activity and
environment; actual API entitlements and contract costs still need verification.

## User experiences

- The existing navigation gains one **Shipment tracking** workspace. Platform
  owners see **Control Tower**. Existing quote, dispatch, manifest, wallet and
  customs views remain intact. Existing manifest order references open the same
  tracking drawer and are keyboard accessible.
- A header search and the workspace search accept order/tracking/store references
  and exact parcel tracking numbers. Results rank exact references first and
  remain tenant scoped. Reporting searches default to the last 90 UTC days and
  permit a range of up to 366 days; widen the date range for older list records.
  Conversational exact lookup is not limited to that reporting window.
- Status cards filter actual lists: transit, out for delivery, delivered,
  exceptions, tracking requiring review, returns awaiting receipt and customer
  help requests. No invented historical charts or refund counts are shown.
- The detail drawer groups shipments only through verified store/order identity;
  arbitrary matching addresses/names are not an order relationship. Multiple
  parcel labels and their scans remain separate, with linked returns and an
  independent purchase-refund section. Current shipment state does not regress
  when an older event is received. Actual scan and receipt times are labelled
  separately and rendered in the browser's locale/timezone.
- Operational review can be acknowledged, assigned through the API, annotated,
  escalated or resolved. Notes and attribution are retained in an append-only
  audit. Internal resolution does not mark a carrier delivery, close an insurer
  claim or refund a purchase. Existing carrier support tickets retain their own
  established workflow.
- Known Royal Mail/Evri records can open the official carrier tracking portal;
  this is a public website action, not activation of either direct carrier API.
- Owners/admins can set in-app milestone preferences, a quiet-tracking review
  threshold and polling cadence. Other authorized roles can read preferences.
  Advanced event choices are collapsed. Recent in-app milestones appear in a
  compact feed using the same durable event-derived outbox.
- The branded `/track` page is mobile-first, uses local assets and needs no
  customer account. It reveals only its explicitly shared shipments. It contains
  no complete addresses, contact details, internal notes, account/provider IDs,
  financial amounts or unrestricted proof-of-delivery documents.
- Customers can submit a bounded delivery/return/refund question to the retailer
  queue through their valid capability. This creates an in-app request, not a
  carrier instruction or refund. The retailer sees it in the Customer requests
  filter and detail drawer. Operational review acknowledges those requests.
- Registered conversations use the same shared service for tracking and verified
  store-order groups. An unregistered customer may send `Track link <token>` to
  the existing WhatsApp number: the actual capability is required; a phone number
  or guessed order never grants access. The public page can copy that request
  when Twilio is configured, labelling a configured sandbox as a test sandbox.

No newly introduced feature persists browser form/transcript state across logout.
Pending UI responses are fenced by session generation and tenant/assistance
context. Accounts with read-only tracking permissions do not gain write controls.

## Schema and migration

Apply the complete migration **045_unified_tracking.sql after 044**, once, in the
same database. It has one explicit transaction and a ten-second lock timeout. It
checks earlier tables before DDL. For a missing 043 queue, follow the recovery
instructions in `docs/carrier_manifests_and_media.md`; do not replace or delete
existing queues to make 045 succeed.

New tables are server-only with RLS and browser-role grants revoked:

| Table | Purpose |
| --- | --- |
| `tracking_share_links` | Hashed, expiring/revocable capabilities with fixed shipment membership |
| `tracking_customer_requests` | Capability-verified, bounded customer intake with idempotent request IDs |
| `tracking_preferences` | Tenant in-app categories and operational thresholds |
| `tracking_notifications` | Transactionally staged, unique in-app milestone availability |
| `tracking_refresh_jobs` | Read-only scheduled work, leases, cooldowns, attempts and failure states |
| `tracking_provider_limits` | Shared per-account API admission/rate-limit hold |
| `tracking_case_reviews` | Operational review and assignment; not carrier/refund state |
| `tracking_operations_audit` | Append-only searches, cross-tenant detail access and sensitive operations |

Tracking-event facts become append-only; only the existing `support_pending`
staging flag may change. Original provider status/identifiers, bounded carrier
text and normalized facts are retained server-side. UNKNOWN tracking facts can be
stored after 045 without writing UNKNOWN into the shipment state machine or
notifying customers that an invented milestone occurred. Before the new schema
is ready, native receivers retain their previous unsupported-event behavior.

No shipment enum additions, wallet schema changes, financial locks or unrelated
provider lifecycle rewrites are included. New indexes support tenant/date,
reference, return-reference and chronological event queries.

## Capability security and limits

A new link has 256 bits of randomness; only its SHA-256 hash is stored in the
share table. The token is placed in the browser fragment and POSTed in a bounded
JSON body, never an HTTP URL/query string. The raw token is not written to browser
storage or analytics. Do not enable infrastructure request-body logging for these
public endpoints or encrypted conversational inputs.

Link membership is checked against the tenant at issuance, guarded in PostgreSQL,
and filtered again on every read. It cannot be expanded or unrevoked. Defaults
share only the requested confirmed shipment; the web order action explicitly
includes the displayed order's confirmed parcels, excluding returns. Explicit API
options can include that order and its selected parents' linked returns. Newly
created shipments/returns are not silently added to an existing capability.

Defaults/limits:

- Seven-day links; maximum 30 days, computed with the database clock.
- At most 100 fixed shipment records per capability and 20 active links per anchor.
- Three new help requests per link/day; the same request UUID/content replays
  without creating another request. Changed content under the same UUID conflicts.
- Public bodies at most 4 KB; 30 requests/minute/client-address hash per process,
  with a bounded in-memory map. Add a shared reverse-proxy limit across replicas.
- Interactive groups of at most 100 siblings, 100 linked returns and 5,000 events;
  oversized histories require an operational review rather than silent truncation.
- Tenant-aware pagination and explicit admin dependencies on every global route.

Customer capabilities do not authenticate a workspace and cannot buy, return,
cancel, refresh a provider, read another order or expose a financial record.
Public errors for expired/revoked/unknown tokens do not enumerate order IDs.
The public page uses no-referrer/no-store, a restrictive CSP and no third-party
scripts. Hosted tracking does not require iframe embedding.

## API inventory

| Audience | Operations |
| --- | --- |
| Workspace | `GET /api/v1/tracking/shipments`; `GET /shipments/{id}` |
| Share management | `POST /api/v1/tracking/shipments/{id}/share`; `GET /shipments/{id}/share-links`; `DELETE /api/v1/tracking/share-links/{id}` |
| Preferences/feed | `GET, PUT /api/v1/tracking/preferences`; `GET /notifications`; `GET /capabilities` |
| Review/refresh | `POST /api/v1/tracking/shipments/{id}/review`; `POST /shipments/{id}/refresh` |
| Platform owner | `GET /api/v1/admin/tracking/shipments`; `GET /shipments/{id}`; `POST /shipments/{id}/review`, `/refresh`, `/retry`; `GET /health` |
| Customer capability | `POST /api/v1/public/tracking/resolve`; `POST /api/v1/public/tracking/help` |
| Public assets | `GET /track`, `/tracking-public.js`, `/tracking-ui.css`; authenticated UI controller `/tracking-workspace.js` contains no credentials |

Relative entries in a row use the same row's `/api/v1/tracking` or
`/api/v1/admin/tracking` prefix. Generated OpenAPI and the architecture manual
contain complete paths and request schemas.

READ roles: OWNER, ADMIN, DISPATCHER, ACCOUNTANT. Share/review/refresh writes:
OWNER, ADMIN, DISPATCHER. Preference writes: OWNER/ADMIN. Global search, reviews,
health and explicit failed-job retries: current configured platform owners.
Retailer query parameters cannot change the authenticated tenant. Admin drill-down
uses the actual selected tenant and is audited without logging raw search text.

## Provider reconciliation and activation

Default configuration:

```dotenv
TRACKING_POLLING_ENABLED=false
BOOKING_PAGE_URL=https://YOUR_PUBLIC_APPLICATION_ORIGIN
```

Keep polling off until the connected account's GET quotas, rate limits, contract
costs and production credentials are verified. Basic recorded tracking/public
viewing remains available regardless of polling or optional messaging failures.
`BOOKING_PAGE_URL` must reach this application, including `/track` and its assets;
the restricted Twilio-ingress-only tunnel is not a general application origin.

| Provider | Tracking implementation | Remaining activation boundary |
| --- | --- | --- |
| EasyPost | Existing verified webhooks; optional GET-only shipment/tracker reconciliation and supported scan history | Actual account/environment credentials, purchase bindings, API entitlement/quota and staging acceptance |
| Sendcloud v3 | Existing verified native webhook and explicit account status mapping; original status IDs retained | Real connection settings and current provider subscriptions; polling explicitly unsupported |
| Shippo | Existing verified native webhook, environment checks and original source status | Actual connected account/webhook configuration; polling explicitly unsupported |
| Royal Mail / Evri direct | Existing disabled provisions remain disabled; public carrier portals do not activate APIs | Issued direct API contracts, credentials, implementation/certification remain required |
| Marketplaces/stores | Existing authorized fulfillment/return associations reused | A fulfillment association is not a complete carrier or merchandise-refund feed |
| Stripe | Existing wallet/payment/label finance workflows unchanged | These are not evidence that a merchant refunded a purchased product |

The optional worker seeds up to 100 active EasyPost shipments per minute from the
last 90 days, using current authorized creator or platform-owner access. It uses
SKIP LOCKED claims, a 45-second lease, a shared account admission interval of at
least 30 seconds and a 12-second provider/ingestion timeout. No DB transaction is
held while calling a provider. It retrieves existing purchased shipment/tracker
IDs and verifies remote mode/tracking binding. There is no tracker-creation POST.

Successful nonterminal work recurs at the tenant cadence (default six hours,
configurable one to 24 hours). Terminal shipments stop. Transient failures use
exponential backoff with jitter and a five-attempt limit. Numeric Retry-After
holds are bounded to one day and applied account-wide; unavailable/invalid headers
use a conservative default hold. DEAD and UNSUPPORTED work is observable and
requires an audited platform-owner retry. Expired read leases can recover safely;
this is not a purchase replay. Changing a connection flag blocks new refresh calls
without erasing history or hiding a submitted financial outcome.

The runtime capability registry reports unknown contract costs/quotas as unknown,
not zero. It does not introduce automatic pass-through charges for visibility.

## Messaging economics and unsupported breadth

Existing Twilio rules and consent controls remain authoritative. A customer-initiated
inbound message opens the service window; proactive messages outside it require
approved templates. Twilio/Meta fees depend on message/template/account context,
so no fixed universal cost or unlimited message promise is encoded here.
See [Twilio window/template rules](https://www.twilio.com/docs/whatsapp/key-concepts)
and [current WhatsApp pricing](https://www.twilio.com/en-us/whatsapp/pricing).

New ordinary milestone WhatsApp, SMS and email campaigns are **not activated**.
The new outbox is free in-app availability; existing consented WhatsApp exception
alerts still use SupportDelivery. Identity SMTP configuration is not automatically
permission to send shipment campaigns to buyers. No new external messages were
sent during implementation.

Merchandise refund pending/processing/completed/failed feeds, marketplace financial
permissions, warehouse inspection states, arbitrary direct-carrier polling,
per-service SLA prediction, global historical trend charts and an embeddable widget
are not simulated. Missing feeds are explicitly unavailable. Carrier-estimate
timestamps are displayed only where actually supplied with a reliable timezone;
dates are not inferred from price-estimate delivery days or a quiet tracking feed.

## Verification and release

Normal regression:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
```

Explicit disposable PostgreSQL service/DDL tests (Node.js/npm required):

```powershell
npm install --prefix tmp/tracking045-test @electric-sql/pglite@0.5.10 --ignore-scripts
$env:PGLITE_TEST_MODULE = Join-Path (Get-Location) 'tmp/tracking045-test/node_modules/@electric-sql/pglite/dist/index.cjs'
.\.venv\Scripts\python.exe -m pytest -q tests/test_tracking_workspace_postgres.py
```

The PostgreSQL suite runs complete 043, 044 and 045 scripts plus actual Python
service queries through a disposable PostgreSQL bridge. It never loads `.env`,
connects to Supabase, buys a label or sends a message. It covers tenant/admin
scopes, grouped parcels/returns, separate refund absence, capability hashing,
revocation/expiry, membership guards, bounded/idempotent help, immutable events,
notification deduplication, unknown/late facts, read-only GET reconciliation,
failure exhaustion, account rate-limit holds and authorized platform refreshes.
Without the explicit dependency, these tests skip rather than using a real DB.

Browser QA uses `tests/tracking_workspace_browser.py` against an isolated
`--local-preview` server with synthetic-only API fixtures. It covers owner, tenant
admin, dispatcher, accountant, individual and platform-owner desktop/mobile views,
customer intake, revoked links, session-response fencing, no horizontal overflow
and no capability in HTTP URLs. Screenshots/reports are generated locally under
`output/tracking045-qa`; they are not live carrier evidence.

Before production rollout, verify the real migration baseline and RLS, native
asyncpg connectivity/contention, public HTTPS app hosting, connection entitlements,
carrier webhook acceptance, source status mapping, read quotas and real authorized
phone delivery. No live database migration or production provider acceptance is
claimed by the local tests. Preserve unresolved financial and messaging evidence;
define retention/deletion policies for capability hashes, customer notes, audit
history and notification availability without deleting active investigations.

Local verification on 21 October 2026: the full `tests` suite with the explicit
disposable PostgreSQL dependency completed with **972 passed, 1 skipped,
14 subtests passed and 2 warnings**. Six-persona desktop/mobile browser QA and
public customer-page checks passed using synthetic fixtures, with no page errors
or horizontal overflow. JavaScript syntax, Python compilation and diff whitespace
checks also passed. These are repository checks, not live-carrier certification.
