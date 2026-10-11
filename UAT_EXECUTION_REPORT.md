# EasyInvio 200-case UAT execution audit

Run UTC: 2026-10-11T14:59:43.971105+00:00

Executed: 200 / 200. Results: {'PASS': 71, 'FAIL': 1, 'PARTIAL': 88, 'BLOCKED': 40}.

**Acceptance rule:** PASS means only the stated scope passed. PARTIAL means controlled contract checks passed but the requested genuine end-to-end workflow is unproven. BLOCKED means a prerequisite or human/provider action prevented execution. No blocked or mocked case is represented as a live integration pass.

The explicit specification ranges contain 35 cases each for A–E and 25 for F. These are used instead of the contradictory phrase “split evenly”.

Sandbox writes: disposable Supabase Auth users/member/session rows were created for genuine password login and removed after execution. Financial database probes roll back their writes. No genuine merchant password, personal-phone message, charge or carrier dispatch was fabricated.

## Live prerequisite checks

```json
{
  "backend_http": 200,
  "sandbox_tenants": 28,
  "active_test_carriers": 0,
  "active_stores": 72,
  "real_password_verified_roles": [
    "OWNER",
    "DISPATCHER",
    "ACCOUNTANT"
  ],
  "stripe_enabled": true,
  "stripe_account_http": 200,
  "twilio_enabled": true,
  "twilio_account_http": 200,
  "hubspot_enabled": false,
  "hubspot_environment": "PRODUCTION",
  "hubspot_provisioning_enabled": false,
  "hubspot_companies_http": 403,
  "disposable_identities_cleaned": true
}
```

Cleanup errors: none.

## Release decision

Not accepted for production: partial/blocked live workflows and any failures require resolution before claiming full readiness.

## Required next actions

- TC-032 is an HTTP rejection contract failure, not an observed tenant leak: foreign tenant query parameters are ignored and own rows returned. Decide whether to explicitly reject tenant override parameters; do not change assertions just to get a green result.
- Configure an active platform-owned EasyPost TEST connection. Native sandbox label purchase is currently fenced in the application, so credentials alone will not unlock the requested real label scenarios.
- Complete a sandbox Stripe Checkout card/payment/callback lifecycle and refund/decline exercises. Account authentication and rolled-back ledger probes are not equivalent to this evidence.
- Provide a genuine HubSpot test account with Companies/Contacts read/write scopes. Current account configuration is PRODUCTION, synchronization/provisioning are disabled, and Companies read access returns 403. Validate the low-credit property requirement separately; current contract coverage does not prove it exists.
- Use the joined WhatsApp sandbox phone for inbound commands and confirm outbound delivery receipts after carriers are enabled. A valid Twilio account response is not a delivered message.
- Complete the 150-order customs review/signature and configure a genuine test storefront before asserting combined native labels and marketplace fulfillment pushback.
- Supplemental browser checks cover login/recovery, navigation, dark-control contrast and exception actions using controlled data; they do not certify every live provider journey. See docs/uat_200/README.md.

## TC-001 · A · missing authorization on /api/v1/shipments/manifest

**Status:** PASS · **Scope:** http · **Time:** 3.91 ms

**Execution steps:**

1. GET /api/v1/shipments/manifest with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-002 · A · malformed authorization on /api/v1/shipments/manifest

**Status:** PASS · **Scope:** http · **Time:** 1.99 ms

**Execution steps:**

1. GET /api/v1/shipments/manifest with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-003 · A · missing authorization on /api/v1/wallet

**Status:** PASS · **Scope:** http · **Time:** 1.89 ms

**Execution steps:**

1. GET /api/v1/wallet with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-004 · A · malformed authorization on /api/v1/wallet

**Status:** PASS · **Scope:** http · **Time:** 1.96 ms

**Execution steps:**

1. GET /api/v1/wallet with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-005 · A · missing authorization on /api/v1/profile

**Status:** PASS · **Scope:** http · **Time:** 2.89 ms

**Execution steps:**

1. GET /api/v1/profile with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-006 · A · malformed authorization on /api/v1/profile

**Status:** PASS · **Scope:** http · **Time:** 5.21 ms

**Execution steps:**

1. GET /api/v1/profile with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-007 · A · missing authorization on /api/v1/admin/tenants

**Status:** PASS · **Scope:** http · **Time:** 2.3 ms

**Execution steps:**

1. GET /api/v1/admin/tenants with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-008 · A · malformed authorization on /api/v1/admin/tenants

**Status:** PASS · **Scope:** http · **Time:** 1.76 ms

**Execution steps:**

1. GET /api/v1/admin/tenants with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-009 · A · missing authorization on /api/v1/admin/margins

**Status:** PASS · **Scope:** http · **Time:** 1.72 ms

**Execution steps:**

1. GET /api/v1/admin/margins with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-010 · A · malformed authorization on /api/v1/admin/margins

**Status:** PASS · **Scope:** http · **Time:** 1.71 ms

**Execution steps:**

1. GET /api/v1/admin/margins with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-011 · A · missing authorization on /api/v1/admin/carriers

**Status:** PASS · **Scope:** http · **Time:** 1.48 ms

**Execution steps:**

1. GET /api/v1/admin/carriers with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-012 · A · malformed authorization on /api/v1/admin/carriers

**Status:** PASS · **Scope:** http · **Time:** 1.49 ms

**Execution steps:**

1. GET /api/v1/admin/carriers with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-013 · A · missing authorization on /api/v1/admin/platform-carriers

**Status:** PASS · **Scope:** http · **Time:** 1.51 ms

**Execution steps:**

1. GET /api/v1/admin/platform-carriers with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-014 · A · malformed authorization on /api/v1/admin/platform-carriers

**Status:** PASS · **Scope:** http · **Time:** 2.76 ms

**Execution steps:**

1. GET /api/v1/admin/platform-carriers with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-015 · A · missing authorization on /api/v1/admin/transactions

**Status:** PASS · **Scope:** http · **Time:** 3.54 ms

**Execution steps:**

1. GET /api/v1/admin/transactions with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-016 · A · malformed authorization on /api/v1/admin/transactions

**Status:** PASS · **Scope:** http · **Time:** 6.83 ms

**Execution steps:**

1. GET /api/v1/admin/transactions with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-017 · A · missing authorization on /api/v1/support/tickets

**Status:** PASS · **Scope:** http · **Time:** 2.91 ms

**Execution steps:**

1. GET /api/v1/support/tickets with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-018 · A · malformed authorization on /api/v1/support/tickets

**Status:** PASS · **Scope:** http · **Time:** 2.96 ms

**Execution steps:**

1. GET /api/v1/support/tickets with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-019 · A · missing authorization on /api/v1/dispatch-workspace/orders

**Status:** PASS · **Scope:** http · **Time:** 3.19 ms

**Execution steps:**

1. GET /api/v1/dispatch-workspace/orders with missing bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-020 · A · malformed authorization on /api/v1/dispatch-workspace/orders

**Status:** PASS · **Scope:** http · **Time:** 3.2 ms

**Execution steps:**

1. GET /api/v1/dispatch-workspace/orders with malformed bearer credentials

**Assertions:** HTTP 401; no tenant records returned.

**Evidence:** Live local API HTTP 401; real Supabase-backed authentication where role specified.

## TC-021 · A · DISPATCHER boundary /api/v1/profile

**Status:** PASS · **Scope:** http · **Time:** 723.76 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/profile with verified app JWT.

**Assertions:** HTTP [200]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 200; real Supabase-backed authentication where role specified.

## TC-022 · A · OWNER boundary /api/v1/profile

**Status:** PASS · **Scope:** http · **Time:** 315.49 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/profile with verified app JWT.

