# Local → UAT → Production

Think of Local as your workbench, UAT as your test room, and Production as your
customer shop. Git saves code; Vercel runs a selected saved version. Saving a
commit does not deploy it. Git-triggered builds remain disabled.

| Place | Code | Browser address | Deploy on every edit? |
|---|---|---|---|
| Local | current feature branch | http://127.0.0.1:8000 | No |
| UAT | `uat` branch | https://uat.easyinvio.com | No; only a chosen test batch |
| Production | approved `main` | https://easyinvio.com | Only after UAT approval |

## 1. Start your workbench

Open this checkout in VS Code: `C:\Projects\easyinvio\tmp\local-development`.
It is based on latest main and uses branch `feat/local-uat-workflow`. The old
checkout and its unrelated local edits are preserved. `.env.local` is private,
ignored by Git, and has the same database credentials as your existing `.env`.

In its PowerShell terminal run:

```powershell
.\.venv\Scripts\python.exe scripts/dev.py
```

Open `/` for landing, `/login` for sign-in, `/workspace` for the app and `/pricing`
for pricing, all under http://127.0.0.1:8000. Real sign-in/API calls are enabled;
this is not a dummy layout preview. Authentication and RBAC remain active.
Stop with Ctrl+C, edit, and run again. HTML/assets can usually be checked by
refreshing; restart after Python or environment changes. No Vercel build is needed.

Use `--preview` only for layouts without database/sign-in. Do not use
`python main.py`: that CLI starts before all later module routes are imported.

## 2. Check on your phone

Stop the loopback server first. Find the PC's Wi-Fi IPv4 address with `ipconfig`.
For example, if it is 192.168.1.25:

```powershell
.\.venv\Scripts\python.exe scripts/dev.py --lan --public-url http://192.168.1.25:8000
```

On a phone on the same trusted Wi-Fi, open http://192.168.1.25:8000. On your phone,
127.0.0.1 means the phone, not the computer. Allow Python on **Private networks**
if Windows prompts; do not open router ports. For HTTPS-dependent flows, use the
HTTPS tunnel below. Test narrow layouts, sign-in, navigation and forms.

## 3. One shared database means one shared set of records

As requested, no new database is created. This is **not data isolation**.
Use sandbox tenants and test accounts; keep `DATABASE_ENVIRONMENT=SANDBOX`,
`PROVIDER_ENVIRONMENT=TEST`, `STRIPE_LIVEMODE=false` for Local/UAT. These labels
do not copy or separate the database. An admin may still change shared records.
Do not apply experimental/destructive migrations to this database. Existing
live tenants may be blocked from test-provider operations; use sandbox tenants.
Existing Supabase Auth identities/passwords are shared too. Add the exact local
and UAT password-recovery URLs to Supabase Auth's allowed redirect URLs if needed.

Local web startup disables all continuous workers. It does not automatically
process shared billing, imports, notifications, tracking or reconciliation jobs.
API actions that you explicitly perform can still write shared data.

## 4. WhatsApp testing with the existing real Gupshup number

Do not delete/migrate the number or change approved templates. The provider's
normal message charges still apply. Keep `WHATSAPP_UAT_MODE=true`, the personal
test-recipient allowlist, and authenticated Gupshup v2 callbacks.

The one business number/app has one selected callback destination. Local, UAT
and Production must not compete to consume that same database queue. The
callback is selected manually in Gupshup for the test period.

For Local:

1. Pause hosted WhatsApp processing first (`WHATSAPP_OUTBOUND_PAUSED=true` on
   each hosted deployment using this same app/queue; apply via a deliberate
   release). This also pauses their WhatsApp notices. A laptop cannot stop a
   hosted worker by changing its own .env. Do not claim this is zero-downtime
   production testing. If live customers require uninterrupted WhatsApp, a
   separate business number/app or queue-scope implementation is required.
2. In a separate terminal run `ngrok http 8000`. Keep it open. Note its HTTPS URL.
3. In private `.env.local`, set `GUPSHUP_WEBHOOK_URL` to that HTTPS URL plus
   `/api/v1/integrations/whatsapp/gupshup/webhook`; keep HEADER authentication and
   the existing secret. Set `WHATSAPP_OUTBOUND_PAUSED=false` locally.
4. Start:

   ```powershell
   .\.venv\Scripts\python.exe scripts/dev.py --whatsapp --hosted-whatsapp-paused --public-url https://YOUR-TUNNEL.ngrok-free.app
   ```

5. Point Gupshup's callback at the same HTTPS webhook URL, retaining the custom
   header. Allow the tunnel origin in Supabase Auth redirect URLs for recovery.
