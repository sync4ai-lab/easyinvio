# Sendcloud and additional aggregator setup

EasyInvio now supports Sendcloud **v3 dynamic rate discovery** alongside EasyPost. The old v2 method-limit adapter remains available for existing connections. New Sendcloud setup defaults to `https://panel.sendcloud.sc/api/v3`, uses public/secret Basic Auth, sends origin/destination addresses and package dimensions/weights to `/shipping-options` with `calculate_quotes=true`, and maps actual quotes through the shared tenant margin pipeline. No manual `SENDCLOUD_METHODS` list is required for v3.

## Obtain Sendcloud keys

1. Sign in to your company-owned Sendcloud account.
2. Complete your sender/invoice address setup and enable the carriers you want to offer.
3. Open **Settings → Integrations**.
4. Find **Sendcloud API** and click **Connect**.
5. Name the integration **EasyInvio platform** and save.
6. Copy the generated **Public API Key** and **Secret API Key** securely.
7. In EasyInvio, sign in as the authorized platform owner, then open **Carrier Connectors → Sendcloud → Set Up**.
8. Enter both keys, select TEST while this app is in provider TEST mode, save and activate the shared connection.
9. Click **Verify Connection** on its network row. This is a read-only authentication probe and does not buy a label.

The Sendcloud public key acts as the Basic Auth username; the secret key is its password. The implemented adapter uses Basic Auth; do not configure the Sendcloud integration to require OAuth unless a separate OAuth adapter is implemented. Credentials are encrypted server-side and projected into eligible tenant-bound rows; client users never receive the master keys.

Sendcloud's credentials are not automatically separate sandbox keys like EasyPost's TEST keys. Selecting TEST here controls which sandbox tenants can use this connection; the implemented Sendcloud operations are read-only quote/metadata calls. It does not make a live shipment announcement safe. No label/charge is created during these checks.

Official setup: https://support.sendcloud.com/hc/en-us/articles/360024967012-Sendcloud-API-documentation-and-Quick-Start-Guide
Authentication: https://sendcloud.dev/docs/getting-started/authentication
Quote API/schema: https://sendcloud.dev/api/v3/shipping-options/return-a-list-of-available-shipping-options

## Implemented boundaries

- V3 parcels: dynamically discovers carriers/options activated in the upstream account; Decimal costs, tenant-isolated markup, timeout/response-size limits, currency matching and option deduplication.
- Missing prices, unknown currencies, unmatched weight bands, service-point-only/return services and estimated extra surcharges are not turned into invented all-inclusive offers.
- Letters and industrial pallets/freight require their own verified provider contracts; this parcel adapter rejects them.
- Sendcloud native label purchasing, Orders API management, Returns API automation and Ship-an-Order are **not implemented** by this quote adapter. Do not mistake the Set Up/Verify actions for support for those workflows. The capability catalogue explicitly reports these as false.
- Existing EasyPost and regional providers remain available; no migrations or existing connector changes are required.

## Common interface versus provider protocol

`backend/aggregator_registry.py` documents recognized provider/version capabilities. `GET /api/v1/admin/platform-carriers/capabilities` and `POST /api/v1/admin/platform-carriers/{id}/verify` are owner-only. New providers need an explicit adapter mapping their authentication, rates, service identities, cargo limits, label idempotency/reconciliation and webhook signatures to the common application model. Adding a random URL/key is not enough. The approved LocalRegional protocol remains available for compatible vendors.

For a third aggregator, supply its name/documentation and obtain its company-owned credentials. Multiple Sendcloud carriers already provide additional shipping choices, but Sendcloud v2 and v3 are versions of one aggregator, not two separate providers.

## Verification

222 regression test executions passed, including seven new Sendcloud/credential-verification checks. Enterprise browser checks passed with no JavaScript errors. These are controlled protocol tests, not genuine Sendcloud account verification: no Sendcloud keys have been supplied yet.

The newly saved EasyPost shared TEST connection is active and its read-only `/shipments` authentication request returned HTTP 200. `/carrier_accounts` is unsuitable for testing this TEST key because carrier-account management is production-only; the verification button now uses `/shipments?page_size=1` instead.

HubSpot remains disabled: current configured mode SANDBOX, actual token account type STANDARD, Companies API HTTP 403. That token/account configuration still needs correction before genuine CRM tests.
