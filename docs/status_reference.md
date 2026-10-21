# Understand statuses and resolve unexpected results

Use this guide when an order, quote, payment, return, tracking update or claim
shows a status you do not expect. It explains the recorded state and the safe
next step. It does not inspect your account or change a carrier, payment or claim.

## Start here: identify the screen

### Which Pending, Failed or Received do you mean?

Pending, Failed, Received, Submitted and Completed have different meanings in
different workflows. Check the screen: shipment booking, wallet payment, return,
claim, store sync or message delivery. Tell support the screen name, exact status,
reference and time. A message delivered is not a parcel delivered. A return
received is not a merchandise refund. If the screen is unclear, ask which process
the status belongs to before retrying anything.

### Unexpected status: a safe recovery checklist

Refresh the same workspace and check the shipment details, payment activity and
latest carrier scan. Compare scan time with update-received time. Keep the
reference, exact message and screenshot. If money is reserved or a carrier
purchase is uncertain, do not pay or book again to clear the status. Use
[Contact support](/help/contact) for reconciliation. Never send passwords, OTPs,
card numbers, API credentials or a private customer tracking-link token to support.

## Orders, preparation and quote expiry

### Orders — Imported needs preparation / PENDING_IMPORT

Order data was imported into EasyInvio from a store or file; this does not mean
customs import clearance. Addresses, packing or customs goods may need review
before pricing. Choose Prepare & compare rates, verify the actual measurements
and goods, and complete any outstanding customs review. Not priced yet is normal
until a usable quote exists. Uploading an order does not buy a label.

### Orders — Imported not shipped / UNFULFILLED

The store order has not been fulfilled. Review the correct store/order reference,
addresses, measured packing and goods in Marketplace Workspace, then compare
rates. A saved store order or chosen shipping preference is not a carrier booking.
If the store has already fulfilled it elsewhere, contact support before booking
again so duplicate fulfillment can be checked.

### Quotes — Not priced yet / Unquoted / DRAFT

Shipment details exist without a current usable carrier offer. Not priced yet
describes price availability; Draft describes preparation. Complete the addresses,
measured packages and required goods, then request rates. If none are available,
check the reported route/packing issue or ask support to check connected services.
Do not understate measurements or invent customs data to obtain a quote.

### Quotes — Quoted not booked / QUOTED

A saved price exists but no label has been bought. Check its expiry and service,
then use Review & book to open checkout. Add to batch only selects an order;
use Review & book selected orders to proceed with the batch. Confirm the final
price and payment. Closing review or selecting a checkbox does not purchase
postage. If the quote expires first, use Requote.

### Quotes — Quote expired / QUOTE_EXPIRED

The saved price can no longer be booked. EasyInvio uses a five-minute quote
validity window by default; the displayed expiry is authoritative for that offer.
Choose Requote to restore saved addresses, goods and all boxes in Create a
shipment. Review them and compare fresh carrier services. Prices and availability
may change. A previous customs approval or selected price is not automatically
reused. Never pay against an expired offer.

### Quotes — Fresh quote required / QUOTE_UNAVAILABLE

An older record has no verifiable usable expiry or offer. Request fresh rates
using Requote where offered; fill any missing legacy details. If restoration is
blocked because a previous purchase is unresolved, contact support with the
reference instead of creating a duplicate. A historical displayed amount is the
last quoted price, not proof of a captured payment.

## Booking, labels and carrier handover

### Booking — In progress / BOOKING / EXECUTING

The selected operation is being processed. A carrier purchase may already have
been submitted. Wait for the existing result and refresh the same order. Do not
create another booking or payment to make it progress. If it remains unresolved,
give support the booking reference and payment time. An executing assistant
workflow is not itself carrier confirmation.

### Booking — Carrier confirmation pending / SYNC_PENDING

The carrier outcome or asynchronous label is not final. Keep the existing order
and check it again; support can reconcile the existing transaction. Do not buy a
second label or assume reserved wallet funds were captured. A pending label
cannot be printed for real dispatch. There is no guaranteed completion time;
provider responses and availability determine the next result.

### Booking — Failed / FAILED

