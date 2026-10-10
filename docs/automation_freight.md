# Cargo, customs and bulk fulfillment

The live schema write path is verified for all four cargo types and international customs using five rolled-back Supabase writes (`docs/automation_writepath_verification.json`). Draft snapshots include the required markup/currency fields, quote expiry exceeds quote time, generated price columns are left to PostgreSQL, and international shipments persist content type, incoterm and same-tenant customs reviewer metadata. The selected provider rate is retained inside `pricing_snapshot.selected_rate` for reconciliation.

`backend/automation_freight_engine.py` is mounted in the configured backend. Migration 013 is applied to the connected sandbox: it adds cargo types, permits dimension-free letters while retaining dimensional requirements for other cargo, extends store platforms to Amazon, and connects bulk-order failures to support tickets. The original rating/finance pipeline is extended rather than bypassed.

## Cargo pricing

Supported types are LETTER, PARCEL, PALLET and OVERLAND_FREIGHT. Send Decimal strings. Letters must weigh strictly below 0.5 kg; supplied box measurements are discarded. Parcels use the existing 5000 cm³/kg divisor. Pallets/road freight compare actual weight, cubic volume × configured kg/m³, and, for non-stackable cargo, floor loading metres × configured kg/loading-metre. Loading metres are footprint m² divided by the configured vehicle-deck width. Chargeable weight rounds upward to 0.001 kg.

Server configuration defaults are `FREIGHT_KG_PER_M3=333`, `FREIGHT_KG_PER_LOADING_METRE=1750`, `FREIGHT_DECK_WIDTH_M=2.4`. They describe a configurable example road-freight tariff profile; factors differ by contract, lane and carrier. They are not a universal freight class or a certified NMFC classification. Freight bypasses express EasyPost rating and goes through the regional `/rates` adapter, which receives cargo type and stackability. Carrier-specific freight products and purchase contracts must be configured with that provider. Actual weight/dimensions include packing and pallets.

Authenticated `POST /api/v1/automation/cargo-weight` accepts a Cargo object, for example:

```json
{"cargo_type":"PALLET","actual_weight_kg":"100.000","length_cm":"120","width_cm":"80","height_cm":"100","stackable":false}
```

With the default profile, this yields 0.4 loading metres and a 700.000 kg floor-charge basis. It does not imply 700 kg actual mass.

## Bulk API

`POST /api/v1/automation/bulk-fulfill?mode=QUOTE_ONLY` accepts a raw array of 1–100 normalized orders, up to 5 MB, with a tenant JWT having OWNER, ADMIN or DISPATCHER permission:

```json
[
  {
    "idempotency_key":"YOUR_STABLE_ORDER_UUID",
    "order_reference":"#1024",
    "platform":"SHOPIFY",
    "origin":{"name":"Warehouse","line1":"10 High Street","city":"London","postal_code":"SW1A 1AA","country_code":"GB"},
    "destination":{"name":"Customer","line1":"20 High Street","city":"Manchester","postal_code":"M1 1AA","country_code":"GB"},
    "cargo":{"cargo_type":"PARCEL","actual_weight_kg":"2.500","length_cm":"40","width_cm":"30","height_cm":"20"},
    "currency":"GBP"
  }
]
```

Platforms may be SHOPIFY, WOOCOMMERCE, AMAZON or MANUAL. An optional `store_id`/`store_order_id` pair must identify an active same-tenant store with the matching platform. The store/provider adapter normalizes native order payloads into this schema; Amazon seller API credentials/OAuth and remote polling are not fabricated. Country alpha-3 inputs are normalized to alpha-2. Invalid addresses are returned as individual validation failures; no Google address-verification call is claimed.

QUOTE_ONLY is the default: it persists valid rated shipments and customs metadata, returns the lowest available customer rate and never purchases labels. It does not require wallet funding to obtain a quote. Providers still require actual tenant-owned carrier credentials; no rates are invented. The shared worker limit is at most four orders across simultaneous batches, and existing provider concurrency limits remain in force.

`mode=FULFILL` first checks active billing and available prepaid credit, then obtains a complete parallel quote result and selects the cheapest customer tier using Decimal. Partial provider results are rejected for automatic purchase because the unavailable provider might have been cheaper. A transactionally locked wallet reservation rechecks the full price, preventing concurrent overspending. POSTPAID_30_DAY retains the existing active-billing behavior; no new postpaid credit-limit policy is invented. Stored pricing uses the existing ex-tax quote contract with tax_amount zero; a jurisdiction-specific shipping-tax calculator is outside this module.

