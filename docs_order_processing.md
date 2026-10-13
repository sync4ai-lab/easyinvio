# Import and prepare store orders

This guide is for warehouse teams and workspace administrators using EasyInvio.com. It explains what arrives from a connected store, what still needs checking, and how to keep the original order reference intact.

## Current availability

EasyInvio supports authenticated Shopify order notifications, authorised Shopify order retrieval, and an Amazon notification queue that retrieves current order details. A store must be registered, connected and enabled first. Registering a store name alone does not start imports.

An imported order is a preparation record. It does not purchase a label, charge a wallet, book a collection or guarantee shipping without review. Timing depends on the storefront, permissions, network and processing queue; import is not guaranteed at the exact moment of sale.

## How orders reach your workspace

### Shopify notifications and retrieval

Shopify sends supported order-created or order-paid notifications to the configured public HTTPS receiver. EasyInvio checks the notification signature and registered store identity before reading the order details. The notification contains order information; this differs from polling Shopify for every sale.

You can also use Retrieve orders in Store Integrations or Sync Marketplace Orders in Marketplace Workspace. This retrieval path searches for eligible open, unfulfilled orders. Current import eligibility and data requirements still apply.

Notification intake and open-order retrieval are separate paths. A notification or a locally displayed UNFULFILLED preparation state does not guarantee that nobody has since fulfilled the sale elsewhere. Check the current storefront order before dispatching, especially when another fulfilment tool is in use.

### Amazon notifications and order lookup

Amazon intake requires an authorised seller connection and the configured AWS notification delivery arrangement. EasyInvio authenticates the incoming notification, records its order reference and queues a lookup of the latest authorised order data.

The current adapter accepts merchant-fulfilled, wholly unshipped orders. Amazon-fulfilled and partially allocated orders do not become ordinary ready-to-book warehouse rows through this path. Product weights must be available from the verified SKU weight mapping. Missing permissions or data can leave a notification in review.

There is no generic public Amazon webhook that gives every seller access to every order. Platform setup and appropriate seller authorisation are required.

### Public receiver setup

Platform administrators configure `POST /api/v1/integrations/ecommerce/orders-sync`, including its registered store reference and provider authentication. Localhost cannot receive internet notifications without a properly configured public HTTPS route.

Warehouse users should use the connection screens and support guidance rather than editing webhook URLs or sharing credentials. See [Connect Shopify and find your orders](/help/connect-shopify).

## What happens after import

1. Open Marketplace Workspace and select the connected store.
2. Find the order using its original store reference.
3. Review the recipient address and current shipping status in the store.
4. Measure the packed cargo and allocate goods to boxes for a multi-package order.
5. Review product values, manufacturing origins and HS codes when customs documents are required.
6. Request quotes and choose an eligible service.
7. Confirm payment and wait for confirmed label documents before dispatching.

New inbound records use a preparation state such as UNFULFILLED. Other import paths can show PENDING_IMPORT. Neither means that a carrier has collected the parcel.

## Resolve address and product validation problems

### Missing postcode or incomplete address

Confirm the recipient's correct address with the merchant or customer. Correct missing information in the source order where possible. Check the country and postcode together; never substitute a guessed postcode.

The workspace also needs a complete sender address. The current importer uses its saved billing address as the initial sender address. Confirm that this is a suitable dispatch address before quoting. Ask your administrator or support to correct an incomplete company address.

### City text that cannot be read

Check for accidental line breaks, copied markup, control characters or a field sent as an object instead of plain text. Normal accented place names are not automatically invalid in EasyInvio. Do not strip legitimate characters or rename a city to bypass an error. A carrier can apply its own restrictions after EasyInvio's initial validation.

### Missing weight, value or goods detail

Check that a SKU has a verified unit weight and that quantity is correct. A product's net weight excludes its box and packing material. Enter the measured packed weight during preparation, and ensure total goods weight does not exceed it.

Each goods line in a multi-box order needs a box assignment. Do not duplicate the total order weight or all goods onto every box. Read the [package-weight guide](/help/package-weight) for size-based charging.

## Preserve references when retrying

EasyInvio checks store and order identity to avoid another row for the same unchanged order. A repeated valid import can return the existing record.

If an imported order arrives with different shipping data, the system requests reconciliation rather than silently overwriting it. Keep the same store and order reference and ask support to review the change. Changing an order ID to force import risks duplicate fulfilment.

A Shopify payload rejected before import may have no local shipment row; its reference remains in the store's order and delivery records. Amazon notifications have a separate received/imported/ignored/review trail. Correct or retry the appropriate source rather than assuming every rejected payload was saved as a shipment.

## Defaults that reduce repeated work

Administrators can configure a connector's supported cargo classification and verified SKU unit weights. Company sender information must also be complete. These defaults help prepare an order; they do not prove that its final packaging is suitable.

Packaging sizes offers examples that users can select and check. It is not a universal package-size lock for every incoming order. Carrier availability depends on the route, cargo, account, weight and dimensions.

The current product has no complete hands-free policy for choosing packaging, guessing missing weights, selecting a fallback carrier and buying every incoming order. Review and explicit booking remain part of the supported workflow.

## Get help without exposing customer data

Include the store name, original order reference, time of the failed attempt and short error message. Do not email credentials, full customer addresses or unredacted order exports.

[Contact EasyInvio support](/help/contact), [learn about booking payments](/help/booking-payments), or [return to the Help Centre](/help).
