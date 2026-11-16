# Public daily rate examples

The landing page has one registration CTA in the header and no duplicate hero calculator. The rate tab reads only GET `/api/v1/public/rate-showcase`. Ten fixed parcel scenarios cover five UK journeys and five journeys from the UK to Paris, Berlin and Amsterdam, with packed weights 0.5–10 kg and explicit dimensions. Samples use public venue locations, not customer addresses.

## Required activation

1. Identify an EasyInvio-owned marketing workspace and its approved carrier account IDs. Publication consent is represented by explicit configuration; no account is selected automatically and no customer/private contract is used implicitly.
2. Apply `migrations/050_public_rate_showcase.sql` to the intended database using your normal migration workflow. The cache is inaccessible to `anon` and `authenticated` database roles. Ordinary application startup still works without this migration when publication is disabled.
3. Configure these values in the worker’s deployment environment and privately for an operator refresh:
   - `PUBLIC_RATE_SHOWCASE_ENABLED=true`
   - `PUBLIC_RATE_SHOWCASE_TENANT_ID=<approved workspace UUID>`
   - `PUBLIC_RATE_SHOWCASE_ACCOUNT_IDS=["<approved carrier account UUID>"]`
   - `PROVIDER_ENVIRONMENT=LIVE` and valid LIVE credentials on those existing carrier connections.
4. Deploy the matching web/worker source bundle. The worker refreshes on startup, then checks every five minutes. A database advisory lock plus a durable timestamp bounds provider refreshes across replicas; failed/missing scenarios retry at most hourly, successful same-day scenarios are reused until the next UTC day.
5. To refresh just the marketing examples without starting queue consumers, run `.venv\Scripts\python.exe -m backend.public_rate_showcase`. This creates rate requests through existing adapters only. No label purchase, wallet debit, pickup, tracking registration, notification or customer shipment is initiated. Providers may create their ordinary draft shipment/rate objects, and address verification/API usage may consume quota.

## Published price meaning

The existing rating engine applies dimensional charging, account eligibility, pricing rules and provider validation. The lowest returned GBP price that permits label purchase is selected for each scenario, excluding VAT and destination duties/taxes. It is an example checked at the displayed time, not a guarantee of the lowest market price, a reserved fare or a checkout offer. The signed-in user must enter real addresses, contents and customs details and get a new quote.

Only city labels, dimensions, weights, public carrier/service names, client-facing price, estimate, confirmed transport mode and check timestamp are exposed. Quote IDs, account/workspace IDs, provider credentials, execution metadata, margins, wholesale costs and customer records are excluded. Anonymous visitors cannot supply routes or trigger provider calls. Outdated-day prices are removed rather than displayed as today’s deals. Missing configuration, missing migrations, no services and local preview all return ten useful route cards with no fabricated price.

No air/road/sea mode is inferred from speed, brand or destination. A mode is published only when the provider explicitly returns ROAD, AIR or SEA. Current fixed scenarios are parcels; ocean freight is not advertised if no verified ocean service is returned.

The route selection query `rate_example` accepts only the ten catalog IDs. It opens existing registration or, for a verified signed-in user, the workspace. A fresh-quote button copies package measurements only; it does not overwrite private addresses or submit a booking. No price or privilege comes from a query parameter.
