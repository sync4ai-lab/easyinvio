# Sandbox readiness and remaining setup — 11 October 2026

The configured sandbox is running locally. This is not a certification that all
provider integrations are complete or that the app is ready for public production.
Some credentials/permissions are missing; some external capabilities still need
implementation. Changing flags cannot replace either.

## Changes completed

- Applied existing migration `019_stripe_snapshot_reconciliation.sql` to the
  configured Supabase sandbox. Stripe event/refund tables now exist. No wallet
  balances were changed and no real payment was created by the migration.
- Kept test Stripe payments and Twilio WhatsApp Sandbox enabled. Enabled the
  existing proactive support worker; no staged messages or opted-in recipients
  existed during activation, so activation sent no message.
- Reconfigured Stripe CLI forwarding to use the **project's sandbox key** in its
  child-process environment. The CLI's default authenticated account differed.
  Synchronized the corresponding listener signing secret privately in `.env`.
  Listener covers `checkout.session.completed`, `charge.refunded`, `charge.failed`.
- Removed empty optional HubSpot deal/app settings from private `.env`. The
  credential keys, account IDs, encryption keys and phone configuration remain.
  There are now zero empty assignments in `.env`; optional feature templates
  remain in `.env.example` for later use.
- Replaced the unused placeholder regional allowlist with the supported official
  Sendcloud HTTPS origin. This does not create/activate an account or tariff.
- Removed the placeholder booking URL and made that setting optional. Without a
  deployed booking UI, WhatsApp quotes direct the user to the authenticated app
  instead of emitting a broken placeholder hyperlink.
- Restarted the local backend. Health returned HTTP 200; valid Stripe signature
  returned 200 and invalid signature returned 400. Listener reported ready.
- 43 focused regression test executions passed. The real-database Stripe probe
  passed credit, refund, replay, failed-charge and rollback checks with all its
  fixture changes rolled back and zero real Stripe calls.

## Active flags in private .env

| Setting | Value | Why |
| --- | --- | --- |
| DATABASE_ENVIRONMENT | SANDBOX | Current test database/tenants |
| PROVIDER_ENVIRONMENT | TEST | Use carrier test credentials |
| STRIPE_ENABLED | true | Valid project sandbox key, listener and migration |
| STRIPE_LIVEMODE | false | No real card payments |
| SANDBOX_HOOKS_ENABLED | true | Existing sandbox harness |
| TWILIO_ENABLED | true | Real inbound phone round trip verified |
| TWILIO_WHATSAPP_SANDBOX_ENABLED | true | Official sandbox sender |
| SUPPORT_WHATSAPP_ENABLED | true | Worker ready; consent/window/template rules still enforced |
| HUBSPOT_ENABLED | false | Current token receives CRM HTTP 403 |
| HUBSPOT_ENVIRONMENT | PRODUCTION | Actual configured portal reports STANDARD; it is not a sandbox |
| HUBSPOT_UPSELL_ENABLED | false | Deal pipeline/stage IDs not supplied |
| HUBSPOT_PROVISIONING_ENABLED | false | App ID/client secret/subscription not supplied |
| AUTOMATION_PURCHASE_ENABLED | false | Current bulk engine rejects sandbox label purchase independently of this flag |

`DATABASE_TLS_STRICT=false` retains verified TLS and hostname validation with the
existing Supabase CA compatibility setting. It does not turn encryption off.

## What you need to do next

### 1. Carrier rates: obtain an EasyPost Test API key

Create/access your EasyPost account and obtain its **Test** API key. Sign into
EasyInvio as the platform owner, open **Carrier Provider Settings ? EasyPost ?
Set Up**, and configure EasyInvio's shared TEST connection once. It serves all
sandbox clients; no client selection or disclosure of the key is required.
Client-specific legacy connections remain supported separately. The platform
connection API stores encrypted credentials and maintains tenant-specific booking
references. See `docs/platform_carriers.md` for the architecture and controls.

Harbor currently uses GBP. Its carrier must return GBP prices. The adapter does
not invent currency conversions: for USD-only EasyPost prices/customs, use a
USD test workspace/route or implement and validate an explicit FX workflow.
GBP international customs currently require a compatible regional provider.
A second aggregator requires its genuine credentials and supported service limits.
Sendcloud method limits may be keyed by the shared platform connection UUID.

