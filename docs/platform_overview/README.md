# EasyInvio application manual

This is the maintained architecture and onboarding reference for EasyInvio.com. It describes the implementation in this repository, including business and individual workspaces, conversational onboarding, carrier selection, payments, protection, claims and headless returns through migration 042. Open [overview.html](overview.html) for a searchable offline edition with diagrams and API tables. Read [llm_handoff.md](llm_handoff.md) before changing code with an LLM.

The source is `docs/platform_overview`. The generated distribution is `output/EasyInvio-Architecture`; `output/EasyInvio-Architecture.zip` contains the same manual. Changes belong in the source chapters and generator, followed by regeneration. Do not edit only the distribution.

## Reading order

1. [Functional architecture](functional_architecture.md): product scope, personas, features and complete customer journeys.
2. [Technical architecture](technical_architecture.md): components, startup, deployment boundaries, concurrency and source ownership.
3. [Agent reference](agent_reference.md): each actual worker, deterministic delegate, model contract and fallback.
4. [Security and finance](security_and_finance.md): identity, tenancy, Decimal arithmetic, reservations, payments and audit requirements.
5. [Integrations](integrations.md): carrier, storefront, messaging, email, customs, CRM and insurer contracts.
6. [Data model](data_model.md): tables, migrations, ownership and recovery states; [generated data dictionary](data_dictionary.md) for exact repository DDL.
7. [API reference](api_reference.md): every generated HTTP operation, dependency guard, request schema, response contract and implementation location.
8. [Operations runbook](operations_runbook.md): local startup, configuration, onboarding, troubleshooting and reconciliation.
9. [Testing and release](testing_and_release.md): test layers, UAT interpretation, external acceptance and release gates.
10. [LLM handoff](llm_handoff.md): instructions, reading paths and invariants for safe future changes.

## Machine readable references

- `openapi.json`: current application OpenAPI export, created without running lifespan or connecting to providers.
- `api_inventory.json`: operation-to-source/dependency mapping; application role checks can also reside in called helpers.
- `source_map.json`: Python modules, classes, functions and repository SQL references.
- `data_inventory.json`: migration objects and exact CREATE TABLE definitions available in this checkout.
- `configuration.json`: source-declared settings and environment-variable names, never private `.env` values.
- `versions.json`: installed local versions, declared ranges and lockfile entries with capture date.
- `agent_contracts.json`: source-declared model calls, tool/output contracts and Pydantic agent schemas.
- `manifest.json`: source revision, generated-file hashes and inventory counts.

## Interpretation rules

Implemented code, enabled configuration, a reachable provider account and live acceptance are different states. A feature in this manual may require credentials, contracts, feature flags, migrations, a permitted role or manual review. This manual is not a production release approval or a statement that any particular tenant has those prerequisites.

The core application is a modular monolith, not a deployed fleet of independent AI microservices. AI suggestions do not authorize a purchase, change a stored monetary price or establish customs/insurance approval. Personal accounts use the same financial and shipment schema as business accounts.

The initial core schema predates the checked-in migration sequence, which starts at 006. A new database needs the authorized baseline schema as well as the later migrations. Do not infer that applying 006–042 alone creates a complete fresh installation.

## Rebuild and verify

From the project root, using the project virtual environment:

```powershell
.\.venv\Scripts\python.exe docs/platform_overview/generate.py --render --export
.\.venv\Scripts\python.exe docs/platform_overview/generate.py --check
.\.venv\Scripts\python.exe docs/platform_overview/verify_manual.py
```

Generation reads application source, safe package metadata and source-declared schemas. It does not start the server, read customer exports, apply SQL, send messages, buy labels, charge cards or publish a deployment. Source links reference the recorded application commit and require repository access. The manual and diagrams work offline; source code itself is not bundled.
