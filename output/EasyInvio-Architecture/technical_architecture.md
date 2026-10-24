# Technical architecture

The deployed unit represented by this repository is an asynchronous Python FastAPI application with a vanilla JavaScript single-page web interface. Logical services and agent workers are Python components within that application; PostgreSQL tables/outboxes coordinate durable state. External providers commit independently of database transactions. No Redis, Celery, Kubernetes, separate vector database or separate carrier microservice deployment is established by this code.

![Technical architecture](technical_architecture.svg)

## Technology and version authority

`versions.json` records the generator’s Python interpreter, installed distributions, requirement declarations and lockfile entries. Installed local versions are not remote server versions. `requirements.txt` contains ranges/unpinned packages; `requirements.lock.txt` pins only a subset of the expanded dependency set. A complete reproducible production dependency artifact is an operational deliverable, not implied by that partial lockfile.

| Layer | Implementation | Important boundary |
| --- | --- | --- |
| Web client | Root `index.html`, HTML/CSS and modern vanilla JavaScript; Tailwind browser CDN major 4 and Lucide 0.468.0 | No React/Next build owns this UI; CDN patch versions and production asset strategy require separate control |
| API/runtime | FastAPI, Starlette, Uvicorn, Pydantic 2, pydantic-settings, asyncio | Lifespan creates real services; ASGITransport alone does not run startup |
| HTTP and validation | httpx, strict Pydantic schemas, bounded streams, timeouts, trusted endpoint/host checks | A provider body is untrusted and never becomes a fabricated quote or confirmed charge |
| Persistence | Supabase PostgreSQL/Auth; asyncpg; application transactions/advisory locks/row locks | Backend DB role can bypass RLS, so explicit tenant predicates remain mandatory |
| Identity | Supabase Auth HTTP/JWKS/JWT, application auth sessions, Fernet-encrypted provider tokens/credentials | Server-held refresh secrets; browser identity does not come from sender_id or an editable tenant field |
| AI | OpenAI Python client and Agents SDK, structured outputs/tools, optional embeddings | Bounded advisory/preparation layer, not monetary or authorization authority |
| Payment/messaging | Stripe and Twilio SDKs; verified webhook flows | Correct environment and signatures, not a successful popup or HTTP POST alone, establish success |
| Documents/imports | reportlab, pypdf, openpyxl, Pillow, safe XML, Markdown, multipart | PDF/data generation does not imply external filing or dispatch |
| Verification | pytest, pytest-asyncio, httpx mock/ASGI transports, Playwright and a Node syntax/contract check | Synthetic checks and live provider acceptance have different evidence scopes |

## Runtime composition

`main.py:lifespan` creates `LogisticsSupervisor` and its bounded runtime, then enters `deterministic_lifespan`. Configured mode loads Settings, installs query-secret redaction, builds a shared httpx client and asyncpg pool, verifies the database role and required schema objects, and wires the domain services into `app.state`. The optional agents’ invalid configuration disables assistance rather than rewriting financial behavior.

The pool reserves capacity for the dispatch listener. Database settings bound statement, lock and idle-transaction timeouts. A trusted role must have BYPASSRLS and the ability required by authenticated-role permission checks. Production startup checks a set of required tables, while feature-specific services can enforce additional migration readiness on first use; startup success does not prove all optional migrations/credentials are ready.

| `app.state` component | Responsibility/source |
| --- | --- |
| `settings`, `repository`, `rating` | Configuration, tenant-scoped carrier access and deterministic rates in main.py |
| `finance` | Wallet reservation, submission, capture/release and Stripe top-up creation |
| `xcover`, `protection`, `claims` | Provider client, protection purchase/reconciliation, XClaim submission/settlement |
| `automation_freight` | Validated Order snapshots, packing/customs preparation and quote-only/fulfillment modes |
| `partner_lifecycle`, `native_partners` | Selected-offer purchase/cancel/documents and configured native order/tracking jobs |
| `csv_orders`, `ecommerce`, `amazon_inbound` | Upload/order persistence, configured storefronts and marketplace intake |
| `dispatch_updates` | Dedicated PostgreSQL commit-time event listener and workspace update delivery |
| `tracking_support`, `support_delivery` | Tracking ingestion, ticket staging and notification outboxes |
| `payment_snapshots`, optional `sandbox_billing` | Verified Stripe event reconciliation and explicit sandbox controls |
| `admin_portal`, `whatsapp`, `twilio_validator`, `jwks` | Management, phone identity/conversation integration and JWT validation |
| optional `hubspot` | Verified configured CRM account, synchronization and provisioning |
| `logistics_supervisor` | Ingestion/customs/rate recommendations, deterministic audit/support delegates and help retrieval |

