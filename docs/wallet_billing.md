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


Billing screens display UTC dates without times. Provider timestamps are retained
for paid-period reconciliation and exact proration; an existing paid renewal
anchor is not silently moved to midnight. Amounts and displayed remaining days
use two decimal places, while calculations retain their exact precision.

An existing subscription upgrade offers card or full-wallet payment. Wallet
availability excludes reserved funds and is rechecked under lock at confirmation
and settlement. The provider invoice total must match the authorized wallet total;
tax changes require review without a new debit. A wallet-settled provider invoice
is marked paid out of band, with an idempotent wallet debit and recurring-price
update. Unknown provider outcomes require finance review, never a second charge.
Future renewals retain their existing payment method. Initial recurring-plan
activation continues to use secure card checkout.

Owner-scoped processing of an already-authorized operation is available from
billing confirmation/refresh, so local WEB mode does not need a general billing
worker to prepare an upgrade invoice or observe its payment. It checks tenant and
original actor, respects operation leases and never starts other shared workers.
Annual refunds involving wallet-settled provider invoices require reconciliation
of the original funding source; no card refund is inferred from a wallet debit.


The plan payment selector and wallet summary now share the wallet-ledger balance
source. Billing refresh and each upgrade review reload the available amount;
missing balance data disables wallet selection with an unavailable message,
never a synthetic zero. The server still validates funds at confirmation.
Failed historical plan-change requests stay in the audit data but do not appear
under the active-plan summary. Genuine unresolved requests remain visible.
Reviews use compact amount/date/price cards, a single proration calculation and
explicit "No payment due now" wording for zero-cost changes.


Downgrade review includes an inline comparison generated from the current and
target capabilities returned by the server: lower software fee, reduced parcel,
store and user allowances, and selected supported features that cease to be
included. It omits features retained in the target tier and does not advertise
planned capabilities. Keeping the current plan dismisses the preview without
confirming any commercial operation; downgrade confirmation remains available.
The displayed tax label is simply "tax". This copy change does not change the
wallet subscription tax percentage, automatic-tax configuration or VAT policy.


Subscription VAT configuration: prices remain exclusive of tax. For approved UK
standard-rated billing set SUBSCRIPTION_TAX_PERCENT=20 and a validated exclusive
GB Stripe tax-rate ID in SUBSCRIPTION_STRIPE_TAX_RATE_ID. Both card and wallet
reviews show net, VAT and total; tax is calculated on the rounded prorated net
fee. Checkout attaches the rate to the subscription; upgrade invoices attach the
same rate and validate the total before settlement. Recurring plan changes carry
the rate to future invoices. Do not combine fixed-rate and automatic-tax modes.
Positive fixed VAT is restricted to GB billing and live collection requires
SUBSCRIPTION_VAT_REGISTERED=true after actual VAT registration. International or
exempt/reverse-charge tax treatment needs a separate approved policy; the fixed
UK setting is not a blanket worldwide 20% rule.

Downgrades retain the existing end-of-period policy: paid access continues until
renewal, so there is no mid-cycle credit or refund. The preview shows zero credit
now and the new renewal net/VAT/total. Moving a downgrade to an immediate cutover
would require a distinct, approved credit/refund policy. Annual cancellation
refunds use verified original invoice net and VAT amounts, not the current rate;
tax never paid must never be invented in a refund. Historical invoices are not
rewritten and earlier untaxed payments are not retroactively charged.

Local test VAT was configured with an exclusive 20% test rate and future UK test
subscription invoices were updated with no proration. No payment was created.
The owner confirmed UK VAT registration on 28 November 2026. Live tax collection
remains unchanged pending the customer tax classification and rollout policy below.


VAT rollout decision, researched 28 November 2026:

- Treat the software subscription separately from parcel transport, customs tax,
  wallet funding and other services. The UK fixed-rate implementation above is
  a tested restricted mode, not completed international tax support.
- UK-established supplier to UK subscription customers: normally 20%, including
  VAT-registered business customers. Command GBP 75 net + GBP 15 VAT = GBP 90.
  For overseas B2B general-rule services, determine the receiving establishment
  and retain evidence of business status; normally no UK VAT and the applicable
  reverse-charge treatment. Incorporation country alone is insufficient.
- EU private-consumer software subscriptions normally follow consumer location
  and its local VAT rate. A UK-only established supplier cannot rely on the EU
  EUR 10,000 threshold. Non-Union OSS can consolidate eligible EU B2C service VAT
  reporting; registration and filing still need arranging.
- Collect verified billing name/address/country, business or consumer status,
  VAT number and validation outcome, receiving establishment where relevant,
  and required location evidence. Do not reuse a parcel recipient's shipping
  address as the subscription customer's tax location.
- Recommended international subscription design: Stripe Tax with actual merchant
  registrations and suitable software tax classification, using the same server
  calculation and stored net/tax/gross evidence for card and wallet. Missing
  registrations can produce zero tax; that must not be interpreted as exemption.
- Freight needs its own matrix: customer business status, place of supply,
  transport route, zero-rating evidence and whether EasyInvio contracts as
  principal or agent. UK domestic courier services are generally standard-rated;
  qualifying international transport can be zero-rated. Neither blanket 20%
  nor copying every carrier input VAT amount is a sufficient output-tax policy.
- Obtain accountant confirmation of wallet classification and tax point. Advance
  payments and single-/multi-purpose vouchers have different treatment; do not
  automatically tax both a top-up and its later spending.
- Consumer-facing prices must include unavoidable VAT; business net prices need
  clear VAT labelling. Consider showing UK GBP 75 ex VAT / GBP 90 inc VAT together.
- Historical real undercharged VAT requires accountant review and proper invoice
  correction; it is not erased by fixing future configuration. No automatic
  retroactive customer debit is authorized by this implementation.

Primary sources:

- HMRC place of supply: https://www.gov.uk/guidance/vat-place-of-supply-of-services-notice-741a
- HMRC digital consumers: https://www.gov.uk/guidance/the-vat-rules-if-you-supply-digital-services-to-private-consumers
- European Commission OSS: https://vat-one-stop-shop.ec.europa.eu/one-stop-shop_en
- HMRC freight: https://www.gov.uk/guidance/vat-on-freight-transport-and-associated-services-notice-744b
- HMRC advances: https://www.gov.uk/guidance/vat-instalments-deposits-credit-sales
- HMRC vouchers: https://www.gov.uk/guidance/business-promotions-and-vat-notice-7007
- HMRC corrections: https://www.gov.uk/guidance/how-to-correct-vat-errors-and-make-adjustments-or-claims-vat-notice-70045
- CMA consumer prices: https://www.gov.uk/government/publications/price-transparency-cma209/providing-clear-and-accurate-information-about-prices-summary
- Stripe customer location: https://docs.stripe.com/tax/customer-locations
- Stripe standalone calculations: https://docs.stripe.com/tax/standalone-tax-api
- Sendcloud billing entities: https://www.sendcloud.com/terms-conditions/
- Sendcloud country-specific VAT: https://support.sendcloud.com/hc/en-us/articles/360025144311-Can-I-get-a-VAT-free-invoice

Before European commercial rollout, approve the receiving-establishment and
business-status evidence flow, EU consumer registration/filing arrangements, and
shipping principal/agent contracts and tax matrix. Do not activate international
collection merely by changing SUBSCRIPTION_TAX_PERCENT.
