# WhatsApp UAT: provider audit and phone test script

For migration 056 and activation steps, see [Unified CX automation](unified_cx_automation.md). This earlier audit does not imply the shared database or provider settings have changed.

Audited 22 November 2026 against feature branch `feat/whatsapp-progressive-assistant`
(application commit `14d5aaf`). This is a source/configuration/read-only database
audit, not a claim that every provider accepted a fresh API request today.
No messages, carrier quotes, labels, payments or database changes were made by
the audit. The source paths inspected include `main.py`,
`backend/sendcloud_adapter.py`, `backend/automation_three_partners.py`,
`backend/provider_routing.py`, and the WhatsApp gateway, consumer and entitlement
modules. Secret values were neither printed nor included here.

## 1. What is actually configured

| Connection | Switch | Platform database record | Credential check | Quote readiness |
|---|---|---|---|---|
| Sendcloud v3 | Enabled | Active, TEST, not retired | Decrypts; identity binding and public/secret fields present | Native dynamic HTTP rate adapter |
| Sendcloud v2 | Enabled | Inactive, TEST, not retired | Decrypts; required fields present | Not selected; no verified method configuration exists |
| EasyPost | Enabled | Active, TEST, not retired | Decrypts; identity-bound nonempty key | Real HTTP rate adapter; provider permissions, route and currency still determine results |
| Shippo | Enabled | Active, TEST, not retired | Decrypts; identity-bound nonempty key | Real HTTP rate adapter; provider permissions, route and currency still determine results |
| Royal Mail direct | Disabled | No platform or tenant connection found | None to check | Not ready; strategy requires an issued contract implementation, not just credentials |
| Evri direct | Disabled | No platform or tenant connection found | None to check | Not ready; same contract requirement |

There are **29 active tenant account copies per active aggregator**. These are
platform-linked accounts, not 29 separate carrier contracts. Other inactive and
seed accounts exist; the `.example.invalid` accounts are inactive. There are no
LIVE platform connections. An Evri or Royal Mail service returned through an
aggregator is distinct from a direct Evri/Royal Mail integration.

`PROVIDER_ENVIRONMENT=TEST` and `DATABASE_ENVIRONMENT=SANDBOX` are set in the
local, UAT and production-reference files on disk. Real network requests in this
mode can return provider test/sandbox results; they are **not proof of a purchasable
production tariff**. The file called production `.env` is currently a reference
for a sandbox deployment. Vercel's label “Production” does not change that.
The deployed Vercel variable values were not inspected in this audit.

### Rates, routing and fallbacks

- `main.py` RatingService queries enabled tenant accounts. `provider_routing.py`
  runs configured direct providers first, then aggregators, and removes exact
  duplicate carrier/service/currency choices. It still queries aggregators for
  uncovered services. In this configuration there are no active direct providers.
- Sendcloud v3 calls `/shipping-options` with `calculate_quotes=true`. It accepts
  priced eligible services, not missing prices or estimated surcharges.
- Sendcloud supports v3 only. Retired rate adapters and upgrade UI have been removed;
  stored historical connection records are retained for audit.
- Guest UK estimates prefer v3, attempt at most two eligible platform accounts,
  and stop at the first successful provider. Their top two services are **not a
  comparison across every aggregator**. Shippo can be available in workspace
  quoting without being reached by the bounded guest path.
- Configured quote failures return diagnostics/handoff, not invented rates.
  Explicit `--local-preview` uses simulated UI quote data; guest live estimates
  are disabled there. That deliberate preview mode is not a credential fallback.
- Public estimates apply Starter's 18% baseline. Authenticated rates use the
  workspace's pricing policy. No code forces a price into a £3–£6 range, converts
  currencies silently or guarantees two services when only one is returned.

### Configuration gaps to address before claiming full end-to-end coverage