Preparation or label purchase failed; the parcel has not thereby been dispatched.
Read the reported reason, verify addresses, goods and packing, and check wallet
activity. A definite rejection releases an unused booking hold; an uncertain
outcome requires support review. Use Requote only when offered. If funds remain
reserved, do not repeatedly pay or book the same shipment.

### Booking — Label created / LABEL_CREATED / BOOKED

The carrier label or booking is confirmed. Download the carrier-supplied label,
check the tracking number and service, and prepare the parcel for handover.
Label created does not mean collected, in transit or insured. Use a paperless QR
only when that specific carrier/service supplied one. If a document is missing,
refresh and ask support to retrieve the confirmed label; do not purchase again.

### Handover — MANIFESTED / DISPATCHED

MANIFESTED means the shipment belongs to a prepared end-of-day manifest.
DISPATCHED means dispatch was recorded. Neither alone proves a carrier collection
scan. Follow the existing collection arrangement and check subsequent tracking.
A manifest can block ordinary cancellation: ask support to reconcile close-out
before attempting to cancel. Do not treat an internal handover sheet as a
confirmed carrier pickup appointment.

### Booking — Cancelled / CANCELLED

The shipment was cancelled. Do not send it using the old label. Check the
cancellation/refund record separately: cancellation does not establish a refund
to your bank or the buyer. If you still need to send the goods, request a fresh
quote after confirming the previous cancellation and financial outcome.

### Documents — PDF label, drop-off QR, POD and commercial invoice

Use the actual carrier PDF at the intended print size. A carrier-issued QR is
available only for supported paperless drop-off services and eligible locations;
an ordinary tracking QR is not postage. POD requires delivered status and a real
carrier proof asset. Commercial invoice and receipt downloads require the
appropriate confirmed booking/payment data and role. Missing controls often
mean the document is not ready, not that a label should be bought again.

## Tracking, scans and delivery evidence

### Tracking — IN_TRANSIT / OUT_FOR_DELIVERY

IN_TRANSIT means the carrier reported movement through its network.
OUT_FOR_DELIVERY means the carrier reported the final delivery route. Open the
timeline and use the latest scan time and actual carrier estimate, if supplied.
Do not promise a guaranteed delivery time from either label. For an overdue
shipment, check for exceptions and contact support with the tracking reference.

### Tracking — AVAILABLE_FOR_PICKUP / DELIVERY_ATTEMPTED

AVAILABLE_FOR_PICKUP means the carrier reported a collection point; check the
carrier's location, opening hours, identification requirements and deadline.
DELIVERY_ATTEMPTED means an attempt was reported, not successful delivery. Follow
the carrier's actual redelivery/collection instructions. If those instructions
are missing, ask support; do not send the buyer to an assumed post office.

### Tracking — CUSTOMS_PROCESSING / EXCEPTION

CUSTOMS_PROCESSING is a reported customs milestone. EXCEPTION means a carrier
issue, such as an address, customs or delivery problem, needs attention. Read the
actual scan/exception and provide requested accurate documents or contact facts.
Do not change declared values or HS codes just to bypass a block. If the required
action is unclear, contact support. Neither status proves loss or insurance cover.

### Tracking — RETURNED_TO_SENDER

The carrier reported the parcel being returned to its sender. Check the reason,
latest scan and sender address; contact support to establish the next handover or
receipt. This does not automatically create a separate customer return booking,
prove warehouse receipt, or refund the buyer's purchase.

### Tracking — DELIVERED and missing proof

The carrier reported delivery. View delivery proof only when the carrier supplied
a signature/photo/proof URL. Delivered does not guarantee that a POD image exists.
If the buyer disputes delivery, retain the reference and contact support to check
the carrier evidence. Do not change the carrier scan manually or file a duplicate
claim simply because the POD button is absent.

### Tracking — AWAITING_CARRIER_UPDATE / AWAITING_TRACKING

No usable scan or package tracking record has arrived yet. A confirmed label is
not a collection scan; unbooked orders should not have tracking evidence. Check
booking confirmation and actual handover. For multiple boxes, inspect each box's
tracking number. If a handed-over parcel remains without scans, ask support to
check the carrier feed rather than purchasing another label.

