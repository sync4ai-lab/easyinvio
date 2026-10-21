# Testing and release evidence

Tests establish the behavior they actually exercise. Synthetic provider boundaries are valuable for deterministic contracts and failure paths; they do not certify active carrier contracts, email delivery, production RLS or insurer settlement. Historical UAT reports remain historical records rather than release approvals to be overwritten by a new pass count.

## Verification layers

| Layer | What to verify | Evidence boundary |
| --- | --- | --- |
| Pure calculations/schemas | Exact Decimal scale/rounding, invalid types/nonfinite values, packing/volumetric and customs validation, margin policy | No carrier, wallet reconciliation or deployed database implied |
| Service/HTTP contracts | Auth/tenant/store guards, actual request schema, bounded failures, source connection binding, native response projection | ASGI service fakes are not live provider acceptance |
| Concurrency/idempotency | Same/changed keys, simultaneous booking, submitted uncertainty, capture/release/replay invariants, original return parent fencing | Python mock locks do not replace an authorized real PostgreSQL concurrency test |
| Browser | Personas, login/reset, session cleanup, safe rendering, selection/payment/return controls, disabled actions, responsive layout | Offline network stubs do not establish external delivery or charging |
| Controlled DB sandbox | Actual constraints, role grants, RLS/browser permissions, foreign-tenant rows, transaction/concurrency and migration compatibility | Must use an approved isolated baseline and test fixtures, not a current client workspace |
| External sandbox/staging | Real credentials/modes, quotes, selected-label lifecycle, Stripe events, SMTP OTP/recovery, signatures, stores, insurer workflows and QR retrieval | Each provider’s sandbox contract is specific; some integrations have no verified non-billable purchase mode |
| Product/release UAT | Mandatory feature/security/finance gates, operational recovery, support workflow and product-owner acceptance | An aggregate pass percentage never overrides a failed mandatory gate |

