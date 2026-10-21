# LLM and new engineer handoff

Start with AGENTS.md and the current user request, then this manual’s README, functional architecture, security/finance invariants and the source modules owning the requested behavior. The manual describes the recorded implementation; it does not override repository instructions, newer source, deployed provider contracts or explicit user authorization.

## First hour reading path

1. Confirm the working directory, branch, remote, staged state and unrelated local edits. Never print `.env`, credentials, tokens, exports or raw customer/provider logs.
2. Read the functional and technical chapters to distinguish personas, domain services, optional agents and external integrations.
3. Look up the exact HTTP operation in api_reference.md/api_inventory.json and its schema in openapi.json. Follow the source location and called permission helpers; dependency summaries are not complete role policies.
4. Use source_map.json to find owning classes/functions and data_dictionary.md/data_inventory.json to find checked-in migrations. Obtain the authorized baseline for actual database setup.
5. Read the relevant tests and feature guide before changing a contract. Preserve established error, idempotency, projection and financial behavior.
6. Check operations_runbook.md before starting workers, invoking diagnostics or interpreting payment/webhook failures.

## Non-negotiable implementation rules

- Identity comes from validated session/phone/provider context, never an editable user/tenant/role string or a model proposal. Explicitly tenant-scope every privileged SQL path.
- BUSINESS/INDIVIDUAL and seller classification are server-owned strategy fields. They do not create new authorization roles or a parallel wallet schema.
- Use Decimal with strict validated input, explicit scale/rounding and supported currency. Never replace exact money with float or silently relabel a currency.
- Reuse RatingService, immutable selected offers, PartnerLifecycleService, FinanceEngine and native payment/claim methods. Do not implement a second wallet balance-update path.
- Mark submissions/receipts before external effects and preserve unknown outcomes. Timeout is not rejection; do not release funds or retry a provider buy blindly.
- AI parses/ranks/prepares within bounded source-backed candidates. It cannot grant permission, change a displayed price, invent an offer/rate/reference/address, approve customs or establish coverage/settlement.
- Use only documented provider-specific flags and real returned assets. `generate_qr_code=true` is not a universal carrier contract; printable fallback is a valid result.
- Store returns, ordinary fulfillment, merchant refund, restocking and insurer claims are distinct lifecycles. Do not collapse their statuses or update the forward order as fulfilled by a return.
- Recover through existing GET/status/outbox reconciliation and audited operator workflows. A processing receipt is not disposable bookkeeping.
- Preserve user edits and stage only task changes. Project instructions authorize routine relevant checks, coherent commits and pushes; they do not authorize deployment, live SQL, labels, charges or outreach.

## Common change paths

| Request | Read first |
| --- | --- |
| New conversational intent | agents/models.py, conversational_gateway.py, conversation_context.py, ConversationStore and the native service/role guard |
| Agent prompt/tool change | agent_reference.md, agents/workers.py or margin_optimizer.py, runtime.py, exact output schema and grounding/fallback tests |
| Carrier/rate/QR problem | aggregator_registry.py, sendcloud_adapter.py or main strategies, automation_three_partners.py, carrier_access.py, label_availability.py, return_documents.py |
| Payment/booking mismatch | FinanceEngine, partner lifecycle, card_checkout.py, payment_gateway.py, immutable snapshot and reservation tests |
| Signup/session/email issue | identity.py, web_registration.py, whatsapp_onboarding.py, actual Auth templates, source defaults and callbacks; never inspect secrets by printing them |
| Product/address/customs UI | tenant_catalogs.py, customer_checkout.py, final SPA wrappers and tests; tariff candidates and review consent remain explicit |
| Store/marketplace return | ecommerce_connectors.py, store_connections.py, ecommerce_inbound.py, return_ingress.py, reverse_logistics.py and store_returns.py |
| Support/claims/settlement | tracking_and_support.py, support_workflow.py, support_delivery.py, shipment_protection.py, xcover_claims.py and evidence/ledger tests |
| Admin persona/markup/report | admin_portal.py, admin_management.py, workspace_personas.py, client_assistance.py and migrations 037/040/041 |

## Documentation maintenance

The source manual is `docs/platform_overview`. Edit its curated Markdown chapters/diagram definitions, then run the generator to refresh overview HTML, endpoint/schema inventories, source maps, data/configuration catalogs and diagrams. Use `--render --export` to refresh PNGs and `output/EasyInvio-Architecture.zip`. Check mode verifies coverage and distribution content; it does not substitute for application tests.

Record source revision separately from the documentation commit. Installed local package versions are not deployed versions, a feature flag default is not active configuration, and an old UAT number is not a new test run. Preserve historical UAT reports instead of silently revising them into a sign-off.

When a change introduces an API, table, source module, agent contract or integration capability, update the owning chapter and regenerate. When the code’s behavior is uncertain, inspect its source/test path and describe the limitation rather than filling the gap with a plausible architecture. Do not add the private architecture manual to public help retrieval without a separate deliberate product decision.

## Safe verification defaults

Use `rg`/`rg --files` on intended source directories and exclude output/archives. Scope regression tests to `tests`; repository-root discovery can execute diagnostics from temporary folders. Use isolated dependency/service fixtures with cleanup; manage FastAPI lifespan deliberately when required. Never start real workers against a configured customer database just to make an HTTP test pass.

For reversible documentation edits, validate content, links/rendering and diff cleanliness. For behavioral changes, run the owning meaningful tests and required checks, then broaden only for a specific unresolved concern. Follow the project’s automatic Git synchronization policy and report the resulting branch/commit/push accurately.

## Manifest/media change invariants

Read manifest_service.py, logistics_media.py, migration 044, whatsapp_queue.py and the carrier_manifests_and_media operating guide before changing EOD or image delivery. Preserve manifest tenant/account membership, cancellation lock coordination, pre-submission fencing, immutable snapshots and GET-only native recovery. MANIFESTED must remain compatible with label access, tracking, protection, reports and booking replay. Internal handover references are not carrier tracking/pickup outcomes.

Do not create a generic Sendcloud manifest POST without its verified public contract. Do not put private QR assets in a public bucket or allow chat input to select arbitrary outbound URLs. Definite failed media and uncertain REST outcomes have different recovery authority; neither authorizes replaying a financial action.

## Tracking 2.0 ownership

Read tracking_workspace.py, tracking_refresh.py, migration 045 and docs/tracking_2_implementation.md before changing tracking. Preserve fixed customer-link membership, public allowlists, tenant/admin authorization, immutable scan facts, read-only provider reconciliation, account cooldowns and default-disabled polling. A stale feed is not a confirmed delay, a return receipt is not a purchase refund, and a provider capability declaration is not activation or contract certification.
