# EasyInvio Master Suite UAT Audit and Sign Off Decision

**Decision: UAT SIGN-OFF WITHHELD — TEST EXECUTION BLOCKED.** The supplied terminal runs do not establish whether the covered application workflows pass or fail. One run stopped during import; the second collected seven tests but failed to execute their bodies because the required async test runner was absent. Decimal input choices are sound in parts of the file, but this suite does not establish complete financial precision, provider integration or tenant isolation.

Review date: 14 October 2026, Europe/London. Scope: `tests/test_easyinvio_complete_matrix.py`, the attached terminal output, and the production implementations referenced by its assertions. This is a technical acceptance assessment, not a product-owner approval or authorization to release.

## Execution evidence

| Evidence | Recorded result | Interpretation |
| --- | --- | --- |
| Supplied `pytest -v -s tests/test_easyinvio_complete_matrix.py` | Zero tests collected; one collection error; 8.36 seconds | `ModuleNotFoundError: No module named 'main'` blocked import. |
| Supplied `python -m pytest -v -s tests/test_easyinvio_complete_matrix.py` | Seven collected; seven reported failures; seven warnings; 25.42 seconds | Every failure says async functions are unsupported. `pytest.mark.asyncio` is unknown; no test body or business assertion executed. |
| Audit collection check using the project virtual environment | Seven tests collected; seven unknown-async-marker warnings; 11.00 seconds | Confirms the current file imports under the module invocation and still lacks the runner for its chosen marker. Collection alone is not a test pass. |
| Separate audit regression run | 51 passed; 18.34 seconds | Existing margin-optimizer, consolidation, logistics and XCover tests passed. These are separate unit/component checks, not a successful execution of the master suite or live carrier UAT. |

The supplied sessions report Windows, Python 3.14.0, pytest 9.1.1, pluggy 1.6.0 and the anyio 4.15.1 plugin. AnyIO being installed does not activate tests marked `pytest.mark.asyncio`. Merely registering that marker would suppress a warning without providing an async runner.

The file defines **seven executable tests**, despite headings that assign ranges through TC-250. It does not implement 250 cases, a parameterized 250-case matrix, or a stress test with measured throughput. Reported failure rate is 7/7 at the harness stage; the application assertion pass rate is **not determined**.

## Review of each claimed scenario

| Case | Current assertion | Evidence needed for acceptance |
| --- | --- | --- |
| TC-001 — consolidation | HTTP 200, list length at most ten, no three supplier names in `service_code` | Controlled responses from all three adapters, duplicate carrier/service tiers with different absolute margins, verified winning execution record, customer-price ordering, ten-option cap and fewer-than-ten behavior. An empty list satisfies the current length assertion. Check the full client response for private supplier identifiers, not just service names. |
| TC-016 — concurrent booking | At least one response is HTTP 409 | A real prepared offer for the authenticated fixture tenant, simultaneous requests, at most one upstream purchase, exactly one successful ledger capture, correct wallet/reservation deltas, and a consistent replay or conflict result. A random UUID and unrelated tenant cannot exercise the intended purchase lock. |
| TC-044 — volumetric charging | HTTP 200 only | Assert that 50 × 40 × 30 cm produces 12.000 kg volumetric/billable weight at divisor 5000, while actual weight remains 1.500 kg. Inspect the returned weight snapshot and the adapter request. |
| TC-072 — comma normalization | Local string replacement contains `4.5kg` | Call the actual ingestion/parser path with `4,5kg`, verify exact Decimal weight, validated country normalization and missing-field handling. Testing Python's `str.replace` does not test the application. |
| TC-101 — tenant isolation | HTTP 403 for a foreign `tenant_id` query parameter | Use valid authentication for tenant A, create distinctive tenant B data, and assert that no tenant B row is returned. The current native-orders route queries only `context.tenant_id`; it does not consume this query parameter. A successful response containing only A's rows can be correct isolation. Test direct browser database grants/RLS separately from backend tenant-scoped queries. |
| TC-236 — protection floor | Repeated local `max(value × 0.01, 1.20)` arithmetic | Call `calculate_xcover_premium`, verify the £1.20 estimate, currency and unavailable/uninsured flags. A £0.40 estimated difference is not confirmed insurer commission or realized profit. |
| TC-227 — liability cap | Local comparison sets a boolean | Call the production calculator with £6500.00 and assert its actual HTTP 400 exception and message. The current test raises no exception and checks no endpoint response. |

