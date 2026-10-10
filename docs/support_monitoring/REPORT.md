# Support lifecycle and owner monitoring journeys

Validated on 10 October 2026. These are journey-specific results, not a rewrite
of the previous 100-case UAT report. The configured backend runs at
http://127.0.0.1:8000.

## Flow 2: carrier exception to merchant notification

The normalized, timestamp-signed tracking route remains available. The same
`POST /api/v1/tracking/webhook` now also accepts native EasyPost `tracker.updated`
events with an explicitly configured account key and mode. It verifies the
raw-body HMAC using EasyPost's SDK-compatible secret normalization, maps failure,
error and return-to-sender milestones to EXCEPTION, and retains existing
tenant/account matching, duplicate-event and stale/terminal-state protections.
The native account URL uses `?integration_key=YOUR_KEY_NAME`. That identifier
is not a secret; the webhook secret authenticates the event.

The durable worker creates the internal support ticket and deterministic
remedy. Postal-code issues receive a specific merchant/address/invoice review
action. It does not claim Google Maps verification, automatic carrier correction,
customs clearance or a confirmed delivery date. The ticket records
`DETERMINISTIC_MOCK`, not a fictional external model call.

Remedies are staged for active, verified merchant bindings. A new optional worker
can send an approved WhatsApp template to an explicitly opted-in owner/admin,
or free-form remedy text within a service window recorded from a verified
inbound merchant message. Duplicate inbound message SIDs cannot extend that
window, and browser writes cannot forge it. Without a template or current
window, the notification stays staged.
It checks the configured receiver number, active workspace and sandbox/production
account boundary. The database claim commits before network I/O. Timeouts and
ambiguous responses remain RECONCILIATION_REQUIRED, with no blind automatic
resend. Definite rejection becomes FAILED; rate limits receive bounded backoff.

Twilio acceptance is recorded as ACCEPTED. Only an authenticated status callback
advances to SENT/DELIVERED/READ. Callbacks check the exact configured external
URL signature, account, message SID and recipient; older states cannot downgrade
delivery. Error codes are retained without provider response bodies or secrets.
When the shipment becomes DELIVERED, active tickets close and unsent STAGED
notifications are cancelled. Already accepted alerts are not falsely recalled.

Merchant owners/admins can opt in/out through the Wallet interface after their
number has been verified and bound. Raw browser table writes cannot forge phone
identity, verification or notification consent. The existing sandbox bootstrap
now supplies the binding table's required `verified_at` timestamp for the
platform-owner-controlled enrollment path; sandbox membership remains necessary.

## Flow 3: Super-Admin Command Center

Owner authentication remains the server-verified platform-owner allowlist.
Client roles cannot access macro routes by changing a browser toggle.

The command center now displays:

- Revenue, stored gross markup and booked package counts separately by currency.
  GBP cards remain explicitly GBP-only. Stored markup is not net accounting
  profit and no unsupported FX consolidation is performed.
- Carrier distribution over the same reporting range, without truncating the
  distribution to the first 20 carriers.
- Current cross-tenant billing-plan/status counts and dated wallet payment
  status/amount summaries. Fixture opening credits are not payment receipts.
- Active support counts and the newest 100 active threads with company context,
  reviewable remedies and actual notification receipt/error states.
  A scope selector preserves access to historical closed/resolved threads.
- An explicit Production/Sandbox selector. Production is the default; synthetic
  seed accounts do not silently inflate production revenue or company counts.

The analytics read uses a repeatable-read snapshot and existing tenant/account
relationships. New global booking/payment, active-ticket, send-queue and provider
message indexes support these access paths. These tests validate the fixture
scale and index presence; they do not certify a large-production latency SLA.

## Executed results

