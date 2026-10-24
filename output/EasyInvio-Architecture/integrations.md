# Integrations and capability boundaries

This catalog separates SDK versions, API contracts and deployment activation. Local package versions are in [versions.json](versions.json); carrier/service availability is a property of the connected account, contract, route, dimensions, goods and environment. A quote is not a guarantee that the same connection may purchase a label.

## Carriers and aggregators

Royal Mail and Evri direct adapters are disabled extension provisions, not certified
wire integrations. Issued carrier API specifications and tested lifecycle bridges
are still required. See `docs/direct_carrier_provisions.md`
in the repository for the readiness boundary. All new provider work has
`INTEGRATION_*_ENABLED` controls; existing aggregator defaults remain enabled,
direct defaults remain disabled. Historical read-only reconciliation stays available.
Direct-first routing has a 2.2-second primary budget; aggregators retain uncovered
services, with exact native duplicates filtered from the offers. Equal-price
consolidation favors registered direct sources. No guessed OAuth/rates endpoint
or negotiated carrier price is enabled.

| Integration | Implemented path | Activation and limits |
| --- | --- | --- |
| EasyPost | Native quote/shipment/order lifecycle, selected-rate buy, retrieve/refund, tracking/forms, measured parcel/multi-piece and reviewed customs mapping; native returns | Canonical `https://api.easypost.com/v2`, account credentials and verified remote test/production mode; return shipment/rate must be freshly quoted |
| Sendcloud v3 | Dynamic shipping-option prices, native shipment/return announcement and document retrieval, cancellation request/status, supported customs/order workflows | Canonical `https://panel.sendcloud.sc/api/v3`, public/secret credentials, real contract/option eligibility; ordinary TEST mode cannot purchase billable labels |
| Sendcloud legacy pricing | Existing configured v2 method/limit price path | A compatibility path, not the preferred contract for new integrations; method limits/prices are not invented |
| Shippo | Native token-authenticated quotes, transactions, retrieved label status/refunds and supported returns/customs | Canonical configured endpoint and correct test/live token; native return carrier allowlist and cargo limits apply |
| Regional connections | Existing validated configurable regional rate strategy/registry | No generic assumption of purchase, industrial freight, letter, return or document support without its registered native adapter |

The registry reports capabilities, but the exact provider response and environment still determine bookability. Native parcel adapters do not establish universal road, sea, pallet or oversized freight booking. A manual freight/parcel help request preserves measurements and opens a support workflow instead of inventing a wholesale tariff.

### Paperless returns

Sendcloud rate discovery retains `functionalities.labelless`. A requested paperless return uses `delivery_option=drop_off_labelless` only when the chosen option explicitly supports it. Returned delivery option and actual document determine paperless availability. Printable services remain printable; a carrier QR or labelless label is not synthesized from a tracking URL.

EasyPost USPS Label Broker requires an enabled USPS Returns program. After confirmed purchase, the integration requests `/shipments/{id}/forms` with `form.type=label_qr_code`. This is not a universal `generate_qr_code=true` option. The optional POST is durably fenced; a timeout preserves the purchased label and later GET can retrieve the appended form. FedEx/Canada Post/other QR programs are not automatically implemented by the USPS path.

Shippo and other unsupported QR programs retain printable fallback. A paperless document can only be used at eligible locations for the selected service; it is not an assurance that every post office or depot will accept it.

## Storefronts and marketplaces

Store configuration lives in tenant-bound encrypted workspace connection envelopes, with legacy server connector settings as a compatibility source. Public settings reveal capability/configuration presence rather than private keys. Credentials, seller authorization, live import/delivery/return flags and active operator membership are independent controls.

