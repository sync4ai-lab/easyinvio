# API reference

194 OpenAPI HTTP operations across 172 paths are listed below, followed by WebSocket/non-schema routes and every request/response component. This export imports the app without starting lifespan.

Use [openapi.json](openapi.json) for structural contracts and [api_inventory.json](api_inventory.json) for source/dependency mapping. Custom Python validators can impose stricter rules than generated JSON Schema, including rejecting floats on a Decimal field. Empty response schemas do not prove an empty response; read the handler/service when no response model is declared.

Workspace Bearer authentication, platform-owner allowlisting, callback signatures, scoped document tokens and preview guards are different. Missing OpenAPI security metadata never establishes anonymous access. Guards may live in called helpers.

## Shared conventions

- Preserve exact decimal strings and currency as required by the component schema. NaN/infinity and unsupported floats are not money.
- Keep a stable request/idempotency UUID for one semantic action; changed payloads conflict. Never resubmit an uncertain charge as a new key.
- Inspect every batch item and count; HTTP success does not prove every item booked.
- 401 concerns identity/signature, 403 scope/permission/activation, 404 scoped lookup, 409 conflict/review/expiry, 422 validation/readiness. A timeout/5xx can retain an unknown outcome; handlers may document more specific statuses.

## HTTP operation index

| Method | Path | Summary |
| --- | --- | --- |
| GET | [/api/v1/admin/agents/metrics](#op-get-api-v1-admin-agents-metrics) | Metrics |
| GET | [/api/v1/admin/analytics/dashboard](#op-get-api-v1-admin-analytics-dashboard) | Platform Report |
| POST | [/api/v1/admin/audit/invoice](#op-post-api-v1-admin-audit-invoice) | Owner Audit |
| GET | [/api/v1/admin/carriers](#op-get-api-v1-admin-carriers) | Carriers |
| POST | [/api/v1/admin/carriers](#op-post-api-v1-admin-carriers) | Add Carrier |
| DELETE | [/api/v1/admin/carriers/{account_id}](#op-delete-api-v1-admin-carriers-account-id) | Remove Carrier |
| PATCH | [/api/v1/admin/carriers/{account_id}](#op-patch-api-v1-admin-carriers-account-id) | Change Carrier |
| POST | [/api/v1/admin/carriers/{account_id}/disable](#op-post-api-v1-admin-carriers-account-id-disable) | Remove Carrier |
| POST | [/api/v1/admin/carriers/{account_id}/replace-credentials](#op-post-api-v1-admin-carriers-account-id-replace-credentials) | Replace Credentials |
| GET | [/api/v1/admin/client-assistance/clients](#op-get-api-v1-admin-client-assistance-clients) | Clients |
| GET | [/api/v1/admin/client-assistance/events](#op-get-api-v1-admin-client-assistance-events) | Events |
| POST | [/api/v1/admin/client-assistance/sessions](#op-post-api-v1-admin-client-assistance-sessions) | Start |
| DELETE | [/api/v1/admin/client-assistance/sessions/{session_id}](#op-delete-api-v1-admin-client-assistance-sessions-session-id) | Stop |
| GET | [/api/v1/admin/individual-pricing](#op-get-api-v1-admin-individual-pricing) | Read Individual Pricing |
| PUT | [/api/v1/admin/individual-pricing](#op-put-api-v1-admin-individual-pricing) | Update Individual Pricing |
| POST | [/api/v1/admin/insurance/settlements](#op-post-api-v1-admin-insurance-settlements) | Platform Settlement |
| GET | [/api/v1/admin/integrations/alerts](#op-get-api-v1-admin-integrations-alerts) | Integration Alerts |
| GET | [/api/v1/admin/margins](#op-get-api-v1-admin-margins) | Margins |
| POST | [/api/v1/admin/margins](#op-post-api-v1-admin-margins) | Create Margin |
| DELETE | [/api/v1/admin/margins/{rule_id}](#op-delete-api-v1-admin-margins-rule-id) | Retire Margin |
| PUT | [/api/v1/admin/margins/{rule_id}](#op-put-api-v1-admin-margins-rule-id) | Update Margin |
| GET | [/api/v1/admin/platform-carriers](#op-get-api-v1-admin-platform-carriers) | List Connections |
| POST | [/api/v1/admin/platform-carriers](#op-post-api-v1-admin-platform-carriers) | Create |
| GET | [/api/v1/admin/platform-carriers/capabilities](#op-get-api-v1-admin-platform-carriers-capabilities) | Capabilities |
| DELETE | [/api/v1/admin/platform-carriers/{connection_id}](#op-delete-api-v1-admin-platform-carriers-connection-id) | Retire |
| PUT | [/api/v1/admin/platform-carriers/{connection_id}](#op-put-api-v1-admin-platform-carriers-connection-id) | Update |
| POST | [/api/v1/admin/platform-carriers/{connection_id}/disable](#op-post-api-v1-admin-platform-carriers-connection-id-disable) | Retire |
| POST | [/api/v1/admin/platform-carriers/{connection_id}/native-orders/reconcile](#op-post-api-v1-admin-platform-carriers-connection-id-native-orders-reconcile) | Reconcile Order |
| GET | [/api/v1/admin/platform-carriers/{connection_id}/native-settings](#op-get-api-v1-admin-platform-carriers-connection-id-native-settings) | Read Configuration |
| PUT | [/api/v1/admin/platform-carriers/{connection_id}/native-settings](#op-put-api-v1-admin-platform-carriers-connection-id-native-settings) | Configure |
| GET | [/api/v1/admin/platform-carriers/{connection_id}/quote-diagnostics](#op-get-api-v1-admin-platform-carriers-connection-id-quote-diagnostics) | Diagnostics |
| POST | [/api/v1/admin/platform-carriers/{connection_id}/upgrade-sendcloud](#op-post-api-v1-admin-platform-carriers-connection-id-upgrade-sendcloud) | Upgrade Sendcloud |
| POST | [/api/v1/admin/platform-carriers/{connection_id}/verify](#op-post-api-v1-admin-platform-carriers-connection-id-verify) | Verify Connection |
| POST | [/api/v1/admin/sandbox/whatsapp-setup](#op-post-api-v1-admin-sandbox-whatsapp-setup) | Setup Whatsapp |
| GET | [/api/v1/admin/shipments/manifest](#op-get-api-v1-admin-shipments-manifest) | Owner Manifest |
| GET | [/api/v1/admin/shipments/{shipment_id}/dispute-draft](#op-get-api-v1-admin-shipments-shipment-id-dispute-draft) | Admin Get Draft |
| PUT | [/api/v1/admin/shipments/{shipment_id}/dispute-draft](#op-put-api-v1-admin-shipments-shipment-id-dispute-draft) | Admin Save Draft |
| GET | [/api/v1/admin/support/tickets](#op-get-api-v1-admin-support-tickets) | All Tickets |
| POST | [/api/v1/admin/support/tickets/{ticket_id}/intervene](#op-post-api-v1-admin-support-tickets-ticket-id-intervene) | Admin Intervene |
| POST | [/api/v1/admin/support/tickets/{ticket_id}/resolve](#op-post-api-v1-admin-support-tickets-ticket-id-resolve) | Admin Resolve |
| GET | [/api/v1/admin/support/whatsapp/bindings](#op-get-api-v1-admin-support-whatsapp-bindings) | Bindings |
| PATCH | [/api/v1/admin/support/whatsapp/bindings/{binding_id}](#op-patch-api-v1-admin-support-whatsapp-bindings-binding-id) | Pause |
| GET | [/api/v1/admin/tenants](#op-get-api-v1-admin-tenants) | Tenants |
| POST | [/api/v1/admin/tenants](#op-post-api-v1-admin-tenants) | Create Tenant |
| PATCH | [/api/v1/admin/tenants/{tenant_id}/seller-classification](#op-patch-api-v1-admin-tenants-tenant-id-seller-classification) | Update Seller Classification |
| GET | [/api/v1/admin/transactions](#op-get-api-v1-admin-transactions) | Transactions |
| POST | [/api/v1/agents/customs/information](#op-post-api-v1-agents-customs-information) | Information |
| POST | [/api/v1/agents/customs/suggest](#op-post-api-v1-agents-customs-suggest) | Customs |
| POST | [/api/v1/agents/interpret](#op-post-api-v1-agents-interpret) | Interpret |
| POST | [/api/v1/agents/quote](#op-post-api-v1-agents-quote) | Quote |
| GET | [/api/v1/analytics/carrier-performance](#op-get-api-v1-analytics-carrier-performance) | Carrier Performance |
| GET | [/api/v1/analytics/reports](#op-get-api-v1-analytics-reports) | Reports |
| GET | [/api/v1/analytics/tracking-readiness](#op-get-api-v1-analytics-tracking-readiness) | Readiness |
| POST | [/api/v1/audit/invoice](#op-post-api-v1-audit-invoice) | Audit |
| POST | [/api/v1/audit/preview](#op-post-api-v1-audit-preview) | Audit Preview |
| POST | [/api/v1/auth/accept-invitation](#op-post-api-v1-auth-accept-invitation) | Accept |
| POST | [/api/v1/auth/forgot-password](#op-post-api-v1-auth-forgot-password) | Forgot Password |
| POST | [/api/v1/auth/logout](#op-post-api-v1-auth-logout) | Logout |
| GET | [/api/v1/auth/me](#op-get-api-v1-auth-me) | Me |
| PATCH | [/api/v1/auth/me](#op-patch-api-v1-auth-me) | Update Me |
| POST | [/api/v1/auth/register](#op-post-api-v1-auth-register) | Register Account |
| POST | [/api/v1/auth/register/verify](#op-post-api-v1-auth-register-verify) | Verify Account |
| POST | [/api/v1/auth/renew](#op-post-api-v1-auth-renew) | Renew |
| POST | [/api/v1/auth/reset-password](#op-post-api-v1-auth-reset-password) | Reset Password |
| POST | [/api/v1/auth/token](#op-post-api-v1-auth-token) | Token |
| POST | [/api/v1/automation/bulk-fulfill](#op-post-api-v1-automation-bulk-fulfill) | Bulk |
| POST | [/api/v1/automation/cargo-weight](#op-post-api-v1-automation-cargo-weight) | Cargo Weight |
| GET | [/api/v1/automation/customs/{shipment_id}](#op-get-api-v1-automation-customs-shipment-id) | Customs |
| POST | [/api/v1/automation/orders/{shipment_id}/reconcile](#op-post-api-v1-automation-orders-shipment-id-reconcile) | Reconcile |
| POST | [/api/v1/billing/carts](#op-post-api-v1-billing-carts) | Create |
| POST | [/api/v1/billing/carts/{cart_id}/complete](#op-post-api-v1-billing-carts-cart-id-complete) | Complete |
| POST | [/api/v1/billing/create-checkout](#op-post-api-v1-billing-create-checkout) | Create Checkout |
| POST | [/api/v1/billing/test-topup](#op-post-api-v1-billing-test-topup) | Test Topup |
| GET | [/api/v1/billing/topups/{topup_id}](#op-get-api-v1-billing-topups-topup-id) | Topup Status |
| POST | [/api/v1/billing/topups/{topup_id}/reconcile](#op-post-api-v1-billing-topups-topup-id-reconcile) | Reconcile |
| GET | [/api/v1/billing/wallet-activity](#op-get-api-v1-billing-wallet-activity) | Activity |
| POST | [/api/v1/billing/webhooks/stripe](#op-post-api-v1-billing-webhooks-stripe) | Snapshot Webhook |
| GET | [/api/v1/catalog/addresses](#op-get-api-v1-catalog-addresses) | List Addresses |
| POST | [/api/v1/catalog/addresses](#op-post-api-v1-catalog-addresses) | Create Addresses |
| DELETE | [/api/v1/catalog/addresses/{record_id}](#op-delete-api-v1-catalog-addresses-record-id) | Archive Addresses |
| PUT | [/api/v1/catalog/addresses/{record_id}](#op-put-api-v1-catalog-addresses-record-id) | Update Addresses |
| GET | [/api/v1/catalog/contacts](#op-get-api-v1-catalog-contacts) | List Contacts |
| POST | [/api/v1/catalog/contacts](#op-post-api-v1-catalog-contacts) | Create Contacts |
| DELETE | [/api/v1/catalog/contacts/{record_id}](#op-delete-api-v1-catalog-contacts-record-id) | Archive Contacts |
| PUT | [/api/v1/catalog/contacts/{record_id}](#op-put-api-v1-catalog-contacts-record-id) | Update Contacts |
| GET | [/api/v1/catalog/products](#op-get-api-v1-catalog-products) | List Products |
| POST | [/api/v1/catalog/products](#op-post-api-v1-catalog-products) | Create Products |
| GET | [/api/v1/catalog/products/by-sku/{sku}](#op-get-api-v1-catalog-products-by-sku-sku) | By Sku |
| DELETE | [/api/v1/catalog/products/{record_id}](#op-delete-api-v1-catalog-products-record-id) | Archive Products |
| PUT | [/api/v1/catalog/products/{record_id}](#op-put-api-v1-catalog-products-record-id) | Update Products |
| GET | [/api/v1/checkout/context](#op-get-api-v1-checkout-context) | Context |
| POST | [/api/v1/checkout/hs-search](#op-post-api-v1-checkout-hs-search) | Hs Search |
| POST | [/api/v1/checkout/prepare](#op-post-api-v1-checkout-prepare) | Prepare |
| GET | [/api/v1/checkout/{shipment_id}/commercial-invoice.pdf](#op-get-api-v1-checkout-shipment-id-commercial-invoice-pdf) | Invoice |
| GET | [/api/v1/checkout/{shipment_id}/receipt.pdf](#op-get-api-v1-checkout-shipment-id-receipt-pdf) | Receipt |
| GET | [/api/v1/config](#op-get-api-v1-config) | Public Config |
| POST | [/api/v1/conversational/process-message](#op-post-api-v1-conversational-process-message) | Process Message |
| GET | [/api/v1/countries](#op-get-api-v1-countries) | Countries |
| POST | [/api/v1/crm/sync-tenant](#op-post-api-v1-crm-sync-tenant) | Sync Tenant |
| POST | [/api/v1/customs/declaration](#op-post-api-v1-customs-declaration) | Declaration |
| POST | [/api/v1/customs/harmonize](#op-post-api-v1-customs-harmonize) | Harmonize |
| GET | [/api/v1/dispatch-workspace/orders](#op-get-api-v1-dispatch-workspace-orders) | Inbox |
| GET | [/api/v1/dispatch-workspace/orders/{shipment_id}](#op-get-api-v1-dispatch-workspace-orders-shipment-id) | Prepare |
| POST | [/api/v1/dispatch-workspace/orders/{shipment_id}/prepare](#op-post-api-v1-dispatch-workspace-orders-shipment-id-prepare) | Save Preparation |
| POST | [/api/v1/dispatch-workspace/print-bundle](#op-post-api-v1-dispatch-workspace-print-bundle) | Print Bundle |
| POST | [/api/v1/dispatch-workspace/process](#op-post-api-v1-dispatch-workspace-process) | Process |
| POST | [/api/v1/dispatch-workspace/sync/{store_id}](#op-post-api-v1-dispatch-workspace-sync-store-id) | Sync |
| POST | [/api/v1/dispatch/manifests/close](#op-post-api-v1-dispatch-manifests-close) | Close |
| POST | [/api/v1/dispatch/manifests/preview](#op-post-api-v1-dispatch-manifests-preview) | Preview |
| GET | [/api/v1/dispatch/manifests/{manifest_id}](#op-get-api-v1-dispatch-manifests-manifest-id) | Status |
| GET | [/api/v1/dispatch/manifests/{manifest_id}/document](#op-get-api-v1-dispatch-manifests-manifest-id-document) | Document |
| GET | [/api/v1/dispatch/manifests/{manifest_id}/download](#op-get-api-v1-dispatch-manifests-manifest-id-download) | Download |
| GET | [/api/v1/dispatch/summary](#op-get-api-v1-dispatch-summary) | Dispatch Summary |
| POST | [/api/v1/finance/audit-invoice-upload](#op-post-api-v1-finance-audit-invoice-upload) | Upload |
| GET | [/api/v1/finance/billing-disputes](#op-get-api-v1-finance-billing-disputes) | Disputes |
| POST | [/api/v1/help/search-agent](#op-post-api-v1-help-search-agent) | Search |
| POST | [/api/v1/integration/pull-orders](#op-post-api-v1-integration-pull-orders) | Pull Orders |
| POST | [/api/v1/integration/return-webhooks/{store_id}](#op-post-api-v1-integration-return-webhooks-store-id) | Return Webhook |
| GET | [/api/v1/integration/tracking-events](#op-get-api-v1-integration-tracking-events) | Tracking Events |
| POST | [/api/v1/integration/tracking-events/{event_id}/reconcile](#op-post-api-v1-integration-tracking-events-event-id-reconcile) | Reconcile Tracking |
| POST | [/api/v1/integration/tracking-events/{event_id}/return-reference](#op-post-api-v1-integration-tracking-events-event-id-return-reference) | Link Return |
| POST | [/api/v1/integration/webhooks/{store_id}](#op-post-api-v1-integration-webhooks-store-id) | Native Webhook |
| POST | [/api/v1/integrations/ecommerce/orders-sync](#op-post-api-v1-integrations-ecommerce-orders-sync) | Orders |
| POST | [/api/v1/integrations/hubspot-webhook](#op-post-api-v1-integrations-hubspot-webhook) | Webhook |
| POST | [/api/v1/integrations/whatsapp/outbound-status/{part_id}](#op-post-api-v1-integrations-whatsapp-outbound-status-part-id) | Status |
| POST | [/api/v1/integrations/whatsapp/webhook](#op-post-api-v1-integrations-whatsapp-webhook) | Whatsapp Webhook |
| POST | [/api/v1/logistics/cargo-weight](#op-post-api-v1-logistics-cargo-weight) | Cargo Weight |
| POST | [/api/v1/logistics/package-guidance](#op-post-api-v1-logistics-package-guidance) | Public Guidance |
| POST | [/api/v1/logistics/weight](#op-post-api-v1-logistics-weight) | Weight |
| GET | [/api/v1/profile](#op-get-api-v1-profile) | Profile |
| POST | [/api/v1/rates/preview](#op-post-api-v1-rates-preview) | Rates Preview |
| POST | [/api/v1/rates/sample](#op-post-api-v1-rates-sample) | Sample Rates |
| GET | [/api/v1/routing/disruptions](#op-get-api-v1-routing-disruptions) | Routing |
| GET | [/api/v1/routing/preview](#op-get-api-v1-routing-preview) | Routing Preview |
| GET | [/api/v1/routing/sample](#op-get-api-v1-routing-sample) | Sample Routing |
| POST | [/api/v1/shipments/batch](#op-post-api-v1-shipments-batch) | Batch |
| POST | [/api/v1/shipments/batch-preview](#op-post-api-v1-shipments-batch-preview) | Batch Preview |
| POST | [/api/v1/shipments/batch-review-preview](#op-post-api-v1-shipments-batch-review-preview) | Review Preview |
| GET | [/api/v1/shipments/batch-template](#op-get-api-v1-shipments-batch-template) | Batch Template |
| GET | [/api/v1/shipments/batch/{shipment_id}](#op-get-api-v1-shipments-batch-shipment-id) | Uploaded Order |
| POST | [/api/v1/shipments/batch/{shipment_id}/quote](#op-post-api-v1-shipments-batch-shipment-id-quote) | Review Order |
| POST | [/api/v1/shipments/bulk/checkout](#op-post-api-v1-shipments-bulk-checkout) | Checkout |
| POST | [/api/v1/shipments/bulk/print-bundle](#op-post-api-v1-shipments-bulk-print-bundle) | Print Bundle |
| POST | [/api/v1/shipments/bulk/quote](#op-post-api-v1-shipments-bulk-quote) | Quote |
| POST | [/api/v1/shipments/bulk/review](#op-post-api-v1-shipments-bulk-review) | Review |
| GET | [/api/v1/shipments/manifest](#op-get-api-v1-shipments-manifest) | Manifest |
| GET | [/api/v1/shipments/{shipment_id}/dispute-draft](#op-get-api-v1-shipments-shipment-id-dispute-draft) | Get Draft |
| PUT | [/api/v1/shipments/{shipment_id}/dispute-draft](#op-put-api-v1-shipments-shipment-id-dispute-draft) | Save Draft |
| GET | [/api/v1/shipments/{shipment_id}/label/preview](#op-get-api-v1-shipments-shipment-id-label-preview) | Print Preview |
| GET | [/api/v1/shipping/claims/{case_id}](#op-get-api-v1-shipping-claims-case-id) | Claim Status |
| GET | [/api/v1/shipping/claims/{case_id}/evidence/{evidence_id}](#op-get-api-v1-shipping-claims-case-id-evidence-evidence-id) | Evidence Download |
| POST | [/api/v1/shipping/confirm-booking](#op-post-api-v1-shipping-confirm-booking) | Confirm |
| POST | [/api/v1/shipping/insurance-updates](#op-post-api-v1-shipping-insurance-updates) | Insurance Updates |
| GET | [/api/v1/shipping/insured-shipments](#op-get-api-v1-shipping-insured-shipments) | Insured List |
| GET | [/api/v1/shipping/native-orders](#op-get-api-v1-shipping-native-orders) | Native Order Statuses |
| POST | [/api/v1/shipping/native-orders/sync](#op-post-api-v1-shipping-native-orders-sync) | Synchronize |
| POST | [/api/v1/shipping/package-check](#op-post-api-v1-shipping-package-check) | Workspace Check |
| POST | [/api/v1/shipping/prepare-return](#op-post-api-v1-shipping-prepare-return) | Prepare Return |
| GET | [/api/v1/shipping/protection-quote](#op-get-api-v1-shipping-protection-quote) | Protection Quote |
| POST | [/api/v1/shipping/protection-quote](#op-post-api-v1-shipping-protection-quote) | Prepare Protection |
| POST | [/api/v1/shipping/quote-support](#op-post-api-v1-shipping-quote-support) | Quote Support |
| POST | [/api/v1/shipping/request-void](#op-post-api-v1-shipping-request-void) | Void |
| GET | [/api/v1/shipping/return-dropoff](#op-get-api-v1-shipping-return-dropoff) | Return Dropoff |
| GET | [/api/v1/shipping/return-requests/{request_id}](#op-get-api-v1-shipping-return-requests-request-id) | Return Status |
| POST | [/api/v1/shipping/submit-claim](#op-post-api-v1-shipping-submit-claim) | Submit Claim |
| POST | [/api/v1/shipping/tracking-webhooks](#op-post-api-v1-shipping-tracking-webhooks) | Tracking Webhooks |
| GET | [/api/v1/shipping/{shipment_id}/documents/{document}](#op-get-api-v1-shipping-shipment-id-documents-document) | Document |
| GET | [/api/v1/support/tickets](#op-get-api-v1-support-tickets) | Client Tickets |
| POST | [/api/v1/support/tickets/{ticket_id}/intervene](#op-post-api-v1-support-tickets-ticket-id-intervene) | Intervene |
| POST | [/api/v1/support/tickets/{ticket_id}/resolve](#op-post-api-v1-support-tickets-ticket-id-resolve) | Resolve |
| POST | [/api/v1/support/whatsapp/consent](#op-post-api-v1-support-whatsapp-consent) | Consent |
| POST | [/api/v1/support/whatsapp/status/{message_id}](#op-post-api-v1-support-whatsapp-status-message-id) | Status |
| POST | [/api/v1/tracking/webhook](#op-post-api-v1-tracking-webhook) | Webhook |
| GET | [/api/v1/wallet](#op-get-api-v1-wallet) | Wallet |
| POST | [/api/v1/workspace/invitations](#op-post-api-v1-workspace-invitations) | Invite |
| POST | [/api/v1/workspace/invitations/{invite_id}/cancel](#op-post-api-v1-workspace-invitations-invite-id-cancel) | Cancel |
| POST | [/api/v1/workspace/invitations/{invite_id}/resend](#op-post-api-v1-workspace-invitations-invite-id-resend) | Resend |
| GET | [/api/v1/workspace/settings](#op-get-api-v1-workspace-settings) | Settings |
| PATCH | [/api/v1/workspace/settings](#op-patch-api-v1-workspace-settings) | Company |
| GET | [/api/v1/workspace/stores](#op-get-api-v1-workspace-stores) | Stores |
| POST | [/api/v1/workspace/stores](#op-post-api-v1-workspace-stores) | Create Store |
| PATCH | [/api/v1/workspace/stores/{store_id}](#op-patch-api-v1-workspace-stores-store-id) | Store State |
| GET | [/api/v1/workspace/stores/{store_id}/connection](#op-get-api-v1-workspace-stores-store-id-connection) | Read |
| PUT | [/api/v1/workspace/stores/{store_id}/connection](#op-put-api-v1-workspace-stores-store-id-connection) | Save |
| GET | [/api/v1/workspace/stores/{store_id}/notifications](#op-get-api-v1-workspace-stores-store-id-notifications) | Notifications |
| POST | [/api/v1/workspace/stores/{store_id}/notifications/{notification_id}/retry](#op-post-api-v1-workspace-stores-store-id-notifications-notification-id-retry) | Retry |
| POST | [/api/v1/workspace/users](#op-post-api-v1-workspace-users) | Add Member |
| PATCH | [/api/v1/workspace/users/{member_id}](#op-patch-api-v1-workspace-users-member-id) | Member |
| GET | [/health](#op-get-health) | Health |
| POST | [/v1/rates](#op-post-v1-rates) | Get Rates |
| POST | [/v1/wallet/topups](#op-post-v1-wallet-topups) | Create Wallet Topup |
| GET | [/v1/whatsapp/quote-choice](#op-get-v1-whatsapp-quote-choice) | Resolve Quote Choice |
| POST | [/webhooks/stripe](#op-post-webhooks-stripe) | Stripe Webhook |
| POST | [/webhooks/twilio/whatsapp](#op-post-webhooks-twilio-whatsapp) | Inbound Whatsapp |

## Operation contracts

<a id="op-get-api-v1-admin-agents-metrics"></a>
### GET /api/v1/admin/agents/metrics

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/agents/routes.py:60](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/agents/routes.py#L60), `build_router.<locals>.metrics`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-analytics-dashboard"></a>
### GET /api/v1/admin/analytics/dashboard

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/dashboard_portal.py:107](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L107), `build_router.<locals>.platform_report`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "start_date",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "date",
      "title": "Start Date"
    }
  },
  {
    "name": "end_date",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "date",
      "title": "End Date"
    }
  },
  {
    "name": "environment",
    "in": "query",
    "required": false,
    "schema": {
      "enum": [
        "PRODUCTION",
        "SANDBOX"
      ],
      "type": "string",
      "default": "PRODUCTION",
      "title": "Environment"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-audit-invoice"></a>
### POST /api/v1/admin/audit/invoice

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/ai_engine.py:282](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ai_engine.py#L282), `build_router.<locals>.owner_audit`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "tenant_id",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/InvoiceInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-carriers"></a>
### GET /api/v1/admin/carriers

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:127](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L127), `carriers`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-carriers"></a>
### POST /api/v1/admin/carriers

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:138](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L138), `add_carrier`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CarrierCreate"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-delete-api-v1-admin-carriers-account-id"></a>
### DELETE /api/v1/admin/carriers/{account_id}

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:210](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L210), `remove_carrier`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "account_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Account Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-patch-api-v1-admin-carriers-account-id"></a>
### PATCH /api/v1/admin/carriers/{account_id}

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:183](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L183), `change_carrier`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "account_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Account Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CarrierUpdate"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-carriers-account-id-disable"></a>
### POST /api/v1/admin/carriers/{account_id}/disable

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:210](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L210), `remove_carrier`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "account_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Account Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-carriers-account-id-replace-credentials"></a>
### POST /api/v1/admin/carriers/{account_id}/replace-credentials

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/credential_rotation.py:32](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/credential_rotation.py#L32), `replace_credentials`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: `require_recent_admin_auth`.

Parameters:

```json
[
  {
    "name": "account_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Account Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CredentialReplacement"
      }
    }
  }
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-client-assistance-clients"></a>
### GET /api/v1/admin/client-assistance/clients

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/client_assistance.py:111](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/client_assistance.py#L111), `clients`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "q",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string",
      "maxLength": 200,
      "default": "",
      "title": "Q"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-client-assistance-events"></a>
### GET /api/v1/admin/client-assistance/events

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/client_assistance.py:164](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/client_assistance.py#L164), `events`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "tenant_id",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Tenant Id"
    }
  },
  {
    "name": "include_reads",
    "in": "query",
    "required": false,
    "schema": {
      "type": "boolean",
      "default": false,
      "title": "Include Reads"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-client-assistance-sessions"></a>
### POST /api/v1/admin/client-assistance/sessions

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/client_assistance.py:122](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/client_assistance.py#L122), `start`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/StartAssistance"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-delete-api-v1-admin-client-assistance-sessions-session-id"></a>
### DELETE /api/v1/admin/client-assistance/sessions/{session_id}

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/client_assistance.py:151](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/client_assistance.py#L151), `stop`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "session_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Session Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-individual-pricing"></a>
### GET /api/v1/admin/individual-pricing

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_portal.py:588](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_portal.py#L588), `read_individual_pricing`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-put-api-v1-admin-individual-pricing"></a>
### PUT /api/v1/admin/individual-pricing

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_portal.py:595](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_portal.py#L595), `update_individual_pricing`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/IndividualPricingUpdate"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-insurance-settlements"></a>
### POST /api/v1/admin/insurance/settlements

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/shipment_protection.py:2177](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/shipment_protection.py#L2177), `build_router.<locals>.platform_settlement`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PlatformSettlement"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-integrations-alerts"></a>
### GET /api/v1/admin/integrations/alerts

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/hubspot_crm.py:472](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/hubspot_crm.py#L472), `build_router.<locals>.integration_alerts`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-margins"></a>
### GET /api/v1/admin/margins

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:43](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L43), `margins`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "tenant_id",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Tenant Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-margins"></a>
### POST /api/v1/admin/margins

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_portal.py:569](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_portal.py#L569), `create_margin`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/MarginCreate"
      }
    }
  }
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/MarginCreated"
        }
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-delete-api-v1-admin-margins-rule-id"></a>
### DELETE /api/v1/admin/margins/{rule_id}

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:80](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L80), `retire_margin`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "rule_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Rule Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-put-api-v1-admin-margins-rule-id"></a>
### PUT /api/v1/admin/margins/{rule_id}

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:54](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L54), `update_margin`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "rule_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Rule Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/MarginCreate"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-platform-carriers"></a>
### GET /api/v1/admin/platform-carriers

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/platform_carriers.py:107](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/platform_carriers.py#L107), `list_connections`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-platform-carriers"></a>
### POST /api/v1/admin/platform-carriers

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/platform_carriers.py:114](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/platform_carriers.py#L114), `create`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PlatformConnection"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-platform-carriers-capabilities"></a>
### GET /api/v1/admin/platform-carriers/capabilities

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/platform_carriers.py:134](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/platform_carriers.py#L134), `capabilities`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-delete-api-v1-admin-platform-carriers-connection-id"></a>
### DELETE /api/v1/admin/platform-carriers/{connection_id}

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/platform_carriers.py:124](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/platform_carriers.py#L124), `retire`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "connection_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Connection Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-put-api-v1-admin-platform-carriers-connection-id"></a>
### PUT /api/v1/admin/platform-carriers/{connection_id}

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/platform_carriers.py:119](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/platform_carriers.py#L119), `update`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "connection_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Connection Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PlatformConnection"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-platform-carriers-connection-id-disable"></a>
### POST /api/v1/admin/platform-carriers/{connection_id}/disable

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/platform_carriers.py:124](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/platform_carriers.py#L124), `retire`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "connection_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Connection Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-platform-carriers-connection-id-native-orders-reconcile"></a>
### POST /api/v1/admin/platform-carriers/{connection_id}/native-orders/reconcile

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/automation_three_partners.py:460](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L460), `build_native_router.<locals>.reconcile_order`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "connection_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Connection Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/NativeOrderReconciliation"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-platform-carriers-connection-id-native-settings"></a>
### GET /api/v1/admin/platform-carriers/{connection_id}/native-settings

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/automation_three_partners.py:526](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L526), `build_native_router.<locals>.read_configuration`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "connection_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Connection Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-put-api-v1-admin-platform-carriers-connection-id-native-settings"></a>
### PUT /api/v1/admin/platform-carriers/{connection_id}/native-settings

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/automation_three_partners.py:486](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L486), `build_native_router.<locals>.configure`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "connection_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Connection Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/NativeProviderSettings"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-platform-carriers-connection-id-quote-diagnostics"></a>
### GET /api/v1/admin/platform-carriers/{connection_id}/quote-diagnostics

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/workspace_settings.py:178](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L178), `build_router.<locals>.diagnostics`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "connection_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Connection Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-platform-carriers-connection-id-upgrade-sendcloud"></a>
### POST /api/v1/admin/platform-carriers/{connection_id}/upgrade-sendcloud

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/platform_carriers.py:141](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/platform_carriers.py#L141), `upgrade_sendcloud`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "connection_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Connection Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-platform-carriers-connection-id-verify"></a>
### POST /api/v1/admin/platform-carriers/{connection_id}/verify

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/platform_carriers.py:206](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/platform_carriers.py#L206), `verify_connection`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: `ShippoAdapter(None, secret, environment=row['environment']).authentication`, `httpx.BasicAuth`.

Parameters:

```json
[
  {
    "name": "connection_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Connection Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-sandbox-whatsapp-setup"></a>
### POST /api/v1/admin/sandbox/whatsapp-setup

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/sandbox_hooks.py:301](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/sandbox_hooks.py#L301), `build_router.<locals>.setup_whatsapp`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: `require_sandbox_environment`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/WhatsAppSandboxSetup"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-shipments-manifest"></a>
### GET /api/v1/admin/shipments/manifest

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/advanced_logistics.py:377](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L377), `build_router.<locals>.owner_manifest`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-shipments-shipment-id-dispute-draft"></a>
### GET /api/v1/admin/shipments/{shipment_id}/dispute-draft

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/workspace_settings.py:204](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L204), `build_router.<locals>.admin_get_draft`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  },
  {
    "name": "tenant_id",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-put-api-v1-admin-shipments-shipment-id-dispute-draft"></a>
### PUT /api/v1/admin/shipments/{shipment_id}/dispute-draft

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/workspace_settings.py:207](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L207), `build_router.<locals>.admin_save_draft`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  },
  {
    "name": "tenant_id",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Draft"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-support-tickets"></a>
### GET /api/v1/admin/support/tickets

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/dashboard_portal.py:198](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L198), `build_router.<locals>.all_tickets`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "environment",
    "in": "query",
    "required": false,
    "schema": {
      "enum": [
        "PRODUCTION",
        "SANDBOX"
      ],
      "type": "string",
      "default": "PRODUCTION",
      "title": "Environment"
    }
  },
  {
    "name": "active_only",
    "in": "query",
    "required": false,
    "schema": {
      "type": "boolean",
      "default": false,
      "title": "Active Only"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-support-tickets-ticket-id-intervene"></a>
### POST /api/v1/admin/support/tickets/{ticket_id}/intervene

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/dashboard_portal.py:209](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L209), `build_router.<locals>.admin_intervene`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "ticket_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Ticket Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Intervention"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-support-tickets-ticket-id-resolve"></a>
### POST /api/v1/admin/support/tickets/{ticket_id}/resolve

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/dashboard_portal.py:221](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L221), `build_router.<locals>.admin_resolve`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "ticket_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Ticket Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-support-whatsapp-bindings"></a>
### GET /api/v1/admin/support/whatsapp/bindings

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/support_alert_controls.py:16](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/support_alert_controls.py#L16), `build_router.<locals>.bindings`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-patch-api-v1-admin-support-whatsapp-bindings-binding-id"></a>
### PATCH /api/v1/admin/support/whatsapp/bindings/{binding_id}

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/support_alert_controls.py:32](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/support_alert_controls.py#L32), `build_router.<locals>.pause`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "binding_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Binding Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/AlertPause"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-tenants"></a>
### GET /api/v1/admin/tenants

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:33](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L33), `tenants`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "limit",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "maximum": 500,
      "minimum": 1,
      "default": 200,
      "title": "Limit"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-admin-tenants"></a>
### POST /api/v1/admin/tenants

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_portal.py:561](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_portal.py#L561), `create_tenant`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TenantCreate"
      }
    }
  }
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/TenantCreated"
        }
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-patch-api-v1-admin-tenants-tenant-id-seller-classification"></a>
### PATCH /api/v1/admin/tenants/{tenant_id}/seller-classification

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:237](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L237), `update_seller_classification`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "tenant_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/SellerClassificationUpdate"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-admin-transactions"></a>
### GET /api/v1/admin/transactions

Platform owner dependency; additional source/helper guards apply.

Implementation: [backend/admin_management.py:223](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/admin_management.py#L223), `transactions`.

Declared dependencies: `HTTPBearer`, `authenticate_platform_owner`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "tenant_id",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Tenant Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-agents-customs-information"></a>
### POST /api/v1/agents/customs/information

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/agents/routes.py:46](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/agents/routes.py#L46), `build_router.<locals>.information`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `engine.dispatch_permission`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CustomsItems"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-agents-customs-suggest"></a>
### POST /api/v1/agents/customs/suggest

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/agents/routes.py:29](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/agents/routes.py#L29), `build_router.<locals>.customs`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `engine.dispatch_permission`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Description"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-agents-interpret"></a>
### POST /api/v1/agents/interpret

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/agents/routes.py:20](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/agents/routes.py#L20), `build_router.<locals>.interpret`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/MessageRequest"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-agents-quote"></a>
### POST /api/v1/agents/quote

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/agents/routes.py:24](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/agents/routes.py#L24), `build_router.<locals>.quote`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RatingRequest"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-analytics-carrier-performance"></a>
### GET /api/v1/analytics/carrier-performance

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [main.py:2361](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/main.py#L2361), `carrier_performance`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "destination_country",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Destination Country"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-analytics-reports"></a>
### GET /api/v1/analytics/reports

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tracking_and_support.py:347](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tracking_and_support.py#L347), `build_router.<locals>.reports`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "start_date",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "date",
      "title": "Start Date"
    }
  },
  {
    "name": "end_date",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "date",
      "title": "End Date"
    }
  },
  {
    "name": "page",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "maximum": 10000,
      "minimum": 1,
      "default": 1,
      "title": "Page"
    }
  },
  {
    "name": "page_size",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "maximum": 500,
      "minimum": 1,
      "default": 100,
      "title": "Page Size"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-analytics-tracking-readiness"></a>
### GET /api/v1/analytics/tracking-readiness

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/delivery_quality.py:45](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/delivery_quality.py#L45), `build_router.<locals>.readiness`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `validate_tenant_query`.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}`.

Parameters:

```json
[
  {
    "name": "origin_country",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Origin Country"
    }
  },
  {
    "name": "destination_country",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Destination Country"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-audit-invoice"></a>
### POST /api/v1/audit/invoice

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/ai_engine.py:262](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ai_engine.py#L262), `build_router.<locals>.audit`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/InvoiceInput"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-audit-preview"></a>
### POST /api/v1/audit/preview

Preview/configuration guard; not live integration evidence.

Implementation: [backend/ai_engine.py:290](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ai_engine.py#L290), `build_router.<locals>.audit_preview`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/InvoiceInput"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-auth-accept-invitation"></a>
### POST /api/v1/auth/accept-invitation

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/workspace_settings.py:130](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L130), `build_router.<locals>.accept`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Accept"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-auth-forgot-password"></a>
### POST /api/v1/auth/forgot-password

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/identity.py:280](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/identity.py#L280), `forgot_password`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RecoveryRequest"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-auth-logout"></a>
### POST /api/v1/auth/logout

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/identity.py:245](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/identity.py#L245), `logout`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-auth-me"></a>
### GET /api/v1/auth/me

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/identity.py:223](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/identity.py#L223), `me`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-patch-api-v1-auth-me"></a>
### PATCH /api/v1/auth/me

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/identity.py:233](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/identity.py#L233), `update_me`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ProfileUpdate"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-auth-register"></a>
### POST /api/v1/auth/register

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/identity.py:344](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/identity.py#L344), `register_account`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RegistrationStart"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-auth-register-verify"></a>
### POST /api/v1/auth/register/verify

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/identity.py:348](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/identity.py#L348), `verify_account`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RegistrationVerify"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-auth-renew"></a>
### POST /api/v1/auth/renew

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/identity.py:129](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/identity.py#L129), `renew`.

Declared dependencies: none.
Guard/helper calls in handler: `hashlib.sha256(request.headers.get('authorization', '').encode()).hexdigest`, `request.headers.get('authorization', '').encode`, `settings.auth_jwt_secret.get_secret_value`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-auth-reset-password"></a>
### POST /api/v1/auth/reset-password

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/identity.py:309](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/identity.py#L309), `reset_password`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ResetPassword"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-auth-token"></a>
### POST /api/v1/auth/token

Identity/registration/recovery-specific validation and limits.

Implementation: [backend/identity.py:74](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/identity.py#L74), `token`.

Declared dependencies: none.
Guard/helper calls in handler: `settings.auth_jwt_secret.get_secret_value`, `settings.auth_jwt_secret.get_secret_value().encode`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Login"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-automation-bulk-fulfill"></a>
### POST /api/v1/automation/bulk-fulfill

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_freight_engine.py:585](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_freight_engine.py#L585), `build_router.<locals>.bulk`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-automation-cargo-weight"></a>
### POST /api/v1/automation/cargo-weight

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_freight_engine.py:574](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_freight_engine.py#L574), `build_router.<locals>.cargo_weight`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Cargo"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-automation-customs-shipment-id"></a>
### GET /api/v1/automation/customs/{shipment_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_freight_engine.py:578](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_freight_engine.py#L578), `build_router.<locals>.customs`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-automation-orders-shipment-id-reconcile"></a>
### POST /api/v1/automation/orders/{shipment_id}/reconcile

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_freight_engine.py:582](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_freight_engine.py#L582), `build_router.<locals>.reconcile`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-billing-carts"></a>
### POST /api/v1/billing/carts

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/card_checkout.py:137](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/card_checkout.py#L137), `build_router.<locals>.create`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CardCart"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-billing-carts-cart-id-complete"></a>
### POST /api/v1/billing/carts/{cart_id}/complete

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/card_checkout.py:140](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/card_checkout.py#L140), `build_router.<locals>.complete`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "cart_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Cart Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-billing-create-checkout"></a>
### POST /api/v1/billing/create-checkout

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/payment_gateway.py:354](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/payment_gateway.py#L354), `build_router.<locals>.create_checkout`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `require_payment_gateway`.

Inline role conditions: `context.role not in FINANCE_ROLES`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CheckoutInput"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-billing-test-topup"></a>
### POST /api/v1/billing/test-topup

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/sandbox_hooks.py:284](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/sandbox_hooks.py#L284), `build_router.<locals>.test_topup`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TestTopupInput"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-billing-topups-topup-id"></a>
### GET /api/v1/billing/topups/{topup_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/payment_gateway.py:391](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/payment_gateway.py#L391), `build_router.<locals>.topup_status`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in FINANCE_ROLES`.

Parameters:

```json
[
  {
    "name": "topup_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Topup Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-billing-topups-topup-id-reconcile"></a>
### POST /api/v1/billing/topups/{topup_id}/reconcile

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/payment_gateway.py:387](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/payment_gateway.py#L387), `build_router.<locals>.reconcile`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "topup_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Topup Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-billing-wallet-activity"></a>
### GET /api/v1/billing/wallet-activity

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/payment_gateway.py:375](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/payment_gateway.py#L375), `build_router.<locals>.activity`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in FINANCE_ROLES`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-billing-webhooks-stripe"></a>
### POST /api/v1/billing/webhooks/stripe

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [backend/payment_gateway.py:189](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/payment_gateway.py#L189), `snapshot_webhook`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-catalog-addresses"></a>
### GET /api/v1/catalog/addresses

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:184](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L184), `build_router.<locals>.routes.<locals>.listing`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Parameters:

```json
[
  {
    "name": "q",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string",
      "maxLength": 100,
      "default": "",
      "title": "Q"
    }
  },
  {
    "name": "offset",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "maximum": 10000,
      "minimum": 0,
      "default": 0,
      "title": "Offset"
    }
  },
  {
    "name": "limit",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "maximum": 100,
      "minimum": 1,
      "default": 50,
      "title": "Limit"
    }
  },
  {
    "name": "address_role",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "enum": [
            "SENDER",
            "RETURN",
            "PICKUP",
            "INVOICE"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Address Role"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-catalog-addresses"></a>
### POST /api/v1/catalog/addresses

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:193](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L193), `build_router.<locals>.routes.<locals>.create`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/AddressInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-delete-api-v1-catalog-addresses-record-id"></a>
### DELETE /api/v1/catalog/addresses/{record_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:207](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L207), `build_router.<locals>.routes.<locals>.archive`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Parameters:

```json
[
  {
    "name": "record_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Record Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ArchiveInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-put-api-v1-catalog-addresses-record-id"></a>
### PUT /api/v1/catalog/addresses/{record_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:200](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L200), `build_router.<locals>.routes.<locals>.update`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Parameters:

```json
[
  {
    "name": "record_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Record Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/AddressInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-catalog-contacts"></a>
### GET /api/v1/catalog/contacts

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:184](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L184), `build_router.<locals>.routes.<locals>.listing`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Parameters:

```json
[
  {
    "name": "q",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string",
      "maxLength": 100,
      "default": "",
      "title": "Q"
    }
  },
  {
    "name": "offset",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "maximum": 10000,
      "minimum": 0,
      "default": 0,
      "title": "Offset"
    }
  },
  {
    "name": "limit",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "maximum": 100,
      "minimum": 1,
      "default": 50,
      "title": "Limit"
    }
  },
  {
    "name": "address_role",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "enum": [
            "SENDER",
            "RETURN",
            "PICKUP",
            "INVOICE"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Address Role"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-catalog-contacts"></a>
### POST /api/v1/catalog/contacts

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:193](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L193), `build_router.<locals>.routes.<locals>.create`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ContactInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-delete-api-v1-catalog-contacts-record-id"></a>
### DELETE /api/v1/catalog/contacts/{record_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:207](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L207), `build_router.<locals>.routes.<locals>.archive`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Parameters:

```json
[
  {
    "name": "record_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Record Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ArchiveInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-put-api-v1-catalog-contacts-record-id"></a>
### PUT /api/v1/catalog/contacts/{record_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:200](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L200), `build_router.<locals>.routes.<locals>.update`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Parameters:

```json
[
  {
    "name": "record_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Record Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ContactInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-catalog-products"></a>
### GET /api/v1/catalog/products

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:184](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L184), `build_router.<locals>.routes.<locals>.listing`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Parameters:

```json
[
  {
    "name": "q",
    "in": "query",
    "required": false,
    "schema": {
      "type": "string",
      "maxLength": 100,
      "default": "",
      "title": "Q"
    }
  },
  {
    "name": "offset",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "maximum": 10000,
      "minimum": 0,
      "default": 0,
      "title": "Offset"
    }
  },
  {
    "name": "limit",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "maximum": 100,
      "minimum": 1,
      "default": 50,
      "title": "Limit"
    }
  },
  {
    "name": "address_role",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "enum": [
            "SENDER",
            "RETURN",
            "PICKUP",
            "INVOICE"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Address Role"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-catalog-products"></a>
### POST /api/v1/catalog/products

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:193](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L193), `build_router.<locals>.routes.<locals>.create`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ProductInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-catalog-products-by-sku-sku"></a>
### GET /api/v1/catalog/products/by-sku/{sku}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:225](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L225), `build_router.<locals>.by_sku`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "sku",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Sku"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-delete-api-v1-catalog-products-record-id"></a>
### DELETE /api/v1/catalog/products/{record_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:207](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L207), `build_router.<locals>.routes.<locals>.archive`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Parameters:

```json
[
  {
    "name": "record_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Record Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ArchiveInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-put-api-v1-catalog-products-record-id"></a>
### PUT /api/v1/catalog/products/{record_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/tenant_catalogs.py:200](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tenant_catalogs.py#L200), `build_router.<locals>.routes.<locals>.update`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permission`.

Parameters:

```json
[
  {
    "name": "record_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Record Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ProductInput"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-checkout-context"></a>
### GET /api/v1/checkout/context

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/customer_checkout.py:130](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/customer_checkout.py#L130), `build_router.<locals>.context`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "offer_id",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Offer Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-checkout-hs-search"></a>
### POST /api/v1/checkout/hs-search

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/customer_checkout.py:118](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/customer_checkout.py#L118), `build_router.<locals>.hs_search`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TariffQuery"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-checkout-prepare"></a>
### POST /api/v1/checkout/prepare

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/customer_checkout.py:142](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/customer_checkout.py#L142), `build_router.<locals>.prepare`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `user.role != 'DISPATCHER'`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CheckoutPrepare"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-checkout-shipment-id-commercial-invoice-pdf"></a>
### GET /api/v1/checkout/{shipment_id}/commercial-invoice.pdf

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/customer_checkout.py:218](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/customer_checkout.py#L218), `build_router.<locals>.invoice`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-checkout-shipment-id-receipt-pdf"></a>
### GET /api/v1/checkout/{shipment_id}/receipt.pdf

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/customer_checkout.py:201](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/customer_checkout.py#L201), `build_router.<locals>.receipt`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `user.role == 'DISPATCHER'`.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-config"></a>
### GET /api/v1/config

Public UI/help/health/config surface; inspect projection.

Implementation: [main.py:2292](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/main.py#L2292), `public_config`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-conversational-process-message"></a>
### POST /api/v1/conversational/process-message

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/agents/conversational_gateway.py:661](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/agents/conversational_gateway.py#L661), `build_router.<locals>.process_message`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `validate_tenant_query`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ConversationMessage"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-countries"></a>
### GET /api/v1/countries

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/advanced_logistics.py:381](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L381), `build_router.<locals>.countries`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-crm-sync-tenant"></a>
### POST /api/v1/crm/sync-tenant

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/hubspot_crm.py:454](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/hubspot_crm.py#L454), `build_router.<locals>.sync_tenant`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN'}`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/SyncTenantInput"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "202": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-customs-declaration"></a>
### POST /api/v1/customs/declaration

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/advanced_logistics.py:186](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L186), `build_router.<locals>.declaration`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/DeclarationInput"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-customs-harmonize"></a>
### POST /api/v1/customs/harmonize

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/ai_engine.py:240](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ai_engine.py#L240), `build_router.<locals>.harmonize`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/DescriptionInput"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-dispatch-workspace-orders"></a>
### GET /api/v1/dispatch-workspace/orders

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dispatch_workspace.py:157](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dispatch_workspace.py#L157), `build_router.<locals>.inbox`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Parameters:

```json
[
  {
    "name": "offset",
    "in": "query",
    "required": false,
    "schema": {
      "type": "integer",
      "default": 0,
      "title": "Offset"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-dispatch-workspace-orders-shipment-id"></a>
### GET /api/v1/dispatch-workspace/orders/{shipment_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dispatch_workspace.py:195](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dispatch_workspace.py#L195), `build_router.<locals>.prepare`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-dispatch-workspace-orders-shipment-id-prepare"></a>
### POST /api/v1/dispatch-workspace/orders/{shipment_id}/prepare

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dispatch_workspace.py:202](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dispatch_workspace.py#L202), `build_router.<locals>.save_preparation`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Order"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-dispatch-workspace-print-bundle"></a>
### POST /api/v1/dispatch-workspace/print-bundle

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dispatch_workspace.py:230](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dispatch_workspace.py#L230), `build_router.<locals>.print_bundle`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Selection"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-dispatch-workspace-process"></a>
### POST /api/v1/dispatch-workspace/process

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dispatch_workspace.py:215](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dispatch_workspace.py#L215), `build_router.<locals>.process`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Selection"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-dispatch-workspace-sync-store-id"></a>
### POST /api/v1/dispatch-workspace/sync/{store_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dispatch_workspace.py:176](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dispatch_workspace.py#L176), `build_router.<locals>.sync`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Parameters:

```json
[
  {
    "name": "store_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Store Id"
    }
  },
  {
    "name": "after",
    "in": "query",
    "required": false,
    "schema": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "After"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-dispatch-manifests-close"></a>
### POST /api/v1/dispatch/manifests/close

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/manifest_service.py:393](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/manifest_service.py#L393), `build_router.<locals>.close`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CloseManifest"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/ManifestResult"
        }
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-dispatch-manifests-preview"></a>
### POST /api/v1/dispatch/manifests/preview

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/manifest_service.py:389](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/manifest_service.py#L389), `build_router.<locals>.preview`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PreviewManifest"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "items": {
            "$ref": "#/components/schemas/ManifestCandidateSummary"
          },
          "type": "array",
          "title": "Response Preview Api V1 Dispatch Manifests Preview Post"
        }
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-dispatch-manifests-manifest-id"></a>
### GET /api/v1/dispatch/manifests/{manifest_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/manifest_service.py:398](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/manifest_service.py#L398), `build_router.<locals>.status`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "manifest_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Manifest Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/ManifestResult"
        }
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-dispatch-manifests-manifest-id-document"></a>
### GET /api/v1/dispatch/manifests/{manifest_id}/document

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/manifest_service.py:401](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/manifest_service.py#L401), `build_router.<locals>.document`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "manifest_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Manifest Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-dispatch-manifests-manifest-id-download"></a>
### GET /api/v1/dispatch/manifests/{manifest_id}/download

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/manifest_service.py:404](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/manifest_service.py#L404), `build_router.<locals>.download`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "manifest_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Manifest Id"
    }
  },
  {
    "name": "token",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Token"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-dispatch-summary"></a>
### GET /api/v1/dispatch/summary

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dashboard_portal.py:61](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L61), `build_router.<locals>.dispatch_summary`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-finance-audit-invoice-upload"></a>
### POST /api/v1/finance/audit-invoice-upload

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/invoice_upload.py:162](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/invoice_upload.py#L162), `build_router.<locals>.upload`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}`.

Request body:

```json
{
  "content": {
    "multipart/form-data": {
      "schema": {
        "$ref": "#/components/schemas/Body_upload_api_v1_finance_audit_invoice_upload_post"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-finance-billing-disputes"></a>
### GET /api/v1/finance/billing-disputes

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/invoice_upload.py:225](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/invoice_upload.py#L225), `build_router.<locals>.disputes`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-help-search-agent"></a>
### POST /api/v1/help/search-agent

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/agents/routes.py:56](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/agents/routes.py#L56), `build_router.<locals>.search`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/HelpQuestion"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-integration-pull-orders"></a>
### POST /api/v1/integration/pull-orders

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/ecommerce_sync.py:444](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ecommerce_sync.py#L444), `build_router.<locals>.pull_orders`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-integration-return-webhooks-store-id"></a>
### POST /api/v1/integration/return-webhooks/{store_id}

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [backend/ecommerce_sync.py:371](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ecommerce_sync.py#L371), `build_router.<locals>.return_webhook`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "store_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Store Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-integration-tracking-events"></a>
### GET /api/v1/integration/tracking-events

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/ecommerce_sync.py:384](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ecommerce_sync.py#L384), `build_router.<locals>.tracking_events`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-integration-tracking-events-event-id-reconcile"></a>
### POST /api/v1/integration/tracking-events/{event_id}/reconcile

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/ecommerce_sync.py:394](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ecommerce_sync.py#L394), `build_router.<locals>.reconcile_tracking`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN'}`.

Parameters:

```json
[
  {
    "name": "event_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Event Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-integration-tracking-events-event-id-return-reference"></a>
### POST /api/v1/integration/tracking-events/{event_id}/return-reference

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/ecommerce_sync.py:424](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ecommerce_sync.py#L424), `build_router.<locals>.link_return`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN'}`.

Parameters:

```json
[
  {
    "name": "event_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Event Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ReturnReference"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-integration-webhooks-store-id"></a>
### POST /api/v1/integration/webhooks/{store_id}

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [backend/ecommerce_sync.py:376](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ecommerce_sync.py#L376), `build_router.<locals>.native_webhook`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "store_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Store Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-integrations-ecommerce-orders-sync"></a>
### POST /api/v1/integrations/ecommerce/orders-sync

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/ecommerce_inbound.py:182](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ecommerce_inbound.py#L182), `build_router.<locals>.orders`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "store_id",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Store Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-integrations-hubspot-webhook"></a>
### POST /api/v1/integrations/hubspot-webhook

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [backend/hubspot_provisioning.py:49](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/hubspot_provisioning.py#L49), `webhook`.

Declared dependencies: none.
Guard/helper calls in handler: `verify_signature`.

Request body:

```json
null
```

Documented responses:

```json
{
  "202": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-integrations-whatsapp-outbound-status-part-id"></a>
### POST /api/v1/integrations/whatsapp/outbound-status/{part_id}

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/whatsapp_queue.py:301](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/whatsapp_queue.py#L301), `build_media_status_router.<locals>.status`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "part_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "integer",
      "title": "Part Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-integrations-whatsapp-webhook"></a>
### POST /api/v1/integrations/whatsapp/webhook

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [backend/whatsapp_bot.py:86](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/whatsapp_bot.py#L86), `whatsapp_webhook`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-logistics-cargo-weight"></a>
### POST /api/v1/logistics/cargo-weight

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/advanced_logistics.py:178](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L178), `build_router.<locals>.cargo_weight`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Cargo"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-logistics-package-guidance"></a>
### POST /api/v1/logistics/package-guidance

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/package_guidance.py:159](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/package_guidance.py#L159), `build_router.<locals>.public_guidance`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PackageCheck"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-logistics-weight"></a>
### POST /api/v1/logistics/weight

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/advanced_logistics.py:174](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L174), `build_router.<locals>.weight`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ParcelInput"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-profile"></a>
### GET /api/v1/profile

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/dashboard_portal.py:84](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L84), `build_router.<locals>.profile`.

Declared dependencies: none.
Guard/helper calls in handler: `authenticate`, `authenticate_platform_owner`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-rates-preview"></a>
### POST /api/v1/rates/preview

Preview/configuration guard; not live integration evidence.

Implementation: [backend/advanced_logistics.py:190](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L190), `build_router.<locals>.rates_preview`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "additionalProperties": true,
        "type": "object",
        "title": "Body"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-rates-sample"></a>
### POST /api/v1/rates/sample

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/advanced_logistics.py:199](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L199), `build_router.<locals>.sample_rates`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "additionalProperties": true,
        "type": "object",
        "title": "Body"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-routing-disruptions"></a>
### GET /api/v1/routing/disruptions

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/ai_engine.py:247](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/ai_engine.py#L247), `build_router.<locals>.routing`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "origin",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Origin"
    }
  },
  {
    "name": "destination",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Destination"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-routing-preview"></a>
### GET /api/v1/routing/preview

Preview/configuration guard; not live integration evidence.

Implementation: [backend/advanced_logistics.py:211](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L211), `build_router.<locals>.routing_preview`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "origin",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Origin"
    }
  },
  {
    "name": "destination",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Destination"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-routing-sample"></a>
### GET /api/v1/routing/sample

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/advanced_logistics.py:205](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L205), `build_router.<locals>.sample_routing`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "origin",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Origin"
    }
  },
  {
    "name": "destination",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Destination"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipments-batch"></a>
### POST /api/v1/shipments/batch

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/advanced_logistics.py:221](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L221), `build_router.<locals>.batch`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-shipments-batch-preview"></a>
### POST /api/v1/shipments/batch-preview

Preview/configuration guard; not live integration evidence.

Implementation: [backend/advanced_logistics.py:252](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L252), `build_router.<locals>.batch_preview`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-shipments-batch-review-preview"></a>
### POST /api/v1/shipments/batch-review-preview

Preview/configuration guard; not live integration evidence.

Implementation: [backend/advanced_logistics.py:289](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L289), `build_router.<locals>.review_preview`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Order"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-shipments-batch-template"></a>
### GET /api/v1/shipments/batch-template

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/advanced_logistics.py:285](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L285), `build_router.<locals>.batch_template`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "extended",
    "in": "query",
    "required": false,
    "schema": {
      "type": "boolean",
      "default": false,
      "title": "Extended"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-shipments-batch-shipment-id"></a>
### GET /api/v1/shipments/batch/{shipment_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/advanced_logistics.py:302](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L302), `build_router.<locals>.uploaded_order`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}`.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipments-batch-shipment-id-quote"></a>
### POST /api/v1/shipments/batch/{shipment_id}/quote

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/advanced_logistics.py:312](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L312), `build_router.<locals>.review_order`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}`.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CSVCustomsReview"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipments-bulk-checkout"></a>
### POST /api/v1/shipments/bulk/checkout

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/bulk_checkout.py:141](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/bulk_checkout.py#L141), `build_router.<locals>.checkout`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CheckoutSelection"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipments-bulk-print-bundle"></a>
### POST /api/v1/shipments/bulk/print-bundle

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/bulk_checkout.py:145](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/bulk_checkout.py#L145), `build_router.<locals>.print_bundle`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/OrderSelection"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipments-bulk-quote"></a>
### POST /api/v1/shipments/bulk/quote

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/bulk_checkout.py:129](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/bulk_checkout.py#L129), `build_router.<locals>.quote`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Inline role conditions: `context.role != 'DISPATCHER'`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/OrderSelection"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipments-bulk-review"></a>
### POST /api/v1/shipments/bulk/review

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/bulk_checkout.py:125](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/bulk_checkout.py#L125), `build_router.<locals>.review`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `permitted`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/OrderSelection"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-shipments-manifest"></a>
### GET /api/v1/shipments/manifest

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/advanced_logistics.py:370](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L370), `build_router.<locals>.manifest`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `validate_tenant_query`.

Inline role conditions: `context.role != 'DISPATCHER'`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-shipments-shipment-id-dispute-draft"></a>
### GET /api/v1/shipments/{shipment_id}/dispute-draft

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/workspace_settings.py:161](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L161), `build_router.<locals>.get_draft`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}`.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-put-api-v1-shipments-shipment-id-dispute-draft"></a>
### PUT /api/v1/shipments/{shipment_id}/dispute-draft

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/workspace_settings.py:167](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L167), `build_router.<locals>.save_draft`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}`.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Draft"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-shipments-shipment-id-label-preview"></a>
### GET /api/v1/shipments/{shipment_id}/label/preview

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/sandbox_hooks.py:294](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/sandbox_hooks.py#L294), `build_router.<locals>.print_preview`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `request.app.state.finance.authorize_label_preview`.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-shipping-claims-case-id"></a>
### GET /api/v1/shipping/claims/{case_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/shipment_protection.py:1987](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/shipment_protection.py#L1987), `build_router.<locals>.claim_status`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `require_claim_role`.

Parameters:

```json
[
  {
    "name": "case_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Case Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-shipping-claims-case-id-evidence-evidence-id"></a>
### GET /api/v1/shipping/claims/{case_id}/evidence/{evidence_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/shipment_protection.py:2039](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/shipment_protection.py#L2039), `build_router.<locals>.evidence_download`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `require_claim_role`.

Parameters:

```json
[
  {
    "name": "case_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Case Id"
    }
  },
  {
    "name": "evidence_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Evidence Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-confirm-booking"></a>
### POST /api/v1/shipping/confirm-booking

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_three_partners.py:2063](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L2063), `build_router.<locals>.confirm`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/BookingRequest"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-insurance-updates"></a>
### POST /api/v1/shipping/insurance-updates

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [backend/shipment_protection.py:2069](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/shipment_protection.py#L2069), `build_router.<locals>.insurance_updates`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-shipping-insured-shipments"></a>
### GET /api/v1/shipping/insured-shipments

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/shipment_protection.py:1695](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/shipment_protection.py#L1695), `build_router.<locals>.insured_list`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `require_claim_role`, `validate_tenant_query`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-shipping-native-orders"></a>
### GET /api/v1/shipping/native-orders

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_three_partners.py:570](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L570), `build_native_router.<locals>.native_order_statuses`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `authorize`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-native-orders-sync"></a>
### POST /api/v1/shipping/native-orders/sync

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_three_partners.py:541](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L541), `build_native_router.<locals>.synchronize`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `authorize`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/NativeOrderSelection"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-package-check"></a>
### POST /api/v1/shipping/package-check

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/package_guidance.py:163](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/package_guidance.py#L163), `build_router.<locals>.workspace_check`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/PackageCheck"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-prepare-return"></a>
### POST /api/v1/shipping/prepare-return

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_three_partners.py:2080](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L2080), `build_router.<locals>.prepare_return`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `validate_tenant_query`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "anyOf": [
          {
            "$ref": "#/components/schemas/ReturnRequest"
          },
          {
            "items": {
              "$ref": "#/components/schemas/ReturnCommand"
            },
            "type": "array"
          }
        ],
        "title": "Body"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-shipping-protection-quote"></a>
### GET /api/v1/shipping/protection-quote

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/shipment_protection.py:1614](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/shipment_protection.py#L1614), `build_router.<locals>.protection_quote`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "offer_id",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Offer Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-protection-quote"></a>
### POST /api/v1/shipping/protection-quote

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/shipment_protection.py:1681](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/shipment_protection.py#L1681), `build_router.<locals>.prepare_protection`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}`.

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "type": "object",
        "additionalProperties": true,
        "title": "Body"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-quote-support"></a>
### POST /api/v1/shipping/quote-support

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/package_guidance.py:137](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/package_guidance.py#L137), `build_router.<locals>.quote_support`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/QuoteSupport"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-request-void"></a>
### POST /api/v1/shipping/request-void

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_three_partners.py:2076](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L2076), `build_router.<locals>.void`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/VoidRequest"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-shipping-return-dropoff"></a>
### GET /api/v1/shipping/return-dropoff

Scoped signed return-document capability token.

Implementation: [backend/automation_three_partners.py:2096](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L2096), `build_router.<locals>.return_dropoff`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "token",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Token"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-shipping-return-requests-request-id"></a>
### GET /api/v1/shipping/return-requests/{request_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_three_partners.py:2089](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L2089), `build_router.<locals>.return_status`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `validate_tenant_query`.

Parameters:

```json
[
  {
    "name": "request_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-submit-claim"></a>
### POST /api/v1/shipping/submit-claim

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/shipment_protection.py:1738](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/shipment_protection.py#L1738), `build_router.<locals>.submit_claim`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: `require_claim_role`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-shipping-tracking-webhooks"></a>
### POST /api/v1/shipping/tracking-webhooks

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [backend/automation_three_partners.py:471](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L471), `build_native_router.<locals>.tracking_webhooks`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-shipping-shipment-id-documents-document"></a>
### GET /api/v1/shipping/{shipment_id}/documents/{document}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/automation_three_partners.py:2105](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/automation_three_partners.py#L2105), `build_router.<locals>.document`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "shipment_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  },
  {
    "name": "document",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Document"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-support-tickets"></a>
### GET /api/v1/support/tickets

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dashboard_portal.py:194](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L194), `build_router.<locals>.client_tickets`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-support-tickets-ticket-id-intervene"></a>
### POST /api/v1/support/tickets/{ticket_id}/intervene

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dashboard_portal.py:202](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L202), `build_router.<locals>.intervene`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}`.

Parameters:

```json
[
  {
    "name": "ticket_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Ticket Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Intervention"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-support-tickets-ticket-id-resolve"></a>
### POST /api/v1/support/tickets/{ticket_id}/resolve

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dashboard_portal.py:213](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L213), `build_router.<locals>.resolve`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}`.

Parameters:

```json
[
  {
    "name": "ticket_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Ticket Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-support-whatsapp-consent"></a>
### POST /api/v1/support/whatsapp/consent

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/support_delivery.py:151](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/support_delivery.py#L151), `build_router.<locals>.consent`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN'}`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Consent"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-support-whatsapp-status-message-id"></a>
### POST /api/v1/support/whatsapp/status/{message_id}

Handler/service validation; declared dependencies are not the full security policy.

Implementation: [backend/support_delivery.py:148](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/support_delivery.py#L148), `build_router.<locals>.status`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "message_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Message Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-tracking-webhook"></a>
### POST /api/v1/tracking/webhook

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [backend/tracking_and_support.py:313](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/tracking_and_support.py#L313), `build_router.<locals>.webhook`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-get-api-v1-wallet"></a>
### GET /api/v1/wallet

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/advanced_logistics.py:386](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/advanced_logistics.py#L386), `build_router.<locals>.wallet`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-workspace-invitations"></a>
### POST /api/v1/workspace/invitations

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/workspace_settings.py:95](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L95), `build_router.<locals>.invite`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/Invite"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-workspace-invitations-invite-id-cancel"></a>
### POST /api/v1/workspace/invitations/{invite_id}/cancel

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/workspace_settings.py:123](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L123), `build_router.<locals>.cancel`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "invite_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Invite Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-workspace-invitations-invite-id-resend"></a>
### POST /api/v1/workspace/invitations/{invite_id}/resend

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/workspace_settings.py:112](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L112), `build_router.<locals>.resend`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "invite_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Invite Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-workspace-settings"></a>
### GET /api/v1/workspace/settings

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/workspace_settings.py:71](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L71), `build_router.<locals>.settings`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-patch-api-v1-workspace-settings"></a>
### PATCH /api/v1/workspace/settings

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/workspace_settings.py:79](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L79), `build_router.<locals>.company`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/CompanyUpdate"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-workspace-stores"></a>
### GET /api/v1/workspace/stores

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dashboard_portal.py:37](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L37), `build_router.<locals>.stores`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN', 'ACCOUNTANT'}`.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

<a id="op-post-api-v1-workspace-stores"></a>
### POST /api/v1/workspace/stores

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dashboard_portal.py:46](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L46), `build_router.<locals>.create_store`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN'}`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/StoreConfiguration"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-patch-api-v1-workspace-stores-store-id"></a>
### PATCH /api/v1/workspace/stores/{store_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dashboard_portal.py:53](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L53), `build_router.<locals>.store_state`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN'}`.

Parameters:

```json
[
  {
    "name": "store_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Store Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/StoreState"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-workspace-stores-store-id-connection"></a>
### GET /api/v1/workspace/stores/{store_id}/connection

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/store_connections.py:79](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/store_connections.py#L79), `build_router.<locals>.read`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "store_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Store Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-put-api-v1-workspace-stores-store-id-connection"></a>
### PUT /api/v1/workspace/stores/{store_id}/connection

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/store_connections.py:87](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/store_connections.py#L87), `build_router.<locals>.save`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "store_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Store Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/ConnectionSetup"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-api-v1-workspace-stores-store-id-notifications"></a>
### GET /api/v1/workspace/stores/{store_id}/notifications

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/store_connections.py:152](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/store_connections.py#L152), `build_router.<locals>.notifications`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "store_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Store Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-workspace-stores-store-id-notifications-notification-id-retry"></a>
### POST /api/v1/workspace/stores/{store_id}/notifications/{notification_id}/retry

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/store_connections.py:161](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/store_connections.py#L161), `build_router.<locals>.retry`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "store_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Store Id"
    }
  },
  {
    "name": "notification_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Notification Id"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-api-v1-workspace-users"></a>
### POST /api/v1/workspace/users

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/dashboard_portal.py:68](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dashboard_portal.py#L68), `build_router.<locals>.add_member`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in {'OWNER', 'ADMIN'}`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/WorkspaceMember"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "201": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-patch-api-v1-workspace-users-member-id"></a>
### PATCH /api/v1/workspace/users/{member_id}

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [backend/workspace_settings.py:85](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/workspace_settings.py#L85), `build_router.<locals>.member`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Parameters:

```json
[
  {
    "name": "member_id",
    "in": "path",
    "required": true,
    "schema": {
      "type": "string",
      "format": "uuid",
      "title": "Member Id"
    }
  }
]
```

Request body:

```json
{
  "required": true,
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/MemberUpdate"
      }
    }
  }
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-health"></a>
### GET /health

Public UI/help/health/config surface; inspect projection.

Implementation: [main.py:2281](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/main.py#L2281), `health`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "additionalProperties": {
            "type": "string"
          },
          "type": "object",
          "title": "Response Health Health Get"
        }
      }
    }
  }
}
```

<a id="op-post-v1-rates"></a>
### POST /v1/rates

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [main.py:2301](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/main.py#L2301), `get_rates`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in DISPATCH_ROLES | FINANCE_ROLES`; `context.role == 'DISPATCHER'`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/RatingRequest"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/RatingResponse"
        }
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-v1-wallet-topups"></a>
### POST /v1/wallet/topups

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [main.py:2379](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/main.py#L2379), `create_wallet_topup`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in FINANCE_ROLES`.

Request body:

```json
{
  "content": {
    "application/json": {
      "schema": {
        "$ref": "#/components/schemas/TopupRequest"
      }
    }
  },
  "required": true
}
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/TopupResponse"
        }
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-get-v1-whatsapp-quote-choice"></a>
### GET /v1/whatsapp/quote-choice

Authenticated workspace dependency; endpoint/helper role and tenant guards apply.

Implementation: [main.py:2452](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/main.py#L2452), `resolve_quote_choice`.

Declared dependencies: `HTTPBearer`, `authenticate`.
Guard/helper calls in handler: follow linked implementation and service.

Inline role conditions: `context.role not in DISPATCH_ROLES`.

Parameters:

```json
[
  {
    "name": "token",
    "in": "query",
    "required": true,
    "schema": {
      "type": "string",
      "title": "Token"
    }
  }
]
```

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "additionalProperties": true,
          "title": "Response Resolve Quote Choice V1 Whatsapp Quote Choice Get"
        }
      }
    }
  },
  "422": {
    "description": "Validation Error",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/HTTPValidationError"
        }
      }
    }
  }
}
```

<a id="op-post-webhooks-stripe"></a>
### POST /webhooks/stripe

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [main.py:2400](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/main.py#L2400), `stripe_webhook`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {
          "additionalProperties": {
            "type": "boolean"
          },
          "type": "object",
          "title": "Response Stripe Webhook Webhooks Stripe Post"
        }
      }
    }
  }
}
```

<a id="op-post-webhooks-twilio-whatsapp"></a>
### POST /webhooks/twilio/whatsapp

Callback-specific signature/identity/tenant checks in handler and service.

Implementation: [main.py:2446](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/main.py#L2446), `inbound_whatsapp`.

Declared dependencies: none.
Guard/helper calls in handler: follow linked implementation and service.

Request body:

```json
null
```

Documented responses:

```json
{
  "200": {
    "description": "Successful Response",
    "content": {
      "application/json": {
        "schema": {}
      }
    }
  }
}
```

## WebSocket contract

`/api/v1/dispatch-workspace/live` requires an approved Origin, rejects URL query tokens, and expects the first JSON message within ten seconds to contain access_token. Assistance adds assistance_session_id when applicable. It applies normal authentication and revalidates membership while sending events. Messages include refresh_required, shipment_changed and heartbeat. A bounded queue overflow or listener reconnect requires HTTP refresh. The broker enforces a maximum of 100 sockets; these are notifications, not booking or wallet commands.

- `/api/v1/dispatch-workspace/live` — [backend/dispatch_realtime.py:56](https://github.com/sync4ai-lab/veloce.ai/blob/e4d73e7f2ab88945b4977bf18a718815d4846f98/backend/dispatch_realtime.py#L56).

## Routes excluded from OpenAPI

| Method | Path | Handler |
| --- | --- | --- |
| GET | `/openapi.json` | `FastAPI.setup.<locals>.openapi` |
| HEAD | `/openapi.json` | `FastAPI.setup.<locals>.openapi` |
| GET | `/docs` | `FastAPI.setup.<locals>.swagger_ui_html` |
| HEAD | `/docs` | `FastAPI.setup.<locals>.swagger_ui_html` |
| GET | `/docs/oauth2-redirect` | `FastAPI.setup.<locals>.swagger_ui_redirect` |
| HEAD | `/docs/oauth2-redirect` | `FastAPI.setup.<locals>.swagger_ui_redirect` |
| GET | `/redoc` | `FastAPI.setup.<locals>.redoc_html` |
| HEAD | `/redoc` | `FastAPI.setup.<locals>.redoc_html` |
| GET | `/set-password` | `frontend` |
| GET | `/` | `frontend` |
| GET | `/help/` | `support_hub` |
| GET | `/help` | `support_hub` |
| GET | `/help/assets/{asset}` | `support_asset` |
| GET | `/help/search-index.json` | `support_search_index` |
| GET | `/help/contact` | `support_contact` |
| GET | `/help/source/{slug}` | `support_source` |
| GET | `/help/{slug}` | `support_guide` |

## Component schema dictionary

All schema branches, constraints, required fields and defaults are retained. Follow nested $ref entries through openapi.json. Source defaults are not active account configuration.

### Accept

```json
{
  "properties": {
    "access_token": {
      "type": "string",
      "maxLength": 16000,
      "minLength": 20,
      "format": "password",
      "title": "Access Token",
      "writeOnly": true
    },
    "password": {
      "type": "string",
      "maxLength": 128,
      "minLength": 12,
      "format": "password",
      "title": "Password",
      "writeOnly": true
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "access_token",
    "password"
  ],
  "title": "Accept"
}
```

### Address

```json
{
  "properties": {
    "name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Name"
    },
    "company": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Company"
    },
    "line1": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Line1"
    },
    "line2": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Line2"
    },
    "city": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "City"
    },
    "state": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100
        },
        {
          "type": "null"
        }
      ],
      "title": "State"
    },
    "postal_code": {
      "type": "string",
      "maxLength": 30,
      "minLength": 1,
      "title": "Postal Code"
    },
    "country_code": {
      "type": "string",
      "pattern": "^[A-Z]{2}$",
      "title": "Country Code"
    },
    "phone": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^\\+[1-9][0-9]{7,14}$"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone"
    },
    "email": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 254,
          "pattern": "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$"
        },
        {
          "type": "null"
        }
      ],
      "title": "Email"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "name",
    "line1",
    "city",
    "postal_code",
    "country_code"
  ],
  "title": "Address"
}
```

### AddressInput

```json
{
  "properties": {
    "expected_version": {
      "anyOf": [
        {
          "type": "integer",
          "minimum": 1.0
        },
        {
          "type": "null"
        }
      ],
      "title": "Expected Version"
    },
    "label": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "Label"
    },
    "address": {
      "$ref": "#/components/schemas/Address"
    },
    "address_role": {
      "type": "string",
      "enum": [
        "SENDER",
        "RETURN",
        "PICKUP",
        "INVOICE"
      ],
      "title": "Address Role"
    },
    "is_default": {
      "type": "boolean",
      "title": "Is Default",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "label",
    "address",
    "address_role"
  ],
  "title": "AddressInput"
}
```

### AlertPause

```json
{
  "properties": {
    "paused": {
      "type": "boolean",
      "title": "Paused"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "paused"
  ],
  "title": "AlertPause"
}
```

### ArchiveInput

```json
{
  "properties": {
    "expected_version": {
      "type": "integer",
      "minimum": 1.0,
      "title": "Expected Version"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "expected_version"
  ],
  "title": "ArchiveInput"
}
```

### Body_upload_api_v1_finance_audit_invoice_upload_post

```json
{
  "properties": {
    "file": {
      "type": "string",
      "contentMediaType": "application/octet-stream",
      "title": "File"
    },
    "invoice_reference": {
      "type": "string",
      "title": "Invoice Reference"
    },
    "carrier_account_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Carrier Account Id"
    }
  },
  "type": "object",
  "required": [
    "file",
    "invoice_reference"
  ],
  "title": "Body_upload_api_v1_finance_audit_invoice_upload_post"
}
```

### BookingRequest

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "offer_id": {
      "type": "string",
      "format": "uuid",
      "title": "Offer Id"
    },
    "insurance_requested": {
      "type": "boolean",
      "title": "Insurance Requested",
      "default": false
    },
    "insurance_quote_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Insurance Quote Id"
    },
    "insurance_terms_accepted": {
      "type": "boolean",
      "title": "Insurance Terms Accepted",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "offer_id"
  ],
  "title": "BookingRequest"
}
```

### CSVCustomsReview

```json
{
  "properties": {
    "items": {
      "items": {
        "$ref": "#/components/schemas/Goods"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Items"
    },
    "customs_signer": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Customs Signer"
    },
    "hs_codes_reviewed": {
      "type": "boolean",
      "const": true,
      "title": "Hs Codes Reviewed"
    },
    "recipient_phone": {
      "type": "string",
      "pattern": "^\\+[1-9][0-9]{7,14}$",
      "title": "Recipient Phone"
    },
    "origin_state": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Origin State"
    },
    "destination_state": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Destination State"
    },
    "postal_form": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "CN22",
            "CN23"
          ]
        },
        {
          "type": "null"
        }
      ],
      "title": "Postal Form"
    },
    "incoterm": {
      "type": "string",
      "enum": [
        "DAP",
        "DDP",
        "FCA",
        "EXW"
      ],
      "title": "Incoterm",
      "default": "DAP"
    },
    "sender_eori": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Sender Eori"
    },
    "recipient_eori": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Recipient Eori"
    },
    "sender_vat": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Sender Vat"
    },
    "recipient_vat": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Recipient Vat"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "items",
    "customs_signer",
    "hs_codes_reviewed",
    "recipient_phone"
  ],
  "title": "CSVCustomsReview"
}
```

### CardCart

```json
{
  "properties": {
    "offers": {
      "items": {
        "$ref": "#/components/schemas/SelectedOffer"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Offers"
    },
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "return_origin": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Return Origin"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "offers",
    "request_id"
  ],
  "title": "CardCart"
}
```

### Cargo

```json
{
  "properties": {
    "cargo_type": {
      "type": "string",
      "enum": [
        "LETTER",
        "PARCEL",
        "PALLET",
        "OVERLAND_FREIGHT"
      ],
      "title": "Cargo Type",
      "default": "PARCEL"
    },
    "actual_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 30000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Actual Weight Kg"
    },
    "length_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1500.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Length Cm"
    },
    "width_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 300.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Width Cm"
    },
    "height_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 400.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Height Cm"
    },
    "stackable": {
      "type": "boolean",
      "title": "Stackable",
      "default": true
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "actual_weight_kg"
  ],
  "title": "Cargo"
}
```

### CarrierCreate

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "account_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Account Name"
    },
    "aggregator": {
      "type": "string",
      "enum": [
        "EASYPOST",
        "REGIONAL"
      ],
      "title": "Aggregator"
    },
    "regional_provider_code": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Regional Provider Code"
    },
    "api_base_url": {
      "type": "string",
      "maxLength": 500,
      "title": "Api Base Url"
    },
    "api_key": {
      "type": "string",
      "format": "password",
      "title": "Api Key",
      "writeOnly": true
    },
    "upstream_account_id": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Upstream Account Id"
    },
    "environment": {
      "type": "string",
      "enum": [
        "TEST",
        "LIVE"
      ],
      "title": "Environment",
      "default": "TEST"
    },
    "priority": {
      "type": "integer",
      "maximum": 1000000.0,
      "minimum": 0.0,
      "title": "Priority",
      "default": 100
    },
    "timeout_seconds": {
      "type": "integer",
      "maximum": 120.0,
      "minimum": 1.0,
      "title": "Timeout Seconds",
      "default": 30
    },
    "is_active": {
      "type": "boolean",
      "title": "Is Active",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "account_name",
    "aggregator",
    "api_base_url",
    "api_key"
  ],
  "title": "CarrierCreate"
}
```

### CarrierUpdate

```json
{
  "properties": {
    "is_active": {
      "type": "boolean",
      "title": "Is Active"
    },
    "priority": {
      "type": "integer",
      "maximum": 1000000.0,
      "minimum": 0.0,
      "title": "Priority",
      "default": 100
    },
    "timeout_seconds": {
      "type": "integer",
      "maximum": 120.0,
      "minimum": 1.0,
      "title": "Timeout Seconds",
      "default": 30
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "is_active"
  ],
  "title": "CarrierUpdate"
}
```

### CheckoutCustoms

```json
{
  "properties": {
    "items": {
      "items": {
        "$ref": "#/components/schemas/Goods"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Items"
    },
    "signer": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Signer"
    },
    "reviewed": {
      "type": "boolean",
      "title": "Reviewed"
    },
    "currency": {
      "type": "string",
      "pattern": "^(GBP|EUR|USD)$",
      "title": "Currency"
    },
    "category": {
      "type": "string",
      "pattern": "^(SALE|GIFT|RETURN|SAMPLE|OTHER)$",
      "title": "Category"
    },
    "category_other": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200,
          "minLength": 3
        },
        {
          "type": "null"
        }
      ],
      "title": "Category Other"
    },
    "incoterm": {
      "type": "string",
      "pattern": "^DAP$",
      "title": "Incoterm",
      "default": "DAP"
    },
    "sender_eori": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Sender Eori"
    },
    "recipient_eori": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Recipient Eori"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "items",
    "signer",
    "reviewed",
    "currency",
    "category"
  ],
  "title": "CheckoutCustoms"
}
```

### CheckoutInput

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "topup_amount": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 10000.0,
          "minimum": 1.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Topup Amount"
    },
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "return_origin": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Return Origin"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "topup_amount"
  ],
  "title": "CheckoutInput"
}
```

### CheckoutPrepare

```json
{
  "properties": {
    "offer_id": {
      "type": "string",
      "format": "uuid",
      "title": "Offer Id"
    },
    "customs": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/CheckoutCustoms"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "offer_id"
  ],
  "title": "CheckoutPrepare"
}
```

### CheckoutSelection

```json
{
  "properties": {
    "offers": {
      "items": {
        "$ref": "#/components/schemas/SelectedOffer"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Offers"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "offers"
  ],
  "title": "CheckoutSelection"
}
```

### ClientRate

```json
{
  "properties": {
    "recommendation_badge": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 180
        },
        {
          "type": "null"
        }
      ],
      "title": "Recommendation Badge"
    },
    "package_count": {
      "type": "integer",
      "maximum": 100.0,
      "minimum": 1.0,
      "title": "Package Count",
      "default": 1
    },
    "package_weight_summary": {
      "additionalProperties": true,
      "type": "object",
      "title": "Package Weight Summary"
    },
    "label_purchase_available": {
      "type": "boolean",
      "title": "Label Purchase Available",
      "default": true
    },
    "label_purchase_notice": {
      "type": "string",
      "title": "Label Purchase Notice",
      "default": ""
    },
    "execution_details": {
      "additionalProperties": true,
      "type": "object",
      "title": "Execution Details"
    },
    "offer_id": {
      "type": "string",
      "format": "uuid",
      "title": "Offer Id"
    },
    "on_time_rate": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "On Time Rate"
    },
    "avg_transit_days": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Avg Transit Days"
    },
    "route_risk_level": {
      "type": "string",
      "enum": [
        "LOW",
        "MEDIUM",
        "HIGH_DELAY_ALERT"
      ],
      "title": "Route Risk Level",
      "default": "LOW"
    },
    "history_status": {
      "type": "string",
      "title": "History Status",
      "default": "NO_HISTORY"
    },
    "metric_scope": {
      "type": "string",
      "title": "Metric Scope",
      "default": "NO_MEASURED_HISTORY"
    },
    "history_samples": {
      "type": "integer",
      "title": "History Samples",
      "default": 0
    },
    "delivery_samples": {
      "type": "integer",
      "title": "Delivery Samples",
      "default": 0
    },
    "on_time_samples": {
      "type": "integer",
      "title": "On Time Samples",
      "default": 0
    },
    "active_exceptions": {
      "type": "integer",
      "title": "Active Exceptions",
      "default": 0
    },
    "on_time_method": {
      "type": "string",
      "title": "On Time Method",
      "default": ""
    },
    "transit_method": {
      "type": "string",
      "title": "Transit Method",
      "default": ""
    },
    "provider": {
      "type": "string",
      "enum": [
        "EASYPOST",
        "REGIONAL"
      ],
      "title": "Provider"
    },
    "account_id": {
      "type": "string",
      "format": "uuid",
      "title": "Account Id"
    },
    "upstream_shipment_id": {
      "type": "string",
      "title": "Upstream Shipment Id"
    },
    "upstream_rate_id": {
      "type": "string",
      "title": "Upstream Rate Id"
    },
    "carrier_code": {
      "type": "string",
      "title": "Carrier Code"
    },
    "service_code": {
      "type": "string",
      "title": "Service Code"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency"
    },
    "client_price_ex_tax": {
      "type": "string",
      "title": "Client Price Ex Tax"
    },
    "delivery_days": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "title": "Delivery Days"
    },
    "fee_breakdown": {
      "additionalProperties": true,
      "type": "object",
      "title": "Fee Breakdown"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "provider",
    "account_id",
    "upstream_shipment_id",
    "upstream_rate_id",
    "carrier_code",
    "service_code",
    "currency",
    "client_price_ex_tax",
    "delivery_days"
  ],
  "title": "ClientRate"
}
```

### CloseManifest

```json
{
  "properties": {
    "warehouse_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Warehouse Id"
    },
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "carrier_account_id": {
      "type": "string",
      "format": "uuid",
      "title": "Carrier Account Id"
    },
    "carrier_code": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 50,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Carrier Code"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "request_id",
    "carrier_account_id"
  ],
  "title": "CloseManifest"
}
```

### CompanyProfile

```json
{
  "properties": {
    "phone_e164": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^\\+[1-9][0-9]{7,14}$"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone E164"
    },
    "company_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Company Name"
    },
    "contact_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Contact Name"
    },
    "billing_email": {
      "type": "string",
      "maxLength": 254,
      "pattern": "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$",
      "title": "Billing Email"
    },
    "address_line1": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Address Line1"
    },
    "address_line2": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Address Line2"
    },
    "city": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "City"
    },
    "postal_code": {
      "type": "string",
      "maxLength": 30,
      "minLength": 1,
      "title": "Postal Code"
    },
    "country_code": {
      "type": "string",
      "title": "Country Code"
    },
    "company_registration_number": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Company Registration Number"
    },
    "tax_id": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Tax Id"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "company_name",
    "contact_name",
    "billing_email",
    "address_line1",
    "city",
    "postal_code",
    "country_code"
  ],
  "title": "CompanyProfile"
}
```

### CompanyUpdate

```json
{
  "properties": {
    "company_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Company Name"
    },
    "workspace_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Workspace Name"
    },
    "billing_email": {
      "type": "string",
      "maxLength": 254,
      "pattern": "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$",
      "title": "Billing Email"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "company_name",
    "workspace_name",
    "billing_email"
  ],
  "title": "CompanyUpdate"
}
```

### ConnectionSetup

```json
{
  "properties": {
    "shop_domain": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Shop Domain"
    },
    "access_token": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 4096,
          "format": "password",
          "writeOnly": true
        },
        {
          "type": "null"
        }
      ],
      "title": "Access Token"
    },
    "client_id": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Client Id"
    },
    "client_secret": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 4096,
          "format": "password",
          "writeOnly": true
        },
        {
          "type": "null"
        }
      ],
      "title": "Client Secret"
    },
    "authorization_mode": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "TOKEN",
            "CLIENT_CREDENTIALS"
          ]
        },
        {
          "type": "null"
        }
      ],
      "title": "Authorization Mode"
    },
    "webhook_secret": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 4096,
          "format": "password",
          "writeOnly": true
        },
        {
          "type": "null"
        }
      ],
      "title": "Webhook Secret"
    },
    "live_import": {
      "type": "boolean",
      "title": "Live Import",
      "default": true
    },
    "live_returns": {
      "type": "boolean",
      "title": "Live Returns",
      "default": false
    },
    "sku_unit_grams": {
      "additionalProperties": {
        "type": "string"
      },
      "type": "object",
      "maxProperties": 1000,
      "title": "Sku Unit Grams"
    },
    "cargo_type": {
      "type": "string",
      "enum": [
        "LETTER",
        "PARCEL",
        "PALLET",
        "OVERLAND_FREIGHT"
      ],
      "title": "Cargo Type",
      "default": "PARCEL"
    },
    "amazon_region": {
      "type": "string",
      "enum": [
        "na",
        "eu",
        "fe"
      ],
      "title": "Amazon Region",
      "default": "eu"
    },
    "amazon_seller_id": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100
        },
        {
          "type": "null"
        }
      ],
      "title": "Amazon Seller Id"
    },
    "amazon_marketplace_ids": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "maxItems": 50,
      "title": "Amazon Marketplace Ids"
    },
    "amazon_client_id": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Amazon Client Id"
    },
    "amazon_client_secret": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 4096,
          "format": "password",
          "writeOnly": true
        },
        {
          "type": "null"
        }
      ],
      "title": "Amazon Client Secret"
    },
    "amazon_refresh_token": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 4096,
          "format": "password",
          "writeOnly": true
        },
        {
          "type": "null"
        }
      ],
      "title": "Amazon Refresh Token"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "title": "ConnectionSetup"
}
```

### Consent

```json
{
  "properties": {
    "notification_opt_in": {
      "type": "boolean",
      "title": "Notification Opt In"
    }
  },
  "type": "object",
  "required": [
    "notification_opt_in"
  ],
  "title": "Consent"
}
```

### ContactInput

```json
{
  "properties": {
    "expected_version": {
      "anyOf": [
        {
          "type": "integer",
          "minimum": 1.0
        },
        {
          "type": "null"
        }
      ],
      "title": "Expected Version"
    },
    "label": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "Label"
    },
    "address": {
      "$ref": "#/components/schemas/Address"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "label",
    "address"
  ],
  "title": "ContactInput"
}
```

### ConversationMessage

```json
{
  "properties": {
    "sender_id": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^\\+[1-9][0-9]{7,14}$"
        },
        {
          "type": "null"
        }
      ],
      "title": "Sender Id"
    },
    "message_body": {
      "type": "string",
      "maxLength": 2000,
      "minLength": 1,
      "title": "Message Body"
    },
    "channel": {
      "type": "string",
      "enum": [
        "WHATSAPP",
        "WEB_CHAT"
      ],
      "title": "Channel"
    },
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "media_urls": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "maxItems": 1,
      "title": "Media Urls"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "message_body",
    "channel"
  ],
  "title": "ConversationMessage"
}
```

### CredentialReplacement

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "new_api_key": {
      "type": "string",
      "format": "password",
      "title": "New Api Key",
      "writeOnly": true
    },
    "reason": {
      "type": "string",
      "maxLength": 500,
      "minLength": 10,
      "title": "Reason"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "request_id",
    "new_api_key",
    "reason"
  ],
  "title": "CredentialReplacement"
}
```

### CustomsItem

```json
{
  "properties": {
    "description": {
      "type": "string",
      "maxLength": 500,
      "minLength": 3,
      "title": "Description"
    },
    "hs_code": {
      "type": "string",
      "maxLength": 10,
      "pattern": "^\\d{6}(?:\\d{2})?(?:\\d{2})?$",
      "title": "Hs Code"
    },
    "origin_country": {
      "type": "string",
      "title": "Origin Country"
    },
    "quantity": {
      "type": "integer",
      "maximum": 100000.0,
      "exclusiveMinimum": 0.0,
      "title": "Quantity"
    },
    "unit_value": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Unit Value"
    },
    "unit_net_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 30000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Unit Net Weight Kg"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "description",
    "hs_code",
    "origin_country",
    "quantity",
    "unit_value",
    "unit_net_weight_kg"
  ],
  "title": "CustomsItem"
}
```

### CustomsItems

```json
{
  "properties": {
    "items": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Items"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "items"
  ],
  "title": "CustomsItems"
}
```

### DeclarationInput

```json
{
  "properties": {
    "invoice_reference": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "Invoice Reference"
    },
    "form": {
      "type": "string",
      "enum": [
        "CN22",
        "CN23",
        "COMMERCIAL_INVOICE"
      ],
      "title": "Form",
      "default": "CN23"
    },
    "sender": {
      "$ref": "#/components/schemas/DeclarationParty"
    },
    "recipient": {
      "$ref": "#/components/schemas/DeclarationParty"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency",
      "default": "GBP"
    },
    "category": {
      "type": "string",
      "enum": [
        "SALE",
        "GIFT",
        "RETURN",
        "SAMPLE",
        "OTHER"
      ],
      "title": "Category",
      "default": "SALE"
    },
    "incoterm": {
      "type": "string",
      "enum": [
        "DAP",
        "DDP",
        "FCA",
        "EXW"
      ],
      "title": "Incoterm",
      "default": "DAP"
    },
    "items": {
      "items": {
        "$ref": "#/components/schemas/CustomsItem"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Items"
    },
    "gross_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 30000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Gross Weight Kg"
    },
    "shipping_cost": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Shipping Cost",
      "default": "0"
    },
    "hs_codes_reviewed": {
      "type": "boolean",
      "const": true,
      "title": "Hs Codes Reviewed"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "invoice_reference",
    "sender",
    "recipient",
    "items",
    "gross_weight_kg",
    "hs_codes_reviewed"
  ],
  "title": "DeclarationInput"
}
```

### DeclarationParty

```json
{
  "properties": {
    "name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Name"
    },
    "line1": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Line1"
    },
    "city": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "City"
    },
    "postal_code": {
      "type": "string",
      "maxLength": 30,
      "minLength": 1,
      "title": "Postal Code"
    },
    "country_code": {
      "type": "string",
      "title": "Country Code"
    },
    "eori": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Eori"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "name",
    "line1",
    "city",
    "postal_code",
    "country_code"
  ],
  "title": "DeclarationParty"
}
```

### Description

```json
{
  "properties": {
    "description": {
      "type": "string",
      "maxLength": 500,
      "minLength": 3,
      "title": "Description"
    },
    "sku": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Sku"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "description"
  ],
  "title": "Description"
}
```

### DescriptionInput

```json
{
  "properties": {
    "item_description": {
      "type": "string",
      "maxLength": 500,
      "minLength": 3,
      "title": "Item Description"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "item_description"
  ],
  "title": "DescriptionInput"
}
```

### Dimensions

```json
{
  "properties": {
    "length_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1500.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Length Cm"
    },
    "width_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Width Cm"
    },
    "height_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Height Cm"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "length_cm",
    "width_cm",
    "height_cm"
  ],
  "title": "Dimensions"
}
```

### Draft

```json
{
  "properties": {
    "content": {
      "type": "string",
      "maxLength": 12000,
      "minLength": 10,
      "title": "Content"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "content"
  ],
  "title": "Draft"
}
```

### Goods

```json
{
  "properties": {
    "description": {
      "type": "string",
      "maxLength": 500,
      "minLength": 3,
      "title": "Description"
    },
    "quantity": {
      "type": "integer",
      "maximum": 10000.0,
      "minimum": 1.0,
      "title": "Quantity"
    },
    "unit_value": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Unit Value"
    },
    "unit_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 30000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Unit Weight Kg"
    },
    "origin_country": {
      "type": "string",
      "title": "Origin Country"
    },
    "sku": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Sku"
    },
    "package_index": {
      "anyOf": [
        {
          "type": "integer",
          "maximum": 100.0,
          "minimum": 1.0
        },
        {
          "type": "null"
        }
      ],
      "title": "Package Index"
    },
    "hs_code": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^\\d{6}(?:\\d{2})?(?:\\d{2})?$"
        },
        {
          "type": "null"
        }
      ],
      "title": "Hs Code"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "description",
    "quantity",
    "unit_value",
    "unit_weight_kg",
    "origin_country"
  ],
  "title": "Goods"
}
```

### HTTPValidationError

```json
{
  "properties": {
    "detail": {
      "items": {
        "$ref": "#/components/schemas/ValidationError"
      },
      "type": "array",
      "title": "Detail"
    }
  },
  "type": "object",
  "title": "HTTPValidationError"
}
```

### HelpQuestion

```json
{
  "properties": {
    "query": {
      "type": "string",
      "maxLength": 800,
      "minLength": 3,
      "title": "Query"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "query"
  ],
  "title": "HelpQuestion"
}
```

### IndividualPricingUpdate

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "expected_version": {
      "type": "integer",
      "minimum": 0.0,
      "title": "Expected Version"
    },
    "individual_global_markup_percent": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 999.99,
          "minimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Individual Global Markup Percent"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "expected_version",
    "individual_global_markup_percent"
  ],
  "title": "IndividualPricingUpdate"
}
```

### Intervention

```json
{
  "properties": {
    "note": {
      "type": "string",
      "maxLength": 2000,
      "minLength": 3,
      "title": "Note"
    },
    "start_review": {
      "type": "boolean",
      "title": "Start Review",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "note"
  ],
  "title": "Intervention"
}
```

### Invite

```json
{
  "properties": {
    "first_name": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "First Name"
    },
    "last_name": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "Last Name"
    },
    "email": {
      "type": "string",
      "maxLength": 254,
      "pattern": "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$",
      "title": "Email"
    },
    "role": {
      "type": "string",
      "enum": [
        "DISPATCHER",
        "ACCOUNTANT"
      ],
      "title": "Role"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "first_name",
    "last_name",
    "email",
    "role"
  ],
  "title": "Invite"
}
```

### InvoiceInput

```json
{
  "properties": {
    "invoice_reference": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "pattern": "^[A-Za-z0-9 _./-]+$",
      "title": "Invoice Reference"
    },
    "lines": {
      "items": {
        "$ref": "#/components/schemas/InvoiceLine"
      },
      "type": "array",
      "maxItems": 500,
      "minItems": 1,
      "title": "Lines"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "invoice_reference",
    "lines"
  ],
  "title": "InvoiceInput"
}
```

### InvoiceLine

```json
{
  "properties": {
    "shipment_id": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency"
    },
    "billed_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 30000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Billed Weight Kg"
    },
    "base_cost": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Base Cost"
    },
    "fuel_surcharge": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Fuel Surcharge"
    },
    "residential_fee": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Residential Fee",
      "default": "0"
    },
    "remote_area_fee": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Remote Area Fee"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "shipment_id",
    "currency",
    "billed_weight_kg",
    "base_cost",
    "fuel_surcharge",
    "remote_area_fee"
  ],
  "title": "InvoiceLine"
}
```

### Login

```json
{
  "properties": {
    "email": {
      "type": "string",
      "maxLength": 254,
      "pattern": "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$",
      "title": "Email"
    },
    "password": {
      "type": "string",
      "maxLength": 4096,
      "minLength": 1,
      "format": "password",
      "title": "Password",
      "writeOnly": true
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "email",
    "password"
  ],
  "title": "Login"
}
```

### ManifestCandidateSummary

```json
{
  "properties": {
    "carrier_account_id": {
      "type": "string",
      "format": "uuid",
      "title": "Carrier Account Id"
    },
    "carrier_code": {
      "type": "string",
      "title": "Carrier Code"
    },
    "total_shipments": {
      "type": "integer",
      "title": "Total Shipments"
    },
    "total_weight_kg": {
      "type": "string",
      "title": "Total Weight Kg"
    },
    "origin_postcode": {
      "type": "string",
      "title": "Origin Postcode"
    },
    "document_kind": {
      "type": "string",
      "enum": [
        "CARRIER_MANIFEST",
        "INTERNAL_HANDOVER"
      ],
      "title": "Document Kind"
    }
  },
  "type": "object",
  "required": [
    "carrier_account_id",
    "carrier_code",
    "total_shipments",
    "total_weight_kg",
    "origin_postcode",
    "document_kind"
  ],
  "title": "ManifestCandidateSummary"
}
```

### ManifestResult

```json
{
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid",
      "title": "Id"
    },
    "status": {
      "type": "string",
      "enum": [
        "DRAFT",
        "SUBMITTED",
        "FAILED",
        "COMPLETED"
      ],
      "title": "Status"
    },
    "carrier_account_id": {
      "type": "string",
      "format": "uuid",
      "title": "Carrier Account Id"
    },
    "carrier_code": {
      "type": "string",
      "title": "Carrier Code"
    },
    "total_shipments": {
      "type": "integer",
      "title": "Total Shipments"
    },
    "total_weight_kg": {
      "type": "string",
      "title": "Total Weight Kg"
    },
    "master_tracking_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Master Tracking Id"
    },
    "manifest_document_url": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Manifest Document Url"
    },
    "document_kind": {
      "type": "string",
      "enum": [
        "CARRIER_MANIFEST",
        "INTERNAL_HANDOVER"
      ],
      "title": "Document Kind"
    },
    "carrier_closed": {
      "type": "boolean",
      "title": "Carrier Closed",
      "default": false
    },
    "message": {
      "type": "string",
      "title": "Message"
    }
  },
  "type": "object",
  "required": [
    "id",
    "status",
    "carrier_account_id",
    "carrier_code",
    "total_shipments",
    "total_weight_kg",
    "document_kind",
    "message"
  ],
  "title": "ManifestResult"
}
```

### MarginCreate

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "destination_country": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Destination Country"
    },
    "origin_country": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Origin Country"
    },
    "billing_plan": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "PREPAID_WALLET",
            "POSTPAID_30_DAY"
          ]
        },
        {
          "type": "null"
        }
      ],
      "title": "Billing Plan"
    },
    "cargo_type": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "LETTER",
            "PARCEL",
            "PALLET",
            "OVERLAND_FREIGHT"
          ]
        },
        {
          "type": "null"
        }
      ],
      "title": "Cargo Type"
    },
    "min_volume_m3": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 100000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Min Volume M3"
    },
    "max_volume_m3": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 100000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Max Volume M3"
    },
    "carrier_code": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Carrier Code"
    },
    "service_code": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Service Code"
    },
    "carrier_account_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Carrier Account Id"
    },
    "currency": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "GBP",
            "EUR",
            "USD"
          ]
        },
        {
          "type": "null"
        }
      ],
      "title": "Currency"
    },
    "markup_type": {
      "type": "string",
      "enum": [
        "PERCENTAGE",
        "FLAT_RATE"
      ],
      "title": "Markup Type"
    },
    "markup_value": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Markup Value"
    },
    "minimum_markup": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Minimum Markup",
      "default": "0"
    },
    "maximum_markup": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Maximum Markup"
    },
    "min_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Min Weight Kg"
    },
    "max_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Max Weight Kg"
    },
    "min_wholesale_cost": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "minimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Min Wholesale Cost"
    },
    "max_wholesale_cost": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Max Wholesale Cost"
    },
    "priority": {
      "type": "integer",
      "maximum": 1000000.0,
      "minimum": 0.0,
      "title": "Priority",
      "default": 100
    },
    "is_active": {
      "type": "boolean",
      "title": "Is Active",
      "default": true
    },
    "valid_from": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ],
      "title": "Valid From"
    },
    "valid_until": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ],
      "title": "Valid Until"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "markup_type",
    "markup_value"
  ],
  "title": "MarginCreate"
}
```

### MarginCreated

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "id": {
      "type": "string",
      "format": "uuid",
      "title": "Id"
    },
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "destination_country": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Destination Country"
    },
    "carrier_code": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Carrier Code"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency"
    },
    "markup_type": {
      "type": "string",
      "enum": [
        "PERCENTAGE",
        "FLAT_RATE"
      ],
      "title": "Markup Type"
    },
    "markup_value": {
      "type": "string",
      "title": "Markup Value"
    },
    "priority": {
      "type": "integer",
      "title": "Priority"
    },
    "is_active": {
      "type": "boolean",
      "title": "Is Active"
    },
    "valid_from": {
      "type": "string",
      "format": "date-time",
      "title": "Valid From"
    },
    "valid_until": {
      "anyOf": [
        {
          "type": "string",
          "format": "date-time"
        },
        {
          "type": "null"
        }
      ],
      "title": "Valid Until"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "request_id",
    "id",
    "tenant_id",
    "destination_country",
    "carrier_code",
    "currency",
    "markup_type",
    "markup_value",
    "priority",
    "is_active",
    "valid_from",
    "valid_until"
  ],
  "title": "MarginCreated"
}
```

### MemberUpdate

```json
{
  "properties": {
    "role": {
      "type": "string",
      "enum": [
        "DISPATCHER",
        "ACCOUNTANT"
      ],
      "title": "Role"
    },
    "is_active": {
      "type": "boolean",
      "title": "Is Active"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "role",
    "is_active"
  ],
  "title": "MemberUpdate"
}
```

### MessageRequest

```json
{
  "properties": {
    "text": {
      "type": "string",
      "maxLength": 2000,
      "minLength": 3,
      "title": "Text"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "text"
  ],
  "title": "MessageRequest"
}
```

### NativeOrderReconciliation

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "shipment_id": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    },
    "remote_object_id": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "pattern": "^[A-Za-z0-9_-]+$",
      "title": "Remote Object Id"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "shipment_id",
    "remote_object_id"
  ],
  "title": "NativeOrderReconciliation"
}
```

### NativeOrderSelection

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "shipment_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Shipment Ids"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "shipment_ids"
  ],
  "title": "NativeOrderSelection"
}
```

### NativeProviderSettings

```json
{
  "properties": {
    "order_sync_enabled": {
      "type": "boolean",
      "title": "Order Sync Enabled",
      "default": false
    },
    "sendcloud_integration_id": {
      "anyOf": [
        {
          "type": "integer",
          "exclusiveMinimum": 0.0
        },
        {
          "type": "null"
        }
      ],
      "title": "Sendcloud Integration Id"
    },
    "webhook_enabled": {
      "type": "boolean",
      "title": "Webhook Enabled",
      "default": false
    },
    "webhook_auth": {
      "type": "string",
      "enum": [
        "HMAC",
        "URL_TOKEN"
      ],
      "title": "Webhook Auth",
      "default": "HMAC"
    },
    "webhook_secret": {
      "anyOf": [
        {
          "type": "string",
          "format": "password",
          "writeOnly": true
        },
        {
          "type": "null"
        }
      ],
      "title": "Webhook Secret"
    },
    "pod_allowed_hosts": {
      "items": {
        "type": "string"
      },
      "type": "array",
      "maxItems": 30,
      "title": "Pod Allowed Hosts"
    },
    "sendcloud_status_map": {
      "additionalProperties": {
        "type": "string",
        "enum": [
          "IN_TRANSIT",
          "DELIVERED",
          "EXCEPTION"
        ]
      },
      "type": "object",
      "title": "Sendcloud Status Map"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "title": "NativeProviderSettings"
}
```

### Order

```json
{
  "properties": {
    "idempotency_key": {
      "type": "string",
      "format": "uuid",
      "title": "Idempotency Key"
    },
    "order_reference": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1,
      "title": "Order Reference"
    },
    "platform": {
      "type": "string",
      "enum": [
        "SHOPIFY",
        "WOOCOMMERCE",
        "AMAZON",
        "MANUAL"
      ],
      "title": "Platform",
      "default": "MANUAL"
    },
    "store_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Store Id"
    },
    "store_order_id": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 150,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Store Order Id"
    },
    "origin": {
      "additionalProperties": true,
      "type": "object",
      "title": "Origin"
    },
    "destination": {
      "additionalProperties": true,
      "type": "object",
      "title": "Destination"
    },
    "cargo": {
      "$ref": "#/components/schemas/Cargo"
    },
    "packages": {
      "items": {
        "$ref": "#/components/schemas/Cargo"
      },
      "type": "array",
      "maxItems": 100,
      "title": "Packages"
    },
    "multi_parcel_dimensions": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array",
      "maxItems": 100,
      "title": "Multi Parcel Dimensions"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency",
      "default": "GBP"
    },
    "items": {
      "items": {
        "$ref": "#/components/schemas/Goods"
      },
      "type": "array",
      "maxItems": 100,
      "title": "Items"
    },
    "sender_eori": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Sender Eori"
    },
    "recipient_eori": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Recipient Eori"
    },
    "sender_vat": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Sender Vat"
    },
    "recipient_vat": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Recipient Vat"
    },
    "customs_signer": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Customs Signer"
    },
    "hs_codes_reviewed": {
      "type": "boolean",
      "title": "Hs Codes Reviewed",
      "default": false
    },
    "postal_form": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "CN22",
            "CN23"
          ]
        },
        {
          "type": "null"
        }
      ],
      "title": "Postal Form"
    },
    "customs_required_override": {
      "type": "boolean",
      "title": "Customs Required Override",
      "default": false
    },
    "incoterm": {
      "type": "string",
      "enum": [
        "DAP",
        "DDP",
        "FCA",
        "EXW"
      ],
      "title": "Incoterm",
      "default": "DAP"
    },
    "invoice_reference": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Invoice Reference"
    },
    "customs_currency": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "GBP",
            "EUR",
            "USD"
          ]
        },
        {
          "type": "null"
        }
      ],
      "title": "Customs Currency"
    },
    "customs_category": {
      "type": "string",
      "enum": [
        "SALE",
        "GIFT",
        "RETURN",
        "SAMPLE",
        "OTHER"
      ],
      "title": "Customs Category",
      "default": "SALE"
    },
    "customs_category_other": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200,
          "minLength": 3
        },
        {
          "type": "null"
        }
      ],
      "title": "Customs Category Other"
    },
    "is_return": {
      "type": "boolean",
      "title": "Is Return",
      "default": false
    },
    "return_of_shipment_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Return Of Shipment Id"
    },
    "return_network_selection": {
      "type": "boolean",
      "title": "Return Network Selection",
      "default": false
    },
    "return_warehouse_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Return Warehouse Id"
    },
    "return_warehouse_version": {
      "anyOf": [
        {
          "type": "integer",
          "minimum": 1.0
        },
        {
          "type": "null"
        }
      ],
      "title": "Return Warehouse Version"
    },
    "paperless_requested": {
      "type": "boolean",
      "title": "Paperless Requested",
      "default": false
    },
    "original_invoice_number": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 40
        },
        {
          "type": "null"
        }
      ],
      "title": "Original Invoice Number"
    },
    "return_data": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "title": "Return Data"
    },
    "store_return_reference": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Store Return Reference"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "idempotency_key",
    "order_reference",
    "origin",
    "destination",
    "cargo"
  ],
  "title": "Order"
}
```

### OrderSelection

```json
{
  "properties": {
    "shipment_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Shipment Ids"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "shipment_ids"
  ],
  "title": "OrderSelection"
}
```

### PackageCheck

```json
{
  "properties": {
    "origin_country": {
      "type": "string",
      "title": "Origin Country"
    },
    "destination_country": {
      "type": "string",
      "title": "Destination Country"
    },
    "cargo_type": {
      "type": "string",
      "enum": [
        "LETTER",
        "PARCEL",
        "PALLET",
        "OVERLAND_FREIGHT"
      ],
      "title": "Cargo Type"
    },
    "actual_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 30000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Actual Weight Kg"
    },
    "dimensions": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/PackageDimensions"
        },
        {
          "type": "null"
        }
      ]
    },
    "shipment_items": {
      "items": {
        "$ref": "#/components/schemas/Goods"
      },
      "type": "array",
      "maxItems": 100,
      "title": "Shipment Items"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "origin_country",
    "destination_country",
    "cargo_type",
    "actual_weight_kg"
  ],
  "title": "PackageCheck"
}
```

### PackageDimensions

```json
{
  "properties": {
    "length_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1500.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Length Cm"
    },
    "width_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Width Cm"
    },
    "height_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Height Cm"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "length_cm",
    "width_cm",
    "height_cm"
  ],
  "title": "PackageDimensions"
}
```

### PackageInput

```json
{
  "properties": {
    "box_index": {
      "type": "integer",
      "maximum": 100.0,
      "minimum": 1.0,
      "title": "Box Index"
    },
    "length_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Length Cm"
    },
    "width_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Width Cm"
    },
    "height_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Height Cm"
    },
    "actual_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Actual Weight Kg"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "box_index",
    "length_cm",
    "width_cm",
    "height_cm",
    "actual_weight_kg"
  ],
  "title": "PackageInput"
}
```

### ParcelInput

```json
{
  "properties": {
    "length_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Length Cm"
    },
    "width_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Width Cm"
    },
    "height_cm": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Height Cm"
    },
    "actual_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Actual Weight Kg"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "length_cm",
    "width_cm",
    "height_cm",
    "actual_weight_kg"
  ],
  "title": "ParcelInput"
}
```

### PersonalProfile

```json
{
  "properties": {
    "full_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 2,
      "title": "Full Name"
    },
    "billing_email": {
      "type": "string",
      "maxLength": 254,
      "pattern": "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$",
      "title": "Billing Email"
    },
    "phone_e164": {
      "type": "string",
      "pattern": "^\\+[1-9][0-9]{7,14}$",
      "title": "Phone E164"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "full_name",
    "billing_email",
    "phone_e164"
  ],
  "title": "PersonalProfile"
}
```

### PlatformConnection

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "tenant_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Tenant Id"
    },
    "account_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Account Name"
    },
    "aggregator": {
      "type": "string",
      "enum": [
        "EASYPOST",
        "REGIONAL"
      ],
      "title": "Aggregator"
    },
    "regional_provider_code": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 100,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Regional Provider Code"
    },
    "api_base_url": {
      "type": "string",
      "maxLength": 500,
      "title": "Api Base Url"
    },
    "api_key": {
      "anyOf": [
        {
          "type": "string",
          "format": "password",
          "writeOnly": true
        },
        {
          "type": "null"
        }
      ],
      "title": "Api Key"
    },
    "upstream_account_id": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Upstream Account Id"
    },
    "environment": {
      "type": "string",
      "enum": [
        "TEST",
        "LIVE"
      ],
      "title": "Environment",
      "default": "TEST"
    },
    "priority": {
      "type": "integer",
      "maximum": 1000000.0,
      "minimum": 0.0,
      "title": "Priority",
      "default": 100
    },
    "timeout_seconds": {
      "type": "integer",
      "maximum": 120.0,
      "minimum": 1.0,
      "title": "Timeout Seconds",
      "default": 30
    },
    "is_active": {
      "type": "boolean",
      "title": "Is Active",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "account_name",
    "aggregator",
    "api_base_url"
  ],
  "title": "PlatformConnection"
}
```

### PlatformSettlement

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "claim_id": {
      "type": "string",
      "format": "uuid",
      "title": "Claim Id"
    },
    "settlement_id": {
      "type": "string",
      "format": "uuid",
      "title": "Settlement Id"
    },
    "approved_amount": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 5000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Approved Amount"
    },
    "currency": {
      "type": "string",
      "const": "GBP",
      "title": "Currency"
    },
    "insurer_payment_reference": {
      "type": "string",
      "maxLength": 150,
      "minLength": 5,
      "pattern": "^[A-Za-z0-9_.:/-]+$",
      "title": "Insurer Payment Reference"
    },
    "received_at": {
      "type": "string",
      "format": "date-time",
      "title": "Received At"
    },
    "funds_received_verified": {
      "type": "boolean",
      "const": true,
      "title": "Funds Received Verified"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "claim_id",
    "settlement_id",
    "approved_amount",
    "currency",
    "insurer_payment_reference",
    "received_at",
    "funds_received_verified"
  ],
  "title": "PlatformSettlement"
}
```

### PreviewManifest

```json
{
  "properties": {
    "warehouse_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Warehouse Id"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "title": "PreviewManifest"
}
```

### ProductInput

```json
{
  "properties": {
    "expected_version": {
      "anyOf": [
        {
          "type": "integer",
          "minimum": 1.0
        },
        {
          "type": "null"
        }
      ],
      "title": "Expected Version"
    },
    "sku": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Sku"
    },
    "description": {
      "type": "string",
      "maxLength": 500,
      "minLength": 3,
      "title": "Description"
    },
    "unit_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 30000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Unit Weight Kg"
    },
    "unit_value": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 1000000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Unit Value"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency",
      "default": "GBP"
    },
    "origin_country": {
      "type": "string",
      "title": "Origin Country"
    },
    "hs_code": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^([0-9]{6}|[0-9]{8}|[0-9]{10})$"
        },
        {
          "type": "null"
        }
      ],
      "title": "Hs Code"
    },
    "hs_reviewed": {
      "type": "boolean",
      "title": "Hs Reviewed",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "sku",
    "description",
    "unit_weight_kg",
    "unit_value",
    "origin_country"
  ],
  "title": "ProductInput"
}
```

### ProfileUpdate

```json
{
  "properties": {
    "full_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "pattern": "^[^\\x00-\\x1f\\x7f]+$",
      "title": "Full Name"
    },
    "phone_e164": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^\\+[1-9][0-9]{7,14}$"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone E164"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "full_name"
  ],
  "title": "ProfileUpdate"
}
```

### ProviderIssue

```json
{
  "properties": {
    "provider": {
      "type": "string",
      "enum": [
        "EASYPOST",
        "REGIONAL"
      ],
      "title": "Provider"
    },
    "account_id": {
      "type": "string",
      "format": "uuid",
      "title": "Account Id"
    },
    "code": {
      "type": "string",
      "title": "Code"
    },
    "retryable": {
      "type": "boolean",
      "title": "Retryable"
    },
    "available_currencies": {
      "items": {
        "type": "string",
        "enum": [
          "GBP",
          "EUR",
          "USD"
        ]
      },
      "type": "array",
      "title": "Available Currencies"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "provider",
    "account_id",
    "code",
    "retryable"
  ],
  "title": "ProviderIssue"
}
```

### QuoteSupport

```json
{
  "properties": {
    "origin_country": {
      "type": "string",
      "title": "Origin Country"
    },
    "destination_country": {
      "type": "string",
      "title": "Destination Country"
    },
    "cargo_type": {
      "type": "string",
      "enum": [
        "LETTER",
        "PARCEL",
        "PALLET",
        "OVERLAND_FREIGHT"
      ],
      "title": "Cargo Type"
    },
    "actual_weight_kg": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 30000.0,
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Actual Weight Kg"
    },
    "dimensions": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/PackageDimensions"
        },
        {
          "type": "null"
        }
      ]
    },
    "shipment_items": {
      "items": {
        "$ref": "#/components/schemas/Goods"
      },
      "type": "array",
      "maxItems": 100,
      "title": "Shipment Items"
    },
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "transport_mode": {
      "type": "string",
      "enum": [
        "PARCEL",
        "ROAD",
        "SEA"
      ],
      "title": "Transport Mode",
      "default": "PARCEL"
    },
    "notes": {
      "type": "string",
      "maxLength": 1000,
      "title": "Notes",
      "default": ""
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "origin_country",
    "destination_country",
    "cargo_type",
    "actual_weight_kg"
  ],
  "title": "QuoteSupport"
}
```

### RatingRequest

```json
{
  "properties": {
    "multi_parcel_dimensions": {
      "items": {
        "$ref": "#/components/schemas/PackageInput"
      },
      "type": "array",
      "maxItems": 100,
      "title": "Multi Parcel Dimensions"
    },
    "origin": {
      "$ref": "#/components/schemas/Address"
    },
    "destination": {
      "$ref": "#/components/schemas/Address"
    },
    "dimensions": {
      "items": {
        "$ref": "#/components/schemas/Dimensions"
      },
      "type": "array",
      "maxItems": 100,
      "title": "Dimensions"
    },
    "weights_kg": {
      "items": {
        "anyOf": [
          {
            "type": "number",
            "maximum": 30000.0,
            "exclusiveMinimum": 0.0
          },
          {
            "type": "string"
          }
        ]
      },
      "type": "array",
      "maxItems": 100,
      "title": "Weights Kg"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency",
      "default": "GBP"
    },
    "cargo_type": {
      "type": "string",
      "enum": [
        "LETTER",
        "PARCEL",
        "PALLET",
        "OVERLAND_FREIGHT"
      ],
      "title": "Cargo Type",
      "default": "PARCEL"
    },
    "stackable": {
      "type": "boolean",
      "title": "Stackable",
      "default": true
    },
    "customs_document": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "title": "Customs Document"
    },
    "shipment_items": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array",
      "maxItems": 100,
      "title": "Shipment Items"
    },
    "goods_currency": {
      "anyOf": [
        {
          "type": "string",
          "enum": [
            "GBP",
            "EUR",
            "USD"
          ]
        },
        {
          "type": "null"
        }
      ],
      "title": "Goods Currency"
    },
    "is_return": {
      "type": "boolean",
      "title": "Is Return",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "origin",
    "destination"
  ],
  "title": "RatingRequest"
}
```

### RatingResponse

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency"
    },
    "quoted_at": {
      "type": "string",
      "format": "date-time",
      "title": "Quoted At"
    },
    "expires_at": {
      "type": "string",
      "format": "date-time",
      "title": "Expires At"
    },
    "partial": {
      "type": "boolean",
      "title": "Partial"
    },
    "weight": {
      "additionalProperties": {
        "type": "string"
      },
      "type": "object",
      "title": "Weight"
    },
    "rates": {
      "items": {
        "$ref": "#/components/schemas/ClientRate"
      },
      "type": "array",
      "title": "Rates"
    },
    "issues": {
      "items": {
        "$ref": "#/components/schemas/ProviderIssue"
      },
      "type": "array",
      "title": "Issues"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "request_id",
    "currency",
    "quoted_at",
    "expires_at",
    "partial",
    "rates",
    "issues"
  ],
  "title": "RatingResponse"
}
```

### RecoveryRequest

```json
{
  "properties": {
    "email": {
      "type": "string",
      "maxLength": 254,
      "pattern": "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$",
      "title": "Email"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "email"
  ],
  "title": "RecoveryRequest"
}
```

### RegistrationStart

```json
{
  "properties": {
    "workspace_type": {
      "type": "string",
      "enum": [
        "BUSINESS",
        "INDIVIDUAL"
      ],
      "title": "Workspace Type"
    },
    "profile": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/CompanyProfile"
        },
        {
          "$ref": "#/components/schemas/PersonalProfile"
        }
      ],
      "title": "Profile"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "workspace_type",
    "profile"
  ],
  "title": "RegistrationStart"
}
```

### RegistrationVerify

```json
{
  "properties": {
    "registration_id": {
      "type": "string",
      "format": "uuid",
      "title": "Registration Id"
    },
    "registration_secret": {
      "type": "string",
      "maxLength": 100,
      "minLength": 32,
      "format": "password",
      "title": "Registration Secret",
      "writeOnly": true
    },
    "code": {
      "type": "string",
      "format": "password",
      "title": "Code",
      "writeOnly": true
    },
    "password": {
      "type": "string",
      "maxLength": 128,
      "minLength": 12,
      "format": "password",
      "title": "Password",
      "writeOnly": true
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "registration_id",
    "registration_secret",
    "code",
    "password"
  ],
  "title": "RegistrationVerify"
}
```

### ResetPassword

```json
{
  "properties": {
    "email": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 254,
          "pattern": "^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$"
        },
        {
          "type": "null"
        }
      ],
      "title": "Email"
    },
    "token_hash": {
      "type": "string",
      "maxLength": 1024,
      "minLength": 20,
      "format": "password",
      "title": "Token Hash",
      "writeOnly": true
    },
    "password": {
      "type": "string",
      "maxLength": 128,
      "minLength": 12,
      "format": "password",
      "title": "Password",
      "writeOnly": true
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "token_hash",
    "password"
  ],
  "title": "ResetPassword"
}
```

### ReturnCommand

```json
{
  "properties": {
    "idempotency_key": {
      "type": "string",
      "format": "uuid",
      "title": "Idempotency Key"
    },
    "shipment_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Shipment Id"
    },
    "order_reference": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Order Reference"
    },
    "charge_bearer": {
      "type": "string",
      "enum": [
        "RETAILER_PAY",
        "CUSTOMER_PAY"
      ],
      "title": "Charge Bearer",
      "default": "RETAILER_PAY"
    },
    "paperless_requested": {
      "type": "boolean",
      "title": "Paperless Requested",
      "default": true
    },
    "maximum_price": {
      "anyOf": [
        {
          "type": "number",
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Maximum Price"
    },
    "customs_signer": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Customs Signer"
    },
    "hs_codes_reviewed": {
      "type": "boolean",
      "title": "Hs Codes Reviewed",
      "default": false
    },
    "store_return_reference": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200,
          "minLength": 1
        },
        {
          "type": "null"
        }
      ],
      "title": "Store Return Reference"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "idempotency_key"
  ],
  "title": "ReturnCommand"
}
```

### ReturnReference

```json
{
  "properties": {
    "reference": {
      "type": "string",
      "pattern": "^gid://shopify/ReverseFulfillmentOrder/[1-9][0-9]{0,30}$",
      "title": "Reference"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "reference"
  ],
  "title": "ReturnReference"
}
```

### ReturnRequest

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "shipment_id": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    },
    "idempotency_key": {
      "type": "string",
      "format": "uuid",
      "title": "Idempotency Key"
    },
    "customs_signer": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Customs Signer"
    },
    "hs_codes_reviewed": {
      "type": "boolean",
      "title": "Hs Codes Reviewed",
      "default": false
    },
    "store_return_reference": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 200
        },
        {
          "type": "null"
        }
      ],
      "title": "Store Return Reference"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "shipment_id",
    "idempotency_key"
  ],
  "title": "ReturnRequest"
}
```

### SelectedOffer

```json
{
  "properties": {
    "shipment_id": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    },
    "offer_id": {
      "type": "string",
      "format": "uuid",
      "title": "Offer Id"
    },
    "expected_price": {
      "anyOf": [
        {
          "type": "number",
          "exclusiveMinimum": 0.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Expected Price"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "shipment_id",
    "offer_id",
    "expected_price",
    "currency"
  ],
  "title": "SelectedOffer"
}
```

### Selection

```json
{
  "properties": {
    "shipment_ids": {
      "items": {
        "type": "string",
        "format": "uuid"
      },
      "type": "array",
      "maxItems": 100,
      "minItems": 1,
      "title": "Shipment Ids"
    },
    "mode": {
      "type": "string",
      "enum": [
        "QUOTE_ONLY",
        "FULFILL"
      ],
      "title": "Mode",
      "default": "QUOTE_ONLY"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "shipment_ids"
  ],
  "title": "Selection"
}
```

### SellerClassificationUpdate

```json
{
  "properties": {
    "seller_classification": {
      "type": "string",
      "enum": [
        "STANDARD",
        "HIGH_VOLUME_COST_SENSITIVE_SELLER"
      ],
      "title": "Seller Classification"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "seller_classification"
  ],
  "title": "SellerClassificationUpdate"
}
```

### StartAssistance

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "reason": {
      "type": "string",
      "maxLength": 500,
      "minLength": 10,
      "pattern": "^[^\\x00-\\x1f\\x7f]+$",
      "title": "Reason"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "reason"
  ],
  "title": "StartAssistance"
}
```

### StoreConfiguration

```json
{
  "properties": {
    "platform": {
      "type": "string",
      "enum": [
        "SHOPIFY",
        "WOOCOMMERCE",
        "AMAZON"
      ],
      "title": "Platform"
    },
    "display_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Display Name"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "platform",
    "display_name"
  ],
  "title": "StoreConfiguration"
}
```

### StoreState

```json
{
  "properties": {
    "is_active": {
      "type": "boolean",
      "title": "Is Active"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "is_active"
  ],
  "title": "StoreState"
}
```

### SyncTenantInput

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id"
  ],
  "title": "SyncTenantInput"
}
```

### TariffQuery

```json
{
  "properties": {
    "description": {
      "type": "string",
      "maxLength": 500,
      "minLength": 3,
      "title": "Description"
    },
    "official_only": {
      "type": "boolean",
      "title": "Official Only",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "description"
  ],
  "title": "TariffQuery"
}
```

### TenantCreate

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "company_profile": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/CompanyProfile"
        },
        {
          "$ref": "#/components/schemas/PersonalProfile"
        }
      ],
      "title": "Company Profile"
    },
    "workspace_type": {
      "type": "string",
      "enum": [
        "BUSINESS",
        "INDIVIDUAL"
      ],
      "title": "Workspace Type",
      "default": "BUSINESS"
    },
    "billing_plan": {
      "type": "string",
      "enum": [
        "PREPAID_WALLET",
        "POSTPAID_30_DAY"
      ],
      "title": "Billing Plan"
    },
    "default_currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Default Currency",
      "default": "GBP"
    },
    "owner_auth_user_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Owner Auth User Id"
    },
    "stripe_customer_id": {
      "anyOf": [
        {
          "type": "string",
          "pattern": "^cus_[A-Za-z0-9]{1,100}$"
        },
        {
          "type": "null"
        }
      ],
      "title": "Stripe Customer Id"
    },
    "is_sandbox": {
      "type": "boolean",
      "title": "Is Sandbox",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "company_profile",
    "billing_plan"
  ],
  "title": "TenantCreate"
}
```

### TenantCreated

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "company_profile": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/CompanyProfile"
        },
        {
          "$ref": "#/components/schemas/PersonalProfile"
        }
      ],
      "title": "Company Profile"
    },
    "workspace_type": {
      "type": "string",
      "enum": [
        "BUSINESS",
        "INDIVIDUAL"
      ],
      "title": "Workspace Type",
      "default": "BUSINESS"
    },
    "billing_plan": {
      "type": "string",
      "enum": [
        "PREPAID_WALLET",
        "POSTPAID_30_DAY"
      ],
      "title": "Billing Plan"
    },
    "default_currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Default Currency"
    },
    "workspace_status": {
      "type": "string",
      "const": "ACTIVE",
      "title": "Workspace Status",
      "default": "ACTIVE"
    },
    "billing_status": {
      "type": "string",
      "const": "ACTIVE",
      "title": "Billing Status",
      "default": "ACTIVE"
    },
    "owner_auth_user_id": {
      "anyOf": [
        {
          "type": "string",
          "format": "uuid"
        },
        {
          "type": "null"
        }
      ],
      "title": "Owner Auth User Id"
    },
    "wallet_provisioned": {
      "type": "boolean",
      "title": "Wallet Provisioned",
      "default": true
    },
    "is_sandbox": {
      "type": "boolean",
      "title": "Is Sandbox",
      "default": false
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "request_id",
    "tenant_id",
    "company_profile",
    "billing_plan",
    "default_currency",
    "owner_auth_user_id"
  ],
  "title": "TenantCreated"
}
```

### TestTopupInput

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "test_token": {
      "type": "string",
      "enum": [
        "tok_visa",
        "tok_chargeDeclined"
      ],
      "title": "Test Token",
      "default": "tok_visa"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "request_id"
  ],
  "title": "TestTopupInput"
}
```

### TopupRequest

```json
{
  "properties": {
    "request_id": {
      "type": "string",
      "format": "uuid",
      "title": "Request Id"
    },
    "amount": {
      "anyOf": [
        {
          "type": "number",
          "maximum": 10000.0,
          "minimum": 1.0
        },
        {
          "type": "string"
        }
      ],
      "title": "Amount"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "request_id",
    "amount"
  ],
  "title": "TopupRequest"
}
```

### TopupResponse

```json
{
  "properties": {
    "topup_id": {
      "type": "string",
      "format": "uuid",
      "title": "Topup Id"
    },
    "checkout_session_id": {
      "type": "string",
      "title": "Checkout Session Id"
    },
    "checkout_url": {
      "type": "string",
      "title": "Checkout Url"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "topup_id",
    "checkout_session_id",
    "checkout_url"
  ],
  "title": "TopupResponse"
}
```

### ValidationError

```json
{
  "properties": {
    "loc": {
      "items": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "integer"
          }
        ]
      },
      "type": "array",
      "title": "Location"
    },
    "msg": {
      "type": "string",
      "title": "Message"
    },
    "type": {
      "type": "string",
      "title": "Error Type"
    },
    "input": {
      "title": "Input"
    },
    "ctx": {
      "type": "object",
      "title": "Context"
    }
  },
  "type": "object",
  "required": [
    "loc",
    "msg",
    "type"
  ],
  "title": "ValidationError"
}
```

### VoidRequest

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "shipment_id": {
      "type": "string",
      "format": "uuid",
      "title": "Shipment Id"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "shipment_id"
  ],
  "title": "VoidRequest"
}
```

### WhatsAppSandboxSetup

```json
{
  "properties": {
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "title": "Tenant Id"
    },
    "auth_user_id": {
      "type": "string",
      "format": "uuid",
      "title": "Auth User Id"
    },
    "sender_e164": {
      "type": "string",
      "pattern": "^\\+[1-9][0-9]{7,14}$",
      "title": "Sender E164"
    },
    "route_code": {
      "type": "string",
      "pattern": "^[A-Z0-9_-]{1,24}$",
      "title": "Route Code",
      "default": "EXPORT_US"
    },
    "origin_address": {
      "additionalProperties": true,
      "type": "object",
      "title": "Origin Address"
    },
    "destination_address": {
      "additionalProperties": true,
      "type": "object",
      "title": "Destination Address"
    },
    "dimensions": {
      "additionalProperties": true,
      "type": "object",
      "title": "Dimensions"
    },
    "currency": {
      "type": "string",
      "enum": [
        "GBP",
        "EUR",
        "USD"
      ],
      "title": "Currency",
      "default": "GBP"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "tenant_id",
    "auth_user_id",
    "sender_e164",
    "origin_address",
    "destination_address",
    "dimensions"
  ],
  "title": "WhatsAppSandboxSetup"
}
```

### WorkspaceMember

```json
{
  "properties": {
    "auth_user_id": {
      "type": "string",
      "format": "uuid",
      "title": "Auth User Id"
    },
    "full_name": {
      "type": "string",
      "maxLength": 200,
      "minLength": 1,
      "title": "Full Name"
    },
    "role": {
      "type": "string",
      "enum": [
        "DISPATCHER",
        "ACCOUNTANT"
      ],
      "title": "Role",
      "default": "DISPATCHER"
    }
  },
  "additionalProperties": false,
  "type": "object",
  "required": [
    "auth_user_id",
    "full_name"
  ],
  "title": "WorkspaceMember"
}
```
