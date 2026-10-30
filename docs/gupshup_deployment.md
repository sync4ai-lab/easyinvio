# Controlled Gupshup deployment ? EasyInvio

Prepared 27 October 2026. Local implementation only: no push, deployment, hosted migration, registration, account mutation or real message has been performed. Keep sending paused. Your latest screenshots confirm self-service at apps.gupshup.io and an EasyInvio app with a created API key. Settings shows App Type Sandbox; use its App ID, not the separately reported Namespace or Customer ID. No Partner/ISV account is needed for one EasyInvio sender serving verified merchants. Separate merchant-owned senders would require a different onboarding design.

## 1. What this changes

Selected-provider transport serves chat/signup replies, opted-in merchant support alerts, sender milestones and payment-gated return instructions. Gupshup uses the same existing tenant, role, verification, quote, checkout, wallet and return services. The external Gupshup callback acknowledges with an empty 200 after durable storage; business actions happen in logistics-worker. Internal XML formatting remains an implementation detail.

Twilio remains available for compatibility and its original signed callbacks. There is no automatic failover. Existing encrypted Twilio inbox/reply records retain their identity. Migration 049 assigns existing proactive WhatsApp rows to Twilio; new, unassigned proactive rows use the selected provider. Provider-bound rows cannot silently switch transports. Never force an uncertain row back to READY.

Every WhatsApp path checks the same pause and tester allowlist, including signup and secure-media fallback. Email keeps its existing delivery configuration and test-recipient controls. A transport can be real while DATABASE_ENVIRONMENT=SANDBOX and PROVIDER_ENVIRONMENT=TEST. This does not authorise live Stripe or carrier purchases.

## 2. Verified product/API contract and limits

This adapter uses **self-service v2 Gupshup-format payloads**, not Partner APIs, Bizgate bearer-token APIs or Meta v3 passthrough payloads.

| Operation | Implemented contract |
| --- | --- |
| Text | POST https://api.gupshup.io/wa/api/v1/msg; apikey header; form channel, source, destination, src.name, message JSON |
| Image | Same endpoint; image with originalUrl, previewUrl, caption for recognised image paths |
| Document | Same endpoint; file with url and filename; otherwise use a secure document link |
| Approved template | POST https://api.gupshup.io/wa/api/v1/template/msg; approved template id and ordered params; never a Twilio HX identifier |
| Acceptance | submitted plus messageId; acceptance is not delivery |
| Inbound | app, version=2, timestamp, type=message, payload id/source/type/payload; phones required |
| Delivery | type=message-event; enqueued/failed identify the Gupshup ID, later sent/delivered/read use gsId plus WhatsApp ID; aliases retained |
| Callback response | Empty 200 only after persistence; busy storage returns 503 for provider redelivery |
| Session | Chat needs a trusted inbound receive time under 23h59m old; proactively sent support/shipment/return notices always require configured approved utility templates |
| Retry | No automatic Gupshup retry after 429, timeout, 5xx, malformed acceptance or ambiguous result. Uncertain attempts require reconciliation. Twilio's existing bounded explicit-429 retry policy remains. |
| Idempotency | No request-level exactly-once guarantee is assumed. Inbox uniqueness, encrypted replies, committed send fences and provider/account-scoped attempt keys prevent automatic replay. |
| Monetary cost | Attempts store category/template/provider/tenant and IDs. Cost remains NULL/UNKNOWN; this is not a reconciled billing or tenant-budget system. |

Your supplied self-service **Add Webhook** screenshot explicitly offers **Includes headers** and says a configured key/value is delivered with webhook events. The recommended mode is therefore **HEADER**, using a randomly generated secret in the fixed header `X-EasyInvio-Webhook-Token`. This is customer-configured shared-secret authentication, not an invented provider signature or HMAC. The application requires exactly one header value and compares it in constant time; tokens must be at least 32 bytes.

Optional SOURCE_IP and HEADER_AND_SOURCE_IP modes additionally use provider-confirmed callback IPs. The application checks the actual socket IP locally. On Vercel an IP check requires VERCEL=1 and exactly one platform-overwritten x-vercel-forwarded-for address; arbitrary X-Forwarded-For is not trusted. Enable Vercel's system variables for IP mode. Add a matching path-scoped firewall rule as defence in depth. Shared-secret mode does not require trusting a forwarded client IP. App/source payload fields alone never establish authentication.

Official sources checked:

