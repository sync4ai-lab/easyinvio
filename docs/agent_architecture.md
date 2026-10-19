# EasyInvio bounded logistics assistance

The supervisor coordinates narrow workers around existing services. It is an application state machine, not a model deciding who may spend money. Optional preparation and rate badges do not change FinanceEngine or RLS contexts. The separate Settings catalogs use migration 036. Conversational actions require private receipt migration 038, applied after 037. Standard workflows remain available with AI disabled.

## Capabilities and boundaries

| Capability | Implementation | Authority |
|---|---|---|
| Message preparation | IngestionWorkerAgent retains the quote preparation tool and adds a structured ConversationalIntent extractor | A model proposal cannot authorize a purchase. Explicit commands, authenticated roles, displayed options and native service checks authorize actions |
| Conversational actions | Both signed Twilio webhook routes and the authenticated web chat use ConversationalActionGateway | Registered phone bindings or the browser session establish identity. Receipt hashes prevent changed-content replay; durable private choices preserve the displayed option order |
| CSV imports | Known headers normalize without AI. Unknown headers use a bounded tool call containing column names only | Row values are unchanged. Existing CSV validators, durable imports, quote flow and manual booking approval remain authoritative |
| Customs preparation | Typed goods preserve quantities, weights, values, origin and allocation; descriptions are deduplicated for suggestions | The existing checkout tariff search additionally ranks fresh official UK tariff candidates when AI is enabled, keeping their source links and requiring review. The separate example-suggestion endpoint uses eight examples and is not a certified tariff. Codes and national extensions require review; customs approval is never granted by AI |
| Quote execution | Supervisor calls the existing durable rates endpoint with a complete RatingRequest | Current permissions, package rules, pricing and stored quote snapshots apply |
| Booking | Existing authenticated confirm-booking route passes a chosen opaque offer to Supervisor, then PartnerLifecycleService | Existing FinanceEngine locks, reservation/capture/release, uncertain-purchase reconciliation and PDF proxies are unchanged. No model has this tool |
| Invoice audits | InvoiceSurchargeAuditorAgent delegates existing exact Decimal comparisons | Current tenant-scoped snapshots, confidence definition, idempotency and billing_disputes writes stay authoritative. Zero model tokens |
| Tracking exceptions | ProactiveClaimsSupportAgent delegates authenticated provider ingestion and durable ticket/outbox staging | Current signature checks, event deduplication, administrator controls, verified recipient and notification consent remain mandatory. Zero model tokens |
| Help | Published local guides are split at section headings into versioned, bounded chunks with direct section citations. Optional 256-dimensional embeddings rank excerpts; structured answers must cite retrieved IDs | Authenticated workspace requests only. No access to customer records, purchases or messages. Unavailable AI falls back to compact related-guide cards with an explicit availability message |

## API surface

- `POST /api/v1/agents/interpret`: `{ "text": "Quote 4.5kg from GBR to USA" }`. Returns extracted facts, NEEDS_INPUT and `booking_authorized: false`.
- `POST /api/v1/agents/quote`: the existing complete RatingRequest schema. Returns the quote and supervisor transitions. It never books.
- `POST /api/v1/agents/customs/suggest`: `{ "description": "cotton knitted t-shirt" }`. Returns a review-required suggestion.
- `POST /api/v1/agents/customs/information`: `{ "items": [...] }`, using the existing Goods schema, up to 100 lines. Preserves goods facts and returns suggestions without approving them.
- `POST /api/v1/help/search-agent`: `{ "query": "When is my wallet charged?" }`. Returns answer, source links, retrieval mode, document version and generation usage.
- `POST /api/v1/conversational/process-message`: authenticated WEB_CHAT messages with `message_body`, `channel` and a stable UUID `request_id`. Optional `sender_id` is not an authentication credential. Returns `status`, `conversational_reply` and `action_taken`.
- `GET /api/v1/admin/agents/metrics`: existing platform-owner authentication; aggregate current-process model/embedding usage and configuration status. No prompts or secrets.

