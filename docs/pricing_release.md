# Pricing release checklist

The canonical policy is `backend/entitlements.py`. Checkout price validation,
subscription lifecycle arithmetic and contracted revenue reporting use it.

| Plan | Monthly GBP | Annual GBP | Included parcels/month | Overage GBP/parcel |
| --- | ---: | ---: | ---: | ---: |
| Starter | 0 | 0 | 150 | 0.15 |
| Velocity | 25 | 240 | 2,000 | 0.05 |
| Command | 75 | 720 | 4,000 | 0.02 |

Prices exclude applicable VAT, postage and third-party usage. Higher Command
volumes require agreement. Annual billing saves 20% on the software subscription.
Public help, guest estimates and safe tracking remain rate limited; paid workspace
WhatsApp, AI and store API entitlements are preserved. These prices alone cannot
guarantee profit: monitor actual messaging, model, address-lookup and carrier spend.

## Existing overage limitation

The policy already exposes the requested overage rates. Existing database booking
guards still stop Starter above 150 parcels; paid plans record overage reservations
but do not automatically collect an overage charge. This pricing task preserves
those controls and does not introduce new billing side effects or migrations.
The public FAQ and estimator explicitly disclose this. Activate a separately tested
overage collection flow before advertising automatic extra-parcel billing.

## Before enabling paid checkout in UAT or releasing to Production

Create four GBP recurring Stripe Prices in the matching Stripe environment:
Velocity monthly 2500 pence, Velocity yearly 24000 pence, Command monthly 7500
pence, Command yearly 72000 pence. Use `per_unit`, interval count 1.
Update the existing `SUBSCRIPTION_PRICE_IDS` mapping (keys `VELOCITY:MONTHLY`,
`VELOCITY:ANNUAL`, `COMMAND:MONTHLY`, `COMMAND:ANNUAL`) to those real Price IDs.
Do not invent IDs or reuse old prices: checkout rejects mismatching amounts.
Test in Stripe test mode first; this code change does not change Stripe objects,
environment files, existing agreements, or deploy any environment.

If paid subscriptions already exist at previous rates, reconcile those agreements
and Price mappings before rollout. The current validator requires the published
amount even for provider reconciliation; old prices will require review. Existing
paid terms are not automatically grandfathered or changed at Stripe. Annual
cancellation uses the new monthly rate for clawback, so review existing contracts
before activating this release. Invoice and statement history remains unchanged.

## Local checks

Open `/pricing` on the local server. Toggle monthly/annual; confirm 25/75 and
20/60, with annual totals 240/720. At 6,000 parcels Command has 40 GBP overage:
monthly software plus overage 115 GBP, annual equivalent plus overage 100 GBP.
Check the seven-category table on desktop and mobile, and open plan signup links.
No database migration is required for this pricing update.
