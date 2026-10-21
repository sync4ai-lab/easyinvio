# Security and financial invariants

Identity, tenant authorization, immutable pricing and externally confirmed outcomes are shared infrastructure. Reusing them is necessary for every web, WhatsApp, storefront, marketplace, admin-assistance and return feature. Do not create parallel wallet math or let model output become authority.

## Identity and sessions

The website authenticates through the application identity gateway backed by Supabase Auth. An application session references an encrypted provider access/refresh-token envelope in `app_auth_sessions`. The signed application access token is held in browser memory. Initial renewal windows are fifteen minutes, limited by provider expiry; renewal has an eight-hour absolute session limit. An expired application session cannot be resurrected just by refreshing the page. Provider refresh credentials stay on the server.

Normal authentication validates signatures/claims and active workspace membership rather than trusting tenant_id, role text, sender_id or a UI tab. The platform super-admin allowlist is distinct from tenant OWNER/ADMIN roles. A user with ambiguous multiple memberships is not silently assigned a workspace at login. Recovery links are constrained to configured origins and verified token/identity checks; passwords and OTPs are not ordinary application table fields.

The browser clears session-scoped forms, quote choices, order drafts, chat and modal state on logout or identity/workspace change. Async callbacks must compare their original scope/generation before rendering; a response from the prior tenant must not populate the new workspace.

## Tenant isolation and RLS

Every domain lookup/update binds the authenticated tenant. UUIDs do not authorize access. Cross-tenant tracking references, offer IDs, shipment IDs, payment carts, catalog IDs and claim IDs must resolve within the caller’s scope. Store-triggered returns additionally require the original shipment’s configured store ID.

Private backend tables enable RLS and revoke ordinary PUBLIC/anon/authenticated access where declared. The application DB role is privileged and can bypass RLS, so database RLS alone does not protect server queries that omit tenant predicates. Direct browser-database permission checks and authenticated API tests are separate acceptance gates. Inspect exact DDL and role checks rather than assuming every table has the same policy.

`validate_tenant_query` rejects a mismatched tenant selector on routes that call it. Other endpoints can legitimately ignore an unused query parameter and return only authenticated tenant rows; the security assertion is absence of foreign records plus the route’s actual contract, not a universal assumption that every request must return 403.

## Administrative assistance

Support sessions retain actor Auth ID, selected tenant, controlled operator membership, reason, hashed bearer binding, creation/expiry and revocation. Events record session starts/ends and request starts/finishes. The append-only event trigger disallows normal event updates/deletes. An active support context uses selected workspace owner functionality without issuing the target employee’s JWT or concealing the original administrator.

Assistance is time-limited and revocable, and renewal cannot extend beyond the implemented maximum. Keep session scoping and audit persistence on new routes. A required write-ahead audit failure must not silently become an unaudited privileged write. Ordinary service/registration/return receipts additionally retain the original requesting actor.

## Decimal and money representation

Use Decimal from validated strings or exact integral values. The strict shared decimal helper rejects floats, booleans, malformed numbers, NaN and infinities. JSON payloads should send monetary/weight fields as strings where required by the schema; serialization does not justify a float conversion before quantization. SQL `numeric` columns preserve their declared scale; inspect table DDL because weights, dimensions and money have different limits.

Use explicit rounding rules at the domain boundary. The protection estimate calculates one percent, quantizes pennies with ROUND_HALF_UP and applies a GBP 1.20 minimum. Zero/negative declared value and values above GBP 5,000 are rejected. GBP 120.50 produces an estimated GBP 1.21. That calculation returns uninsured/unavailable disclosures and does not buy cover.

Business rates use matching priority margin rules and their declared percentage/fixed/minimum behavior. Individual rates bypass those rules and snapshot one global percentage/version, defaulting to exactly 20.00% only for an absent configuration row. No business minimum-markup floor is added to that consumer rule. A stored price remains the price for that immutable offer until its expiry; later configuration affects future quotes.

Do not add different currencies together. Invoice comparisons and quote/ledger totals must retain source currency. Current shipping checkout excludes tax; a profile/persona flag alone cannot supply a jurisdiction, tax registration or rate. No new tax collection should be inferred from persona support.

## Reservation and purchase lifecycle

![Booking and financial outcomes](booking_lifecycle.svg)

1. Validate workspace/role, prepared contents, selected offer, expiry, credential snapshot and supported environment before money or purchase.
2. Acquire the existing order/booking advisory lock and recheck authoritative shipment state. A repeated request can replay the exact known result; another selected offer cannot replace a submitted purchase.
3. In the financial transaction, lock the wallet/billing row and create the immutable reservation. Available prepaid credit is balance minus reserved balance; never use an unlocked read to authorize spend.
4. Mark the reservation submitted before a carrier mutation. If no submission occurred, release through the native NOT_SUBMITTED path; do not issue a compensating balance UPDATE by hand.
5. A confirmed label plus the native settlement path captures the exact reservation and persists tracking/documents. Definitive provider rejection releases it. Timeout, interrupted mutation or ambiguous response retains the reservation and native reference for reconciliation.
6. GET-based confirmation/polling may resolve a submitted purchase; it does not buy a second label. Capture/release/refund idempotency and ledger entries remain owned by FinanceEngine/native lifecycle.