| Finding from current data/config | Required next step |
|---|---|
| Your current tester has one active verified workspace binding | Use a second approved, unbound phone for guest tests. A registered browser user is not automatically the same thing as a WhatsApp binding. Do not delete a working binding just to run this script. |
| Zero tenants opted into `public_status_lookup_enabled` | A deliberately selected test merchant must authorize public status publication before its positive public-lookup test can pass. Negative/private lookup already works. |
| No rows in `whatsapp_consumer_return_policies` | Merchant owner/admin must authorize a bounded return policy before automatic consumer returns can purchase anything. |
| Sendcloud v3 TEST label purchase is explicitly blocked; its booking integration ID is also missing | The lifecycle allows verified non-billable TEST label contracts only for EasyPost/Shippo. Adding a Sendcloud integration ID will not remove this TEST block. That ID is additionally required for a future deliberately enabled LIVE Sendcloud booking. Quoting does not require it. |
| None of the three active aggregators has partner webhook options configured | Configure provider callbacks and authentication for fresh tracking events; signed Gupshup chat callbacks alone do not supply carrier tracking. |
| `TRACKING_POLLING_ENABLED=false`; local/UAT run WhatsApp-only jobs | Chat reads recorded status; automatic tracking polling, other outboxes and notification workers will not run just because the WhatsApp worker runs. Test their specific worker/callback path separately. |
| All 32 sandbox tenants currently have enforced Command; two non-sandbox tenants have unenforced Starter | Starter and Velocity entitlement tests need dedicated sandbox test accounts with enforcement enabled. Editing a plan without enforcement will not test a rejection. Do not use non-sandbox accounts to bypass this. |
| XCover and insurer claims are disabled locally/UAT | Complaint support intake can work; insurer claim filing/payment is not an available acceptance outcome. Explicit insured-claim intake needs a valid eligible recorded policy. |
| Royal Mail/Evri direct are contract stubs without injected contracts | Provider-specific contract implementation/certification is needed. Merely setting their flags to true will still fail. |

For the three active aggregators, do **not** add duplicate credentials to `.env`
or hand-copy encrypted `public.carrier_accounts` rows. Platform connection
administration propagates scoped tenant copies. For a missing workspace, inspect
its active status, sandbox flag, account activity, environment and platform link.
An encryption key being available proves local decryptability, not upstream
credential validity. Provider-specific permissions and enabled carrier contracts
still need one successful quote for the actual route/currency.

## 2. Start here: one environment and a small set of fixtures

1. Choose Local **or** hosted UAT as the single WhatsApp consumer. Both share a
   database/queue/number. Pause the other environment's consumer before testing.
2. Local: keep ngrok running. From the local worktree run the established launcher:

   ```powershell
   .\.venv\Scripts\python.exe scripts/dev.py --whatsapp --hosted-whatsapp-paused --public-url https://al-agglutinative-hyperconscientiously.ngrok-free.dev
   ```

   The hosted consumer must actually be paused; the switch is an acknowledgement,
   not a remote pause command. Do not start a second process on port 8000.
3. Confirm `/health`, the current Gupshup callback URL, matching header
   authentication and the test-recipient allowlist. The inspected local booking
   and callback URLs use ngrok; `.env.uat` uses `https://uat.easyinvio.com`.
4. For hosted UAT, confirm its deployment commit includes the feature. A new
   local change does not automatically update the `uat` branch/deployment.
5. Send messages to the existing business sender **+447831450398**. Use your
   currently bound tester for merchant tests, an approved unbound tester for
   guest tests, and the recorded parcel recipient for automatic consumer returns.
6. In a sandbox workspace prepare the following fixture references. Replace
   angle-bracket placeholders below with values copied from that workspace:

   | Placeholder | Fixture |
   |---|---|
   | `<REF_DRAFT>` | DRAFT/QUOTED shipment, no manifest |
   | `<REF_BOOKED>` | BOOKED label, not manifested |
   | `<REF_TRANSIT>` | IN_TRANSIT shipment with recorded tracking events |
   | `<REF_DELIVERED>` | Single UK GBP parcel delivered within authorized return window, recipient phone matches the consumer tester, original measured packaging stored |
   | `<REF_INSURED>` | Shipment with an eligible recorded insurance purchase; ordinary shipping protection text is insufficient |
   | `<TRACKING_NUMBER>` | Exact carrier number of the test shipment; use a reference at least eight characters for public lookup |
   | `<SECURE_TOKEN>` | Actual unexpired, unrevoked capability token from a merchant-generated tracking share link |

Never literally send `<REF_...>` or `<SECURE_TOKEN>`. Fixture-dependent messages
cannot have one universal real reference. Keep secure links private.

Send `Cancel` before starting a new quote; this clears a draft, not a booking or
binding. Guest guidance counts all inbound messages from that sender/receiver
over 24 hours: message 31 gets a limit response, later ones may get no reply.
Split optional negative tests across days/approved testers rather than disabling
the budget. Each phone request/reply can still incur your provider's normal fee.