6. From the allowed personal phone, test Hello, a setup question, a quote,
   tracking, and a complaint on an owned test parcel. Confirm wallet/carrier
   mutations separately. Only WhatsApp queue processing runs locally; operations
   requiring other asynchronous workers wait for the controlled UAT test below.
7. At the end, restore Gupshup's callback to the chosen hosted environment,
   stop the local server/tunnel, then resume that environment's WhatsApp worker.

This normal ngrok tunnel exposes the authenticated web application as well as
the webhook. Do not use the old `configure_whatsapp_tunnel.py`: it is Twilio-only
and does not configure this Gupshup flow. Never paste secrets in tunnel URLs.

## 5. Prepare UAT once in Vercel (account owner)

No Vercel account-management session is available to the coding agent here, so
domain/environment changes below must be made in your dashboard.

1. Keep Production branch `main`. Add/verify `easyinvio.com` (and optionally
   www.easyinvio.com) as Production domains; complete Vercel's shown DNS steps
   at your domain registrar. Verify the current Production site at that address
   **before** moving uat.easyinvio.com.
2. Use a Git branch named `uat`, based on the code batch you want to test.
   Save test settings under Vercel **Preview**, restricted to branch `uat` if
   the UI offers that choice. Keep Production variables separate.
3. Preview settings: same database, sandbox/test provider settings above,
   approved Gupshup template mapping/credentials, allowed personal recipients,
   `BOOKING_PAGE_URL=https://uat.easyinvio.com`,
   `AUTH_RECOVERY_REDIRECT_URL=https://uat.easyinvio.com/set-password`, matching
   checkout URLs, and `FRONTEND_ALLOWED_ORIGINS=["https://uat.easyinvio.com"]`.
   `REGIONAL_ALLOWED_ORIGINS` is a carrier API allowlist, not browser CORS;
   preserve the approved carrier API origins rather than adding local HTTP URLs.
4. Initially set `BACKGROUND_JOB_MODE=NONE` and `WHATSAPP_OUTBOUND_PAUSED=true`
   in Preview. Create one Preview deployment from `uat`. Verify pages/sign-in.
5. Once Ready, Settings → Domains → Edit uat.easyinvio.com → Preview → Git
   Branch `uat`. Verify the domain's assigned deployment/source. Do not change
   the domain while its target is missing or failed. Vercel deployment protection
   must permit Gupshup's webhook requests; the custom webhook header is not a
   Vercel SSO bypass token. Do not disable application webhook authentication.
6. For a WhatsApp-only UAT test, pause other consumers as in step 4 above, use
   `BACKGROUND_JOB_MODE=WHATSAPP_ONLY`, unpause WhatsApp in UAT, then deploy that
   test batch and point Gupshup at UAT. No other continuous jobs run in this mode.
7. For full asynchronous tests, arrange a maintenance window: hosted Production
   workers must be paused (`BACKGROUND_JOB_MODE=NONE` in an applied release)
   before allowing UAT `BACKGROUND_JOB_MODE=ALL`. Because data is shared, UAT
   workers can see Production jobs too. Do not do this with unprocessed live
   customer work; separate databases/fully scoped queues are needed for that.
   Resume Production and pause UAT at the end. Do not run ALL in both at once.

NONE leaves a hosted daemon waiting; it does not remove its container/resource
cost. Manual batching reduces builds, not all runtime charges. If the daemon
continues costing too much, review its Vercel usage before keeping UAT running.

## 6. Daily work and a release

1. Make/review changes on a feature branch; test locally as often as needed.
2. Commit/push the batch, integrate into `uat` after local checks, then create
   **one** Preview deployment for that chosen batch. Do not deploy every edit.
3. Test desktop/mobile, login/logout, role access, quotes, explicit payment/
   booking, parcel privacy, support, returns and notification behavior. Record
   expected vs actual results. A deployment being Ready is not acceptance testing.
4. When you approve UAT, merge the tested code into `main` and create one
   Production deployment using Production settings. Verify easyinvio.com and
   keep the previous working deployment for rollback.

No domain, DNS, provider callback, hosted environment or database is changed by
this guide or the local launcher. Existing schema through 054 remains required.

References: [Vercel environments](https://vercel.com/docs/deployments/environments),
[assigning a domain to a branch](https://vercel.com/docs/domains/working-with-domains/assign-domain-to-a-git-branch).

## Private import files and release settings

See [private_environment_files.md](private_environment_files.md) for the generated
Local/UAT files, bulk import steps, missing provider values and Production launch
checklist. Environment files remain private and are never committed.
