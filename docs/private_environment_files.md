# Private Local, UAT and Production environment files

These are private files on this computer, not committed source files:

| Purpose | File | How it is used |
| --- | --- | --- |
| Production configuration | `C:/Projects/easyinvio/.env` | Deliberate future Production import only |
| UAT configuration | `C:/Projects/easyinvio/tmp/local-development/.env.uat` | Import into Vercel Preview, branch `uat` |
| Local configuration | `C:/Projects/easyinvio/tmp/local-development/.env.local` | Loaded automatically by `scripts/dev.py` |

The original Production file and previous Local file have timestamped private
`.backup-...` copies beside them. All these files are Git-ignored. Do not paste
contents into chat, commit them, or upload them as public artifacts. Names alone
are not environment selectors: choose Preview explicitly when importing UAT.
Do not import Local into Vercel.

## What was prepared

Existing parseable credentials were retained. A malformed template assignment
and a stray shell word were removed; the three approved Gupshup template IDs
were reconstructed as one valid JSON assignment. Template language is `en`, as
previously configured; verify against the actual approved language if sending
returns a provider language error. Only the original backup preserves malformed
unparsed text.

Production website URLs now use `https://easyinvio.com`. Existing payment
mode, provider mode and recipient restrictions were preserved. This is a
Production configuration file, NOT a completed live-payment launch setup.
The existing Stripe key is a test key. No live credentials were invented.
No hosted variables, callbacks, domains, migrations or deployments were changed.

UAT uses `https://uat.easyinvio.com`, the shared database and real Gupshup app,
test providers, Stripe test mode, the personal WhatsApp allowlist, and the new
progressive assistant. Subscription, billing lifecycle and consumer CX flags
are on. Migrations through 055 must be applied before starting this release.
HubSpot and XCover are disabled in UAT/Local until deliberately testing those
integrations; their existing credentials/configuration remain in the files.
AI FAQ web search is disabled in UAT/Local to avoid unnecessary external search.

UAT runs `BACKGROUND_JOB_MODE=WHATSAPP_ONLY` with outbound WhatsApp unpaused.
Before deploying it, pause ALL other consumers of this shared app/database
queue in their actual hosted configuration. Editing this computer's Production
file does not pause hosted workers. A worker-only WhatsApp test does not run
queued email, support/return notification delivery, scheduled billing, tracking
polling or other asynchronous jobs. Full asynchronous UAT requires pausing other
shared-database workers, then deliberately selecting `BACKGROUND_JOB_MODE=ALL`
(and enabling the feature under test). Do not run ALL in both hosted sites.

Local uses loopback browser URLs and `BACKGROUND_JOB_MODE=NONE`, with outbound
WhatsApp paused. Gupshup's stored webhook URL still names UAT: a localhost URL
cannot receive public WhatsApp callbacks. NGROK_AUTHTOKEN stays Local only; it
was not copied into the UAT upload. Local booking URLs accept HTTP only on
loopback addresses; provider callback URLs still require HTTPS.

## UAT import once per settings batch

1. Vercel project -> Settings -> Environment Variables -> Import .env.
2. Select the private `.env.uat` file above. Select ONLY Preview and branch
   `uat` if offered. Review the entire list before saving, particularly URLs.
3. For conflicts, replace the Preview/uat value only. Preserve Production.
   A branch-specific Preview value overrides an all-Preview value. Avoid leaving
   an older branch-specific value overriding a newly imported generic value.
   Import does not necessarily remove stale keys absent from the file.
4. Confirm migrations through 055, the UAT domain assignment, callback access
   through deployment protection, and single-active-consumer setup.
5. Create ONE new Preview deployment from `uat`. Environment changes do not
   alter existing deployments. Test startup, sign-in and WhatsApp explicitly.
6. Keep Gupshup's callback at the UAT HTTPS webhook while testing UAT.

Vercel reference: https://vercel.com/docs/environment-variables

## Run Local

From `C:/Projects/easyinvio/tmp/local-development`:

```powershell
.\.venv\Scripts\python.exe scripts/dev.py
```

Restart after changing environment variables or Python. The launcher uses
`.env.local`, not the original checkout's `.env`. Landing, login, workspace and
pricing are all served at `http://127.0.0.1:8000`.

For Local WhatsApp, first pause hosted consumers, obtain a real HTTPS tunnel,
set Local GUPSHUP_WEBHOOK_URL to its exact webhook URL, unpause Local outbound,
then use `--whatsapp --hosted-whatsapp-paused --public-url https://YOUR-TUNNEL`.
Set Gupshup's dashboard callback to match; restore it to UAT after testing.
See `local_uat_production.md` for the complete procedure and mobile testing.

## Values that cannot be inferred

- `SUBSCRIPTION_PRICE_IDS` is empty. In Stripe TEST mode, create/find the four
  recurring prices. Map `VELOCITY:MONTHLY`, `VELOCITY:ANNUAL`, `COMMAND:MONTHLY`,
  `COMMAND:ANNUAL` to their real `price_...` IDs. Expected amounts are 2900,
  28800, 7900 and 78000 GBP pence respectively. No paid subscription checkout
  is available until configured. Production needs separate LIVE price IDs.
- STRIPE_WEBHOOK_SECRET was retained. Verify it belongs to the endpoint and
  mode being tested. A new endpoint has its own signing secret; get it from
  Stripe's webhook destination details. Never paste it into chat.
- REGIONAL_ALLOWED_ORIGINS retains the previous nonempty list, which contains
  a placeholder and website origins. Obtain actual approved custom carrier
  API origins from the carrier contract/configuration. Do not replace it with
  browser CORS origins or an empty list (Settings requires a nonempty list).
  Aggregator integrations have separate registry handling.
- A Local HTTPS tunnel URL is not known until the tunnel is running.
- Live Stripe/carrier/insurance credentials, tax configuration and separate
  UAT database/Gupshup app are not supplied by this task.

## Permanent Production launch checklist

Keep UAT settings permanently as test settings; do not flip its values to live.
Before the first public launch, review and verify:

- Separate test database/auth/storage and WhatsApp app/number if uninterrupted
  independent testing is required. Shared database/number is not full isolation.
- Production URLs, auth redirects, webhook endpoints and domain assignment.
- Stripe live key, live endpoint secret and live subscription price mapping;
  STRIPE_LIVEMODE=true only after deliberate payment acceptance testing.
- DATABASE_ENVIRONMENT=LIVE and PROVIDER_ENVIRONMENT=LIVE with approved live
  tenants and carrier credentials; these switches do not create/copy databases.
- Correct XCover contracts/credentials before enabling insurance. Existing
  mock/placeholder insurance values do not make an insurance integration live.
- Production recipient restrictions: WHATSAPP_UAT_MODE=false and intended
  shipment notification recipient configuration only after public approval.
- Production WHATSAPP_OUTBOUND_PAUSED=false and worker mode ALL only when
  approved and no shared test workers can consume its jobs.
- Correct real email recipients, HubSpot account, tax handling and feature flags.
- Approved migrations, accepted code merged into main, Production deployment,
  smoke tests and rollback target. No launch changes happen automatically.

For future releases, change/test Local -> UAT, then move accepted code and
approved migrations to Production using its own settings. Add new variables to
all relevant environment files deliberately. These copies do not auto-sync.