## 3. Exact phone messages and expected results

Every row also uses the common queue/delivery evidence in section 4. “Expected”
describes behavior, not exact generated prose or a guaranteed carrier price.

### A. Guest parcel quoting: unbound tester

| Step | Send this message | Expected behavior | Additional evidence |
|---|---|---|---|
| A1 | `Hello` | Short welcome and available help; no identity wall or model needed for greeting | Queue/outbox only; no shipment/purchase |
| A2 | `Quote 2kg from Leeds to London` | Ask for countries and missing dimensions; retain route/weight | `whatsapp_guest_drafts` encrypted draft |
| A3 | `Both UK` | Keep 2kg/route; request missing packed box size | Same guest draft, fixed 15-minute lifetime |
| A4 | `25x20x15 cm` | Live UK estimate from configured provider, up to two named priced services and prefill link; representative postcode note where applicable | `guest_rate_unavailable`/`guest_estimate_unavailable` only on failure; guest success is cached in process, not a tenant booking |
| A5 | `Quote 2kg from ls126ej, Leeds GB to B69 3EB Birmingham GB 25x20x15` | Normalize LS12 6EJ/B69 3EB; use PAF LEEDS/OLDBURY, not a town-mismatch rejection | Open prefill link and confirm canonical route/weight/dimensions |
| A6 | `Quote 2kg from Leeds LS12 6EJ GB to Paris 75001 FR 25x20x15` | International **workspace handoff**, preserving facts; guest international live rate shopping is not implemented | `/api/v1/public/quick-quote` verification; no invented international price |
| A7, optional | `Quote 2kg from Leeds ZZ99 9ZZ GB to London SW1A 1AA GB 25x20x15` | Reject malformed/nonexistent postcode or report PAF unavailable; no substitute presented as exact | No new shipment/label; distinguish bad input from lookup outage |

Open A5's fresh link: top-right Sign in, account creation without workflow field,
blank phone, country-name selector. Switching auth views retains edited quote
details. Login opens Create shipment, prefilled quote and editable account sender
contacts. Expired links must ask for a fresh quote, not authorize checkout.

### B. Authenticated workspace quotes and booking handoff

Use a verified bound OWNER/ADMIN/DISPATCHER in an enforced Velocity/Command
sandbox workspace, with active aggregator accounts and a suitable wallet.

| Step | Send this message | Expected behavior | Additional evidence |
|---|---|---|---|
| B1 | `Cancel` | Clear pending merchant draft; do not cancel a shipment | `conversational_messages` |
| B2 | `Quote 2kg from Leeds LS12 6EJ GB to Oldbury B69 3EB GB 25x20x15` | Collect exact premises/contact details if absent; then query enabled tenant aggregators | `conversational_messages`, `partner_unbound_quotes`, `whatsapp_quote_choices` |
| B3 | Reply `1` **only if that numbered premise is your intended test address** | Adopt selected PAF premise; repeat for delivery only when prompted | Merchant draft in conversational response; exact town/postcode authoritative |
| B4 | When asked for a contact, send `UAT Sender` or `UAT Recipient` | Collect missing contact name. If asked for a full address, reply `UAT Recipient; <actual test street>; Oldbury` | No default street should be invented from a city hub |
| B5 | `Book option 1` | Signed checkout link for the current unexpired displayed merchant offer; **no label purchase or charge from this message** | `whatsapp_quote_choices`; no new booking until web confirmation |
| B6 | Open link, sign in with the same workspace, review then explicitly confirm in web checkout | Choose EasyPost/Shippo for a verified TEST booking, subject to service/payment checks. Sendcloud TEST label purchase is explicitly blocked even if its integration ID is configured | `partner_shipping_offers`, `shipments`, wallet/reservation/ledger evidence and provider dashboard TEST result |
| B7 | `Quote 2kg from Leeds LS12 6EJ GB to Paris 75001 FR 25x20x15` | Collect full addresses/state where required; query eligible services, final customs/goods review in checkout | Quote diagnostics, same offer tables; never assume a GBP offer if provider returned only EUR/USD |

Available options depend on configured contracts, currency and route. A partial
result is not proof all three providers succeeded. Inspect issues per provider.
Do not repeatedly click Confirm to diagnose a pending booking. A fresh inbound
`Book option 1` is not the same thing as replaying one provider message ID.