- [Self-service message API](https://docs.gupshup.io/reference/msg)
- [Template messages](https://docs.gupshup.io/docs/template-messages)
- [Delivery event payloads](https://docs.gupshup.io/docs/message-events)
- [Subscription API](https://docs.gupshup.io/reference/updateanexisitngsubscription)
- [2025 platform changes: subscriptions replace old callback configuration, apps dashboard redirect does not itself change APIs](https://support.gupshup.io/hc/en-us/articles/42866242419609-Gupshup-Technical-and-Policy-Updates-2025)
- [Published callback IPs](https://support.gupshup.io/hc/en-us/articles/56952275875097-IP-Addresses-for-Webhook-Delivery)
- [Vercel protected request headers](https://vercel.com/docs/headers/request-headers)
- [Daemons use project Production variables](https://vercel.com/changelog/vercel-daemons-is-now-in-public-beta)
- [Environment changes require a new deployment](https://vercel.com/docs/environment-variables)

The published callback list checked on this date is 34.202.224.208, 52.66.99.126, 15.206.217.7, 3.126.35.181 and 3.6.228.131. These are provider network addresses, not customer data. They are deliberately not automatically enabled. Do not substitute Partner IP lists, broad CIDRs or media-fetch IPs.

## 3. Your Gupshup account ? manual steps

1. Your EasyInvio app has now been created. Open that one app; do not create an app for every merchant.
2. Record the exact **App name**, **App ID** and **source/sender number** shown inside that app. App ID is not the dashboard Customer ID or Namespace; use the field explicitly labelled App ID in Settings. A tester's phone is not the business source number.
3. Open the app's API credentials/settings. Find the credential specifically documented for the self-service `/wa` API's **apikey** header. Store it privately in GUPSHUP_API_KEY. The dashboard's **Account Secret** may be part of token provisioning: do not assume it is this API key. If your app offers only Customer App Token/Bearer authentication, leave this integration disabled and confirm that credential's supported endpoint with Gupshup. Do not paste any secret in chat. Your screenshot confirms a created API key, but its value has not been tested. Its banner announces API-key deprecation on **31 March 2027**. The implemented transport uses the current apikey contract. Customer Access/App Token generation, renewal and bearer authentication are not implemented here; plan that separate verified migration before the deadline rather than entering a 24-hour token as a permanent API key.
4. For initial sandbox tests use the app's own displayed tester/opt-in/join instructions and its displayed source number. Do not reuse any Twilio join phrase or number. Sandbox capabilities and available templates may differ; unavailable proactive templates stay blocked/held.
5. For the intended operational sender, use Gupshup's onboarding flow to register a number controlled by EasyInvio. Complete Meta business/WhatsApp account, display-name and phone verification requirements shown for your account. No owned working Twilio sender exists to migrate. Do not register the founder's personal WhatsApp number casually; existing app/coexistence eligibility must be checked with Gupshup first.
6. Request approved **utility** templates for support case messages, sender shipment updates and return instructions. Confirm language, exact approved ID, placeholders and any text-length limits. Generic templates made almost entirely of a body placeholder may be rejected; adapt the wording with Gupshup without changing parameter order.
7. Open the app's **Webhooks/Subscriptions** section (new apps use subscriptions; do not follow obsolete single callback API instructions). Add one active subscription for:

   `https://uat.easyinvio.com/api/v1/integrations/whatsapp/gupshup/webhook`

   On the exact form you shared, enter **Webhook Name (Tag)** = `EasyInvioUAT`, the callback URL above, and select **Gupshup format (v2)** instead of the currently selected Meta format (v3). Under **Message Events**, select exactly **Message, Enqueued, Failed, Sent, Delivered, Read**. Leave Delete, Billing, Flow Message, Payments, Messaging Handovers and Others unchecked for this initial setup. Do not use Select all.

   Tick **Includes headers**. Add key **X-EasyInvio-Webhook-Token** and a strong random private value. Generate it in your local PowerShell terminal with `.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"`, then privately save the same value in GUPSHUP_WEBHOOK_TOKEN locally and in Vercel Production. Do not put the API key in this webhook header and do not use a URL query secret. Set GUPSHUP_WEBHOOK_AUTH_MODE=HEADER. Save the subscription only after matching web/worker code and the database migration have been deployed and the endpoint is reachable; the old deployed app does not yet contain this new route. Avoid duplicate subscriptions to the same app/URL. v3 Meta format is not supported here. Do not subscribe billing/flow/payment events expecting new features; unsupported types fail validation.
8. Verify the saved custom header and v2 subscription match this configuration. For optional IP filtering, obtain confirmation of callback delivery IPs. Keep enabled=false until deployment prerequisites and this origin protection are ready. A source IP cannot be replaced by checking the payload's app field.
9. Trial/sandbox access is not full production registration. Real transport may incur charges even for shipping TEST data. Confirm your Gupshup/Meta rate card and wallet funding before manually sending.

## 4. Exact environment settings

Use the same private values in local .env when testing locally and in **Vercel ? EasyInvio project ? Settings ? Environment Variables ? Production** for UAT hosting. Do not edit .env.example with real values. Click Add/Edit, enter the name and value separately, choose Production and Save. JSON values need actual brackets/quotes, with no enclosing shell quotes in the Vercel value box.

| Variable | Secret? / source | Safe setup value / purpose |
| --- | --- | --- |
| WHATSAPP_PROVIDER | No; operator | GUPSHUP intended, TWILIO only for explicit compatibility rollback |
| GUPSHUP_PRODUCT | No | SELF_SERVICE; no Partner/Bizgate mixing |
| GUPSHUP_ENABLED | No; operator | false until prerequisites complete |
| GUPSHUP_API_KEY | **Secret**; app's compatible /wa API credentials | Private value; no Twilio credential required |
| GUPSHUP_APP_NAME | No; app | Exact case-sensitive API app name |
| GUPSHUP_APP_ID | No; app | Exact app ID, not Customer ID |
| GUPSHUP_SOURCE_NUMBER | Operational identifier; app | Business sender E.164, plus and country code |
| GUPSHUP_WEBHOOK_URL | No | Exact UAT URL above, no query string |
| GUPSHUP_WEBHOOK_AUTH_MODE | No | DISABLED initially; HEADER recommended with Includes headers; optional SOURCE_IP or HEADER_AND_SOURCE_IP |
| GUPSHUP_WEBHOOK_TOKEN | **Secret**; locally generated random value | Same 32+ byte value as the configured X-EasyInvio-Webhook-Token header; required for HEADER modes |
| GUPSHUP_CALLBACK_IPS_CONFIRMED | No; operator | false initially; true only after provider confirmation |
| GUPSHUP_CALLBACK_IPS | No; provider-confirmed | [] initially, then JSON array of exact callback IP strings |
| WHATSAPP_UAT_MODE | No | true even though Vercel hosting says Production |
| WHATSAPP_TEST_RECIPIENTS | **Personal data**; consenting test phones | [] initially; private JSON E.164 array. Applies to ALL WhatsApp paths |
| WHATSAPP_OUTBOUND_PAUSED | No | true until explicitly performing the manual checks below |
| GUPSHUP_TEMPLATES | No secrets; approved app template definitions | {} initially; JSON mapping below |
| WHATSAPP_QUEUE_WORKERS | No; existing | Keep 2 unless operational capacity requires another value |
| WHATSAPP_BRAND_NAME | No; existing | EasyInvio.com |
| WHATSAPP_ONBOARDING_ENABLED | No; existing | Keep false unless testing the existing signup flow |
| WHATSAPP_ONBOARDING_DAILY_LIMIT | No; existing | Preserve existing limit; default 100 |
| SUPPORT_WHATSAPP_ENABLED | No; existing | false until SUPPORT template and verified opt-in ready |
| SHIPMENT_WHATSAPP_NOTIFICATIONS_ENABLED | No; existing | false until SHIPMENT template and sender consent ready |
| RETURN_WHATSAPP_ENABLED | No; existing | false until RETURN template and customer permission ready |
| CREDENTIAL_KEYS | **Secret**; existing encrypted queue key ring | Preserve existing keys and IDs; never regenerate/delete old keys casually |
| QUOTE_LINK_SECRET | **Secret**; existing | Preserve existing signing key, at least 32 bytes |
| BOOKING_PAGE_URL | No; existing | Existing HTTPS UAT checkout base; keep authenticated checkout |
| DATABASE_ENVIRONMENT | No; existing | SANDBOX |
| PROVIDER_ENVIRONMENT | No; existing | TEST |
| STRIPE_ENABLED and Stripe keys | Mixed; existing | Preserve current disabled/test configuration; never enable live payments for this migration |
| RUNTIME_ROLE | No; existing | WEB for HTTP via vercel.json; worker_runtime overrides WORKER before importing main |
| VERCEL | System variable | Platform-provided 1 on Vercel; enable automatic system environment exposure; never fake it for local ingress |

Template mapping shape (replace IDs privately only after approval; parameters must match actual templates):

```json
{"SUPPORT":{"provider_id":"APPROVED_SUPPORT_ID","language":"en_GB","category":"UTILITY","parameters":["body"]},"SHIPMENT":{"provider_id":"APPROVED_SHIPMENT_ID","language":"en_GB","category":"UTILITY","parameters":["reference","body","tracking"]},"RETURN":{"provider_id":"APPROVED_RETURN_ID","language":"en_GB","category":"UTILITY","parameters":["heading","body","link"]}}
```

The language belongs to the approved ID; it is not sent as an invented wire parameter. Unused optional parameter names can be omitted only when the approved template does not need them. Missing Gupshup templates hold/disable their proactive path; Twilio HX IDs are never reused.

Retain TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER and TWILIO_WEBHOOK_URL privately while old signed callbacks may still arrive. Retain SUPPORT_WHATSAPP_STATUS_URL for those callbacks. TWILIO_ENABLED=false and TWILIO_WHATSAPP_SANDBOX_ENABLED=false are recommended for cutover; Gupshup selection does not require valid Twilio values. SUPPORT_WHATSAPP_CONTENT_SID, SHIPMENT_WHATSAPP_CONTENT_SID, RETURN_WHATSAPP_CONTENT_SID and RETURN_WHATSAPP_MESSAGING_SERVICE_SID are Twilio-only, ignored by Gupshup. Twilio local ingress tooling remains Twilio-only. Email variables and their recipient allowlists remain unchanged.

`logistics-worker` is a **Vercel Daemon in the same project**, defined in vercel.json, root deployment/worker, one lhr1 instance. Containerfile starts `python -m backend.worker_runtime`. It receives project Production environment variables; there is no separate worker-host settings page in this repository. Save variables at the project level, then redeploy the matching application and daemon. A saved setting does not alter already-running processes. Current hosted state still needs dashboard/log verification; local files do not prove a deployment changed.

## 5. Database, verified bindings and rollout ? manual only

1. Keep WhatsApp paused on the old deployment and stop new test messages. Allow in-flight sends to complete; inspect all pending/PROCESSING/SENDING/REVIEW_REQUIRED rows. Reconcile provider logs before any manual requeue. Retain keys and receipt history. Do not re-send financial commands through a new provider to retry an unknown old command.
2. Take a Supabase backup/snapshot using your normal recovery process. Record schema version, deployed commit and private environment settings. Verify that the backup can be restored in an isolated database.
3. Check the actual database has **complete migrations through 048**, especially 017, 039 and 043?047. Base WhatsApp/wallet DDL is absent from this repository; have your DBA compare actual definitions/constraints/grants. Do not generate missing production tables from unit-test fixtures. Local PGlite tests exercise actual new migration SQL on a synthetic disposable prerequisite schema, not certify your hosted base schema.
4. Apply **migrations/049_whatsapp_providers.sql once**, in Supabase SQL editor, reviewing the complete script first. It runs transactionally and adds provider identity, scoped uniqueness, attempts and receipts without granting bindings or consent. New code checks for its tables at startup when WhatsApp is enabled. Disabled messaging does not require starting a transport. Verify provider columns/indexes and existing RLS/grants after applying.
5. Old proactive rows are bound to TWILIO; old inbox and replies remain TWILIO. New rows are assigned before network send. Uncertain sends stay fenced. Do not copy queue rows across providers or change their external IDs.
6. Provision/reverify each intended merchant against the **new receiving business number**. Prefer the existing WhatsApp signup/email-OTP flow for a new workspace. For an existing workspace, use a controlled support procedure: check the active Auth user/member and tenant, independently verify phone ownership, then create the binding for that member/new receiver. Do not blindly replace all legacy receivers, reassign tenants or set verified_at because a phone is known. Existing users must not be accidentally signed up into duplicate workspaces. There is no new general-purpose existing-workspace phone-linking UI in this migration; support must follow your verified identity procedure.
7. Re-obtain recipient opt-in for notifications from the new sender. Default notification_opt_in=false; the authorised account owner opts in through existing controls after verification. Sender shipment/customer return permission is separately recorded by existing workflows. Multiple eligible workspace bindings must be resolved explicitly; never pick the first workspace.
8. Review and publish the branch only when you choose to deploy. Build final sources using:

```powershell
.venv\Scripts\python.exe scripts/build_vercel.py --bundle
.venv\Scripts\python.exe scripts/build_vercel.py
```

   Commit both deployment/worker/runtime.tar.gz and source_manifest.json with source. The allowlisted build rejects stale source and unexpected public assets; it never packages .env. Use matching web/worker source/configuration. No commands in this guide have pushed or deployed automatically.
9. Keep RUNTIME_ROLE=WEB for HTTP. Confirm daemon logs report WORKER and background jobs started. A green HTTP health response alone does not prove queues are consumed.
10. Ensure the exact webhook path is reachable from Gupshup through Vercel Deployment Protection. Configure a **path-scoped routing exception**, protected by the configured secret header and optionally confirmed callback-IP filtering, using mechanisms actually available on your Vercel plan. Do not disable protection globally and do not put a bypass secret into URLs/logs. If your plan cannot expose that path safely, use a dedicated controlled webhook origin/proxy preserving authenticated origin; activation stays disabled until designed and verified.
11. Configure app credentials/source, the matching header secret/v2 subscription and migration first; then set GUPSHUP_ENABLED=true while WHATSAPP_OUTBOUND_PAUSED=true. Redeploy both processes. Run `.venv\Scripts\python.exe -m backend.check_whatsapp` locally for redacted configuration readiness; it sends nothing. It does not prove handset delivery. Missing RETURN templates are also reported when that channel is enabled.
12. For the short controlled test window, set WHATSAPP_OUTBOUND_PAUSED=false with UAT mode still true and only consenting tester phones allowlisted. Redeploy. Stop immediately if unexpected messages or permissions appear; pause and redeploy again.

## 6. Explicitly manual acceptance checklist

These steps can incur real messaging charges; none is run automatically.

- Send `help` from an allowlisted, verified merchant to the app's displayed source. Confirm durable GUPSHUP inbox row, worker consumption, one accepted reply, provider external ID and eventual delivered/read receipt. Repeating the same provider callback ID must not repeat the action.
- Send from a non-allowlisted phone: no signup emails, business action or WhatsApp reply should occur. Submit a fabricated HTTP callback without the configured secret header: it must return 403 in HEADER mode. In IP modes, unapproved source IPs must also fail. Never treat a locally fabricated valid payload as proof of real provider authentication.
- Request a quote using an existing verified merchant's saved route/cargo. Confirm normal test rates and signed checkout link. Open in a fresh browser: authentication is still required; no purchase from text alone. Keep carrier/payment TEST modes.
- Test existing email-OTP signup separately with a consenting tester. Confirm no free wallet credit or booking is created by signup. Existing merchant linking requires the verified support procedure above.
- With recorded opt-in and an approved SUPPORT utility template, stage one legitimate support notification through the existing TEST exception workflow. Check one template send, tenant attribution and delivery receipt.
- Create one TEST shipment with explicit sender WhatsApp permission to an allowlisted tester. Check milestone deduplication, then disable that preference and confirm it suppresses the notice. Email should behave as before.
- Prepare an authorised TEST return. Confirm payment/label gating. For the existing media-enabled flow, check private document/image delivery and deduplicated secure-link fallback after a **definite** media rejection. A timeout must go to review, never trigger a second send or Twilio fallback. Confirm return template receipt separately.
- Pause outbound and verify no chat, support, shipment, return or queued fallback WhatsApp is sent; email remains independently configured. Resume only for controlled tests. Record evidence without keys, message bodies, links containing tokens or customer details.

## 7. Recovery and remaining prelaunch work

Configuration rollback: pause, reconcile in-flight attempts, select TWILIO explicitly, restore its verified credentials/source/URL and Twilio settings, then deploy matching source/bundle. Existing provider-bound Gupshup attempts must not be re-sent through Twilio. Keep GUPSHUP_ENABLED=true with its original app/header/IP settings if late Gupshup receipts must still be accepted; commands stay disabled when TWILIO is selected. The active Twilio worker also reconciles stored Gupshup receipts. Keep migration 049 in place; reverting to older source may require careful handling because new gs: IDs are not Twilio SIDs. Prefer configuration rollback on this dual-provider version. Do not drop the new tables/indexes while they hold IDs needed for reconciliation.

Business-number rollback is different: moving an owned number between providers requires provider/Meta onboarding and verification. Keeping a Twilio adapter does **not** make its shared sandbox a fallback for your new EasyInvio business number.

Activation blockers: privately installing the created API key and correct App ID/source, source/tester registration, saved callback header protection, approved proactive templates, hosted schema review, verified merchant bindings and explicit deployment/manual acceptance. The account type and existence of an app/API key are confirmed by your screenshots; installed runtime settings and live acceptance are not. API-key deprecation on 31 March 2027 is a separate scheduled migration risk.

Separate prelaunch risks: no new human-agent inbox or recipient identity system; unknown billing costs/tenant budgets are not implemented; no BSUID-only/username recipient support (phone identity required); no refund-authority redesign. The baseline return regression for a DISPATCHER CUSTOMER_PAY role expected 403 but returned 409 before this work; it is recorded in the test report and must be resolved as a separate product/authorisation decision before production. No test has been weakened to hide it.