`ReverseLogisticsService`, `TenantCatalogService` and conversational gateway objects are constructed around shared services/pools when needed. They are not additional independent network servers.

## Background workers

The configured lifespan owns and cancels worker tasks on shutdown. Database jobs/outboxes survive process restarts; in-memory semaphores/caches/metrics do not.

| Task | Work | Activation |
| --- | --- | --- |
| E-commerce tracking worker | Retry pending imports/tracking delivery and invoke the existing return synchronization jobs | Configured mode; per-connector authorization controls effects |
| Native partner worker | Configured order synchronization, provider callback/event processing and reconciliation | Configured mode; native options/credentials determine eligible jobs |
| Partner lifecycle worker | Pending label GET polling and cancellation confirmation | Configured mode; preserves submitted reservation fencing |
| Dispatch updates worker | PostgreSQL LISTEN-based committed workspace events | Configured database/listener connection |
| Amazon inbound worker | Bounded, authenticated seller notification/order intake | Configured mode; seller credentials and connection state gate requests |
| Tracking/support worker | Durable exception/support work | Configured mode; authenticated event and settings controls |
| Support delivery worker | Approved email/WhatsApp delivery/status and retry state | Configured settings, recipient/consent/window rules |
| Payment snapshot worker | Retrieve and reconcile verified Stripe event snapshots | `STRIPE_ENABLED` |
| Card basket worker | Continue baskets only after verified funding, then existing selected-offer checkout | `STRIPE_ENABLED` |
| Protection worker | Resolve pending policy outcomes | XCover configuration/contract readiness |
| Claims worker | Submit/reconcile eligible claims and provider settlement evidence | XClaim configuration readiness |
| HubSpot worker | Configured CRM outbox/provisioning/metrics work | `HUBSPOT_ENABLED` and valid optional configuration |

These are deterministic operations workers. They are distinct from the named AI specialists in [agent_reference.md](agent_reference.md).

## Request and trust boundaries

Browser requests pass through identity/session, tenant and role checks before domain methods. Super-admin assistance retains the original operator and selected tenant context. Public Twilio, provider, Stripe and store callback routes implement their own signature/identity checks; absence of an OAuth scheme in generated OpenAPI does not make them unauthenticated.

The API reference lists declared dependencies and source locations. Some constraints live in called helpers, so the dependency column is not a complete authorization policy. Frontend visibility improves usability but never replaces backend permission checks.

Main routers are assembled from domain modules. Current OpenAPI is exported without lifespan and includes request schemas, constraints, security declarations where supplied, status responses and operation IDs. Some endpoints return validated domain dictionaries without a response model; an empty OpenAPI response schema must not be interpreted as an empty response.

## Domain source ownership