### C. Two-tier tracking

| Step | Send this message | Expected behavior | Additional evidence |
|---|---|---|---|
| C1, unbound | `Track <TRACKING_NUMBER>` | Currently: no publicly available status because all merchants opted out. After deliberate fixture opt-in: fixed carrier/status vocabulary and up to three published applied events, no names/addresses/POD | `tenants.public_status_lookup_enabled`, `shipments`, `tracking_events` |
| C2, unbound | `Track NOTFOUND123456` | Generic unavailable/private response; not an assertion parcel does not exist | No cross-tenant disclosure or new shipment |
| C3 | `Track link <SECURE_TOKEN>` | Capability-scoped parcel status; creates a short-lived consumer session, not a merchant login | `tracking_share_links`, `whatsapp_consumer_sessions`, `whatsapp_consumer_messages` |
| C4, grouped link only | `Use parcel 2` | Switch only to a parcel already authorized by the capability | Consumer session; reject out-of-range parcel numbers |
| C5, bound merchant | `Track <REF_TRANSIT>` | Workspace-scoped recorded tracking and available guidance | `conversational_messages`, `tracking_events`; foreign workspace references must fail |
| C6, optional | Re-send a revoked/expired secure link | Unavailable/expired response; no retained authority from it | Revocation/expiry checked on `tracking_share_links` |

The secure consumer path has precedence when the token is explicitly pasted,
even from a merchant-bound phone. Subsequent tokenless messages from a bound
merchant phone can return to merchant routing. Use an unbound recipient phone
for the multi-message consumer return/support scenario.

### D. Paperless return and media: conditional, currently policy-blocked

Start with C3 using `<REF_DELIVERED>`'s actual secure link and recipient phone.

| Step | Send this message | Expected behavior | Additional evidence |
|---|---|---|---|
| D1 | `I want to return this parcel` | Ask explicit recipient/original-packaging confirmation; no purchase yet | Consumer session pending action |
| D2 | `Confirm return` | **Currently:** support case plus retailer-review message because no return policy exists. With authorized policy: verify recipient/window/single parcel/UK/GBP, entitlement, cap, rate and fresh merchant authority before proceeding | `support_tickets`, `whatsapp_consumer_return_policies`, `return_review_sessions`, `shipments` |
| D3, authorized fixture only | Complete returned secure payment link if customer-pay | Payment-required path produces no label until confirmed payment and carrier result | `return_customer_deliveries`, payment records, return shipment |
| D4, bound merchant alternative | `Return order <REF_DELIVERED>` | Merchant-authorized return workflow; can create a TEST return and affect wallet state. No generic guest authority | `conversational_messages`, return shipment, `return_review_sessions` where used |
| D5, result inspection | No additional message needed | If carrier supplies a supported paperless asset, deliver image/document view. Otherwise truthful printed-label fallback; never synthesize a fake QR | `logistics_media_assets`, queue parts, delivery status, return document links |

Automatic return success additionally needs an authorized warehouse, original
order metadata, current measured packaging, provider return support and payment.
Sendcloud TEST purchase restriction also prevents an end-to-end Sendcloud TEST return label; configuring an integration ID alone is insufficient. A return QR
is conditional carrier output, not a promise for every route or provider.

### E. Address-change triage, not automatic carrier mutation

| Step | Send this message | Expected behavior | Additional evidence |
|---|---|---|---|
| E1, guest | `Change my delivery address` | Sign-in/secure-link handoff; no shipment detail disclosed | Guest reply only |
| E2, bound | `Change delivery address for shipment <REF_DRAFT> to my corrected address` | DRAFT/QUOTED and no manifest: direct to workspace edit and fresh quote, no change or support ticket required by this branch | `conversational_messages`; unchanged shipment address/status |
| E3, bound | `Change delivery address for shipment <REF_BOOKED> to my corrected address` | Carrier-intercept/address review ticket, even before manifest: BOOKED is not treated like DRAFT | `support_tickets.cx_kind=SERVICE_REQUEST`, `issue_category=ADDRESS_CHANGE` |
| E4, bound | `Change delivery address for shipment <REF_TRANSIT> to my corrected address` | Same carrier-review intake; never claim redirect succeeded | Support ticket/outbox; no fabricated carrier update |
| E5, consumer | After secure link: `Please change my delivery address; I entered it incorrectly` | Capability-scoped support intake; no arbitrary address mutation | `tracking_customer_requests`, `support_tickets`, `support_message_outbox` |

