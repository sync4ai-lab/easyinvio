# Requirements to close remaining partial / blocked cases

Most previous blockers were missing test infrastructure, not unavailable Stripe/Twilio/HubSpot integrations. Headless browsers and disposable real Supabase login users now close those gaps. No additional SQL migration is required for the fixes made in this testing pass.

The finance service has been exercised against real PostgreSQL with controlled carrier receipts. Booking/printing end-to-end cases still need a safe test-mode booking adapter (additional feature work) or properly supported carrier TEST integrations. Credentials alone do not bypass the existing sandbox purchase gates.

| Case | Current result | Concrete requirement |
|---|---|---|
| TC-031 | BLOCKED | Activate genuinely credentialed EasyPost TEST and regional TEST carrier accounts. Measure real concurrent rate requests against both; the controlled timeout test completed in about 230ms, but it cannot certify actual upstream latency. |
| TC-051 | PARTIAL | Implement/enable a clearly labelled test-mode booking adapter, or provide valid carrier sandbox access with an approved TEST fulfillment path. Postpaid zero-wallet reservation already passes. Full new-label creation is gated off in the current sandbox configuration. |
| TC-052 | PARTIAL | Same test-mode booking path as TC-051. Real PostgreSQL 100→80 settlement and reserve/capture ledger already pass with controlled provider receipts; end-to-end UI/new carrier label remains unverified. |
| TC-053 | PARTIAL | Same booking adapter; verify exact-funds booking and label response together. Actual PostgreSQL 100→0 settlement already passes. Do not disable production credit/tenant safety checks. |
| TC-056 | PARTIAL | Connect the verified atomic wallet reservation to that sandbox label adapter; run two simultaneous 15.00 bookings on 20.00 and assert exactly one returned label. Current real concurrency test proves one reservation succeeds and one returns 402. |
| TC-060 | PARTIAL | Wire the completed booking-success callback to wallet/dashboard refresh, then test it through the booking adapter. Initial live wallet/manifest state now synchronizes from the actual server; full paid-booking UI trigger is still not exercised. |
| TC-066 | PARTIAL | Supply reviewed expected HS classifications for fully described products (upper/sole material, construction, intended use, tariff version). The mock matcher and actual HS cards are tested; ambiguous text alone cannot establish authoritative customs correctness. |
| TC-099 | PARTIAL | Run the same browser suite on actual macOS/iOS Safari, locally or via a browser-testing service. Installed Chrome/Edge and Firefox/WebKit checks passed; WebKit is not actual Apple Safari. |

The five failed cases are separate specification/implementation gaps documented in RESULTS.md. Stripe test-topup remains intentionally excluded. Test passwords/tokens were held only in memory and all five disposable auth identities were deleted after each real-login run.