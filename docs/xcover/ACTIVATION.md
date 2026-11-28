# XCover activation checklist

Local readiness checked on 28 November 2026: protection is disabled, a signing
secret is absent, and parcel-contract/retail-pricing confirmations are false.
Configured credential values were not printed, changed or committed. Production
configuration has not been inspected or changed.

## What to obtain from the XCover integration manager

- Separate staging and production partner ID, API key and signing secret.
- Confirmation that the contracted product covers UK-origin parcels, with its
  supported destinations, commodities, limits, exclusions and policy wording.
- Approved retail premium/markup and applicable protection tax treatment. The
  current GBP 1.20 minimum / 1% screen estimate is not a provider-issued tariff.
- Approved claims arrangement, customer disclosures and policy documents.
  Native XClaim needs its separate credentials, form bindings, webhook and
  settlement mappings; quote/booking credentials do not configure claims.

## Configure staging first

Set server-only `XCOVER_ENABLED=true`, `XCOVER_ENVIRONMENT=TEST`,
`XCOVER_PARTNER_ID`, `XCOVER_API_KEY` and `XCOVER_SIGNING_SECRET` through secure
configuration. Set `XCOVER_PARCEL_CONTRACT_VERIFIED=true` and
`XCOVER_RETAIL_PRICING_VERIFIED=true` only after receiving those confirmations.
Never share or commit credentials. Confirm required protection/claims migrations
are applied through the normal database release process; this UI change applies
no migrations. Use a single protection reconciliation worker for the shared DB.

Verify a provider-issued quote, exclusions/documents, explicit customer consent,
premium and tax total, wallet reservation and debit, label/policy confirmation,
receipt, retry/idempotency and failed/unknown provider response recovery. Test a
claim and settlement before claiming native claims are operational. The existing
protected single-label path supports GBP, GB-origin and wallet funding; bulk and
card-funded protected bookings remain outside that path.

## Production activation

After successful staging acceptance, configure the distinct LIVE credentials and
`XCOVER_ENVIRONMENT=LIVE` in the production secret store. Verify production
product/pricing permissions, callback reachability and the single-worker
arrangement before enabling. A live policy is confirmed only by XCover's actual
booking response; enabling a flag does not create coverage or eliminate all
merchant liability. Do not use test keys or bypass readiness/environment guards.

Official API reference: https://xcover-api-docs.covergenius.com/parcel_insurance.html
Production endpoint: https://api.xcover.com/x
Staging endpoint: https://staging.api.xcover.com/xcover

## Why a carrier quote can be unavailable for booking

With `PROVIDER_ENVIRONMENT=TEST`, the application currently supports test label
purchase for the EasyPost and Shippo adapters. Other configured endpoints can
return rates but are gated as quote-only before payment. This includes offers
from the Sendcloud test connection regardless of carrier name (for example
InPost or Hermes). A low price does not establish label-purchase capability.
Use a bookable test service to exercise booking. Live booking requires an
enabled supported provider account and live purchasing authorization; do not
switch the entire environment to LIVE merely to bypass the test restriction.