| Area | Principal files |
| --- | --- |
| Entrypoint/configuration/auth/rates/finance | `main.py`, `backend/identity.py`, `backend/database_tls.py` |
| Workspaces, personas and admin | `workspace_personas.py`, `web_registration.py`, `workspace_settings.py`, `admin_portal.py`, `admin_management.py`, `client_assistance.py` |
| Carrier routing and diagnostics | `aggregator_registry.py`, `sendcloud_adapter.py`, `carrier_access.py`, `carrier_consolidation.py`, `rate_diagnostics.py`, `platform_carriers.py`, `credential_rotation.py` |
| Orders, packing and booking | `automation_freight_engine.py`, `automation_three_partners.py`, `order_csv.py`, `package_sets.py`, `package_guidance.py`, `customer_checkout.py`, `bulk_checkout.py`, `booking_receipt.py` |
| Documents and dispatch | `dispatch_workspace.py`, `dispatch_realtime.py`, `dispatch_pdf.py`, `multi_label.py`, `advanced_logistics.py` |
| Payments and financial audit | `card_checkout.py`, `payment_gateway.py`, `invoice_upload.py`, `sandbox_hooks.py` |
| Stores/marketplaces/returns | `ecommerce_sync.py`, `ecommerce_connectors.py`, `ecommerce_inbound.py`, `store_connections.py`, `store_returns.py`, `reverse_logistics.py`, `return_ingress.py`, `return_documents.py` |
| Messaging and signup | `whatsapp_ingress.py`, `whatsapp_onboarding.py`, `whatsapp_bot.py`, main.py WhatsAppService, `agents/conversational_gateway.py` |
| Tracking/support/claims | `tracking_and_support.py`, `support_workflow.py`, `support_delivery.py`, `support_alert_controls.py`, `shipment_protection.py`, `xcover_claims.py`, `conversational_claims.py` |
| CRM and research | `hubspot_crm.py`, `hubspot_provisioning.py`, `tools/sme_lead_scraper.py` |
| AI and help | `agents/supervisor.py`, `workers.py`, `margin_optimizer.py`, `runtime.py`, `config.py`, `models.py`, `conversation_context.py`, `rag_support.py`, `routes.py`, `help_center.py` |

Paths in the table are relative to `backend/` except where stated. The generated source map lists all Python classes/functions and exact lines, including utility/diagnostic modules. A module’s presence does not mean it runs at startup; seed, migration and probe scripts must be treated as potentially mutating tools.

## Concurrency and failure design

Async provider fan-out, order limiters and model semaphores bound local concurrency. Stable receipts, PostgreSQL advisory locks, unique constraints and wallet row locks coordinate across processes. Per-process model rate limits are abuse controls, not a global billing limit.

No ordinary database transaction can atomically include a carrier, Stripe, Supabase Auth, Shopify or insurer commit. Write-ahead submitted/processing states, exact references, later GET observations and operator reconciliation handle this gap. Never automatically repeat a charge-producing provider mutation after timeout. A network error is not proof of rejection.

Returns add a private receipt before external work, allow only currently active return connections for the new network-selection mode, revalidate warehouse version and delegate financial settlement to the same native lifecycle. Legacy return quoting retains its historical connection behavior; the new flag does not reactivate retired accounts.

## Frontend lifecycle

The root SPA holds session access state in memory. It restores neither an authenticated session nor shipment forms merely by reading a stored token after page refresh. Renewal uses the application identity service while active; logout, identity/workspace change and assistance changes clear scoped forms, quotes, dialogs and chat state. Recovery links use the configured fragment/token contract and verified identity before password setup.

The code contains successive wrappers/extensions around shared UI functions. Before modifying `setView`, `clearSession`, renderers or API helpers, find the final assignment and all wrappers rather than editing an obsolete earlier definition. New interfaces should use textContent/DOM-safe rendering, actual API helpers, role state, responsive layout and identity-generation checks for asynchronous results.

## Deployment assumptions

Uvicorn serves the API and root HTML; a separate local frontend helper is optional. Public integrations need a reachable HTTPS origin and correctly configured callback URLs. ngrok is a local development ingress helper, not evidence of a production hosting architecture. Supabase custom SMTP is configured in Auth, not implemented as a second direct SendGrid mail engine.

Environment values, production host details, deployed PostgreSQL/Supabase versions, active contracts, external quotas and carrier coverage are deployment facts. The generated inventory deliberately reads source declarations and installed package metadata rather than private environment files or live provider databases.

## Queued WhatsApp and PAF execution (migration 043)

`app.state.whatsapp_queue` owns the encrypted inbox/outbox and Twilio REST client. `WHATSAPP_QUEUE_WORKERS` supplies 2 worker slots by default (1?8 per process). `app.state.paf` owns the shared asynchronous Ideal Postcodes adapter. Startup checks the two queue tables when Twilio is enabled; the key ring is mandatory. Webhook handlers delegate to `accept_whatsapp`, which authenticates and commits without any carrier lookup. Workers resolve identity and run `ConversationalActionGateway`/onboarding after the database claim commits. No database connection is retained during provider work or outbound REST.