**Assertions:** HTTP [200]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 200; real Supabase-backed authentication where role specified.

## TC-023 · A · ACCOUNTANT boundary /api/v1/profile

**Status:** PASS · **Scope:** http · **Time:** 367.57 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/profile with verified app JWT.

**Assertions:** HTTP [200]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 200; real Supabase-backed authentication where role specified.

## TC-024 · A · DISPATCHER boundary /api/v1/shipments/manifest

**Status:** PASS · **Scope:** http · **Time:** 297.27 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/shipments/manifest with verified app JWT.

**Assertions:** HTTP [200]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 200; real Supabase-backed authentication where role specified.

## TC-025 · A · OWNER boundary /api/v1/shipments/manifest

**Status:** PASS · **Scope:** http · **Time:** 274.29 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/shipments/manifest with verified app JWT.

**Assertions:** HTTP [200]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 200; real Supabase-backed authentication where role specified.

## TC-026 · A · DISPATCHER boundary /api/v1/wallet

**Status:** PASS · **Scope:** http · **Time:** 235.86 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/wallet with verified app JWT.

**Assertions:** HTTP [403]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 403; real Supabase-backed authentication where role specified.

## TC-027 · A · ACCOUNTANT boundary /api/v1/wallet

**Status:** PASS · **Scope:** http · **Time:** 189.03 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/wallet with verified app JWT.

**Assertions:** HTTP [200]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 200; real Supabase-backed authentication where role specified.

## TC-028 · A · DISPATCHER boundary /api/v1/admin/tenants

**Status:** PASS · **Scope:** http · **Time:** 73.26 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/admin/tenants with verified app JWT.

**Assertions:** HTTP [403]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 403; real Supabase-backed authentication where role specified.

## TC-029 · A · OWNER boundary /api/v1/admin/tenants

**Status:** PASS · **Scope:** http · **Time:** 94.25 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/admin/tenants with verified app JWT.

**Assertions:** HTTP [403]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 403; real Supabase-backed authentication where role specified.

## TC-030 · A · ACCOUNTANT boundary /api/v1/admin/transactions

**Status:** PASS · **Scope:** http · **Time:** 79.23 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/admin/transactions with verified app JWT.

**Assertions:** HTTP [403]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 403; real Supabase-backed authentication where role specified.

## TC-031 · A · DISPATCHER boundary /api/v1/admin/platform-carriers

**Status:** PASS · **Scope:** http · **Time:** 68.02 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/admin/platform-carriers with verified app JWT.

**Assertions:** HTTP [403]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 403; real Supabase-backed authentication where role specified.

## TC-032 · A · DISPATCHER boundary /api/v1/shipments/manifest?tenant_id=00000000-0000-4000-8000-000000000001

**Status:** FAIL · **Scope:** http · **Time:** 252.51 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/shipments/manifest?tenant_id=00000000-0000-4000-8000-000000000001 with verified app JWT.

**Assertions:** HTTP [400, 403, 422]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Expected [400, 403, 422], observed HTTP 200; foreign manifest rows=0. Foreign tenant query parameter tested against a real other sandbox tenant.

## TC-033 · A · OWNER boundary /api/v1/automation/customs/00000000-0000-4000-8000-000000000001

**Status:** PASS · **Scope:** http · **Time:** 200.97 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/automation/customs/00000000-0000-4000-8000-000000000001 with verified app JWT.

**Assertions:** HTTP [403, 404]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 404; real Supabase-backed authentication where role specified.

## TC-034 · A · DISPATCHER boundary /api/v1/analytics/reports?start_date=2026-09-01&end_date=2026-10-31

**Status:** PASS · **Scope:** http · **Time:** 95.0 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/analytics/reports?start_date=2026-09-01&end_date=2026-10-31 with verified app JWT.

**Assertions:** HTTP [403]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 403; real Supabase-backed authentication where role specified.

## TC-035 · A · OWNER boundary /api/v1/admin/analytics/dashboard?start_date=2026-09-01&end_date=2026-10-31

**Status:** PASS · **Scope:** http · **Time:** 50.39 ms

**Execution steps:**

1. Provision disposable auth principal and member in an existing synthetic sandbox tenant.
2. POST /api/v1/auth/token with generated password.
3. GET /api/v1/admin/analytics/dashboard?start_date=2026-09-01&end_date=2026-10-31 with verified app JWT.

**Assertions:** HTTP [403]; manifest rows, when returned, must all belong to the authenticated tenant.

**Evidence:** Live local API HTTP 403; real Supabase-backed authentication where role specified.

## TC-036 · B · volumetric and actual

**Status:** PASS · **Scope:** contract · **Time:** 29.39 ms

**Execution steps:**

1. Run isolated existing test test_logistics.MathTests.test_volumetric_and_actual; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_logistics.MathTests.test_volumetric_and_actual; controlled dependencies, no genuine provider transaction.

## TC-037 · B · round up without float

**Status:** PASS · **Scope:** contract · **Time:** 0.14 ms

**Execution steps:**

1. Run isolated existing test test_logistics.MathTests.test_round_up_without_float; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_logistics.MathTests.test_round_up_without_float; controlled dependencies, no genuine provider transaction.

## TC-038 · B · letter and freight matrix

**Status:** PASS · **Scope:** contract · **Time:** 25.84 ms

**Execution steps:**

1. Run isolated existing test test_automation_freight.AutomationTests.test_letter_and_freight_matrix; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_automation_freight.AutomationTests.test_letter_and_freight_matrix; controlled dependencies, no genuine provider transaction.

## TC-039 · B · PARCEL 2.5kg 60x50x40 stackable=True

**Status:** PASS · **Scope:** cargo-positive · **Time:** 0.07 ms

**Execution steps:**

1. Validate Cargo and execute strict Decimal cargo charging.

**Assertions:** Billable weight exactly 24.000 kg.

**Evidence:** Actual Decimal calculation: {'cargo_type': 'PARCEL', 'actual_weight_kg': '2.5', 'volume_m3': '0.12', 'volumetric_weight_kg': '24.00', 'loading_metres': '0', 'floor_weight_kg': '0', 'billable_weight_kg': '24.000', 'basis': 'volumetric', 'tariff_profile': 'EXPRESS_5000', 'kg_per_m3': '333', 'kg_per_loading_metre': '1750', 'deck_width_m': '2.4'}

## TC-040 · B · PARCEL 30kg 60x50x40 stackable=True

**Status:** PASS · **Scope:** cargo-positive · **Time:** 0.07 ms

**Execution steps:**

1. Validate Cargo and execute strict Decimal cargo charging.

**Assertions:** Billable weight exactly 30.000 kg.

**Evidence:** Actual Decimal calculation: {'cargo_type': 'PARCEL', 'actual_weight_kg': '30', 'volume_m3': '0.12', 'volumetric_weight_kg': '24.00', 'loading_metres': '0', 'floor_weight_kg': '0', 'billable_weight_kg': '30.000', 'basis': 'actual', 'tariff_profile': 'EXPRESS_5000', 'kg_per_m3': '333', 'kg_per_loading_metre': '1750', 'deck_width_m': '2.4'}

## TC-041 · B · PARCEL 0.1kg 10.01x10x10 stackable=True

**Status:** PASS · **Scope:** cargo-positive · **Time:** 0.1 ms

**Execution steps:**

1. Validate Cargo and execute strict Decimal cargo charging.

**Assertions:** Billable weight exactly 0.201 kg.

**Evidence:** Actual Decimal calculation: {'cargo_type': 'PARCEL', 'actual_weight_kg': '0.1', 'volume_m3': '0.001001', 'volumetric_weight_kg': '0.200200', 'loading_metres': '0', 'floor_weight_kg': '0', 'billable_weight_kg': '0.201', 'basis': 'volumetric', 'tariff_profile': 'EXPRESS_5000', 'kg_per_m3': '333', 'kg_per_loading_metre': '1750', 'deck_width_m': '2.4'}

