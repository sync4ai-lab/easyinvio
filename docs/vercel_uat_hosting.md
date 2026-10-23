# Vercel UAT hosting

The Vercel Production deployment is used for UAT with SANDBOX database settings,
TEST carrier environments and Stripe test keys. Hosting environment names do not
authorize live purchases. Keep the existing payment and carrier safeguards.

## Why the original deployment exhausted connections

Every Python instance previously started the complete set of continuous workers
and a dedicated PostgreSQL LISTEN connection. Even a request for CSS or JavaScript
entered Python startup. Several instances could exhaust the 15-session Supavisor
pool. The pooler's 200-client limit is a separate limit; it does not increase the
number of database sessions available in session mode.

## Process ownership

`RUNTIME_ROLE=AUTO` preserves local combined operation. On Vercel, `vercel.json`
sets WEB explicitly. `python -m backend.worker_runtime` overrides its own process
role to WORKER before importing the application.

| Role | HTTP services | Continuous jobs | Dispatch LISTEN |
| --- | --- | --- | --- |
| COMBINED (local default) | Available | Enabled | Enabled |
| WEB (Vercel function) | Available | Disabled | Disabled |
| WORKER (daemon) | Initialised for internal job dispatch; no HTTP listener | Enabled | Disabled |

The dedicated `logistics-worker` daemon runs one instance in `lhr1`. It handles
ecommerce tracking, native provider jobs, partner reconciliation, optional XCover
protection/claims, Amazon intake, support messages, WhatsApp queues, Stripe event
reconciliation, card completion, return delivery and optional HubSpot jobs.
Each optional integration retains its existing enablement checks. The worker
supervisor exits if a continuous job unexpectedly stops, so the host can restart
it. SIGTERM/SIGINT trigger cancellation and connection cleanup. Existing durable
receipts and ambiguous-outcome states remain responsible for safe reconciliation;
restarting a worker does not authorize replaying an uncertain purchase or send.

## Database sessions and locks

Keep the existing **session-pooler** DATABASE_URL. The app uses session advisory
locks across committed transactions and external provider calls. A transaction
pooler is incompatible with those operations; changing only the port to 6543 is
unsafe. TLS certificate and hostname verification remain enabled.

WEB uses an asyncpg pool with zero initial sessions, at most two acquired sessions,
and `max_queries=1`: an acquired connection closes on release after its unit of
work, not between statements or transactions. This prevents frozen web instances
from retaining idle sessions, without changing financial locks. It adds connection
handshake overhead. Long provider operations still hold their acquired sessions.

WORKER uses a separate per-process budget, `WORKER_DB_POOL_MAX_SIZE=8` by default,
independent of `DB_POOL_MAX_SIZE=2`. Combined local mode preserves its original
pool sizing and dedicated listener. The limits are **per process**, not a global
database concurrency cap. Allow headroom for active web operations, deployment
rollovers, administrative tools and any local servers. This change is not proof
that a 15-session pool will support arbitrary load or concurrent deployments.
Close obsolete local servers and assess connection metrics during UAT before
changing pool capacity. Do not terminate unknown sessions or raise limits blindly.

## CDN assets and dashboard updates

The build copies only ten explicitly named public HTML/JS/CSS files into
`public/`. Vercel serves those through its CDN. Only `/`, `/set-password` and
`/track` receive frontend rewrites; API requests retain their original paths.
No .env, source tree, customer export, uploaded document or private media directory
is copied into public. Public tracking keeps its no-referrer/CSP headers.

`/api/v1/config` advertises POLLING in WEB mode. Authenticated dashboards refresh
the active dispatch, manifest or wallet view every 15 seconds while visible.
Logout clears the polling timer. Local combined mode keeps WebSockets. Vercel
Functions do not supply a WebSocket server; this setup does not pretend otherwise.

## Reproducible worker build context

Vercel builds a daemon using the directory containing its Containerfile. To avoid
duplicating the repository, publishing worker source, or assuming access to parent
directories during Docker build, `deployment/worker/runtime.tar.gz` contains a
deterministic allowlisted source bundle. `source_manifest.json` records every file
hash. No configuration values or credentials are included. The container runs as
an unprivileged user. Both web and worker install the existing requirements.txt.
The older requirements.lock.txt is included for reference, but is not enforced:
it is incomplete and pins websockets 17.2, while the current Agents dependency
requires a version below 17. Do not add that older file as pip constraints. The
source bundle is reproducible; the existing dependency ranges are not a complete
dependency lock. Record resolved versions from the actual build for release QA.

After runtime changes, run:

```powershell
.\.venv\Scripts\python.exe scripts/build_vercel.py --bundle
.\.venv\Scripts\python.exe scripts/build_vercel.py
```

Commit the refreshed archive and manifest with their source changes. The Vercel
build command checks the bundle against the current source and fails on drift.
Do not bypass this check: different web and worker source versions are unsafe.
Public assets are generated and ignored by Git. Runtime bundle inputs are the
Python backend, main.py, requirements, public CA certificates, Help Centre sources
and shared support components. The build never reads .env.

## Deployment and acceptance

Vercel Daemons are public beta and currently run in Production deployments only.
Verify availability, quota and billing in the actual project; local tests cannot
prove the remote daemon builds or runs. A successful HTTP build alone is not full
acceptance. No database migration is required for this hosting change.

1. Retain the saved UAT variables and the FastAPI framework preset/root settings.
2. Ensure no dashboard build-command override replaces the checked-in build command.
3. Deploy the commit, then inspect both the function and `logistics-worker` logs.
4. Confirm `/health` and `/api/v1/config` succeed and report POLLING.
5. Confirm static asset requests no longer start Python and dashboard refresh works.
6. Confirm the daemon logs `EasyInvio worker started` and all enabled queues run.
7. Test a real Stripe TEST checkout, signed event, wallet credit and deferred card
   booking; never infer successful payment from a redirect alone.
8. Complete Twilio Sandbox webhook access separately, then test signed ingress,
   queued processing and outbound replies. This remains pending until configured.
9. Exercise returns, email delivery, carrier sandbox labels and reconciliation
   paths using their actual enabled integrations. Compare connection counts with
   the pool budget under concurrent UAT requests and during a deployment rollover.

If the daemon is absent or fails, do not mark payments, queued messages or returns
as UAT-ready. Preserve durable pending work and fix hosting; do not replay actions
manually, enable uncertain retries, or re-enable continuous jobs in web instances.

References: [Vercel FastAPI static assets](https://vercel.com/docs/frameworks/backend/fastapi#serving-frontend-and-static-assets),
[Vercel Daemons](https://vercel.com/docs/daemons),
[daemon configuration](https://vercel.com/docs/daemons/config-reference),
[Supabase connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres).