| Channel | Intake/sync | Signature or authorization | Specific boundary |
| --- | --- | --- | --- |
| Shopify | Signed order create/paid webhooks, supported read-only order retrieval, opt-in native fulfillment and reverse-delivery tracking | Shopify HMAC over exact request body plus canonical shop-domain/topic checks; stored access/app credentials | Return tracking requires a verified ReverseFulfillmentOrder reference and correct quantities; a return must not fulfill the outbound order |
| WooCommerce | Signed supported order webhook normalization and verified SKU weight lookup | WooCommerce body HMAC/topic checks | No universal native return/RMA/refund lifecycle is inferred |
| Amazon | Signed normalized gateway plus implemented authorized seller notification/order intake using configured marketplaces/region/credentials | Gateway HMAC/timestamp or the explicit native seller intake contract | An arbitrary JSON notification is not proof of SP-API authorization; no universal Amazon return approval is supplied |
| Manual/CSV | Reviewed orders, source references, row-level errors, measured packages | Workspace JWT/role and schema checks | Import/quote creates no booking; ambiguity is returned for review |
| Normalized reverse gateway | Same ReturnCommand array for merchant and marketplace backends | Enabled `live_returns`, active configured dispatch member, per-store HMAC/timestamp | This is an explicit reviewed return command contract, not an automatic refund-to-label conversion |

The normalized return endpoint is `/api/v1/integration/return-webhooks/{store_id}`. Its signing bytes are `timestamp + '.' + store_id + '.' + exact_body`, using UTF-8 and the saved webhook secret with HMAC-SHA256 hex output. Headers are X-EasyInvio-Timestamp and X-EasyInvio-Return-Signature; timestamps expire after five minutes. Each body is a bounded array of stable request IDs. Customer-paid checkout requires the configured real role OWNER/ADMIN.

Outgoing store tracking uses durable outboxes. Return quantity/reference and return lifecycle are preserved; unsupported delivery updates remain held for review. Native marketplace return approval, merchant refunds, restocking and exchanges are separate product capabilities.

## Stripe payments

`FinanceEngine`, `payment_gateway.py` and `card_checkout.py` use Stripe Checkout and verified snapshots/webhooks for wallet funding and exact selected-offer card baskets. STRIPE_ENABLED, secret/webhook keys, livemode, return URLs and the existing database/payment mode checks control activation. The SDK version and configured Stripe event/API behavior are different facts; event payload variants are handled by the existing snapshot reconciliation contract.

A client popup or redirect is only navigation. Verified payment precedes credit and eligible label purchasing. Check the cart/top-up receipt before retrying. TEST/LIVE mismatches, wrong amounts/currency and uncertain provider outcomes remain blocked/reviewable. Customer-paid returns use a Stripe link, not a silent debit to the retailer wallet.

## Twilio and conversational ingress

Twilio posts to `/api/v1/integrations/whatsapp/webhook`. RequestValidator verifies the signature against the exact configured public URL, account and request values. `TWILIO_WEBHOOK_URL` includes that endpoint; `BOOKING_PAGE_URL` is the separate dashboard origin for handoff links. An ngrok localhost inspection URL is not the public forwarding URL.

After signature validation, both WhatsApp webhook URLs commit an encrypted raw event to the migration 043 inbox and return empty `<Response/>`. A 450 ms application budget targets acknowledgement below 500 ms under healthy infrastructure; production percentiles need staging measurement. Carrier/onboarding/agent calls run in lifespan-owned `WhatsAppQueue` workers, not in the webhook. SQL row locks and unique MessageSid enforce ordered per-phone processing and duplicate/conflicting-content handling. Canonical SHA-256 covers all signed field pairs; the existing scoped conversational receipt remains unchanged.

Registered senders resolve through active bindings and real membership when a worker executes. Unregistered senders enter opt-in onboarding when enabled. Reply parts are encrypted and staged before a Twilio REST call in `asyncio.to_thread`; automatic SDK retries are off. SENDING/PROCESSING and unknown outcomes are fenced for reconciliation. ACCEPTED records REST acceptance, not delivery. READY can resume unsent parts without replaying the action. Original ingress time governs the free-form messaging window.

Confirmed paperless returns attach a separate `media_url` using the same shipment's signed public HTTPS document proxy. No QR means printable/link fallback. Twilio must reach the public proxy and receive a supported real carrier image/PDF; delivery, file-size and account restrictions still need live acceptance.

### Licensed UK address lookup

