# Operations runbook

Use an authorized development/sandbox environment for integration setup and mutation testing. Application startup, a passing unit suite and a provider accepting an email are separate checks. Record the exact application revision, migration state and environment before diagnosing an incident.

## Local startup

From `C:\Projects\veloce-ai` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` and check `/health`. Use module import mode so the entire main.py module and its late router registrations are loaded before startup. The legacy direct `python main.py` path starts its runner before some later router registrations; it is not the preferred complete application startup command.

For an isolated local preview with the full module import order:

```powershell
.\.venv\Scripts\python.exe -c "import sys, uvicorn; sys.argv.append('--local-preview'); uvicorn.run('main:app', host='127.0.0.1', port=8000)"
```

Preview is sample UI/logic, not evidence of real database, wallet, payment or carrier success. Do not pass `--local-preview` directly to the uvicorn command parser. The optional `serve_frontend.py` serves only allowed UI routes on 5500 and avoids exposing the project directory; the SPA routes API calls from that port to loopback 8000. Never use a generic directory server at the project root that could serve `.env` or exports.

## Port and process diagnosis

`WinError 10048` means the listening address/port is already occupied, often by the first backend instance. It does not mean the application needs a different Twilio endpoint. Identify the listener without terminating unrelated processes:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess
Get-Process -Id <OwningProcess-from-the-previous-command>
```

Keep the intended existing server or stop that identified development instance with Ctrl+C in its own terminal. If you deliberately change the server port, also update the tunnel target and applicable local origins. A log line like `127.0.0.1:59164 - GET /health 200` shows the caller’s ephemeral source port, not a changed server listening port.

For startup failures, collect the exception preceding “Application startup failed,” not only that final line. Do not paste a full `.env`, access token, database URL or provider body. Missing schema, DB role capability, TLS, malformed JSON configuration and optional-provider configuration are different diagnoses.

## Configuration reference

[configuration.json](configuration.json) and [configuration_reference.md](configuration_reference.md) list source-declared settings/types/default expressions and variable names from `.env.example`. They never publish private `.env` values. Field defaults are not deployment instructions to enable every feature.

| Group | Required setup/activation |
| --- | --- |
| Core database/Auth | Supabase URL and appropriate publishable/server keys; DATABASE_URL; approved CA/TLS mode; server Fernet CREDENTIAL_KEYS; approved baseline schema and migrations; AUTH_JWT_SECRET for app sessions |
| Browser identity | FRONTEND_ALLOWED_ORIGINS, JWT algorithm/audience, correct password-recovery origin, platform-admin Auth ID allowlist |
| Carrier accounts | Approved canonical provider origin, encrypted real key/account credentials, environment, tenant account access, timeout and exact approved document hosts |
| Spending | PROVIDER_ENVIRONMENT, DATABASE_ENVIRONMENT, tenant sandbox flag and AUTOMATION_PURCHASE_ENABLED must satisfy native guards |
| Stripe | STRIPE_ENABLED, correct mode/key, signing secret, success/cancel URLs, verified webhook destination and adequate DB pool capacity for card checkout |
| WhatsApp | TWILIO_ENABLED, account/token/number, exact public TWILIO_WEBHOOK_URL, sandbox pairing where applicable; BOOKING_PAGE_URL and strong QUOTE_LINK_SECRET for links |
| Signup/email | WHATSAPP_ONBOARDING_ENABLED and limits; Supabase email OTP/signup settings; custom SMTP/approved sender; OTP/reset templates; recovery allowlist |
| Stores | Encrypted store connections or approved legacy ECOMMERCE_CONNECTORS, real platform authorization, SKU weights when missing, explicit import/delivery/live_returns controls |
| Tracking/support | Native provider settings or valid tenant-bound TRACKING_WEBHOOK_KEYS; notification controls, approved recipient/consent, template/status URL where needed |
| AI | LOGISTICS_AGENTS_ENABLED plus OPENAI_API_KEY; bounded model/embedding/time/concurrency/token/cache settings |
| Insurance/claims | Real XCover product/key/signature/contract/pricing verification; separate XClaim credentials, approved FNOL/settlement mappings and payout identity |
| CRM | Optional HubSpot credentials, expected portal/environment, signed app subscription and stage mappings for provisioning |
| Research utility | COMPANIES_HOUSE_API_KEY only for manually invoked company-level research; no app-startup requirement |