Real purchases require `AUTOMATION_PURCHASE_ENABLED=true`, `PROVIDER_ENVIRONMENT=LIVE`, `DATABASE_ENVIRONMENT=LIVE`, a non-sandbox tenant, active carrier credentials and sufficient credit. These restrictions preserve the existing sandbox no-dispatch guard. Do not enable this flag just to test local parsing. Your current sandbox cannot purchase real labels.

The complete EasyPost adapter purchases the already-rated immutable shipment using `/shipments/{id}/buy` with its exact rate ID, checks production mode and returned shipment/rate identity, and settles the wallet only after confirmed tracking/label data. Returned labels are provider URLs, not mock ZPL. Customs-form URLs and declaration metadata are collated into each `print_bundle`; no printer broadcast or physical printing occurs. Successful retries return the persisted label/form bundle and do not buy again. Existing settlement hooks also enqueue storefront tracking push-back.

The regional **rating** contract is already defined in `main.py`; no regional **purchase** contract was supplied. Register your provider's actual async `buy(account, rate)` and `reconcile(account, rate)` adapter using `service.register_purchase_adapter('REGIONAL', adapter)`. If the cheapest tier belongs to a provider without a purchase adapter, the order fails explicitly instead of silently selecting a more expensive tier or claiming a label exists.

## Customs

The exported `async generate_customs_declaration(shipment_id)` requires `customs_scope(service, authenticated_tenant_id)` and performs tenant-scoped reads. The authenticated GET `/api/v1/automation/customs/{shipment_id}` supplies that scope. It reads saved automation orders or complete existing shipment customs items, returning a commercial-invoice data matrix with EORI/VAT fields, exact line values and weights, product origin, HS codes, signer, incoterm and declaration statement.

For international goods, add an `items` array containing description, quantity, unit_value, unit_weight_kg and origin_country, plus optional HS code. Missing codes receive the existing simulated AI prediction with its provenance. Unknown goods abstain. Actual carrier submission requires `hs_codes_reviewed=true` and `customs_signer`; these do not replace statutory or national classification requirements. Net goods weight cannot exceed gross cargo weight. The VAT/EORI fields come from explicit party data or the tenant's recorded seller registrations; no registration is invented.

Country differences conservatively require customs except common EU-area country pairs. `customs_required_override=true` supports special-territory cases; this simple country policy does not claim to resolve every customs territory exception. Optional `postal_form` selects CN22/CN23 metadata; postal eligibility and valuation thresholds are not guessed from currency amounts. The actual carrier supplies any generated customs forms.

Customs metadata is attached to rating **before** an EasyPost shipment is created, because those shipments are immutable. EasyPost CustomsItem values are USD; GBP/EUR international orders are routed to regional providers instead of being misrepresented as USD. No exchange rate is guessed. CN22/CN23 and commercial-invoice metadata are included with the resulting label bundle; an integrated printer can render/download the documents.

## Failures and reconciliation

One invalid order does not cancel its peers. Per-order failure receipts and deterministic mock-AI remedies are saved in `automation_failures`/`support_tickets`, including failures before a valid shipment can exist. These appear in the existing support dashboard. Ticket write failures are logged without secrets and surfaced as `support_ticket_recorded=false`, rather than claiming persistence during a database outage.

Network timeouts or malformed purchase responses remain uncertain: SUBMITTED wallet funds are retained, the response says RECONCILIATION_REQUIRED, and the engine never retries the purchase automatically. Authenticated `POST /api/v1/automation/orders/{shipment_id}/reconcile` retrieves the existing provider shipment and settles only a confirmed purchase. A never-submitted RESERVED booking may be released; unresolved submitted outcomes retain the reservation. Tenant/order session locks prevent competing batches from purchasing the same order. Changing the payload under an existing idempotency key returns a conflict.

## Verification

Tests cover strict letters, freight floor arithmetic, Decimal customs values, weight-only EasyPost requests, purchase identity/mode checking, cheapest-tier selection, reserve/settle ordering, insufficient credit, sandbox fencing, ambiguous outcomes and a 100-order batch with one isolated failure. The real Supabase validation check creates one labelled invalid-order support ticket under the existing connectivity-test tenant, leaves its wallet unchanged and performs zero carrier calls. See `docs/automation_sandbox_verification.json` for that receipt. Actual carrier purchases have not been executed in this session.

Primary references: [EasyPost shipments and immutable customs data](https://docs.easypost.com/docs/shipments), [Customs item values and weights](https://docs.easypost.com/docs/customs-items), [DHL freight charging rules](https://www.dhl.com/content/dam/dhl/local/be/dhl-freight/documents/pdf/be-freight-weight-and-dimensions-charging-rules.pdf).