The existing rates, official tariff search, CSV, invoice, tracking and confirm-booking paths are connected directly. Provider webhooks and ordinary UI rates retain their current deterministic validation. Help searches on each keystroke remain local; the explicit assistant button calls the server. Anonymous visitors can still read every public guide.

## Activation

1. Install the pinned-range dependencies in `requirements.txt` using the project virtual environment.
2. Set `OPENAI_API_KEY` privately and `LOGISTICS_AGENTS_ENABLED=true`. The default model is the requested `gpt-4o-mini`; embeddings use `text-embedding-3-small`. Never put credentials in Git.
3. Apply `migrations/038_conversational_actions.sql` after 037 before using chat actions, then restart the backend. Existing preparation and help endpoints do not need this new table.
4. Test messages, mapped CSV headers, reviewed customs examples and Help Centre answers in a non-production workspace. Complete accuracy evaluations against your real use cases before broader rollout.
5. Inspect the protected metrics endpoint and your provider billing dashboard. Set a provider budget appropriate to your account. To disable AI, set the flag false and restart; standard shipping tools continue.

## Cost, privacy and resilience

Each model run is limited to one turn, 600 output tokens by default, no model retries, a six-second timeout and four concurrent slots. WhatsApp parsing has a tighter three-second budget. Per-tenant, per-process sliding limits conservatively reserve input bytes plus schema overhead and output allowance. These are abuse controls, not guaranteed billing caps or shared limits across multiple server processes.

## Conversational commands and deployment

The dashboard's **Ask EasyInvio** button opens a session-bound conversation. Its contents stay in browser memory and clear on logout, login or an assistance workspace change. Renewing the same active session keeps the conversation. The Help Centre search remains a documentation-only endpoint; the action gateway is a separate authenticated interface that can also call that documentation retriever.

Both `/webhooks/twilio/whatsapp` and `/api/v1/integrations/whatsapp/webhook` verify the existing Twilio signature before resolving an active, verified phone binding. An unregistered number receives 403. Configure Twilio's canonical external webhook URL for the chosen route, as before. Sending arbitrary WHATSAPP JSON to the web endpoint is forbidden, including with a valid web session. Web chat derives tenant and user from the existing session, never from a supplied phone number. Existing admin-assistance request auditing still applies.

Supported commands work with AI disabled:

- `Quote 4.5kg from GB to US route EXPORT_US`: an explicitly selected saved route can supply full addresses and measured packaging. Without a route code, the gateway collects postcodes, explicit countries, packed weight, measured dimensions and real contact/street/city details across turns. The native rating service consolidates prices; up to ten actual options are stored in displayed order. This command does not invent goods details or remove international customs review requirements. Use Create a shipment when the route lacks the required goods or customs information.
- WhatsApp `Book option 1` returns a signed link for the selected option from the latest completed quote. It does not reserve funds or buy a label. Configure `BOOKING_PAGE_URL` to the HTTPS dashboard root (the current ngrok forwarding origin for local testing, not the Twilio webhook path). The browser removes the signed query from its address bar, keeps it in memory through sign-in, and resolves it only for the same authenticated user and workspace. Expired links require fresh quotes. Customers review packing, customs and payment in the existing checkout before confirming. Refreshing before resolution requires reopening the message link.
- Web chat `Book option 1`: confirms the price displayed by the latest completed quote for this user, workspace and channel. The choice must be unexpired. OWNER, ADMIN or DISPATCHER permission is required. PartnerLifecycleService owns preparation, customs readiness, environment checks, wallet reservation, capture/release, carrier confirmation and document generation. A model choosing an option is insufficient consent. Protection is not automatically added.
- `Track YOUR_REFERENCE`: looks up a unique shipment UUID, customer reference or tracking number within the authenticated tenant. It reports recorded status and milestone timestamps, including recent recorded exceptions. It does not claim a new live carrier check or expose internal supplier error text.
- `Top up 50 GBP`: OWNER, ADMIN or ACCOUNTANT permission is required. The amount must match the wallet currency, be between 1 and 10000 and have at most two decimal places. Exact Decimal values reach FinanceEngine.create_checkout. A verified HTTPS Stripe Checkout link lets the customer complete payment; chat does not credit the wallet or collect card details.
- `Claim TRACKING123 damaged Describe what happened`: use `lost` or `damaged` and at least ten characters of notes. A locally confirmed XCover policy is required. This creates a `CLAIM_INGESTED` support case and ticket. It does not assert current insurer eligibility, submit FNOL, approve a claim, change delivery status or credit funds. Insurer filing and evidence use the existing Shipment protection & claims workflow, which verifies coverage with the provider.
- `Help`: lists commands without a model call. General questions use the published-document retriever when available; disabled AI retains document excerpts and citations.