## TC-042 · B · LETTER 0.499kg NonexNonexNone stackable=True

**Status:** PASS · **Scope:** cargo-positive · **Time:** 0.06 ms

**Execution steps:**

1. Validate Cargo and execute strict Decimal cargo charging.

**Assertions:** Billable weight exactly 0.499 kg.

**Evidence:** Actual Decimal calculation: {'cargo_type': 'LETTER', 'actual_weight_kg': '0.499', 'billable_weight_kg': '0.499', 'basis': 'actual', 'dimensions_required': False}

## TC-043 · B · LETTER 0.100kg NonexNonexNone stackable=True

**Status:** PASS · **Scope:** cargo-positive · **Time:** 0.06 ms

**Execution steps:**

1. Validate Cargo and execute strict Decimal cargo charging.

**Assertions:** Billable weight exactly 0.100 kg.

**Evidence:** Actual Decimal calculation: {'cargo_type': 'LETTER', 'actual_weight_kg': '0.100', 'billable_weight_kg': '0.100', 'basis': 'actual', 'dimensions_required': False}

## TC-044 · B · PALLET 100kg 120x80x100 stackable=False

**Status:** PASS · **Scope:** cargo-positive · **Time:** 0.08 ms

**Execution steps:**

1. Validate Cargo and execute strict Decimal cargo charging.

**Assertions:** Billable weight exactly 700.000 kg.

**Evidence:** Actual Decimal calculation: {'cargo_type': 'PALLET', 'actual_weight_kg': '100', 'volume_m3': '0.96', 'volumetric_weight_kg': '319.68', 'loading_metres': '0.4', 'floor_weight_kg': '700.0', 'billable_weight_kg': '700.000', 'basis': 'floor', 'tariff_profile': 'CONFIGURED_ROAD_FREIGHT', 'kg_per_m3': '333', 'kg_per_loading_metre': '1750', 'deck_width_m': '2.4'}

## TC-045 · B · PALLET 100kg 120x80x100 stackable=True

**Status:** PASS · **Scope:** cargo-positive · **Time:** 0.1 ms

**Execution steps:**

1. Validate Cargo and execute strict Decimal cargo charging.

**Assertions:** Billable weight exactly 319.680 kg.

**Evidence:** Actual Decimal calculation: {'cargo_type': 'PALLET', 'actual_weight_kg': '100', 'volume_m3': '0.96', 'volumetric_weight_kg': '319.68', 'loading_metres': '0.4', 'floor_weight_kg': '0', 'billable_weight_kg': '319.680', 'basis': 'volumetric', 'tariff_profile': 'CONFIGURED_ROAD_FREIGHT', 'kg_per_m3': '333', 'kg_per_loading_metre': '1750', 'deck_width_m': '2.4'}

## TC-046 · B · OVERLAND_FREIGHT 900kg 200x120x100 stackable=False

**Status:** PASS · **Scope:** cargo-positive · **Time:** 0.07 ms

**Execution steps:**

1. Validate Cargo and execute strict Decimal cargo charging.

**Assertions:** Billable weight exactly 1750.000 kg.

**Evidence:** Actual Decimal calculation: {'cargo_type': 'OVERLAND_FREIGHT', 'actual_weight_kg': '900', 'volume_m3': '2.4', 'volumetric_weight_kg': '799.2', 'loading_metres': '1', 'floor_weight_kg': '1750', 'billable_weight_kg': '1750.000', 'basis': 'floor', 'tariff_profile': 'CONFIGURED_ROAD_FREIGHT', 'kg_per_m3': '333', 'kg_per_loading_metre': '1750', 'deck_width_m': '2.4'}

## TC-047 · B · PARCEL rejects length_cm='0'

**Status:** PASS · **Scope:** cargo · **Time:** 0.06 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-048 · B · PARCEL rejects length_cm='-1'

**Status:** PASS · **Scope:** cargo · **Time:** 0.04 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-049 · B · PARCEL rejects length_cm='alphabetical'

**Status:** PASS · **Scope:** cargo · **Time:** 0.04 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-050 · B · PARCEL rejects length_cm='NaN'

**Status:** PASS · **Scope:** cargo · **Time:** 0.04 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-051 · B · PARCEL rejects length_cm='Infinity'

**Status:** PASS · **Scope:** cargo · **Time:** 0.04 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-052 · B · PARCEL rejects length_cm=True

**Status:** PASS · **Scope:** cargo · **Time:** 0.04 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-053 · B · PARCEL rejects width_cm='0'

**Status:** PASS · **Scope:** cargo · **Time:** 0.04 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-054 · B · PARCEL rejects width_cm='-1'

**Status:** PASS · **Scope:** cargo · **Time:** 0.04 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-055 · B · PARCEL rejects width_cm='alphabetical'

**Status:** PASS · **Scope:** cargo · **Time:** 0.03 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-056 · B · PARCEL rejects width_cm='NaN'

**Status:** PASS · **Scope:** cargo · **Time:** 0.03 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-057 · B · PARCEL rejects width_cm='Infinity'

**Status:** PASS · **Scope:** cargo · **Time:** 0.03 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-058 · B · PARCEL rejects width_cm=True

**Status:** PASS · **Scope:** cargo · **Time:** 0.03 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-059 · B · PARCEL rejects height_cm='0'

**Status:** PASS · **Scope:** cargo · **Time:** 0.05 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-060 · B · PARCEL rejects height_cm='-1'

**Status:** PASS · **Scope:** cargo · **Time:** 0.03 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-061 · B · PARCEL rejects height_cm='alphabetical'

**Status:** PASS · **Scope:** cargo · **Time:** 0.03 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-062 · B · PARCEL rejects height_cm='NaN'

**Status:** PASS · **Scope:** cargo · **Time:** 0.03 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-063 · B · PARCEL rejects height_cm='Infinity'

**Status:** PASS · **Scope:** cargo · **Time:** 0.03 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-064 · B · PARCEL rejects height_cm=True

**Status:** PASS · **Scope:** cargo · **Time:** 0.03 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-065 · B · PARCEL rejects actual_weight_kg='0'

**Status:** PASS · **Scope:** cargo · **Time:** 0.04 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-066 · B · PARCEL rejects actual_weight_kg='-1'

**Status:** PASS · **Scope:** cargo · **Time:** 0.09 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-067 · B · PARCEL rejects actual_weight_kg='alphabetical'

**Status:** PASS · **Scope:** cargo · **Time:** 0.05 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-068 · B · PARCEL rejects actual_weight_kg='NaN'

**Status:** PASS · **Scope:** cargo · **Time:** 0.07 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-069 · B · PARCEL rejects actual_weight_kg='Infinity'

**Status:** PASS · **Scope:** cargo · **Time:** 0.05 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-070 · B · PARCEL rejects actual_weight_kg=True

**Status:** PASS · **Scope:** cargo · **Time:** 0.05 ms

**Execution steps:**

1. Validate Cargo input and calculate Decimal charge if validation permits it.

**Assertions:** Invalid dimension/weight rejected; no float or NaN enters pricing.

**Evidence:** Invalid cargo rejected by actual application model/Decimal calculation.

## TC-071 · C · new route metadata redirects and status

**Status:** PARTIAL · **Scope:** contract · **Time:** 55.73 ms

**Execution steps:**

1. Run isolated existing test test_payment_gateway.PaymentTests.test_new_route_metadata_redirects_and_status; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_payment_gateway.PaymentTests.test_new_route_metadata_redirects_and_status; controlled dependencies, no genuine provider transaction.

