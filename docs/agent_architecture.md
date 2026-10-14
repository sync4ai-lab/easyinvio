# EasyInvio bounded logistics assistance

The supervisor coordinates narrow workers around existing services. It is an application state machine, not a model deciding who may spend money. Agent orchestration and optional rate badges require no additional migration, RLS-context change or FinanceEngine modification. The separate Settings catalogs use migration 036. Standard workflows remain available with AI disabled.

## Capabilities and boundaries

| Capability | Implementation | Authority |
|---|---|---|
| Message preparation | IngestionWorkerAgent uses the existing parser first; otherwise one forced, read-only Agents SDK tool call extracts typed facts | A UI message cannot authorize a purchase. Missing addresses, dimensions and goods require review |
| WhatsApp quotes | Verified Twilio ingress resolves the registered sender before optional parsing outside database locks | Existing saved routes supply real addresses and measurements; the current receipt and quote-choice flow stays authoritative |
| CSV imports | Known headers normalize without AI. Unknown headers use a bounded tool call containing column names only | Row values are unchanged. Existing CSV validators, durable imports, quote flow and manual booking approval remain authoritative |
| Customs preparation | Typed goods preserve quantities, weights, values, origin and allocation; descriptions are deduplicated for suggestions | The existing checkout tariff search additionally ranks fresh official UK tariff candidates when AI is enabled, keeping their source links and requiring review. The separate example-suggestion endpoint uses eight examples and is not a certified tariff. Codes and national extensions require review; customs approval is never granted by AI |
| Quote execution | Supervisor calls the existing durable rates endpoint with a complete RatingRequest | Current permissions, package rules, pricing and stored quote snapshots apply |
| Booking | Existing authenticated confirm-booking route passes a chosen opaque offer to Supervisor, then PartnerLifecycleService | Existing FinanceEngine locks, reservation/capture/release, uncertain-purchase reconciliation and PDF proxies are unchanged. No model has this tool |
| Invoice audits | InvoiceSurchargeAuditorAgent delegates existing exact Decimal comparisons | Current tenant-scoped snapshots, confidence definition, idempotency and billing_disputes writes stay authoritative. Zero model tokens |
| Tracking exceptions | ProactiveClaimsSupportAgent delegates authenticated provider ingestion and durable ticket/outbox staging | Current signature checks, event deduplication, administrator controls, verified recipient and notification consent remain mandatory. Zero model tokens |
| Help | Published local guides are split at section headings into versioned, bounded chunks with direct section citations. Optional 256-dimensional embeddings rank excerpts; structured answers must cite retrieved IDs | Authenticated workspace requests only. No access to customer records, purchases or messages. Unavailable AI falls back to compact related-guide cards with an explicit availability message |

## API surface

- `POST /api/v1/agents/interpret`: `{ "text": "Quote 4.5kg from GBR to USA" }`. Returns extracted facts, NEEDS_INPUT and `booking_authorized: false`.
- `POST /api/v1/agents/quote`: the existing complete RatingRequest schema. Returns the quote and supervisor transitions. It never books.
- `POST /api/v1/agents/customs/suggest`: `{ "description": "cotton knitted t-shirt" }`. Returns a review-required suggestion.
- `POST /api/v1/agents/customs/information`: `{ "items": [...] }`, using the existing Goods schema, up to 100 lines. Preserves goods facts and returns suggestions without approving them.
- `POST /api/v1/help/search-agent`: `{ "query": "When is my wallet charged?" }`. Returns answer, source links, retrieval mode, document version and generation usage.
- `GET /api/v1/admin/agents/metrics`: existing platform-owner authentication; aggregate current-process model/embedding usage and configuration status. No prompts or secrets.

The existing rates, official tariff search, CSV, invoice, tracking and confirm-booking paths are connected directly. Provider webhooks and ordinary UI rates retain their current deterministic validation. Help searches on each keystroke remain local; the explicit assistant button calls the server. Anonymous visitors can still read every public guide.

## Activation

