# Queued WhatsApp processing and UK premise selection

Implemented 21 October 2026. Both `/webhooks/twilio/whatsapp` and `/api/v1/integrations/whatsapp/webhook` validate the configured canonical Twilio URL, account, signature and every form field before accepting a message. Configure the actual externally reachable URL in Twilio and `TWILIO_WEBHOOK_URL` exactly as before.

## Activation

1. Apply `migrations/043_whatsapp_async_ingress.sql` after 042 through the authorized database migration process. This change does not apply it automatically. With Twilio enabled, startup checks both new tables and fails clearly if they are missing.
2. Retain the existing valid `CREDENTIAL_KEYS` Fernet key ring. Inbound events and outgoing parts can contain email addresses, phone numbers and verification codes; they are encrypted, never logged as raw content. Keep old key IDs while outstanding jobs still use them.
3. Set `IDEAL_POSTCODES_API_KEY` to a licensed Ideal Postcodes key with Royal Mail PAF access. The value is server-only. No private key has been added to `.env` by this implementation.
4. Use existing valid `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER` and `TWILIO_ENABLED`. The account must be allowed to send WhatsApp REST replies; sandbox recipients must remain joined. `WHATSAPP_QUEUE_WORKERS` defaults to 2 and accepts 1–8 workers per process.
5. Restart Uvicorn normally. Workers run in FastAPI lifespan and are cancelled on shutdown. Multiple application instances coordinate through PostgreSQL row locks; no Redis or Celery is required.
6. For native return media, `BOOKING_PAGE_URL` must identify this application's public HTTPS origin. The document endpoint and approved carrier document hosts must be reachable by Twilio. A localhost/private URL will not deliver WhatsApp media.

## Ingress and processing contract

The HTTP path performs bounded signature/form validation and one short database transaction. It encrypts the exact original form bytes, records a SHA-256 digest over all canonical signed field pairs and inserts one queue entry per MessageSid. Reordering equivalent form fields does not change the digest. A repeated SID with different content returns 409; a matching duplicate is acknowledged without another action or send. Successful acceptance returns exactly `<Response/>`; the HTTP response no longer contains quote/onboarding text.

The request has a 450 ms application budget, a 100 ms pool-acquisition limit and short database lock/statement budgets. The target is successful acknowledgement within 500 ms under healthy infrastructure. This is a design budget, not a measured production percentile or a guarantee during network/database cancellation stalls. A failed/timed-out durable enqueue returns 503 so Twilio can redeliver the same SID. No in-memory background task is used to acknowledge work that has not committed.

Workers claim eligible conversation heads with `FOR UPDATE SKIP LOCKED`. Later messages from the same sender/receiver wait while an earlier message is unfinished; different phone threads can progress concurrently. The claim commits before onboarding, PAF, AI, carrier, Stripe or return services run. Identity is resolved from the active phone binding at execution, not from a caller-controlled tenant ID. Original receipt time is used for the inbound service-window timestamp, so a queue backlog does not manufacture a new 24-hour messaging window.

The existing `ConversationStore` scoped UUID and SHA-256 receipt contract remains in force. Draft expiry is still the original fifteen-minute deadline, never refreshed by premise pagination, selection or subsequent replies. An interrupted action is not automatically rerun.

## Address collection

Dynamic WhatsApp quotes with an explicitly confirmed GB country and a UK postcode use the asynchronous `PAFClient` interface. `IdealPostcodesClient` is the supplied implementation: fixed HTTPS origin, server-side authorization header, PAF dataset restriction, bounded pagination, postcode/UDPRN/premise validation and provider-formatted address lines. A future Loqate implementation can satisfy the same interface without changing the conversation controller.

The bot lists eight numbered premises at a time. Reply with a displayed number, `More`, `Back` or `Cancel`. Numeric selection populates `main.Address` using the provider's premise/street lines, dependent thoroughfare/locality lines, post town and normalized postcode. Contact name is collected separately; it is not inferred from a building. Invalid indices, mismatched postcodes or provider outages never create a guessed street. Missing/failed lookup asks for correction/retry or the ordinary web shipment form. Non-GB addresses and the existing web form retain their established collection and validation paths. Existing explicit saved-route quoting remains its separate administrator-configured path; PAF selection does not retroactively certify those stored addresses.