## TC-072 · C · signed event credits once and rejects tampering

**Status:** PARTIAL · **Scope:** contract · **Time:** 30.3 ms

**Execution steps:**

1. Run isolated existing test test_payment_gateway.PaymentTests.test_signed_event_credits_once_and_rejects_tampering; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_payment_gateway.PaymentTests.test_signed_event_credits_once_and_rejects_tampering; controlled dependencies, no genuine provider transaction.

## TC-073 · C · concurrent events sum and replay only once

**Status:** PARTIAL · **Scope:** contract · **Time:** 20.49 ms

**Execution steps:**

1. Run isolated existing test test_payment_gateway.PaymentTests.test_concurrent_events_sum_and_replay_only_once; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_payment_gateway.PaymentTests.test_concurrent_events_sum_and_replay_only_once; controlled dependencies, no genuine provider transaction.

## TC-074 · C · ledger failure rolls back balance and status

**Status:** PARTIAL · **Scope:** contract · **Time:** 9.28 ms

**Execution steps:**

1. Run isolated existing test test_payment_gateway.PaymentTests.test_ledger_failure_rolls_back_balance_and_status; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_payment_gateway.PaymentTests.test_ledger_failure_rolls_back_balance_and_status; controlled dependencies, no genuine provider transaction.

## TC-075 · C · wrong amount customer currency and unpaid

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.38 ms

**Execution steps:**

1. Run isolated existing test test_payment_gateway.PaymentTests.test_wrong_amount_customer_currency_and_unpaid; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_payment_gateway.PaymentTests.test_wrong_amount_customer_currency_and_unpaid; controlled dependencies, no genuine provider transaction.

## TC-076 · C · role tenant mode and decimal boundaries

**Status:** PARTIAL · **Scope:** contract · **Time:** 22.1 ms

**Execution steps:**

1. Run isolated existing test test_payment_gateway.PaymentTests.test_role_tenant_mode_and_decimal_boundaries; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_payment_gateway.PaymentTests.test_role_tenant_mode_and_decimal_boundaries; controlled dependencies, no genuine provider transaction.

## TC-077 · C · missing customer is provisioned without row locks

**Status:** PARTIAL · **Scope:** contract · **Time:** 15.79 ms

**Execution steps:**

1. Run isolated existing test test_payment_gateway.PaymentTests.test_missing_customer_is_provisioned_without_row_locks; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_payment_gateway.PaymentTests.test_missing_customer_is_provisioned_without_row_locks; controlled dependencies, no genuine provider transaction.

## TC-078 · C · credit success state intent and stored url

**Status:** PARTIAL · **Scope:** contract · **Time:** 11.26 ms

**Execution steps:**

1. Run isolated existing test test_stripe_snapshots.SnapshotTests.test_credit_success_state_intent_and_stored_url; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_stripe_snapshots.SnapshotTests.test_credit_success_state_intent_and_stored_url; controlled dependencies, no genuine provider transaction.

## TC-079 · C · cumulative partial refunds replays and out of order

**Status:** PARTIAL · **Scope:** contract · **Time:** 11.83 ms

**Execution steps:**

1. Run isolated existing test test_stripe_snapshots.SnapshotTests.test_cumulative_partial_refunds_replays_and_out_of_order; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_stripe_snapshots.SnapshotTests.test_cumulative_partial_refunds_replays_and_out_of_order; controlled dependencies, no genuine provider transaction.

## TC-080 · C · concurrent refund events do not double debit

**Status:** PARTIAL · **Scope:** contract · **Time:** 16.44 ms

**Execution steps:**

1. Run isolated existing test test_stripe_snapshots.SnapshotTests.test_concurrent_refund_events_do_not_double_debit; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_stripe_snapshots.SnapshotTests.test_concurrent_refund_events_do_not_double_debit; controlled dependencies, no genuine provider transaction.

## TC-081 · C · refund respects reserved money and holds workspace

**Status:** PARTIAL · **Scope:** contract · **Time:** 9.92 ms

**Execution steps:**

1. Run isolated existing test test_stripe_snapshots.SnapshotTests.test_refund_respects_reserved_money_and_holds_workspace; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_stripe_snapshots.SnapshotTests.test_refund_respects_reserved_money_and_holds_workspace; controlled dependencies, no genuine provider transaction.

## TC-082 · C · failed charge maps pending intent but never downgrades paid

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.29 ms

**Execution steps:**

1. Run isolated existing test test_stripe_snapshots.SnapshotTests.test_failed_charge_maps_pending_intent_but_never_downgrades_paid; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_stripe_snapshots.SnapshotTests.test_failed_charge_maps_pending_intent_but_never_downgrades_paid; controlled dependencies, no genuine provider transaction.

## TC-083 · C · cross tenant or wrong amount refunds never debit

**Status:** PARTIAL · **Scope:** contract · **Time:** 14.08 ms

**Execution steps:**

1. Run isolated existing test test_stripe_snapshots.SnapshotTests.test_cross_tenant_or_wrong_amount_refunds_never_debit; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_stripe_snapshots.SnapshotTests.test_cross_tenant_or_wrong_amount_refunds_never_debit; controlled dependencies, no genuine provider transaction.

## TC-084 · C · process failure is durable and returns 200

**Status:** PARTIAL · **Scope:** contract · **Time:** 16.71 ms

**Execution steps:**

1. Run isolated existing test test_stripe_snapshots.SnapshotTests.test_process_failure_is_durable_and_returns_200; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_stripe_snapshots.SnapshotTests.test_process_failure_is_durable_and_returns_200; controlled dependencies, no genuine provider transaction.

## TC-085 · C · receipt storage outage returns retryable 503

**Status:** PARTIAL · **Scope:** contract · **Time:** 14.77 ms

**Execution steps:**

1. Run isolated existing test test_stripe_snapshots.SnapshotTests.test_receipt_storage_outage_returns_retryable_503; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_stripe_snapshots.SnapshotTests.test_receipt_storage_outage_returns_retryable_503; controlled dependencies, no genuine provider transaction.

## TC-086 · C · signature exact scope snapshot and collision

**Status:** PARTIAL · **Scope:** contract · **Time:** 18.74 ms

**Execution steps:**

1. Run isolated existing test test_stripe_snapshots.SnapshotTests.test_signature_exact_scope_snapshot_and_collision; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_stripe_snapshots.SnapshotTests.test_signature_exact_scope_snapshot_and_collision; controlled dependencies, no genuine provider transaction.

## TC-087 · C · 100 credit and idempotent retry

**Status:** PARTIAL · **Scope:** contract · **Time:** 31.23 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.BillingTests.test_100_credit_and_idempotent_retry; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.BillingTests.test_100_credit_and_idempotent_retry; controlled dependencies, no genuine provider transaction.

## TC-088 · C · concurrent retries credit only once

**Status:** PARTIAL · **Scope:** contract · **Time:** 23.83 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.BillingTests.test_concurrent_retries_credit_only_once; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.BillingTests.test_concurrent_retries_credit_only_once; controlled dependencies, no genuine provider transaction.

## TC-089 · C · live keys and unmarked tenants rejected before stripe

**Status:** PARTIAL · **Scope:** contract · **Time:** 7.84 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.BillingTests.test_live_keys_and_unmarked_tenants_rejected_before_stripe; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.BillingTests.test_live_keys_and_unmarked_tenants_rejected_before_stripe; controlled dependencies, no genuine provider transaction.

## TC-090 · C · decline and wrong stripe response never credit

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.7 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.BillingTests.test_decline_and_wrong_stripe_response_never_credit; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.BillingTests.test_decline_and_wrong_stripe_response_never_credit; controlled dependencies, no genuine provider transaction.

