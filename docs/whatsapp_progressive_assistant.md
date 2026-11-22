# Progressive WhatsApp shipping assistant

This release builds on the verified webhook, encrypted queue, consumer CX and
merchant gateway. It does not create a separate booking/payment engine.

## Enable deliberately in Local/UAT

1. Apply `migrations/055_whatsapp_progressive_assistant.sql` once, after 054.
   It adds encrypted 15-minute guest drafts and a disabled-by-default merchant
   public-status policy. It makes no provider calls and grants no spending or
   public lookup consent. This file was tested on disposable PostgreSQL only.
2. Set `WHATSAPP_PROGRESSIVE_ENABLED=true` and
   `WHATSAPP_CONSUMER_CX_ENABLED=true` in the private local/UAT environment used
   by the selected web/worker pair. Restart local processes after changing it.
3. Retain the real Gupshup app, custom header authentication, approved templates,
   UAT test-recipient allowlist and the single-active-consumer procedure in
   `local_uat_production.md`. Do not deploy to Production before UAT acceptance.

## What guests can do

- Say Hello or ask an app how-to: existing concise welcome / public RAG.
- Say `Quote 2kg from Leeds GB to Birmingham GB 25x20x10`: grounded,
  model-free extraction followed by live platform-provider rates. Prompts ask
  for exact pickup and delivery town, postcode and country. Missing box size
  is requested instead of assuming a package for a live request.
- With only UK towns, the estimate uses the explicit representative postcode
  map in `backend/public_route_estimates.py`. Unknown towns use one bounded
  licensed exact-town Ideal Postcodes search. These are representative routing
  points, not geographically nearest locations or verified customer addresses.
- Supplied UK postcodes are normalized before PAF lookup (`ls126ej` becomes
  `LS12 6EJ`). A successful lookup makes the official PAF post town authoritative:
  a colloquial city such as Birmingham is replaced by the resolved post town,
  rather than rejected. Provider requests and quick-quote prefill use those same
  normalized postcodes and official towns. Merchant drafts and selected premises
  retain the same canonical values.
- A malformed or nonexistent supplied postcode requests correction and does
  not silently switch to a city hub. Representative postcodes are available only
  when no postcode was supplied. A PAF outage remains retryable, not evidence
  that the postcode is wrong. No LLM geocodes or invents an address.
- Guest pricing reads only active, non-retired platform connections in the
  server's provider environment. Sendcloud v3 is preferred; configured legacy
  Sendcloud methods or a supported default aggregator can be used as fallback.
  At most two connections are attempted. Merchant BYOC credentials, roles,
  wallet access and tenant pricing rules are never borrowed for a guest.
- The cheapest two distinct returned services are shown with real carrier and
  service labels, provider-supplied transit days (or explicitly unavailable),
  and the Starter 18% baseline markup using established monetary rounding.
  Prices are not forced into a target range. No rate is manufactured when the
  provider is unavailable. A configured TEST connection can return test-mode
  provider prices; validate LIVE connections separately before public launch.
- Sendcloud v2 needs verified configured method limits. Optional method fields
  `service_name` and `delivery_days` preserve verified metadata. If service names
  are absent, the read-only shipping-method catalogue is used. V3 preserves
  names from its shipping-options response. Country-only legacy tariffs may
  lack postcode-specific surcharges; full-address quoting remains mandatory.
- International/freight requests hand off without fabricated prices. Offline
  layout preview explains that live estimates are disabled; it does not invent
  numbers. Live failures return a useful retry/workspace handoff.
- A 15-minute HS256 signed quick-quote link carries only supplied route/cargo
  facts, never merchant identity, a price commitment or booking authority.
  `/api/v1/public/quick-quote` verifies signature, purpose, audience and expiry.
  The login/signup page displays four editable fields and copies them into
  the authenticated shipment form after sign-in and an expiry recheck. It never requests
  rates, buys postage or fills personal contact/street details automatically.
- `Track` asks for one tracking reference; invalid or unpublished references
  can be retried in the same 15-minute thread. Raw-reference lookup returns only
  exact matches for merchants who have explicitly enabled public status lookup.
  Ambiguous matches reveal nothing. Public lookup discloses only a fixed status,
  allowlisted carrier label and up to three applied scan times. Raw location
  strings are omitted because they may contain addresses rather than hub names.
- Existing secure tracking links retain their own capability checks, revocation,
  expiry and recipient/return-policy rules. Guest state never becomes a role.

## Phone quote input and follow-up replies

Quote dimensions accept `25x25x10`, `25X25X10` and `25 x 25 x 10`, with optional
`cm`. Unitless triplets are treated as centimetres, shown explicitly in the
route estimate and editable before any booking. Other explicit
units are rejected rather than silently treated as cm.

Cities alone do not establish a country. After `Shipping quote for 4.5 kg from
Leeds to London`, the assistant retains weight and cities and asks only for
countries. `Both UK`, `GB to GB` and `GB, GB` complete those country slots.
A replacement full quote may change weight/size. A corrected city discards a
stale postcode parsed from an older turn. Countries are never inferred from
city names. Completing a UK parcel request now performs a bounded provider
rate request and may incur provider lookup fees.

Guest estimates show up to two live platform-provider options. Verified eligible
merchant conversations use the separate authenticated connected-provider path,
which still requires its usual address, parcel, role and plan checks.

## Enable optional public reference lookup

A directly signed-in active merchant Owner/Admin may call:

