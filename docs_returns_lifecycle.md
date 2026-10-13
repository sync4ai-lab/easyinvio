# Prepare a return without changing the original sale

This guide explains EasyInvio.com's supported reverse-shipment preparation and store return synchronization. It is for merchants, warehouse teams and administrators arranging a return through an enabled workflow.

## Current availability

The backend can prepare a return quote from an eligible, confirmed outbound shipment. It links the new return to the original shipment, reverses operational addresses and supplies provider-specific return information where supported.

There is no general customer-facing self-service return portal in the current dashboard. Ask support to use the authorised workflow if it is not exposed to your role. A reverse-address quote is not an approved return label, store refund or collection booking.

Grouped multi-piece return purchases are guarded. A multi-box original needs review rather than assuming all its boxes can be reversed through one existing return call.

## Prepare the reverse shipment

1. Locate the original confirmed booking and tracking reference.
2. Confirm merchant authorisation and identify exactly which goods are returning.
3. Check the return sender and receiving warehouse. The backend starts by swapping the original recipient and sender; old details may need review.
4. Check the actual return packaging and weight. Do not assume the customer kept the outbound box.
5. Review goods, customs details and the original invoice reference where required.
6. Request an eligible return quote through support or the authorised integration.
7. Review its price and explicitly confirm the separate booking before sending the label to the returning customer.

The original-shipment preparation path copies the outbound snapshot. It is not a complete editor for arbitrary partial returns, changed addresses or repacked goods. Those differences need an accurately supported preparation or manual review. Never edit a booked snapshot or force an incompatible copied return through checkout.

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

Original-shipment return preparation does not automatically request CN22/CN23. The print bundle checks for required carrier-issued forms rather than inventing them. Ask support to confirm availability before dispatching a postal return needing such a form.

## Receive, inspect and decide

Record tracking and compare received goods with the approved case. A delivered return scan does not approve a customer refund, restore stock or establish undamaged condition.

If quantities, condition or documents differ, retain evidence and follow the merchant's inspection process. Partial returns, exchanges and grouped cancellations need explicit handling outside unsupported automatic flows.

[Contact EasyInvio support](/help/contact), [read about tracking](/help/features/labels-and-tracking), or [return to the Help Centre](/help).