### Tracking — RECORDED / STALE / UNKNOWN

RECORDED means tracking facts are available. STALE means the last update exceeds
the workspace's review threshold; it is not proof of a delivery delay. UNKNOWN
means the carrier supplied a fact that cannot safely be mapped to a known
milestone. Review the latest scan/time and ask support if necessary. Older scans
are retained without moving a delivered parcel backwards. No new date is invented.

### Tracking — Partial delivery / multiple boxes

Each box has its own tracking outcome. One box delivered does not mean every box
was delivered. Check the package list and identify the missing box/reference when
contacting support. The whole shipment reaches delivered only when the required
box delivery evidence is complete. Do not start a duplicate whole-order booking
or assume a merchandise refund from a partial carrier update.

## Wallet, card payment and booking funds

### Wallet — RESERVED / Credit reserved

Money is held for a booking and reduces available wallet credit; it is not yet a
completed label charge. Check the existing booking. If the outcome is pending,
allow reconciliation or contact support; do not top up or pay again merely to
clear the hold. Only add genuine extra funds if you separately need more credit.

### Wallet — SUBMITTED / CAPTURED / RELEASED

SUBMITTED means a carrier purchase has crossed the submission boundary and must
be reconciled before retrying. CAPTURED means the confirmed label cost was charged.
RELEASED means an unused reservation was removed; it is not a new bank refund.
Compare the booking and wallet activity. If they disagree, give support the
reference, amount and currency; do not manually repeat the purchase.

### Wallet top-up — PENDING / SUCCESS / FAILED

PENDING means payment confirmation is outstanding. SUCCESS means a verified
top-up result; check the actual wallet credit. FAILED means the payment was not
successfully applied. A browser redirect or closed Stripe window alone does not
prove payment. If Stripe shows success but the wallet has not updated, check
activity and contact support before paying again. Never send full card details.

### Card checkout — CREATING / AWAITING_PAYMENT / BOOKING

CREATING prepares a secure checkout session. AWAITING_PAYMENT waits for verified
payment; closing the window does not confirm it. BOOKING processes the selected
labels after verified funding. Open the existing checkout/order and check its
outcome. If payment succeeded, do not pay a second time to restart a stalled
booking; ask support to reconcile the existing basket.

### Card checkout — COMPLETED / REVIEW_REQUIRED

COMPLETED means the checkout processing finished; inspect each order's booking
result and confirmed labels. REVIEW_REQUIRED means an outcome needs attention,
possibly after a payment succeeded. Check each order and wallet activity. Verified
funds from a rejected label can remain in the wallet; a failed label does not
automatically refund a successful card payment to the bank. Contact support before retrying.

### Billing — ACTIVE / restricted billing or insufficient funds

ACTIVE is a workspace/billing access state, not a paid shipment. An insufficient
funds error means available credit does not meet the required amount/currency.
Check reservations, billing plan and currency with the owner/accountant. Only a
permitted financial user should add needed funds. If access is restricted or
invoiced credit needs review, contact the administrator; do not create a second account.

## Cancellation, label refunds and merchandise refunds

### Label cancellation — PENDING

The carrier cancellation/refund request is not fully confirmed. Do not use the
label or assume a credit has been applied. Check the existing cancellation record
and ask support if it remains unresolved. A carrier acknowledging a request is
not the same as confirming its cancellation/refund. Multi-box cancellation can
require separate reconciliation; do not cancel only one box and assume all are refunded.

### Label refund — CREDITED / SHIPMENT_REFUND

The confirmed label reversal has been credited through the applicable workspace
billing/ledger path. Check its amount and currency against the original booking.
This is a shipping-label reversal, not necessarily a bank-card refund and not a
refund of goods bought from a retailer. If the credit is missing, ask the owner
or support to check the recorded reversal; do not submit another cancellation.

### Merchandise refund — UNAVAILABLE / NOT_CONNECTED

EasyInvio has no verified buyer-purchase refund feed for this view. It cannot
confirm refund pending, processing, paid or failed from a parcel/return scan.
Ask the retailer or marketplace/payment provider for the purchase refund reference
and status. Return received, wallet credit and insurer settlement are separate
facts. Do not promise the buyer a refund or a bank arrival date from this screen.