### F. AI customs and volumetric/freight boundaries

| Step | Send this message | Expected behavior | Additional evidence |
|---|---|---|---|
| F1, guest | `What customs information and HS code details do I need for a cotton T-shirt sent to France?` | Curated/general customs guidance; **not** a structured, authoritative HS lookup | Queue/outbox; no customs declaration created |
| F2, guest | `How does volumetric weight work for a 40x30x20 cm box weighing 2kg?` | Curated explanation includes common divisor-5000 example (4.8kg); not a general exact freight calculator action | No carrier/AI call for curated advice path |
| F3, bound | `Quote 100kg pallet from Leeds LS12 6EJ GB to Oldbury B69 3EB GB 120x80x100` | Handoff to full cargo form; no parcel adapter pretending to offer freight | `conversational_messages`; prefill link, not a freight quote |

Structured HS classification **is implemented in web/API**, via
`POST /api/v1/agents/customs/suggest`, and guarded by Command's
`customs_hs_builder`. WhatsApp has no dedicated customs or calculate-weight action
in `ConversationalIntent`. General RAG help is not evidence that these actions ran.
Complete this coverage in the signed-in Command customs UI with description
`100% cotton knitted adult T-shirt`, review candidate evidence, and confirm the
classification before declaration. Inspect the request in browser Network and
the admin agent metrics endpoint; absence of model availability must not invent a
classification. An HS suggestion is not automatically a saved declaration.

