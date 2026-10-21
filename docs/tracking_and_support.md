# Tracking, delivery proof and support

Module: `backend/tracking_and_support.py`. Migration 011 has been applied to the currently configured Supabase sandbox. It adds delivery-proof metadata, tenant/account tracking lookup indexes, durable tracking receipts, support tickets and a WhatsApp staging outbox. The SQL file can also be applied elsewhere; execute its enum DO block separately before the main transaction if your editor wraps scripts in one transaction.

## Configure an aggregator adapter

Set server-only `TRACKING_WEBHOOK_KEYS` in `.env` to a JSON object such as:

```json
{
  "carrier-adapter-1": {
    "tenant_id": "YOUR_TENANT_UUID",
    "carrier_account_id": "YOUR_TENANT_CARRIER_ACCOUNT_UUID",
    "secret": "YOUR_RANDOM_SIGNING_SECRET_AT_LEAST_32_BYTES",
    "pod_allowed_hosts": ["proof.your-carrier.example", "your-approved-storage.example"]
  }
}
```

Use an independent random secret for each integration; do not use Supabase or provider API keys as signing secrets. The default configuration is empty, so unsigned/unconfigured callbacks are rejected. Restart the backend after configuration changes.

If startup reports `Invalid TRACKING_WEBHOOK_KEYS JSON`, check this optional
legacy setting. When using native encrypted provider connections instead of a
custom normalized webhook adapter, set `TRACKING_WEBHOOK_KEYS={}` in `.env` and
restart the backend. This explicitly disables only the legacy receiver; it does
not configure or disable native carrier webhooks. A plain API key or signing
secret is not a valid value for this setting: an enabled legacy receiver needs
the complete tenant/account-bound JSON map above. Do not invent tenant IDs or
weaken signature validation to remove the warning.

`POST /api/v1/tracking/webhook` accepts the following normalized JSON:

```json
{
  "event_id": "provider-event-123",
  "tracking_number": "YOUR_TRACKING_NUMBER",
  "status": "EXCEPTION",
  "occurred_at": "2026-10-10T12:00:00Z",
  "raw_error": "Customs clearance requires additional documentation"
}
```

The sender supplies `Content-Type: application/json`, `X-Veloce-Key-Id`, `X-Veloce-Timestamp` (Unix seconds), and `X-Veloce-Signature`. Compute the signature as lowercase hex HMAC-SHA256 of `timestamp + "." + key_id + "." + exact_raw_request_body`, using the configured signing secret. Timestamp tolerance is five minutes. All three authentication headers must occur exactly once; payload limit is 64 KB. Each provider must verify its native webhook and normalize/sign this payload through its adapter. This endpoint does not claim compatibility with an unsigned/native EasyPost or regional payload; provider wire formats and authentication differ.

Tenant and account come from the signing-key configuration, never request JSON. Shipment lookup checks both values plus tracking number. Missing or ambiguous matches fail closed. Event IDs are deduplicated within tenant/key; conflicting bodies return 409. Older/equal timestamps are recorded but do not regress state, and DELIVERED cannot regress to an exception. Existing shipment statuses must represent a confirmed carrier booking/dispatch. The listener makes no carrier purchases.

For a DELIVERED event, add `proof_of_delivery_url`. Only exact configured HTTPS hostnames on port 443 are accepted; credentials, IP-literal hosts and fragments are rejected. The URL is stored in `shipments.proof_of_delivery_url`, not fetched, downloaded or made public by this service. Use access-controlled storage and an appropriate retention policy; signed URLs may expire and require a provider refresh. The original proof is retained when a delivered update has no new URL.

## Proactive support

An accepted EXCEPTION queues work in the same database transaction as the status update. The background worker processes up to 50 receipts per transaction using `FOR UPDATE SKIP LOCKED`, so restarts and concurrent workers do not lose or duplicate tickets. Its preconfigured prompt documents the safe behavior; the current implementation uses a deterministic mock-AI classifier, clearly recorded as `DETERMINISTIC_MOCK`, rather than claiming an external model was called. It classifies customs, address, weather and failed-delivery errors without echoing arbitrary carrier instructions or inventing delivery promises.

Each event creates a tenant/shipment-scoped `support_tickets` row containing a remedy. For active OWNER/ADMIN WhatsApp bindings in that same tenant, `support_message_outbox` receives deduplicated `TWILIO_WHATSAPP` messages in STAGED state. This is a durable hand-off for an outbound Twilio sender; this implementation does not transmit messages. Your Twilio integration remains disabled, and automatic transmission would require an outbound sender plus a valid WhatsApp conversation window or approved template. No phone numbers are inferred from shipping addresses. Delivery resolves open tickets and cancels unsent staged messages. Delayed ticket work for an already delivered shipment creates a resolved ticket without a notification.

Tables are private to server roles; direct browser grants are revoked. Delivery-proof mutation is guarded against browser writes. Inspect tickets and staged messages in your Supabase SQL editor; no public ticket read/write API was requested or added.

## Financial reports

`GET /api/v1/analytics/reports?start_date=2026-10-01&end_date=2026-10-31&page=1&page_size=100` requires your tenant's OWNER, ADMIN or ACCOUNTANT JWT. A request cannot select another tenant. The date range is inclusive UTC, at most 367 days; payment pagination is capped at 500 rows per page. Use `has_more` to retrieve all pages.

Shipping volume sums `parcel_count` for shipments booked within the range that are BOOKED, DISPATCHED, IN_TRANSIT, EXCEPTION or DELIVERED. Spend uses the actual stored final customer price; margin uses stored `profit_markup`, preserving the price charged at booking rather than recalculating today's margin. Currency totals remain separate. All monetary fields are Decimal strings with two places. A repeatable-read snapshot keeps report queries consistent.

Wallet payments list the real `wallet_topups` records, including their pending/completed/failed status, credit timestamp and sandbox flag, using their creation date within the range. No postpaid invoice-payment table exists in the inspected schema, so this endpoint does not invent one. Recorded margin is gross platform markup, not net accounting profit or provider invoice reconciliation.

## Verification

The unit tests use local database doubles for signed HTTP, tenant/account isolation, duplicate/conflicting event IDs, stale updates, terminal delivery, POD restrictions, remedy sanitization, date ranges and exact money. The separate sandbox verification performs real read-only schema/report queries; it does not purchase labels or send WhatsApp messages. Provider credentials and webhook signing keys are not fabricated.