The optional model proposes one of six typed intents. Its parse has a three-second deadline; explicit commands need zero parser tokens. The legacy QuoteIntent remains for existing preparation callers. Monetary model fields reject binary floats. Mutation handlers independently ground the exact booking, top-up and claim command in the original message. Approximate natural-language payment instructions receive an explicit command example instead of executing.

Migration 038 stores message hashes, actor/tenant/channel identity, processing outcome and private ordered quote-choice references. It does not store raw conversation prompts. Claim notes are deliberately saved in the existing private insurance/support records. The receipt's short transaction commits before model or provider IO, and releases its database connection before native financial services run. Only one processing message per user/channel starts at a time. Completed deliveries replay the saved result; changed-content reuse and unfinished deliveries receive 409. Reuse the same request UUID when retrying a web request; Twilio MessageSid maps to a stable UUID.

An interrupted action is never automatically executed again. REVIEW_REQUIRED receipts need comparison with authoritative shipments, reservations, payments or claim cases. A process crash may leave PROCESSING and block later messages in that thread. An authorized operator must reconcile its outcome before changing that receipt to REVIEW_REQUIRED; do not delete receipts or restart purchases to clear the block. This is a deliberate financial retry fence. No carrier purchase, Stripe payment, model API call or migration was executed as part of the local contract/browser tests.

Identical private requests cache in bounded memory for five minutes, scoped to tenant and model; generated help answers cache for two minutes with document-version invalidation. Concurrent identical first requests may still incur separate calls. Published-document vectors alone cache under `output/agents`; queries and customer rows are never written there. The public index builds lazily once per process/document version and can be shared through that cache directory. Runtime metrics include embedding and generation usage; per-answer `usage` reports generation only, not shared index construction. Cache hits report zero new generation tokens.

SDK tracing is disabled, Responses storage is disabled and application usage logs contain worker names and token counts rather than prompt content. CSV assistance sends only unfamiliar headers and remaining allowable targets. Customs assistance sends descriptions and example dictionary entries. Help removes obvious emails, international phone numbers and UUIDs before processing, but this is not a comprehensive personal-data scrubber: users must avoid entering private details. Sending model inputs is still subject to your OpenAI account's data-handling settings.

Model failure cannot debit a wallet. A failed model call offers standard-form guidance; help falls back to compact cards linking to original documentation. If vector retrieval is unavailable, generation can still use source-backed keyword retrieval. Transient generation failures are not cached over subsequent recovery. Consequential service failures preserve existing reservation release or reconciliation behavior rather than letting an agent retry purchases. Durable tickets and outbox jobs remain in the existing database pipeline, not a new in-memory message queue.

## What this does not claim

This layer does not create an authoritative customs catalogue, enable missing carrier contracts, repair unavailable provider credentials, create insurance coverage, schedule pickups, automate merchant consent or certify model accuracy. It does not implement autonomous claim approval or infer missing shipment measurements. It cannot guarantee that every supported-looking package produces a carrier rate. Those are operational capabilities, not problems that an LLM can safely invent around.

The design reduces avoidable token use by reserving AI for ambiguous interpretation and documentation answers. Its value should be measured through successful booking rate, time to prepare a shipment, grounded-answer accuracy, support resolution time and tokens per completed workflow. Claims of being the world's first or best logistics platform require external evidence.

## References

- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk)
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Embeddings](https://developers.openai.com/api/docs/guides/embeddings)


## Top-ten rate advice and reviewed catalogs

Pricing still uses the existing database margin rules. Carrier/service/currency consolidation chooses the largest absolute contribution (customer price minus returned wholesale total), with deterministic ties, then retains up to ten lowest customer prices. This is not a claim of net accounting profit after overhead, tax and other platform expenses. UI rate requests optionally send only those offers' customer prices, estimates and measured local history to MarginOptimizerAgent. No supplier IDs, credentials or wholesale costs go to that model.

The advice step has an outer 1.5-second timeout. It may attach one evidence-checked, server-formatted badge, but cannot reorder, reprice or purchase any offer. Missing history cannot produce a reliability claim. A timeout or invalid recommendation returns the unchanged offers without a badge. Internal failures are written asynchronously to existing automation_failures and support_tickets, grouped by tenant/error/hour to prevent repeated optional timeouts flooding the queue. Writes are bounded and logged if storage is unavailable; no system can guarantee a database trace during a database outage. Completed-response usage is measured; cancelled requests may still incur provider charges not represented by a completed SDK usage response.

Migration 036 prepares private address/contact/product catalogs; it does not alter finance, shipment or RLS contexts. Saved SKU facts become ordinary validated quote snapshots. The authenticated customs suggestion endpoint can accept an optional sku and reuse a matching, explicitly reviewed tenant product without a model call. A different description cannot silently inherit that reviewed classification. Every shipment declaration still requires human approval.


## WhatsApp conversational registration

`backend/whatsapp_onboarding.py` adds an opt-in `ConversationalSignupManager`. It runs only behind the existing signature-verified Twilio endpoints. Both endpoints check registration receipts before routing a delivery; registered users otherwise continue into the existing conversational action gateway. Inactive, revoked, suspended or ambiguous bindings cannot create a replacement account through signup. Every later message still checks the active binding, membership, workspace and action permission; phone verification is not a permanent permission override.

The customer flow is:

1. Send **Register** or **Hello** from an unregistered WhatsApp number.
2. Choose **1** for Business or **2** for Individual. Business accounts supply legal company name, registration number and country: `Example Trading Ltd, 12345678, GB`.
3. Business accounts supply contact and billing fields: `Alex Smith; 1 Example Road; Leeds; LS1 1AA; YES`. YES declares authority to register the company. These billing details are not automatically treated as a shipment pickup address.
4. Supply an email address that is not already associated with an account or another registration. Individual accounts go directly to this step, without company, registration, VAT, EORI or billing-address questions.
5. Receive the email OTP through Supabase and a separate six-digit WhatsApp challenge through the signed webhook reply. Send **EMAIL_CODE WHATSAPP_CODE** as two numeric codes separated by a space. Using the WhatsApp code twice does not prove email access.
6. After both codes verify, Business accounts send **Continue**; Individual accounts provide their full name to complete workspace creation. The account has an OWNER membership, a GBP wallet with exactly 0.00 available and reserved credit, a native Supabase Auth identity/profile and an active verified WhatsApp binding. It receives no free funds, carrier credentials, quotes, shipping labels or protection cover.
7. Open the password setup email on the computer where the app is available. If delivery is not confirmed, use the existing **Forgot password** screen. Passwords and recovery credentials are handled by Supabase Auth; they are never collected in WhatsApp or stored in a new public.users token column.

**Deployment requirements:**

- Apply `migrations/039_whatsapp_onboarding.sql` after 038. Do not reuse migration number 027; it already belongs to a different feature. The migration adds private queue/receipt tables and tenant creation-source metadata. Legacy source values default to UNKNOWN when this column is newly added. Existing RLS contexts and deterministic FinanceEngine locks are unchanged.
- Configure a valid public HTTPS Twilio ingress and its exact canonical URL, enable Twilio and retain its existing signature checks. Localhost alone cannot receive Twilio webhooks. See the existing WhatsApp integration setup for the allowed receiver/account settings.
- In Supabase Auth, enable email signup and configure SMTP/delivery limits for the intended customer addresses. Change the Magic Link email template to include `{{ .Token }}` so the customer receives an email code. Email OTPs may use 6?10 digits; configure the provider's email OTP expiry to 900 seconds. The app also enforces a 15-minute verification deadline and a maximum of five attempts; provider limits remain in force.
- Configure the existing password recovery redirect allowlist and Reset Password template exactly as described in [password recovery setup](identity/password_recovery.md). Use the actual HTTPS desktop application origin in production. A loopback recovery URL is usable only on the computer running the local app.
- The [SendGrid onboarding configuration](identity/password_recovery.md#sendgrid-backed-whatsapp-onboarding) supplies complete responsive OTP and recovery templates, the `operations@easyinvio.com` sender settings and supported `/set-password` destinations. SMTP credentials remain in Supabase Auth; the onboarding API does not send independently generated email codes.
- Set `WHATSAPP_ONBOARDING_ENABLED=true` and restart the backend. The default is false. `WHATSAPP_ONBOARDING_DAILY_LIMIT` defaults to 100 new sessions per receiving number per day. Existing signing/encryption keys must remain configured; no secrets belong in Git.
- Complete an authorised sandbox acceptance run with your own phone/email after configuration. Automated tests use fake provider responses and create no real identities, emails, workspaces or funds. Newly created accounts still need approved carrier access and Stripe customer/funding configuration before they can obtain paid services.

Company parsing is deterministic and uses no AI tokens. Legal registration numbers are scoped to the supplied country, normalised for comparison, and checked against existing tenants and active signup queues. This is a duplication check, not a company-register lookup, legal ownership verification, KYB certification or proof of authority beyond the customer's declaration. Email responses do not identify which existing account caused a conflict.

Supabase creates the provisional Auth identity when an email OTP is requested. The app grants no tenant membership until the independent codes verify. After verification, the real provider UUID is checkpointed; no invented UUID is inserted into auth.users. Server-owned app_metadata is updated through the Auth admin API. Tenant, zero wallet, OWNER membership, app profile and WhatsApp binding are then committed together in one SQL transaction, with a final duplicate check. Short tenant, membership and binding table locks fence concurrent account creation during that final transaction; no network calls occur while those locks are held. Auth and PostgreSQL are separate systems, so this is resumable provisioning, not a distributed atomic transaction. Metadata pointing to an unfinished tenant grants no membership.

Native async HTTP sends the email request without blocking the Python event loop or starting an untracked thread. The response says delivery was accepted only after the provider accepts it; it cannot guarantee inbox arrival. Password-email delivery is optional and tightly bounded after the database commit. If the provider's one-time verification result is uncertain, the queue enters RECONCILIATION_REQUIRED and cannot automatically verify again. A persisted PROVISIONING step can resume within its verification window; an expired setup needs operator review. Review authoritative Auth records, queue state, memberships and bindings before resolving an interruption. Never delete an Auth identity merely to retry signup.

Phone challenges use a purpose-separated HMAC, not plaintext storage. Receipt responses are encrypted with the existing credential key ring because a replay can contain the WhatsApp code; receipts older than 15 minutes do not replay that code. Email codes and Auth session tokens are not persisted by this service. The queue retains the registration outcome and identity references for reconciliation, rather than deleting all audit evidence on success. Queue/receipt data is private, and operators must apply their retention policy to expired/cancelled history. Browser roles have no direct access.

Resends require a 60-second wait, are limited to three per registration and do not reset the five-attempt verification budget. Starts are limited to three per phone per day, with a receiver-wide cap and a 30-message hourly phone limit. Delivery SIDs are idempotent and bound to the original sender, receiver and message HMAC. Changed-content SID reuse is rejected. Expired pending sessions release their company/email reservations. Cancelling before activation does not promise to delete a provisional Supabase identity; an abandoned identity may need support review.

Official references: [Supabase email OTP configuration and verification](https://supabase.com/docs/guides/auth/auth-email-passwordless), [server-side Auth metadata updates](https://supabase.com/docs/reference/javascript/auth-admin-updateuserbyid).


## Multi-turn quote and support context

`backend/agents/conversation_context.py` defines a typed 15-minute draft. The
latest completed receipt in migration 038 stores it privately under `_pending`,
scoped by tenant, authenticated user and channel, and bound to the selected
admin-assistance session when applicable. It is not returned to the browser.
No additional schema migration or in-memory session cache is required. A single
PROCESSING receipt still fences concurrent deliveries; replay of a completed
message returns its saved response without advancing the draft again. Structured
address and quote facts now remain in private receipts for reconciliation; raw
prompts are not retained except deliberately recorded claim notes. Retention
policies must cover these private structured drafts as well as prior choices.

Examples work in the same controller for WEB_CHAT and signed WHATSAPP:

1. `Get a quote for a 3kg parcel from London to Paris` records the weight and
   cities, then requests `Origin Postcode, Destination Postcode`.
2. Reply with the real postcodes, then confirm ISO countries if not already
   supplied. Numeric postcodes alone do not establish a country, and no city is
   inferred from a postcode without an implemented authoritative lookup.
3. Reply with measured `length x width x height` in centimetres, then real pickup
   and delivery `contact name; street; city`, optionally adding a fourth field
   for state/province. The operator supplies all facts not already known.
4. The native RatingRequest/RatingService boundary validates the complete payload,
   applies dimensional charging, evaluates margins and consolidates up to ten
   actual offers. No fabricated street, dimensions, goods or provider rate is
   introduced. International booking still requires the existing customs review.
5. `Cancel` clears the active draft. A fresh quote command starts a new draft;
   unrelated actions interrupt the old one. Expired drafts are ignored. A rate
   outage retains a bounded retry draft; only an explicit Retry requests rates
   again. No rate error authorizes a purchase or wallet action.

Explicit quote phrases, field replies, tracking references and simple lost/damaged
messages avoid model calls. For other wording, IngestionWorkerAgent uses one
forced side-effect-free `submit_conversational_intent` tool call, with grounded
postcodes/cities, missing facts set to null and no invented countries. Existing
model deadlines, token limits and deterministic command authorization remain.

`Where is my package?` asks for a reference when none has been established in
the immediately preceding conversation turn. It can reuse that user's latest
explicitly tracked reference, not an arbitrary tenant shipment. Replies report
saved carrier milestones and timestamps, not a new live carrier API check or an
invented warehouse location. Recent exception records are described without
asserting that a historic exception is still active.

`My package is lost` or `My package is damaged` asks for the tracking reference,
then checks the tenant shipment, role and confirmed local XCover policy before
creating the existing CLAIM_INGESTED case and OPEN support ticket. It does not
change shipment status, file an insurer claim, or credit a wallet. Explicit
`Claim REFERENCE lost Detailed description` commands remain supported.

The reply includes a `/?claim_id=UUID` dashboard link when the configured
AUTH_RECOVERY_REDIRECT_URL supplies a valid app origin. It is a reference, not
a bearer credential; the user must sign into the correct workspace. The
frontend loads the case through the authenticated existing claims endpoint and
opens the real photo input/drop panel. Backend evidence validation and provider
eligibility remain authoritative. Production must serve this SPA at that origin;
localhost links work only on the dashboard computer.

A chat intake may be completed exactly once by its original authenticated actor
through the existing submit-claim endpoint. `backend/conversational_claims.py`
requires a matching workspace, shipment, policy, reason, creator, prior digest,
unsubmitted CLAIM_INGESTED state, empty submission/evidence and the chat intake
marker. The normal claim advisory lock and SQL transaction enclose the upgrade,
activity and photograph writes. Subsequent changed-evidence requests remain
conflicts; identical submissions retain existing idempotency. The normal insurer
worker or trusted portal, not chat, completes insurer filing.

Validation uses synthetic SQL/provider boundaries and an offline browser scenario.
No live carrier quote, label, payment, insurer filing, migration or SMTP change
is performed by those checks. Source: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling).


## Business and individual workspaces (migration 040)

Apply `migrations/040_workspace_personas.sql` after 039, before restarting this version. Do not apply the proposed migration 028: that number is already used. No migration was executed by the implementation checks. Existing tenants and in-progress company registrations retain BUSINESS. New WhatsApp registrations start at PENDING_PERSONA. INDIVIDUAL workspaces have a real personal name, verified email and phone pairing, without invented corporate identifiers or billing addresses. Shipping still requires actual sender/recipient addresses and reviewed international customs data.

Both personas use the same tenants, users, wallets, shipments, quote choices, bookings and insurance/claims tables. `workspace_type` is server-owned, not an authorization role or a client-supplied quote override. Platform administrators can create either profile shape. Client listings and audited assistance expose the stored persona. Personal phone details collected on the website do not establish verified WhatsApp access.

Web sign-up uses `/api/v1/auth/register` and `/api/v1/auth/register/verify`. A private 15-minute receipt, hashed random registration secret, per-IP limit and five-attempt budget precede activation. Auth owns email OTP verification. The database stores no passwords or raw OTPs. The password is submitted only with verification, sent to the Auth API, then cleared from the form. Existing Auth identities cannot be claimed by entering their email. Uncertain Auth operations are fenced for reconciliation. Verified tenant, zero GBP wallet, OWNER membership and profile commit in one SQL transaction. Auth provisioning and SQL are separate systems: an interruption after an external change needs support review, not automatic replay. A refresh/back action clears the browser-only verification receipt; use the current verification session until it completes. No free credit, live purchase or web login is granted by signup.

Publish the updated `docs/identity/email_templates/verification_otp.html` in Supabase's email OTP templates. It now explains both website code entry and WhatsApp's two-code response. Supabase controls email OTP length (supported here: 6 to 10 digits); a fixed six-digit promise would be incorrect for projects configured with eight digits. Retain the existing SMTP sender, email signup configuration and recovery redirect allowlist. Password setup retains the single-use recovery-token flow and normal password login; the desktop form additionally checks the entered email against the verified recovery identity.

`/api/v1/admin/individual-pricing` is platform-owner-only. GET returns percentage/version; PUT requires a request UUID and expected version. Updates use an advisory lock, compare-and-set version and append-only `individual_pricing_events`; repeated identical requests replay, changed or stale requests conflict. The active singleton is a separate private configuration table, not a tenant margin rule or an audit-event column. No artificial all-zero tenant is inserted. The default is exactly 20.00 percent, with no business minimum-markup floor. Quotes use fixed-point Decimal, the existing monetary rounding rules and supported currency. Database failures do not silently replace configured pricing.

`RatingService.quote` reads one individual policy for the batch. Every individual offer bypasses business margin_rules, retaining the applied percentage and configuration version in its private execution/pricing snapshot. Existing quotes keep their displayed price until expiry; a setting change affects new quotes. Business rule selection is unchanged. Customer payloads continue to omit private execution details. Wallet locking, capture/release, card payment and insurer eligibility follow existing deterministic services.

The owner dashboard groups shipping totals by tenants.workspace_type and currency, and ticket/account counts by workspace_type. It displays paired Business/Personal bars for package volume, confirmed labels, gross revenue, stored gross margin, period ticket counts and active accounts. Combined currency totals remain compatible with existing widgets. Reports retain their period and sandbox/production filters; currencies are never added together. Shipping margin is stored gross markup, not net profit. Tax assessment remains the existing excluded-tax behavior: persona alone does not establish jurisdiction, registration status or a tax rate, and no new tax collection is introduced.

Validation: 872 tests passed, one skipped, 14 subtests passed; personal registration/cohort and WhatsApp checkout offline browser checks passed. These checks use synthetic providers/database boundaries. A staging migration, real SMTP verification, payment and carrier/insurance acceptance remain separate operational checks.


## Budget carrier strategy and company-level prospect research (migration 041)

Apply `migrations/041_budget_seller_strategy.sql` after 040 before restarting this version. The migration was not executed by implementation checks. It adds the server-owned tenant `seller_classification` flag, extends the existing admin audit action allowlist, and protects both seller_classification and workspace_type from browser database updates. Platform administrators explicitly select Prefer budget carriers in Client Accounts; an authenticated owner-only PATCH endpoint locks the tenant row and audits old/new classifications in the same transaction. Classification is a commercial account preference, not an inferred nationality, demographic attribute or proof of shipment volume. Individual accounts already qualify without a business flag.

Worker 3 lives in `backend/agents/margin_optimizer.py`. The finalized top-ten offers, prices, currencies, order and private booking references remain deterministic. Within the existing 1.5-second optional layer, the worker reads the verified tenant's persona/classification and gives the model the complete shortlist and bounded account strategy. For INDIVIDUAL or HIGH_VOLUME_COST_SENSITIVE_SELLER accounts, code identifies the cheapest available Evri/Royal Mail/Yodel offer satisfying the budget constraints. It must have no active exception or HIGH_DELAY_ALERT, be no more expensive than available non-budget choices, and be at most two estimated days slower than the fastest available non-budget choice. Missing budget delivery estimates do not establish the two-day allowance when enterprise estimates exist. Unknown history is never described as proven reliability. Mixed currencies cannot produce a budget preference.

After a valid model response, deterministic code enforces the eligible preferred index and applies exactly one `EasyInvio Budget Choice` badge. Otherwise normal balanced selection continues. No actual budget carrier returned means no invented budget option. AI disabled, profile lookup failure, model failure or timeout retains the original priced shortlist without adding a badge; existing background troubleshooting persistence is retained. Carrier contracts and route availability remain prerequisites. No preference reorders offers, changes a price, purchases a label or moves wallet credit.

`backend/tools/sme_lead_scraper.py` is a manually invoked research utility, separate from application startup. It uses Companies House's official advanced search API with active-company, location and SIC filters. Defaults are TW6 (Heathrow) and M90 (Manchester Airport), with e-commerce, wholesale and warehousing SIC categories. Local checks enforce exact outward postcode districts, active status and intersecting SIC codes; company-number de-duplication and source URLs preserve provenance. Pagination limits and truncation are explicit. Calls are sequential, at least one second apart, with request budgets, timeouts, bounded backoff and Retry-After handling. API errors produce no completed export. Existing reports require explicit --overwrite.

Set `COMPANIES_HOUSE_API_KEY` in your environment or in a private env file. For example:

```powershell
.\.venv\Scripts\python.exe -m backend.tools.sme_lead_scraper --env-file .env --output output/sme_leads/prospects.json
```

The JSON contains company-level leads, search completeness information and unsent email drafts. Registered offices do not prove an operating warehouse, SME size, shipping volume or trading corridor. The tool does not request officers, founders, ethnicity, nationality or personal email addresses. To focus on China/India trading corridors, supply explicit company-level public declarations for review:

```text
company_number,trade_country,evidence_url,storefront_type
```

Use eight-character company numbers (including leading zeros), trade_country CN or IN, a public HTTPS evidence page, and the company's declared storefront category. Run with `--corridor-evidence path/to/reviewed-company-evidence.csv --require-corridor-evidence` to retain only companies with supplied corridor evidence. Evidence is labelled SUPPLIED_FOR_MANUAL_REVIEW; a URL alone is not independently verified proof. No website crawling or inferred personal-nationality targeting occurs. Without evidence, the result remains a general hub/sector prospect list requiring qualification.

Outreach is company-team-addressed draft text, with no discovered recipient and no sending code. It avoids the unsupported 14-percent margin-loss statistic, unconditional carrier/fee claims and promises of live credit. The proposed fifty-pound demo is explicitly illustrative simulated credit subject to demo setup, not an automatic allocation, withdrawable funds or live-label spending power. No company emails, wallets or account records are modified. Exports under output/sme_leads are ignored by Git.

Sources: [Companies House advanced search](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/search/advanced-company-search), [API authentication](https://developer.company-information.service.gov.uk/authentication), [rate limits](https://developer.company-information.service.gov.uk/developer-guidelines), [official SIC list](https://resources.companieshouse.gov.uk/sic/).

Validation: 883 tests passed, one skipped and 14 subtests passed. The offline admin-control/budget-badge browser scenario passed. Discovery tests use synthetic Companies House replies; no real company export, outreach, wallet credit, live booking or migration was performed.