For exact zero-carrier-cost arithmetic use the local API or the cargo form:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/logistics/weight -Method Post -ContentType application/json -Body '{"length_cm":40,"width_cm":30,"height_cm":20,"actual_weight_kg":2}'
Invoke-RestMethod http://127.0.0.1:8000/api/v1/logistics/cargo-weight -Method Post -ContentType application/json -Body '{"cargo_type":"PALLET","actual_weight_kg":100,"length_cm":120,"width_cm":80,"height_cm":100,"stackable":true}'
```

Expect parcel billable weight 4.8kg; configured stackable freight 319.680kg at
333kg/m³. Non-stackable freight also considers loading-metre floor weight.
These calculators are not carrier offers and normally create no database rows.

### G. Warehouse End-of-Day manifests

Use a paid, dispatch-authorized sandbox account with BOOKED unmanifested labels.

| Step | Send this message | Expected behavior | Additional evidence |
|---|---|---|---|
| G1 | `Manifest status` | Unmanifested carrier/warehouse totals plus recent manifest states | `shipments.manifest_id`, `carrier_manifests` |
| G2 | `Close manifest Evri` | Only use Evri if G1 lists exactly one matching batch; otherwise choose the actual listed carrier. Reject ambiguity or open dispatch preview | `carrier_manifests`, `carrier_manifest_events` |
| G3 | `Manifest status` | Show resulting status/document if completed. Unknown provider outcome stays submitted/unconfirmed | Same tables; log `Manifest outcome retained` for uncertain failures |

EasyPost uses native `/scan_forms`. Other configured paths generate an
**internal handover sheet**, recorded as `INTERNAL_HANDOVER`; a completed sheet
does not mean Sendcloud/Shippo accepted a native EOD close. Check `document_kind`.
Do not re-send G2 to reconcile an uncertain native submission; use status first.

### H. Complaint, damage, claim and refund intake

| Step | Send this message | Expected behavior | Additional evidence |
|---|---|---|---|
| H1, bound | `Complaint for shipment <REF_TRANSIT>: my delivery is delayed and I need an update` | Workspace-scoped complaint ticket; no invented delivery promise | `support_tickets` COMPLAINT/MISSING_DELAYED, `support_message_outbox` |
| H2, bound | `Complaint for shipment <REF_DELIVERED>: the parcel arrived damaged with broken contents` | Damage support case, not automatic insurer filing/payment | `support_tickets` COMPLAINT/DAMAGED |
| H3, consumer | After secure link: `My parcel arrived damaged and the contents are broken` | Capability-scoped intake; request text if insufficient detail; no cross-parcel access | `tracking_customer_requests`, `support_tickets`, consumer receipts |
| H4, eligible insured fixture only | `Claim <REF_INSURED> damaged The outer box was crushed and the contents were broken` | Explicit insurance intake where eligible: CLAIM_INGESTED and support case; otherwise eligibility/configuration error. No insurer submission/settlement claim | `insurance_claim_cases`, `insurance_purchases`, `support_tickets` |
| H5, bound | `Refund inquiry for shipment <REF_BOOKED>: please review the unused label` | Void/refund review case for unmanifested BOOKED label; no automatic refund | `support_tickets` REFUND_INQUIRY; wallet unchanged by intake |
| H6, consumer | After secure link: `Where is my refund?` | Return delivery/refund inquiry case; delivery is not proof merchant refunded | Consumer receipts, return shipment/events, support ticket |

Support alert staging and alert delivery are separate. With WhatsApp-only jobs,
do not mark merchant notification delivery PASS merely because an outbox row exists.
Photos sent into chat are not currently processed as insurer evidence; use the
secure claims/support UI for attachments.

### I. Starter versus Velocity versus Command

Use separate enforced sandbox accounts/bindings (or an operator-controlled test
fixture change), not guest messages pretending to be another plan. Two existing
non-sandbox Starter rows have enforcement off, so they cannot prove gating.

| Test | Exact message/action | Expected |
|---|---|---|
| I1, Starter bound | B2 quote message | Workspace quick-quote continuation and Velocity upgrade guidance; no paid WhatsApp quote action |
| I2, Starter bound | `Return order <REF_DELIVERED>` | Upgrade guidance, no return purchase |
| I3, Starter bound | `Close manifest Evri` | Upgrade guidance, no manifest close |
| I4, Starter bound | `Track <REF_TRANSIT>` | Tracking can work; HELP and TRACK_PACKAGE are exempt from the broad WhatsApp paid-feature guard |
| I5, Velocity bound | B2 then `Book option 1` | Paid WhatsApp quote/handoff allowed, still subject to dispatch role, account, price, expiry and payment checks |
| I6, Velocity/Command | D/G with valid fixtures | Paperless-return and EOD entitlements allowed; provider prerequisites still apply |
| I7, Velocity vs Command | Use web customs suggestion action in F | Velocity rejected for customs_hs_builder; Command allowed. A WhatsApp help answer alone does not test this feature gate |

Inspect `tenants.subscription_plan`, `plan_status`, period end,
`plan_enforcement_enabled`, global `SUBSCRIPTION_TIERS_ENABLED` and
`conversational_messages.response` status/action. Expired/cancelled plans can
effectively become Starter. Plan access never replaces OWNER/ADMIN/DISPATCHER
permissions. ACCOUNTANT should not gain dispatch powers from a paid plan.

### J. Other implemented chat checks (optional)

- `Top up 5 GBP` on a paid, dispatch-authorized bound account: Stripe checkout
  link, no payment merely from chat. Inspect checkout/payment/wallet records only
  after explicitly completing Stripe test checkout.
- `How do I connect Shopify to EasyInvio?`: bounded documentation/RAG answer;
  inspect agent metrics if a model was needed. No store created by asking.
- `What can you do?`: menu; `Thanks`: short acknowledgement, no model required.
- Explicit `Register` on a fresh unbound test phone starts the implemented
  Business/Individual onboarding flow. Follow its own prompts and genuine
  email/phone codes; never use illustrative codes as valid credentials. This
  creates auth/tenant/binding records, so run only for an intentional test account.
  Inspect `whatsapp_registration_queue`, `whatsapp_registration_receipts`,
  `app_user_profiles`, `users`, `tenants`, `whatsapp_bindings`.

## 4. Where to look: common evidence and safe SQL

Local logs: launcher terminal and, if started with redirected output,
`local-whatsapp.log` / `local-whatsapp-error.log`. For hosted UAT select the
**actual Preview deployment's web function logs**, then its WhatsApp worker logs;
the old `logistics-worker` warning stream alone is not webhook evidence.

Useful log strings:

- `gupshup_callback_received`, `gupshup_callback_accepted kind=...`;
  `gupshup_callback_rejected status=...` and
  `gupshup_callback_storage_unavailable` diagnose ingress failures.
- `whatsapp_job_needs_review`, `gupshup_job_needs_review`,
  `whatsapp_queue_unavailable`: worker/reconciliation failures.
- `Provider failed ... code=...`: authenticated per-provider failure.
  Guest lookup failures use `guest_rate_unavailable` / `guest_estimate_unavailable`.
  Guest logs may require INFO logging to be visible.
- `UPSTREAM_AUTHENTICATION_REJECTED`, `NO_ELIGIBLE_PRICED_SERVICES`,
  `NO_RATES_IN_REQUESTED_CURRENCY`, `UPSTREAM_TIMEOUT` distinguish different failures.

In Supabase SQL Editor run read-only queries. Do not select raw encrypted payloads,
credentials, tokens or full response bodies when sharing results.

```sql
-- A. Provider readiness, without credential values.
SELECT id, api_base_url, environment, is_active, retired_at
FROM public.platform_carrier_connections ORDER BY api_base_url;

