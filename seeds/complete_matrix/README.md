# Complete-matrix UAT reference fixtures

Run the entire [seed.sql](seed.sql) in the Supabase SQL Editor for a dedicated UAT project as `postgres`, after migrations through 036. This file prepares two isolated sandbox workspaces; it does not execute tests or purchase anything. The seed is intentionally separate from application schema migrations.

| Fixture | Tenant ID | Initial GBP credit | Default markup |
| --- | --- | --- | --- |
| Alpha | `a0000000-0000-0000-0000-000000000001` | 5000.00 | 15%, minimum 1.50 |
| Beta | `a0000000-0000-0000-0000-000000000002` | 2500.00 | 20%, minimum 2.00 |

Each workspace gets four memberships (owner, admin, dispatcher, accountant), four default address roles, one contact, one unreviewed product and three inactive store references. Parent rows are inserted before dependent rows, with all existing foreign keys, credential locks and validation triggers preserved. An unrelated existing tenant or user occupying a reserved fixture ID causes a full rollback. The existing Mavuri company workspace is never touched.

Opening credit is synthetic UAT data, recorded in the fixture's company profile; it is not a verified payment. No Stripe payment, top-up or fabricated wallet-ledger row is inserted. Rerunning the seed preserves wallet spending and reservations rather than replenishing balances. Use a fresh UAT database when a clean financial baseline is required.

The existing platform trigger mirrors configured TEST connections with their real encrypted credentials and key IDs. The seed activates no new provider credentials. Only existing native EasyPost v2, Sendcloud v3 and Shippo TEST mirrors can remain active. Output lists actual carrier account IDs; do not assume the `d000...` IDs from the proposed seed exist. An enabled connection does not guarantee a carrier contract, eligible route, sufficient provider funds or ten unique services. Configure missing connections through Admin using the application's credential encryption workflow.

Stores are inactive FK fixtures, not connected Shopify or Amazon shops. To test real inbound delivery, install the corresponding credentials using the store connection workflow and complete provider authentication. SQL cannot generate legitimate webhook signatures or marketplace authorizations.

## Required corrections to the supplied test file

`tests/test_easyinvio_complete_matrix.py` currently defines seven tests, not 250 executable scenarios. Seeding alone cannot make its HTTP tests pass:

1. `mock_uat_verified_jwt_claims_token_matrix` is not a signed access token. For isolated automated tests, override `main.authenticate` using `app.dependency_overrides` and a `main.TenantContext`, then restore overrides after the test. Keep provider, database, payment and agent calls mocked in those tests. Existing `tests/test_logistics.py` demonstrates that pattern. Do not add a fake-token bypass to production authentication.
2. The synthetic `auth.users` entries are banned indefinitely and have no password or login identity. They support database FK tests only. For browser or live API UAT, invite a dedicated real test user to the fixture workspace using the existing membership flow and sign in normally. Use its verified JWT and actual auth user ID; never unban fixture principals as a shortcut.
3. Current HTTPX requires `AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`. Supplying `app=app` directly is unsupported. ASGITransport does not run application lifespan automatically; initialize mocked app services explicitly or use the project's established TestClient patterns.
4. `RatingRequest` forbids extra fields. Replace top-level `item_description` and `item_declared_value` with supported `shipment_items` goods rows and `goods_currency`. Supply a valid GB postcode, such as `LS1 1AA`, instead of `ES12 78D`. Both addresses and customs data still need actual validation.
5. Change the booking tenant from the real Mavuri ID to the authenticated Alpha fixture. A random `uuid4()` offer has no prepared quote or shipment; quote and prepare the booking through the current endpoints first, then use the returned opaque offer ID. A concurrency assertion using an invented offer cannot verify wallet idempotency. Mock external label purchases or use explicitly configured sandbox provider tests.
6. Cross-workspace requests may legitimately return 401, 403, 404 or validation errors depending on authentication and the specific endpoint. First authenticate correctly and verify the route exists, then assert the documented tenant boundary and that no foreign rows are returned. A fake-token failure does not prove tenant isolation.
7. The comma conversion and two insurance checks currently exercise local expressions, not production services. Use existing production unit tests for those behaviors. No seed can activate XCover without its partner configuration or prove claim settlement using local arithmetic.

## What is deliberately created through application workflows

Prepared offers, booking permits, shipments, wallet reservations, immutable ledger captures, purchased labels, tracking events and insurance policies must come from the corresponding validated workflow. They are not seeded as successful external transactions. Existing tests for those components use controlled provider responses and rollback database probes.

The seed prints workspace balances, role principal IDs, actual carrier account IDs and store IDs. It never prints ciphertext, API keys or passwords. Test SQL validity with `tests/complete_matrix_seed_database_probe.py`: it requires SANDBOX/TEST configuration, executes the seed twice inside an outer transaction, checks rerun behavior and rolls everything back.