### Refund question — pending, processing, completed or failed elsewhere

First identify the money: unused wallet hold, cancelled shipping label, original
card top-up, retailer merchandise purchase or insurer compensation. A status in
one system does not prove a refund in another. Use the relevant payment/provider
reference and contact the responsible retailer, accountant or support team.
These everyday terms are not new EasyInvio merchandise-refund states.

## Returns and warehouse receipt

Create return becomes available after the original outbound shipment has recorded
DELIVERED. A created label, handover manifest or in-transit scan does not establish
that the customer has received the goods. Refresh tracking if a delivery scan is
missing; do not manually change a status merely to unlock a return.

The return opens in the Create shipment workspace with a RETURN SHIPMENT heading.
Review saved packing and contents, the customer collection address and the default
RETURN address from Settings. Packing, goods and customs inputs can be reviewed
and edited without a support request. The original price is not a return quote:
compare fresh services, select a price, then confirm payment. There is no mandatory
maximum-price field. A grouped multi-parcel original still requires separately
measured returns; the application does not silently combine parcels into one label.

### Return preparation — PREPARING / QUOTED

PREPARING means the saved return details are being rated; no label is purchased.
QUOTED means current return service choices are available until the displayed
expiry. Choose a service to pay from workspace billing or create a customer card
payment link. Compare fresh rates when expired. An interrupted preparation is not
an instruction to repeat a purchase; refresh its existing result first.

### Customer return instructions — READY / SENDING / ACCEPTED / FAILED / REVIEW_REQUIRED

Customer email and WhatsApp instructions are optional and require channel setup
and confirmed customer permission. Disabled channels are shown as unavailable.
READY means queued, SENDING means an outbound attempt has started, and ACCEPTED
means the provider accepted the request, not that the customer read or received it.
FAILED means a rejected or disabled channel; use the recorded reason. An uncertain
send becomes REVIEW_REQUIRED and is not blindly resent. Share the existing result
manually if needed, and ask an administrator to reconcile an ambiguous send.

For customer-paid returns, the first notice contains only a Stripe payment link.
The label notice is staged only after verified payment and carrier confirmation.
Retailer-paid returns send confirmed label instructions directly. Customer document
links expire after 24 hours and are checked again at download; an unpaid or cancelled
return cannot expose a label through them. QR is offered only when the selected
carrier supplies a real paperless asset. Otherwise print the carrier PDF label.

### Return request — PROCESSING / PAYMENT_REQUIRED

PROCESSING means the existing reverse-logistics request is being prepared.
PAYMENT_REQUIRED means the customer-paid return still needs verified checkout
payment. Follow the existing secure payment link when offered; no return label
is confirmed solely by submitting the request. Do not send a second return
command to bypass a pending payment or uncertain carrier outcome.

### Return request — BOOKED / REVIEW_REQUIRED

BOOKED means the return label is confirmed; use its supplied PDF or eligible
carrier QR. REVIEW_REQUIRED means the original shipment, return warehouse,
packing, payment or carrier outcome needs attention. Read the reason and contact
the retailer/support as appropriate. Returns must keep their original-shipment
and verified-return-address relationship; do not create an unrelated forward label to bypass review.

### Store return — NONE / REQUESTED / APPROVED

NONE means no return state was recorded. REQUESTED records a return request.
APPROVED records the supported return approval/preparation state; it does not
prove that a carrier label exists. Check the separate return booking, payment and
documents before handing over goods. Store approval alone does not refund the
purchase or confirm warehouse inspection.

### Store return — IN_TRANSIT / RECEIVED

IN_TRANSIT means the return parcel is moving back through the carrier network.
RECEIVED means the recorded return delivery/receipt condition was met. Check the
return tracking separately from the original outbound shipment. Carrier delivery
does not establish warehouse inspection, restocking, exchange or a merchandise
refund. Ask the retailer for those decisions and their actual recorded evidence.

### Store return — REVIEW_REQUIRED / RESOLVED

REVIEW_REQUIRED means the return/store mapping or outcome needs attention.
RESOLVED means that return workflow's review was resolved; it is not proof of a
payment refund. Check the return reference and contact the retailer/support with
the original and return shipment references. Do not change a return reference
just to force an update to an unrelated store order.

