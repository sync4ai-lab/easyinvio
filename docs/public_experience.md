# Public and workspace experience

The public landing page uses the same `/brand-mark.svg`, `/brand.css` wordmark,
slate/indigo/emerald palette and `/ask-easyinvio.css` chat presentation as the
workspace. Both assistants are named **Ask EasyInvio**.

## Browser sessions

The existing revocable app session is also carried in an HttpOnly, SameSite=Strict
cookie. HTTPS deployments mark it Secure. Access/refresh tokens are not written to
localStorage or sessionStorage. The workspace continues using its bearer in memory.

- `/api/v1/public/session` returns only verified authentication status and a name;
  the landing page does not decode a JWT or retrieve tenant records.
- `/api/v1/auth/browser-session/restore` requires the cookie, exact same Origin and
  `X-EasyInvio-Session: 1`. It reuses the existing renewal and active-role checks.
- `/api/v1/public/session/logout` requires the same Origin/header, revokes the
  current app session and clears the cookie. Existing bearer logout also clears it.
- All these responses are non-cacheable. No migration is required.
- Navigation clears private forms and in-memory state without logging out on the
  server. Reload/back navigation verifies the cookie before restoring the workspace.
- Explicit workspace logout returns to `/`. Landing logout also returns to `/`.
- Existing session expiry and the eight-hour absolute work-session limit remain.
  Sessions are scoped to the same browser origin; preview and UAT domains do not
  share a login.

## Public guidance

`POST /api/v1/public/assistance` accepts only `{ "query": "..." }`, at most 1000
characters. It reuses `HelpRetriever` with a public documentation identity, no
conversation history, tenant repository, action tools, booking or payment access.
Only the published Help Centre corpus and existing safe public web guidance can
supply answers. Account lookup questions return a workspace link; they do not
invoke the tenant conversational gateway. Authenticated workspace chat continues
to use its existing authorization, tenant scope and action confirmations.

Weight-based cost questions can return the existing illustrative sample calculator
with disclosed parcel assumptions. These are not actual carrier quotations and do
not reflect destination-specific pricing. Actual rates require the workspace.

Existing `LOGISTICS_AGENTS_ENABLED` and private `OPENAI_API_KEY` configuration enable
model assistance. No new key or secret is exposed to the browser. If unavailable,
public guidance still returns documented excerpts and citations. Timeouts and
provider failures have a readable fallback. No hosted environment setting was
changed by this implementation.

The public route has bounded process-local IP/global admission limits and uses the
shared anonymous model budget. Production deployments should additionally apply
an edge rate-limit rule to this path for aggregate protection across instances;
the process counters are not a cross-region spend cap. Avoid logging request bodies.

## Verification

`tests/test_public_experience.py` tests private-question gating, hostile tenant
fields, read-only documentation retrieval, model-free fallback, illustrative
rates, rate limits, secure cookie flags, CSRF, invalid/revoked sessions and logout.

`python tests/public_experience_browser.py` runs with synthetic API responses and
checks matching brand assets, mobile layout, public chat rendering, signed-in
landing navigation, session restoration and both logout paths. It makes no live
provider calls. Screenshots/reports are written only to `output/public-experience-qa`.

Rebuild deployment assets and the worker bundle after changing runtime files:

```powershell
.venv\Scripts\python.exe scripts/build_vercel.py --bundle
.venv\Scripts\python.exe scripts/build_vercel.py
```

After deployment, sign in once to issue the new browser cookie. Confirm home shows
your name, Open workspace restores the session, and Sign out returns home without
the profile menu. Test an Amazon how-to question without signing in, then verify
an actual tracking/refund question asks to open the authorized workspace.
