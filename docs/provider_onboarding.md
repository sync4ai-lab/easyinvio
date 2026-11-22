# Royal Mail Evri and XCover onboarding

Reviewed 22 November 2026 on the local feature branch. Sendcloud v3 is active in the shared TEST configuration; the retired Sendcloud connection is inactive. Its runtime adapter, configuration field and upgrade UI have been removed. Stored shipping, financial and audit records are preserved. No provider account has been purchased, activated or changed by this work.

## What is implemented and what remains

| Provider | Implemented | Still required before activation |
|---|---|---|
| Sendcloud v3 | Dynamic real rate discovery, platform/tenant credential handling and native lifecycle adapters with environment/payment guards | Existing provider setup and LIVE contract/integration ID checks still apply. Removal of the older adapter does not change TEST purchase restrictions |
| Royal Mail direct | Typed domestic single-piece parcel/letter interface, exact grams/dimensions, PAF requirement, account/carrier/currency response checks, validated PDF/ZPL/manifest interfaces, disabled-by-default routing | Actual approved HTTP authentication and transport; rate source or negotiated tariff engine; account-service mapping; booking/reconciliation/cancellation/returns/manifest/tracking bridges; sandbox certification. No direct endpoint is registered |
| Evri direct | Same guarded direct interface, Postable height candidate helper, validation of an actual returned 16-digit drop-off barcode and carrier image | Actual approved API transport and routing credentials; full service/package eligibility; real pricing; paperless-return contract; lifecycle/tracking bridges and certification. A height helper does not establish Postable eligibility |
| XCover policy purchase | UK-origin parcel quote and booking client, signing, explicit opt-in/terms, combined checkout, insurance reservation/capture/release, uncertain-booking reconciliation, confirmed policy details and private records | Partner agreement and approved parcel product, keys/signing secret, allowed countries/goods/values, actual wholesale and permitted retail pricing/taxes, policy terms, successful partner sandbox and LIVE approval |
| XClaim insurer claims | Separate JWT authentication, claim types and FNOL forms, uploaded evidence IDs, queued submission, uncertain submission reconciliation, signed callbacks plus authoritative status retrieval, private evidence/status UI, policy-portal fallback | Separate partner code/key/password, webhook signing contract, real loss/damage FNOL field bindings, approved LIVE API origin, settlement/payment schema and payee confirmation, end-to-end partner sandbox tests |
| Claims without an insurer | Shared web/WhatsApp lost/damaged intake, fresh ownership/capability checks, missing-evidence guidance and private dossiers | Migration 056 and its rollout flags; human merchant/carrier handling. There is no universal automatic carrier-claim submission API |

The direct carrier files are scaffolding, not certified transports. `DIRECT_REGISTRATIONS` is empty. Setting a flag or adding a credential row will not complete them. The label/manifest interfaces do not bypass the existing wallet and purchase orchestration.

XCover is a much fuller integration, but local/UAT file checks show it disabled, with no API key, signing secret or headless claims credentials. A partner ID field contains text; that does not verify an issued account. The root Production-reference file sets XCover enabled but still lacks the required credentials and approvals, so readiness remains blocked. These are local file checks, not an inspection of current Vercel variables.

## Choose platform or merchant accounts

A **platform account** means EasyInvio signs the carrier contract and pays the carrier, while eligible tenants use internal account projections. A **merchant account** means an individual retailer uses its own contracted carrier account and negotiated prices. The database already supports both patterns; merchant-owned accounts remain subject to plan entitlements.

Ask each carrier to explicitly approve the intended model, including third-party merchant shipments, multiple pickup locations, billing responsibility and any resale restrictions. Existing platform propagation/encryption is shared infrastructure; direct Royal Mail/Evri transport still needs implementation after the contract is supplied. XCover currently uses a platform partner configuration, not a separate insurer credential set for every tenant. Tenant-specific insurers or additional insurer brands would require new adapters and account modelling.

## Royal Mail action list