## Shipment protection and insurance

### Protection — unavailable / not added / QUOTE_PENDING / QUOTED

Unavailable or not added means no protection was purchased. QUOTE_PENDING requests
terms; QUOTED offers terms but is not confirmed cover. Review the available policy
eligibility, exclusions and price before agreeing. A proposed premium, checkbox
or shipping label is not proof of insurance. If protection is unavailable, do not
tell a buyer the goods are insured; ask support about eligible arrangements.

### Protection — PENDING / RESERVED / POLICY_SUBMITTED

Protection is not yet confirmed: funds/processing may be reserved or a policy
request submitted. Check the existing purchase and ask support to reconcile if
it remains pending. Do not purchase protection a second time or represent the
shipment as insured until confirmed policy evidence is present.

### Protection — INSURED / CONFIRMED

The recorded policy purchase is confirmed. Check the actual policy reference,
coverage, limits and exclusions for this shipment. It does not guarantee payment
of a future claim. Retain the shipping and goods evidence and follow the claim
requirements if loss/damage occurs.

### Protection — FAILED / CANCELLED / RECONCILIATION_REQUIRED

FAILED means protection was not successfully added. CANCELLED indicates a recorded
policy cancellation. RECONCILIATION_REQUIRED means the outcome is uncertain, not
confirmed cover or a confirmed refund. Check the policy and charge records with
support; do not assume replacement cover or automatically buy a duplicate policy.

## Claims, evidence and compensation

### Claims — CLAIM_INGESTED

A loss/damage support intake exists; the insurer has not thereby accepted a formal
claim. Open the secure claims panel, verify the shipment and policy, and supply
the requested incident details, photographs and goods evidence. Reuse the same
case reference rather than opening duplicate cases.

### Claims — SUBMISSION_PENDING / SUBMISSION_SUBMITTED

The existing case is waiting for submission or has crossed the submission boundary.
Do not resubmit it as a new claim. Check the same panel for the result and ask
support to reconcile an unresolved submission. Uploading photographs alone does
not establish insurer receipt or claim acceptance.

### Claims — INSURER_SUBMITTED / UNDER_INSURER_REVIEW

An insurer submission is recorded or the insurer is reviewing it. Follow the
existing claim reference and any insurer requests. Keep evidence available and
avoid duplicate filings. These states are not approval, compensation paid or a
guaranteed decision date; contact support if a required next step is unclear.

### Claims — ACTION_REQUIRED

The claim needs further information or action. Read the actual request in the
claim panel, provide the requested accurate documents/photos and retain the case
reference. Do not invent evidence or submit a second claim to bypass the request.
If the request is missing or unclear, contact support for that existing case.

### Claims — DECLINED / CLOSED

DECLINED means the insurer reported a declined/withdrawn outcome; CLOSED means the
case was closed. Neither proves money was paid. Read the recorded reason and
contact support about the available review route and required evidence. Do not
assume a right to appeal or promise a payment without actual insurer terms.

### Claims — INSURER_PAYMENT_REPORTED

The insurer reported a payment-related outcome. This alone does not prove that
funds reached EasyInvio or your wallet. Support/accounting must verify receipt,
amount, currency and claim linkage before any authorized compensation credit.
Do not issue a manual duplicate refund based only on this status.

### Claims — REFUND_APPROVED_AND_CREDITED

The supported compensation workflow recorded an approved, verified workspace
credit. Check the amount/currency and claim reference in wallet/billing activity.
This is insurance compensation, not automatically a retailer merchandise refund
or a bank-card refund. Ask support/accounting to reconcile any mismatch before
requesting or applying another credit.

### Claims — RECONCILIATION_REQUIRED; evidence PENDING / SUBMITTED / CONFIRMED

RECONCILIATION_REQUIRED means an insurer or settlement outcome needs verification;
do not resubmit or credit money to clear it. Evidence PENDING awaits upload,
SUBMITTED records an upload attempt, and CONFIRMED records provider confirmation
of that file. File confirmation is not claim approval. Contact support with the
existing case reference if an upload/submission remains unresolved.