-- B. Common ingress/reply evidence; note the UTC time of each phone test.
SELECT id, provider, state, error_code, created_at, updated_at
FROM public.whatsapp_inbound_queue ORDER BY id DESC LIMIT 20;
SELECT id, inbound_id, part_index, state, delivery_status, error_code, updated_at
FROM public.whatsapp_reply_outbox ORDER BY id DESC LIMIT 30;

-- C. Scope to YOUR workspace. Replace the placeholder with its UUID first.
SELECT id, channel, state, response->>'action_taken' AS action,
       response->>'status' AS result_status, created_at, completed_at
FROM public.conversational_messages
WHERE tenant_id = '<YOUR_TENANT_UUID>'::uuid ORDER BY created_at DESC LIMIT 20;

SELECT request_id, expires_at, jsonb_array_length(quote_payload->'rates') AS rate_count
FROM public.partner_unbound_quotes
WHERE tenant_id = '<YOUR_TENANT_UUID>'::uuid ORDER BY expires_at DESC LIMIT 10;

SELECT id, status, carrier_code, manifest_id, return_of_shipment_id
FROM public.shipments WHERE tenant_id = '<YOUR_TENANT_UUID>'::uuid
ORDER BY created_at DESC LIMIT 20;

SELECT id, shipment_id, status, cx_kind, issue_category, insurance_claim_id
FROM public.support_tickets WHERE tenant_id = '<YOUR_TENANT_UUID>'::uuid
ORDER BY created_at DESC LIMIT 20;

SELECT id, carrier_code, status, document_kind, total_shipments, error_code
FROM public.carrier_manifests WHERE tenant_id = '<YOUR_TENANT_UUID>'::uuid
ORDER BY created_at DESC LIMIT 10;

SELECT tenant_id, subscription_plan, plan_status, plan_enforcement_enabled,
       is_sandbox, public_status_lookup_enabled
FROM public.tenants WHERE tenant_id = '<YOUR_TENANT_UUID>'::uuid;
```

Queue `ACCEPTED` means Gupshup accepted the outbound API call, **not** that the
phone received it. Check `delivery_status`, provider callback events and the
actual phone. `whatsapp_delivery_attempts` / `whatsapp_delivery_events` also
record applicable provider-notification sends; absence there alone is not proof
the conversational queue failed. Check `support_message_outbox` and
`return_customer_deliveries` for their own delivery paths.

Guest drafts and rate caches need not leave permanent tenant quote rows. Guest
draft removal after completion is expected. Secure consumer tracking uses
`whatsapp_consumer_messages`, not authenticated `conversational_messages`.
Subscriptions are columns on `tenants`; there is no `tenant_subscriptions` table.

## 5. Pass/fail record and cost-conscious run order

Record: test ID, UTC time, environment/deployment commit, tester role/plan,
reference, observed result, queue ID, related ticket/offer/manifest ID, and
PASS / FAIL / BLOCKED. Do not paste secrets or secure links into public evidence.

Run A once with an unbound tester, B1–B5, C, E and H support intake first. These
do not require a label purchase. Then deliberately test one provider TEST booking,
one return and one manifest when prerequisites exist. Gupshup messaging fees,
PAF lookups and applicable model/API usage still apply. Use offline mocked tests
for duplicate callbacks, timeouts and large negative-input suites.

Do not mark blocked capabilities PASS because a friendly guidance response
appeared. Current blockers are guest international live pricing, positive public
lookup opt-in, consumer return policy, Sendcloud TEST label contract restriction and missing future LIVE booking integration ID,
carrier event ingestion, direct Royal Mail/Evri contracts, structured WhatsApp HS/
freight calculation, and Starter/Velocity fixture coverage. These require distinct
configuration or feature work; they are not all environment-variable changes.
