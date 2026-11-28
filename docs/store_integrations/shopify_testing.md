# Shopify development-store test

Registering a store only names it in EasyInvio. It does not authorize Shopify.
After successful registration, connection settings open directly. Save and verify
Shopify connection encrypts the credentials and performs a read-only shop query.
It does not import orders, create fulfillments, notify buyers, or buy labels.
Retrieve orders is a separate action and checks whether the app can read orders.

## Before you begin

- Sign into EasyInvio as the client workspace Owner or Admin.
- The effective plan must permit stores: Starter currently permits zero,
  Velocity two, Command five. Finish any required plan confirmation/payment first.
  The UI now shows a plan-limit rejection inside the registration dialog and
  links to Change plan. It does not silently register a disconnected placeholder.
- Create a Shopify dev store from your Dev Dashboard, then create/install an app
  in the **same Shopify organization**. Client credentials do not work across
  unrelated merchant organizations. For another merchant, use a valid Admin API
  token obtained through an authorized Shopify installation/OAuth flow instead.
- Grant `read_orders` for retrieval. Order shipping addresses require appropriate
  protected customer-data access; check the app's data-access configuration.
  For optional merchant-managed fulfillment/tracking write-back, also authorize
  `read_merchant_managed_fulfillment_orders` and
  `write_merchant_managed_fulfillment_orders`. Leave write-back off initially.

## Values to enter

| Field | Value |
| --- | --- |
| Display name | `Sync4ai Shopify QA` (any recognizable name) |
| Platform | Shopify |
| Shopify store hostname | Your actual `your-dev-store.myshopify.com`; no `https://`, `/admin`, path or custom storefront domain |
| Connection method | App credentials (same Shopify organization) |
| App Client ID | The installed app's real Client ID from Shopify Dev Dashboard |
| App Client secret | The same app's real Client secret; enter only in EasyInvio's password field |
| Admin API access token | Leave blank when using app credentials |
| Webhook signing secret | Leave blank for this initial API-retrieval test |
| Verified product weights | `EI-TEE = 200` if the product has SKU `EI-TEE` and unit weight 200 grams; use the exact SKU and correct unit weight for each product |
| Read-only order retrieval | Enabled |
| Live tracking write-back | Disabled initially |
| Signed return requests | Disabled initially |

These hostname/ID examples are placeholders. Dummy credentials will not establish
a real Shopify connection. Do not use a Shopify login password, Storefront API
token, Stripe key, or EasyInvio token in the Admin API credentials fields.

Client credentials exchange is performed by the backend. Shopify issues a
short-lived token; the adapter obtains a token when needed. No token needs to be
copied from an example or exposed in browser scripts.

## Verify the flow

1. Open Store Integrations, choose Shopify, enter the display name, and register.
2. Fill the connection form using the installed app values above. Save and verify.
3. A successful read-only verification closes the form and displays a result in
   the store panel. This proves shop access, not fulfillment permission or webhook
   delivery. A failed verification stays visible in the form; settings already
   saved remain encrypted. Correct the credentials and retry without registering
   another store. Blank secret fields retain the saved credentials.
4. In Shopify, create a shippable product with SKU `EI-TEE`, unit weight 200 g and
   a positive price. Place an order using Shopify's test payment gateway (or the
   payment provider's test mode), a complete UK shipping address and GBP currency.
   Keep the order wholly unfulfilled and at a single fulfillment location.
5. Click Retrieve orders in EasyInvio. The order appears in Marketplace Workspace.
   Missing SKU weights, incomplete addresses and partial fulfillment require
   review. Enter packed weight and dimensions before comparing rates.
6. Retrieve again: the same upstream order must not create another shipment.
   Import and quote actions do not purchase a label; booking requires its own
   explicit confirmation and eligible funding.

For later webhook testing, app-managed Shopify webhooks use the app Client secret
for signature validation. Manually created webhooks use the signing secret shown
by Shopify. Save that matching secret in EasyInvio and use a public HTTPS callback
origin plus `/api/v1/integration/webhooks/<store-id>`. Opening the connection form
does not register those webhooks automatically. Initial API retrieval needs no
ngrok webhook callback.

## Official references

- [Create a Shopify dev store](https://shopify.dev/docs/apps/build/stores/development-stores)
- [Authenticate apps for stores in your organization](https://shopify.dev/docs/apps/build/authentication-authorization/client-credentials-grant)
- [Shopify API access scopes](https://shopify.dev/docs/api/usage/access-scopes)

Automated acceptance: `tests/store_registration_browser.py` uses synthetic HTTP
responses to cover plan rejection, direct handoff, form submission, verification
failure/retry, clearing secret fields and responsive layout. It sends nothing to
Shopify and does not prove a merchant's real credentials or scopes work.
