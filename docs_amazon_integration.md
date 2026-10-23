# Connect Amazon Marketplace and import orders

EasyInvio supports an authorised Amazon seller connection, AWS ORDER_CHANGE notifications and queued retrieval through Orders API v2026-01-01. This is a configured integration, not a one-click Seller Central login. Workspace owners or admins save the connection; an Amazon/AWS administrator completes the external setup. Dispatchers can prepare imported orders but cannot edit seller credentials.

## Setup steps with a UK example

1. Sign in as a workspace owner or admin. Open **Store Integrations**, choose **Amazon**, select **Connect store**, and register a name such as **My UK Amazon Store**. Registration alone does not import orders.
2. Open that store's **Connection settings**. Choose **Europe / UK** for the SP-API region. Enter your **Seller ID** and the marketplace IDs authorised for that seller. The UK marketplace ID is **A1F83G8C2ARO7P**; confirm that your seller actually operates there.
3. Have your Amazon developer administrator authorise the correct SP-API application for the seller. Obtain its **App Client ID**, **App Client secret** and **Seller refresh token** through Amazon's approved authorisation process. The app needs access to the required order, recipient/address, fulfilment and proceeds data. A private app can be self-authorised for its organisation; a public app needs seller authorisation. EasyInvio currently stores the resulting credentials; it does not provide a complete public-app consent flow.
4. Enter those values only in the secure **Connection settings** fields. Add verified SKU weights, one per line, for example **MUG-BLUE = 350** and **TEE-M = 180**. Weights are grams per unit, not packed shipment weight. Add a strong AWS API-destination key of at least 32 characters in **Webhook signing secret / AWS API-destination key**. Save the connection. Never paste credentials into chat.
5. Ask your AWS administrator to connect the seller's **ORDER_CHANGE** notification delivery using the AWS setup below. Amazon is notification-driven here; the Shopify **Retrieve orders** button is not the Amazon import mechanism.
6. After an eligible notification arrives, open the Amazon store's **Import activity**. Then open **Marketplace Workspace**, select the store, and find the Amazon order reference. Review packing, the customer address, measured dimensions and customs, then request quotes and explicitly book the chosen service. Import does not buy a label or charge a wallet.

## AWS notification delivery setup

Create an Amazon Notifications API destination backed by Amazon SQS and subscribe to **ORDER_CHANGE** for the authorised seller. Configure the queue access policy and the application/notification permissions required by Amazon.

Connect that queue to **EventBridge Pipes**, with SQS batch size **1**, and an EventBridge API destination. Forward the original notification object, not the surrounding SQS record, array or SNS envelope. For an SQS source, use an input template such as **{"detail": <$.body>}** to preserve the JSON object in the receiver-supported detail envelope. Do not quote the object substitution. Inspect a sample delivery to confirm that detail contains the original ORDER_CHANGE object; malformed string transformations are rejected.

Set the API destination method to **POST**. Use your own public EasyInvio domain and that store's UUID: **https://YOUR-EASYINVIO-DOMAIN/api/v1/integrations/ecommerce/orders-sync?store_id=YOUR-STORE-UUID**. These two labels describe values to replace with your deployment and registered store; they are not real credentials. Configure the EventBridge connection's API-key header **x-easyinvio-amazon-key** with the same secret saved in EasyInvio Connection settings.

EasyInvio authenticates the event, checks seller/marketplace identity, stores a durable receipt and queues a current order lookup. Its background logistics worker must be running to process that queue. Configure appropriate queue retry/dead-letter monitoring so failed deliveries remain visible. Saving connection settings alone does not create the Amazon subscription, SQS queue, Pipe or API destination.

## Test and troubleshoot Amazon orders

For an eligible example, use a merchant-fulfilled, wholly unshipped order containing two units of MUG-BLUE, with that SKU mapped to 350 grams and complete recipient/address and price data. EasyInvio can prepare its 700-gram goods weight; the dispatcher still measures the packed parcel. Amazon-fulfilled/FBA orders are not imported as ordinary merchant dispatches; partial allocation requires review.

If **Import activity** is empty, inspect the Amazon subscription and AWS delivery/dead-letter logs, the API destination URL, store UUID, header and key. If events arrive but remain queued, check the deployed background worker. If an entry needs review, check seller authorisation, marketplace IDs, required data permissions, complete recipient details and SKU weights. Correct the cause before using the available retry action. Preserve the original order reference to avoid duplicate fulfilment.

During UAT, do not assume the application's TEST carrier setting makes an Amazon seller connection a sandbox connection. The current order reader uses Amazon's regional seller API endpoint. Amazon's static API sandbox is not proof of end-to-end seller notification delivery. Use only an authorised, deliberately selected test arrangement and keep label purchases in the intended environment.

## Official references and related help

Amazon authorisation methods: https://developer-docs.amazon/sp-api/docs/authorizing-selling-partner-api-applications

Amazon Notifications API: https://developer-docs.amazon/sp-api/docs/notifications-api

Amazon Orders API: https://developer-docs.amazon/sp-api/docs/orders-api

Amazon marketplace IDs: https://developer-docs.amazon/sp-api/docs/marketplace-ids

AWS input transformation: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-pipes-input-transformation.html

For other store preparation steps, read [Import and prepare store orders](/help/features/order-processing). For permissions, read [Invite your team and protect access](/help/team-and-security).
