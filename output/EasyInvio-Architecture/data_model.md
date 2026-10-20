# Data model and migrations

Supabase PostgreSQL stores tenant identity, prepared and booked shipments, funds, operational receipts and outboxes. Supabase Auth owns credentials and verified identity. Application SQL and external provider calls have independent commits; durable states retain uncertainty rather than treating a network failure as rollback.

The generated [data_dictionary.md](data_dictionary.md) lists every checked-in migration and exact CREATE TABLE definitions. [data_inventory.json](data_inventory.json) also lists later ALTER targets and SQL object references. These are source-derived, not a live database introspection or a consolidated reconstruction of every ALTER/trigger/index into a final schema.

## Baseline schema

The baseline tables used by main.py include tenants, users, carrier_accounts, margin_rules, shipments, wallets, wallet_topups, wallet_reservations, wallet_ledger, whatsapp_bindings, whatsapp_routes, whatsapp_quote_choices and whatsapp_receipts. The original initial-schema steps are not fully present as migrations 001–005 in this checkout. An authorized baseline must exist before applying the checked-in sequence beginning at 006. A developer must not invent a replacement financial schema from field guesses.

Auth IDs and application membership IDs are distinct. Most domain objects scope by tenant_id and id; relevant foreign keys bind that pair to prevent cross-tenant references. A `created_by_user_id` membership reference and an `actor_auth_user_id` identity reference are not interchangeable.

## Domain ownership

| Domain | Principal records | Authoritative service |
| --- | --- | --- |
| Workspace | tenants, users, profiles/settings, invitations, web_registration_sessions | Identity, workspace settings/personas, admin management and registration |
| Sessions | app_auth_sessions, app_login_limits and identity-rate-limit state | Identity gateway; encrypted provider token envelopes |
| Shipping | shipments, package/goods records, partner_shipping_offers, quote snapshots | Rating, automation/order preparation and native partner lifecycle |
| Carrier configuration | carrier_accounts, platform connection/options and credential rotation/audit records | Platform carrier management and registry |
| Pricing | margin_rules, individual_pricing_settings, individual_pricing_events | Business margin evaluator and server-owned individual policy |
| Funds | wallets, wallet_topups, wallet_reservations, wallet_ledger, payment_carts and Stripe snapshot/reconciliation records | FinanceEngine/payment gateway/card checkout |
| Catalogs | tenant_catalog_addresses, tenant_catalog_contacts, tenant_catalog_products | TenantCatalogService with version/default/archive rules |
| Conversations | conversational_messages, whatsapp_quote_choices/receipts/bindings/routes | Shared gateway, receipt store and verified phone service |
| Signup | whatsapp_registration_queue, whatsapp_registration_receipts, web_registration_sessions | Signup managers plus Supabase Auth |
| Returns | reverse_logistics_requests, shipments return parent/lifecycle, return tracking outbox state | ReverseLogisticsService and existing booking/store return services |
| Stores | ecommerce_stores, workspace_store_connections, ecommerce_tracking_outbox, amazon_order_notifications | E-commerce/store connection/seller intake services |
| Tracking/support | tracking_events, support_tickets, activity/review/alert/outbox records, automation_failures | Tracking ingestion, support workflow and delivery workers |
| Invoice disputes | persisted source baselines, billing_disputes and related audit/activity | Exact invoice upload/audit and dispute workflow |
| Protection/claims | quote/policy/reservation/claim/evidence/settlement records declared in protection migrations | ProtectionService and XClaimService |
| Admin/CRM | admin configuration/management/assistance audit records, CRM outbox/provisioning/metrics | Platform management, assistance and HubSpot services |
| Dispatch | workspace_dispatch_events and PostgreSQL notifications | Commit-time dispatch events and realtime listener |

Use the generated dictionary for exact table names/DDL, not the grouped shorthand above. Multiple tables can participate in one domain; some foundational tables are baseline-only.

## Important snapshots

`shipments.logistics_metadata.automation_order` retains validated addresses, cargo/packages, goods, customs consent and return context. `automation_customs` is the reviewed declaration snapshot. `automation_label` retains the confirmed native label/documents; `return_dropoff_qr_code_url` is the real provider drop-off asset where available. These private snapshots are projected for public/client transport rather than rewritten by AI.

`pricing_snapshot.selected_rate`, immutable offer IDs, source connection fingerprint, wholesale/client/currency fields and expiry establish what was quoted/selected. Provider rate IDs are not interchangeable across accounts or environments. Persisted invoice baselines retain actual component breakdowns; a display estimate is not an authoritative wholesale baseline.

