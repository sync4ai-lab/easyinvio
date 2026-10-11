# Three-provider lifecycle and administrator setup

EasyInvio now exposes EasyPost, Sendcloud v3 and Shippo in the administrator provider catalogue. Shiprocket integration code and setup options have been removed. The legacy Sendcloud v2 adapter remains available for existing connections, but is excluded from new-provider selection.

## Administrator workflow

1. Sign in as the verified platform owner and open Carrier Connectors.
2. Choose **Add New Aggregator** to open the full setup form directly. Official endpoints are detected automatically; API formats can be selected inside the form. Individual provider cards retain Set Up actions.
3. Supply an account name and credentials matching the server's TEST or LIVE environment. Official endpoints and internal identifiers are automatic. Shippo uses a `shippo_test_` or `shippo_live_` token; Sendcloud uses its public and secret keys.
4. Use **Verify Connection** for a read-only credential check. This does not purchase a label.
5. Use **Edit Settings** to change an existing connection. Keys remain write-only and encrypted on the server. Changing credentials invalidates outstanding quotes; obtain new quotes before booking. Replacement keys must belong to the same upstream account if historic labels still require access.
6. **Disable** excludes the connection from new outbound quotes. It retains credentials, shipment references and audit history for in-flight reconciliation, return bookings, refunds and label downloads. Disabled rows remain visible; Edit Settings can re-enable them. Client-specific legacy overrides are hidden unless explicitly selected.

Changing the provider, environment or upstream account on a connection with shipment history is rejected: create a new connection and disable the old one instead.

Connections are owned by EasyInvio and distributed to eligible tenants through the existing platform-carrier mechanism. Client responses retain carrier/service names and opaque offers; credentials, provider routing and native document URLs stay private.

## Extensibility boundary

Adding, editing and removing configurations for supported adapters is self-service. The catalogue is loaded from the protected backend capabilities endpoint rather than requiring another hardcoded frontend card. A new native provider must implement `BaseAggregatorAdapter`, register its official endpoint in `ADAPTERS`, and publish its capabilities in `aggregator_registry.py`. The pricing and booking routers then use that adapter through the same factory.

A previously unsupported API cannot safely be implemented using only an API key and URL: request schemas, asynchronous purchase outcomes, customs fields, cancellation confirmation and return rates differ. The optional custom regional connection supports the existing approved `/rates` contract; it does not claim native label purchase support.

## Transaction and security behavior

- `POST /api/v1/shipping/confirm-booking` accepts only the authenticated tenant and an opaque offer ID. Private server snapshots determine the account, native rate and price.
- Direct speed quotes and packed workspace quotes can be bound to shipments. Multi-package speed quotes require individual packed workspace orders before booking.
- Shared advisory locks and wallet row locks protect preparation and purchase. Confirmed labels are persisted before settlement. Repeated booking returns the original label without another purchase or debit.
- Ambiguous native outcomes retain submitted reservations and require reconciliation; mutating provider calls are not automatically retried.
- `POST /api/v1/shipping/request-void` credits the original captured charge only after confirmed native cancellation. Pending cancellation requests do not credit a wallet. A durable worker polls pending cancellations with bounded backoff.
- `POST /api/v1/shipping/prepare-return` requires an original shipment in the same tenant and obtains a fresh return quote. International returns require new customs authorization. A forward rate is never reused as a return price.
- Authenticated document downloads use EasyInvio URLs, exact approved upstream hosts and PDF validation. Bearer tokens are not forwarded to unrelated document hosts.
- Existing canonical `BOOKED` status is preserved for compatibility with manifests, analytics, tracking and CRM hooks.

## Database

[Migration 023](../../migrations/023_partner_lifecycle.sql) adds private unbound quotes, bound offers, pending cancellations, connection retirement timestamps and constrained, idempotent shipment-refund ledger entries. Browser roles have no access to the private lifecycle tables.

Migration 023 was applied twice to the configured SANDBOX database; the second run verified idempotency. See [migration receipt](migration_receipt.json). No additional manual database update is required for that sandbox. Other environments need migrations through 023 before deploying this code.

## Validation and remaining external checks

| Area | Result and evidence |
| --- | --- |
| Automated application suite | 247 tests passed; includes tenant tampering, exact adapter selection, credential changes, actual-vs-volumetric weight, native response contracts, financial environment guards and return cancellation confirmation. These are controlled tests, not proof of all provider deployments. |
| Administrator browser | Passed provider selection, automatic Shippo fields, authentication guards, removal/archive controls, no JavaScript errors and no horizontal overflow at 375–1440px. |
| Carrier presentation and identity browser suites | Passed branding, financial-role disclosures, performance badges, mobile layouts, login/profile/logout regression checks using controlled data. |
| Genuine EasyPost TEST lifecycle | Passed actual rates, insufficient-wallet rejection, test label creation, one wallet debit and idempotent booking replay. Actual cancellation was pending, so no premature refund was applied. All database test writes rolled back. |
| Confirmed-cancellation database reversal | Passed once-only credit against actual SQL using a controlled provider-confirmation simulation. This is explicitly not a genuine carrier cancellation confirmation. |
| Shippo | Native contract tests passed; a genuine saved-token purchase/return/refund test was not executed in this run. |
| Sendcloud | Native contracts implemented and tested with controlled responses. No ordinary Sendcloud label was purchased: normal carrier labels can be billed, so TEST purchase remains guarded. No LIVE label or return was created. |
| Native tracking webhooks | Native receivers for all three partners are implemented in automation_three_partners.py. Actual console registration/delivery still requires configuration; see ../three_partners/REPORT.md. |
| Native order synchronization | Implemented with an opted-in durable queue and provider-specific semantics. See ../three_partners/REPORT.md for the implementation and validation evidence. |

See [sandbox test evidence](sandbox_probe.json). No Stripe payment, WhatsApp message or HubSpot synchronization was sent by that probe. Real provider TEST labels remain in the provider account even though database fixtures were rolled back.

Official contract references: [EasyPost returns](https://docs.easypost.com/docs/shipments/returns), [Shippo returns](https://docs.goshippo.com/shipments/returns), [Sendcloud shipments schema](https://sendcloud.dev/.openapi/v3/shipments/openapi.yaml), [Sendcloud returns schema](https://sendcloud.dev/.openapi/v3/returns/openapi.yaml), and [Sendcloud test labels](https://sendcloud.dev/docs/getting-started/test-labels/).