## Safe local commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
& .\.venv\Lib\site-packages\playwright\driver\node.exe tests/frontend_contract.cjs
.\.venv\Scripts\python.exe tests/headless_returns_browser.py
```

Scope pytest to `tests`. Repository-root discovery can collect temporary diagnostics, customer result text or executable probes under output/Archive that were never meant as a safe regression suite. Do not run every `verify_*`, `apply_*`, seed or output script blindly. Some probes contact a configured database/provider or mutate fixtures.

Async API fixtures must deliberately initialize required services or explicitly manage the FastAPI lifespan. `httpx.ASGITransport(app=app)` does not automatically start it. For isolated tests, install controlled service/pool fixtures and scope/restore dependency overrides in finally blocks. A real integration fixture starting background workers requires an approved sandbox, not just a mocked JWT and an existing company UUID.

## Current recorded implementation evidence

The headless-returns implementation at application commit `10b4eef` recorded 907 passing tests, one skipped test and fourteen passing subtests using `pytest tests -q -p no:cacheprovider`. The known TestTopupInput collection warning was present. Offline headless-return browser checks covered authenticated batch submission, exact price ceiling, duplicate-submit UI fencing, QR link rendering, role restriction, mobile layout and identity cleanup; the frontend contract check passed.

This is prior implementation evidence, not a claim that this documentation build reruns all application tests or exercises a live database/provider. Test files and their ownership are indexed in the generated source map/test catalog; new changes must run the checks appropriate to their scope.

## Interpreting the old master matrix

The historical 252 calculator passes represented seven unique input/expectation pairs repeated 36 times. They prove repeatability for those component assertions, not 252 independent end-to-end business scenarios or a concurrent load target. Exact output strings establish the tested penny values; constructing Decimal from an output only proves parseability, not provenance throughout the application.

Earlier HTTP failures included invalid RatingRequest fields, absent lifespan-provided app.state services and incorrect expectations about an unused tenant query parameter. A 503/AttributeError is not a successful carrier integration test. Correct assertions must retain sanitized response details, verify actual meaningful rates, distinct duplicate tiers/order/shortlist behavior and foreign-data exclusion. A len(rates) <= 10 check alone permits zero results.

Tests removed from one revised file do not become passing evidence. Concurrency, volumetric weight, comma normalization, wallet deltas, one-time purchase/capture and actual provider lifecycle coverage must be verified in their real owning tests. Error status assertions should also verify the intended classification/message where it matters.

## Required release acceptance

1. Verify the authorized baseline and applied migrations through 042, exact schema constraints/role grants and safe rollback/backup plan in the target environment.
2. Verify each persona and platform-admin boundary with real authenticated identities; test foreign-tenant/store fixtures and direct database permissions separately. Test assistance attribution and expiry.
3. Verify exact new quote/customer price snapshots, individual global policy versioning, business rules, supported currencies and tax disclosures. AI recommendation failure must preserve priced offers.
4. Exercise successful purchase, definitive rejection, unknown outcome, cancellation and recovery against each authorized carrier program. Demonstrate one financial capture/release and no duplicate label on redelivery.
5. Verify Stripe mode/amount/currency, top-up event replay, exact baskets, customer-paid return handoff and remaining-credit behavior. Do not judge payment by the popup alone.
6. Verify public HTTPS webhook identity and callback URLs; test invalid signatures, replayed IDs and tenant/store/account binding. Confirm email OTP/recovery templates, actual delivery and completed provisioning.
7. Verify customs review and real carrier document download, multi-piece goods allocation, return warehouse version checks, and any supported paperless program at eligible locations. Do not promise universal freight or QR coverage.
8. Where protection is sold, verify the contracted XCover product/pricing/territory and full policy/claim/settlement workflow with approved provider evidence. Estimate-only tests cannot authorize sale.
9. Exercise store and support outbox recovery, credential rotation, worker interruption and operational reconciliation without duplicate messages, purchases or credits.
10. Retain sanitized terminal/JUnit/browser/provider evidence, record known exclusions and obtain explicit product-owner/release authorization. Documentation and a Git push are not that authorization.

## Documentation checks

The architecture generator validates current OpenAPI/source mappings, schema references, chapter links, file hashes, diagrams and distribution parity without applying migrations or running lifespan. Its browser review checks searchable navigation, tables, code blocks, diagrams, links and mobile overflow. For documentation-only changes, diff review and `git diff --check` are the required project checks; application tests are needed if code behavior also changes.

## Queued WhatsApp/PAF change verification, 21 October 2026

The scoped offline regression run passed **222 tests** across test_whatsapp_queue, test_paf_lookup, test_conversation_context, test_conversational_gateway, test_whatsapp_bot, test_sandbox_hooks, test_whatsapp_onboarding, test_whatsapp_ingress, test_agents, test_headless_returns and test_identity, with two existing collection warnings. Compilation and diff checks also passed. Fake DB/HTTP/Twilio services validate empty signed acknowledgement, encrypted events, replay/conflict handling, PAF mapping and both UK endpoints, immutable TTL, media parameters, uncertain/definite send fencing and READY recovery.

No migration, live PAF lookup, carrier purchase, payment or WhatsApp send was executed. These tests do not prove actual PostgreSQL lock contention or the sub-500 ms production latency percentile. Staging acceptance must apply 043, provision licensed PAF, verify actual signature/REST account permissions, measure acknowledgement under load, exercise crash/reconciliation and confirm Twilio can fetch/deliver the signed carrier document.

## EOD manifests and signed media, 21 October 2026

The full tests directory passed **945 tests, one skipped and 14 subtests**, with two existing collection warnings. Compilation and diff checks passed. Synthetic provider/database/Storage/Twilio tests cover role/tenant boundaries, exact totals, replay/competing closes, native membership/document validation, timeout fencing, 1,005 shipments in bounded batches, image sanitization/private signing, and immediate/signed-callback media fallback. A three-page 60-shipment sample PDF was rendered and visually inspected.

No migration, live close-out, Storage upload, payment or message was executed. Staging must verify the actual 044 migration/constraints and lock contention, provider eligibility/label dates, private bucket policies and retention, dependency deployment, signed host reachability and real WhatsApp delivery. A generated internal sheet is never external carrier acceptance evidence.
