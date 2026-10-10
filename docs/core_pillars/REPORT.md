# Core pillar verification

Existing operational modules were preserved. This pass added optional pricing
selectors, native signed storefront intake, opt-in Shopify fulfillment delivery
and read-only Sendcloud rating, and repaired the real order-import write path.

| Pillar | Supported now | Remaining activation or development |
|---|---|---|
| Freight | Four cargo types, Decimal express and configurable freight-floor weights, parallel carrier rates, bounded bulk workflow. Letters require explicit provider address verification. Native Sendcloud v2 price reads use verified method limits. | Active provider credentials/contracts; regional/Sendcloud purchase adapters. Actual dimension scanners require a device integration. Freight factors are not certified NMFC classes. |
| Margins/wallet | Tenant/lane/carrier/service/weight/cost rules, new cargo/billing-plan/volume selectors, indexed selection, fixed/percentage markups, locked reserve/submit/capture/release. | Custom commercial tiers beyond prepaid/postpaid need an agreed tier model. Existing fallback is a **20% wholesale markup** (£100 → £120), not a 20% gross-margin formula. |
| E-commerce | Normalized Shopify/WooCommerce/Amazon imports, native Shopify/Woo HMAC intake, signed Amazon adapter gateway, replay/tenant checks, unpacked-order promotion, durable outbox. Opt-in Shopify whole-order/single-location fulfillment and read-only reconciliation. | Store credentials, subscriptions and public HTTPS callback. Woo/Amazon outbound writes still need adapters; Amazon SP-API/OAuth/SNS is not implemented by the gateway. Split Shopify allocations need explicit allocation support. |
| Customs | Pattern-based HS suggestions/abstention/review, CN22/CN23/commercial-invoice metadata, international label print bundles. | Predictions remain simulated; human classification review, carrier forms and actual printer integration remain necessary. |
| Support/audit | Signed tracking, POD restrictions, durable exception tickets/remedies, WhatsApp staging, invoice weight/fuel/residential/remote comparisons and unsent disputes. Provider fee baselines now persist during bulk quoting. | Carrier signing configuration; Twilio credentials and outbound sender/template/conversation handling before message transmission. |

## Database and corrected workflows

Migration **016_core_pillars.sql** was validated in a rollback and applied to the
configured Supabase sandbox. It adds nullable pricing selectors and an index,
permits truly unpacked PENDING_IMPORT shipments without an invented carrier,
and adds remote delivery/reconciliation outbox states. Other shipment states
retain required carrier/cargo packing rules. No SQL action or seed rerun is
needed in this sandbox.

Order imports previously attempted to write generated `final_client_price` and
omitted required fields. They now resolve an active same-tenant member, persist
complete sender/recipient addresses, retain exact item weight in metadata and
round the stored weight upward to 0.001 kg. Empty optional address fields are
omitted. Imports remain unbookable until packing/rating. Use the returned
shipment UUID as the bulk order's `idempotency_key`, retaining its `store_id`
and `store_order_id`, to promote the same row without duplicate store identity.

Routing now filters the actual country columns while retaining tenant isolation.
Bulk repricing clears stale audit baselines and records new ones only when the
provider returns complete fee components. Quote totals never produce invented
surcharge splits. The admin margin form exposes cargo, billing tier and m³ bounds.

## Store connector configuration

`ECOMMERCE_CONNECTORS` is a server-only JSON object keyed by registered store
UUID. Default `{}` disables public storefront intake. Each value requires
`tenant_id`, `auth_user_id` of an active OWNER/ADMIN/DISPATCHER, `platform` and
`webhook_secret` of at least 32 characters. Shopify requires `shop_domain` using
the canonical `your-shop.myshopify.com` host. Use the actual Shopify app client
secret or Woo webhook secret, never a Supabase key.

POST `/api/v1/integration/webhooks/{store_id}` checks exact-body
`X-Shopify-Hmac-Sha256` plus domain/topic, or `X-WC-Webhook-Signature` plus topic.
Woo pending/on-hold/processing orders need verified `sku_unit_grams` configuration
because native order payloads do not reliably carry weights. Unknown weights
are rejected. The JWT `pull-orders` endpoint accepts normalized orders.

