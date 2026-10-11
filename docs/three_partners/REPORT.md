# Three-partner native lifecycle implementation

The complete execution code is in [backend/automation_three_partners.py](../../backend/automation_three_partners.py). The former aggregator_lifecycle module preserves its import names for compatibility. There are no unfinished provider handlers, TODO blocks or placeholder method bodies in the new module.

## Provider contract matrix

| Lifecycle | EasyPost | Sendcloud | Shippo |
| --- | --- | --- | --- |
| Purchase | Selected native shipment/rate, GET preflight, POST `/v2/shipments/{id}/buy`, mode and rate confirmation | POST `/api/v3/shipments/announce`, exact quoted option/contract, normalized parcel documents | POST `/transactions/`, exact selected rate, PDF, optional synchronized native order, confirmed TEST/LIVE response |
| Native orders | Single-package synchronization reuses the quoted Shipment; multi-package requests explicitly POST `/v2/orders` with nested shipments | Explicit single-element native batches POST `/api/v3/orders`; GET confirmation before treating asynchronous acceptance as synchronized | Explicit POST `/orders/` with recipient, sender, item totals, placed time and isolated reference |
| Fulfillment | Reconciles the confirmed Shipment/label; EasyPost has no generic sales-order status endpoint | Verified native order followed by idempotent PATCH order status after confirmed local booking | Transaction references the native Order; worker confirms SHIPPED status and matching transaction |
| Customs | Nested customs_info and quantity totals, HS classification and tax_identifiers | Native customs_information, tax_numbers, item weights/values and invoice details | Individual customs/items requests, customs/declarations, exporter EORI, invoice and incoterm mapping |
| Tracking | Native tracker.updated wrapper and X-Hmac-Signature | Native parcel_status_changed wrapper and Sendcloud-Signature; explicit numeric status mappings | Native track_updated wrapper; provisioned Shippo-Auth-Signature, or documented strong URL token fallback |
| Cancellation | Refund request; wallet credit only after native refunded confirmation | Native cancellation; queued responses stay pending; returns use separate PATCH cancellation and GET confirmation | Native refunds endpoint; queued refunds stay pending until confirmed |
| Returns | Fresh is_return native quote; provider reverses original forward addresses | Fresh return option and native returns announcement/retrieval | Fresh supported USPS/UPS/FedEx return quote; extra.is_return reverses addresses |
| Documents | Authenticated EasyInvio PDF proxy | Authenticated EasyInvio PDF proxy | Authenticated EasyInvio PDF proxy |

The attachment's `/v1/orders/` and `/v1/transactions/` Shippo paths do not match its documented API. Sendcloud v3 is used for new integrations instead of silently attaching v2 request bodies to v3 connections. EasyPost Orders represent multi-package shipping; arbitrary unrelated marketplace orders are not placed into one shared-address Order.

## Database and automation behavior

[Migration 024](../../migrations/024_native_partner_orders_and_webhooks.sql) adds encrypted per-connection webhook settings and a private native-order queue. It was applied twice to the configured SANDBOX database, with RLS/browser-access checks passing. See [receipt](migration_receipt.json). No additional manual SQL execution is needed for this sandbox. Other databases need migrations through 024 before deployment.

After a marketplace order has been packed and prepared, the shipment trigger queues native synchronization for its selected provider when that connection is enabled. It does not distribute customer information to every competing provider. On booking, enabled synchronization must be confirmed before the wallet reservation and label purchase. Shippo's confirmed Order ID is injected into its Transaction request. A durable worker subsequently reconciles native fulfillment independently of the paid label.

The queue commits SENDING before a remote mutation. Ambiguous outcomes retain a reconciliation state and are never retried as another create request. Known native IDs are reconciled with read-only GETs; Sendcloud asynchronous acceptance is not marked complete prematurely. Definite failures without a remote ID can be retried explicitly through the sync route or booking after correcting their data. Changed packing/customs after synchronization requires reconciliation or a fresh prepared order. A platform-owner reconciliation endpoint verifies a supplied remote ID against the stored local reference before accepting it.

Money is serialized from Decimal without conversion to float. Refunds retain the existing atomic captured-reservation/wallet/ledger transaction and once-only refund index. No wallet credit is issued merely because a cancellation request returned HTTP 200 or 202.

Native tracking resolves the tenant and account through the authenticated platform connection and stored tracking reference, never an incoming tenant_id. It rejects ambiguous matches and mismatched native shipment references. Signature validation precedes parsing and ingestion. The existing tracking transaction handles chronological ordering, replay fences, DELIVERED terminal state, approved POD URLs and durable exception support events. The support worker creates one remedy ticket and stages the existing WhatsApp outbox. A delivered event closes active tickets and cancels unsent remedies.