## TC-091 · C · zero balance blocks actual label and booking guards

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.39 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.BillingTests.test_zero_balance_blocks_actual_label_and_booking_guards; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.BillingTests.test_zero_balance_blocks_actual_label_and_booking_guards; controlled dependencies, no genuine provider transaction.

## TC-092 · C · funded label is sample without charge

**Status:** PARTIAL · **Scope:** contract · **Time:** 9.17 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.BillingTests.test_funded_label_is_sample_without_charge; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.BillingTests.test_funded_label_is_sample_without_charge; controlled dependencies, no genuine provider transaction.

## TC-093 · C · sandbox cannot submit carrier purchase

**Status:** PARTIAL · **Scope:** contract · **Time:** 7.97 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.BillingTests.test_sandbox_cannot_submit_carrier_purchase; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.BillingTests.test_sandbox_cannot_submit_carrier_purchase; controlled dependencies, no genuine provider transaction.

## TC-094 · C · failed ledger rolls back and retry reconciles same payment

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.76 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.BillingTests.test_failed_ledger_rolls_back_and_retry_reconciles_same_payment; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.BillingTests.test_failed_ledger_rolls_back_and_retry_reconciles_same_payment; controlled dependencies, no genuine provider transaction.

## TC-095 · C · missing customer is created in test mode

**Status:** PARTIAL · **Scope:** contract · **Time:** 9.1 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.BillingTests.test_missing_customer_is_created_in_test_mode; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.BillingTests.test_missing_customer_is_created_in_test_mode; controlled dependencies, no genuine provider transaction.

## TC-096 · C · Real sandbox database dispatcher_wallet_lock_probe.py

**Status:** PASS · **Scope:** probe · **Time:** 1770.75 ms

**Execution steps:**

1. Run tests/dispatcher_wallet_lock_probe.py against configured Supabase with transactions rolled back.

**Assertions:** Process exits 0; real lock/financial assertions pass; no fixture balance persists.

**Evidence:** Real Supabase probe assertions passed; all mutations rolled back: dispatcher_wallet_lock_probe.py

## TC-097 · C · Real sandbox database stripe_snapshot_database_probe.py

**Status:** PASS · **Scope:** probe · **Time:** 6204.87 ms

**Execution steps:**

1. Run tests/stripe_snapshot_database_probe.py against configured Supabase with transactions rolled back.

**Assertions:** Process exits 0; real lock/financial assertions pass; no fixture balance persists.

**Evidence:** Real Supabase probe assertions passed; all mutations rolled back: stripe_snapshot_database_probe.py

## TC-098 · C · Funded 1000 GBP wallet purchases 15 GBP native label

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.02 ms

**Execution steps:**

1. Check sandbox readiness for genuine carrier purchase and real card callback.

**Assertions:** Requires genuine native label purchase or customer/card action; contract tests do not prove this workflow.

**Evidence:** Active TEST carriers=0; native sandbox purchases are fenced; genuine card completion/store dispatch not executed.

## TC-099 · C · 10 GBP wallet blocks 12 GBP native purchase before carrier

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Check sandbox readiness for genuine carrier purchase and real card callback.

**Assertions:** Requires genuine native label purchase or customer/card action; contract tests do not prove this workflow.

**Evidence:** Active TEST carriers=0; native sandbox purchases are fenced; genuine card completion/store dispatch not executed.

## TC-100 · C · Ten identical concurrent native purchases produce one label

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Check sandbox readiness for genuine carrier purchase and real card callback.

**Assertions:** Requires genuine native label purchase or customer/card action; contract tests do not prove this workflow.

**Evidence:** Active TEST carriers=0; native sandbox purchases are fenced; genuine card completion/store dispatch not executed.

## TC-101 · C · Real Stripe Checkout card authorization and completion callback

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Check sandbox readiness for genuine carrier purchase and real card callback.

**Assertions:** Requires genuine native label purchase or customer/card action; contract tests do not prove this workflow.

**Evidence:** Active TEST carriers=0; native sandbox purchases are fenced; genuine card completion/store dispatch not executed.

## TC-102 · C · Real charge refund reconciles wallet debit

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Check sandbox readiness for genuine carrier purchase and real card callback.

**Assertions:** Requires genuine native label purchase or customer/card action; contract tests do not prove this workflow.

**Evidence:** Active TEST carriers=0; native sandbox purchases are fenced; genuine card completion/store dispatch not executed.

## TC-103 · C · Real declined card changes pending topup to FAILED

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Check sandbox readiness for genuine carrier purchase and real card callback.

**Assertions:** Requires genuine native label purchase or customer/card action; contract tests do not prove this workflow.

**Evidence:** Active TEST carriers=0; native sandbox purchases are fenced; genuine card completion/store dispatch not executed.

## TC-104 · C · Webhook replay over public Stripe delivery produces one credit

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Check sandbox readiness for genuine carrier purchase and real card callback.

**Assertions:** Requires genuine native label purchase or customer/card action; contract tests do not prove this workflow.

**Evidence:** Active TEST carriers=0; native sandbox purchases are fenced; genuine card completion/store dispatch not executed.

## TC-105 · C · Real delayed callback eventually reconciles paid wallet

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Check sandbox readiness for genuine carrier purchase and real card callback.

**Assertions:** Requires genuine native label purchase or customer/card action; contract tests do not prove this workflow.

**Evidence:** Active TEST carriers=0; native sandbox purchases are fenced; genuine card completion/store dispatch not executed.

## TC-106 · D · companies contacts onboard without deal configuration

**Status:** PARTIAL · **Scope:** contract · **Time:** 18.09 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_companies_contacts_onboard_without_deal_configuration; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_companies_contacts_onboard_without_deal_configuration; controlled dependencies, no genuine provider transaction.

## TC-107 · D · account mismatch and standard account block before writes

**Status:** PARTIAL · **Scope:** contract · **Time:** 15.32 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_account_mismatch_and_standard_account_block_before_writes; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_account_mismatch_and_standard_account_block_before_writes; controlled dependencies, no genuine provider transaction.

## TC-108 · D · property type and ambiguous create fail securely

**Status:** PARTIAL · **Scope:** contract · **Time:** 15.57 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_property_type_and_ambiguous_create_fail_securely; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_property_type_and_ambiguous_create_fail_securely; controlled dependencies, no genuine provider transaction.

## TC-109 · D · environment placeholder and secret validation

**Status:** PARTIAL · **Scope:** contract · **Time:** 12.59 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_environment_placeholder_and_secret_validation; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_environment_placeholder_and_secret_validation; controlled dependencies, no genuine provider transaction.

## TC-110 · D · onboarding replay and same company names distinct tenants

**Status:** PARTIAL · **Scope:** contract · **Time:** 14.95 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_onboarding_replay_and_same_company_names_distinct_tenants; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_onboarding_replay_and_same_company_names_distinct_tenants; controlled dependencies, no genuine provider transaction.

## TC-111 · D · milestone exact decimal threshold and single upsell

**Status:** PARTIAL · **Scope:** contract · **Time:** 14.27 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_milestone_exact_decimal_threshold_and_single_upsell; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_milestone_exact_decimal_threshold_and_single_upsell; controlled dependencies, no genuine provider transaction.

## TC-112 · D · rate limit backoff and retry after

**Status:** PARTIAL · **Scope:** contract · **Time:** 9.96 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_rate_limit_backoff_and_retry_after; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_rate_limit_backoff_and_retry_after; controlled dependencies, no genuine provider transaction.

## TC-113 · D · long rate limit deferred and no secret errors

**Status:** PARTIAL · **Scope:** contract · **Time:** 8.94 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_long_rate_limit_deferred_and_no_secret_errors; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_long_rate_limit_deferred_and_no_secret_errors; controlled dependencies, no genuine provider transaction.

