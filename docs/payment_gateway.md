# Stripe prepaid wallet Checkout

The new `backend/payment_gateway.py` connects the existing shared financial
engine to authenticated hosted Checkout. It uses the official Stripe client's
native asynchronous `checkout.sessions.create_async`, rather than blocking a
FastAPI request with the synchronous Session.create method. Card entry stays on
Stripe, never inside an app iframe or local card form.

## Routes

- `POST /api/v1/billing/create-checkout`: OWNER/ADMIN/ACCOUNTANT only. The body
  contains the verified tenant UUID, Decimal amount string and retry UUID.
  Request amounts range from 1.00 to 10000.00 with two decimal places. Floats,
  booleans, NaN and cross-tenant requests are rejected. Test keys require a
  SANDBOX database and a sandbox-marked PREPAID_WALLET tenant.
- `GET /api/v1/billing/topups/{topup_id}`: tenant-isolated database confirmation.
- `POST /api/v1/billing/webhooks/stripe`: alias of the existing signed receiver.
  The original `/webhooks/stripe` and `/v1/wallet/topups` paths remain supported.

```json
{
  "tenant_id": "YOUR_VERIFIED_TENANT_UUID",
  "request_id": "A_UUID_TO_REUSE_FOR_RETRIES",
  "topup_amount": "250.00"
}
```

Response includes `url`, `topup_id`, `checkout_session_id` and `mode: TEST`.
There is no live-payment switch on this new testing route. The existing live
financial route keeps its existing environment fences.

If the tenant has no Stripe customer, the gateway creates one using canonical
company/email data, with a tenant-scoped idempotency key and advisory lock.
All remote Stripe calls occur after financial transactions end. A PENDING
top-up is recorded before Checkout creation; retries reuse the registered
session and never add credits during creation.

Session metadata includes `tenant_id`, `purpose=wallet_topup` and `topup_id`.
Customer, session, request identity, amount, currency and environment must all
match the registered top-up. A raw signed `checkout.session.completed` or
`checkout.session.async_payment_succeeded` event credits only if
`payment_status=paid`. Unpaid or unrelated sessions do not credit the wallet.
Within one PostgreSQL transaction the service locks the tenant/top-up/wallet,
adds the Decimal amount to balance, inserts one ledger entry and marks the
top-up CREDITED. Session/event uniqueness and the CREDITED check prevent
double funding, including duplicate events and concurrent delivery. Any
ledger failure rolls back the balance and payment state.

## Local configuration

No new migration is needed. Existing wallet tables and migrations through 008
provide the ledger/top-up fields; migration 018 optionally queues CRM wallet
metrics. This feature does not enable HubSpot, Twilio or live carrier purchases.

Save the test credentials privately in `.env`:

```dotenv
STRIPE_ENABLED=false
STRIPE_LIVEMODE=false
STRIPE_SECRET_KEY=sk_test_YOUR_SECRET_KEY
STRIPE_WEBHOOK_SECRET=whsec_YOUR_ENDPOINT_SIGNING_SECRET
DATABASE_ENVIRONMENT=SANDBOX
CHECKOUT_SUCCESS_URL=http://127.0.0.1:8000/?payment=success
CHECKOUT_CANCEL_URL=http://127.0.0.1:8000/?payment=cancel
```

Use the actual frontend origin/port if served separately. Return URLs come
only from server configuration; the gateway appends `payment` and `topup_id`
parameters. Production hosting would use HTTPS on the deployed EasyInvio.com
app origin. Changing branding does not configure DNS or hosting. Loopback HTTP
is accepted for local testing; live mode requires HTTPS.

### Windows PowerShell setup

Install the official CLI once (Node/npm required):

```powershell
npm.cmd install -g @stripe/cli
stripe.cmd --version
```

If `stripe` is not recognized, close/reopen PowerShell. The npm wrapper can also
be called directly, avoiding PATH and PowerShell script-policy issues:

```powershell
& "$env:APPDATA\npm\stripe.cmd" --version
& "$env:APPDATA\npm\stripe.cmd" login
```

Approve the browser pairing for the intended Stripe account/sandbox. Starting
PowerShell in `C:\WINDOWS\system32` is fine; `cd C:\Projects\veloce-ai` selects
this project but does not install the CLI. Copy commands without the PS prompt,
trailing backslashes or Markdown link formatting.

Forward events using the Stripe CLI:

```powershell
& "$env:APPDATA\npm\stripe.cmd" listen --events checkout.session.completed,checkout.session.async_payment_succeeded --forward-to http://127.0.0.1:8000/api/v1/billing/webhooks/stripe
```

Use the `whsec_...` printed by that listener for local forwarding. It is not
necessarily the same secret as a dashboard-hosted endpoint. Once test credentials
and URLs are configured, enable STRIPE_ENABLED and restart the configured backend.
Use a financial-role login belonging to a marked sandbox prepaid tenant. Synthetic
fixture Auth principals are banned and are not customer logins.

## UI

Wallet & Billing has a Top Up Wallet Credit action and native accessible
`stripePaymentModal` dialog with 100/250/500 tiers, styled for the active wallet
currency. A payment window is opened synchronously during the user gesture to
avoid popup blocking. If blocked, a validated `checkout.stripe.com` link is shown.
The modal stores the retry ID locally and polls only the authenticated status
endpoint. A browser success parameter never changes a balance. The wallet
refreshes and the payment window closes only after the ledger reports CREDITED.
Unconfirmed payments remain pending; failures are shown without assuming credit.
The legacy sample-credit action remains explicitly separate and browser-only.

Unsigned users cannot proceed to Checkout; dispatcher navigation hides Wallet
and the API rejects financial requests regardless of DOM manipulation.

## Validation

90 selected tests passed, covering Checkout, signed webhooks, replay and race
handling, atomic rollback, optional integrations and freight/admin regressions.
Chromium verified the modal, tiers, blocked unsigned checkout, the popup URL,
pending-state balance preservation, server-confirmed credit and responsive
widths 375/768/1366, with no JavaScript errors.

The real Supabase sandbox probe created controlled PENDING top-ups, credited
one with exact Decimal math, proved replay did not duplicate credit, injected a
database ledger rejection and verified rollback. The entire probe transaction
was then rolled back. **No real Stripe API requests or card payments occurred.**
Live sandbox-provider verification remains pending actual Stripe credentials.

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_payment_gateway tests.test_sandbox_hooks -q
.\.venv\Scripts\python.exe -m tests.payment_database_probe
.\.venv\Scripts\python.exe -m tests.test_payment_browser
```

References: [Checkout Session creation](https://docs.stripe.com/api/checkout/sessions/create),
[Checkout fulfillment](https://docs.stripe.com/checkout/fulfillment).


## Snapshot controller update

The primary `/api/v1/billing/webhooks/stripe` route now uses the durable,
three-event snapshot controller. Apply migration 019 and follow
[stripe_snapshot_controller.md](stripe_snapshot_controller.md) for the
Checkout completion, charge refund and failed charge scope, acknowledgement
policy and updated local listener command. This supersedes the earlier alias
and two-event instructions for that primary endpoint; the legacy webhook path
retains its old compatibility behavior.
