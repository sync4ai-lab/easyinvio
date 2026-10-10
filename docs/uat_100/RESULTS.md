# Veloce.AI — consolidated 100-case report after remediation

2026-10-10T10:16:24.525976+00:00

86 PASS, 5 FAIL, 1 BLOCKED, 7 PARTIAL, 1 EXCLUDED.

**Validation:** 65 selected regression tests passed. Real browser geometry/interactions were tested in Chromium, Chrome, Edge, Firefox and WebKit. Actual Supabase logins, role dashboards, tenant isolation, wallet capture, invoice comparisons and ticket lifecycle were tested. Controlled carrier receipts were used for financial settlement; no real carrier label was purchased. Actual Apple Safari remains untested.

**Database:** `migrations/014_support_ticket_lifecycle.sql` was rollback-validated and applied to your configured Supabase sandbox. It adds `IN_REVIEW`/`CLOSED` ticket states, `archived_at` and an index; preserves historical `RESOLVED` data. No further SQL needs to be run in this sandbox. Apply the migration when deploying to any other database. Receipt: `migration_014_receipt.json`.

Backend restarted and `/health`, new routes, and updated frontend verified locally. Stripe/Twilio/HubSpot were not called. Existing 27 tenants and fixture data were preserved; remediation probes rolled back. Previous UAT-RACE audit records remain.

## Remaining acceptance gaps

- TC-029: Deferred: current providers and database support one parcel per shipment. Multiple orders in bulk remain supported. Carrier multi-piece purchases require a new provider/database contract; summing boxes into one pretend parcel would be incorrect.
- TC-047: Specification conflict: GBP/EUR/USD support is deliberate. No cross-currency totals are silently combined; GBP-only enforcement would remove existing required functionality.
- TC-048: Specification conflict: existing pricing rules use lower numeric priority first. Reversing the order would alter current customer prices. The convention remains unchanged.
- TC-049: Performance target unmet: remote PostgreSQL lookups still exceed 15ms. No stale financial cache was introduced to manufacture a pass.
- TC-068: Specification conflict: no valid universal generic HS code exists for arbitrary random text. Classifier preserves review-required abstention rather than fabricating a commodity code.

These cases retain their failed acceptance result; they are not labelled passed or silently excluded. Warehouse enrollment requires a pre-provisioned Supabase principal. Disposable real-auth users were provisioned for testing without emails; every disposable identity was deleted after verification. No additional database migration was needed for this testing expansion.

## All 100 cases

### TC-001 — PASS: Login validation with valid OIDC token context

Expected: Grants secure access, sets dynamic tenant session state.

Observed: Actual Supabase ES256 login succeeded; backend accepted server-owned app_metadata tenant identity, confirmed active membership and loaded private browser dashboard.

Evidence: real_auth_evidence.json

### TC-002 — PASS: Login rejection with malformed or expired token payload

Expected: HTTP 401 Unauthorized response generated.

Observed: Controlled authentication tests reject missing, expired and tampered tokens.

Evidence: core_regression.log: test_missing_expired_and_tampered_tokens

### TC-003 — PASS: Row-Level Security (RLS) shipment search bypass attempt

Expected: Client A querying Client B's shipment ID returns 0 rows or 404.

Observed: Authenticated RLS returned exactly 8 own shipments; zero other-tenant rows.

Evidence: database_evidence.json

### TC-004 — PASS: Cross-tenant URL tampering via parameter injection

Expected: Changing tenant parameters on the dashboard displays an error and resets to the session identity.

Observed: Actual authenticated tenant URL tampering preserved session identity, removed the conflicting query parameter and displayed a rejection notification.

Evidence: real_auth_evidence.json

### TC-005 — PASS: Accountant role boundary restriction check

Expected: Allowed to view invoices and financial reports; blocked from clicking "Book Label".

Observed: Actual accountant login: financial reports 200; sample ZPL preview 403; quote button disabled and dispatch viewport blocked.

Evidence: real_auth_evidence.json

### TC-006 — PASS: Dispatcher role boundary restriction check

Expected: Allowed to quote and print labels; completely blocked from viewing platform margin reports or admin settings.

Observed: Actual dispatcher login: quote viewport allowed and sample ZPL preview 200; financial reports/platform admin 403. Actual carrier purchase is a separate unverified integration.

Evidence: real_auth_evidence.json