1. Install the pinned-range dependencies in `requirements.txt` using the project virtual environment.
2. Set `OPENAI_API_KEY` privately and `LOGISTICS_AGENTS_ENABLED=true`. The default model is the requested `gpt-4o-mini`; embeddings use `text-embedding-3-small`. Never put credentials in Git.
3. Restart the backend. No SQL migration is needed.
4. Test messages, mapped CSV headers, reviewed customs examples and Help Centre answers in a non-production workspace. Complete accuracy evaluations against your real use cases before broader rollout.
5. Inspect the protected metrics endpoint and your provider billing dashboard. Set a provider budget appropriate to your account. To disable AI, set the flag false and restart; standard shipping tools continue.

## Cost, privacy and resilience

Each model run is limited to one turn, 600 output tokens by default, no model retries, a six-second timeout and four concurrent slots. WhatsApp parsing has a tighter three-second budget. Per-tenant, per-process sliding limits conservatively reserve input bytes plus schema overhead and output allowance. These are abuse controls, not guaranteed billing caps or shared limits across multiple server processes.

Identical private requests cache in bounded memory for five minutes, scoped to tenant and model; generated help answers cache for two minutes with document-version invalidation. Concurrent identical first requests may still incur separate calls. Published-document vectors alone cache under `output/agents`; queries and customer rows are never written there. The public index builds lazily once per process/document version and can be shared through that cache directory. Runtime metrics include embedding and generation usage; per-answer `usage` reports generation only, not shared index construction. Cache hits report zero new generation tokens.

SDK tracing is disabled, Responses storage is disabled and application usage logs contain worker names and token counts rather than prompt content. CSV assistance sends only unfamiliar headers and remaining allowable targets. Customs assistance sends descriptions and example dictionary entries. Help removes obvious emails, international phone numbers and UUIDs before processing, but this is not a comprehensive personal-data scrubber: users must avoid entering private details. Sending model inputs is still subject to your OpenAI account's data-handling settings.

Model failure cannot debit a wallet. A failed model call offers standard-form guidance; help falls back to compact cards linking to original documentation. If vector retrieval is unavailable, generation can still use source-backed keyword retrieval. Transient generation failures are not cached over subsequent recovery. Consequential service failures preserve existing reservation release or reconciliation behavior rather than letting an agent retry purchases. Durable tickets and outbox jobs remain in the existing database pipeline, not a new in-memory message queue.

## What this does not claim

This layer does not create an authoritative customs catalogue, enable missing carrier contracts, repair unavailable provider credentials, create insurance coverage, schedule pickups, automate merchant consent or certify model accuracy. It does not implement autonomous claim approval or infer missing shipment measurements. It cannot guarantee that every supported-looking package produces a carrier rate. Those are operational capabilities, not problems that an LLM can safely invent around.

The design reduces avoidable token use by reserving AI for ambiguous interpretation and documentation answers. Its value should be measured through successful booking rate, time to prepare a shipment, grounded-answer accuracy, support resolution time and tokens per completed workflow. Claims of being the world's first or best logistics platform require external evidence.

## References

- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk)
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Embeddings](https://developers.openai.com/api/docs/guides/embeddings)


## Top-three rate advice and reviewed catalogs

Pricing still uses the existing database margin rules. Carrier/service/currency consolidation chooses the largest absolute contribution (customer price minus returned wholesale total), with deterministic ties, then retains the three lowest customer prices. This is not a claim of net accounting profit after overhead, tax and other platform expenses. UI rate requests optionally send only those offers' customer prices, estimates and measured local history to MarginOptimizerAgent. No supplier IDs, credentials or wholesale costs go to that model.

The advice step has an outer 1.5-second timeout. It may attach one evidence-checked, server-formatted badge, but cannot reorder, reprice or purchase any offer. Missing history cannot produce a reliability claim. A timeout or invalid recommendation returns the unchanged offers without a badge. Internal failures are written asynchronously to existing automation_failures and support_tickets, grouped by tenant/error/hour to prevent repeated optional timeouts flooding the queue. Writes are bounded and logged if storage is unavailable; no system can guarantee a database trace during a database outage. Completed-response usage is measured; cancelled requests may still incur provider charges not represented by a completed SDK usage response.

Migration 036 prepares private address/contact/product catalogs; it does not alter finance, shipment or RLS contexts. Saved SKU facts become ordinary validated quote snapshots. The authenticated customs suggestion endpoint can accept an optional sku and reuse a matching, explicitly reviewed tenant product without a model call. A different description cannot silently inherit that reviewed classification. Every shipment declaration still requires human approval.