`PAFClient` is the asynchronous adapter boundary; `IdealPostcodesClient` uses a fixed HTTPS endpoint, server-only `IDEAL_POSTCODES_API_KEY`, PAF dataset filtering and bounded postcode pagination. Dynamic GB WhatsApp quotes present eight premises per page, accept a displayed number/More/Back, preserve provider-formatted lines and post town, then collect the contact name. Failed/unconfigured lookup never inserts a guessed UK street. POST /api/v1/addresses/uk/lookup exposes authenticated PAF premise selection to web pickup/delivery fields. UK full-address matching also runs server-side before quotes and new label purchases, including returns and saved offers. LIVE has no unverified UK fallback; TEST without a key permits synthetic fixtures. Non-GB addresses are not certified by PAF. The complete pagination call has an eight-second deadline. PAF access/licensing and retention are operational prerequisites, not carrier eligibility guarantees.

Outbound support WhatsApp delivery is independently gated by SUPPORT_WHATSAPP_ENABLED, verified recipient/consent and either the supported recent inbound service window or approved template Content SID. Returning TwiML to a user’s inbound message does not authorize unsolicited outreach campaigns.

## Supabase Auth and SendGrid

The application calls Supabase Auth’s OTP, verify, password/session and recovery endpoints. The project’s Auth SMTP configuration relays email through SendGrid with the approved sender (the configured operational setup uses operations@easyinvio.com). SMTP server credentials and sender/template configuration belong in Supabase Auth/secret management, not in a second local OTP generator or browser script.

Use the maintained verification and reset templates in `docs/identity/email_templates`. Email OTP length is accepted from six to ten digits; the separate application WhatsApp code is six digits. Email delivery acceptance is not proof of inbox delivery. Unverified identities can exist temporarily in Auth while the workspace remains unprovisioned; email collision/reuse handling must preserve identity ownership, not delete/claim an arbitrary Auth account.

Recovery redirects must be allowlisted and point to the deployed SPA route that understands the fragment/token contract. `localhost:3000` only works if that user’s computer is serving the app there. A safe local configured origin is the actual Uvicorn/dashboard address, not a port guessed from another framework.

## UK tariff search and customs

`customer_checkout.search_tariff` calls the UK Integrated Online Tariff search at `https://www.trade-tariff.service.gov.uk/api/v2/search`, returns normalized official candidates/source URLs and asks clarification for ambiguous goods. Product classification lookup reuses it. Optional AI ranking is constrained to returned candidates; the separate local curated dictionary is not an official worldwide HS database. Destination requirements and final classification remain reviewed shipment facts.

## XCover and XClaim

`shipment_protection.py` separates a deterministic price estimate from provider quote/policy booking. XCOVER_ENABLED, TEST/LIVE environment, real partner/API/signing credentials, verified parcel contract and verified retail pricing must be ready before protection is available. Supported territory, product, currency, goods and timing come from the contracted program, not marketing copy.

`xcover_claims.py` uses separate XClaim program credentials and token/signature handling. It supports configured first-notice-of-loss mapping, evidence upload, creation, GET reconciliation/webhook intake and settlement-source validation. FNOL/settlement mappings must match partner-authoritative fields; unknown fields are not guessed. An approved claim status alone is not proof that the master account received settlement. Wallet payout uses verified payment/currency/reference/payee/receipt/time and an idempotent credit path.

Conversation intake records CLAIM_INGESTED plus an OPEN support ticket after policy/role checks and sends the authenticated evidence-panel link. It does not directly authorize insurer submission or issue money.

## HubSpot CRM

Configured HubSpot integration supports verified account/portal checks, durable CRM synchronization, selected activation/metrics and signed Closed Won provisioning workflows. Private access tokens are account credentials, not intrinsically sandbox keys. HUBSPOT_ENVIRONMENT and expected portal must match the approved account; provisioning additionally requires the app subscription, secret/app identity, exact public URL and selected stage mapping.

Optional upsell stages/pipeline settings do not permit invented deals or promises of customer savings. HubSpot startup/configuration failure can disable optional CRM without granting an alternate onboarding permission. Inspect the CRM outbox before replaying any mutation.

## Companies House research

