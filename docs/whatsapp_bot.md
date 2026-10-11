# WhatsApp sandbox setup and verification

The conversational endpoint is `POST /api/v1/integrations/whatsapp/webhook`.
The existing `/webhooks/twilio/whatsapp` endpoint remains available when its URL
is configured instead. Configure one exact public URL; signatures for a different
path, host, scheme or query string are rejected. Never paste `POST ` into a URL.

## Local setup

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
   cd C:\Projects\veloce-ai
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
$env:PYTHONPATH='C:\Projects\veloce-ai;C:\Projects\veloce-ai\tests'
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