Start with [Royal Mail API Shipping](https://www.royalmail.com/business/parcels/shipping-solutions/api-shipping) and the [developer onboarding guide](https://developer.royalmail.net/index.php/start). Royal Mail describes Business Account approval, sandbox onboarding and API subscription. Its guide directs existing customers to their account manager; it lists `business.customer.service@royalmail.com` if you do not have one. The developer account itself is free; ask for the shipping contract's actual charges and commitments before accepting it.

Request all of these together:

1. Approval for **EasyInvio as a multi-merchant shipping platform**, or approval for connecting each merchant's own account. Explain the legal contracting entity and EasyInvio trading brand.
2. The approved product/version: API Shipping, Tracking and the contracted returns/collection services. A website login or OBA access alone is not the complete API setup.
3. Issued sandbox and Production base URLs, OpenAPI/Postman specifications, authentication requirements, application/client credentials, token/certificate requirements if applicable, account numbers and posting-location identifiers.
4. Enabled service/product codes, package formats, UK/international entitlements, label formats and dimensions, customs rules, return-label/QR availability, manifest requirements and certification examples.
5. Actual rating API access **if provided**. Otherwise the approved machine-readable account tariff, effective dates, VAT/fuel/remote-area/peak/other surcharge rules and billing reconciliation rules. Do not assume the shipping API supplies a live price.
6. Tracking subscription or polling API, status catalogue, authentication and limits; cancellation/refund, idempotency and uncertain-submission lookup rules; carrier claims process/API if offered.
7. Written test-call/test-label billing rules, minimum volumes, deposits, collection charges, support and acceptance/sign-off criteria.

Once received, we can implement the real transport, contract tests and lifecycle wiring, then add the approved platform or tenant connection and enable it in UAT.

## Evri action list

Contact the business team at **sales@evri.com**, or your assigned account manager. The address is published in [Evri's business-account FAQ](https://www.evri.com/faqs/account/i-send-a-lot-of-parcels-can-you-offer-me-a-business-or-credit-account). [Business account options](https://www.evri.com/business) differ by volume and service. Ask which account actually includes direct integration; do not assume a normal consumer or frequent-seller login includes it.

Request:

1. Platform/multi-merchant approval versus merchant-owned accounts, agreed volume, billing/credit/deposit terms and pickup-location rules.
2. The exact Evri product and API family for outbound labels, tracking, returns and manifests. Get the issued API specification and routing/authentication credential names; do not substitute documentation for a different Evri or DHL product.
3. Sandbox/Production URLs and credentials, client/customer/account/depot identifiers as required by that specification, service codes and test fixtures.
4. Real quote API or agreed tariff tables plus every surcharge and effective date; dimensional-weight, Postable, parcel size/weight and international rules.
5. Paperless ParcelShop/locker return entitlement, QR/barcode response fields and actual sample assets, collection/drop-off constraints, cancellation/refund and manifest/handover requirements.
6. Tracking events/signatures or approved polling, API limits, idempotency/lookup after timeout, lost/damage claims procedure, sandbox billing and certification criteria.

We will map the issued fields into encrypted platform/tenant credentials after reviewing the specification. There are deliberately no guessed `EVRI_USERNAME` or `ROYAL_MAIL_TOKEN_URL` fields to fill in today.

## Cover Genius XCover and XClaim action list

Use **Get a Demo** on [Cover Genius](https://covergenius.com/) and ask for the shipping/logistics partnerships team plus an integration manager. Request a **UK-origin parcel protection partnership and headless XClaim access for EasyInvio**. Buying a single parcel policy does not establish a platform partnership. Their [parcel API documentation](https://xcover-api-docs.covergenius.com/parcel_insurance.html) and [XClaim documentation](https://partner-docs.covergenius.com/xclaim) describe different API responsibilities.

Ask for:

1. The legal entity/brand onboarding requirements and permission to offer protection to our merchants through web and WhatsApp; required disclosures, consent wording, policy documents, complaints process and approved customer communications.
2. TEST and LIVE partner IDs, API keys and signing secrets; confirmed parcel product/version, countries, goods exclusions, declared-value limits, policy inception/expiry rules and real sample quote/booking responses.
3. Wholesale premium/tax rules, permitted retail pricing/commission, settlement and invoicing, minimum commitments/deposits and free versus billable sandbox actions. Current estimate arithmetic is not an insurer-approved tariff.
4. Separate XClaim partner code, programmatic API key/password, approved TEST/LIVE origins and authentication/token documentation.
5. Real loss/damage claim-type IDs and FNOL (first notice of loss) forms. Ask which returned field IDs map to description, shipment/policy reference, incident date, item value, contact details and uploaded image/document IDs. These bindings cannot be invented from our internal field names.
6. Callback registration, webhook signing secret/header/algorithm, event fixtures, status definitions, retries and rate limits. Proposed UAT receiver: `https://uat.easyinvio.com/api/v1/shipping/insurance-updates`; Production: `https://www.easyinvio.com/api/v1/shipping/insurance-updates`. Confirm these during onboarding before registering anything.
7. Exact authoritative fields for amount, currency, unique payment reference, payee, funds received and receipt time. Confirm whether money is paid to EasyInvio or directly to the insured customer. Our automatic wallet-credit path requires verified funds received by the approved EasyInvio master payee; direct-to-customer payment must not also become wallet credit.
8. Policy cancellation/amendment/refund requirements. A complete automatic policy cancellation/amendment flow is not present in the current client and must be designed against their approved contract.

### Existing private configuration fields

Use `.env.local` first, then Preview after deliberate UAT approval. Do not enable placeholders. Store secrets locally or in the appropriate secret manager; do not paste them into chat or commit them.

| Fields | Source |
|---|---|
| `XCOVER_ENVIRONMENT` | TEST during onboarding; LIVE only after approval |
| `XCOVER_PARTNER_ID`, `XCOVER_API_KEY`, `XCOVER_SIGNING_SECRET` | Cover Genius integration manager |
| `XCOVER_PARCEL_CONTRACT_VERIFIED`, `XCOVER_RETAIL_PRICING_VERIFIED` | Set true only after the corresponding partner approval and implementation review |
| `XCOVER_CLAIMS_PARTNER_CODE`, `XCOVER_CLAIMS_API_KEY`, `XCOVER_CLAIMS_API_PASSWORD` | Separate XClaim access |
| `XCOVER_CLAIMS_WEBHOOK_SECRET`, `XCOVER_CLAIMS_WEBHOOK_URL`, `XCOVER_CLAIMS_LIVE_API_ORIGIN` | Approved receiver/security and LIVE endpoint contract |
| `XCOVER_CLAIMS_FNOL_BINDINGS` | Real per-reason FNOL field mapping to our supported sources |
| `XCOVER_CLAIMS_SETTLEMENT_MAPPING` | Partner-supplied JSON pointers for amount/currency/payment_reference/payee/funds_received/received_at |
| `XCOVER_CLAIMS_MASTER_PAYEE_ID` | Confirmed EasyInvio payment recipient |
| `XCOVER_ENABLED`, `XCOVER_CLAIMS_ENABLED` | Enable only after all prerequisites and sandbox acceptance |

The complete field list already exists in `.env.example`. `SANDBOX` is accepted as an alias for insurer TEST. Database SANDBOX mode, carrier TEST mode and insurer TEST mode must agree for the chosen workspace.

## Next implementation and test sequence

1. Send the three enquiries below. Supply non-secret specifications and account entitlements first; enter issued keys into private configuration through a secure channel.
2. Build Royal Mail/Evri HTTP contracts and the booking/reconciliation/returns/tracking/manifest bridges. Test rejected addresses, precise surcharges, timeout uncertainty and environment mismatches before activation. Keep aggregator fallback available.
3. Map and validate XCover/XClaim partner-specific fields, approved terms/pricing and settlement schema. Exercise quote, explicit purchase, confirmed policy, claim evidence, submission retry, signed status and exactly-once settlement in provider sandbox.
4. Apply any reviewed migrations deliberately. Migration 056 is prepared but was not applied by the prior implementation; this audit did not apply it either. Existing insurance migrations 032/033 must be verified on the target database.
5. Enable one provider at a time in Local/UAT, verify actual provider acceptance and billing, and only then approve Production release. No flag alone certifies an integration.

### Enquiry text for the carriers

> We are building EasyInvio.com, a UK multi-tenant shipping platform with web and WhatsApp booking. Please advise whether we should use an approved platform/reseller account or connect each merchant's own account. We need sandbox and Production access for rates or negotiated tariffs, labels, tracking, returns including paperless QR where supported, manifests, cancellation/refunds and claims handling. Please provide your approved API specification, commercial/minimum-volume terms, credential onboarding and certification process. We are pre-launch and want non-billable sandbox testing before committing to live volume.

### Enquiry text for Cover Genius

> We would like to offer UK-origin parcel protection within EasyInvio.com web and WhatsApp journeys. Please connect us with shipping/logistics partnerships and an integration manager for XCover policy quotes/bookings and separate headless XClaim access. We need the approved product, retail pricing/disclosures, sandbox credentials, FNOL/evidence schemas, signed callbacks and authoritative settlement fields, with clarity on whether claims pay our platform or the customer. Please confirm onboarding, minimum commitments and sandbox costs.

No enquiry was sent on your behalf. No purchases, policy bookings, carrier labels or customer messages were made during this work.
