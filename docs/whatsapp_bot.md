# WhatsApp sandbox setup and verification

The conversational endpoint is `POST /api/v1/integrations/whatsapp/webhook`.
The existing `/webhooks/twilio/whatsapp` endpoint remains available when its URL
is configured instead. Configure one exact public URL; signatures for a different
path, host, scheme or query string are rejected. Never paste `POST ` into a URL.


## Hosted UAT setup on easyinvio.com (25 October 2026)

The owned website domain, Twilio organization domain verification, and WhatsApp sender registration are three separate configurations. The organization Domains screen proves control of employee email domains; it does not activate a WhatsApp sender, remove sandbox membership restrictions, or configure message webhooks.

### Domain ownership

Public DNS uses Hostinger nameservers. In Hostinger Domains > DNS > easyinvio.com add TXT name _twilio, value copied exactly from the Twilio Verify domain screen (twilio-domain-verification= followed by its token), TTL 3600. Save it, wait for public DNS visibility and click Check verification in Twilio. Keep existing website and email records. The DNS token is not an application environment variable. DNS publication and Twilio's confirmed verification are different states.

### Application configuration

For this deployed UAT site, keep the existing account credentials and use the following values both locally and in the easyinvio Vercel project's Production environment. The project calls this Production because it is the hosting deployment; shipping stays TEST and the database remains SANDBOX.

```dotenv
TWILIO_ENABLED=true
TWILIO_WHATSAPP_SANDBOX_ENABLED=true
TWILIO_WHATSAPP_NUMBER=+14155238886
TWILIO_WEBHOOK_URL=https://uat.easyinvio.com/api/v1/integrations/whatsapp/webhook
SUPPORT_WHATSAPP_STATUS_URL=https://uat.easyinvio.com/api/v1/support/whatsapp/status
BOOKING_PAGE_URL=https://uat.easyinvio.com/
DATABASE_ENVIRONMENT=SANDBOX
PROVIDER_ENVIRONMENT=TEST
```

The local webhook, support callback and booking URLs were aligned to the owned UAT hostname. This fixes a stale local support callback that pointed to an old ngrok tunnel. Dashboard values require authenticated saves; local .env edits do not change Twilio or Vercel. The logistics-worker daemon shares the Vercel project's Production variables and must load the new deployment. No separate company data needs to be pasted into its configuration. Credentials, link-signing secrets and encryption keys remain private and unchanged.

### Trial Console versus legacy Sandbox UI

The live account read reports an active Trial account. In the new Twilio Console use Home > Try out WhatsApp. Activate/link the test phone, open Receive a message, choose Custom under the inbound/auto-reply settings, enter the exact incoming webhook URL above and Save. Standard uses a Twilio-hosted reply and does not test EasyInvio. In the legacy Console the equivalent is Messaging > Try it out > Send a WhatsApp message > Sandbox settings > When a message comes in, using POST. The new Console may not show a tab called Sandbox settings.

Each participating phone must join the account's displayed test environment; a successful join from a week ago is not proof of current membership. The legacy Sandbox membership expires after three days and must be renewed. Read the current Console join instructions rather than guessing a join code. Test credentials do not operate WhatsApp: use the active account's actual credentials.

The bot and support sends generate per-message status callbacks. Do not paste the support status base into the incoming webhook field or invent an outbound-status part ID in the global callback field. The shared sandbox sender is not an EasyInvio registered business number.

### Pairing, consent, worker and templates

A valid WhatsApp join authorizes the provider transport, not access to a customer's EasyInvio workspace. The phone must separately be bound to the intended active client membership and verified by the application's pairing/onboarding workflow. A binding to a seeded test company must not be treated as ownership of a real business. Do not change a user's role, manufacture consent or mark another person's phone verified to make a test pass. Proactive merchant support requires notification opt-in; sender-shipment notices require the shipment sender's permission and a TEST recipient allowlist.

The active account's read-only audit confirmed past WhatsApp outbound messages reached read status, but older inbound records had provider error 12300. These are historical, not proof that the currently deployed webhook/worker configuration works. The new public incoming endpoint responds without a redirect and rejects unsigned requests with 403. A negative signature probe sends no WhatsApp message and proves neither signed enqueue nor reply delivery. Current encrypted inbox/outbox tables exist and must remain private.

