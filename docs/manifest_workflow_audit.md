# Manifest & Labels: workflow audit and operating guide

Reviewed 21 October 2026. This describes the implemented application, not live
carrier certification. No customer shipments, wallet entries or production
database rows were modified during this review. No new migration is required.

## What each status means

| Display | Where it occurs | Expected next step |
|---|---|---|
| Imported — needs preparation | CSV/store order data has been saved before packing, address or customs preparation is complete | Prepare & compare rates; review uploaded customs only when actually outstanding |
| Imported — not shipped | A store order is unfulfilled; it is not a carrier booking | Complete preparation and compare rates |
| Draft — needs quote | Shipment preparation is saved without a current usable offer | Prepare & compare rates |
| Quoted — not booked | A saved shipping offer is still within its expiry | Review & book a service, or add it to a batch and use Review & book selected orders |
| Quote expired | The quote deadline has passed | Requote restores saved shipment details in Create a shipment; review them and request new prices |
| Fresh quote required | An older QUOTED row has no verifiable expiry | Request fresh rates; no booking action is offered |
| Booking in progress | A purchase has entered the booking workflow | Wait/review the existing outcome; do not submit a duplicate purchase |
| Carrier confirmation pending | The provider outcome is unconfirmed or asynchronous | Reconcile/retrieve the existing provider transaction; do not buy again |
| Booking failed | Preparation or label purchase failed | Review the shipment; requote only when no pending purchase/financial reservation remains |
| Label created / Booked | The label/booking is confirmed | Download the actual carrier document; hand over the parcel using the selected service |
| On a handover manifest | A confirmed shipment was added to an EOD manifest | Handover preparation; this is not proof of collection |
| Dispatched | Dispatch has been recorded | Follow the next actual carrier update |
| In transit | Carrier reported movement through its network | Follow the timeline |
| Out for delivery | Carrier reported the final delivery route | Await the carrier's delivery outcome |
| Delivery exception | Carrier reported an exception | Review the recorded exception; use the existing support workflow |
| Delivered | Carrier reported delivery | Open delivery proof only if a genuine proof URL was supplied |
| Cancelled | Shipment was cancelled | Do not dispatch using a previous label |

“Imported” means data brought into EasyInvio from a file or store. It does not
mean customs import clearance. An imported order can need address/packing/goods
review before a carrier can price it. Its independent price label now says
**Not priced yet** instead of the confusing “Unquoted” combination.

## Findings and fixes

1. **Carrier missing from the API:** the manifest SELECT omitted `carrier_code`
   and `service_code`. It now returns those saved columns, falling back to the
   selected-rate snapshot and historical carrier metadata. The UI says “Not
   selected” on an unprepared order, or “Unavailable on this older record” when
   a historical record genuinely lacks carrier identity. It never invents or
   backfills a carrier from tracking-number patterns.
2. **Checkbox looked like navigation:** selection previously only populated a
   separate batch set. Current quotes now have a direct **Review & book** button.
   **Add to batch** remains explicit; the batch button shows the selected count
   and is disabled when empty. Opening review never buys a label or charges funds.
3. **Expiry was hidden:** the API now exposes quote creation/expiry and server
   time. The page displays the deadline and transitions a visible quote to
   **Quote expired**, removes stale batch selection and hides the booking action.
   Backend offer-expiry and price-snapshot checks remain authoritative.
4. **Requote had no restoration path:** the authenticated, dispatch-role
   `GET /api/v1/shipments/{shipment_id}/requote-context` returns only saved source
   facts for the caller's tenant. It restores addresses/contact fields, cargo,
   measurements, currencies, goods, SKUs, HS candidates, all saved boxes and
   goods-to-box allocation in Create a shipment. Additional boxes and allocation
   remain editable. Old prices, offer IDs, provider credentials and customs
   approval are not copied. Missing legacy facts remain blank for review.
5. **Unsafe retry possibilities:** restoration refuses confirmed shipments,
   return shipments and unresolved RESERVED/SUBMITTED wallet holds or SENDING/
   RECONCILIATION_REQUIRED provider jobs. Returns keep their existing parent and
   verified-warehouse fencing. A changed quote creates a new preparation rather
   than rewriting historical carrier or financial outcomes.
6. **POD offered without evidence:** View delivery proof appears only on a
   DELIVERED row with a safe, actual carrier proof URL. Failed, quoted, draft and
   merely label-created rows do not offer POD.
7. **Raw JSON instead of a customer document:** the drawer now shows a readable
   goods table, quantities, values/currency, net weights, manufacture countries
   and HS codes, plus a clear draft/review label. Confirmed shipments load actual
   carrier scans from the shared tracking domain; unavailable scans are stated
   plainly. The existing JSON export is hidden in this customer workflow.
8. **Document actions did not match readiness:** label, QR, receipt and invoice
   controls depend on actual booking/assets/payment evidence and role. Customs
   review is offered only for an eligible imported draft with outstanding review.
   Backend document authorization/host validation remains in place.
