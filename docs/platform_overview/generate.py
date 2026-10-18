"""Rebuild the repository-derived architecture overview without network access."""
from pathlib import Path
from html import escape
import importlib.metadata as metadata
import json
import sys

ROOT = Path(__file__).resolve().parent
PACKAGES = {
    'API framework': 'fastapi', 'ASGI server': 'uvicorn', 'ASGI foundation': 'starlette',
    'Validation': 'pydantic', 'Configuration': 'pydantic-settings', 'Async HTTP': 'httpx',
    'PostgreSQL driver': 'asyncpg', 'JWT': 'PyJWT', 'Encryption': 'cryptography',
    'Payments SDK': 'stripe', 'Messaging SDK': 'twilio', 'OpenAI client': 'openai',
    'Agents SDK': 'openai-agents', 'PDF generation': 'reportlab', 'PDF merging/reading': 'pypdf',
    'Spreadsheet input': 'openpyxl', 'Images': 'Pillow', 'Help rendering': 'Markdown',
    'Uploads': 'python-multipart', 'Safe XML': 'defusedxml', 'Country codes': 'pycountry',
    'Test runner': 'pytest', 'Async test plugin': 'pytest-asyncio', 'Browser testing': 'playwright',
}
PERSONAS = [
    ('Platform Super Admin', [
        'Network revenue, stored markup, tenant and billing dashboards with date/environment filters.',
        'Client onboarding, company and billing-plan administration; carrier connection management, verification and diagnostics.',
        'Priority margin rules, lane/cargo selectors and platform-owned carrier access controls.',
        'Search and open a client workspace with owner-level assistance; return to admin; attributable append-only request audit.',
        'Support investigations, quote/freight cases, notification controls, credential replacement and agent usage metrics.',
    ]),
    ('Client OWNER / ADMIN', [
        'Company settings, team membership and invitations, subject to each endpoint\'s role rules.',
        'Warehouse addresses by role/default, saved contacts, SKU catalog and reviewed HS classifications.',
        'Store connector configuration, order import/sync, dispatch workspace and bulk CSV processing.',
        'Quotes, customs review, booking, labels, tracking, wallet/card payment flows and operational reporting.',
        'Client support, invoice audit/dispute workflows and protection/claim workflows when eligible.',
    ]),
    ('Warehouse DISPATCHER', [
        'Prepare imported or manual orders; select saved addresses/SKUs and capture measured multi-package contents.',
        'Compare up to ten consolidated offers; review customs and confirm an explicitly selected booking.',
        'Bulk dispatch, label/document bundles, shipment references, tracking and delivery exceptions.',
        'Maintain catalogs where authorized; request parcel assistance or manual freight quotations.',
    ]),
    ('Finance ACCOUNTANT', [
        'Wallet balance/activity and authorized Stripe top-up checkout; financial views subject to endpoint permissions.',
        'Upload carrier invoices, compare exact saved cost snapshots and prepare/review dispute drafts.',
        'Read catalogs and use permitted help/quote tools; no implied dispatcher booking or catalog-write authority.',
    ]),
    ('Registered WhatsApp / web-chat user', [
        'Shared conversational gateway for QUOTE, BOOK_RESERVATION, TRACK_PACKAGE, TOPUP_WALLET, FILE_CLAIM and HELP.',
        'Explicit commands work without an LLM; optional structured intent parsing handles ambiguous wording.',
        'Actions inherit verified membership and role permissions. Quotes require complete saved route data; claims require confirmed cover.',
        'Stable message receipts and ordered choices fence duplicate delivery and uncertain action replay.',
    ]),
    ('Prospective customer / public visitor', [
        'Public Help Centre guides and clearly separated sample/preview workflows.',
        'Opt-in WhatsApp company/profile/email registration with independent email and phone codes.',
        'Verified provisioning creates OWNER membership, profile and a zero-balance GBP wallet; password setup uses Supabase Auth.',
    ]),
]
TECH = [
    ('Web workspace', ['index.html: HTML + JavaScript', 'Tailwind 4 + custom CSS; Lucide', 'Session in memory; role-aware screens']),
    ('Signed / authenticated ingress', ['Twilio WhatsApp webhooks', 'Store and tracking callbacks', 'Stripe payment webhooks']),
    ('Identity and tenant boundary', ['Supabase Auth / JWT + membership', 'Role guards; verified tenant binding', 'Admin assistance + write-ahead audit']),
    ('FastAPI modular monolith', ['main.py lifespan + backend routers', 'asyncio, asyncpg pools, bounded IO', 'Pydantic request/response validation']),
    ('Deterministic domain services', ['RatingService + MarginEvaluator', 'PartnerLifecycleService + FinanceEngine', 'Decimal; wallet locks; replay fences']),
    ('Bounded optional AI layer', ['Supervisor + typed worker outputs', 'Intent / customs / rate badge / help', 'No model authority over wallet or price']),
    ('Operational service modules', ['Dispatch, catalogs, stores, tracking', 'Invoice audits, support and claims', 'PDFs, durable receipts and outbox jobs']),
    ('Supabase managed services', ['PostgreSQL: tenant-scoped records', 'Auth identities + private backend tables', 'RLS, SQL transactions, audit / ledger']),
    ('External adapters / providers', ['EasyPost, Sendcloud, Shippo; Stripe', 'Twilio; configured store / CRM / cover APIs', 'Official tariff lookup; OpenAI; SMTP']),
]
FUNCTIONAL = [
    ('Join and configure', ['Visitor / OWNER / platform admin', 'Company, profile and dual-code signup', 'Team, addresses, contacts, SKU catalog']),
    ('Bring orders into the workspace', ['Store connectors / CSV / manual form', 'Validate identity, addresses and goods', 'Retain order references and row errors']),
    ('Prepare and compare', ['Dispatcher / authorized client user', 'Measured boxes, goods and customs review', 'Deterministic deduplication: up to 10 rates']),
    ('Approve and pay', ['OWNER / ADMIN / DISPATCHER booking', 'Explicit service and price confirmation', 'Wallet reservation or Stripe checkout']),
    ('Buy and document', ['Native booking lifecycle', 'Provider confirmation; capture / release', 'Carrier labels and document bundles']),
    ('Track and synchronize', ['Warehouse / customer / support', 'Validated milestones and exceptions', 'Store fulfillment updates; outbox recovery']),
    ('Reconcile and resolve', ['Finance / support / platform admin', 'Invoice audit, disputes, eligible claims', 'Quote diagnostics and manual freight cases']),
    ('Operate and improve', ['Platform admin / tenant management', 'Revenue, markup and delivery history', 'Margin controls; audited client assistance']),
    ('Assist across channels', ['WhatsApp / desktop chat / Help Centre', 'Shared authenticated action controller', 'Optional AI + documentation citations']),
]


