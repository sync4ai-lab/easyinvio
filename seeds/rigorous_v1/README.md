# Rigorous sandbox fixtures — 24 customers

These complete SQL scripts were generated against the live schema, rollback-tested, committed to Supabase and rerun successfully without changing counts. The batch identifier is `veloce-rigorous-v1`; workspace slugs are `seed24-01` through `seed24-24`. Existing unrelated rows are preserved. All tenant rows are `is_sandbox=true`.

## Exact execution order

1. `00_preflight.sql` — starts the transaction, checks prerequisites and reserved UUID collisions, records the seed batch and saves/suppresses only the two optional CRM queue triggers.
2. `01_tenants_and_auth.sql` — 24 tenants; each creates its wallet through the existing trigger. Adds 72 disabled synthetic `auth.users` FK parents.
3. `02_members_and_carrier_accounts.sql` — three tenant members each (OWNER, DISPATCHER, ACCOUNTANT), then two inactive TEST carrier accounts each.
4. `03_margins_and_stores.sql` — default/US-lane percentage rules and Shopify, WooCommerce and Amazon stores per tenant.
5. `04_shipments_and_customs.sql` — eight shipments per tenant, referencing those members/accounts/margins/stores, with complete addresses, cargo and reviewed synthetic customs items where required.
6. `05_wallets_reservations_and_ledger.sql` — records synthetic opening balances, captured/pending reservations and ordered RESERVE/CAPTURE ledger entries; reconciles closing wallet state.
7. `06_tracking_and_support.sql` — IN_TRANSIT/DELIVERED/EXCEPTION event receipts, synthetic POD URLs and one open exception ticket per tenant.
8. `07_verify_and_commit.sql` — restores CRM triggers to their exact original states, verifies counts, fees, customs, generated prices, wallet reconciliation and actual authenticated-role RLS, exercises FK/letter rejection, then commits.

**In Supabase SQL Editor, run only the complete `all_in_one.sql`.** It wraps all eight steps in one atomic DO statement, so temporary state cannot disappear between independently dispatched statements. Select the entire file, not an inner step. The numbered files are for advanced execution on one persistent connection: 00 starts a transaction and 07 commits it, and they must never be run as separate independent editor queries. The Python runner supplies its own outer transaction for rollback-only verification. PostgreSQL constraints and tenant-protection triggers remain enabled throughout. Only the two named optional CRM queue hooks are temporarily suppressed, within the transaction; this prevents generating CRM work for these fixtures.

Already applied to the current project. Repeating the pack verifies and preserves an unchanged completed dataset; it does not reset records changed by later tests. UUIDs are deterministic and the batch marker prevents overwriting unrelated tenants. It is not a cleanup/reset script.

## Resulting rows

| Entity | Count |
|---|---:|
| Tenants / wallets | 24 / 24 |
| Disabled auth principals / members | 72 / 72 |
| Inactive TEST carrier accounts | 48 |
| Margin rules | 48 |
| E-commerce stores | 72 |
| Shipments | 192 |
| Wallet reservations | 108 |
| Wallet ledger entries | 156 |
| Tracking events | 72 |
| Open support tickets | 24 |

There are no seeded Stripe customers, checkout sessions, wallet top-up payments, Twilio bindings/messages or HubSpot company/contact jobs. No carrier API calls, real labels, real POD images or emails were created. URLs use `example.invalid`; tracking references start `SEED24`. Carrier credential envelopes are valid Fernet ciphertext containing a deliberately unusable fixture token; their local encryption key is in `.env`, never in the SQL pack or catalogs. Accounts are inactive so the real rating adapters do not call them. These fixtures are for database/application logic; they do not supply working carrier APIs.

## Scenario coverage

- 18 prepaid tenants and 6 postpaid tenants; 8 tenants per GBP/EUR/USD currency.
- 21 active workspaces, 3 suspended; billing includes ACTIVE, PAST_DUE and SUSPENDED.
- 8 zero-balance wallets, 4 low-credit wallets and 12 funded wallets with held reservations.
- Each tenant has DRAFT, QUOTED, BOOKED, IN_TRANSIT, DELIVERED, EXCEPTION, FAILED and either BOOKING or a second QUOTED shipment.
- Cargo includes PARCEL, a non-stackable PALLET floor-charge case, a dimension-free LETTER and OVERLAND_FREIGHT.
- US and German customs examples have correctly typed unit values/weights, six-digit HS codes and same-tenant reviewer links. All review statements are synthetic fixtures, not real customs certifications.
- Shipment price columns are PostgreSQL-generated. The scripts populate wholesale cost, markup and tax inputs, leaving generated totals untouched. Historical margin snapshots use the deployed schema's PERCENTAGE values.
- Invoice-baseline fee strings reconcile exactly to wholesale cost, with cargo-appropriate billable weights.

**Opening balances are synthetic test capital, not incoming payment transactions.** The live ledger's TOPUP constraint requires Stripe session/event references, so these scripts do not fabricate TOPUP entries. `fixture_seed_runs.opening_balances` is the explicit opening audit record. Each closing wallet equals its recorded opening balance plus ledger balance deltas, and reserved funds match live reservations and ledger deltas. Postpaid reservations do not deduct prepaid wallet money.

The auth principals are banned indefinitely and have no usable password; they satisfy referential integrity without creating live login accounts. Later API/login tests should provision a separately controlled Supabase Auth test user and tenant claim. The seed verifier uses actual PostgreSQL `authenticated` role/JWT session settings to prove tenant isolation without issuing login tokens. Sandbox tenants are intentionally excluded from the live platform-owner revenue/tenant dashboard.

## Receipts and commands

`docs/rigorous_seed_receipt.json` contains the committed counts and verification result. `docs/rigorous_seed_catalog.json` lists the exact seeded tenant/member/account/shipment IDs and baseline values for later test cases. `docs/seed_schema_verified.json` records the inspected schema constraints, generated columns and triggers without customer records or secrets.

```powershell
# Validate the pack and roll back its transaction:
.venv/Scripts/python.exe -m backend.seed_rigorous_data

# Commit (or verify an unchanged completed dataset):
.venv/Scripts/python.exe -m backend.seed_rigorous_data --apply
```

HubSpot, Stripe and Twilio must remain disabled for this runner. Do not run this fixture pack against a live customer environment. The SQL pack itself marks all generated tenants as sandbox and inactive carrier accounts as TEST; the Python runner additionally checks `DATABASE_ENVIRONMENT=SANDBOX` and disabled integration flags.