## Support cases and internal operational review

### Support — OPEN / IN_REVIEW / RESOLVED / CLOSED

OPEN is an active internal support case. IN_REVIEW means a reviewer is working on
it. RESOLVED records internal resolution; CLOSED records closure/archive. These
states do not change carrier scans, approve an insurer claim or refund money.
Read the latest note and provide requested facts. If the real problem remains,
contact support using the existing case reference and explain the discrepancy.

### Tracking review — ACKNOWLEDGED / IN_REVIEW / ESCALATED / RESOLVED

These are internal operations review states, separate from parcel movement.
ACKNOWLEDGED records receipt; IN_REVIEW records investigation; ESCALATED records
escalation; RESOLVED records review resolution. Check the recorded note and carrier
timeline independently. If the note and real delivery problem disagree, ask
support to review the case rather than manually changing a carrier status.

### Customer help — OPEN / ACKNOWLEDGED

OPEN means a customer tracking-page help request was logged. ACKNOWLEDGED means
the operational review acknowledged it. This does not prove a message was sent
to the carrier or that the delivery issue is resolved. Keep the request/shipment
reference and contact the retailer/support if further information is needed.

### Invoice dispute — DRAFT / SUBMITTED / RESOLVED

DRAFT is a proposed surcharge/invoice review, not a sent carrier complaint.
SUBMITTED records the supported submission state; RESOLVED records review
resolution. Verify the original invoice, measurements and amounts with your
accountant. Neither a draft nor a resolved review automatically credits money or
establishes a carrier's acceptance of a complaint.

## Store, carrier connection and synchronization

### Store intake — RECEIVED / IMPORTED / IGNORED / REVIEW_REQUIRED

RECEIVED records incoming store data; IMPORTED records a saved order; IGNORED means
that event was not imported; REVIEW_REQUIRED means validation or order identity
needs attention. Check the store reference, unfulfilled state, address and verified
SKU weights. Fix accurate source data or follow the review message. Do not assume
every ignored webhook is a failed purchase or create duplicate manual orders blindly.

### Store tracking sync — PENDING / DELIVERED / SIMULATED_DELIVERED / RECONCILIATION_REQUIRED

In the store-sync workflow, PENDING awaits an outbound tracking update. DELIVERED
means that update reached the connected store, not that the parcel reached its
buyer. SIMULATED_DELIVERED is test/simulation evidence only. Check the separate
carrier timeline for physical delivery. If the store is not updated, give support
the store/order and shipment references; do not buy another label.
RECONCILIATION_REQUIRED needs verification of the existing store update or mapping;
do not force a return update into an unrelated forward fulfillment.

### Native partner sync — PENDING / SENDING / SYNCED / FAILED / SUPERSEDED

These describe transferring an order to a connected provider, not physical
delivery. PENDING awaits work; SENDING is in progress; SYNCED records the transfer;
FAILED needs review; SUPERSEDED means an older preparation was replaced. Separate
fulfillment PENDING/CONFIRMED/FAILED describes that follow-up step. For unresolved
or RECONCILIATION_REQUIRED work, ask support to inspect the existing transaction
instead of re-uploading or repurchasing the order.

### Connection — Enabled, disabled, TEST / LIVE, quote-only

Enabled means the configured integration may participate; it is not proof every
service or contract is ready. Disabled stops eligible new work. TEST is practice;
LIVE is the configured production environment. Quote-only services cannot issue
labels through that connection. Ask the platform administrator/support to check
the enabled account, entitlement and environment. Never use a TEST label for real dispatch.

## Registration, invitations and conversational assistance

### Registration — PENDING_PERSONA / PENDING_COMPANY / PENDING_PROFILE / PENDING_EMAIL

Registration is collecting the requested identity/profile information. Choose
Business or Individual and answer only the current prompt. Individual signup
skips company metadata. Use the intended email and phone. Do not enter an OTP
into a company-name field or repeatedly restart registration to bypass a warning;
contact support if the saved registration cannot be resumed.

### Registration — SENDING_EMAIL / PENDING_OTP / PROVISIONING / VERIFIED