## Decimal precision assessment

The test inputs for dimensions and packed weights use decimal strings, and the two local insurance examples construct `Decimal` from strings rather than floats. Those choices avoid introducing binary floating-point approximations at input construction. They do **not** prove perfect fixed-point behavior through validation, pricing, JSON serialization, database persistence, reservations, captures or refunds.

The production code has stronger controls than this suite verifies:

- `main.decimal_input` rejects float and boolean inputs. `Dimensions` validates Decimal dimensions to two places; packed weights are limited to three places.
- `main.money` quantizes to cents using `ROUND_HALF_UP` within a Decimal context with precision 50.
- `Goods` validates item values and weights using strict decimal parsing and declared precision limits.
- `calculate_xcover_premium` rounds the one-percent calculation to cents before applying the £1.20 minimum. It rejects nonpositive values and values above £5000.00, and returns an estimate rather than proof of paid coverage.
- The existing optimizer regression tests verify that recommendation badges do not change offer order or Decimal customer prices.

The master suite's local premium expression omits cent quantization. For example, declared value £120.50 produces Decimal `1.2050` locally, whereas the production calculator rounds the premium estimate to £1.21. Its single £20.00 example cannot expose that difference. Numeric equality with `Decimal('1.20')` also does not by itself prove a two-place serialized representation.

Required precision cases include £20.00 → £1.20, £120.00 → £1.20, £120.50 → £1.21 and £5000.00 → £50.00, plus rejection of £5000.01, zero, negative, boolean, float, NaN and infinity inputs where prohibited by the relevant interface. Verify exact string/Decimal outputs, half-cent rounding, large valid amounts, and wallet reconciliation before and after success, rejection, timeout and replay. No test should convert money to float to perform its assertion.

## Harness and fixture defects

1. **Async execution is blocked.** `requirements-test.txt` currently supplies pytest, but not pytest-asyncio. Retain `pytest.mark.asyncio` and add a compatible pytest-asyncio development/test dependency, or deliberately migrate the tests to the installed AnyIO runner with `pytest.mark.anyio` and an asyncio backend fixture. The three purely local expression checks could be synchronous functions, although they still need production assertions.
2. **The HTTP client constructor is incompatible with the installed HTTPX API.** Replace `AsyncClient(app=app, ...)` with `AsyncClient(transport=ASGITransport(app=app), ...)`. ASGITransport does not automatically initialize app lifespan. Supply explicit mocked services for isolated tests or a deliberate lifespan fixture for integration tests.
3. **Authentication is never established.** `MOCK_JWT_CLAIMS` is unused, and the bearer string is not a signed JWT. Use scoped test dependency overrides with `TenantContext` for mocked tests; restore them after every test. Use an actual authorized test user's token for sandbox integration tests. Never introduce a production fake-token bypass.
4. **The rating payload does not match the strict request model.** Top-level `item_description` and `item_declared_value` are forbidden fields; use supported `shipment_items` and `goods_currency`. The sample GB postcode is unsuitable for a real carrier address; replace it with a valid fixture address. Do not confuse request-model acceptance with carrier address verification.
5. **Booking references are not prepared.** The booking request names the existing company workspace while the declared mock context names Alpha, and invents an offer ID. Use the same authenticated sandbox tenant throughout quote, preparation and confirmation. SQL fixtures cannot fabricate valid external purchases or a quote's verified private execution context.
6. **Security assertions are too narrow.** A 403 alone does not prove RLS or absence of leaked records. A fake token only exercises authentication failure. Create real foreign fixture rows and verify access through each actual interface and role.
7. **Tests and fixtures are not isolated.** The shallow payload copy currently changes only replaced top-level fields, but future nested mutations would share data; use independent fixtures or deep copies. Scope app-state changes and dependency overrides, restore them reliably, and use transaction rollback for database probes. Keep provider purchases and notifications mocked during unit tests.

