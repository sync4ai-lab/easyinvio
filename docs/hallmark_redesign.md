# EasyInvio visual redesign

Local feature branch: `feat/hallmark-app-redesign`, based on `58d0ab2`.
No merge or deployment to UAT or Production is part of this change.

## Review it locally

The isolated layout preview runs at http://127.0.0.1:8012/.
Home: `/`; account: `/login`, `/login?mode=signup`; pricing: `/pricing`.
Layout preview disables real authentication, database and provider calls.

To sign in with your existing test account, open a **new PowerShell terminal**:

```powershell
cd C:\Projects\easyinvio\tmp\hallmark-redesign
C:\Projects\easyinvio\.venv\Scripts\python.exe scripts/dev.py --env-file ..\local-development\.env.local --port 8013
```

Then open http://127.0.0.1:8013/. This uses your existing private local settings;
it starts the web application with background jobs off. No environment file is
copied or committed. Your existing app at port 8000 remains separate.
Do not add `--whatsapp` or start another shared-queue consumer for a visual review.
To review from your phone, use `--lan` with your laptop's Wi-Fi IPv4 address,
or deliberately point a tunnel at port 8013. Changing the WhatsApp callback
is unnecessary for this visual redesign; the existing quote handoff is tested offline.

## What changed

- One shared palette and type system across home, pricing, account and workspace.
- Original logo asset and brand green retained; darker green actions improve light-surface contrast.
- Home prioritizes the existing secure parcel tracking form; existing examples stay labelled as examples.
- Login is a two-column brand/form composition on desktop and a single column on phones.
- Registration retains all fields, country selection, business/personal choice and verification flow.
- Existing role-based tabs remain; on phones a native Workspace menu disclosure presents the same buttons.
- Existing table scroll regions, error messages, loading states, quote draft transfer, password controls and approvals remain.
- No additional font downloads, runtime libraries, AI calls, provider calls, polling or paid services.

## Copy and material

Hero: “Less shipping admin. More parcels on their way.” becomes “Less admin. More parcels moving.”
The longer original introduction is retained below the hero.
The new short introduction says “Your orders, labels and tracking. Connected through your workspace and WhatsApp.”
Context labels move below headings; static badges use sentence case.
Decorative link arrows and business/personal emoji icons are removed; destinations and controls remain.
Help-link middle dots become slashes. Terms, consents and shipping disclaimers are not rewritten.
Existing illustrative orders, analytics, feedback, pricing and integration claims are carried over as found;
they are not new claims or verified customer evidence. Review those facts before public launch.

## Validation

```powershell
$env:BROWSER_CHANNEL='msedge'
C:\Projects\easyinvio\.venv\Scripts\python.exe tests/quick_quote_signin_browser.py
C:\Projects\easyinvio\.venv\Scripts\python.exe tests/hallmark_redesign_browser.py
C:\Projects\easyinvio\.venv\Scripts\python.exe -m pytest tests/test_public_experience.py tests/test_identity.py tests/test_manifest_workflow.py -q
```

The visual script requires the layout server on port 8012. Its API responses and
account are entirely synthetic. It visits all nine customer tabs at five widths,
checks the mobile menu, focus and reduced motion, and captures screenshots.
The existing quote regression checks guest-to-login and restored-session handoff.
No live WhatsApp messages, bookings, payments, insurer claims or database migrations are used.
Legacy tests asserting the former dark palette need a separately approved baseline refresh;
they have not been edited to make this redesign pass.

## Design review tools

Hallmark static audit and preserved-interface comparison are recorded locally in `.hallmark`.
Its Puppeteer renderer is unavailable in this environment. Screenshots and interactive
acceptance instead use the project's Playwright package with Microsoft Edge.
The finish review is in-thread, not an independent subagent review.

Visual inspiration: Linear's navigation clarity (https://linear.app/changelog/2026-03-12-ui-refresh),
Wise's clear review-before-payment flow (https://wise.com/help/articles/2977959/how-do-i-send-money-with-wise),
and Shippo's shipping task focus (https://goshippo.com/products/shipping).
No competitor branding, copy, assets or functionality is copied.

## Future changes

Read `design.md` first. Edit semantic roles in `tokens.css`, shared app presentation
in `design-system.css`, and public composition in `public-redesign.css`.
New assets are explicitly allowed by the existing static route and Vercel asset builder.
To release later: review this branch locally, explicitly request UAT integration/testing,
then approve Production separately. Do not replace private environment values for a design change.

## Existing manifest-test limitation

The unchanged `tests/manifest_workflow_browser.py` completed its OWNER, ADMIN,
DISPATCHER, ACCOUNTANT and INDIVIDUAL action checks (18 shipment states each),
then failed the SUPER_ADMIN visibility assertion at line 160. The same assertion
also fails when serving the original `58d0ab2` files. Permissions were not altered
as part of this visual task. This fixture is not reported as a fully passing suite.
