# EasyInvio bounded logistics assistance

The supervisor coordinates narrow workers around existing services. It is an application state machine, not a model deciding who may spend money. No database migration, RLS change or FinanceEngine modification is required. Standard workflows remain available with AI disabled.

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
| Help | Published local guides are versioned into 61 bounded chunks at this revision. Optional 256-dimensional embeddings rank excerpts; structured answers must cite retrieved IDs | Authenticated workspace requests only. No access to customer records, purchases or messages. Unavailable AI falls back to document excerpts |

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

Model failure cannot debit a wallet. A failed model call offers standard-form guidance; help falls back to original documentation. Consequential service failures preserve existing reservation release or reconciliation behavior rather than letting an agent retry purchases. Durable tickets and outbox jobs remain in the existing database pipeline, not a new in-memory message queue.

## What this does not claim

This layer does not create an authoritative customs catalogue, enable missing carrier contracts, repair unavailable provider credentials, create insurance coverage, schedule pickups, automate merchant consent or certify model accuracy. It does not implement autonomous claim approval or infer missing shipment measurements. It cannot guarantee that every supported-looking package produces a carrier rate. Those are operational capabilities, not problems that an LLM can safely invent around.

The design reduces avoidable token use by reserving AI for ambiguous interpretation and documentation answers. Its value should be measured through successful booking rate, time to prepare a shipment, grounded-answer accuracy, support resolution time and tokens per completed workflow. Claims of being the world's first or best logistics platform require external evidence.

## References

- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk)
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Embeddings](https://developers.openai.com/api/docs/guides/embeddings)