def diagram(filename, title, subtitle, cards, footer, functional=False):
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="1150" viewBox="0 0 1500 1150" role="img">',
           f'<title>{escape(title)}</title><desc>{escape(subtitle)}</desc>',
           '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0 0L10 5L0 10" fill="#64748b"/></marker></defs>',
           '<rect width="1500" height="1150" fill="#f8fafc"/>',
           '<style>text{font-family:Arial,sans-serif}.title{font-size:36px;font-weight:700;fill:#0f172a}.sub{font-size:19px;fill:#475569}.head{font-size:21px;font-weight:700;fill:#0f172a}.body{font-size:18px;fill:#334155}.small{font-size:17px;fill:#475569}</style>',
           f'<text x="48" y="66" class="title">{escape(title)}</text>',
           f'<text x="48" y="104" class="sub">{escape(subtitle)}</text>']
    for i, (heading, lines) in enumerate(cards):
        row, col = divmod(i, 3)
        x, y = 48 + col * 478, 175 + row * 280
        svg.append(f'<rect x="{x}" y="{y}" width="448" height="214" rx="16" fill="white" stroke="#cbd5e1" stroke-width="2"/>')
        svg.append(f'<rect x="{x}" y="{y}" width="448" height="8" rx="4" fill="{("#059669" if functional else "#4f46e5")}"/>')
        svg.append(f'<text x="{x+20}" y="{y+44}" class="head">{i+1:02d}  {escape(heading)}</text>')
        for line_number, line in enumerate(lines):
            svg.append(f'<text x="{x+20}" y="{y+86+line_number*32}" class="body">{escape(line)}</text>')
        if functional and col < 2:
            svg.append(f'<path d="M{x+450} {y+105}H{x+472}" stroke="#64748b" stroke-width="2" marker-end="url(#arrow)"/>')
        if not functional and row < 2:
            svg.append(f'<path d="M{x+224} {y+219}V{y+264}" stroke="#64748b" stroke-width="2" marker-end="url(#arrow)"/>')
    svg.append('<rect x="48" y="1025" width="1404" height="82" rx="12" fill="#e0e7ff"/>')
    for i, line in enumerate(footer):
        svg.append(f'<text x="70" y="{1056+i*27}" class="small">{escape(line)}</text>')
    if functional:
        for row in range(3):
            for col in range(2):
                x, y = 48 + col * 478 + 472, 175 + row * 280 + 105
                svg.append(f'<path d="M{x-8} {y-5}L{x} {y}L{x-8} {y+5}Z" fill="#64748b"/>')
    else:
        for row in range(2):
            for col in range(3):
                x, y = 48 + col * 478 + 224, 175 + row * 280 + 264
                svg.append(f'<path d="M{x-5} {y-8}L{x} {y}L{x+5} {y-8}Z" fill="#64748b"/>')
    svg.append('</svg>')
    rendered = '\n'.join(svg)
    styles = {'title': 'font-size:36px;font-weight:700;fill:#0f172a', 'sub': 'font-size:19px;fill:#475569', 'head': 'font-size:21px;font-weight:700;fill:#0f172a', 'body': 'font-size:18px;fill:#334155', 'small': 'font-size:17px;fill:#475569'}
    for name, style in styles.items():
        rendered = rendered.replace(f'class="{name}"', f'style="font-family:Arial,sans-serif;{style}"')
    (ROOT / filename).write_text(rendered, encoding='utf-8')


