# EasyInvio Master Suite UAT Audit — Revision 3

**Technical decision: full UAT sign-off remains withheld.** The supplied run records 252 passing calculator checks and two failing HTTP checks. The calculator checks cover seven distinct input scenarios, each repeated 36 times. This evidence supports limited protection-estimate verification; it does not establish successful staging integration, production readiness or financial stress acceptance.

Review date: 14 October 2026, Europe/London. Application baseline: commit `95ad031`. This report assesses the current user-managed master suite, the local execution log and the attached terminal output. It updates the acceptance assessment in [revision 2](uat_master_suite_audit_2026-10-14_revision_2.md), retaining that report as historical evidence. No human acceptance signature or release authorization is implied.

## Recorded execution

| Measure | Supplied evidence |
| --- | --- |
| Collected tests | 254 |
| Passed | 252 |
| Failed | 2 |
| Duration | 23.99 seconds |
| Aggregate pass percentage | 99.21% |
| Unique calculator input/expectation combinations | 7, repeated 36 times each |
| Successful HTTP acceptance checks | 0 of 2 |

The environment reports Windows, Python 3.14.0, pytest 9.1.1, pluggy 1.6.0, anyio 4.15.1 and pytest-asyncio 1.4.0, with asyncio strict mode. The async tests execute, and the HTTP client uses `ASGITransport` successfully. These resolve earlier runner and client-constructor issues.

Independent review rerun: **252 passed, two deselected in 32.68 seconds**, using the calculator subset only:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_easyinvio_complete_matrix.py -k quantization_and_liability_matrix -q -p no:cacheprovider
```

The two HTTP checks were deliberately excluded from this rerun. No application lifespan, live provider requests or persistent database writes were required for this calculator verification. Its duration is separate from the supplied full-run duration.

The HTTP tests call the imported application in process using `http://test`. They do not send requests to a separately running staging server. The fixture does not enter application lifespan or install the required service objects. The log contains no successful SQL execution, provider transaction identifiers, authenticated staging requests or resource/latency measurements. Consequently, this is not evidence of a completed audit of the actual staging database layer.

Sequentially repeating seven assertions is useful repeatability evidence. It is not 252 independent business scenarios, a concurrency test or a load benchmark. Total pytest duration is not a shipment quotation latency measurement.

## Protection estimate and Decimal assessment

| Declared value GBP | Expected outcome | Recorded repetitions passed |
| --- | --- | --- |
| 20.00 | Premium estimate `1.20` | 36 |
| 120.00 | Premium estimate `1.20` | 36 |
| 120.50 | Premium estimate `1.21` | 36 |
| 5000.00 | Premium estimate `50.00` | 36 |
| 5000.01 | HTTPException status 400 | 36 |
| 0.00 | HTTPException status 400 | 36 |
| -10.00 | HTTPException status 400 | 36 |

These comprise 144 successful-value assertions and 108 expected-rejection checks. An expected rejection passing is a valid boundary result, not a failed test.

The test constructs every calculator input from a string using `Decimal(declared_val)` and calls the production `calculate_xcover_premium` function. That function uses fixed-point Decimal multiplication and `quantize(Decimal('.01'), rounding=ROUND_HALF_UP)`, applying the GBP 1.20 floor and rejecting declared values above GBP 5000 or at/below zero. Exact serialized premium equality verifies the listed penny outcomes, including half-cent rounding to `1.21`.

The assertion `isinstance(Decimal(result['premium_estimate']), Decimal)` only verifies that the returned text can be converted to Decimal. It does not prove the absence of float conversions elsewhere. The exact expected-string assertions provide the useful precision evidence here.

**Limited component result: the seven tested calculator outcomes pass. Perfect application-wide Decimal precision is not established.** The matrix does not exercise direct float/boolean input rejection, malformed text, NaN/infinity, excessive scale, nearby rounding thresholds, currency conversion, provider serialization or database monetary writes. Rejection assertions check HTTP status only, without checking the intended error classification/message.

The estimator is a local arithmetic function. It reports `insured=False`, `available=False`, no confirmed wholesale cost or profit margin, and an internal estimated baseline cost of GBP 0.80. These disclosure fields are not asserted by this matrix. Passing the calculator does not verify an XCover policy purchase, XClaim submission, insurer settlement or permission to charge a protection premium.

## Failure 1: rate evaluation returns HTTP 503

`test_top_10_profit_maximizer_route_ingestion` receives 503 instead of 200. The captured application message is `Rating processing failure`; no response body or underlying exception is recorded.

The current fixture now uses supported `shipment_items` and `goods_currency` fields. The previous 422 request-validation failure has progressed to handler execution. This is an improvement in the fixture, not a successful rate evaluation.

The inspected `/v1/rates` handler accesses `request.app.state.rating`, optionally uses `logistics_supervisor`, and can persist quote snapshots through the rating service pool. The application initializes these services during lifespan. The test fixture only clears dependency overrides and yields the shared application; it does not initialize these services. In a fresh test process, missing rating state is consistent with the generic exception branch that logs this message and returns 503. The supplied log does not reveal the caught exception, so the precise cause is not independently proven by the trace. It must not be reported as an aggregator outage or a margin-calculation failure.

Even after service initialization is corrected, `len(rates) <= 10` permits an empty list and does not prove the required consolidation algorithm. A meaningful deterministic acceptance fixture should contain duplicate carrier/service tiers with different absolute profits and more than ten unique eligible offers. Assertions must verify the retained duplicate winner, price order, expected non-empty shortlist, ten-offer limit, fewer-than-ten behavior and preserved private booking references. AI timeout/failure must preserve deterministic results and monetary values; any recommendation must reference an existing offer.

