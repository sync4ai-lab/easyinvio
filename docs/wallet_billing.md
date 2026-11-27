# Wallet & Billing: local test guide

Restart your usual local launcher, preserving any WhatsApp flags. Sign in at
`http://127.0.0.1:8000/workspace` and open Wallet & Billing.

1. Check available/reserved balances, active plan, monthly usage and scheduled changes.
2. Filter transactions, change pages and enable reservation holds. Balances after
   each movement are stored server values; the browser does not reconstruct them.
3. Preview this month or generate a completed-period statement. Inspect subscription
   charges, carrier totals, itemized lines and the wallet waterfall. Download PDF/CSV.
   Preview downloads regenerate current records without persisting a statement.
4. Upload a CSV/XLSX carrier invoice, review findings, export a CSV/PDF evidence
   packet, and explicitly log a support case. Repeating the case action reuses it.

OWNER, ADMIN and ACCOUNTANT can read financial information. Only the actual Owner
can authorize subscription changes. Dispatcher access stays blocked. Plan details
load independently of the statement configuration switch; statement controls still
require that switch. Existing financial confirmation and payment flows are retained.

## Carrier audit files

Use one worksheet, at most 1,000 rows / 5 MB, without formulas. Consolidate split
invoice lines by reference. Required columns, with net charges excluding VAT:

`upstream_shipment_id,currency,invoice_weight_kg,wholesale_cost,residential_fee`

Surcharge audits match confirmed bookings in the current tenant and currency.
Recorded weights, wholesale costs and verified commercial-address evidence determine
differences. A finding requests review; it does not establish liability or issue a
refund. Exports include saved evidence. Logging a support case does not send any
messages, submit to a carrier or change wallet balances.

## Competitor savings checks

Command savings mode also requires `easyinvio_shipment_id` per row: create a
comparable EasyInvio quote first, then include its shipment ID. A confirmed booking
or unexpired quote supplies the calibrated customer price. Currency and packed
weight must match. Confirm the same route, dimensions and service scope yourself:
the selected shipment ID is a comparison reference, not proof of identical terms.

Results show potential savings against that saved price, not a new live offer or a
guaranteed future rate. Missing/ambiguous evidence requires review. No aggregator,
PAF or LLM calls are made during this comparison. Savings do not create disputes.
Leave the optional shipment-ID column blank for ordinary surcharge audits.

## Accounting and release scope

MTD hero totals are posted wallet shipping movements in UTC and wallet currency.
External/card-funded and postpaid shipping appear separately in statements.
Unknown VAT remains unknown. Gross debits already include recorded VAT; the
waterfall never subtracts it twice. Stripe subscription payments/refunds do not
move the postage wallet. Top-ups are funding, not taxable revenue. Keep original
tax invoices; the account activity statement is not a replacement.

No new migration, private environment changes or deployment are required by this
update. Existing migrations through 058 are assumed applied. Stripe price setup
still follows `docs/pricing_release.md` before a paid checkout rollout.


## Wallet usability follow-up

- Verified CREDITED top-ups close the payment dialog and return to Wallet & Billing. A success URL cannot grant wallet funds.
- Complimentary describes billing, Command describes feature access. The published price is a reference price, not a charge. Unavailable plan selection/cancellation controls are hidden; contact support for an assigned-plan change. Paid agreements retain review and explicit confirmation.
- Wallet shipment links include Back to wallet transactions and Show all shipments. Reservation filters show temporary earmarks/releases without changing funds.
- From/To dates are inclusive UTC calendar dates in the UI. View selected dates creates a read-only activity view up to 366 days (today ends at the request time); its PDF and CSV retain those exact bounds. Save completed monthly statement retains an immutable snapshot up to 32 days. Both paths keep the 10,000-line bound. EI-prefixed references identify saved statements, not individual payments.
- Invoice checks accept the documented CSV/XLSX schema, not arbitrary invoice PDFs. Surcharge findings compare booked evidence; savings compare saved customer prices and require a comparable EasyInvio shipment ID. Neither operation obtains fresh quotes, proves carrier liability or issues refunds.
- Saved findings start as billing_disputes DRAFT. Log support dispute case explicitly creates a repeat-safe OPEN support ticket. Existing support intervention/resolve routes record review notes and move tickets through IN_REVIEW to CLOSED. Closing support does not synchronize billing_disputes status. There is no carrier submission or HubSpot support-ticket synchronization here; current HubSpot integration covers companies, contacts, deals and tenant metrics. Placement and CRM lifecycle changes are deferred for product review.