```text
PUT /api/v1/whatsapp/public-status-policy
Content-Type: application/json
Authorization: Bearer <existing app session>

{"enabled":true}
```

Use the normal authenticated app API mechanism; do not copy session tokens into
chat, source code or public URLs. Platform assistance cannot grant this consent.
Send `{"enabled":false}` to revoke. Until enabled, guests can still use their
secure parcel link; no global shipment-number search is opened by migration.

## Existing merchant plans and roles remain authoritative

- Starter: welcome, public guidance and signed quote-form handoff; authenticated
  own-workspace tracking is not blocked by the WhatsApp booking entitlement.
- Velocity/Command: existing conversational live rates, signed checkout, wallet
  checks and eligible returns. A WhatsApp quote shortlist is limited to three;
  one initial signed link is retained, and Book/Select N chooses a stored option.
- HS builder, custom margin rules and BYOC retain their Command gates. Carrier
  advisor retains its Velocity gate. Requests offer an entitled workspace
  handoff or contextual pricing link; they do not silently execute automation.
- EOD manifests remain Velocity/Command, consistent with the published pricing
  and current entitlements, rather than moving an advertised feature to Command.
- Address change requests are separate from Returns FAQ. Unbooked drafts link
  to workspace review/requote; booked shipments create carrier-review cases.
  The bot never claims an address was changed or an intercept was accepted.
  Dispatch-role checks still apply to merchant address requests.
- Expired/cancelled plans, user roles, usage quotas, funding, manifest/carrier
  restrictions and explicit confirmation remain checked by existing services.

## Cost controls and limits

Quote extraction and curated advice are model-free. Complete guest quotes now
make provider requests. An in-process single-flight cache holds responses for
120 seconds (128 entries); address resolutions last 300 seconds (256 entries).
Each worker process permits up to 12 uncached estimate attempts per minute,
with at most two provider connections attempted and an eight-second overall
budget. Failures are cached too. Existing durable per-sender daily message
limits still apply. These process limits reset on restart and are not a global
monetary cap. Licensed PAF and aggregator lookups may have their own charges.
App FAQ retains bounded/cached RAG. No external lookup is done for Hello.

BOOKING_PAGE_URL is authoritative. Link creation refuses an empty/invalid origin
and never reads Host or forwarded headers. An explicitly configured UAT or
Production origin survives `scripts/dev.py --public-url`. Local loopback
configuration may deliberately use the explicitly supplied HTTPS tunnel for
phone testing. The quick-quote token contains only supplied fields: substituted
hub postcodes never silently become customer postcodes in the booking form.
The mobile form prefills automatically after sign-in, without auto-rating or
buying postage. Full delivery addresses and final prices must be confirmed.

Text responses are consolidated to at most 1,440 characters with a complete
action URL preserved where possible. Native return media can need a separate
message. Character limits reduce verbose/multipart application responses; they
do not redefine Meta/Gupshup billing, and WhatsApp is not SMS segmentation.
Critical estimate, confirmation and privacy warnings are deliberately retained.

## UAT examples

1. Hello → welcome; no model call.
2. Quote to London → one missing-slot prompt; then supply weight and both
   countries. Check the signed handoff and four fields on a narrow phone screen.
3. Modify/expire the quick-quote token → rejected; no automatic rates or purchase.
4. Track → invalid reference → retry → merchant-opted-in test reference → only
   status/carrier/times. Revoke public policy and repeat → no published status.
5. Use another merchant's UUID without an opt-in/capability → no private record.
6. How to pack fragile glass / connect Shopify / change delivery address → three
   different routes: curated advice / RAG / verification or carrier-review triage.
7. Starter booking → quote-form link and upgrade guidance; Velocity/Command
   permitted operations still require their existing role and confirmation.
8. Repeat the same inbound message ID → receipt replay, no duplicate mutation.

No live provider message, price lookup, purchase, refund or migration was run
while implementing this update. Provider account types/environments were checked
using a read-only database query. HTTP adapter tests use synthetic responses.

Provider references: https://openapi.ideal-postcodes.co.uk/ and
https://sendcloud.dev/docs/shipping/shipping-rates

## Live estimate validation

The affected WhatsApp/public/prefill/PAF/adapter suite passed 176 tests. A separate
adapter/hosting/logistics run passed 59 tests and found one existing failure:
`tests/test_logistics.py::PreviewHTTPTests::test_audit_and_customs` expects an
`hs_code` that the unauthenticated preview response does not provide. The same
failure was reproduced on unchanged commit `8571e05` in an isolated checkout.
No customs behavior was changed for this task.

All 26 inline JavaScript blocks passed syntax checks. A 390x844 headless Edge
check used a mocked signed-token verification response, confirmed automatic
prefill at the authenticated UI transition and `/workspace` path, and blocked
external traffic and all rate/purchase requests. This is not a real sign-in or
live Sendcloud acceptance test. Test responses include several priced real-
shaped Sendcloud services and verify the cheapest two, names, transit and
Starter markup. Provider account existence was checked read-only; no carrier
rate request was made while implementing the change.

The postcode-authority follow-up passed 101 focused offline tests. Its exact
regression message is `Quote 2kg from ls126ej, leeds gb to B69 3EB birmingham gb
25x20x15`. Mocked PAF resolves LEEDS/OLDBURY; the real Sendcloud adapter receives
LS12 6EJ/B69 3EB with those official towns, and the signed prefill contains the
same canonical route. Malformed/nonexistent postcode and merchant premise
selection cases are covered. No real postcode or carrier lookup was made.