Each phone/receiving-number thread is serialized using ordered eligible heads and `FOR UPDATE SKIP LOCKED`. Different threads and instances can progress independently. READY responses resume only unsent parts; PROCESSING/SENDING/REVIEW_REQUIRED are durable fences, not expiring leases that authorize replay. Encrypted raw events/replies require key rotation and retention controls. The targeted sub-500 ms ack must be load-tested against actual PostgreSQL/pool/network conditions.

## Manifest and carrier-media services (migration 044)

`ManifestService` is registered as app.state.manifests. It uses the existing pool, settings and repository; carrier submissions and ReportLab rendering run after short claim transactions commit. Preview aggregates all eligible shipment counts/packed weights; close uses bounded 1,000-shipment batches, tenant/account advisory locks, the cancellation-lock namespace and row locks. Claims and immutable snapshots precede upstream calls. Stored provider references permit GET-only recovery. PDFs are stored as private database bytes, with authenticated and narrowly signed downloads.

`QRMediaService` and logistics_media normalize actual carrier documents with Pillow/PyMuPDF, reject active/external SVG content, enforce limits and persist immutable private Supabase Storage objects. A database asset record binds tenant, shipment, hash and object key. No general URL proxy or public writable bucket is introduced. WhatsApp outbox parts support one signed image and a separate fallback viewing URL. Signed status callbacks verify account, SID and phone pair before scheduling an idempotent fallback or resolving uncertain REST acceptance. These are deterministic services, not new model agents.

## Shared Tracking 2.0 domain

`backend/tracking_workspace.py` owns tenant-scoped search, multi-parcel/order/return projections, customer capabilities and operator review. The browser workspace, public `/track` page and conversational gateway consume this same domain. Existing signed ingress and TrackingSupportService remain the event owner; migration 045 adds immutable event protection and private operational tables. `backend/tracking_refresh.py` implements optional EasyPost GET-only reconciliation, leased SQL work, account-wide cooldowns and bounded retry exhaustion. Startup enables the observer only after all eight 045 tables exist; legacy booking/tracking remains available without that migration. Polling defaults off.

## Manifest action ownership

`backend/return_review.py` implements the manual two-phase reverse workflow: tenant-scoped restoration, typed parcel/goods/customs edits, quote-only preparation, expiry checks and explicit offer selection. `return-workspace.js` mounts the return form inside Create shipment, fences session/workspace changes and never exposes an unpaid label. Selection atomically claims the existing original-parent return receipt before delegating to PartnerLifecycleService or the exact-price Stripe basket. `backend/return_delivery.py` stages payment notices and, only after verified payment and carrier confirmation for the selected offer, label notices. Its optional Hostinger SMTP/Twilio worker (with SendGrid only as an explicitly selected legacy email transport) commits SENDING before network I/O and never retries ambiguous sends. Private migration 046 tables own preparation/outbound receipts; signed customer document downloads recheck the payment and shipment state. Existing rating, booking and financial owners remain unchanged.

`backend/manifest_workflow.py` owns the read-only action policy and allowlisted requote projection. `advanced_logistics.py` returns carrier/service identity, quote expiry, server time and evidence flags; its tenant-bound GET requote-context route never books or mutates rows. `manifest-workflow.js` renders context-appropriate actions and a customer-readable drawer, restores complex shipment facts and drops expired batch selections. SQL uses a bounded lateral lookup for unresolved historical provider jobs. Existing native confirmation, financial locks and document host validation remain authoritative.

## Public brand assets

The eight explicit brand asset routes in main.py serve SVG, PNG, CSS and the web manifest with correct media types and nosniff headers. scripts/build_vercel.py includes exactly these files in the public CDN allowlist; application secrets and exports remain excluded. Public tracking CSP permits only same-origin images and manifests, with its existing script, frame and form restrictions preserved. Header dimensions are reserved before SVG loading; explicit light/dark surface classes control monochrome contrast. scripts/generate_brand_icons.py renders the checked-in SVG into transparent platform sizes using the existing development browser, without network requests.
