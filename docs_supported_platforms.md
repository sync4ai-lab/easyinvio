# Supported sales platforms and connection methods

## What the directory promises

All 24 codes share normalized order intake, the ordinary preparation/quote/booking pipeline and an optional explicitly authorized hosted returns portal. A directory entry does not mean native OAuth, native webhook authentication, automatic installation or successful API scope verification. Every store needs active merchant authorization, applicable subscription entitlements and configured carriers. Imports do not purchase labels.

Native REST adapters use merchant-authorized credentials entered in encrypted Connection settings. Retrieval is explicit and bounded; it is not a scheduled historical backfill. Tokens that expire must be renewed through the platform's authorized mechanism. Composite products, split locations/partial fulfillment, unknown SKU weights or incomplete addresses require review. Access tokens alone are not proof of successful imports/write-back.

## Native and custom website capabilities

| Platform | Order intake | Tracking write-back | Setup |
|---|---|---|---|
| Shopify | Native signed orders/create or orders/paid; GraphQL retrieval | Native whole-order GraphQL fulfillment; explicit toggle | Token or authorized own-organization app credentials; external OAuth/webhook setup |
| WooCommerce | Native signed order.created/order.updated; REST retrieval | REST completion, EasyInvio tracking metadata and internal order note | HTTPS origin; consumer key/secret for REST; signing secret for webhooks |
| Amazon | AWS notification plus authorized seller order fetch | Not implemented | Seller credentials plus external SQS/EventBridge setup; worker required |
| Custom Website / REST API | Store-signed normalized order API | Signed callback to retailer origin | Generated key ID/secret; optional callback |
| eBay | Fulfillment REST retrieval; normalized signed bridge notifications | Native shipping fulfillment | Authorized seller bearer token; weights per SKU |
| BigCommerce | Orders v2 REST retrieval; signed normalized bridge | Native order shipment creation | Store hash and API token; single shipping address |
| Wix | eCommerce Orders REST query; signed normalized bridge | Native order fulfillment | Site ID and authorized token; store notification settings may send email |
| Magento / Adobe Commerce | Orders REST retrieval; signed normalized bridge | Native shipment with tracking | Store HTTPS origin and authorized REST token; simple physical products only |

Checkout rates use EasyInvio's signed API for each registered store; there is no claim of native storefront checkout-widget installation. Hosted returns are EasyInvio's public page under each store's configured policy, not marketplace-program return authorization. Native Amazon tracking/returns are not implied. Shopify return tracking still requires an approved reverse-fulfillment reference and appropriate permissions.

## Bridge platforms

Etsy, TikTok Shop, Squarespace, PrestaShop, Shopware, Ecwid, Square, Weebly, OpenCart, OnBuy, ManoMano, Mirakl, Kaufland, Linnworks and ChannelEngine use **API_BRIDGE** mode. They have no implemented native OAuth/order importer in this release. A retailer's developer or trusted middleware reads their platform and submits the documented normalized order object through EasyInvio's signed API; that same bridge receives signed tracking callbacks and updates the platform. They can use signed checkout rates and an enabled EasyInvio hosted returns portal.

CSV / SFTP Batch is the 24th directory code. Existing CSV preparation/upload is available. An SFTP daemon, automated file fetch and scheduled file ingestion are not implemented; use an external bridge or manual CSV upload. It must not be marketed as an active SFTP connection.

For a bespoke store or ERP, read [Connect your custom website](/help/connect-custom-website). Do not send API passwords or signing secrets by email. Use Test connection for the supported native read check and inspect the order inbox/tracking sync activity; a saved name is only registration.
