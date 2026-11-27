# Connect your custom website with signed APIs

## Retailer setup

Your own custom website can submit orders and request live checkout estimates without pretending to be Shopify. A workspace owner registers **Custom Website / REST API** in Store Integrations, saves the retailer's public HTTPS origin, and optionally a tracking callback on that same origin. Configure measured SKU weights for native adapters; normalized bridge orders carry their own explicit unit weights. Save a complete warehouse billing address, connect eligible carrier accounts and ensure your subscription includes store integrations.

Copy the generated key ID and one-time signing secret into your backend's secret store. Never put signing credentials in browser JavaScript, a mobile app, a URL or a public Make/Zapier step. The server encrypts credentials with its configured Fernet key. Blank secret inputs retain previous values. Rotate API signing secret invalidates existing signatures, including any native webhook using the same store secret: coordinate replacement at both ends. Secrets cannot be retrieved by GET.

Use **Test connection** for native API read checks. A bridge has no native API login to test: prove inbound delivery with a correctly signed request. A successful native read does not prove write scopes, notifications or carrier readiness. Setup does not buy labels. API limits are 120 orders/minute and 20 checkout requests/minute per store; requests fail closed on invalid signatures. All database-backed features require migration 057 after 056.

## Exact signing contract

Send JSON bytes and these headers: `Content-Type: application/json`, `X-EasyInvio-Store-Id` (UUID), `X-EasyInvio-Key-Id`, `X-EasyInvio-Timestamp` (Unix seconds), `X-EasyInvio-Signature` (lowercase hex).

Canonical text is `timestamp.METHOD.path.store_uuid.sha256(raw_body)` joined with literal dots. METHOD is uppercase; path begins `/` and excludes origin/query. Use exactly the transmitted UTF-8 bytes. Compute HMAC-SHA256 with the signing secret. The timestamp must be within five minutes. Duplicate authentication headers are rejected. Key ID identifies the current credential, not a second secret. Routes are store-bound and recheck the merchant's active dispatch authority. Repeated identical order IDs are idempotent; changed shipping data returns 409 for review. The signature is not a one-use nonce: timestamp-limited retries are intentional, and order IDs provide durable mutation idempotency.

Python signing example (run on your backend; variables are loaded from your private configuration):

```python
import hashlib, hmac, json, time
raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
stamp = str(int(time.time()))
canonical = ".".join((stamp, "POST", path, str(store_id), hashlib.sha256(raw).hexdigest()))
signature = hmac.new(signing_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
headers = {"Content-Type": "application/json", "X-EasyInvio-Store-Id": str(store_id),
           "X-EasyInvio-Key-Id": key_id, "X-EasyInvio-Timestamp": stamp,
           "X-EasyInvio-Signature": signature}
# Send raw as the HTTP body. Do not reserialize payload after signing.
```

Node.js signing and callback verification example:

```javascript
import {createHash, createHmac, timingSafeEqual} from 'node:crypto';
const raw = Buffer.from(JSON.stringify(payload), 'utf8');
const timestamp = String(Math.floor(Date.now()/1000));
function sign(bytes, stamp, path, storeId, secret) {
  const canonical = [stamp, 'POST', path, storeId,
    createHash('sha256').update(bytes).digest('hex')].join('.');
  return createHmac('sha256', secret).update(canonical).digest('hex');
}
const signature = sign(raw, timestamp, path, storeId, signingSecret);
// On your callback server, retain original raw bytes before any JSON middleware.
function verifyCallback(bytes, stamp, signature, path, storeId, secret) {
  if (!/^\d+$/.test(stamp) || Math.abs(Date.now()/1000-Number(stamp))>300 ||
      !/^[a-f0-9]{64}$/.test(signature)) return false;
  return timingSafeEqual(Buffer.from(signature, 'hex'),
    Buffer.from(sign(bytes, stamp, path, storeId, secret), 'hex'));
}
```

Python callback verification uses the same canonical string, a five-minute timestamp check and `hmac.compare_digest(received_signature, expected_signature)`. Check the expected store ID/key ID before acknowledging. Never trust a body-supplied tenant selector.

## Push orders

`POST /api/v1/integration/custom-store/orders` accepts the normalized `StoreOrder` object, not a surrounding platform envelope. Required schema: `id` (string/integer), `name` (reference), `currency` (`GBP|EUR|USD`), `shipping_address` and `line_items` (1–500). Address requires `name,address1,city,zip,country_code`; optional `address2,province,phone,email`. Each item requires `title,quantity` (integer 1–10000), `grams` (unit grams as decimal string); optional all-three `length_cm,width_cm,height_cm`, `unit_value,origin_country,hs_code`. Packed dimensions, goods value/origin and customs still need review before booking. Currency is never silently converted.

