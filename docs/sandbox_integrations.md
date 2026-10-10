# Stripe and WhatsApp sandbox integration

Implementation: `backend/sandbox_hooks.py` and the existing finance/WhatsApp controllers in `main.py`. These hooks call real Stripe test APIs and accept real signed Twilio Sandbox callbacks. They do not run through credential-free `--local-preview`.

## Environment and database

Use a dedicated Supabase sandbox project. Apply migrations 006, 007 and **008_sandbox_hooks.sql** after the original schema. Migration 008 marks sandbox tenants/top-ups, stores PaymentIntent IDs and adds unique indexes for payment credit and active phone binding deduplication. It prevents converting a funded sandbox tenant into a live account. Existing wallets/top-ups are not automatically marked or altered.

Configure `.env` locally:

```dotenv
DATABASE_ENVIRONMENT=SANDBOX
SANDBOX_HOOKS_ENABLED=true
PROVIDER_ENVIRONMENT=TEST
STRIPE_SECRET_KEY=sk_test_YOUR_REAL_TEST_KEY
STRIPE_LIVEMODE=false
TWILIO_WHATSAPP_SANDBOX_ENABLED=true
TWILIO_WHATSAPP_NUMBER=+14155238886
TWILIO_ACCOUNT_SID=YOUR_REAL_AC_ACCOUNT_SID
TWILIO_AUTH_TOKEN=YOUR_REAL_TWILIO_AUTH_TOKEN
TWILIO_WEBHOOK_URL=https://YOUR_PUBLIC_HTTPS_HOST/webhooks/twilio/whatsapp
```

Keep the Supabase, encryption, quote-link, fixed-URL and platform-admin settings required by the existing application. Configure valid HTTPS success/cancel/booking URLs even when testing the direct PaymentIntent hook. Keep keys in `.env`, not source files. `backend.check_setup` reports invalid variable names without their values, and settings errors hide input values.

```powershell
.venv/Scripts/python.exe -m backend.check_setup
.venv/Scripts/python.exe main.py
```

Create an admin tenant using `POST /api/v1/admin/tenants` with the company profile described in `admin_portal.md`, `billing_plan: "PREPAID_WALLET"`, `default_currency: "GBP"`, **`is_sandbox: true`**, and an existing `owner_auth_user_id`. Sign in as that tenant member with the correct top-level tenant claim for customer APIs. The platform-owner allowlist remains separate from tenant OWNER permissions.

## £100 test payment

Authenticated OWNER, ADMIN or ACCOUNTANT request:

```http
POST /api/v1/billing/test-topup
Authorization: Bearer YOUR_SUPABASE_USER_ACCESS_TOKEN
Content-Type: application/json
```

```json
{
  "request_id": "11111111-1111-4111-8111-111111111111",
  "test_token": "tok_visa"
}
```

The amount/currency are fixed server-side to **GBP 100.00 / 10000 minor units**. A missing customer is created in Stripe test mode; an existing customer is retrieved and checked. The function creates a PaymentMethod using the official reusable test token, then confirms a card PaymentIntent with a stable idempotency key. It accepts a successful response only when livemode is false, received amount is exactly 10000, currency/customer/tenant/top-up metadata match and the status is succeeded.

The database records the registered top-up before network confirmation. Stripe calls occur outside financial DB locks. Once confirmed, a transaction locks the tenant, top-up and wallet, adds Decimal £100.00, inserts the TOPUP ledger entry with its PaymentIntent ID, and marks the registered top-up CREDITED. Any commit failure rolls back the credit and ledger; retry the **same request_id** to reconcile the same Stripe payment. Concurrent retries credit once. Ambiguous attempts older than 23 hours are blocked for reconciliation to avoid reusing expired Stripe idempotency keys.

Use a fresh request ID with `"test_token": "tok_chargeDeclined"` to exercise HTTP 402 without a wallet credit. Arbitrary card numbers/tokens, amount changes, live keys and unmarked tenants are not accepted. A test request ID cannot also be used by Checkout, and Checkout webhooks cannot credit a direct sandbox PaymentIntent top-up. Normal test Checkout also requires a sandbox tenant/database; live Checkout is blocked in the sandbox database.

### Zero-balance lock verification

The response contains `zero_balance_label_check` with `blocked: true` and `http_status: 402`. This invokes the **same Decimal funds guard used by real booking reservations and label previews**, using a copied zero-balance snapshot. It does not drain, temporarily overwrite or reserve the actual wallet.

`GET /api/v1/shipments/{shipment_id}/label/preview` checks membership/dispatch role, active billing, shipment ownership/status and locks the wallet. PREPAID printing is blocked when available balance is zero (including fully reserved funds). It only generates visibly marked sample ZPL, does not broadcast to a printer and does not charge a second shipment fee. Active postpaid accounts retain their existing wallet-funding bypass. The frontend calls this guarded endpoint in configured mode and checks available preview funds locally in credential-free preview mode.

Sandbox tenants cannot pass `mark_submitted` or settle `finish_booking(..., outcome="SUCCESS")`, so a test wallet cannot authorize a live carrier label purchase. Reservation release remains available for reconciliation. Carrier quoting can still create upstream draft quote/shipment objects; no labels are purchased by the rating pipeline.