`backend/tools/sme_lead_scraper.py` is manually invoked, outside the application request lifecycle. It queries the official public-data API with active-company, outward postcode district and SIC filters; default hubs are TW6 and M90. It applies de-duplication, bounded pagination/request pacing and explicit truncation reporting.

COMPANIES_HOUSE_API_KEY authenticates that optional research, not shipping or signup. Exports are company-level candidates requiring review. A registered office does not prove an operating warehouse, volume, SME size or trade corridor. China/India corridor evidence must be supplied as explicit company-level declarations for review, not inferred personal nationality. The utility produces unsent drafts with recipient unset, messages_sent=0 and wallet_changes=0; a proposed demo balance is illustrative, not live funds. Do not commit its real prospect exports.

## Contract references

The source modules retain the implemented API contracts. External contract changes require fresh verification before updating adapters: [EasyPost forms](https://docs.easypost.com/docs/shipments/forms), [USPS Label Broker](https://support.easypost.com/hc/en-us/articles/4410441700493-Generate-USPS-Label-Broker-QR-Codes), [Sendcloud returns](https://sendcloud.dev/docs/returns), [Companies House API](https://developer.company-information.service.gov.uk/), [Supabase Auth](https://supabase.com/docs/guides/auth). These links are references, not a statement that every external service/version was live-tested during documentation generation.

## Manifest provider contracts and QR Storage

EasyPost manifest creation uses the documented top-level shipments array at POST /v2/scan_forms. Same origin/carrier account, permitted label date and carrier support remain provider requirements. A created form must match the exact tracking set and supply an approved PDF. A stored sf_ reference supports subsequent GET recovery; timeout never authorizes another POST.

A generic Sendcloud /api/v2/manifests contract is not established by the current public catalog. Sendcloud and unsupported regional/direct connections therefore produce INTERNAL_HANDOVER paperwork with carrier_closed=false. Official carrier-required closure must still be completed through the verified panel/contract-specific workflow; the application does not invent that API or call internal paperwork carrier acceptance.

Supabase Storage supplies private image persistence/read signing with the existing server service key, under LOGISTICS_MEDIA_BUCKET (default easyinvio-logistics). SVG/PDF may be rasterized to PNG using PyMuPDF; PNG/JPEG is decoded/re-encoded with Pillow. Native media sends include the canonical outbound-status callback. Definite format rejection and signed failed/undelivered media status create a unique text-only viewing-link fallback; a timeout alone does not. Proactive support notifications remain separate.

## Tracking capability registry

EasyPost supports installed signed webhooks and optional GET-only retrieval of existing shipment/tracker resources; reconciliation never creates a billable tracker. Sendcloud and Shippo retain verified webhook normalization; arbitrary polling is explicitly unsupported. Royal Mail/Evri direct transports remain disabled provisions, not certified live integrations. The capability API separates installed support, connection activation and environment; contract fees/quotas remain unknown unless verified. New milestone availability is in-app only: paid WhatsApp/SMS/email campaigns are not activated.


### Sender transactional milestone channels

`backend/shipment_notifications.py` owns `SenderNotifications`, `ShipmentNotificationSettings` and `ShipmentNotificationWorker`. SendGrid uses the Mail Send API with separate `SHIPMENT_SENDGRID_API_KEY` and a verified `SHIPMENT_EMAIL_FROM`. Twilio uses existing account/sender credentials plus an approved `SHIPMENT_WHATSAPP_CONTENT_SID` (utility variables: booking reference, milestone text, tracking reference). There is no free-form out-of-window fallback. `SHIPMENT_NOTIFICATION_TEST_RECIPIENTS` restricts TEST sends; outbox environment and runtime environment must match. Both delivery flags default false. These settings do not activate return-customer notifications or change in-app tracking preferences.

`047_sender_shipment_notifications.sql` adds the private status-only outbox and transactional triggers. It stores no recipient addresses or message bodies. The authenticated `GET /api/v1/shipping/{shipment_id}/sender-notifications` reports only the current workspace's outcomes. ACCEPTED is provider acceptance, not proof of delivery. Missing/disabled configuration is SKIPPED, explicit refusal is FAILED, and ambiguous outcomes require review. See `docs_shipment_updates.md` for setup and limitations.