9. **Receipt/invoice download helper rejected valid paths:** the browser helper
   now accepts the explicit authenticated checkout PDF paths and carrier QR path,
   checks document MIME/size, blocks redirects and uses the correct extension.
   Arbitrary external download URLs are still rejected.
10. **Historical provider jobs could duplicate list rows:** the SQL uses a
    bounded lateral lookup for unresolved jobs, rather than multiplying a
    shipment by all its historical carrier jobs.

Expired and missing-expiry labels are **read-time projections**. The database
shipment status remains QUOTED so existing booking, reporting and enum contracts
continue working; expired offers still fail server-side. Failed/expired prices
are labelled **Last quoted price**, not evidence of a payment captured.

## Quote validity and accepted labels

EasyInvio already uses `QUOTE_TTL_SECONDS=300`: five minutes by default, with a
validated setting range of 30–900 seconds. This is the application's validity
window, not a universal industry expiry. Carrier/account conditions differ.
For example, [EasyPost's DHL Express BYOCA guide](https://docs.easypost.com/carriers/dhl-express-guide)
states a minimum five-minute rate validity for that integration; this does not
establish the same contract for every carrier. [EasyPost's rates API](https://docs.easypost.com/docs/shipments/rates)
also supports fetching updated rates. The existing five-minute default is
retained; the UI now accurately reflects the saved deadline. Provider rejection
or service withdrawal before booking still requires a fresh quote.

The earlier paperless-return requests **did not replace carrier PDFs**. A PDF is
a supported carrier output, not a homemade postage label: [EasyPost documents
PDF, PNG, ZPL and EPL2 options](https://docs.easypost.com/docs/shipments/options),
subject to carrier/service support and print sizing. Print the supplied document
at its intended scale and follow carrier instructions. This change does not
generate replacement barcodes, convert PDFs into postage, or activate unsupported
direct carrier integrations.

Keep **both PDF and carrier-issued QR** where provided. A carrier QR is a
service-specific print-at-drop-off asset, not a universally accepted substitute.
For example, [USPS Label Broker](https://support.easypost.com/hc/en-us/articles/4410441700493-Generate-USPS-Label-Broker-QR-Codes)
uses participating locations. [Sendcloud's return-method definitions](https://sendcloud.dev/docs/getting-started/glossary/)
also distinguish labelless returns. The button appears only when the native
provider response contains the actual QR URL/image. Unsupported services retain
their supplied PDF; no generic promise of acceptance at any post office is made.

## Persona permissions

- OWNER, tenant ADMIN, DISPATCHER and individual-owner workspaces can prepare,
  requote and review eligible bookings. Buying still requires the existing
  server-authorized checkout and exact price confirmation.
- ACCOUNTANT has read-only Manifest & Labels navigation and can retrieve eligible
  receipts/invoices and recorded proof. Booking, requoting, returns and carrier
  label/QR downloads remain restricted to dispatch roles.
- Platform owners retain their existing management/Control Tower navigation.
  Cross-workspace manifest projections are read-only; use an explicitly audited
  client-assistance session for tenant dispatch operations. Merely viewing an
  admin row does not grant tenant purchasing authority.

## Verification

`tests/test_manifest_workflow.py` covers 24 state/action/API cases, including
expiry boundaries, absent assets, stale unsafe links, pending financial/provider
outcomes, return fences, multi-box restoration, carrier identity and tenant/role
isolation. `tests/test_manifest_workflow_postgres.py` runs actual SQL joins and
restoration queries in an explicit disposable PostgreSQL instance; it verifies
that historical provider jobs do not duplicate rows or bypass tenant scope.

`tests/manifest_workflow_browser.py` exercises 18 status/asset scenarios across
six personas: 108 action-policy rows. Interactive checks cover direct booking
review, batch selection, in-place expiry, restored multi-box goods, readable
customs, actual scan rendering, proof gating, PDF/QR/receipt/invoice downloads and
375/768/1440 widths. Platform-owner navigation remains restricted. Fixtures and
download bytes are explicitly synthetic; no label purchase, wallet mutation,
customer message or live carrier acceptance is claimed. Local screenshots/report
are written to `output/manifest-workflow-qa`.

Run the suites from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests
# Optional disposable PostgreSQL dependency, as documented in the Tracking 2 guide:
$env:PGLITE_TEST_MODULE = 'C:\path\to\pglite\dist\index.cjs'
.\.venv\Scripts\python.exe -m pytest -q tests/test_manifest_workflow_postgres.py
# Preview server must explicitly use --local-preview, with integrations disabled.
.\.venv\Scripts\python.exe tests/manifest_workflow_browser.py http://127.0.0.1:8768
```

Restart the local backend and refresh the browser to load the new script. No
database migration or changes to active provider credentials are needed. Real
carrier acceptance/printed-label quality and expiring proof links must still be
verified with the connected carrier account in staging.

Final local regression: **997 passed, 1 skipped, 2 warnings, and 14 subtests passed**
with the explicit disposable PostgreSQL dependency. The existing six-persona
Tracking 2 browser suite also passed. The manifest browser action matrix and
interactive document/requote checks passed with no page errors or horizontal
overflow. Python compilation, JavaScript syntax and whitespace checks passed.