| Verification | Result |
|---|---|
| Selected application regressions | **PASS: 123 tests**, including new support delivery/native webhook checks and existing dispatch, freight, customs, pricing, finance, import, security and dashboard paths. Sandbox provider tests use mocks, not live payments. |
| Real Supabase native exception | **PASS:** signed EasyPost-shaped New York customs/postal-code event updates the shipment to EXCEPTION, queues support, and duplicate delivery replays without another ticket. |
| Remedy and outbox | **PASS:** exactly one OPEN ticket and staged merchant remedy with the shipment reference; repeated worker processing does not duplicate them. |
| Controlled WhatsApp delivery | **PASS:** a MockTransport 201 response records ACCEPTED; a signed controlled callback records DELIVERED. The actual database blocks free-form sends before a verified inbound window and inbound SID replay does not extend the window. Approved-template payloads are separately verified in unit tests. No real merchant/mobile was messaged. |
| Resilience/security | **PASS:** bad webhook/callback signatures rejected, late SENT cannot downgrade DELIVERED, uncertain send is not repeated, disabled delivery makes no network call, rate limits restage with backoff. |
| Actual notification database protection | **PASS:** authenticated-role direct consent writes rejected; five delivery/reporting indexes verified. |
| Ticket completion | **PASS:** a subsequent signed DELIVERED milestone closes the support thread. |
| Actual owner database reports | **PASS:** sandbox revenue and margins reconcile exactly with independent SQL by currency; carrier volume sums equal booked package sums; billing states and active company/context/notification fields returned. Owner authorization is overridden in this probe to test database behavior; it is not a live owner login test. |
| Authorization | **PASS:** unit checks deny non-owner macro access before querying the database; configured HTTP rejects unsigned owner/tracking requests. |
| Command-center browser | **PASS:** Chromium renders currencies, billing/payment pipelines and company/notification context; environment switching works; client view clears macro rows; no script errors or horizontal overflow at 375/768/1366 pixels. Uses controlled owner/profile API responses. |
| Existing browser flows | **PASS:** owner/client/dispatcher boundaries and contrast, CSV download/upload/customs review, dispatcher preparation/quote flow. Preview smoke verifies **67 API paths**. |

All functional database test records, phone bindings, ticket/status changes and
notification receipts were rolled back. Only the additive migration persisted.
Existing tenant fixture data, funds and credentials were preserved. No real
EasyPost requests, WhatsApp sends, Stripe transactions or HubSpot activity occurred.

## Database update and activation

`migrations/017_support_delivery_and_monitoring.sql` was rollback-validated and
applied to the configured Supabase sandbox. It preserves historical SENT states,
adds delivery receipt/retry fields and opt-in, protects notification identity,
and creates reporting/send indexes. **You do not need to run more SQL in this
database.** Apply migration 017 after 016 in any other deployment database.

To activate a real Flow 2:

1. Register a public HTTPS webhook URL in EasyPost, set its separate webhook
   secret, and configure the matching `TRACKING_WEBHOOK_KEYS` entry with tenant
   UUID, carrier account UUID, secret and `easypost_mode: "test"` or `"production"`.
   The signature is the native `X-Hmac-Signature`, not a made-up Veloce header.
2. Configure the existing Twilio account/auth token, WhatsApp sender and inbound
   webhook settings; verify/bind the intended merchant number. Sandbox users
   must join the sandbox. Explicitly opt in using the merchant Wallet controls.
3. For a sandbox session, first send a text from the verified merchant mobile
   to the configured inbound webhook; its authenticated handler opens the
   service window. Free-form support text then works within that window.
   For notifications outside the window, configure `SUPPORT_WHATSAPP_CONTENT_SID` for an approved template whose single
   variable contains the stored shipment/remedy text. Configure
   `SUPPORT_WHATSAPP_STATUS_URL` to the exact public HTTPS URL ending
   `/api/v1/support/whatsapp/status`, without a trailing slash or query string.
   Each send appends its outbox UUID. Finally enable `SUPPORT_WHATSAPP_ENABLED`.
   If the sandbox sender does not support your template, wait for a merchant
   inbound message instead of treating template approval as automatic.
4. Prove actual handset delivery through a real signed callback and operator
   inspection. This remains **BLOCKED by missing credentials/configuration**,
   not passed by these controlled-response tests. Template approval, public
   reachability and merchant consent are external prerequisites.

Real outbound support remains disabled in the current `.env`. Do not manually
mark an uncertain notification delivered or resend it merely to turn a test green;
reconcile it with Twilio's actual message records first.

Protocol references: [EasyPost webhooks](https://docs.easypost.com/guides/webhooks-guide),
[EasyPost Python validator](https://github.com/EasyPost/easypost-python/blob/master/easypost/util.py),
[Twilio WhatsApp templates](https://www.twilio.com/docs/whatsapp/tutorial/send-whatsapp-notification-messages-templates)
and [message delivery status](https://www.twilio.com/docs/messaging/api/message-resource).

Repeatable scripts: `tests/support_monitoring_database_probe.py` (sandbox;
idempotent migration plus final functional rollback),
`tests/test_support_monitoring.py`, `tests/test_owner_monitoring_browser.py`.
Standalone scripts need `PYTHONPATH` set to the project root and tests directory.
The local `database_evidence.json` receipt is excluded from Git.