def main():
    versions = {package: metadata.version(package) for package in PACKAGES.values()}
    (ROOT / 'versions.json').write_text(json.dumps({'captured': '2026-10-18', 'python': sys.version.split()[0], 'local_environment': versions}, indent=2)+'\n', encoding='utf-8')
    diagram('technical_architecture.svg', 'EasyInvio | Technical architecture',
            'Repository snapshot: 18 October 2026. Logical components inside one Python application, not separate microservices.', TECH,
            ['Arrows show logical layer flow, not a complete endpoint or deployment network map. Optional AI delegates to native services.',
             'Private DB access is server-side. Durable SQL state fences external side effects; provider and database commits are not atomic.'])
    diagram('functional_architecture.svg', 'EasyInvio | Functional architecture',
            'Read stages 01–08 in order; stage 09 assists multiple stages. Actions always inherit the authenticated role.', FUNCTIONAL,
            ['All stages: tenant isolation • exact money • explicit consequential-action approval • audit and reconciliation.',
             'Provider-dependent functions require activation. Manual freight intake is available; native road/sea booking is not implied.'], True)
    rows = ''.join(f'<tr><td>{escape(purpose)}</td><td>{escape(package)}</td><td>{escape(versions[package])}</td></tr>' for purpose, package in PACKAGES.items())
    personas = ''.join(f'<h3>{escape(name)}</h3><ul>'+''.join(f'<li>{escape(feature)}</li>' for feature in features)+'</ul>' for name, features in PERSONAS)
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EasyInvio platform architecture and capabilities</title>
<style>body{{font:16px/1.65 system-ui,sans-serif;color:#172033;background:#f8fafc;margin:0}}main{{max-width:1100px;margin:auto;padding:40px 24px}}h1{{font-size:34px;line-height:1.2}}h2{{margin-top:40px}}h3{{margin-top:24px}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{padding:9px 14px;text-align:left;border-bottom:1px solid #dbe2ec}}img{{width:100%;height:auto;background:white;border:1px solid #dbe2ec}}a{{color:#4338ca}}.note{{padding:18px;background:#e0e7ff;border-radius:10px}}li{{margin:6px 0}}code{{overflow-wrap:anywhere}}@media print{{body{{background:white}}main{{max-width:none;padding:0}}img, tr{{break-inside:avoid}}h2,h3{{break-after:avoid}}}}</style></head>
<body><main><h1>EasyInvio.com: technology, architecture and capabilities</h1>
<p>Repository review dated 18 October 2026. This describes implemented code, not a certification of deployed services, production readiness or provider acceptance. No secrets, customer records or live database inspection were used.</p>
<p class="note"><strong>Architecture:</strong> an asynchronous Python/FastAPI modular monolith, a browser single-page application, Supabase PostgreSQL/Auth, external service adapters, durable SQL jobs and bounded optional OpenAI assistance. Pricing, financial locks and consequential-action authorization remain deterministic.</p>
<h2>1. Technology stack and versions</h2>
<p>Python target: <strong>3.12+</strong>; inspected project virtual environment: <strong>{escape(sys.version.split()[0])}</strong>. The following are installed local package versions, not claims about a remote server. requirements.txt defines dependency ranges; requirements.lock.txt pins only part of the current dependency set, including no OpenAI package pins. The lockfile therefore does not fully reproduce this environment.</p>
<table><thead><tr><th>Purpose</th><th>Package</th><th>Local version</th></tr></thead><tbody>{rows}</tbody></table>
<ul><li>Frontend: HTML5, modern vanilla JavaScript and CSS; Tailwind browser CDN requests major version 4 (exact patch not pinned); Lucide 0.468.0. No React/Next.js build is used for the main index.html UI.</li>
<li>Persistence: Supabase-hosted PostgreSQL, SQL migrations through 039, Supabase Auth via HTTP/JWT and backend asyncpg. Hosted PostgreSQL/Supabase versions were not inspected.</li>
<li>AI defaults: gpt-4o-mini and text-embedding-3-small; configurable names, not verified active model versions. Embeddings are 256-dimensional in the help retriever; small local corpus search uses in-process vectors, not a dedicated vector database.</li>
<li>Money/concurrency: Python Decimal, fixed-point SQL numeric, asyncio, bounded provider calls, wallet row locks, idempotency receipts and durable outbox/reconciliation states.</li>
<li>External integrations: EasyPost, Sendcloud, Shippo, Stripe, Twilio WhatsApp, configured Shopify/WooCommerce/Amazon order pathways, HubSpot, official UK tariff lookup and XCover/XClaim. SDK versions above are distinct from external API versions, which can vary by connector.</li>
<li>Delivery: Uvicorn serves FastAPI and index.html; optional separate local frontend server. This review does not establish a production cloud host, container platform, Kubernetes, Redis, Celery or a separate microservice deployment.</li></ul>
<h2>2. Downloadable architecture diagrams</h2>
<p><a href="technical_architecture.svg" download>Technical SVG</a> · <a href="technical_architecture.png" download>Technical PNG</a> · <a href="functional_architecture.svg" download>Functional SVG</a> · <a href="functional_architecture.png" download>Functional PNG</a> · <a href="technical_architecture.mmd" download>Technical Mermaid</a> ? <a href="functional_architecture.mmd" download>Functional Mermaid</a> · <a href="versions.json" download>Version inventory</a></p>
<img src="technical_architecture.svg" alt="EasyInvio technical architecture"><img src="functional_architecture.svg" alt="EasyInvio functional architecture">
<p>Technical arrows summarize layers; actual services call each other within the same process. Provider calls and SQL transactions have independent failure boundaries. Functional stages 01–08 describe the lifecycle, while chat/help crosses several stages.</p>
<h2>3. High-level features by persona</h2>{personas}
<p>These are capability groupings, not a replacement for endpoint-specific permissions. A support operator is a platform-admin responsibility in the current implementation, not a separately guaranteed SUPPORT role. Assistance grants selected workspace-owner functionality and does not impersonate a particular employee's narrower role.</p>
<h2>4. AI and documentation flow</h2>
<p>LogisticsSupervisor coordinates ingestion, customs preparation, deterministic invoice/support delegates, optional MarginOptimizerAgent advice and HelpRetriever. The rate badge evaluates up to ten finalized offers within 1.5 seconds and cannot reprice, reorder or buy them. Invoice comparisons and tracking-ticket staging do not require an LLM. Explicit chat commands and WhatsApp registration also avoid model calls.</p>
<p>The Help Centre corpus is defined by backend/help_center.py GUIDES: built-in guide bodies plus the five root files docs_order_processing.md, docs_routing_rules.md, docs_tracking_branding.md, docs_returns_lifecycle.md and docs_carrier_pickups.md. backend/agents/rag_support.py splits sections, versions chunks and optionally ranks embeddings; its vector cache is output/agents. Answers cite /help/ guide sections. Keyword retrieval and related-guide fallbacks remain available when AI is off. This is documentation retrieval, not a search across customer records.</p>
<h2>5. Implementation and activation boundaries</h2>
<ul><li>Carrier adapters and financial flows exist; live results require valid accounts, contracts, permissions, route eligibility, funding and environment alignment. Rate availability does not prove booking availability.</li>
<li>Road/sea freight: measured freight arithmetic and manual support intake exist. Native parcel adapters do not supply universal industrial freight quotes or sea bookings. Automatic courier pickup scheduling is not established.</li>
<li>Storefront intake and tracking are connector-specific. Shopify reverse-delivery tracking requires a verified native return reference; this is not universal automatic returns, refunds, restocking or exchange support.</li>
<li>Customs: official tariff search and reviewed data preparation exist. Human declaration review and destination-specific requirements remain necessary; no universal customs filing certification is claimed.</li>
<li>Protection and claims: estimation, policy/claim integration code and support intake exist, but sale/filing depends on configured provider coverage and permissions. A premium estimate alone is not purchased insurance or an approved claim.</li>
<li>WhatsApp signup requires migration 039, signed public HTTPS Twilio ingress, enabled signup, Supabase email OTP and production custom SMTP/password recovery configuration. New wallets start at zero.</li>
<li>Neither this inventory nor the historical repeated calculator matrix grants full UAT sign-off. Production credentials, deployed migrations and external acceptance need separate verification.</li></ul>
<h2>6. Evidence and scope</h2>
<p>Reviewed: main.py; index.html; requirements.txt; requirements.lock.txt; installed distribution metadata; backend/agents; backend/help_center.py; catalog, assistance, onboarding, dispatch, storefront and return modules; migrations 035–039; docs/agent_architecture.md; docs/admin_client_assistance.md; docs/shipment_quote_support_2026-10-15.md. Older README statements were reconciled against newer modules and feature-specific documentation.</p>
<p>Artifacts can be regenerated offline with <code>.venv\\Scripts\\python.exe docs/platform_overview/generate.py</code>. PNG exports are rendered separately from the SVG files. No application behavior or environment settings were changed.</p>
</main></body></html>'''
    (ROOT / 'overview.html').write_text(html, encoding='utf-8')


if __name__ == '__main__':
    main()