If TRACKING_WEBHOOK_KEYS is malformed, the legacy receiver is deliberately disabled. Valid native encrypted provider configurations can still be available. Correct the JSON/key map for that receiver instead of disabling signature or tenant verification globally.

## Database deployment

Obtain the authorized baseline before creating a new database. Inspect current migration history and backup/rollback policy; apply checked-in migrations in sequence through 042 using approved operational access. Several numbered scripts alter privileged functions, policies, triggers and role grants. Do not assume a file named apply/seed/verify is read-only.

No documentation rebuild applies migrations. The startup table checks are readiness checks rather than a migration runner. If a feature reports “Apply migration 038/042,” confirm its exact schema and privileges in the intended database rather than testing against a live company workspace by accident.

## WhatsApp and email validation

1. Run the configured backend on 8000 and verify health.
2. Start your approved public HTTPS tunnel to that port. In ngrok, `http://127.0.0.1:4040` is the local inspection interface. The forwarding `https://...` origin is what Twilio needs; verify the running tunnel’s actual public URL rather than reusing a stale hostname.
3. Set TWILIO_WEBHOOK_URL to `PUBLIC_HTTPS_ORIGIN/api/v1/integrations/whatsapp/webhook` and save that exact URL as the inbound messaging webhook in the configured Twilio sandbox/sender. Signature verification depends on matching it exactly. Restart after configuration changes.
4. Set BOOKING_PAGE_URL to the public dashboard root served by this app, not the webhook path. A localhost URL in a phone message points to the phone itself.
5. Pair the phone with the current sandbox join code shown by Twilio. The sandbox’s “all set” reply proves pairing, not application webhook delivery.
6. Send Register. Verify persona collection, business-only fields, email dispatch, separate phone code, correctly formatted `EMAIL_CODE PHONE_CODE`, and final provisioning/password email.
7. For an already registered phone, request a quote, supply real missing values, check available choices, and use Book option N to open authenticated web review/payment. Top-up and return tests require deliberate sandbox authorization.

In Supabase Auth, configure the production custom SMTP relay using the approved SendGrid credentials/sender and domain records. Publish the repository OTP/reset templates in their matching Auth template slots. The application does not send a competing email OTP directly through SendGrid. Inspect delivery records/recipient inbox separately from API acceptance.

The email OTP may contain six to ten digits; the separate WhatsApp code is exactly six. Enter the email code first, then a space, then the phone code in WhatsApp. Requesting Resend replaces the active phone challenge and has a one-minute cooldown, three-send budget and five verification attempts; use the latest matching pair. Do not delete an existing Auth identity just to reuse an email. Unverified/stale registration rows, an existing real membership and uncertain verification are handled differently by the signup engine.

## Rate incident investigation

Collect the sanitized quote/request reference, tenant/environment, timestamp, route countries/postcodes, measured dimensions/weight, currency, cargo and returned diagnostic code. Do not include bearer credentials. An empty rate set can be caused by disabled connections, wrong mode/key, unsupported cargo, an ineligible route, currency, size/weight or provider rejection.

Inspect the configured connections and their read-only verification/diagnostic endpoints, native availability notices and sanitized provider issues. A 422 is a request-schema problem; it is not evidence that an aggregator lost its connection. A 503 is not enough to identify a provider; inspect the processing/support diagnostic. A valid quote is not proof a label can be purchased.

If freight says the parcel integrations cannot quote it, keep the exact measurements, lane and stackability and use manual freight/support intake. Do not relabel freight as a parcel, bypass dimensions or invent a tariff. The support team needs a contracted freight provider/manual quote process before offering a live road/sea service.

## Booking and payment incidents

Before retrying, identify shipment, selected offer, order idempotency key, wallet reservation, payment cart/top-up and native provider reference. Check whether the reservation was submitted, captured or released. Never infer “nothing happened” from a popup closing or a network timeout.

