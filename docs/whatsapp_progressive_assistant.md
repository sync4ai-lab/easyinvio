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
- Say `I want to send a parcel 2kg from Leeds GB to London GB, 30x20x10 cm`:
  deterministic intent extraction, no model or rating-provider request. Missing
  route/weight facts are requested together. Partial facts survive for 15
  minutes in encrypted storage; follow-ups do not extend that expiry.
- UK parcel examples use the existing offline simulation. They are labelled
  samples, exclude VAT, and are not presented as Royal Mail/Evri published or
  live rates. Without verified public tariffs, carrier-specific promises would
  be misleading. International/freight requests hand off without invented prices.
- A 15-minute HS256 signed quick-quote link carries only supplied route/cargo
  facts, never merchant identity, a price commitment or booking authority.
  `/api/v1/public/quick-quote` verifies signature, purpose, audience and expiry.
  The login/signup page displays four editable fields and can copy them into
  the authenticated shipment form after rechecking expiry. It never requests
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

Quote dimensions accept `25x25x10`, `25X25X10` and `25?25?10`, with optional
`cm`. Unitless triplets are treated as centimetres, shown explicitly in the
sample estimate and editable before any live quote or booking. Other explicit
units are rejected rather than silently treated as cm.

Cities alone do not establish a country. After `Shipping quote for 4.5 kg from
Leeds to London`, the assistant retains weight and cities and asks only for
countries. `Both UK`, `GB to GB` and `GB, GB` complete those country slots.
A replacement full quote may change weight/size. A corrected city discards a
stale postcode parsed from an older turn. No city-to-country guess or paid
rating request is made in the guest sample path.

Guest estimates remain two offline illustrative options. Verified eligible
merchant conversations use the separate live connected-provider rating path,
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

Common quote extraction, UK sample calculation, tracking projection and curated
packing/battery/volumetric/customs advice are model-free and make no external
carrier calls. App FAQ uses the existing bounded/cached public-document RAG.
Public daily guidance limits are reused. Incoming provider charges cannot be
prevented by this bot; these controls do not guarantee a monetary spending cap.

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

No live migration, provider message, price lookup, purchase or refund was
performed while implementing this release.