## WhatsApp from your mobile

1. In Twilio's WhatsApp Sandbox settings, join from your phone by sending the displayed `join <sandbox code>` to **+1 415 523 8886**. Use your account's regular Account SID/Auth Token for signed inbound Sandbox messages, not Twilio test credentials.
2. Expose the configured backend through a trusted HTTPS tunnel/reverse proxy. Set the exact URL in `TWILIO_WEBHOOK_URL` and the Sandbox's **When a Message Comes in** field; select POST. This setup does not publish a tunnel automatically.
3. Register your phone binding and a saved route with the platform-owner API below. The sender must correspond to an active OWNER, ADMIN or DISPATCHER member of the marked sandbox tenant.
4. Configure TEST carrier accounts and margin rules for that tenant. Text `Quote 4.5kg from GBR to USA` (or append `route EXPORT_US` when there are multiple saved lanes).

### Saved route and verified member binding

`POST /api/v1/admin/sandbox/whatsapp-setup`, authenticated as the platform owner:

```json
{
  "tenant_id": "REPLACE_WITH_SANDBOX_TENANT_UUID",
  "auth_user_id": "REPLACE_WITH_EXISTING_TENANT_AUTH_USER_UUID",
  "sender_e164": "+REPLACE_WITH_YOUR_PERSONAL_E164_NUMBER",
  "route_code": "EXPORT_US",
  "origin_address": {
    "name": "Sandbox warehouse",
    "line1": "REPLACE_WITH_TEST_PICKUP_STREET",
    "city": "London",
    "postal_code": "SW1A 1AA",
    "country_code": "GB"
  },
  "destination_address": {
    "name": "Sandbox recipient",
    "line1": "REPLACE_WITH_TEST_DELIVERY_STREET",
    "city": "New York",
    "postal_code": "10001",
    "country_code": "US"
  },
  "dimensions": {"length_cm": "30", "width_cm": "20", "height_cm": "10"},
  "currency": "GBP"
}
```

This atomically configures a binding to `whatsapp:+14155238886` and inserts/updates the tenant's saved lane. It rejects cross-tenant phone conflicts and invalid/non-dispatch memberships. It sends no message and does not join the Sandbox on your behalf. Use real test address details that your configured carrier rating API accepts; country codes alone cannot provide a carrier quote without an address and parcel dimensions.

### Webhook authentication and response

The wrapper enforces form encoding and a 32 KiB limit, rejects invalid encoding, and uses Twilio's official RequestValidator with the **configured external HTTPS URL and all received fields**, including unknown future optional fields. Proxy Host/forwarded headers cannot change the signed URL. It checks unique AccountSid/From/To/MessageSid/Body/NumMedia fields, configured account/receiver, WhatsApp E.164 syntax, message ID, media count and optional SID aliases. Missing/invalid signatures return 403 before any tenant data is read; malformed signed payloads return 400.

The verified sender/receiver selects one active sandbox tenant binding. The existing parser normalizes GBR/USA to GB/US and retains Decimal weight. Saved-route lookup uses transaction-local RLS claims, and the real `RatingService` uses TEST provider accounts and the database-backed tenant margin evaluator. Pricing reuses the trusted message transaction connection after RESET ROLE, avoiding a second pool-slot dependency. The receipt transaction retains READ COMMITTED so a duplicate sees the first response after waiting for its advisory lock. The returned TwiML contains up to three exact two-decimal customer prices, service names, delivery estimates and signed quote-choice links. It includes a sandbox notice; no payment or label purchase is initiated by a WhatsApp quote. Message-SID receipts suppress duplicate carrier/pricing work and return the same response on webhook retries.

Unbound senders get a generic registration reply, unsupported/media input gets text instructions, invalid ISO/weight syntax gets parsing help, and missing/ambiguous saved routes ask for a route code. Provider/deadline failures return sanitized replies instead of credentials or upstream errors. Twilio receives the TwiML and delivers the reply over WhatsApp.

## What has been verified

Offline tests cover actual SDK request shapes via fakes, exact credit amounts, concurrent replay, Stripe declines/mismatches, wallet rollback, network calls outside locks, real shared zero-balance booking/printing guards, signed form validation, tenant binding, native TwiML pricing and duplicate receipts. JavaScript controller checks cover the zero-funds print block. No real Stripe/Twilio/Supabase sandbox calls or outbound messages were made by the implementation session; complete credentials, apply migration 008 and connect the webhook to run that end-to-end test.

Stripe test transactions move no funds. **Twilio Sandbox messages use standard Twilio pricing** (trial allowances may apply), so WhatsApp sandbox traffic is not guaranteed to be free. Joined Sandbox sessions expire after three days and may need rejoining. See [Stripe testing and tokens](https://docs.stripe.com/testing), [Twilio Sandbox setup, pricing and limitations](https://www.twilio.com/docs/whatsapp/sandbox), and [Twilio signature verification](https://www.twilio.com/docs/usage/security).
# Enabling provider integrations

Set `STRIPE_ENABLED=true` before using Stripe test top-ups and `TWILIO_ENABLED=true` before using WhatsApp sandbox webhooks. Both default to false, allowing Supabase-backed features to run without those provider accounts. Disabled provider endpoints return HTTP 503.