| Symptom | Investigate/action |
| --- | --- |
| Carrier unavailable, credit released | Confirm a definitive rejection/released reservation; request fresh quotes and a permitted alternative |
| Outcome uncertain/reserved credit retained | Reconcile the original native ID with existing GET/polling tools; do not buy or release again |
| Stripe window closes/no payment UI | Check returned checkout error/URL, mode alignment, basket bookability, request receipt and Stripe event/cart state |
| Payment verified, some labels fail | Inspect the existing basket and shipments; unused credit remains in wallet, not an automatic bank refund |
| Expired/changed offer or rotated connection | Requote with current configuration before any new payment/purchase |
| ORDER_SERVICE_FAILED/processing failure | Inspect the support/automation failure code and native service readiness; it is not proof the account is merely “not live” |

Cancellation and refund require the existing verified provider/financial lifecycle. Support must not fix an uncertain purchase with direct wallet SQL or by deleting the idempotency receipt.

## Returns operation

Save a default active RETURN address, enable eligible return connections and apply 042. Use Create return in the manifest or the authenticated API. Arrays contain a stable UUID per intended full-parcel return; optional maximum_price is an exact decimal string in the original quote currency. Inspect every batch result and the booked/payment/review counts.

For CUSTOMER_PAY, an OWNER/ADMIN creates the Stripe link; the customer pays there before a label is bought. RETAILER_PAY uses normal workspace billing. A response with PAYMENT_REQUIRED is not a booked return. Use the authenticated return-status endpoint to observe the existing request and any completed card booking.

A receipt fences one full-parcel return per original shipment even after a failure. Correcting a warehouse or configuration does not authorize clearing a receipt/retrying a purchase. Support must inspect whether any return shipment, reservation, cart, native purchase or optional form request exists and reconcile the existing preparation through approved tooling. There is no blanket automatic retry/reset endpoint in the current headless contract.

If no paperless document is confirmed, print the carrier label. Do not tell a consumer to present an ordinary tracking URL as a QR code. Shared links require the configured public app origin/secret and approved source host, expire after 24 hours and grant only the document. Carrier locations/rules still apply. Optional USPS form failure retains the paid label; GET status can recover the form without another POST.

Enable signed return requests per store before connecting a merchant/marketplace gateway. The gateway must submit the reviewed normalized command array and proper timestamp/HMAC; a platform refund or return request event is not automatically an authorized carrier purchase.

## Claims, support and synchronization

Check policy confirmation and role before claiming coverage. CLAIM_INGESTED is support intake, not insurer review. Review evidence state, provider reference and submitted fence before filing/replaying. Verified settlement needs authoritative payment details before the existing wallet-credit method runs.

For missing store updates, inspect active connector authorization, original store/order identity, outbox state and required native reference. Return delivery must not be marked as ordinary fulfillment. For missing alerts, inspect verified recipient, consent/binding, service window/template, outbox state and provider delivery receipt rather than directly sending a duplicate message.

Dispatch sockets authenticate through the first JSON message, not URL query tokens. If the dedicated database listener reconnects or a queue overflows, clients receive refresh_required; HTTP refresh remains the fallback. A websocket disconnect/heartbeat is not a shipment failure.

## Shutdown and change management

Stop the intended development server with Ctrl+C; lifespan cancels workers and closes clients/pools. A cancelled local coroutine does not undo a provider-side mutation. Review durable submitted/processing states after interruptions. Rolling out credentials, migrations or new pricing requires the existing compare/version/audit safeguards and an explicit deployment plan.

Keep source documentation, generated references, diagrams and the ZIP synchronized with the generator. Follow project AGENTS.md for authorized checks/commits/pushes. Git synchronization alone does not authorize production deployment or database changes.

## WhatsApp inbox/outbox activation and incident handling

Apply 043 after 042 through the authorized migration process. Configure a valid CREDENTIAL_KEYS ring, normal Twilio account/token/number/canonical webhook URL, and a licensed IDEAL_POSTCODES_API_KEY for dynamic UK chat addresses. WHATSAPP_QUEUE_WORKERS defaults to 2 (1?8 per process). Restart the application; no separate Python worker command is needed. Do not apply SQL or charge/send anything merely to regenerate documentation.