Catalog copies protect existing shipments against later catalog edits. Return warehouse identity/version protects against destination changes between preparation and purchase. A policy/claim payload digest, receipt input hash or idempotency key is part of its semantic replay contract; changing payload contents under the same key is a conflict.

## Durable states and recovery

| Aggregate | States or stages relevant to callers | Interpretation |
| --- | --- | --- |
| Shipment | Imported/unfulfilled, DRAFT, QUOTED, BOOKING, BOOKED and tracked terminal/exception states | A quote/import is not a purchase; BOOKING can retain submitted uncertain credit |
| Wallet reservation | Reserved/native pre-submission, SUBMITTED, CAPTURED, released/failure outcomes | Use exact schema/service transition values; a hold and a completed debit are different |
| Card basket | CREATING, AWAITING_PAYMENT, BOOKING, COMPLETED, REVIEW_REQUIRED | A returned checkout URL is not paid; partial results can leave unused wallet credit |
| Conversation receipt | PROCESSING, COMPLETED, REVIEW_REQUIRED | Replay only a completed saved response; interruption must not repeat effects |
| Return receipt | PROCESSING, BOOKED, PAYMENT_REQUIRED, REVIEW_REQUIRED | Unique full-parcel return per original shipment; status observation may recover completed card booking/QR, never repurchase |
| WhatsApp registration | PENDING_PERSONA, PENDING_COMPANY, PENDING_PROFILE, PENDING_EMAIL, SENDING_EMAIL, PENDING_OTP, PROVISIONING, VERIFIED, LOCKED, EXPIRED, CANCELLED, RECONCILIATION_REQUIRED | Separate collection, delivery, proof, provisioning and uncertainty; persona changes required migration 040 |
| Web registration | SENDING_EMAIL, PENDING_OTP, PROVISIONING, VERIFIED, RECONCILIATION_REQUIRED | Private receipt and Auth proof precede workspace activation |
| Claims | Local intake, queued/submitted/provider review and settlement-specific states | CLAIM_INGESTED is not insurer acceptance or settlement; source DDL/provider mappings remain authoritative |
| Store return sync | Return lifecycle plus REQUESTED/APPROVED/IN_TRANSIT/RECEIVED/review/resolved state | Native reverse-delivery reference and tenant/store identity remain required |

State labels in this overview are not a replacement for exact CHECK constraints and service methods. A future enum must be introduced in both schema and transition logic, not invented in a chatbot response.

## Recent migration lineage

| Migration | Added/changed responsibility |
| --- | --- |
| 030 | Exact selected-offer card baskets |
| 031 | Private encrypted workspace store connections |
| 032 | Dispatch commit events and invoice audit support |
| 033 | XCover/XClaim cases, evidence/submission/settlement support |
| 034 | Support alert controls |
| 035 | Multi-package/goods allocation, separate return lifecycle/parent, credential/submitted snapshot protections |
| 036 | Tenant address/contact/product catalogs |
| 037 | Attributable admin assistance sessions and append-only events |
| 038 | Private ordered conversational receipts/quote context |
| 039 | Private WhatsApp registration state and encrypted reply receipts |
| 040 | BUSINESS/INDIVIDUAL personas, individual global policy/audit, web verification receipts and signup state extension |
| 041 | Explicit cost-sensitive seller strategy and server-owned persona/classification guard |
| 042 | Private full-parcel reverse-logistics command receipts and parent/replay fencing |

Earlier checked-in migrations 006–029 add metadata, admin/configuration, sandbox controls, stores/CRM, tracking/support, reports, identity, carriers, native lifecycle and booking references. The generated migration catalog lists all filenames/source hashes; migration numbering must continue after 042 rather than reuse the historical prompt’s proposed 027/028 numbers.

## Access, audit and retention

Private tables revoke ordinary browser roles; trusted backend access still requires explicit tenant predicates. Assistance and individual pricing events are append-only under their declared triggers. Wallet ledger and financial snapshots follow the existing financial invariants. Credential/encrypted receipt fields require key-version management; never export decrypted secrets into documentation or logs.

Retention must cover structured conversation drafts/quote choices, deliberately submitted claim notes/evidence, encrypted onboarding receipts, expired sessions, uploaded invoice data and support delivery/audit records. Runtime model caching is not a substitute for a retention policy. Backup/restore, key retention, data deletion and legal retention are deployment policies that must be defined by the operator; no automatic cleanup should delete unresolved financial evidence.