### TC-007 — PASS: Admin role boundary verification

Expected: Allowed to add new warehouse users within their own tenant space.

Observed: Administrator enrolled a pre-provisioned same-tenant auth principal through real ASGI route and database; dispatcher denied. All changes rolled back. UI enrolls existing pre-provisioned auth UUIDs; does not create login credentials.

Evidence: database_evidence.json

### TC-008 — PASS: Super-Admin role viewport toggle restriction

Expected: Only users with system-wide metadata can toggle the dashboard layout switcher.

Observed: Actual signed-in client roles could not toggle Super-Admin; server returned 403 for macro dashboard. Server subject allowlist remains the sole owner authority.

Evidence: real_auth_evidence.json

### TC-009 — PASS: JWT token claim expiration handling

Expected: System signs the user out automatically when the session expires.

Observed: Expired session timer executed actual clearSession controller; session became null.

Evidence: remediation_frontend_evidence.json

### TC-010 — PASS: Multi-device active login validation

Expected: Tenant metrics load correctly when accessed concurrently on two separate devices.

Observed: Actual real-auth tenant metrics/manifest matched across concurrent HTTP requests and isolated desktop/mobile browser contexts.

Evidence: real_auth_evidence.json

### TC-011 — PASS: Direct SQL injection payload testing via text inputs

Expected: Input data is securely sanitized; queries return 0 results.

Observed: Actual signed-in manifest search returned zero matches for three SQL/HTML injection payloads; injected API tenant parameter returned only authorized tenant tickets.

Evidence: real_auth_evidence.json

### TC-012 — PASS: Disabled user login validation

Expected: Active status flag check defaults to false; access is blocked.

Observed: Actual non-banned Supabase auth account with inactive membership signed in at Supabase but was rejected by Veloce with 403.

Evidence: real_auth_evidence.json

### TC-013 — PASS: Tenant workspace data leak isolation test

Expected: System-wide background tasks verify that tenant data isolation remains intact during bulk processes.

Observed: Concurrent real PostgreSQL QUOTE_ONLY writes for GBP and EUR tenants stored their own 11.50/12.00 prices. Other-tenant ID lookups returned zero. Controlled provider responses, no external carrier calls, all writes rolled back.

Evidence: bulk_isolation_evidence.json

### TC-014 — PASS: Unauthorized API route access verification