## TC-114 · D · authentication failure is not retried

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.95 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_authentication_failure_is_not_retried; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_authentication_failure_is_not_retried; controlled dependencies, no genuine provider transaction.

## TC-115 · D · unique properties required before creating records

**Status:** PARTIAL · **Scope:** contract · **Time:** 9.07 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_unique_properties_required_before_creating_records; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_unique_properties_required_before_creating_records; controlled dependencies, no genuine provider transaction.

## TC-116 · D · decimal validation and retry headers

**Status:** PARTIAL · **Scope:** contract · **Time:** 7.41 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_decimal_validation_and_retry_headers; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_decimal_validation_and_retry_headers; controlled dependencies, no genuine provider transaction.

## TC-117 · D · queued endpoint tenant role and disabled checks

**Status:** PARTIAL · **Scope:** contract · **Time:** 18.47 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_queued_endpoint_tenant_role_and_disabled_checks; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_queued_endpoint_tenant_role_and_disabled_checks; controlled dependencies, no genuine provider transaction.

## TC-118 · D · service uses tenant totals and blocks mixed currency

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.0 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_service_uses_tenant_totals_and_blocks_mixed_currency; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_service_uses_tenant_totals_and_blocks_mixed_currency; controlled dependencies, no genuine provider transaction.

## TC-119 · D · worker persists delivery and preserves new revision

**Status:** PARTIAL · **Scope:** contract · **Time:** 8.37 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_worker_persists_delivery_and_preserves_new_revision; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_worker_persists_delivery_and_preserves_new_revision; controlled dependencies, no genuine provider transaction.

## TC-120 · D · worker blocks permanent failure and unlocks

**Status:** PARTIAL · **Scope:** contract · **Time:** 8.95 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_crm.HubSpotTests.test_worker_blocks_permanent_failure_and_unlocks; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_crm.HubSpotTests.test_worker_blocks_permanent_failure_and_unlocks; controlled dependencies, no genuine provider transaction.

## TC-121 · D · metrics exact and legacy compatible

**Status:** PARTIAL · **Scope:** contract · **Time:** 14.72 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_activation.ActivationTests.test_metrics_exact_and_legacy_compatible; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_activation.ActivationTests.test_metrics_exact_and_legacy_compatible; controlled dependencies, no genuine provider transaction.

## TC-122 · D · inbound company is reused on sync

**Status:** PARTIAL · **Scope:** contract · **Time:** 11.73 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_activation.ActivationTests.test_inbound_company_is_reused_on_sync; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_activation.ActivationTests.test_inbound_company_is_reused_on_sync; controlled dependencies, no genuine provider transaction.

## TC-123 · D · signature raw body timestamp and url integrity

**Status:** PARTIAL · **Scope:** contract · **Time:** 6.64 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_activation.ActivationTests.test_signature_raw_body_timestamp_and_url_integrity; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_activation.ActivationTests.test_signature_raw_body_timestamp_and_url_integrity; controlled dependencies, no genuine provider transaction.

## TC-124 · D · association ambiguity and paging rejected

**Status:** PARTIAL · **Scope:** contract · **Time:** 8.71 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_activation.ActivationTests.test_association_ambiguity_and_paging_rejected; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_activation.ActivationTests.test_association_ambiguity_and_paging_rejected; controlled dependencies, no genuine provider transaction.

## TC-125 · D · provisioning configuration requires separate app credentials

**Status:** PARTIAL · **Scope:** contract · **Time:** 9.22 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_activation.ActivationTests.test_provisioning_configuration_requires_separate_app_credentials; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_activation.ActivationTests.test_provisioning_configuration_requires_separate_app_credentials; controlled dependencies, no genuine provider transaction.

## TC-126 · D · signed webhook queues only correct account and stage

**Status:** PARTIAL · **Scope:** contract · **Time:** 16.69 ms

**Execution steps:**

1. Run isolated existing test test_hubspot_activation.ActivationTests.test_signed_webhook_queues_only_correct_account_and_stage; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_hubspot_activation.ActivationTests.test_signed_webhook_queues_only_correct_account_and_stage; controlled dependencies, no genuine provider transaction.

## TC-127 · D · New tenant Company creation

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-128 · D · Primary Contact creation

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-129 · D · Contact to Company association

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-130 · D · Company reference persisted to Supabase

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-131 · D · Lifetime parcel count PATCH

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-132 · D · Lifetime spend PATCH

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-133 · D · Wallet balance PATCH

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-134 · D · Low-credit company lifecycle property

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-135 · D · Closed-won webhook authentication

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-136 · D · Closed-won workspace provisioning

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-137 · D · Closed-won empty wallet creation

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-138 · D · HubSpot 429 eventual delivery

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-139 · D · CRM event replay deduplication

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-140 · D · Non-blocking sync while labels finalize

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read live HubSpot settings and companies API scope readiness.

**Assertions:** Real CRM object mutation and matching local state required.

**Evidence:** HubSpot enabled=False; companies endpoint HTTP=403; genuine CRM lifecycle writes not executed.

## TC-141 · E · signed query exact decimal pricing and duplicate receipt

**Status:** PARTIAL · **Scope:** contract · **Time:** 12.69 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_bot.ConversationalWebhookTests.test_signed_query_exact_decimal_pricing_and_duplicate_receipt; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_bot.ConversationalWebhookTests.test_signed_query_exact_decimal_pricing_and_duplicate_receipt; controlled dependencies, no genuine provider transaction.

## TC-142 · E · funded and postpaid accounts do not get zero wallet warning

**Status:** PARTIAL · **Scope:** contract · **Time:** 7.62 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_bot.ConversationalWebhookTests.test_funded_and_postpaid_accounts_do_not_get_zero_wallet_warning; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_bot.ConversationalWebhookTests.test_funded_and_postpaid_accounts_do_not_get_zero_wallet_warning; controlled dependencies, no genuine provider transaction.

## TC-143 · E · reserved credit cannot be promised for booking

**Status:** PARTIAL · **Scope:** contract · **Time:** 4.28 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_bot.ConversationalWebhookTests.test_reserved_credit_cannot_be_promised_for_booking; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_bot.ConversationalWebhookTests.test_reserved_credit_cannot_be_promised_for_booking; controlled dependencies, no genuine provider transaction.

## TC-144 · E · unconfigured booking page has no placeholder link

**Status:** PARTIAL · **Scope:** contract · **Time:** 3.74 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_bot.ConversationalWebhookTests.test_unconfigured_booking_page_has_no_placeholder_link; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_bot.ConversationalWebhookTests.test_unconfigured_booking_page_has_no_placeholder_link; controlled dependencies, no genuine provider transaction.

## TC-145 · E · wrong canonical url and disabled integration

**Status:** PARTIAL · **Scope:** contract · **Time:** 5.51 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_bot.ConversationalWebhookTests.test_wrong_canonical_url_and_disabled_integration; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_bot.ConversationalWebhookTests.test_wrong_canonical_url_and_disabled_integration; controlled dependencies, no genuine provider transaction.

## TC-146 · E · long replies are split without breaking booking links

**Status:** PARTIAL · **Scope:** contract · **Time:** 0.22 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_bot.FormatterTests.test_long_replies_are_split_without_breaking_booking_links; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_bot.FormatterTests.test_long_replies_are_split_without_breaking_booking_links; controlled dependencies, no genuine provider transaction.

## TC-147 · E · xml escaping three offers decimal format

**Status:** PARTIAL · **Scope:** contract · **Time:** 0.22 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_bot.FormatterTests.test_xml_escaping_three_offers_decimal_format; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_bot.FormatterTests.test_xml_escaping_three_offers_decimal_format; controlled dependencies, no genuine provider transaction.