```json
{"id":"WEB-1042","name":"#1042","currency":"GBP","shipping_address":{"name":"Demo Recipient","address1":"1 Example Street","city":"Leeds","zip":"LS12 6EJ","country_code":"GB","email":"recipient@example.test"},"line_items":[{"title":"Cotton shirt","quantity":2,"grams":"200","unit_value":"12.00","origin_country":"GB"}]}
```

201 response contains `shipment_id,status,replayed,store_order_id,order_reference,shipping_address,total_weight_kg,total_quantity,line_items,currency`. Initial status is `PENDING_IMPORT`; the example total goods weight is `0.4` kg. Import never purchases a label. Identical retries return `replayed:true`. Only the authenticated store can receive this order; another store or tenant cannot select it through these credentials.

## Checkout rates

`POST /api/v1/integration/custom-store/checkout-rates` accepts `weight_kg,length_cm,width_cm,height_cm` as positive decimal strings, optional `currency` (default GBP), and `destination` containing `name,line1,city,postal_code,country_code`. Supply exact town, postcode and country, plus street/name for carriers that require a complete address. Postcode-only checkout widgets must collect those remaining fields before requesting a carrier quote; no representative address is invented. Origin is the merchant's validated warehouse billing address.

```json
{"weight_kg":"2.000","length_cm":"25","width_cm":"20","height_cm":"15","currency":"GBP","destination":{"name":"Demo Recipient","line1":"1 Example Street","city":"Leeds","postal_code":"LS12 6EJ","country_code":"GB"}}
```

The live response is `{currency,partial,expires_at,rates,notice}`. Each rate is `{carrier,service,price_ex_tax,currency,delivery_days}`; `delivery_days` may be null. The merchant's ordinary rating/tier/margin rules apply. No wholesale cost, provider credential or booking authorization is returned. `partial:true` means some providers did not return offers. Identical checkout requests reuse a store/tenant-bound result for at most 90 seconds and never beyond quote expiry; booking always requotes under current rules. No sample prices replace missing live rates. A checkout estimate is not a label or guaranteed final customs price. Compare fresh rates in the workspace before purchase.

## Tracking callbacks

Enable Live Tracking Write-Back only after configuring your callback receiver. EasyInvio sends signed JSON to the configured HTTPS path on your retailer origin. Apply the same signing contract and exact bytes; callback headers include `Idempotency-Key` equal to `event_id`. Store the event ID durably and acknowledge duplicate delivery without repeating a side effect. Return a 200/201/202 JSON response (or empty 204) only after committing receipt. Do not redirect callbacks. Server errors/timeouts retry with backoff and the same event ID, up to 30 attempts; inspect tracking sync activity for unresolved outcomes.

Scan-status callback schema: `event_id,store_order_id,tracking_lifecycle_type,status,tracking_number,occurred_at`. Only accepted carrier updates are queued, with the original store relationship retained for returns. Forward/return scan callbacks use the same durable signature and event-ID deduplication contract.

Confirmed-label callback schema: `event_id,tracking_lifecycle_type,store_order_id,tracking_number,carrier_name,tracking_url,tracking_numbers,fulfillment_state,return_quantity,store_return_reference,paperless_available,return_dropoff_qr_code_url`. Lifecycle is forward or return. Forward fulfillment is `SHIPPED`; a return label is `RETURN_LABEL_CREATED`. A document API path in this event is workspace-protected, not a public authorization token. Do not interpret a return label or scan as a merchandise refund.

## Hosted returns and developer-free alternatives

An owner/admin opens Public returns portal for the store, chooses a unique address identifier and explicitly enables a spending policy: return window, retailer/customer payment and maximum postage. Share the resulting `/returns/{store_slug}` link on the retailer website. A shopper supplies the order reference and delivery postcode or recorded email; no order contents are shown before verification. Only delivered eligible original single-parcel domestic returns proceed. Customer payment is confirmed through Stripe before documents become available; QR is shown only when the carrier actually supplies one. Optional email/WhatsApp instructions use original recorded contacts and require configured channels and shopper permission.

Embedding this link needs no custom code. CSV import already supports preparing orders without an API integration. Zapier/Make can bridge normalized orders only if a trusted server-side signing step is configured; this is not an installed EasyInvio Zapier/Make app or native OAuth connection. CSV/SFTP is a directory bridge entry: CSV upload exists, but an SFTP receiver/scheduled file collector is not implemented. Never claim an unconfigured middleware connection is active.

## Errors and rollout

401: invalid/expired signature or rotated key. 403: disabled authority/entitlement. 404: unknown store/order or failed shopper verification. 409: changed order, policy, partial allocation or uncertain prior operation needs review. 422: invalid address/weights/configuration. 429: rate limit. 502/503: remote API/database/provider unavailable. Retain original order/event/request IDs; never blindly retry a label purchase or payment. Apply migration 057, deploy web and worker from the same commit and test with deliberately selected merchant accounts. This guide describes implemented endpoints, not proof that your particular provider credentials are live-ready.