For Amazon, a trusted external adapter supplies the normalized StoreOrder shape.
Sign `timestamp + '.' + store UUID + '.' + exact body` with HMAC-SHA256 hex and
send `X-Veloce-Timestamp`/`X-Veloce-Signature`; tolerance is five minutes. This is
not a native SNS endpoint.

Shopify outbound delivery requires `live_delivery=true`, `access_token`, order/
fulfillment API permissions and a selected `api_version` (default `2026-10`).
A durable send fence commits before mutation. Errors/crashes hold the event in
RECONCILIATION_REQUIRED rather than resending automatically. GET
`/api/v1/integration/tracking-events` lists the tenant's latest 200 states.
OWNER/ADMIN can POST `/api/v1/integration/tracking-events/{event_id}/reconcile`;
it only verifies matching existing fulfillment. It never creates another one.
Shopify customer notification is disabled. Current connectors remain empty.

References: [Shopify webhook authentication](https://shopify.dev/docs/api/webhooks/latest),
[Shopify fulfillment creation](https://shopify.dev/docs/api/admin-graphql/latest/mutations/fulfillmentCreate),
[WooCommerce webhook authentication](https://developer.woocommerce.com/docs/apis/rest-api/v3/webhooks/).

## Sendcloud and letter verification

Register a REGIONAL account with `https://panel.sendcloud.sc/api/v2`, approve
`https://panel.sendcloud.sc` in REGIONAL_ALLOWED_ORIGINS, and use the protected
credential controller to encrypt JSON containing `public_key` and `secret_key`.
`SENDCLOUD_METHODS` maps that account UUID to verified method definitions:
`method_id`, `carrier_code`, `cargo_type`, `origin_country`,
`destination_countries`, `min_weight_kg`, exclusive `max_weight_kg`, and maximum
length/width/height in cm. Requests are bounded to four concurrent reads and
100 configured methods. Unknown tariffs, null prices, out-of-bounds dimensions
and mismatched currencies do not become invented quotes. This is a read-only
v2 adapter; assess v3 for new accounts before activation. No Sendcloud parcel or
label is purchased. Letters are excluded until an AVS contract is available.
Reference: [Sendcloud rates](https://sendcloud.dev/api/v2/shipping-prices/retrieve-a-shipping-price).

EasyPost LETTER requests enable strict AVS for both embedded addresses and
require successful delivery-verification flags in the response. The regional
LETTER contract sends `address_validation_required=true` and requires
`address_validation.origin_verified` and `.destination_verified` to be true.
Unsupported verification fails closed instead of claiming deliverability.
Reference: [EasyPost address verification](https://docs.easypost.com/docs/addresses).

## Verification

**87 core backend/security/regression tests passed**, including signature
tampering/domain/duplicate-header rejection, Woo verified SKU weights, Amazon
timestamp checks, Shopify creation/replay/read-only reconciliation, uncertain
delivery fencing, Sendcloud exact-money/null-price behavior and existing role,
cargo, finance, customs, support and auditing regressions. External adapter
responses use MockTransport; no merchant/carrier requests were made.

`database_evidence.json` records real Supabase import/replay, unbookable unpacked
orders, tenant boundaries, import-to-quote promotion, invoice baseline persistence,
cargo/tier/volume pricing and unchanged fallback. Functional test rows rolled
back; only migration 016 persisted. Real PostgreSQL settlement checks also passed
at £20.00, £12.33 and exact £100.00 depletion using controlled receipts and full
rollback. Actual carrier purchases, remote fulfillment, WhatsApp messages and
physical scanning/printing are not claimed as verified.

The owner-control browser suite and seven cargo/customs/manifest/responsiveness
groups passed after the update. Cargo/tier/volume selectors persist in the sample
margin form, role boundaries remain intact, native control colors are readable,
and measured layouts have no page-level horizontal overflow. Backend health
returned HTTP 200; unconfigured native store intake returned HTTP 401.