## TC-148 · E · unconfigured initialization warns without secret

**Status:** PARTIAL · **Scope:** contract · **Time:** 1.49 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_bot.FormatterTests.test_unconfigured_initialization_warns_without_secret; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_bot.FormatterTests.test_unconfigured_initialization_warns_without_secret; controlled dependencies, no genuine provider transaction.

## TC-149 · E · signed query exact decimal pricing and duplicate receipt

**Status:** PARTIAL · **Scope:** contract · **Time:** 6.96 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.WhatsAppTests.test_signed_query_exact_decimal_pricing_and_duplicate_receipt; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.WhatsAppTests.test_signed_query_exact_decimal_pricing_and_duplicate_receipt; controlled dependencies, no genuine provider transaction.

## TC-150 · E · invalid signature never reads tenant data

**Status:** PARTIAL · **Scope:** contract · **Time:** 4.0 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.WhatsAppTests.test_invalid_signature_never_reads_tenant_data; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.WhatsAppTests.test_invalid_signature_never_reads_tenant_data; controlled dependencies, no genuine provider transaction.

## TC-151 · E · signed structural failures

**Status:** PARTIAL · **Scope:** contract · **Time:** 14.85 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.WhatsAppTests.test_signed_structural_failures; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.WhatsAppTests.test_signed_structural_failures; controlled dependencies, no genuine provider transaction.

## TC-152 · E · wrong account receiver and unbound phone

**Status:** PARTIAL · **Scope:** contract · **Time:** 7.82 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.WhatsAppTests.test_wrong_account_receiver_and_unbound_phone; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.WhatsAppTests.test_wrong_account_receiver_and_unbound_phone; controlled dependencies, no genuine provider transaction.

## TC-153 · E · media returns text instruction and bad iso returns help

**Status:** PARTIAL · **Scope:** contract · **Time:** 6.55 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.WhatsAppTests.test_media_returns_text_instruction_and_bad_iso_returns_help; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.WhatsAppTests.test_media_returns_text_instruction_and_bad_iso_returns_help; controlled dependencies, no genuine provider transaction.

## TC-154 · E · non sandbox binding cannot be quoted

**Status:** PARTIAL · **Scope:** contract · **Time:** 3.27 ms

**Execution steps:**

1. Run isolated existing test test_sandbox_hooks.WhatsAppTests.test_non_sandbox_binding_cannot_be_quoted; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_sandbox_hooks.WhatsAppTests.test_non_sandbox_binding_cannot_be_quoted; controlled dependencies, no genuine provider transaction.

## TC-155 · E · only two callbacks are routed

**Status:** PARTIAL · **Scope:** contract · **Time:** 204.88 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_ingress.IngressTests.test_only_two_callbacks_are_routed; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_ingress.IngressTests.test_only_two_callbacks_are_routed; controlled dependencies, no genuine provider transaction.

## TC-156 · E · forwarding preserves raw body and signature only

**Status:** PARTIAL · **Scope:** contract · **Time:** 195.47 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_ingress.IngressTests.test_forwarding_preserves_raw_body_and_signature_only; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_ingress.IngressTests.test_forwarding_preserves_raw_body_and_signature_only; controlled dependencies, no genuine provider transaction.

## TC-157 · E · status callback uuid route

**Status:** PARTIAL · **Scope:** contract · **Time:** 219.09 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_ingress.IngressTests.test_status_callback_uuid_route; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_ingress.IngressTests.test_status_callback_uuid_route; controlled dependencies, no genuine provider transaction.

## TC-158 · E · unsigned oversized and query payloads never forward

**Status:** PARTIAL · **Scope:** contract · **Time:** 205.78 ms

**Execution steps:**

1. Run isolated existing test test_whatsapp_ingress.IngressTests.test_unsigned_oversized_and_query_payloads_never_forward; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_whatsapp_ingress.IngressTests.test_unsigned_oversized_and_query_payloads_never_forward; controlled dependencies, no genuine provider transaction.

## TC-159 · E · Real personal-phone quote 5kg GB to US

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-160 · E · Real personal-phone three calibrated offers

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-161 · E · Live carrier cheapest-offer ordering

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-162 · E · Real click-to-book links

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-163 · E · Zero-wallet warning delivered to phone

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-164 · E · Reserved-wallet warning delivered to phone

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-165 · E · Malformed weight instruction delivered

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-166 · E · Invalid XYZ country instruction delivered

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-167 · E · Missing destination instruction delivered

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-168 · E · Unbound phone registration reply delivered

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-169 · E · Disabled binding registration reply delivered

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-170 · E · Wrong sandbox receiver rejected

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-171 · E · Real Twilio webhook retry returns same quote

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-172 · E · Carrier timeout message delivered

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-173 · E · WhatsApp exception remedy sent

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-174 · E · WhatsApp delivery callback commits receipt

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-175 · E · Long multi-message quote delivered

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.0 ms

**Execution steps:**

1. Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.

**Assertions:** Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.

**Evidence:** Twilio account HTTP=200; actual phone roundtrip/delivery not automated; active TEST carriers=0.

## TC-176 · F · exact requested header and all cargo types

**Status:** PARTIAL · **Scope:** contract · **Time:** 3.2 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVParsingTests.test_exact_requested_header_and_all_cargo_types; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVParsingTests.test_exact_requested_header_and_all_cargo_types; controlled dependencies, no genuine provider transaction.

## TC-177 · F · recipient contact company phone and decimal mapping

**Status:** PARTIAL · **Scope:** contract · **Time:** 0.39 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVParsingTests.test_recipient_contact_company_phone_and_decimal_mapping; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVParsingTests.test_recipient_contact_company_phone_and_decimal_mapping; controlled dependencies, no genuine provider transaction.

## TC-178 · F · invalid rows do not discard valid peers

**Status:** PARTIAL · **Scope:** contract · **Time:** 1.77 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVParsingTests.test_invalid_rows_do_not_discard_valid_peers; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVParsingTests.test_invalid_rows_do_not_discard_valid_peers; controlled dependencies, no genuine provider transaction.

## TC-179 · F · extended international customs and store identity

**Status:** PARTIAL · **Scope:** contract · **Time:** 1.02 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVParsingTests.test_extended_international_customs_and_store_identity; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVParsingTests.test_extended_international_customs_and_store_identity; controlled dependencies, no genuine provider transaction.

## TC-180 · F · validation boundaries and unknown tenant column

**Status:** PARTIAL · **Scope:** contract · **Time:** 13.79 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVParsingTests.test_validation_boundaries_and_unknown_tenant_column; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVParsingTests.test_validation_boundaries_and_unknown_tenant_column; controlled dependencies, no genuine provider transaction.

## TC-181 · F · legacy layout and bom are supported

**Status:** PARTIAL · **Scope:** contract · **Time:** 0.32 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVParsingTests.test_legacy_layout_and_bom_are_supported; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVParsingTests.test_legacy_layout_and_bom_are_supported; controlled dependencies, no genuine provider transaction.

## TC-182 · F · review requires explicit codes and boolean confirmation

**Status:** PARTIAL · **Scope:** contract · **Time:** 0.31 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVParsingTests.test_review_requires_explicit_codes_and_boolean_confirmation; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVParsingTests.test_review_requires_explicit_codes_and_boolean_confirmation; controlled dependencies, no genuine provider transaction.

## TC-183 · F · downloaded template round trips and stages international

**Status:** PARTIAL · **Scope:** contract · **Time:** 20.55 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVRouteTests.test_downloaded_template_round_trips_and_stages_international; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVRouteTests.test_downloaded_template_round_trips_and_stages_international; controlled dependencies, no genuine provider transaction.

## TC-184 · F · batch roles and row dispatch are isolated