Successful inbound HTTP now returns exactly `<Response/>`. Check whatsapp_inbound_queue and whatsapp_reply_outbox states plus Twilio logs for the actual reply. Missing tables prevent Twilio-enabled startup. Failed enqueue returns 503 for same-SID redelivery. Inspect thread ordering: unresolved PROCESSING/SENDING/REVIEW_REQUIRED blocks later messages for that sender/receiver. Never reset these states or blindly resend; reconcile action receipts, reservations/shipments and outbound SIDs through an authorized audited process. ACCEPTED means REST acceptance, not device delivery. READY can resume only unsent STAGED parts.

For PAF failures, check licence/key/account availability without logging the secret. Confirm complete postcode/country and select from the presented list. No manual street fallback is manufactured in dynamic GB chat. Preserve the configured fifteen-minute draft deadline. Public HTTPS BOOKING_PAGE_URL and approved document hosts are required for Twilio QR image/PDF fetching; a localhost dashboard cannot serve media to Twilio. Proactive support-notification delivery remains a separate outbox/callback contract.

## EOD and paperless media rollout

If 044 reports `public.whatsapp_reply_outbox` missing, check that **both**
`public.whatsapp_inbound_queue` and `public.whatsapp_reply_outbox` exist in the
selected Supabase project. Both are installed by the complete
`043_whatsapp_async_ingress.sql` after 042. If neither exists, apply 043, then
rerun the complete corrected 044. A single queue or incompatible schema indicates
partial installation: preserve receipts and compare/repair against 043 rather
than creating an empty replacement table. Corrected 044 checks baseline tables,
column types, unique keys, queue FK and RLS before changing the shipment enum.
The original failure rolls back 044's second transaction; an earlier committed
MANIFESTED enum value may remain and is safe to retain for retry.

Apply the complete 044 script after 043 without an additional outer transaction. Its explicit enum transaction commits before using MANIFESTED. Install updated requirements including PyMuPDF. Confirm private default Storage bucket/policy, valid server-only Supabase service key, approved document hosts, public HTTPS app origin and quote-link signing secret. Configure equivalent policies separately for a custom bucket. Twilio-enabled startup checks the new schema; native media automatically sets /api/v1/integrations/whatsapp/outbound-status/{part_id} on the configured public origin. The Twilio-only local ingress forwards this callback.

Use POST /api/v1/dispatch/manifests/preview, then close with a stable request_id, carrier_account_id and any required carrier_code/warehouse_id. GET /{id} retrieves status/reconciles a known native reference without another POST. Authenticated /{id}/document and signed /{id}/download serve completed PDFs. Live mutations require LIVE database/provider alignment and enabled purchase controls. Internal handover sheets do not replace mandatory carrier paperwork or schedule pickup.

For uncertain submissions, reconcile the manifest and exact member labels against provider records before any maintenance. Do not clear manifest_id or replay a close request as a generic fix. FAILED membership is retained for reviewed remediation. Preview remaining bookings after a 1,000-shipment batch. For media incidents, inspect private bucket visibility, asset/hash/path, viewing link, Twilio SID and signed callback status. Uncertain sends require evidence; a definitive failed image may stage one text fallback. Never retry the original booking or refund it because a document/message failed.

## Tracking 2.0 rollout

Read [the full implementation and rollout guide](https://github.com/sync4ai-lab/veloce.ai/blob/c5b7b15/docs/tracking_2_implementation.md). Apply complete migrations 043, 044 and then 045 to the intended database only after backup/staging review. Set BOOKING_PAGE_URL to the actual HTTPS application origin for customer links, not a webhook-only tunnel. TRACKING_POLLING_ENABLED=false is the safe default. Enabling reconciliation requires an active supported account and verified read entitlements; start with the default six-hour cadence, inspect health/dead jobs and reconcile provider limits before retrying. Native asyncpg contention and actual provider delivery remain staging acceptance work.

## Manifest status and action troubleshooting

See [the workflow audit and operating guide](https://github.com/sync4ai-lab/veloce.ai/blob/main/docs/manifest_workflow_audit.md). Imported means order data imported into EasyInvio, not customs import clearance. The quote default is QUOTE_TTL_SECONDS=300; carrier contract validity can differ. Restart and refresh after frontend changes; no additional migration is required for the manifest fix. Never copy a shipment with unresolved reserved/submitted funds or an uncertain carrier transaction to repeat the purchase. Keep carrier-issued PDFs and native paperless QR assets where supported; never replace them with an invented barcode.
