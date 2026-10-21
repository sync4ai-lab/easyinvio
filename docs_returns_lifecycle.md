# Prepare a return without changing the original sale

This guide explains EasyInvio.com's supported reverse-shipment preparation and store return synchronization. It is for merchants, warehouse teams and administrators arranging a return through an enabled workflow.

## Current availability

Create return is available in Manifest & Labels after the original outbound shipment has recorded DELIVERED. A label, manifest or dispatch scan alone does not establish that the customer received the goods. The return keeps its original-shipment relationship and separate tracking identity.

Merchants can prepare returns themselves in the Create shipment workspace, under a RETURN SHIPMENT heading. A reverse quote is not a purchased label, merchandise refund or collection booking. Owners, administrators and dispatchers can prepare retailer-paid returns; only owners/administrators can create customer-paid checkout. No separate public return portal is required.

Grouped multi-piece return purchases are guarded. A multi-box original needs review rather than assuming all its boxes can be reversed through one existing return call.

## Prepare the reverse shipment

1. Locate the original delivered booking and select Create return.
2. Confirm merchant authorisation and identify exactly which goods are returning.
3. Check the original customer as return sender and your default RETURN address as destination. Change that warehouse in Settings before preparing a new return.
4. Check the actual return packaging and weight. Do not assume the customer kept the outbound box.
5. Review goods, customs details and the original invoice reference where required.
6. Compare current return services and their expiry; there is no mandatory maximum-price field. The original outbound price is not a return price.
7. Select a service and confirm retailer billing or create the customer card payment link. Customer payment must be verified before a return label is created or released.

The form restores saved packing and goods for review and editing, including measurements, weights, values, HS codes and customs registrations. Confirm a fresh signer and classification review where required. Original customer and versioned warehouse addresses remain protected. Do not edit booked snapshots or bypass an unresolved return with a new unrelated booking.

Optional customer email/WhatsApp instructions use original customer contacts and require configured channels and confirmed customer permission. Customer-paid notices contain a payment link first, then confirmed label instructions after payment. Disabled channels are shown as unavailable. READY means queued; ACCEPTED means provider acceptance, not proof of delivery. Failed or uncertain messages show their recorded state and must not be blindly resent. Existing results can be refreshed. Carrier paperless QR is offered only where an actual carrier code exists; otherwise print the carrier PDF. Shared document links expire after 24 hours and recheck payment and shipment state.

## Why the original shipment stays separate

The return has its own identity, lifecycle and tracking number. Its relationship to the original order is retained without inserting another forward shipment using the same storefront order identity.

Return tracking must not call normal forward fulfilment. It does not automatically reopen, complete, refund, restock or otherwise change the original sale's commercial state. Inspection and the merchant's refund decision remain separate.

## Shopify return tracking requirements

Shopify synchronization requires an existing approved reverse-fulfilment order associated with the original sale and an authorised connection with the necessary return permissions.

The native return reference must belong to that order. Packed quantities must match the approved case. Closed, partially dispatched or ambiguous allocations stay in review rather than becoming a whole-case dispatch.

The supported worker attaches tracking through Shopify's reverse-delivery operation. It does not use forward fulfilment and does not notify the customer through that mutation. See [Shopify's reverse-delivery documentation](https://shopify.dev/docs/api/admin-graphql/latest/mutations/reverseDeliveryCreateWithShipping).

The worker records that submission has started before the external change. Recovery checks native state rather than repeatedly creating reverse deliveries after an unclear response.

Physical scans can update local return progress to in transit or received. This does not mean Shopify has an identically named Return In Transit field or that every native status is updated automatically.

## Amazon and unsupported return connections

A generic Amazon return update is not implemented. Seller programs have different permissions and return capabilities. Unconfigured synchronization remains in review and must not use the forward fulfilment worker.

Do not close or fulfil the original order to make a held return disappear. Keep original and return references together and ask support to check the actual seller program.

## Customs for international returns

A cross-border return needs accurate declaration facts. EasyInvio can prepare a commercial declaration with a returned-goods reason and original transaction reference when the data is available and reviewed.

Check the actual description, quantity, manufacturing origin, value, weight and commodity classification. Never use a fabricated zero value, choose a gift reason for convenience, or assume all returns share a universal HS code.

Reversed sender and recipient roles can change whose registration details are relevant. A reviewed declaration is not a tax-relief determination. Great Britain, Northern Ireland and the receiving country can have different requirements.

For UK re-imports, Returned Goods Relief depends on the relevant conditions and evidence. EasyInvio does not automatically select customs procedure codes, submit relief claims or guarantee duty/VAT waivers. Consult the current [GOV.UK guidance on returning goods to the UK](https://www.gov.uk/guidance/returning-goods-to-the-uk) and the carrier or customs adviser.

## Commercial invoices and postal forms

A commercial-invoice PDF does not replace a required CN22 or CN23. The provider must supply the required postal document through the supported booking/document workflow.

EasyInvio does not automatically request CN22/CN23: select the required form in the reviewed return screen. The print bundle checks for carrier-issued forms rather than inventing them. If the selected service cannot provide required paperwork, choose a compatible service before dispatch; unresolved carrier limitations still need review.

## Receive, inspect and decide

Record tracking and compare received goods with the approved case. A delivered return scan does not approve a customer refund, restore stock or establish undamaged condition.

If quantities, condition or documents differ, retain evidence and follow the merchant's inspection process. Partial returns, exchanges and grouped cancellations need explicit handling outside unsupported automatic flows.

[Contact EasyInvio support](/help/contact), [read about tracking](/help/features/labels-and-tracking), or [return to the Help Centre](/help).
