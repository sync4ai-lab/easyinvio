# EasyInvio Updated Master Suite UAT Audit and Sign Off Decision

**Full application UAT sign-off remains withheld. The seven tested protection-estimate scenarios pass component verification.** The supplied run reports 252 passes and two failures. The passes exercise seven distinct calculator inputs, repeated 36 times each. The two HTTP checks do not establish successful rate consolidation or tenant isolation. This supports a limited calculator result, not complete financial precision, live insurance integration or release approval.

Review date: 14 October 2026, Europe/London. This assessment replaces the current acceptance disposition from the [first audit](uat_master_suite_audit_2026-10-14.md), which remains historical evidence. Scope: the updated user-managed master test file, the newly supplied terminal log, and its referenced production calculator, request model and native-orders route. Product-owner acceptance and release authorization remain pending.

## Execution results

| Evidence | Result | Scope |
| --- | --- | --- |
| User-supplied full master-suite run | 254 collected; 252 passed; two failed; 29.01 seconds | 252 repeated calculator checks plus two HTTP tests |
| Independent audit calculator rerun | 252 passed; two deselected; 19.57 seconds | Production calculator cases only; the two HTTP tests were deliberately excluded |

The supplied session reports Windows, Python 3.14.0, pytest 9.1.1, pluggy 1.6.0, anyio 4.15.1 and pytest-asyncio 1.4.0, with asyncio strict mode. The prior async-runner blocker is resolved in this run. The updated client uses `ASGITransport`, resolving the previous unsupported `AsyncClient(app=...)` constructor.

Aggregate pass rate is **99.21% (252/254)**. That percentage must not override failed acceptance gates: the two HTTP checks both failed, and the calculator has seven unique input/expectation combinations. Sequential repetition provides repeatability evidence; it does not expand coverage to 252 independent business scenarios or prove a concurrency/load target. Total pytest duration is not a rate-generation or production latency benchmark.

## Calculator results and Decimal precision

The revised tests call the actual `calculate_xcover_premium` implementation. Each scenario below passed 36 times in the supplied run and in the independent calculator rerun.

| Declared value GBP | Expected result | Verified assertion |
| --- | --- | --- |
| 20.00 | Premium estimate 1.20 | Exact output string and GBP currency |
| 120.00 | Premium estimate 1.20 | Exact output string and GBP currency |
| 120.50 | Premium estimate 1.21 | Half-cent premium rounds up to the penny |
| 5000.00 | Premium estimate 50.00 | Exact output at the liability cap |
| 5000.01 | HTTPException status 400 | Value above cap rejected |
| 0.00 | HTTPException status 400 | Zero declared value rejected |
| -15.00 | HTTPException status 400 | Negative declared value rejected |

All seven input values are strings in the scenario table and are converted to `Decimal` before calling the calculator. There is no float construction in these tested input paths. Exact equality between the returned `premium_estimate` and the expected string verifies the tested serialized penny values, including `1.21` for the half-cent case. The production function uses `Decimal`, `quantize(Decimal('.01'), rounding=ROUND_HALF_UP)` and the £1.20 floor.

**Precision conclusion:** the tested floor, cap and half-cent rounding outcomes are correct. Perfect precision across the application is not established. The statement `isinstance(Decimal(result['premium_estimate']), Decimal)` only confirms that constructing a Decimal succeeds; it cannot prove the value's provenance or exclude a float conversion elsewhere. The exact-string assertions are the meaningful checks in the successful cases.

The comments claim float and string boundary coverage, but the function receives only seven Decimal values. Further cases should exercise the actual input boundary with floats, booleans, NaN, infinities, malformed strings and excessive scale where prohibited. Add values immediately below and above the floor and rounding thresholds, supported large values, and exact output-scale checks. Error cases currently assert status only; they do not verify the intended rejection message or classification.

Wallet locks, monetary database columns, reservations, captures, releases, refunds, currency conversion, tax disclosure, provider payload serialization and insurer settlements are outside this matrix. Passing these component tests does not prove those transaction pathways preserve Decimal values or reconcile balances.

## Quote request failure

**Observed:** `test_top_10_profit_maximizer_route_ingestion` receives HTTP 422 instead of its expected 200. The attached trace does not include the response body.

**Code finding:** the supplied fixture still includes top-level `item_description` and `item_declared_value`, which the strict `RatingRequest` does not accept. These fields must be expressed through the supported `shipment_items` structure and goods currency. This is a request-schema mismatch; a 422 is not evidence that any aggregator lost its connection. The fixture's GB postcode also needs replacement with a valid test address before a genuine carrier integration run; that is distinct from the identified extra-field validation issue.

Record a sanitized `response.json()` on failure so the exact validation locations are retained. For deterministic consolidation testing, supply controlled adapter results containing duplicate carrier/service tiers with different margins and more than ten unique eligible options. Then assert the highest-contribution duplicate winner, customer-price order, shortlist size, fewer-than-ten behavior and the preserved private booking reference. `len(rates) <= 10` alone permits an empty list and proves neither sorting nor de-duplication.

The updated suite no longer contains the previous concurrent-booking, volumetric-weight or comma-normalization tests. Their removal must not be reported as those behaviors passing. Separate tests are still required for them and for actual provider quote/label lifecycles.

## Native orders and tenant isolation failure

**Observed:** `test_cross_tenant_parameter_tampering_isolation_fence` raises `AttributeError: 'State' object has no attribute 'native_partners'`. The HTTP request does not produce the expected isolation response.