Cancellation/refund is another explicit lifecycle. A provider accepting a cancellation request is not proof of final cancellation or a bank refund. Wallet credit follows verified final outcome and the original captured reservation; unsettled state remains reviewable.

## Stripe and customer payment

Checkout URLs must be validated Stripe URLs and created for the authenticated workspace. The verified amount/currency/customer/mode and receipt, not the browser’s redirect parameters, authorize funding. Stripe snapshot events have durable reconciliation; replay must not credit a wallet twice.

Card label baskets select exact prepared offers in one supported currency. They fund the workspace for that basket and purchase only after verified payment. Partial booking leaves unused credited funds in that wallet. CUSTOMER_PAY returns use the same mechanism: an authorized merchant OWNER/ADMIN creates a customer payment link, and verified customer card payment funds the merchant’s return basket. This is not a separate consumer wallet or automatic bank refund.

Sandbox hooks, TEST carrier credentials, SANDBOX database settings and tenant sandbox markings must align. An ordinary Sendcloud account does not acquire a non-billable test-label contract by setting a local TEST flag. Test keys for one provider do not establish a sandbox for another.

## Return and QR safeguards

One full-parcel reverse-logistics receipt per original shipment prevents duplicate returns through new command IDs. A repeated command must match its original content/actor/source. PROCESSING/REVIEW_REQUIRED does not mean safe to buy again. A warehouse changed/archived after quoting requires review; the version and exact normalized address are rechecked before purchase.

Sendcloud labelless is requested only on explicitly capable returned options. EasyPost USPS QR form creation is an optional, durably fenced post-purchase mutation. Its failure cannot turn a confirmed label into a definitive purchase failure, release captured funds or cause another buy. Later status recovery uses GET only.

Document URLs are HTTPS, tenant-bound and fetched only through approved hosts with redirects disabled and byte limits. The QR proxy admits only the supported PDF/PNG/JPEG representations; it does not execute SVG/HTML from a provider. Shared drop-off links use a dedicated issuer/audience, tenant/shipment scope and at most 24 hours, granting one document rather than general login. Query tokens must remain redacted from logs; a local/expired provider asset may still need support even while an application share token is valid.

## External input and secret handling

Twilio requests need valid account/signature and an exact public callback URL. Provider-specific tracking webhooks and Stripe/store/CRM callbacks have different signing contracts; do not reuse one provider’s validation for another. Signed normalized return webhooks require an enabled connection, active configured operator, timestamp within five minutes and HMAC over exact bytes including store identity.

Fernet-encrypted server credential envelopes are bound to their configured workspace/connection identities. A saved quote includes connection identity/fingerprint; rotating credentials requires new quotes for new purchases. Historical connection access is permitted only in verified lifecycle paths and is not a general bypass for disabled accounts.

Never commit `.env`, key files, JWTs, webhook secrets, customer exports, raw database dumps or provider bodies containing credentials. Logs use bounded diagnostic codes and redact query secrets. Seed/probe scripts and SQL are not safe read-only operations merely because they are in the repository. No financial retry should be added as a generic HTTP retry decorator.

## Encrypted conversational transport

Migration 043 stores exact signed inbound form bytes and outgoing parts under the existing Fernet key ring; both can contain OTPs and personal details. Ordinary browser roles have no table access. Keep required historical keys for outstanding rows and establish retention for completed payloads and review evidence. The canonical inbox SHA-256 includes every signed field/value/count while tolerating equivalent field ordering. Same SID/different content is rejected.

Queue claims and SENDING markers commit before external calls. A timeout never authorizes an action or outbound-message replay. PROCESSING/SENDING/REVIEW_REQUIRED can block subsequent messages on that thread until reconciled. READY resumes unsent parts only. Free-form messages older than 23h59m are rejected, and backlog processing does not extend the original inbound messaging window. A return media URL must be this application's HTTPS scoped proxy with a valid token for that same shipment; carrier document allowlists and token expiry still apply.

## Manifest membership and signed assets

Migration 044 constrains manifest membership to the same tenant and carrier account and makes assignment/MANIFESTED transitions server-owned. Audit events are append-only. Manifest creation checks current membership or active audited assistance, workspace/environment, exact origin and booked state. The cancellation lock is shared before claims commit, and a claimed shipment cannot be voided through the ordinary cancellation path. No wallet or financial-ledger write is added.

SUBMITTED preserves membership during uncertain provider creation. A PDF can complete only with exact native tracking membership/approved document or an explicitly internal handover sheet. Native ScanForm references are not fabricated carrier tracking IDs. Completing a document does not regress IN_TRANSIT/DELIVERED or imply physical pickup.

QR images live in a private bucket with immutable tenant/shipment/content-hash keys and 24-hour read capabilities. The default bucket has a restrictive browser-role policy as well as private visibility. Different custom buckets require equivalent provisioning. Storage keys remain server-side. Signed manifest downloads grant only one completed PDF; they do not authenticate a workspace. Signed Twilio failed statuses can resolve transport uncertainty, but cannot rerun a booking or move money.
