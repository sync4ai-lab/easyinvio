# Subscription changes and itemized statements

Apply **052_subscription_lifecycle_and_statements.sql once, after 051**. Do not
rerun 050 or 051. The migration creates scheduling, append-only audit events,
statements and original-payment refund records. It does not charge customers,
call providers or change existing paid agreements.

The release defaults `BILLING_LIFECYCLE_ENABLED=false`. Enable it on both web and
the logistics worker only after 052 has succeeded and subscription tiers are
enabled. A running worker is necessary for provider processing, scheduled changes
and refunds. Migration 052 is checked at startup when the flag is enabled.

## Cancellation policy

For an annually prepaid agreement, service ends 30 days after the confirmed
cancellation preview's request timestamp. Remove the annual discount: value elapsed
service **and the notice period** at the published monthly price, using actual
anchored calendar months and UTC seconds for partial months. Historical upgrades
split usage by tier. Round money half up to pennies.

Refund = max(verified prepaid net cash remaining − repriced usage and notice, 0).
For example, Velocity renewed on 9 November at £288 net annually and cancelled on
15 November ends on 15 December. Monthly-price usage plus notice costs £34.61;
the net refund is £253.39. Original invoice tax is returned proportionally. At
20% original tax, the gross refund is £304.07. This is a calculation example,
not a determination of the merchant's VAT obligations.

Refunds are queued when service ends and returned to original Stripe payments;
they are never converted into wallet funding. Previously refunded money is
excluded. Split-tender, missing payment references, externally changed refunds,
unknown provider outcomes and unreconciled invoices require finance review.
An original annual invoice must match the recorded initial tier; promotional,
split-tender or untracked legacy plan adjustments require reconciliation instead
of guessing the customer's historical monthly price.
The customer sees any extra balance before confirming; a positive balance uses
a separate hosted invoice, never a silent additional card debit. Cancellation
still takes effect if that invoice remains unpaid. There are no negative refunds.

Monthly cancellation keeps already-paid access and charges only the uncovered
notice days, rather than a full extra cycle. A 9 November–9 December renewal,
cancelled on 15 November, ends 15 December: six days of the next 31-day cycle
cost £5.61 net on Velocity. Trial/complimentary access creates no notice charge
and never extends beyond its existing expiry.

## Payments and access

Existing Stripe checkout remains the initial paid activation path. Lifecycle
changes require a bounded, reconciled agreement. Actual customer Owners may
preview and confirm changes. Admins and Accountants may read financial data;
Dispatchers cannot. Assisted support sessions cannot authorize commercial changes.
The existing authentication, membership and assistance controls remain in use.

Every command uses a request UUID, a 10-minute server-owned preview hash and a
plan version. Tenant and wallet locks preserve shipment reservations. An upgrade
only grants the new tier after payment. Insufficient wallet funds fail the
operation; later top-ups do not silently retry it. Wallet-funded agreements
require explicit wallet selection. Stripe-bound agreements use their Stripe
agreement and hosted invoices. Provider price changes use `proration_behavior=none`
because EasyInvio has already calculated the authorized proration.

Downgrades preserve the current tier until its period ends. The lower Stripe
recurring price takes effect at renewal, with no mid-cycle refund. Starter
downgrades stop renewal. A trial selection does not authorize a paid wallet
renewal. Subscription billing cycles are retained; this flow does not switch
monthly agreements into annual agreements or vice versa.
An irregular legacy billing period or a wallet renewal processed more than a
day late requires finance review, rather than guessing a cycle or charging a
full software period after an extended outage. Calendar-month anchoring is
preserved for supported regular periods.

Configure approved `SUBSCRIPTION_PRICE_IDS` as in subscription_rollout.md.
Set `SUBSCRIPTION_WALLET_TAX_PERCENT` to the merchant's actual tax treatment;
its default is not tax advice. Enable `SUBSCRIPTION_AUTOMATIC_TAX_ENABLED` only
with Stripe Tax configured. Customers review and pay Stripe-hosted invoices.
Provider events require the existing verified Stripe signature and environment.
Workers reconcile invoice payment references before making original-card refunds.

`REVIEW` means the external outcome is uncertain: reconcile the operation,
invoice/payment and provider identifiers before any manual resolution. Do not
delete immutable events, reissue a charge under a new UUID, or set the state
back to AUTHORIZED to bypass this check. No general finance-review mutation API
is exposed in this release.

## Workspace and statements

Open **Wallet → Plan, billing & statements → Refresh billing**. Owners see
preview/confirm controls; other finance roles see read-only data. A second
refresh shows queued invoice/payment progress. No background browser polling
or provider calls are triggered by merely opening the landing page.

Create a statement for a completed UTC range (exclusive end, maximum 32 days),
or preview the current month. The default completed period is the previous
calendar month. Final JSON snapshots are immutable, hashed and repeatable;
PDF/CSV exports come from that saved snapshot. Exports are private and no-store.
The screen shows the first 100 lines; exports include the complete statement.
Shorten the range for more than 10,000 financial lines.

Wallet ledger movements are the balance authority. Wallet top-ups are funding,
not revenue. Shipment captures and actual credited label refunds appear once;
booked shipments without a wallet capture are labelled external/postpaid.
Subscription card invoices and settled card refunds do not move the wallet.
Estimated disputes, projected overages and uncompleted refunds are not money.
Tax is included only when recorded: legacy missing tax remains unknown. These
are **account activity statements, not VAT invoices**. Late postings appear in
the period they are recorded. Each currency is separate.

## Validation

Offline arithmetic tests cover calendar boundaries, half-up rounding, annual
discount removal, historical upgrades and late-cancellation balances. Disposable
PostgreSQL tests apply 050–052, verify real constraints, wallet holds, replay,
Owner authorization, immutable statements, cross-workspace isolation and a
synthetic original-card refund with VAT. No production database or payment
provider is used by these tests.
