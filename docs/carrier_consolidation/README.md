# Branded carrier consolidation and performance statistics

Customer quote cards show the carrier/service and EasyInvio.com, not the sourcing aggregator. Customer quote, shipment, dispatch, automation and support JSON projections remove supplier/account/upstream references. Private in-process rate objects and database booking snapshots keep those references so the selected adapter remains bookable. Platform-owner management endpoints intentionally retain provider identity. This is a customer presentation boundary, not a claim that third-party label/tracking URLs or source-code inspection cannot identify infrastructure.

## Selection policy

After every actual wholesale quote receives the tenant's indexed pricing rules, rates are grouped by normalized carrier, service and currency. The retained record maximizes **absolute profit = customer price excluding tax − wholesale cost**. Equal-profit ties prefer the lower customer price, lower wholesale cost, faster known estimate and stable internal reference order. The remaining carrier options are sorted by customer price.

Only known spelling aliases are normalized. Different tiers, currency amounts and unknown service codes are not guessed to be equivalent. Adding Shippo/Shiprocket later requires their adapters to map carrier/service identities consistently; this change does not activate those providers or implement their booking workflows. Existing EasyPost/Sendcloud/regional routing remains the source of actual quotes.

## Performance data

- `on_time_rate`: Decimal percentage of delivered shipments whose measured weekday date boundaries meet the stored quoted delivery-day estimate. Weekends are excluded; holiday calendars are not adjusted. Records with no stored estimate are excluded from this percentage's denominator.
- `avg_transit_days`: Decimal average elapsed calendar days from dispatched_at, falling back to booked_at when dispatch is unavailable, to delivered_at.
- History is scoped to the requesting tenant and destination over a rolling 90-day window. Explicit synthetic/fixture records are excluded.
- Sample counts and method descriptions accompany the metrics. Missing history/estimates produce nulls and "history unavailable" in the UI. No sample percentage is silently generated.
- HIGH_DELAY_ALERT: at least three recent active exception shipments, or at least ten qualified deliveries with below 80% on-time performance. MEDIUM: any recent exception, or at least ten qualified deliveries below 90%. Otherwise LOW; a LOW value with no history does not claim proven reliability.
- Data reads are bounded at 10,000 eligible lane records. If the cap is exceeded or history is unavailable, quote generation continues without fabricated performance data.

The route alert describes recorded exceptions/delays rather than claiming "local sorting" when that cause was not established. Simple carrier wordmarks are code-rendered identification aids, not fetched official artwork. High-risk cards use amber borders and warnings. Accountants can now access read-only Speed Quote Matrix offers without gaining booking permission. Financial fee disclosures remain available to OWNER/ADMIN/ACCOUNTANT; warehouse dispatchers do not receive the wholesale splits.

## API and database

`GET /api/v1/analytics/carrier-performance?destination_country=US` returns tenant-isolated carrier history. `/api/v1/routing/disruptions` now returns carrier summaries rather than provider names; its historical grouping is carrier/destination, with `origin_filter_applied=false` stated explicitly. Existing query authorization remains enforced.

Migration `022_carrier_consolidation.sql` adds only a partial history-query index and is already applied to the configured sandbox. No shipment, wallet or tenant records were permanently altered. Other databases should apply that file after 021. There is no new mandatory column or table.

Opaque `offer_id` values identify presented offers; the live booking implementation continues using its private stored rate snapshot. Do not accept browser-supplied wholesale prices or provider IDs as booking authority. Full native booking/returns expansion remains the previously agreed next task.

## Verification

229 regression executions passed. New checks cover highest-profit selection, distinct currencies/tiers, stable ties, immutable private snapshots, public supplier-reference removal, preservation of customer order references, Decimal historical averages, unknown-data honesty and tenant-scoped queries. Controlled browser checks passed for carrier-only cards, finance-only disclosures, amber alerts and 375/768/1366px layouts. Enterprise and identity browser regressions passed.

The real Supabase probe inserted five temporary shipment histories, verified 50.0% on-time, 2.3 calendar-day average, HIGH_DELAY_ALERT and cross-tenant exclusion, then rolled back every inserted record. These are test assertions, not permanent production trust statistics. The screenshot `rates.png` uses explicitly controlled preview data.