SENDING_EMAIL attempts delivery; acceptance is not proof the inbox received it.
PENDING_OTP waits for the current email code and separate WhatsApp code in the
format the chat requests. PROVISIONING creates/binds the verified workspace;
VERIFIED records completion. Follow the current codes, not an old email link.
Use the password-setup flow for desktop access; do not send codes to support.

### Registration — EXPIRED / LOCKED / CANCELLED / RECONCILIATION_REQUIRED

EXPIRED means the session/challenge expired; LOCKED means its attempt limit was
reached; CANCELLED ends that attempt. Follow the current restart/resend instruction
or ask support when blocked. RECONCILIATION_REQUIRED means activation needs
verification: do not create duplicate workspaces or ask to bypass identity checks.
An unverified registration is not proof of legal company ownership.

### Team invitations — SENDING / PENDING / ACCEPTED / FAILED / CANCELLED

SENDING attempts the invitation email; PENDING awaits acceptance; ACCEPTED records
the invitation being used; FAILED requires administrator review; CANCELLED cannot
be used. Ask the owner/admin to resend an eligible invitation or verify membership.
An expired invitation needs a fresh valid link. Do not share another colleague's
account or assume an accepted invitation overrides a disabled membership.

### Chat agent — RECEIVED / VALIDATING / NEEDS_INPUT / READY / EXECUTING / COMPLETED

These describe an assistance workflow. RECEIVED/VALIDATING check the request;
NEEDS_INPUT asks for missing facts; READY means required preparation exists;
EXECUTING performs the allowed operation; COMPLETED means that operation finished.
Read action_taken and the actual booking/payment/claim result: completed help is
not a completed shipment. REVIEW_REQUIRED needs attention; do not repeat an
uncertain money-moving action to make a chat receipt look complete.

## Advanced status codes support may mention

### Manifest document — DRAFT / SUBMITTED / FAILED / COMPLETED

These describe an end-of-day document, not individual parcel delivery. DRAFT is
being prepared; SUBMITTED crossed the provider boundary; FAILED needs review;
COMPLETED has a prepared document. It may be a carrier manifest or an explicitly
internal handover sheet. If submission is uncertain, support must retrieve or
reconcile it rather than create a duplicate carrier close-out.

### Tracking refresh job — DUE / RUNNING / COMPLETE / DEAD / UNSUPPORTED

These are tracking-refresh work states, not parcel statuses. DUE waits for its
allowed slot; RUNNING is a read in progress; COMPLETE ends that job; DEAD exhausted
its allowed attempts; UNSUPPORTED means no supported polling path for that job.
Webhooks can still supply tracking. Ask support to inspect readiness and rate
limits before an explicit retry; repeated customer refreshes cannot enable a
carrier contract or prove delivery.

### Messaging — QUEUED / STAGED / PROCESSING / READY / SENDING / ACCEPTED

QUEUED/STAGED and the other states describe queued chat/support-message handling. ACCEPTED means the messaging
provider accepted a send, not that the recipient read it. If a request is in
PROCESSING or SENDING with an uncertain outcome, support must reconcile it before
replaying an action. Do not infer payment, label or delivery success from the
message queue. FAILED or REVIEW_REQUIRED needs inspection, not automatic resend.

### Messaging — SENT / DELIVERED / READ / FAILED / CANCELLED / rejected / undelivered

SENT, DELIVERED and READ are provider messaging receipts; they do not describe the
parcel. FAILED, rejected or undelivered means the message was not successfully
delivered; CANCELLED means the notification was stopped. Ask support to check
verified recipients, opt-in, provider delivery and applicable messaging rules.
A missing message does not authorize replay of a booking or payment.

## Related guides and getting help

For a specific task, read [Create a label](/help/first-shipment),
[Booking payments](/help/booking-payments), [Wallet top-ups](/help/wallet-top-ups),
[Returns](/help/features/returns) or [Tracking](/help/features/labels-and-tracking).
For an unexpected result that remains unresolved, use [Contact support](/help/contact)
and include the screen, exact status, reference, time and amount/currency if relevant.
General assistant guidance cannot verify your live shipment, refund or claim;
an authenticated tracking lookup or the relevant native workspace record is needed.