[EasyPost authentication and Test keys](https://docs.easypost.com/docs/authentication).

### 2. HubSpot: correct the CRM token scopes and choose the account environment

The token authenticates to the expected portal, which reports **STANDARD**.
Company records and company/contact property requests currently return **403**.
Core synchronization therefore stays disabled. Configure the chosen CRM app/key
with company/contact read and write access and property/schema read access:

```text
crm.objects.companies.read
crm.objects.companies.write
crm.objects.contacts.read
crm.objects.contacts.write
crm.schemas.companies.read
crm.schemas.contacts.read
```

Retain the account-information permission that already works. Add company-schema
write access only if provisioning properties through the API instead of the UI.
Save any regenerated token privately as `HUBSPOT_ACCESS_TOKEN`.

For strictly sandbox tests, supply a token and portal ID from a developer test or
sandbox account, then validate before setting `HUBSPOT_ENVIRONMENT=SANDBOX`.
The existing STANDARD account can support your normal/free CRM usage, but the
current worker correctly does not send sandbox tenants into it. Do not bypass
this boundary simply by changing the environment flag.

The companies must have these writable custom properties with exact internal
names; they retain the historical `veloce_` integration namespace:

| Property | HubSpot type / field type | Unique |
| --- | --- | --- |
| veloce_tenant_id | string / text | Yes |
| veloce_vat_number | string / text | No |
| veloce_currency | string / text | No |
| veloce_package_count | number / number | No |
| veloce_total_shipments | number / number | No |
| veloce_total_spend | number / number | No |
| veloce_wallet_balance | number / number | No |

After permissions are corrected, run `.\.venv\Scripts\python.exe -m backend.check_hubspot`.
Enable `HUBSPOT_ENABLED=true` only after that succeeds for the intended environment.
Onboarding already queues jobs in Supabase; a disabled worker makes no remote CRM
records. [HubSpot company API](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/companies/guide)
and [properties API](https://developers.hubspot.com/docs/api-reference/legacy/crm/properties/guide).

Upsell deals additionally require deal read/write access, the milestone property,
and pipeline/stage IDs. Closed-won provisioning additionally requires a HubSpot
app webhook subscription, app ID, app client secret and public signed callback.
The current ngrok gateway exposes only Twilio callbacks, not HubSpot's endpoint.
These omitted settings are available in `.env.example`; a service key alone
does not configure the inbound app subscription.

### 3. Proactive WhatsApp alerts: recipient consent and templates

Conversational replies work. The support worker is enabled, but only verified,
active OWNER/ADMIN bindings with notification consent can receive remedies.
The currently paired test membership is DISPATCHER. Use an appropriate client
owner/admin test identity for support alerts and wallet/billing tests; do not
change dispatcher financial permissions to make a test pass.

For out-of-session alerts, create/approve a WhatsApp template with one remedy
variable and add its HX identifier as `SUPPORT_WHATSAPP_CONTENT_SID`. Without that
identifier, delivery waits for a valid recent inbound customer-service window.
No template field is needed for normal immediate conversational replies.

### 4. Store synchronization and carrier tracking

`ECOMMERCE_CONNECTORS={}` currently means no authenticated external store is
configured. Shopify needs a development store, app token, webhook secret, exact
shop domain, store/tenant/member UUID mapping and verified SKU weights. Add the
mapping described by `backend/ecommerce_connectors.py` only after these exist.
Registered database stores alone do not install a storefront app.

`TRACKING_WEBHOOK_KEYS={}` means no external aggregator tracking key is mapped.
Configure per-tenant/account HMAC secrets and approved POD hosts; do not invent a
provider signature scheme. The current adapter's documented protocol is not a
claim that every provider's native webhook is compatible without an adapter.

## Remaining implementation/deployment work

- The bulk fulfillment engine explicitly blocks purchases for sandbox tenants
  and TEST mode. `AUTOMATION_PURCHASE_ENABLED=true` cannot make genuine carrier
  sandbox label purchases work. A separate tested provider-sandbox purchase path
  is required before the full dispatch/label/customs-print journey can pass.
- Sendcloud currently has a rate adapter; native label purchase remains disabled.
- Shopify has configured native import/fulfillment support. WooCommerce/Amazon
  intake uses the signed adapter framework; complete native marketplace polling
  and fulfillment are not implemented by filling `.env` fields.
- Stripe wallet Checkout/reconciliation exists. Stripe Invoicing and Stripe Tax
  are not separately implemented; there are no switches to enable them. Their
  business rules and integrations need implementation before those tests.
- HS classification is a deterministic suggestion engine requiring customs
  review, not a guarantee of official regulatory classification.
- Public production needs HTTPS hosting, a deployed authenticated booking UI,
  a production secret manager, separate live credentials/data and operational
  monitoring/backups. The ngrok development tunnel is not that deployment.

Do not set `PROVIDER_ENVIRONMENT=LIVE`, `STRIPE_LIVEMODE=true`, or change the
database environment to LIVE for the requested sandbox test run.

## Resuming local listeners

The backend runs at `http://127.0.0.1:8000`. Keep ngrok/its restricted port-8009
ingress running for Twilio. `scripts/configure_whatsapp_tunnel.py` configures it.
To restart Stripe forwarding, stop the previous listener, then run
`scripts/start_stripe_sandbox_listener.py` with the project's Python interpreter
and restart the backend afterward. That helper uses the private sandbox key in
the child environment, so it does not inherit a different CLI account. Its secret
is for the local listener, not a deployed Stripe Dashboard endpoint.