Interactive replies can be tested in the 24-hour customer-service window opened by a real user message. The existing shipment and return proactive notification workflows use custom approved utility templates. The shared Twilio Sandbox cannot use custom templates; a boolean enable flag or a domain TXT record cannot remove that provider restriction. In particular, an empty SHIPMENT_WHATSAPP_CONTENT_SID leaves shipment notices unconfigured. Do not reuse an unrelated appointment/verification template to claim a parcel journey was delivered. Complete registered-sender/Meta onboarding and template approval before activating those production workflows.

### Read-only checks and acceptance

```powershell
.\.venv\Scripts\python.exe -m backend.check_whatsapp
# Adds account authentication and public domain TXT checks; never sends a message:
.\.venv\Scripts\python.exe -m backend.check_whatsapp --live
# Reads schema/RLS/queue states only; does not start application workers:
.\.venv\Scripts\python.exe -m tests.whatsapp_database_probe
```

The database probe was updated for the queued transport: its old signed-unknown-sender test predated migration 043 and could now create a real inbound queue row despite claiming read-only behavior. It no longer starts application lifespan workers or submits signed synthetic messages.

After the Console saves and deployment, use only the owner's chosen test phone and explicitly authorize any outbound test. Send a real message from that phone, confirm a new inbound Message SID in Twilio, a matching encrypted inbox receipt in EasyInvio, worker processing, one reply outbox part with its provider SID, and handset delivery/read where available. Match the same SIDs; configuration booleans are not delivery evidence. Repeat only the same provider event for deduplication testing; do not replay uncertain outbound sends. A STAGED/READY job with no attempt is a worker/configuration problem, not proof of a domain-verification failure. Inspect logistics-worker startup logs and the configured database before claiming acceptance. No unsolicited notification, booking or payment is required for the initial transport test.

Registered business sending is a separate rollout: choose a business number, complete Twilio/Meta registration and phone verification, confirm sender approval, configure the webhook, then switch TWILIO_WHATSAPP_SANDBOX_ENABLED=false and use the approved sender's E.164 number. Do not purchase a number, upgrade the account, or migrate a personal WhatsApp number as a side effect of fixing UAT configuration. Those require the owner's explicit choices and any required Meta/phone verification.

Official references: https://www.twilio.com/docs/iam/organizations/domains ; https://www.twilio.com/docs/whatsapp/quickstart ; https://www.twilio.com/docs/whatsapp/sandbox ; https://help.twilio.com/articles/55716571409819-How-do-I-receive-WhatsApp-messages-while-testing ; https://www.hostinger.com/support/1583249-how-to-manage-dns-records-at-hostinger/ .

## Local setup (local development only)

1. In the project's private `.env`, use the account SID and **Auth Token** belonging
   to the Twilio account that owns the Sandbox. Twilio test credentials do not
   operate the WhatsApp Sandbox. Use `TWILIO_ENABLED=true`,
   `TWILIO_WHATSAPP_SANDBOX_ENABLED=true`, and
   `TWILIO_WHATSAPP_NUMBER=+14155238886` (the `whatsapp:` prefix is also accepted).
   Keep `DATABASE_ENVIRONMENT=SANDBOX` and `PROVIDER_ENVIRONMENT=TEST`.