These are identified test-design issues. The supplied log does not show that they were reached during execution. They must not be reported as observed carrier, payment or database defects.

## Remediation and acceptance gates

| Gate | Required evidence | Current disposition |
| --- | --- | --- |
| Harness readiness | Tests collected and executed by the selected async runner; working imports/client transport; initialized isolated services | Blocked by supplied log and current collection warnings |
| Fixture readiness | Scoped tenant memberships, valid prepared offers and authentic or explicitly mocked credentials | Master suite does not establish these |
| Functional coverage | Each listed case invokes production behavior and checks the claimed result | Several cases have missing or local-only assertions |
| Financial controls | Exact Decimal pricing, rounding, one capture per booking, release on definitive rejection, reconciliation on uncertain outcomes | Not established by master suite |
| Tenant boundaries | Authenticated role checks, no foreign records returned, direct database access denied where required | Not established by master suite |
| Provider acceptance | Explicit sandbox evidence for quotes, supported bookings, labels, tracking and failure recovery for each enabled provider | Not established by supplied runs |
| Protection acceptance | Estimate/cap validation plus separate authorized policy/claims integration evidence when protection is enabled | Local examples do not establish coverage or settlement |

Fix the harness and fixtures, replace expression-only checks with calls to production services, then rerun the corrected master suite and retain the terminal/JUnit results. Unit success and sandbox provider acceptance should be reported separately. A release decision also needs reviewed coverage, resolution of material failures and explicit product-owner acceptance.

The supplied master-suite rerun command is:

```powershell
.\.venv\Scripts\python.exe -m pytest -v -s tests/test_easyinvio_complete_matrix.py
```

That command will remain blocked until the chosen async runner and subsequent harness issues are corrected. No runner packages, application code, credentials, schemas or test definitions were changed by this audit.

## Separate regression evidence

The audit executed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_margin_optimizer.py tests/test_carrier_consolidation.py tests/test_logistics.py tests/test_xcover_protection.py -q -p no:cacheprovider
```

Result: **51 passed in 18.34 seconds**. This supports the assertions in those existing tests, including controlled Decimal and recommendation behaviors. It cannot be substituted for the seven blocked master-suite tests, a 250-case matrix, an authenticated live provider run or business UAT approval.

## Evidence references and review disposition

Source code: [master suite](../tests/test_easyinvio_complete_matrix.py), [main models and pricing](../main.py), [protection calculator](../backend/shipment_protection.py), [native-order route](../backend/automation_three_partners.py), [goods validation](../backend/automation_freight_engine.py), [fixture setup guide](../seeds/complete_matrix/README.md).

Terminal source: user-supplied `Pasted text.txt`, attachment `3929aed6-8f5f-4b57-b14c-7d41b883a587`. Its execution date is not printed; the review date above is not a claimed execution timestamp. SHA-256: `0001BF37CD01590C9F4DB17D23856EA5986E76F8CB34123D3C213BC1B6933EFC`.

Reviewed suite SHA-256: `FE04A2B703526AE8F795859D88F9177B0D735F140A8093E3F9600F22C56ADD5C`. The file remains a user-managed, uncommitted artifact; this hash identifies the reviewed snapshot.

**Technical disposition:** acceptance pending remediation and executable evidence. **Product-owner sign-off:** pending; no approval inferred. **Release authorization:** not granted by this report.