**Status:** PARTIAL · **Scope:** contract · **Time:** 20.29 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVRouteTests.test_batch_roles_and_row_dispatch_are_isolated; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVRouteTests.test_batch_roles_and_row_dispatch_are_isolated; controlled dependencies, no genuine provider transaction.

## TC-185 · F · review preview never accepts unreviewed customs

**Status:** PARTIAL · **Scope:** contract · **Time:** 17.6 ms

**Execution steps:**

1. Run isolated existing test test_order_csv.CSVRouteTests.test_review_preview_never_accepts_unreviewed_customs; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_order_csv.CSVRouteTests.test_review_preview_never_accepts_unreviewed_customs; controlled dependencies, no genuine provider transaction.

## TC-186 · F · exact import replay and changed payload

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.49 ms

**Execution steps:**

1. Run isolated existing test test_ecommerce_sync.EcommerceTests.test_exact_import_replay_and_changed_payload; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_ecommerce_sync.EcommerceTests.test_exact_import_replay_and_changed_payload; controlled dependencies, no genuine provider transaction.

## TC-187 · F · tenant and permission isolation

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.69 ms

**Execution steps:**

1. Run isolated existing test test_ecommerce_sync.EcommerceTests.test_tenant_and_permission_isolation; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_ecommerce_sync.EcommerceTests.test_tenant_and_permission_isolation; controlled dependencies, no genuine provider transaction.

## TC-188 · F · outbox simulation retry idempotency and tenant isolation

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.17 ms

**Execution steps:**

1. Run isolated existing test test_ecommerce_sync.EcommerceTests.test_outbox_simulation_retry_idempotency_and_tenant_isolation; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_ecommerce_sync.EcommerceTests.test_outbox_simulation_retry_idempotency_and_tenant_isolation; controlled dependencies, no genuine provider transaction.

## TC-189 · F · validation limits

**Status:** PARTIAL · **Scope:** contract · **Time:** 8.54 ms

**Execution steps:**

1. Run isolated existing test test_ecommerce_sync.EcommerceTests.test_validation_limits; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_ecommerce_sync.EcommerceTests.test_validation_limits; controlled dependencies, no genuine provider transaction.

## TC-190 · F · http import and invalid body

**Status:** PARTIAL · **Scope:** contract · **Time:** 17.02 ms

**Execution steps:**

1. Run isolated existing test test_ecommerce_sync.EcommerceTests.test_http_import_and_invalid_body; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_ecommerce_sync.EcommerceTests.test_http_import_and_invalid_body; controlled dependencies, no genuine provider transaction.

## TC-191 · F · combined pdf preserves label and adds invoice

**Status:** PARTIAL · **Scope:** contract · **Time:** 234.27 ms

**Execution steps:**

1. Run isolated existing test test_dispatch_workspace.WorkspaceTests.test_combined_pdf_preserves_label_and_adds_invoice; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_dispatch_workspace.WorkspaceTests.test_combined_pdf_preserves_label_and_adds_invoice; controlled dependencies, no genuine provider transaction.

## TC-192 · F · pdf boundaries no fake or missing postal forms

**Status:** PARTIAL · **Scope:** contract · **Time:** 216.42 ms

**Execution steps:**

1. Run isolated existing test test_dispatch_workspace.WorkspaceTests.test_pdf_boundaries_no_fake_or_missing_postal_forms; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_dispatch_workspace.WorkspaceTests.test_pdf_boundaries_no_fake_or_missing_postal_forms; controlled dependencies, no genuine provider transaction.

## TC-193 · F · shopify pagination isolated import failure and replay

**Status:** PARTIAL · **Scope:** contract · **Time:** 10.06 ms

**Execution steps:**

1. Run isolated existing test test_dispatch_workspace.WorkspaceTests.test_shopify_pagination_isolated_import_failure_and_replay; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_dispatch_workspace.WorkspaceTests.test_shopify_pagination_isolated_import_failure_and_replay; controlled dependencies, no genuine provider transaction.

## TC-194 · F · hundred orders shared limiter and per order review

**Status:** PARTIAL · **Scope:** contract · **Time:** 275.46 ms

**Execution steps:**

1. Run isolated existing test test_dispatch_workspace.WorkspaceTests.test_hundred_orders_shared_limiter_and_per_order_review; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_dispatch_workspace.WorkspaceTests.test_hundred_orders_shared_limiter_and_per_order_review; controlled dependencies, no genuine provider transaction.

## TC-195 · F · optional customs fields preserve historical import hash shape

**Status:** PARTIAL · **Scope:** contract · **Time:** 12.41 ms

**Execution steps:**

1. Run isolated existing test test_dispatch_workspace.WorkspaceTests.test_optional_customs_fields_preserve_historical_import_hash_shape; its provider/database dependencies are controlled fixtures.

**Assertions:** Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.

**Evidence:** Contract assertions passed: test_dispatch_workspace.WorkspaceTests.test_optional_customs_fields_preserve_historical_import_hash_shape; controlled dependencies, no genuine provider transaction.

## TC-196 · F · 150-row CSV valid150 parsing and isolation

**Status:** PARTIAL · **Scope:** csv · **Time:** 31.21 ms

**Execution steps:**

1. Read generated veloce_bulk_test_150.csv.
2. Apply valid150 variation; parse every row through real CSV/model controller.

**Assertions:** 150 result rows; expected invalid rows isolated; international data retained and customs staging applied.

**Evidence:** 150 rows parsed; 0 isolated errors; model/customs staging only, no actual labels or marketplace transactions.

## TC-197 · F · 150-row CSV missing_zip parsing and isolation

**Status:** PARTIAL · **Scope:** csv · **Time:** 26.08 ms

**Execution steps:**

1. Read generated veloce_bulk_test_150.csv.
2. Apply missing_zip variation; parse every row through real CSV/model controller.

**Assertions:** 150 result rows; expected invalid rows isolated; international data retained and customs staging applied.

**Evidence:** 150 rows parsed; 1 isolated errors; model/customs staging only, no actual labels or marketplace transactions.

## TC-198 · F · 150-row CSV bad_weight parsing and isolation

**Status:** PARTIAL · **Scope:** csv · **Time:** 24.08 ms

**Execution steps:**

1. Read generated veloce_bulk_test_150.csv.
2. Apply bad_weight variation; parse every row through real CSV/model controller.

**Assertions:** 150 result rows; expected invalid rows isolated; international data retained and customs staging applied.

**Evidence:** 150 rows parsed; 1 isolated errors; model/customs staging only, no actual labels or marketplace transactions.

## TC-199 · F · 150-row CSV duplicate_reference parsing and isolation

**Status:** PARTIAL · **Scope:** csv · **Time:** 26.17 ms

**Execution steps:**

1. Read generated veloce_bulk_test_150.csv.
2. Apply duplicate_reference variation; parse every row through real CSV/model controller.

**Assertions:** 150 result rows; expected invalid rows isolated; international data retained and customs staging applied.

**Evidence:** 150 rows parsed; 1 isolated errors; model/customs staging only, no actual labels or marketplace transactions.

## TC-200 · F · 150 real international labels, customs bundle and live marketplace pushback

**Status:** BLOCKED · **Scope:** blocked · **Time:** 0.01 ms

**Execution steps:**

1. Verify live carrier and connected store prerequisites.

**Assertions:** All 150 native labels and genuine store fulfillment updates required; preview documents do not count.

**Evidence:** Active TEST carriers=0; native sandbox purchases are fenced; genuine card completion/store dispatch not executed.

## Supplementary regression evidence

209 unittest test executions passed; the three supplemental browser scripts passed. These are outside the 200-case count and include overlapping controlled contracts, not additional genuine end-to-end provider transactions.