No POD image is fabricated: a URL is saved only when actually supplied by the provider and permitted by an exact hostname allowlist. A carrier may omit POD URLs even on a successful delivery.

## Configuration from the application

Open **Super-Admin → Carrier Connectors → configured connection → Orders & Webhooks**.

1. Enable native order synchronization for the desired connection. Sendcloud also requires the numeric ID of its API integration, not a carrier account number or API key.
2. Enable authenticated tracking and save its signing secret. This is encrypted with the server's existing credential encryption keys; no additional provider API secrets need to be duplicated in .env.
3. Enter exact approved POD hostnames. Leave the list empty if POD URLs should not be accepted yet.
4. For Sendcloud, enter verified numeric status IDs mapped to IN_TRANSIT, DELIVERED or EXCEPTION. The parser does not infer states from localized message text; unmapped states are acknowledged as ignored. Obtain the IDs from Sendcloud's parcel-status catalogue referenced by its webhook documentation.
5. Prepend the public HTTPS backend origin to the displayed path `/api/v1/shipping/tracking-webhooks?source=<connection UUID>` and register it in the provider dashboard. A tunnel such as ngrok is useful during local development because provider servers cannot reach 127.0.0.1.

EasyPost registration must use the same webhook_secret saved here. Sendcloud signs with its Secret Key or Webhook Signature Key: save that matching value, enable webhook feedback on the API integration, paste the complete URL and save. Shippo HMAC requires provisioning by Shippo; if unavailable, select URL_TOKEN, save a strong generated token and append `&token=<that token>` to its configured webhook URL. Register `track_updated` in the matching test/live mode. Query tokens must be excluded from proxy/tunnel request logs; the local backend disables URL-bearing access logs.

Save does not register a subscription at an external provider or claim a console test was delivered. It stores the receiver configuration. Those external steps are necessary for actual webhook delivery.

## Validation results

| Check | Result | Evidence scope |
| --- | --- | --- |
| Full application unit/contract suite | 263 passed | Includes 16 new native-order, signature, isolation, customs, exact Decimal serialization and unknown-outcome tests |
| Native settings browser | Passed | Controlled API; verified owner settings, write-only secret clearing on save/logout and 375/768/1366px layouts |
| Native orders and fulfillment on actual Supabase | Passed for all three providers | Actual triggers, FKs, private queue and persistence; provider HTTP responses controlled with MockTransport |
| Native exception/POD ingestion on actual Supabase | Passed for all three providers | Signed controlled provider snapshots; duplicate receipt, one ticket, POD mapping, terminal/stale protection and forged-signature rejection |
| Genuine EasyPost TEST booking regression | Passed | Actual rates, test label, wallet gate, one debit and booking replay; real refund remained pending and did not credit early |
| Genuine Sendcloud/Shippo label/return/refund streams | Not executed | Requires configured accounts and appropriate provider test facilities; no LIVE purchases were made |
| Genuine provider-console webhook delivery | Not executed | Requires external subscription registration and matching saved signing credentials |

[Database probe](database_probe.json), [browser report](browser_report.json), and [genuine EasyPost evidence](../aggregator_lifecycle/sandbox_probe.json) distinguish controlled contracts from actual external calls. All SQL probe fixture writes were rolled back. No WhatsApp message, Stripe payment or HubSpot synchronization was sent by the native database probe.

Ordinary Sendcloud label announcements can incur real charges. Its existing TEST purchase guard remains enforced; implementing the native API does not turn an ordinary account into a free carrier sandbox. Its test facilities must be configured separately before claiming genuine carrier purchase/return passes.

## Official references

- [EasyPost Orders](https://docs.easypost.com/docs/orders) and [tax identifiers](https://docs.easypost.com/docs/shipments/tax-identifiers).
- [Shippo Orders](https://docs.goshippo.com/orders/orders/), [webhook security](https://docs.goshippo.com/tracking/webhook-security/), and [customs declaration](https://docs.goshippo.com/api-reference/customs-declarations/create-a-new-customs-declaration/).
- [Sendcloud native order schema](https://sendcloud.dev/.openapi/v3/orders/openapi.yaml), [webhook authentication](https://sendcloud.dev/api/v3/webhooks/), [native parcel event schema](https://sendcloud.dev/.openapi/v3/webhooks/openapi.yaml), and [creating test labels](https://sendcloud.dev/docs/getting-started/creating-test-labels/).