Use sanitized test failure output containing the response status and response JSON. Capture controlled internal exception diagnostics without exposing tokens, addresses or provider credentials. Replace the current origin postcode with an approved synthetic sandbox address before attempting a provider integration test; passing the request model does not establish carrier address acceptance.

## Failure 2: tenant isolation test never reaches its assertion

`test_cross_tenant_parameter_tampering_isolation_fence` raises `AttributeError: 'State' object has no attribute 'native_partners'`. It does not return the expected 403. The native-orders handler accesses `app.state.native_partners.pool`, which is initialized during application lifespan. `ASGITransport` does not automatically execute that lifespan, and the fixture supplies no substitute service/pool.

There is a second, separate test-design issue: both HTTP tests override the entire `authenticate` dependency. In the current production code, `authenticate` calls `validate_tenant_query`, which rejects a foreign or invalid `tenant_id` query with 403. The test bypasses that guard by substituting a context directly, then reaches the uninitialized route service. The observed exception neither proves a cross-tenant disclosure nor verifies that the production guard works.

This refines the route-contract discussion in revision 2: **the handler itself queries using the verified context tenant, while the current authentication dependency explicitly rejects a mismatched query parameter.** Testing the handler with authentication replaced cannot establish the complete authenticated endpoint contract.

Acceptance needs separate checks for the real authentication/query guard and tenant-scoped repository access. Use distinctive records belonging to two isolated test tenants and verify that foreign rows are absent from the caller's results. Direct database RLS and browser-role grants need their own permission tests; a mocked OWNER context and the backend's trusted database pool do not prove RLS isolation. The client-assistance middleware appearing in the stack is ordinary request traversal and is not evidence that assistance functionality caused this failure.

## Fixture and evidence limitations

| Finding | Assessment and required change |
| --- | --- |
| Dependency cleanup is now inside a fixture | Better than an import-time global override, but `clear()` destroys any pre-existing overrides. Save and restore the prior mapping in `try/finally`. |
| Shared application yielded without state isolation | Required services are absent in this run; other test runs could leave stale state. Install and restore explicit controlled services per test. |
| Existing company tenant ID and random mocked user | Does not represent a verified user membership or dedicated sandbox fixture. Use isolated test identities. |
| No controlled provider quote matrix | Highest-profit duplicate selection, top-ten sorting and AI fallback remain unverified. |
| No transactions or concurrent booking requests | Wallet locks, one-time capture/release, idempotency and balance reconciliation remain unverified. |
| No live provider or insurer evidence | Quote, label, policy, claim and settlement integration acceptance remains pending. |
| No load profile or latency distribution | Throughput, p95/p99 latency, contention and sustained performance cannot be signed off. |

Do not fix the harness simply by starting the full configured application lifecycle against an existing account: startup connects to the database and starts background workers. Component/API tests should use controlled service fixtures. Staging integration tests need deliberate lifecycle management, isolated tenants, TEST provider connections and controlled workers, with mutation and cleanup boundaries specified beforehand.

## Acceptance disposition and next gates

| Acceptance area | Disposition |
| --- | --- |
| Seven specified protection-estimate inputs | Component verification passed |
| Rate consolidation HTTP acceptance | Failed; service/harness initialization unresolved |
| Authenticated tenant isolation and database RLS | Not established; test fails before assertion and bypasses authentication guard |
| Financial transaction integrity and concurrency | Not exercised |
| Multi-provider and insurer integration | Not established |
| Stress/performance acceptance | Not established |
| Overall UAT / application release | Sign-off withheld; product-owner authorization pending |

Required next evidence:

1. Isolate and initialize the HTTP service fixtures, restore shared state correctly, and retain sanitized failure details.
2. Prove consolidation using controlled duplicate and unique offers, including fewer-than-ten results and agent-failure fallback.
3. Exercise the real tenant-query guard separately from context-scoped data queries; verify authenticated cross-tenant API boundaries and direct database permissions.
4. Add distinct Decimal boundary/type cases and protection-availability disclosure assertions.
5. Verify wallet reservation/capture/release, concurrent idempotency and provider booking outcomes in a dedicated sandbox with reconciled records.
6. Rerun the corrected full suite and archive sanitized terminal/JUnit evidence. Define concurrency and latency targets before claiming stress acceptance. Obtain explicit business acceptance after all mandatory gates pass.

## Evidence references and integrity

Reviewed sources: [master suite](../tests/test_easyinvio_complete_matrix.py), [application authentication, rate route and lifespan](../main.py), [native-orders handler](../backend/automation_three_partners.py), [protection estimator](../backend/shipment_protection.py), [isolated fixture guide](../seeds/complete_matrix/README.md).

The [local execution log](../test_results.txt) and attachment `39f893db-5fcc-455c-827b-bd86bd238ce5/Pasted text.txt` both report 254 collected, 252 passed, two failed and 23.99 seconds. Their raw file hashes differ; retain each identity separately. The log does not state an execution date. The review date is not an inferred execution timestamp.

| Artifact | SHA-256 |
| --- | --- |
| Local `test_results.txt` | `0A651C061766802A82691AE67DBFEDF337F959BA7D9BA26DA46C834290D7E514` |
| Attached `Pasted text.txt` | `2CFB7E2F7B8E88C0B779E8B737AF254B9973E1AAD25C5A2AC4C14754EDCD094F` |
| Reviewed master suite | `492602C4A49A2EABD3210CC2CE4CEE3C6A9AF8186165576537622D7E681995D2` |

The master suite and execution log are user-managed, uncommitted artifacts at review time. Hashes identify the reviewed snapshots. This audit does not change tests, application behavior, schemas, credentials or persistent database data.

Technical reviewer disposition: **limited calculator verification; full UAT pending remediation**. Product-owner acceptance: **pending**. Release authorization: **not granted by this report**.