Expected: Direct backend queries to endpoints like /api/v1/admin/* fail without an active admin token.

Observed: Actual running backend owner dashboard rejects unauthenticated requests with 401.

Evidence: database_evidence.json unauthenticated_http

### TC-015 — PASS: Empty header validation check

Expected: Dropping authorization headers triggers a missing credential response.

Observed: Actual analytics and tickets routes reject missing Authorization headers with 401.

Evidence: database_evidence.json unauthenticated_http

### TC-016 — PASS: Standard package weight validation

Expected: System uses dead weight if it is greater than the calculated volumetric weight.

Observed: {'actual_weight_kg': '2', 'volumetric_weight_kg': '0.200', 'billable_weight_kg': '2.000', 'divisor_cm3_per_kg': '5000', 'basis': 'actual'}

Evidence: direct_observations.json; core_regression.log

### TC-017 — PASS: Volumetric weight calculation override check

Expected: A light but large box (e.g., 50x50x50cm, 2kg) triggers volumetric billing: 50×50×50 / 5000 = 25kg billed.

Observed: {'actual_weight_kg': '2', 'volumetric_weight_kg': '25.000', 'billable_weight_kg': '25.000', 'divisor_cm3_per_kg': '5000', 'basis': 'volumetric'}

Evidence: direct_observations.json; core_regression.log

### TC-018 — PASS: Edge-case volumetric weight match

Expected: If actual weight equals volumetric weight, the system charges the base rate correctly.

Observed: {'actual_weight_kg': '0.200', 'volumetric_weight_kg': '0.200', 'billable_weight_kg': '0.200', 'divisor_cm3_per_kg': '5000', 'basis': 'actual'}

Evidence: direct_observations.json; core_regression.log

### TC-019 — PASS: Fractional weight precision handling

Expected: The database correctly handles highly precise weights like 0.155kg without rounding issues.

Observed: Real numeric column retained 0.155 exactly.

Evidence: database_evidence.json

### TC-020 — PASS: Negative dimension parameter validation

Expected: Entering negative dimensions (e.g., -10cm) triggers a validation error.

Observed: Rejected invalid numeric input

Evidence: direct_observations.json; core_regression.log

### TC-021 — PASS: Zero dimension weight validation

Expected: Entering 0 values for dimensions triggers an input block error.

Observed: Rejected invalid numeric input

Evidence: direct_observations.json; core_regression.log

### TC-022 — PASS: Excessive dimension value restriction

Expected: Packages that exceed carrier maximum limits (e.g., 500cm length) display a warning message.

Observed: 500cm form measurement produced an explicit oversize/freight warning; no universal carrier limit is assumed.

Evidence: remediation_frontend_evidence.json

### TC-023 — PASS: Box layout metric unit validation

Expected: Confirm that the front-end interface correctly converts metric units before submitting backend quote queries.

Observed: Actual Chromium browser: {"submitted": {"length_cm": "35", "width_cm": "30", "height_cm": "20", "actual_weight_kg": "1.55"}, "backend_status": 200, "units": "centimetres and kilograms; Decimal strings"}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-024 — PASS: Custom box template selection tool

Expected: Selecting a saved template automatically populates the length, width, and height inputs.

Observed: Actual controller applyBox(0) populated length 24 and switched to Dispatch.

Evidence: frontend_evidence.json; tests/frontend_contract.cjs

### TC-025 — PASS: Volumetric calculation divider accuracy

Expected: Confirm that the backend logic divides by exactly 5000 for standard express routes.

Observed: {'actual_weight_kg': '2', 'volumetric_weight_kg': '25.000', 'billable_weight_kg': '25.000', 'divisor_cm3_per_kg': '5000', 'basis': 'volumetric'}

Evidence: direct_observations.json; core_regression.log

### TC-026 — PASS: Maximum weight limit check

Expected: Shipments over 1000kg display an overland freight warning.

Observed: Actual Chromium browser: "Weight exceeds 1000 kg parcel limit. Use an overland freight quote."

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-027 — PASS: Form text validation check

Expected: Entering alphabetic text inside numeric weight fields triggers a formatting error.

Observed: Actual Chromium browser: "Real Chromium rejected alphabetic fill into numeric weight input"

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-028 — PASS: Volumetric conversion precision check

Expected: Calculated weights match exact fixed-point parameters without any trailing float artifacts.

Observed: {'actual_weight_kg': '0.155', 'volumetric_weight_kg': '1.999', 'billable_weight_kg': '1.999', 'divisor_cm3_per_kg': '5000', 'basis': 'volumetric'}

Evidence: direct_observations.json; core_regression.log

### TC-029 — FAIL: Multi-box package metric check

Expected: Bulk shipments evaluate and add up the weights of individual boxes correctly.

Observed: Single-parcel schema limits dimensions to one and parcel_count to 1; a multibox shipment sum is unsupported.

Evidence: main.py RatingRequest; database shipment constraints

Deferred: current providers and database support one parcel per shipment. Multiple orders in bulk remain supported. Carrier multi-piece purchases require a new provider/database contract; summing boxes into one pretend parcel would be incorrect.

### TC-030 — PASS: Dimension form autofill consistency

Expected: Interface fields update immediately when swapping predefined box types.

Observed: Actual Chromium browser: {"first_length": "24", "second_length": "40"}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-031 — BLOCKED: Asynchronous multi-carrier query test

Expected: Backend queries both providers at the same time and returns the results within 0.8 seconds.

Observed: Both seeded carrier integrations are inactive with intentionally unusable credentials; real two-provider sub-0.8-second result unavailable.

Evidence: Not executed end-to-end; prerequisite missing

### TC-032 — PASS: Single aggregator down fault-tolerance test

Expected: If one provider is down, the app still loads the remaining carrier options smoothly.

Observed: Actual Chromium browser: "Fault-injected backend response rendered surviving DPD rate plus upstream timeout notice"

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-033 — PASS: Global fallback margin rule validation

Expected: Applies the system-wide baseline markup if no specific tenant rules exist.

Observed: Actual Supabase no-rule supplemental tenant returned 12.00 for 10.00 (20% fallback); applied supplemental fixtures verified read-only.

Evidence: supplement_evidence.json

### TC-034 — PASS: Specific lane margin rule priority check

Expected: If a country-specific rule exists (e.g., UK to USA), it takes priority over global rules.

Observed: US/account rule wins over default: 20%, final 12.00

Evidence: database_evidence.json

### TC-035 — PASS: Tenant-specific margin rule override check

Expected: Confirms that custom client rules successfully override system-wide defaults.

Observed: Controlled live-pipeline test gives different client prices for identical wholesale costs; actual tenant 1 rule returns 11.50.

Evidence: core_regression.log test_two_tenants_receive_different_prices_for_same_wholesale; database_evidence.json

### TC-036 — PASS: Percentage-based markup calculation validation

Expected: A 15% markup rule on a £10.00 base cost calculates a final client price of exactly £11.50.

Observed: Real tenant 1 rule: 10.00 + 15% = 11.50

Evidence: database_evidence.json

### TC-037 — PASS: Flat-rate markup calculation validation

Expected: A flat £5.50 markup rule on a £10.00 base cost calculates a final client price of exactly £15.50.

Observed: Admin service saved FLAT_RATE 5.50 as schema-compatible FIXED Decimal; full database/audit writes rolled back. Stored FIXED 5.50 rule returns 15.50 on base 10.00.

Evidence: database_evidence.json; supplement_evidence.json

### TC-038 — PASS: Zero margin base parameter validation

Expected: Setting a 0% markup rule passes the raw wholesale cost directly to the client.

Observed: Actual zero percentage supplemental rule returned 10.00; applied fixtures verified read-only.

Evidence: supplement_evidence.json

### TC-039 — PASS: Dynamic sorting verification

Expected: Rates display in ascending order, showing the cheapest option at the top of the interface.

Observed: Actual Chromium browser: "Unsorted rates rendered cheapest first using integer-pence comparison"

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-040 — PASS: Maximum markup rule limits check

Expected: Attempting to save a 500% markup rule flags an administrative warning.

Observed: 500% model input now rejected with pricing-policy-review validation message; 499% remains accepted.

Evidence: remediation_core_regression.log

### TC-041 — PASS: Destination ISO code validation check

Expected: Entering invalid country codes (e.g., "XYZ") returns an invalid route code error.

Observed: XYZ rejected as invalid ISO country.

Evidence: direct_observations.json

### TC-042 — PASS: Weight boundary rule validation

Expected: Margins scale accurately when crossing predefined weight tiers (e.g., >20kg rules).

Observed: Actual stored tier: 19.999kg gives 11.00; 20kg gives 12.50 on 10.00 base. Upper bound is exclusive. Applied fixtures verified read-only.

Evidence: supplement_evidence.json

### TC-043 — PASS: Dynamic carrier filtering tool

Expected: Selecting DPD only hides the remaining carrier cards in the results panel.

Observed: Actual DPD selection controller rendered DPD and omitted DHL; original rate indices remain intact.

Evidence: remediation_frontend_evidence.json

### TC-044 — PASS: Surcharge breakdown component check

Expected: Clicking a rate option correctly reveals individual base costs and markup splits.

Observed: Actual JavaScript rendered expandable fee disclosure including residential accessorial fee.

Evidence: frontend_evidence.json

### TC-045 — PASS: Smart routing speed anomaly check

Expected: The system accurately flags routes with high transit delays.

Observed: Five 5-day delays classified as high risk; controlled history classifier, not live carrier prediction.

Evidence: direct_observations.json

### TC-046 — PASS: Multi-user concurrent quoting validation

Expected: Multiple tenants running quotes at the same time receive their respective custom prices without lag.

Observed: Concurrent tenant-specific quote processing with controlled provider responses and real PostgreSQL writes: [{"tenant": "seed24-01", "currency": "GBP", "customer_price": "11.50", "other_tenant_lookup_rows": 0, "shipment_written": true, "quote_process_ms": 503.64}, {"tenant": "seed24-02", "currency": "EUR", "customer_price": "12.00", "other_tenant_lookup_rows": 0, "shipment_written": true, "quote_process_ms": 790.52}]. Live provider response latency remains outside this controlled test.

Evidence: bulk_isolation_evidence.json

### TC-047 — FAIL: Currency baseline enforcement check

Expected: Financial calculations maintain standard GBP currency baselines across the app.

Observed: Application intentionally supports GBP, EUR and USD; seed includes all three. GBP-only expectation does not match design.

Evidence: docs/rigorous_seed_catalog.json; main.py currency models

Specification conflict: GBP/EUR/USD support is deliberate. No cross-currency totals are silently combined; GBP-only enforcement would remove existing required functionality.

### TC-048 — FAIL: Priority index evaluation check

Expected: If multiple custom rules match, the system selects the one with the highest priority score.

Observed: Actual overlapping priority 10 and 100 rules returned priority 10 price 11.00. Implementation uses lower numeric priority first, contrary to highest-score expectation.

Evidence: supplement_evidence.json; backend/admin_portal.py ORDER BY priority ASC

Specification conflict: existing pricing rules use lower numeric priority first. Reversing the order would alter current customer prices. The convention remains unchanged.

### TC-049 — FAIL: Database rule caching speed check

Expected: Margin lookup queries resolve in under 15 milliseconds.

Observed: Five real lookups: [49.74, 43.63, 44.62, 45.64, 43.84] ms; all exceed 15 ms. End-to-end lookup includes network, two SQL queries, no cache.

Evidence: database_evidence.json

Performance target unmet: remote PostgreSQL lookups still exceed 15ms. No stale financial cache was introduced to manufacture a pass.

### TC-050 — PASS: Interface quote refresh check

Expected: Modifying package dimensions automatically clears out old carrier rates.

Observed: Actual Chromium browser: "Real input event cleared stale quotes"

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-051 — PARTIAL: Postpaid 30-day user exemption check

Expected: Postpaid clients can book labels regardless of their current wallet balance.

Observed: Actual postpaid tenant with 0.00 wallet accepted reservation; rolled back. Purchased label remains gated.

Evidence: post_apply_evidence.json

### TC-052 — PARTIAL: Solvent prepaid wallet transaction check

Expected: A prepaid client with a £100 balance can comfortably book a £20 label.

Observed: Actual 100.00 wallet successfully reserved 20.00; no purchased label or final capture performed.

Evidence: database_evidence.json

### TC-053 — PARTIAL: Balanced-to-zero wallet constraint check

Expected: Booking a label that costs exactly the remaining wallet balance brings the wallet to £0.00 and passes.

Observed: Actual exact-funds reservation accepted: 20.00 balance, 20.00 reserved, zero available. Final debit/label not performed.

Evidence: database_evidence.json

### TC-054 — PASS: Prepaid wallet circuit breaker check

Expected: A client with a £10 balance trying to book a £12 label is blocked with an HTTP 402 error.

Observed: Actual wallet 10.00 versus label 12.00 rejected with HTTP 402.

Evidence: database_evidence.json

### TC-055 — PASS: Exact £0.00 wallet baseline block check

Expected: Clients with a zero-balance wallet are immediately blocked from booking labels.

Observed: Actual wallet zero rejected with HTTP 402.

Evidence: database_evidence.json

### TC-056 — PARTIAL: High-concurrency race condition testing

Expected: A client with a £20 balance who rapidly clicks "Book" twice on two £15 labels only generates one label, while the second request is safely blocked.

Observed: Actual simultaneous independent transactions: exactly one 15.00 reservation accepted and second returned 402. Hold released; wallet restored to 20.00 with zero reserved. No label purchase, so full label-generation acceptance remains partial.

Evidence: post_apply_evidence.json

### TC-057 — PASS: Transaction ledger subtraction verification

Expected: Label generation accurately subtracts funds from the wallet and creates a matching audit history row.

Observed: Actual PostgreSQL finance service with controlled carrier receipt: capture reduced wallet 100.00 to 80.00, inserted RESERVE/CAPTURE audit rows and marked the shipment BOOKED. All records rolled back; no carrier label purchased.

Evidence: finance_capture_evidence.json

### TC-058 — EXCLUDED: Mock test environment top-up check

Expected: Running the test endpoint accurately increments the wallet balance.

Observed: Stripe-dependent test-topup intentionally excluded per your instruction; Stripe disabled.

Evidence: Configuration; no Stripe API calls

### TC-059 — PASS: Negative wallet balance protection check

Expected: The database rejects any direct attempts to set negative wallet balances.

Observed: PostgreSQL CHECK rejected balance=-1 (23514).

Evidence: database_evidence.json

### TC-060 — PARTIAL: Wallet balance update speed check

Expected: The dashboard profile balance widget updates immediately after a shipment is processed.

Observed: Preview JavaScript updates wallet immediately; configured paid-shipment dashboard refresh was not exercised.

Evidence: frontend_evidence.json

### TC-061 — PASS: Decimal precision deduction check

Expected: Deducting values with complex fractions (e.g., £12.33) leaves exact balances without any rounding issues.

Observed: Actual PostgreSQL settlement with controlled carrier receipt deducted exactly 12.33 from 100.00, leaving 87.67 and zero reserved. All records rolled back.

Evidence: finance_capture_evidence.json

### TC-062 — PASS: Account status wallet check

Expected: Deactivating a tenant automatically locks out their remaining wallet balance.

Observed: Actual suspended tenant rejected wallet reservation with HTTP 403.

Evidence: database_evidence.json

### TC-063 — PASS: User-role wallet verification

Expected: Dispatchers can spend wallet funds on labels, but are blocked from viewing the main wallet configuration settings.

Observed: Actual dispatcher successfully reserved wallet funds in a rolled-back transaction; wallet configuration viewport was blocked, financial reports 403, operational affordability summary accessible.

Evidence: real_auth_evidence.json

### TC-064 — PASS: Wallet transaction duplicate protection

Expected: Resubmitting identical shipment payloads generates a duplicate transaction error.

Observed: Repeated reservation against same shipment produced HTTP 409.

Evidence: database_evidence.json

### TC-065 — PASS: Consolidated invoicing calculation check

Expected: Weekly account summaries calculate overall shipment totals accurately.

Observed: Actual weekly report reconciled to direct tenant-scoped SQL: 3 packages, GBP 214.36 spend and 27.96 margin, 2026-09-22 through 2026-09-28.

Evidence: post_apply_evidence.json

### TC-066 — PARTIAL: AI Customs Harmonizer text interpretation

Expected: Entering "running leather shoes" successfully predicts the correct HS code card.

Observed: Classifier returns 640399 for running leather shoes, a review-required simulated suggestion; true tariff correctness requires product construction detail. Card presentation only controlled.

Evidence: direct_observations.json; frontend_evidence.json

### TC-067 — PASS: AI Customs confidence rating check

Expected: High-quality inputs render clear match confidence badges.

Observed: Actual Chromium browser: "70% MOCK CONFIDENCE"

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-068 — FAIL: Malformed text description handling

Expected: Entering random text characters defaults to a generic fallback HS code classification.

Observed: Random description abstains with hs_code=null, insufficient_information; does not invent a generic fallback code. This safer behavior conflicts with expected test.

Evidence: direct_observations.json

Specification conflict: no valid universal generic HS code exists for arbitrary random text. Classifier preserves review-required abstention rather than fabricating a commodity code.

### TC-069 — PASS: Inbound exception webhook status update

Expected: Simulating an exception payload from a carrier updates the shipment row status to 'EXCEPTION'.

Observed: Real shipment changed to EXCEPTION and tracking receipt was inserted; transaction rolled back.

Evidence: database_evidence.json

### TC-070 — PASS: Automated AI support ticket creation

Expected: An exception status update automatically triggers a new row in the support tickets table.

Observed: Actual pending tracking event produced one OPEN support ticket; rolled back.

Evidence: database_evidence.json

### TC-071 — PASS: AI summary parsing verification

Expected: The system takes a raw error code like "E_CUSTOMS_40" and translates it into a clear, human-readable summary.

Observed: E_CUSTOMS_40 produces readable customs-clearance review advice via deterministic classifier, not an external LLM.

Evidence: direct_observations.json

### TC-072 — PASS: Manual ticket intervention control

Expected: Clicking "Manually Intervene" changes the ticket status to 'IN_REVIEW'.

Observed: Real ASGI route changed own ticket to IN_REVIEW; rolled back.

Evidence: database_evidence.json

### TC-073 — PASS: AI Invoice Surcharge Auditor matching check

Expected: Uploading an invoice with a mismatched package weight accurately flags an overcharge row.

Observed: Actual stored baseline versus 10kg billed weight and 5.00 excess base charge: weight discrepancy and exact 5.00 overcharge flagged. Weight alone does not invent a monetary charge.

Evidence: database_evidence.json

### TC-074 — PASS: Automated dispute draft generation

Expected: Flagged overcharges generate a ready-to-send claim text template.

Observed: Controlled audit calculated 11.58 overcharge and produced an explicitly unsent dispute draft.

Evidence: core_regression.log test_audit_exact_sums_no_weight_double_count

### TC-075 — PASS: Support ticket tenant isolation verification

Expected: Clients can only see support tickets associated with their own shipments.

Observed: Controlled route tests scope ticket selection/intervention by authenticated tenant; no cross-tenant update.

Evidence: core_regression.log test_client_tickets_and_intervention_scope

### TC-076 — PASS: Ticket counter indicator check

Expected: The client dashboard accurately displays the count of open exceptions.

Observed: One OPEN and one CLOSED test ticket rendered exactly one OPEN EXCEPTION.

Evidence: remediation_frontend_evidence.json

### TC-077 — PASS: Re-route delay predictor execution

Expected: An active exception ticket updates the carrier routing delay matrix.

Observed: Actual exception webhook persisted provider-scoped active_exception metadata; routing reported high risk even without historical delay samples. Delivery clears the exception. No delay duration invented.

Evidence: database_evidence.json; remediation_core_regression.log

### TC-078 — PASS: Text language variation test

Expected: The AI engine parses descriptive inputs accurately regardless of alternative phrasing.

Observed: Executed supported synonyms: leather footwear for jogging → 640399; knitted cotton garment → 610910. Rule-based suggestions still require review. Arbitrary natural language coverage is not claimed.

Evidence: remediation_core_regression.log

### TC-079 — PASS: Proof of Delivery link attachment check

Expected: Successful deliveries correctly save and display the POD URL on the tracking row.

Observed: Actual Chromium browser: {"displayed_https_url": "https://seed-pod.example.invalid/uat.jpg", "scope": "Stored URL linkage; no real carrier signature image fetched"}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-080 — PASS: Ticket history archive logging

Expected: Resolving an exception ticket updates its status to 'CLOSED' and moves it to the archive.

Observed: Actual delivery changed ticket to CLOSED and set archived_at; archive details render closed records.

Evidence: database_evidence.json; remediation_frontend_evidence.json

### TC-081 — PASS: Mobile layout viewport verification

Expected: Interface scales down neatly into a single-column layout on mobile screen widths.

Observed: Actual Chromium browser: {"cols": "343px", "overflow": 0}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-082 — PASS: Desktop layout expansion check

Expected: Widescreen viewports display the side-by-side split columns correctly.

Observed: Actual Chromium browser: [{"x": 258, "y": 301, "width": 575.703125}, {"x": 853.703125, "y": 301, "width": 548.296875}]

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-083 — PASS: Bottom drawer sheet slide interaction

Expected: Clicking "Box Profiles" smoothly reveals the configuration sheet from the bottom on mobile devices.

Observed: Actual Chromium browser: {"x": 0, "y": 121.8125, "width": 375, "height": 690.1875}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-084 — PASS: Backdrop shadow overlay dismissal check

Expected: Tapping outside an open bottom sheet hides the overlay and sheet smoothly.

Observed: Actual Chromium browser: "Real backdrop click dismissed sheet"

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-085 — PASS: Speed quote loader state animation

Expected: Clicking calculate displays a pulsing loading indicator until the rates return.

Observed: Actual Chromium browser: {"animation": "uat-pulse", "finished": true}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-086 — PASS: Client dashboard tab toggle navigation

Expected: Clicking the tabs menu swaps the active viewport cards without reloading the page.

Observed: Actual JavaScript navigation hides/shows panels without a page reload.

Evidence: frontend_evidence.json

### TC-087 — PASS: Admin viewport data view protection

Expected: Client users cannot view or toggle into the Super-Admin view panels.

Observed: Actual controller refused SUPER_ADMIN for CLIENT profile; protected backend macro endpoint denies customer owner.

Evidence: frontend_evidence.json; core_regression.log

### TC-088 — PASS: Data grid element scaling stability

Expected: Resizing the browser window updates chart components without breaking the interface layout.

Observed: Actual Chromium browser: [{"width": 375, "scroll": 375, "charts": [{"width": 343, "scroll": 341}, {"width": 343, "scroll": 341}]}, {"width": 768, "scroll": 768, "charts": [{"width": 500, "scroll": 498}, {"width": 500, "scroll": 498}]}, {"width": 1440, "scroll": 1440, "charts": [{"width": 562, "scroll": 560}, {"width": 562, "scroll": 560}]}]

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-089 — PASS: Custom theme color configuration check

Expected: Dashboard panels apply the predefined dark mode slate theme styles correctly.

Observed: Actual Chromium browser: "rgb(15, 23, 42)"

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-090 — PASS: Micro-copy readability check

Expected: Subheaders and parameters display clearly with correct font sizes.

Observed: Actual Chromium browser: {"minimum_px": 11}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-091 — PASS: Form entry reset button check

Expected: Generating a successful shipment clears out the quoting inputs for the next entry.

Observed: Successful preview dispatch invokes resetQuoteForm; executed reset emptied dimensional/weight fields and invalidated rates. Live purchases remain gated.

Evidence: remediation_frontend_evidence.json

### TC-092 — PASS: Empty state fallback illustration text

Expected: A new workspace with no dispatches shows a clean "No Active Shipments" notification card.

Observed: Actual Chromium browser: "No Active Shipments — no shipments match this view."

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-093 — PASS: Mobile bottom bar icon alignment

Expected: Target layout links maintain uniform spacing across various smartphone screen boundaries.

Observed: Actual Chromium browser: [{"x": 12.25, "width": 48, "height": 46.5}, {"x": 72.75, "width": 48, "height": 46.5}, {"x": 133.25, "width": 48, "height": 46.5}, {"x": 193.75, "width": 48, "height": 46.5}, {"x": 254.25, "width": 48, "height": 46.5}, {"x": 314.75, "width": 48, "height": 46.5}]

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-094 — PASS: Long company text rendering containment

Expected: Extremely long business names wrap neatly within their containers without breaking layout blocks.

Observed: Actual Chromium browser: {"characters": 186, "horizontal_overflow": 0}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-095 — PASS: Action link tap target spacing

Expected: Buttons and interactive links are sized large enough for comfortable finger taps on mobile screens.

Observed: Actual Chromium browser: "All visible controls at least 44px in both dimensions"

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-096 — PASS: Dynamic error container rendering

Expected: Active balance restriction errors display in a bold, notice card style.

Observed: Actual Chromium browser: {"weight": "700", "text": "Insufficient wallet balance"}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-097 — PASS: Analytical graph container box visibility

Expected: Financial summary metric bars align perfectly across comparative intervals.

Observed: Actual Chromium browser: [{"bottom": 1133.4730224609375, "width": 24}, {"bottom": 1133.4730224609375, "width": 24}, {"bottom": 1133.4730224609375, "width": 24}, {"bottom": 1133.4730224609375, "width": 24}, {"bottom": 1133.4730224609375, "width": 24}, {"bottom": 1133.4730224609375, "width": 24}]

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-098 — PASS: Interactive dropdown hover feedback

Expected: Action elements display clear visual hover states on desktop devices.

Observed: Actual Chromium browser: "brightness(1.15)"

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

### TC-099 — PARTIAL: Cross-browser input box rendering

Expected: Input layout parameters display consistently across Chrome, Safari, and Edge.

Observed: Installed Google Chrome, Microsoft Edge, Firefox and Playwright WebKit loaded the real UI with visible weight inputs and zero mobile overflow. Actual Apple Safari on macOS/iOS remains untested; WebKit is not a substitute for Safari release validation.

Evidence: browser/results.json cross_engine

### TC-100 — PASS: Global interface initialization check

Expected: Complete script execution runs flawlessly, with all system icons loading correctly on the initial page load.

Observed: Actual Chromium browser: {"status": "PASS", "page_errors": [], "svg_icons": 21}

Evidence: browser/results.json; browser/mobile.png; browser/desktop.png

## Evidence and reproduction

`remediation_core_regression.log`, `remediation_summary.json`, `database_evidence.json`, `remediation_frontend_evidence.json`, `migration_014_receipt.json`, `post_apply_evidence.json`.

Regenerate this report and rerun core regressions: `.venv/Scripts/python.exe -m tests.report_uat_remediation`.
Rerun real rollback probes: `.venv/Scripts/python.exe -m tests.uat_database_probe`.
Original assessment retained in `results_before_remediation.json`. Frontend DOM tests are `tests/frontend_contract.cjs`; their execution requires Node runtime. Do not rerun the one-time frontend installation scripts.