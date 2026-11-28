# Wallet & Billing

Choose **Change plan**, select a plan, review the price and effective date, then confirm.
For a free/assigned account, this starts a new secure subscription checkout. The
current feature tier is not evidence of a previous payment. Sandbox accounts use
Stripe test mode; paid access starts only after verified subscription payment.

Migration 050 grants existing sandbox workspaces complimentary Command access.
Mavuri Consultancy was verified read-only as sandbox, Command, complimentary,
with no Stripe subscription or period end. No account data was changed in this update.

## Paid-agreement rules

- Upgrade: effective after payment; charge the tier price difference for the remaining
  billing period, using UTC seconds and actual calendar boundaries, rounded to pennies.
- Downgrade: effective at renewal; current features remain until then. No mid-period credit.
- Monthly cancellation: 30 days' notice. Charge only notice service not covered by
  the paid period; any unused prepaid amount requires review, not an automatic refund.
- Annual cancellation: remove the annual discount; price elapsed service and the
  30-day notice at monthly rates. Refund verified unused prepaid money to the original
  payment source, with proportional original tax, after service ends. Missing evidence
  or an additional balance requires reconciliation and explicit payment terms.
- Previews do not charge. Confirmation requires the same unexpired terms and version.
  Only the customer Owner can authorize; assistance sessions cannot.

## Statements

- **Current month**: live activity through now.
- **View date range**: inclusive dates; read-only, up to 366 days. Download PDF/CSV;
  no database statement is created. A date-mismatched old backend produces a restart
  message rather than displaying the wrong month as a successful result.
- **Previous Statements**: choose a month/year, then View monthly statement. The
  complete, finished calendar month is retained as an immutable snapshot. February,
  leap years, and 30/31-day months use their real boundaries; no 32-day wording.
- Display/export references: `EI-01092026-30092026`. Internal storage identifiers stay
  unique across workspaces, and previously issued snapshots/hashes are not rewritten.
- Both paths retain tenant/role checks and the 10,000-transaction bound. Statements
  summarize funding, charges and refunds; original tax invoices remain separate.

## Retired carrier invoice auditor

The invoice-upload auditor, savings comparison, surcharge draft UI, related APIs,
AI worker and marketing claims have been removed. General support tickets,
shipment claims, wallet reconciliation and tax/ledger exports remain available.

Migration `059_retire_carrier_bill_auditor.sql` drops `billing_disputes` and
`shipment_dispute_drafts`; it is supplied for deliberate application after this
code is deployed and has not been run against the shared database. It does not
delete support tickets, wallet records, subscriptions or statement snapshots.

## Local subscription checkout configuration

The inspected `.env.local` has Stripe test mode enabled but `SUBSCRIPTION_PRICE_IDS`
is empty. Wallet funding is separate and does not require recurring plan Prices.
Create test recurring GBP Prices at the published amounts, then configure:

```dotenv
SUBSCRIPTION_PRICE_IDS={"VELOCITY:MONTHLY":"<test price ID for GBP25/month>","VELOCITY:ANNUAL":"<test price ID for GBP240/year>","COMMAND:MONTHLY":"<test price ID for GBP75/month>","COMMAND:ANNUAL":"<test price ID for GBP720/year>"}
```

These are instructions, not an importable environment file. Replace each placeholder
with its real `price_...` ID and restart the local server. Production requires its own
live-mode Prices and configuration. Checkout validates amount, currency, mode and
recurrence on the server; a local preview does not authorize a payment.


## Plan display and registration-aware statements

The summary emphasizes the plan name; Starter is shown as Free. Customer billing
panels omit internal environment labels. Environment checks, verified Stripe
receipts, and entitlement enforcement remain mandatory. Review is a preview;
confirmation authorizes the chosen terms, and the current plan changes only after
verified payment/application. Billing summaries and Profile refresh after an applied
change. Pending changes and a return from checkout use bounded status polling;
the return URL is never payment proof. Scheduled downgrades retain the current
plan until their effective date.

Statement availability starts with `tenants.created_at`, in UTC. Activity previews
and their PDF/CSV exports reject a start date before the registration day. The
current-month default starts at the later of month start and registration day.
Completed monthly statements are available from the registration month onward;
the first month can be partial. Earlier saved artifacts are filtered and cannot
be downloaded through statement detail. New accounts show "No statements to
display" until their first calendar month is complete. Existing snapshots are
not deleted or rewritten.

Local subscription checkout needs four recurring GBP Price mappings in
`SUBSCRIPTION_PRICE_IDS`: Velocity monthly £25 / annual £240, and Command monthly
£75 / annual £720, excluding applicable tax. The local configuration now points
to validated prices in its existing Stripe test environment. No customer
subscription or payment was created during setup. Launch requires the equivalent
live prices and matching live payment/webhook configuration; hiding environment
labels in the UI does not switch payment mode. Restart the local backend after
environment updates.


Subscription checkout redirects use the configured payment success/cancel origins,
independently of public booking links. The local launcher returns the browser to
127.0.0.1; HTTP loopback is accepted only for Stripe test mode. Existing Stripe
Checkout sessions retain their original return URLs.

Owner billing refresh can reconcile a missed initial checkout callback using
real paid checkout events fetched with the server's Stripe credentials. Recovery
accepts no client-provided payment status or session ID, scopes receipts to the
signed-in Owner/workspace and reuses the idempotent subscription event processor.
It scans at most 100 recent checkout events for up to three pending receipts.
Normal signed Stripe webhooks remain required for ongoing invoice, cancellation
and renewal updates in a deployed environment.