2. Sign into [ngrok](https://dashboard.ngrok.com/get-started/your-authtoken) and
   save its authtoken as `NGROK_AUTHTOKEN` in `.env`. This is a separate credential
   from Twilio's Auth Token. Do not commit or share either token.
3. Run from PowerShell:

   ```powershell
   cd C:\Projects\easyinvio
   .\.venv\Scripts\python.exe scripts\configure_whatsapp_tunnel.py
   ```

   The helper starts/reuses an HTTPS tunnel to a restricted webhook gateway on port 8009, stores the incoming
   webhook and support-status URLs in `.env`, and prints the incoming webhook URL.
   It runs ngrok without a visible window and does not print tokens.
4. Restart the backend to load the new URLs:

   ```powershell
   .\.venv\Scripts\python.exe main.py
   ```

   Stop your existing backend first if it already occupies port 8000.
5. Open **Twilio Console → Messaging → Try it out → Send a WhatsApp message →
   Sandbox settings**. Set **When a message comes in** to the complete URL printed
   by the helper, select **POST**, and save. Use your account's displayed Sandbox
   join code to join from your mobile. Leave ngrok and the backend running.
6. A platform owner must register your phone and real saved-route data using the
   existing authenticated `POST /api/v1/admin/sandbox/whatsapp-setup` endpoint.
   It accepts `tenant_id`, `auth_user_id`, `sender_e164`, `route_code`,
   `origin_address`, `destination_address`, `dimensions`, and `currency`.
   The target must be a sandbox tenant with an active OWNER, ADMIN or DISPATCHER
   member. Do not assign another person's phone without verification.
7. Configure actual TEST carrier credentials in Carrier Provider Settings. Mark
   the appropriate tenant's test account active. Synthetic inactive seed accounts
   cannot provide quotes. Send `Quote 4.5kg from GB to US` from the paired phone.
   For ambiguous lanes add `route EXPORT_US` with your saved route code.

Ngrok forwards cloud requests to your local machine: Twilio cannot access your
computer's `127.0.0.1` directly. A deployed HTTPS backend can replace ngrok later.
If the public tunnel URL changes, rerun the helper, restart the backend and update
Twilio's Sandbox setting. Signature verification remains mandatory.

## Behavior and boundaries

- Unknown, disabled, unverified or ambiguous bindings cannot read tenant rates.
- Saved routes supply real addresses and dimensions. No addresses are invented
  from country codes. The existing calculator applies volumetric weights,
  concurrent provider queries and tenant-specific Decimal pricing rules.
- The three cheapest returned customer offers are saved as expiring choices.
  A configured public booking UI enables their signed links.
  The authenticated `/v1/whatsapp/quote-choice?token=...` API resolves these choices;
  the links point to the configured workspace. Receiving or opening a quote does
  not purchase a label. International goods still require customs review.
- Prepaid warnings account for reserved credit, missing/mismatched wallets, zero
  balance and insufficient credit for the cheapest quote. Booking's atomic wallet
  locks remain the final authority. Active postpaid accounts are not blocked by an
  empty wallet.
- Duplicate MessageSids reuse durable TwiML receipts. Invalid signatures return
  403 before sender lookup. Account, receiving number and form structure are also
  validated. Sandbox quotes are explicitly labeled as sandbox quotes.
  Replies exceeding Twilio's message length limit are split at line boundaries
  into multiple TwiML messages, preserving complete booking URLs.
- The existing proactive support delivery worker remains separate and requires
  merchant consent and a valid customer-service window or approved template.
  The tunnel helper configures its callback URL but does not enable outbound sends.
- `WHATSAPP_BRAND_NAME` controls this endpoint's message branding. The confirmed
  brand is `EasyInvio.com`.

## Verification recorded on 11 October 2026

| Check | Result |
| --- | --- |
| Real Twilio read-only account authentication | HTTP 200; active Trial account |
| Real Supabase WhatsApp tables | All four present |
| Configured backend startup and signed unknown-sender DB lookup | Passed |
| Forged signature against configured backend | HTTP 403 |
| Automated WhatsApp, sandbox, support and optional-integration suite | 46 test executions passed |
| Verified active phone bindings / saved routes / active TEST carrier accounts | 0 / 0 / 0 |
| Restricted public ngrok tunnel | Running; callback URLs configured in private .env |
| Public signed callback / forged signature | HTTP 200 with unregistered-sender TwiML / HTTP 403 |
| Public app, docs, admin and billing paths | HTTP 404 |
| Local backend health | HTTP 200 on port 8000 |
| Real phone-to-Twilio-to-local-backend round trip | Pending Sandbox console setting, joining/pairing, saved route and carrier setup |

No real WhatsApp message, carrier purchase, payment or permanent database mutation
was performed during verification. The database probe disables unrelated workers
only in its own process. No new database migration is needed for this module.
An independent earlier Stripe migration, `019_stripe_snapshot_reconciliation.sql`,
was absent during this check and remains required for the new Stripe controller.

Repeat checks:

```powershell
$env:PYTHONPATH='C:\Projects\easyinvio;C:\Projects\easyinvio\tests'
.\.venv\Scripts\python.exe -m unittest tests.test_whatsapp_bot tests.test_sandbox_hooks tests.test_support_monitoring tests.test_optional_integrations -q
.\.venv\Scripts\python.exe tests\whatsapp_database_probe.py
```

Official references: [Twilio WhatsApp quickstart](https://www.twilio.com/docs/whatsapp/quickstart),
[WhatsApp Sandbox](https://www.twilio.com/docs/whatsapp/sandbox),
[ngrok Windows setup](https://ngrok.com/download/windows).

The tunnel gateway forwards only the incoming WhatsApp POST and the UUID-scoped
delivery-status POST to localhost:8000. App pages, administration, billing and API
documentation return 404 at the public tunnel. Configure `BOOKING_PAGE_URL`
separately to your authenticated deployed application; this restricted tunnel
cannot serve booking pages. Local development can validate quote responses before
a public booking UI is deployed.
