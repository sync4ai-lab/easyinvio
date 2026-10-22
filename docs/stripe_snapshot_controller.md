# Stripe snapshot webhook and ledger reconciliation

The complete controller is in `backend/payment_gateway.py`, sharing the existing
FinanceEngine and trusted asyncpg pool. Apply migration 019 after 018, then
restart the configured backend. No migration or financial changes from the
verification probe were committed to Supabase.

## Exact endpoint scope

`POST /api/v1/billing/webhooks/stripe` verifies the original body bytes with
`stripe.Webhook.construct_event` and the endpoint secret. Invalid or duplicate
signature headers return 400. Oversized requests return 413. Test/live mismatches
and connected-account events are rejected. Configure account-level Snapshot
payloads in Stripe; thin notification bodies are not accepted.

Only these three events are dispatched:

| Event | Reconciliation |
| --- | --- |
| checkout.session.completed | A paid, registered wallet top-up credits exactly once; the intent is mapped and transaction_state becomes SUCCESS |
| charge.refunded | A registered charge debits only the new cumulative refund increment and appends REFUND_DEBIT |
| charge.failed | Maps the intent/top-up and marks an uncredited top-up FAILED; late failures never downgrade a credited payment |

Other signed event types receive 200 with ignored=true and cannot alter a wallet.
The endpoint records the event's `api_version`, including the requested
`2026-09-30.endive`, as audit metadata. It validates the explicit snapshot
resource fields rather than rewriting the event or claiming to change your
Dashboard/API version. Choose your actual supported API version in Stripe's
endpoint configuration and keep SDK upgrades separately tested.

The older `/webhooks/stripe` handler retains its legacy Checkout completion and
async-success behavior for compatibility. Point the production event destination
at the new `/api/v1/billing/webhooks/stripe` path. Since the new scope deliberately
excludes async-payment success, do not introduce delayed payment methods without
extending its supported scope first. The current customer Checkout is card-only.

## Accounting and isolation

Amounts use strict integer minor units divided by Decimal(100); the existing
wallet currencies are GBP/EUR/USD. Currency, charge amount, customer, intent,
tenant and registered top-up identities are cross-checked. A customer ID alone
does not authorize a debit. New Checkout requests propagate top-up metadata to
the PaymentIntent, allowing failed charges to identify the original pending row
before Checkout completion. Completed snapshots bind the actual intent ID.

The existing top-up row retains the Checkout URL saved when the session was
created. `transaction_state=SUCCESS` is saved for the requested transaction
trace; `status=CREDITED` remains the authoritative wallet state so existing UI,
tests and replay protections remain compatible. FAILED is allowed by the new
migration, with credited_at remaining null for an uncredited failure.

Credits, refund debits, cumulative charge checkpoints, journal entries and event
completion are committed atomically. Refund snapshots contain cumulative
amount_refunded: an event at 20.00 followed by one at 60.00 debits 20.00 and then
40.00. Replays and later-arriving 20.00 snapshots do not debit again. The revised
ledger index keeps TOPUP credit unique, while allowing multiple REFUND_DEBIT rows
linked to that original top-up. Event IDs remain unique in the journal.

Refunds never consume reserved label funds or violate the nonnegative wallet
constraints. An insufficient available balance holds the tenant workspace
(SUSPENDED/PAST_DUE), preserves the outstanding refund checkpoint and marks the
event RECONCILIATION_REQUIRED. An operator must settle funds/reservations, reset
the event to PENDING for replay and review the workspace status before restoring
dispatch. The handler does not issue a Stripe refund; it accounts for a refund
that Stripe already reported. Keep immutable journal history; do not delete
prior credits to represent a refund.

Unmapped/out-of-order charges are saved for retry and eventual reconciliation.
No guessed customer-to-wallet deduction occurs. Unsupported non-wallet purposes
are ignored. Anonymous or unrelated charges cannot debit another tenant.

## Durable acknowledgement and failures

Verified snapshots are saved in private stripe_webhook_events before processing.
The database-backed worker retries pending events with exponential delays, up to
12 attempts before manual reconciliation. Event row locks, tenant/top-up/wallet
locks and refund checkpoints serialize concurrent financial processing.

A downstream failure rolls back the financial transaction and returns HTTP 200
with deferred=true because the durable receipt can be replayed. If the database
cannot save the receipt at all, HTTP 503 is necessary: returning 200 then would
permanently lose a payment/refund. Stripe retries are safe because processing is
idempotent. The log records only the exception type/sanitized code and traceback
frame names/line numbers, never raw exception text, credentials, card data or
snapshot bodies. Stored snapshots retain only reconciliation fields, not card
or personal-address data.

## Configure and operate

Keep STRIPE_ENABLED, STRIPE_LIVEMODE, API key, signing secret and database
environment consistent. Live mode requires the separate LIVE database and
non-sandbox tenants. This webhook supports both configured environments; the
new create-checkout gateway remains explicitly test-only.

For local forwarding, stop the previous listener and use:

```powershell
& "$env:APPDATA\npm\stripe.cmd" listen --events checkout.session.completed,charge.refunded,charge.failed --forward-to http://127.0.0.1:8000/api/v1/billing/webhooks/stripe
```

Verify the listener's signing secret matches STRIPE_WEBHOOK_SECRET. For a
deployed endpoint use its own Dashboard signing secret and public HTTPS URL.
Do not change tax registrations, initiate refunds, or publish live invoices as
part of controller setup. This implementation adds reconciliation, not Stripe
Invoicing, Tax or dispute workflows.

## Verification evidence

- 99 selected automated tests passed, including signed dispatch, credits,
  cumulative/duplicate/concurrent/out-of-order refunds, failed charges,
  cross-tenant rejection, durable retries and receipt-storage outages.
- Real Supabase rollback-only probe passed: migration rerun, SUCCESS trace and
  paid credit, partial refund journal entries, replay checks, failed-charge
  mapping, paid-status preservation, injected ledger failure rollback and
  private queue grants.
- No actual Stripe calls, card payments or refunds occurred in the probe.
- Migration 019 is provided for operator deployment and was rolled back after
  testing; apply it before restarting with this controller.

Run:

```powershell
$env:PYTHONPATH='C:\Projects\easyinvio;C:\Projects\easyinvio\tests'
.\.venv\Scripts\python.exe -m unittest tests.test_stripe_snapshots tests.test_payment_gateway tests.test_sandbox_hooks -q
.\.venv\Scripts\python.exe -m tests.stripe_snapshot_database_probe
```

References: [Stripe event types](https://docs.stripe.com/api/events/types),
[Charge refund fields](https://docs.stripe.com/api/charges/object),
[Webhook signature verification and retries](https://docs.stripe.com/webhooks).