**Code finding:** `ASGITransport` does not automatically run FastAPI lifespan. The configured startup creates `app.state.native_partners`, but the test neither initializes that lifecycle nor supplies an isolated native-partner service fixture. The inline comment that ASGITransport preserves lifespan execution is incorrect. For an isolated unit/API test, install a controlled service and pool rather than starting background workers against configured external systems. A genuine sandbox integration test needs deliberate lifecycle management and separately controlled workers.

After initialization, the 403 assertion still does not match the current route's contract. The native-orders endpoint queries `WHERE tenant_id=$1` using the authenticated context, and does not consume the supplied `tenant_id` query parameter. A 200 response containing only the caller's rows can be correct behavior. Verify that tenant B has distinctive fixture records and none appear in tenant A's response. If explicit rejection of an unused tenant parameter is a desired product change, specify and test that contract separately; do not infer an RLS defect from the current status expectation.

The file globally overrides `authenticate` at import and returns a privileged context for the existing company workspace. That bypasses JWT verification and membership lookup for these tests. It is acceptable only as explicitly scoped test dependency injection, not as evidence of production authentication or database RLS. Replace the module-level override with a fixture that saves and restores prior overrides, and use isolated test tenant IDs. Otherwise collection can affect other tests in the same Python process, including suites that expect real authentication.

## Remaining coverage and isolation findings

| Finding | Consequence | Required correction |
| --- | --- | --- |
| Seven scenarios multiplied by 36 | Repeated executions are presented as broad stress coverage | Report unique scenarios and repetitions separately; define concurrency, duration and latency targets before a load-test claim |
| Global authentication override without teardown | Shared app state can leak across the full test run | Scope and restore overrides and service fixtures per test |
| Existing company identifiers in mocked context | Test data is not isolated from a real workspace | Use dedicated sandbox fixtures; mock external calls for unit tests |
| No startup/service fixture | Native-orders test cannot reach its database query | Supply a controlled service/pool or an explicitly managed sandbox lifespan |
| Invalid rating fields | Quote endpoint rejects the fixture before successful evaluation | Validate a corrected fixture against `RatingRequest` and retain failure details |
| Calculator-only insurance passes | No policy, claim or settlement is exercised | Keep estimate acceptance separate from authorized XCover/XClaim integration acceptance |
| No foreign rows or direct database access checks | RLS and cross-tenant disclosure are not verified | Create distinctive foreign fixtures and test authenticated API boundaries and browser database permissions separately |

The production estimator returns `insured=False` and `available=False`, with no confirmed wholesale cost or profit margin. Its £0.80 baseline is an internal estimate. The revised matrix does not assert these disclosure flags, commission, tax treatment, policy booking, claim submission or settlement. The file's header claiming verification against active Supabase pools and XCover/XClaim endpoints is unsupported by the recorded tests.

## Acceptance decision and next gates

**Calculator component assessment:** passed for the seven listed inputs and expectations. This is a technical verification result with limited coverage, not an approval to sell shipment protection.

**Full master-suite acceptance:** withheld because two tests fail and their intended operational/security behavior is unverified. **Application release acceptance:** pending authenticated provider, financial and tenant-boundary evidence plus explicit product-owner approval.

To obtain full suite acceptance:

1. Correct and validate the rating fixture, and strengthen assertions to prove the actual consolidation requirements.
2. Initialize isolated application services, scope authentication overrides and replace company identifiers with test fixtures.
3. Test native-orders isolation against the actual route contract using distinctive foreign data; add separate authentication and direct database permission checks.
4. Restore meaningful tests for concurrent booking, volumetric charging and ingestion normalization, and verify wallet deltas and one-time provider purchase/capture behavior.
5. Expand precision coverage to distinct input types and boundaries. Verify estimator availability disclosures separately from policy and settlement workflows.
6. Rerun the corrected full suite, retain sanitized terminal/JUnit evidence, and report unit/component results separately from sandbox provider acceptance. No failed mandatory financial or security gate should be overridden by the aggregate pass percentage.

The independent audit command was:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_easyinvio_complete_matrix.py -k quantization_and_liability_matrix -q -p no:cacheprovider
```

Only the calculator subset was executed independently; its two HTTP tests were excluded. No live provider requests or persistent database writes were required for that subset. The audit does not change application code, tests, dependencies, credentials or schemas.

## Evidence references

Code: [updated master suite](../tests/test_easyinvio_complete_matrix.py), [request model and configured startup](../main.py), [production protection estimator](../backend/shipment_protection.py), [native-orders endpoint](../backend/automation_three_partners.py), [isolated UAT fixture guide](../seeds/complete_matrix/README.md).

Terminal source: `Pasted text.txt`, attachment `86c570fd-b883-4175-a01a-d4a39fdb6a9b`. The log does not print its execution date; 14 October 2026 is the review date. Log SHA-256: `909D0771267939F3398F28510041745F65AF1267A09375BB8F86421A61E7067D`.

Reviewed test-file SHA-256: `4D62A6A9743D471F87FE499058B3F87C778F514E7990074DEA2D704708E97DD4`. The source remains user-managed and uncommitted; the hash identifies this review snapshot.

Technical disposition: **calculator cases verified; full UAT pending remediation**. Product-owner signature: **pending**. Release authorization: **not granted by this assessment**.
