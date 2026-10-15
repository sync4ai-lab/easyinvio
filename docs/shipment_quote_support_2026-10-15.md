# Shipment form and quote-support remediation

Review date: 15 October 2026, Europe/London.

## What changed

The shipment form now labels SKU entry as "Product SKU (type or search)". A merchant may enter their own SKU or select a catalog match. Repeated loaded-product and snapshot explanations were removed. HS-code controls are hidden from the initial goods form; saved classifications remain optional snapshot metadata, and the customs step still requires the shipper's review. The additional section is called "Additional goods".

Address selection searches both warehouse addresses and contacts, including Return and Invoice addresses that the old sender picker excluded. Every result shows its saved role so the operator chooses explicitly. Address search also includes street lines, postcode and country. These changes retain verified-tenant query binding; they do not search other workspaces.

Weight calculation waits until all required measurements are present and positive. An incomplete form displays a short instruction instead of sending empty strings to strict Decimal validation.

Unsupported freight now opens a manual quote request instead of attempting the native parcel adapters. This is conditional on the existing capability check: a configured custom freight connection can still proceed through rate evaluation. Customers can also request parcel help or select road/sea freight review explicitly. No sea-booking adapter, carrier contract or automatic freight price is implied.

## Findings from the configured database

A read-only inspection of twelve recent saved quote records found both unsuccessful requests and records with two, three or five retained offers. Failures included `NO_SERVICES_FOR_ROUTE_OR_ACCOUNT`, `UPSTREAM_REQUEST_REJECTED`, `NO_ELIGIBLE_PRICED_SERVICES` and `FREIGHT_ADAPTER_CONTRACT_NOT_CONFIGURED`. The inspection was platform-wide and does not independently identify the exact request in the screenshots. They do not establish a universal aggregator outage.

The enabled carrier-account records inspected were in TEST environments. Test availability, enabled carrier contracts, origin/destination coverage and account-specific permissions must be checked before assuming the same service is available for a real booking. No credentials were changed or displayed. No label purchase or wallet transaction was attempted.

The native EasyPost, Shippo and Sendcloud adapter paths deliberately reject industrial freight requests. Pallet/road weight arithmetic is implemented, but that calculation does not supply a verified freight quote or sea-freight booking capability. Live freight needs a provider-specific contract and implemented, verified rating/booking interface. Until then, requests can be triaged manually through the new internal cases.

A live replay of the failing customer shipment was not executed. Automatic approval review rejected resending its saved addresses and shipment data to external provider APIs with stored credentials without specific approval. The exact upstream rejection remains unverified; generic provider codes must not be described as a proven adapter defect or authentication failure.

## How the support team handles a call

1. Ask for the quote reference shown beside a failed rate result, or ask the customer to use "Request parcel help or a freight quote". No payment is required.
2. Open the Super-Admin support centre. Choose the reporting/environment filters for that client's workspace. Failed saved rate searches create a "Rate availability investigation" case; manually submitted freight requests create a "Freight quote request" case.
3. Review the reference, route, cargo, measurements and diagnostic codes. Failed quote snapshots remain in the existing private `partner_unbound_quotes` records. The case references that saved request; no shipment or tracking record is fabricated.
4. In Carrier Connectors, open "Capabilities & quote diagnostics" for the affected connection. Check enabled state, TEST versus LIVE configuration, supported origin/destination, currency, active carrier account/contracts and the available services. A connection-verification success proves authentication, not route coverage.
5. For `UPSTREAM_REQUEST_REJECTED`, inspect the exact provider validation result through an authorized diagnostic run before changing payload mappings. For `NO_SERVICES_FOR_ROUTE_OR_ACCOUNT`, verify carrier/route eligibility and account activation. For `FREIGHT_ADAPTER_CONTRACT_NOT_CONFIGURED`, arrange a manual freight quotation or configure a verified freight integration; never relabel freight as a parcel to bypass the block.
6. Add internal notes and close the case through the existing support workflow once the issue is resolved. Client assistance remains available for reproducing the issue in the correct workspace with admin attribution.

If the pictured goods are in the same package, their net weights are 15 + 29 = 44 kg before packaging. A packed weight of 21 kg would be inconsistent. Correct the measurements or separate the packages rather than weakening the goods-mass checks. This observation does not prove it caused every missing quote.

## Persistence and boundaries

`POST /api/v1/shipping/quote-support` validates a tenant-authenticated request and records a case using the existing `automation_failures` and `support_tickets` tables. A request UUID makes retries idempotent within that tenant. Rate searches returning `NO_CARRIER_RATES_AVAILABLE` save the unsuccessful snapshot and attempt internal case creation. Optional support persistence failure does not replace the original rate error or invent a successful case.

Internal cases are excluded from the client ticket query by the existing support boundary. Intake does not write wallet entries, buy labels, submit insurer claims, invoke AI or queue WhatsApp/email messages. Existing admin-assistance request auditing still applies. No schema migration is needed.

The default automated checks use controlled provider/database boundaries. Live provider acceptance and new freight contracts are separate tasks. Restart the backend and refresh the browser to load the changed routes and UI.

## Verification

The repository regression run completed with 768 passed, one opt-in configured-startup smoke test skipped, and 14 subtests passed in 194.24 seconds. There was one existing TestTopupInput collection warning. The isolated browser scenario passed without page errors, including Return-role address search, hidden initial HS controls, manual sea intake and unsupported-road-freight routing. Provider and database boundaries were mocked in that browser run. The configured database inspection was read-only; live provider replay remains pending approval.
