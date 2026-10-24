# EasyInvio brand assets and preview

The header, sign-in screen and public tracking page show the independent SVG mark beside the restored EasyInvio.com wordmark and Shipping intelligence platform tagline. The name is live HTML, not embedded into the icon. The parcel uses the brand emerald green, the security shield and four nodes use silver-white, and the surrounding routes use the existing indigo/blue palette. Static gradients create a subtle metallic highlight without animation, glow, shadows or a surrounding badge.

The image proportions remain 96:112. Header marks are 38px high on desktop and 30px below 768px. Wordmark size, tagline spacing and sign-in grouping shrink at mobile breakpoints, including 320px. Every displayed image has alt="EasyInvio.com"; adjacent duplicate branding text is hidden from assistive technology. The favicon and transparent PNG app icons share the coloured mark. A manifest supplies ordinary 192px and 512px icons; no offline service worker or installability guarantee is introduced.

## Files changed

- Brand assets: brand-mark.svg, brand.css, favicon.svg, favicon-32.png, apple-touch-icon.png, app-icon-192.png, app-icon-512.png, site.webmanifest.
- Application UI: index.html, tracking.html, tracking-ui.css and frontend/identity.js.
- Hosting: main.py (explicit asset routes and tracking image policy), vercel.json (matching policy), scripts/build_vercel.py (public allowlist), scripts/generate_brand_icons.py (reproducible PNG rendering).
- Email defaults/setup: backend/return_delivery.py, backend/shipment_notifications.py, .env.example, docs_shipment_updates.md. The mailbox login and both notification From addresses are support@easyinvio.com. Explicit environment variables override these defaults; no password is stored in source.
- Regression checks: tests/brand_browser.py, tests/test_runtime_hosting.py, tests/test_email_delivery.py, tests/test_sender_notifications.py, tests/test_return_review_postgres.py.
- Architecture source chapters: functional_architecture.md, integrations.md, operations_runbook.md and technical_architecture.md under docs/platform_overview. Generated inventories, manual, HTML and the output/EasyInvio-Architecture copy/ZIP are regenerated against the committed source.
- Worker deployment: deployment/worker/runtime.tar.gz and deployment/worker/source_manifest.json rebuilt to prevent stale worker deployment.

## Preview locally

Start the application with the project's usual local command, for example `.venv\Scripts\python.exe -m uvicorn main:app --reload`, then open http://127.0.0.1:8000/ and http://127.0.0.1:8000/track. This uses your local configuration and may start enabled local workers; use only your UAT credentials.

For an isolated preview/regression with mocked APIs and no real credentials, run `.venv\Scripts\python.exe -m tests.brand_browser`. Screenshots are saved to output/brand-qa, including 320px, desktop, and light/dark surface previews. To regenerate platform PNG icons after editing the vector, run `.venv\Scripts\python.exe scripts/generate_brand_icons.py` and then rebuild with `.venv\Scripts\python.exe scripts/build_vercel.py --bundle`.

Browser favicons can remain cached after deployment; check a fresh tab or private browsing window if the previous icon persists.