Lookup is a licensed address-data dependency, not proof that a particular carrier accepts a PO box, remote destination, parcel or goods category. Exact provider field mappings follow the [Ideal Postcodes postcode lookup contract](https://docs.ideal-postcodes.co.uk/docs/api/postcodes/). PAF storage and retention must match the operator's licence.

## Outbound replies and QR documents

Replies are split into bounded text parts without breaking URLs and encrypted in `whatsapp_reply_outbox` before transmission. The synchronous Twilio SDK call `Client.messages.create` runs through `asyncio.to_thread`, outside a database transaction and without retaining a pool connection. Automatic SDK retries are disabled. A confirmed carrier QR/paperless document adds a separate outbound `media_url` part, using this application's scoped, signed return-document proxy. Ordinary tracking links, authenticated-only document paths and invented QR images are never treated as media.

The proxy validates the token, original tenant/shipment and approved carrier document host, then serves the actual supported carrier image/PDF. QR availability and eligible drop-off locations remain carrier-specific. No QR yields the existing printable/document-link instructions. Twilio fetches media asynchronously, so public reachability, content type/size and carrier availability still require live acceptance. See the [Twilio Message resource](https://www.twilio.com/docs/messaging/api/message-resource) for the REST `MediaUrl` contract.

## State, failure and recovery

Inbound states are STAGED → PROCESSING → READY → ACCEPTED, with FAILED and REVIEW_REQUIRED exits. Outbound parts are STAGED → SENDING → ACCEPTED, with FAILED/REVIEW_REQUIRED exits. ACCEPTED means Twilio returned a valid MessageSid, not that WhatsApp delivered/read the message. Inspect Twilio messaging logs for delivery failures; the separate proactive support notification callback does not update this new conversational outbox.

SENDING commits before the REST request. A timeout, connection interruption, malformed successful response or uncertain server error is fenced for reconciliation. A definite rejection, including rate limiting, is recorded as FAILED rather than automatically replayed. Completed parts are never sent again. A persisted READY job can resume unsent STAGED parts without executing its action again. A stale PROCESSING/SENDING or REVIEW_REQUIRED job is not automatically reset or leased to a second worker: this avoids duplicate email dispatches, checkout links, carrier purchases and WhatsApp messages.

An unfinished/review job blocks later messages on that phone thread. Operations must reconcile it against conversational/signup receipts, shipments, reservations and Twilio logs before permitting further processing. Do not set PROCESSING back to STAGED or SENDING back to STAGED as a generic fix. Record a positively confirmed Twilio SID/acceptance through an authorized, audited maintenance process; if the send cannot be confirmed, escalate rather than silently resend. No new public reset/retry endpoint is exposed. Messages older than 23 hours 59 minutes fail the free-form send window check instead of generating an unsolicited template-free reply.

These server-only tables have RLS enabled and no anon/authenticated grants. They are operational inbox/outbox records, not a public transcript. Operators must define and execute a retention policy covering encrypted payloads (including OTPs), terminal receipts, review records and licensed address snapshots. Preserve outstanding receipts/keys required for reconciliation and never export raw payloads into a support log.

## Verification scope

Tests use synthetic identities, isolated services, fake database connections, mocked Twilio REST and HTTPX PAF responses. They cover signed empty acknowledgement, bounded enqueue failure, duplicate/conflicting messages, encrypted storage, premise mapping/selection/pagination, immutable draft expiry, gateway receipt replay, REST media arguments, definite/uncertain sends, service-window expiry and READY-part recovery. They do not apply SQL or demonstrate live PostgreSQL contention, production latency, Royal Mail licensing, carrier purchase or WhatsApp media delivery. Those are explicit staging acceptance gates before rollout.
