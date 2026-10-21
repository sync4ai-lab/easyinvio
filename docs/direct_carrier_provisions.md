# Direct carrier provisions and integration switches

## Current readiness

Royal Mail and Evri are **disabled provisions, not certified live integrations**.
The application does not send requests to guessed `/shipping/v3/token`, `/rates`,
`/orders` or Evri enterprise endpoints. It does not fabricate negotiated prices,
zero surcharges, thermal labels, tracking numbers, manifests or QR codes.

Royal Mail's [API onboarding instructions](https://sb.developer.royalmail.net/start)
direct API Shipping customers to their account manager. OBA billing credentials
are not, by themselves, evidence of OAuth credentials or an authorized API product.
Evri's [business account information](https://www.evri.com/business) provides
account-manager support for its commercial services. Obtain the issued integration
specification, service entitlements, tariffs, credentials and sandbox fixtures from
each carrier before implementing its transport. Do not substitute aggregator
documentation for a direct carrier contract.

## Operator controls

Copy the following settings from `.env.example` into the server's private `.env`:

```dotenv
INTEGRATION_EASYPOST_ENABLED=true
INTEGRATION_SENDCLOUD_ENABLED=true
INTEGRATION_SHIPPO_ENABLED=true
INTEGRATION_REGIONAL_ENABLED=true
INTEGRATION_ROYAL_MAIL_ENABLED=false
INTEGRATION_EVRI_ENABLED=false
```

Restart **all** API and worker processes after changing a switch. Both Sendcloud
v2 and v3 use the Sendcloud switch. Regional controls other approved regional
connections. Existing aggregator defaults are preserved. No credentials are
introduced into the example file. No new broker dependency is added.

Disabled connections are excluded from quote strategy execution. Cached checkout,
native confirmation and automatic purchase paths reject disabled integrations
before reserving credit. Native HTTP mutations and the legacy EasyPost purchase
transport have a second guard. New manifest submissions are blocked before claims
are written. Account discovery and historical GET/status/document reads remain
available for reconciliation; disabling a connection must not hide an already
submitted purchase or release its financial reservation. Provider-side cancellation
and refund writes are blocked too: restore the integration under operator control
when those actions are required. Disabling a switch does not recall a network
operation already in flight.

These controls complement tenant account activation, credentials, purchase
permissions, environment matching and `AUTOMATION_PURCHASE_ENABLED`. They do not
create accounts or deploy database changes. An all-disabled rating configuration
returns HTTP 503 with an explicit no-enabled-integrations message.

## Direct transport extension boundary

`backend/adapters/direct_contract.py` defines the internal typed interface for a
certified carrier transport. It is **not a claimed Royal Mail or Evri wire schema**.
`RoyalMailStrategy` and `EvriStrategy` implement `RateStrategy`, accept an injected
contract, and fail with `ProviderFailure` if disabled or unconfigured. A returned
quote must match the account, carrier, currency and existing REGIONAL provider
envelope. This preserves the unified account/rating/finance schemas.

Physical mass is converted exactly from kilograms to integer grams; dimensions
remain Decimal centimetres. Unsupported cargo, international or multi-piece input
is rejected explicitly by these initial provisions. LETTER maps internally to
LargeLetter and PARCEL to Parcel, but service eligibility still belongs to the
issued carrier contract. Evri's 3 cm helper is a height candidate check, not a
claim that weight, footprint, drop-off location or contract eligibility passed.

Label input requires `recipient_paf` with premise, thoroughfare, optional dependent
thoroughfare, post town, postcode and UDPRN from a licensed lookup. No regex splitting
of arbitrary address lines establishes PAF verification. A certified implementation
must carry and bind the existing PAF selection to the immutable booking snapshot;
it must not accept customer-supplied proof fields as authoritative.

`EvriStrategy.extract_dropoff_barcode` validates an actual carrier-supplied 16-digit
barcode and normalizes the actual carrier image. It never generates a substitute
barcode or asserts that a QR asset was received when it was not. Native label
and manifest results carry returned tracking/reference/document data.

`DIRECT_REGISTRATIONS` is intentionally empty. After contract implementation and
certification, register the **exact approved HTTPS endpoint and strategy factory**
in code and implement the corresponding lifecycle bridge in
`automation_three_partners.ADAPTERS`, selected-offer binding, uncertain-purchase GET
reconciliation, returns and `ManifestService`. Direct `purchase_label` and
`create_manifest` methods are transport interfaces, not alternative public wallet
or manifest orchestration paths. Setting a direct flag to true alone cannot
complete that missing work. First-party Royal Mail/Evri endpoints are recognized
and cannot silently fall through to a generic regional request strategy.

Required contract evidence includes authentication/token lifetime, exact API paths,
service codes (including any TPN/TPS/SD1 entitlements), negotiated tariffs with all
surcharges, supported addresses/formats, PDF/ZPL dimensions and encoding, return
barcode fields, manifest shipment membership, sandbox behavior, idempotency and
definitive rejection versus uncertain submission behavior. The requested OAuth
URL, Evri signing headers and live-price endpoints have **not** been established
by this implementation.

## Tiering and deduplication

`RatingService` runs registered or recognized direct providers first. Every direct
call has a maximum 2.2-second timeout including semaphore admission, with concurrent
primary execution. Cancellation/failure becomes a typed provider issue. Secondary
providers then use their existing deadline and physical-versus-billable request
mapping. An international or missing direct service can therefore fall back.

Aggregators still run to discover uncovered carriers/services. Their multi-carrier
APIs do not generally accept exact per-service exclusions. Exact normalized
carrier/service/currency matches already provided by direct carriers are removed
from secondary results. This avoids duplicate offers, **not all redundant upstream
network calls**. Do not suppress a whole aggregator when only one carrier succeeds.
Unverified service-code equivalence is not inferred. Final consolidation prefers
a registered direct source on equal customer prices, retains distinct service
tiers and currencies, and preserves existing margin ranking for other comparisons.

## Validation and rollout

Run the offline regression suite without starting production lifespan workers:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_direct_carrier_provisions.py
.\.venv\Scripts\python.exe -m pytest -q tests
```

Fixtures verify local behavior only. They do not certify either carrier's API.
Before activation, add issued-payload contract tests and authorized sandbox tests
covering authentication expiry, rejected addresses, surcharge precision, booking
timeouts, reconciliation, real thermal labels, real paperless returns and exact
manifest membership. Then enable one direct carrier while retaining aggregators,
observe carrier-side acceptance and settlement, and only subsequently retire
aggregator connections. No live label, charge or database mutation is part of this
change.
