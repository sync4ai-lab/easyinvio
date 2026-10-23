# Source and test catalog

Repository module/class/function locations are listed below. Source links reference the recorded revision. Diagnostic/apply/seed scripts can have live effects; review before execution. Source fingerprints in source_map.json normalize CRLF to LF for portable checkouts; artifact hashes remain exact bytes.

## main.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/main.py#L1)

EasyInvio.com: combined rating, financial controls and WhatsApp service.

Python 3.12 or newer. Install dependencies:
    python -m pip install fastapi 'uvicorn[standard]' httpx pydantic         pydantic-settings 'PyJWT[crypto]' cryptography asyncpg 'stripe>=13,<15'         'twilio>=9,<10' 'pycountry>=24.6,<25'

Run local checks without credentials:
    python main.py --self-test

Start after configuring environment variables and applying Steps 2, 4 and 5 SQL:
    python main.py

Required environment variables (or entries in a local .env file):
    SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SERVICE_ROLE_KEY
    DATABASE_URL, CREDENTIAL_KEYS, REGIONAL_ALLOWED_ORIGINS
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
    CHECKOUT_SUCCESS_URL, CHECKOUT_CANCEL_URL
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER
    TWILIO_WEBHOOK_URL, BOOKING_PAGE_URL, QUOTE_LINK_SECRET

CREDENTIAL_KEYS is a JSON object mapping key IDs to Fernet keys.
REGIONAL_ALLOWED_ORIGINS is a JSON array of approved HTTPS API origins.
Optional: JWT_ALGORITHM=ES256, STRIPE_LIVEMODE=false,
PROVIDER_ENVIRONMENT=TEST, DATABASE_CA_FILE, PORT=8000.

This module does not purchase carrier labels or implement a booking frontend.
wallet_risk_interceptor, mark_submitted and finish_booking are the hooks for
the subsequent label-purchase component. RegionalStrategy defines its actual
wire contract; use an adapter matching the selected regional provider's API.

- `Settings` (line 126): `whatsapp_e164`, `sandbox_modes`, `supabase_origin`, `regional_origins`, `checkout_return_url`, `fixed_https_url`, `encryption_keys`, `link_secret`.
- `StrictModel` (line 281): .
- `Dimensions` (line 295): `validate_input`.
- `Address` (line 306): `trim`, `country`.
- `RatingRequest` (line 339): `from_conversation`, `letter_dimensions`, `weights`, `matching_arrays`.
- `ProviderFees` (line 404): `decimal_values`.
- `WholesaleRate` (line 416): `cost_input`, `reconcile_fees`, `codes`.
- `ClientRate` (line 451): .
- `ProviderIssue` (line 482): .
- `RatingResponse` (line 490): .
- `MarginRule` (line 501): `flat_type`, `codes`, `bounds`.
- `TopupRequest` (line 557): `amount_input`.
- `TopupResponse` (line 567): .
- `TenantContext` (line 574): .
- `CarrierAccount` (line 583): .
- `PriceResult` (line 595): .
- `BookingPermit` (line 603): .
- `ParsedQuote` (line 613): .
- `RuleRepository` (line 676): `load`.
- `MemoryRuleRepository` (line 681): `__init__`, `load`.
- `SupabaseRepository` (line 694): `__init__`, `select`, `load`, `accounts`.
- `MarginEvaluator` (line 810): `matches`, `specificity`, `evaluate`.
- `ProviderFailure` (line 882): `__init__`.
- `RateStrategy` (line 888): `__init__`, `post`, `rates`.
- `EasyPostStrategy` (line 928): `address`, `rates`.
- `RegionalStrategy` (line 1030): `rates`.
- `SendcloudStrategy` (line 1069): `__init__`, `rates`.
- `RatingService` (line 1087): `__init__`, `run_provider`, `quote`.
- `FinanceEngine` (line 1289): `__init__`, `lock_tenant`, `lock_wallet`, `append_ledger`, `reserve`, `locked_reservation`, `verified_test_booking`, `mark_submitted`, `finish_booking`, `check_payment_environment`, `authorize_label_preview`, `create_checkout`, `credit_session`.
- `WhatsAppService` (line 1767): `__init__`, `resolve_sender`, `sign_choice`, `process`.

Top-level functions: `decimal_input` (line 285), `parse_json` (line 620), `streamed_json` (line 630), `money` (line 639), `to_minor_units` (line 645), `from_minor_units` (line 656), `encrypt_carrier_credentials` (line 664), `borrow_finance_connection` (line 1281), `country_to_alpha2` (line 1721), `parse_quote` (line 1729), `twiml` (line 1743), `xml_response` (line 1749), `decode_json` (line 1753), `rls_context` (line 1757), `deterministic_lifespan` (line 1910), `lifespan` (line 2080), `branded_carrier_transport` (line 2113), `preview_guard` (line 2137), `validate_tenant_query` (line 2151), `authenticate` (line 2169), `wallet_risk_interceptor` (line 2245), `health` (line 2263), `frontend` (line 2269), `public_tracking_page` (line 2274), `tracking_asset` (line 2286), `public_config` (line 2292), `get_rates` (line 2302), `carrier_performance` (line 2362), `create_wallet_topup` (line 2380), `limited_body` (line 2391), `stripe_webhook` (line 2401), `inbound_whatsapp` (line 2447), `resolve_quote_choice` (line 2453), `verify_local_logic` (line 2531).

Public SQL object references: `carrier_manifests`, `js`, `margin_rules`, `partner_unbound_quotes`, `payment_carts`, `return_customer_deliveries`, `shipments`, `tenants`, `users`, `wallet_ledger`, `wallet_reservations`, `wallet_topups`, `wallets`, `whatsapp_bindings`, `whatsapp_quote_choices`, `whatsapp_receipts`, `whatsapp_reply_outbox`, `whatsapp_routes`.

## backend/__init__.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/__init__.py#L1)

EasyInvio logistics extensions.

## backend/adapters/__init__.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/adapters/__init__.py#L1)

Direct carrier extension points. No unverified carrier endpoint is registered.

- `DirectRegistration` (line 7): .

Top-level functions: `direct_registration` (line 18).

## backend/adapters/direct_contract.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/adapters/direct_contract.py#L1)

Typed internal contract for certified direct transports, not a carrier wire schema.

- `DirectModel` (line 13): .
- `PAFDeliveryAddress` (line 17): .
- `DirectParcel` (line 26): `from_rating`.
- `DirectLabel` (line 49): `document_format`.
- `DirectManifest` (line 64): `pdf_header`.
- `DirectCarrierContract` (line 76): `quote`, `purchase_label`, `create_manifest`.
## backend/adapters/evri_adapter.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/adapters/evri_adapter.py#L1)

Evri direct provision; no guessed enterprise endpoint, signing or QR generation.

- `EvriDropoffBarcode` (line 12): .
- `EvriStrategy` (line 17): `postable_height_candidate`, `extract_dropoff_barcode`.
## backend/adapters/royal_mail_adapter.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/adapters/royal_mail_adapter.py#L1)

Royal Mail direct provision. An issued, certified API contract is mandatory.

- `RoyalMailStrategy` (line 14): `__init__`, `verified_contract`, `rates`, `purchase_label`, `create_manifest`.
## backend/admin_management.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/admin_management.py#L1)

Owner-only, audited management of existing tenant-scoped configuration.

- `CarrierCreate` (line 91): .
- `CarrierUpdate` (line 105): `sealed_fields`.
- `SellerClassificationUpdate` (line 233): .

Top-level functions: `public_record` (line 18), `audit` (line 27), `tenants` (line 34), `margins` (line 44), `update_margin` (line 55), `retire_margin` (line 81), `validate_endpoint` (line 116), `carriers` (line 128), `add_carrier` (line 139), `change_carrier` (line 184), `remove_carrier` (line 212), `transactions` (line 224), `update_seller_classification` (line 238).

Public SQL object references: `admin_management_events`, `carrier_accounts`, `margin_rules`, `tenants`, `wallet_ledger`.

## backend/admin_portal.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/admin_portal.py#L1)

Platform-owner administration and database-backed tenant pricing.

Uses the application's trusted asyncpg pool. Platform permissions come from
server configuration, never from customer roles or client-supplied metadata.
Call get_client_calibrated_rate with await; PostgreSQL access is asynchronous.

- `InputModel` (line 39): .
- `CompanyProfile` (line 50): `trim_text`, `normalize_country`.
- `TenantCreate` (line 74): `persona_profile`.
- `TenantCreated` (line 93): .
- `MarginCreate` (line 107): `exact_decimals`, `integer_priority`, `boolean_active`, `normalize_codes`, `normalize_countries`, `valid_bounds`.
- `MarginCreated` (line 181): .
- `PlatformOwner` (line 197): .
- `AdminService` (line 244): `__init__`, `fingerprint`, `replay`, `audit`, `create_tenant`, `create_margin`.
- `PricingScope` (line 361): .
- `IndividualPricingUpdate` (line 577): `fixed_point`.

Top-level functions: `printable` (line 43), `authenticate_platform_owner` (line 204), `decode_json` (line 240), `configure_pricing_pool` (line 379), `borrowed_pricing_connection` (line 386), `pricing_read_connection` (line 396), `calibrated_pricing_scope` (line 407), `country_aliases` (line 421), `validate_wholesale_cost` (line 426), `calculate_calibrated_price` (line 431), `get_client_calibrated_rate` (line 465), `service_for` (line 543), `database_error` (line 550), `create_tenant` (line 562), `create_margin` (line 570), `read_individual_pricing` (line 589), `update_individual_pricing` (line 596).

Public SQL object references: `admin_configuration_events`, `carrier_accounts`, `individual_pricing_events`, `individual_pricing_settings`, `margin_rules`, `tenants`, `users`, `wallets`.

## backend/advanced_logistics.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/advanced_logistics.py#L1)

Decimal dimensional pricing, declaration metadata and bounded CSV order imports.

- `ParcelInput` (line 33): `decimals`.
- `DeclarationParty` (line 45): `country`, `nonblank`.
- `CustomsItem` (line 67): `integer_quantity`, `decimals`, `country`.
- `DeclarationInput` (line 93): `decimals`, `validate_weight`.

Top-level functions: `calculate_billable_weight` (line 21), `generate_commercial_invoice` (line 121), `preview_rates` (line 144), `build_router` (line 171).

Public SQL object references: `partner_order_jobs`, `shipments`, `tenants`, `wallet_reservations`, `wallets`.

## backend/agents/__init__.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/__init__.py#L1)

Bounded AI assistance around EasyInvio's existing authorised services.

## backend/agents/config.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/config.py#L1)

- `AgentSettings` (line 5): `available`.
## backend/agents/conversation_context.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/conversation_context.py#L1)

Bounded typed conversation drafts and deterministic location extraction.

- `ConversationDraft` (line 26): `active`.

Top-level functions: `explicit_country` (line 14), `location` (line 45), `explicit_quote` (line 85), `merge_quote` (line 106), `collect_reply` (line 124).

## backend/agents/conversational_gateway.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/conversational_gateway.py#L1)

One authenticated action dispatcher for signed WhatsApp and session-bound web chat.

Models extract proposals only. Money, carrier purchases and claim intake remain
owned by deterministic services. Durable receipts fence uncertain action retries.

- `ConversationMessage` (line 35): .
- `ConversationStore` (line 70): `__init__`, `receipt`, `finish`, `latest_quote`, `latest_turn`.
- `ConversationalActionGateway` (line 149): `__init__`, `reply`, `interpret`, `process`, `public`, `pending_reply`, `draft_prompt`, `execute`, `quote`, `collect_uk_premise`, `trigger_return`, `manifest`, `shipment`, `claim`, `claim_panel_url`.

Top-level functions: `decoded` (line 43), `message_xml` (line 47), `signed_whatsapp_message` (line 659), `build_router` (line 669).

Public SQL object references: `admin_client_assistance_sessions`, `carrier_manifests`, `conversational_messages`, `insurance_claim_cases`, `partner_unbound_quotes`, `shipments`, `support_tickets`, `tenants`, `tracking_events`, `users`, `wallets`, `whatsapp_bindings`, `whatsapp_quote_choices`, `whatsapp_routes`.

## backend/agents/margin_optimizer.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/margin_optimizer.py#L1)

Optional strategic advice over immutable, already-priced top-ten offers.

- `StrategicChoice` (line 37): .
- `MarginOptimizerAgent` (line 42): `__init__`, `recommend`, `queue_failure`, `persist_failure`, `close`.

Top-level functions: `budget_candidate` (line 17).

Public SQL object references: `automation_failures`, `support_tickets`, `tenants`.

## backend/agents/models.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/models.py#L1)

- `StrictOutput` (line 9): .
- `QuoteIntent` (line 13): .
- `ConversationalIntent` (line 21): `exact_amount`.
- `ColumnMapping` (line 49): .
- `HeaderMapping` (line 54): .
- `HSSelection` (line 59): .
- `CitedAnswer` (line 65): .
- `State` (line 71): .
- `Workflow` (line 81): `move`.
- `MessageRequest` (line 100): .
- `HelpQuestion` (line 104): .
## backend/agents/rag_support.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/rag_support.py#L1)

Versioned local documentation retrieval; customer queries are never written to disk.

- `GuideSections` (line 19): `__init__`, `flush`, `handle_starttag`, `handle_endtag`, `handle_data`.
- `Chunk` (line 55): .
- `HelpRetriever` (line 75): `__init__`, `corpus`, `lexical_scores`, `index`, `answer`.

Top-level functions: `words` (line 63), `redacted_question` (line 68).

## backend/agents/routes.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/routes.py#L1)

Authenticated AI preparation and documentation; no general-purpose action tools.

- `Description` (line 8): .
- `CustomsItems` (line 13): .

Top-level functions: `build_router` (line 17).

## backend/agents/runtime.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/runtime.py#L1)

No durable customer prompts, no model retries, bounded SDK runs and measured usage.

- `Cache` (line 17): `__init__`, `get`, `put`.
- `ModelResult` (line 40): .
- `AgentRuntime` (line 47): `__init__`, `available`, `key`, `reserve`, `record`, `run`, `embed`, `close`.
## backend/agents/status_guidance.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/status_guidance.py#L1)

Recognize explanatory status questions without authorizing any action.


Top-level functions: `normalized` (line 8), `status_question` (line 12), `needs_status_context` (line 30).

## backend/agents/supervisor.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/supervisor.py#L1)

Bounded orchestration around existing, authoritative logistics services.

- `LogisticsSupervisor` (line 12): `__init__`, `dispatch_permission`, `interpret`, `quote`, `rates`, `confirm`, `whatsapp_quote`.

Top-level functions: `supervisor` (line 119).

## backend/agents/workers.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/agents/workers.py#L1)

Specialists have narrow capabilities; no worker can buy labels or alter a wallet.

- `IngestionWorkerAgent` (line 16): `__init__`, `conversation`, `validate_intent`, `message`, `ground_quote`, `csv_headers`.
- `CustomsHarmonizerAgent` (line 191): `__init__`, `rank_tariff`, `suggest`, `information`.
- `InvoiceSurchargeAuditorAgent` (line 257): `__init__`, `compare`.
- `ProactiveClaimsSupportAgent` (line 269): `__init__`, `receive_tracking`, `stage`.
## backend/aggregator_lifecycle.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/aggregator_lifecycle.py#L1)

Backward-compatible imports for the explicit three-provider engine.

## backend/aggregator_registry.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/aggregator_registry.py#L1)

Explicit aggregator capabilities: shared interface, provider-specific wire contracts.

- `AggregatorCapabilities` (line 5): .

Top-level functions: `identify_aggregator` (line 23), `public_capabilities` (line 26).

## backend/ai_engine.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/ai_engine.py#L1)

Explainable mock ML and tenant-scoped invoice auditing.

Predictions are suggestions, not certified tariff classifications. No external
AI service receives shipment descriptions. Currency and confidence use Decimal.

- `CommodityRule` (line 50): .
- `StrictModel` (line 139): .
- `DescriptionInput` (line 143): .
- `InvoiceLine` (line 147): `decimal_strings`.
- `InvoiceInput` (line 162): `unique_shipments`.

Top-level functions: `strict_decimal` (line 25), `amount` (line 37), `country_code` (line 41), `predict_hs_code` (line 72), `analyze_tracking_history` (line 99), `evaluate_carrier_disruptions` (line 132), `audit_invoice_line` (line 174), `record_invoice_baseline` (line 209), `build_router` (line 236).

Public SQL object references: `shipments`, `tenants`.

## backend/apply_automation_migration.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/apply_automation_migration.py#L1)

Apply the additive freight/support compatibility migration in sandbox.


Top-level functions: `run` (line 9).

## backend/apply_partner_lifecycle.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/apply_partner_lifecycle.py#L1)

Explicit sandbox-only migration runner; contains no credentials or seed data.


Top-level functions: `run` (line 12).

## backend/apply_tracking_migration.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/apply_tracking_migration.py#L1)

Apply only the additive tracking/support migration to configured Supabase.


Top-level functions: `run` (line 9).

## backend/automation_freight_engine.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/automation_freight_engine.py#L1)

Cargo-aware bulk rating, confirmed EasyPost purchase and customs bundles.

Freight tariff factors are contract settings, not a universal NMFC class.
Regional purchasing is enabled only through an explicitly registered adapter.

- `StrictInput` (line 32): .
- `Cargo` (line 36): `strip_letter_dimensions`, `decimals`, `rules`.
- `Goods` (line 95): `decimals`, `origin`.
- `Order` (line 113): `unpack_boxes`, `store_pair`.
- `PurchaseUncertain` (line 259): .
- `PurchaseRejected` (line 260): .
- `EasyPostPurchase` (line 263): `__init__`, `request`, `buy`, `reconcile`, `label`.
- `AutomationService` (line 306): `__init__`, `register_purchase_adapter`, `reconcile`, `fail_ticket`, `process`.

Top-level functions: `calculate_cargo_charge` (line 69), `customs_matrix` (line 184), `customs_scope` (line 224), `generate_customs_declaration` (line 230), `re_safe` (line 559), `processing_remedy` (line 563), `build_router` (line 578).

Public SQL object references: `automation_failures`, `ecommerce_stores`, `partner_shipping_offers`, `shipments`, `support_tickets`, `tenants`, `users`, `wallet_reservations`, `wallets`.

## backend/automation_three_partners.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/automation_three_partners.py#L1)

Native partner lifecycle contracts behind EasyInvio's private account boundary.

Mutating HTTP requests are never retried automatically. A timeout is an unknown
outcome, not a rejected purchase. Return snapshots must contain a newly quoted
return service; a forward price is never reused as a return authorization.

- `NativeProviderSettings` (line 35): `hostnames`, `numeric_statuses`, `secret_length`.
- `NativeOrderSelection` (line 74): .
- `NativeOrderReconciliation` (line 80): .
- `NativePartnerService` (line 234): `__init__`, `decrypt_secret`, `ensure_order`, `sync_one`, `worker`, `fulfillment_cycle`, `receive_tracking`.
- `BaseAggregatorAdapter` (line 743): `__init__`, `authentication`, `request`.
- `EasyPostAdapter` (line 800): `authentication`, `quote`, `sync_order`, `confirm_order_fulfillment`, `retrieve_order`, `normalize`, `normalize_order`, `purchase_label`, `inject_customs`, `retrieve_label`, `void_label`, `void_confirmed`, `generate_return_label`.
- `ShippoAdapter` (line 976): `authentication`, `quote`, `sync_order`, `confirm_order_fulfillment`, `retrieve_order`, `normalize`, `purchase_label`, `retrieve_package_labels`, `retrieve_label`, `inject_customs`, `void_label`, `void_confirmed`, `generate_return_label`.
- `ShippoRateStrategy` (line 1118): `__init__`, `rates`.
- `SendcloudAdapter` (line 1183): `authentication`, `quote`, `purchase_allowed`, `inject_customs`, `payload`, `normalize`, `normalize_single`, `sync_order`, `confirm_order_fulfillment`, `retrieve_order`, `purchase_label`, `normalize_return`, `retrieve_label`, `void_label`, `void_confirmed`, `generate_return_label`.
- `NativeRateStrategy` (line 1426): `__init__`, `rates`.
- `FactoryPurchaseBridge` (line 1443): `__init__`, `snapshot`, `buy`, `reconcile`.
- `BookingRequest` (line 1549): .
- `VoidRequest` (line 1558): .
- `ReturnRequest` (line 1567): .
- `PartnerLifecycleService` (line 1582): `__init__`, `environment`, `ticket`, `public_result`, `bind_direct_quote`, `confirm`, `_prepare_confirm`, `_confirm`, `void`, `poll_and_finalize_sendcloud_label`, `worker`.

Top-level functions: `decode_json` (line 87), `native_timestamp` (line 91), `native_pod` (line 104), `enrich_easypost_event` (line 112), `parse_easypost_tracking` (line 128), `parse_sendcloud_tracking` (line 149), `parse_shippo_tracking` (line 168), `verify_native_signature` (line 190), `wake_exception_delivery` (line 467), `build_native_router` (line 477), `decimal_json` (line 605), `order_total` (line 618), `native_order_key` (line 622), `easypost_parcel` (line 626), `validate_native_cargo` (line 637), `easypost_tax_identifiers` (line 659), `easypost_address` (line 669), `shippo_address` (line 675), `identifier` (line 679), `secure_link` (line 688), `carrier_qr_fields` (line 697), `declaration` (line 713), `return_snapshot` (line 732), `sendcloud_address` (line 1172), `create_adapter` (line 1419), `verify_quote_connection` (line 1435), `authorize` (line 1575), `carrier_document` (line 1994), `prepare_return_quote` (line 2057), `build_router` (line 2115).

Public SQL object references: `carrier_accounts`, `partner_cancellations`, `partner_order_jobs`, `partner_provider_options`, `partner_shipping_offers`, `partner_unbound_quotes`, `platform_carrier_connections`, `platform_carrier_events`, `shipments`, `tenants`, `users`, `wallet_reservations`, `wallets`.

## backend/booking_receipt.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/booking_receipt.py#L1)

Printable booking receipt from confirmed, tenant-owned shipment records.


Top-level functions: `receipt_pdf` (line 11).

## backend/build_rigorous_seed.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/build_rigorous_seed.py#L1)

Generate complete SQL fixture scripts without embedding usable credentials.


Top-level functions: `run` (line 12).

Public SQL object references: `carrier_accounts`, `ecommerce_stores`, `fixture_seed_runs`, `hubspot_sync_jobs`, `margin_rules`, `shipments`, `support_tickets`, `tenants`, `tracking_events`, `users`, `wallet_ledger`, `wallet_reservations`, `wallet_topups`, `wallets`, `whatsapp_bindings`.

## backend/bulk_checkout.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/bulk_checkout.py#L1)

Review persisted rates and explicitly buy selected offers for CSV or store orders.

- `OrderSelection` (line 14): `unique`.
- `SelectedOffer` (line 22): .
- `CheckoutSelection` (line 29): `unique`.

Top-level functions: `order_rows` (line 37), `review_orders` (line 44), `validate_checkout` (line 63), `checkout_orders` (line 100), `build_router` (line 123).

Public SQL object references: `partner_shipping_offers`, `shipments`, `tenants`, `wallet_reservations`, `wallets`.

## backend/card_checkout.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/card_checkout.py#L1)

Card-funded label baskets over the atomic wallet booking ledger.

- `CardCart` (line 14): .

Top-level functions: `permitted` (line 18), `create_cart` (line 21), `complete_cart` (line 69), `_complete_cart` (line 74), `cart_worker` (line 120), `build_router` (line 135).

Public SQL object references: `partner_shipping_offers`, `payment_carts`, `shipments`, `users`, `wallet_topups`.

## backend/carrier_access.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/carrier_access.py#L1)

Historical carrier access is limited to a verified shipment lifecycle.


Top-level functions: `verified_return_parent` (line 6), `return_accounts` (line 40).

Public SQL object references: `shipments`, `tenant_catalog_addresses`.

## backend/carrier_consolidation.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/carrier_consolidation.py#L1)

Private carrier consolidation, tenant-local history and branded public payloads.


Top-level functions: `carrier_identity` (line 14), `service_identity` (line 19), `consolidate_rates` (line 26), `business_days` (line 53), `summarize_history` (line 60), `unknown_history` (line 94), `route_history` (line 101), `public_payload` (line 119).

Public SQL object references: `carrier_accounts`, `shipments`, `tracking_events`.

## backend/check_hubspot.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/check_hubspot.py#L1)

Read-only deployment preflight. Never enables a worker or creates records.

Run from the project root: python -m backend.check_hubspot
Secrets are read through settings and never included in the output.


Top-level functions: `check` (line 13).

## backend/check_setup.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/check_setup.py#L1)

Report invalid environment variable names without exposing their values.

## backend/client_assistance.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/client_assistance.py#L1)

Verified platform operators acting in a tenant, with durable request audit events.

- `AssistanceRoute` (line 20): `get_route_handler`.
- `StartAssistance` (line 56): .
- `ClientAssistanceMiddleware` (line 180): `__init__`, `__call__`.

Top-level functions: `redact_change` (line 39), `append_event` (line 62), `token_fingerprint` (line 70), `resolve_assistance` (line 77), `operator_member_id` (line 100), `clients` (line 112), `start` (line 123), `stop` (line 152), `events` (line 165).

Public SQL object references: `admin_client_assistance_events`, `admin_client_assistance_sessions`, `tenants`, `users`.

## backend/conversational_claims.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/conversational_claims.py#L1)

One-time completion of an authenticated, unsubmitted chat claim draft.


Top-level functions: `complete_conversational_claim` (line 7).

Public SQL object references: `insurance_claim_cases`, `insurance_claim_evidence`, `support_ticket_activity`, `support_tickets`, `users`.

## backend/credential_rotation.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/credential_rotation.py#L1)

Fresh-admin replacement of sealed, tenant-bound credentials; never unlock.

- `CredentialReplacement` (line 13): .

Top-level functions: `require_recent_admin_auth` (line 19), `replace_credentials` (line 33).

Public SQL object references: `carrier_accounts`.

## backend/customer_checkout.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/customer_checkout.py#L1)

Tenant-authorized checkout of private offers and confirmed invoice PDFs.

- `CheckoutCustoms` (line 18): .
- `CheckoutPrepare` (line 30): .
- `TariffQuery` (line 35): .

Top-level functions: `search_tariff` (line 40), `booking_reference` (line 72), `quoted_goods` (line 87), `offer_context` (line 91), `build_router` (line 115).

Public SQL object references: `booking_references`, `easyinvio_booking_reference_sequence`, `partner_unbound_quotes`, `shipments`, `tenants`, `wallet_reservations`.

## backend/dashboard_portal.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/dashboard_portal.py#L1)

Server-verified portal roles, owner analytics and support dashboard actions.

- `Intervention` (line 13): .
- `WorkspaceMember` (line 18): .
- `StoreConfiguration` (line 24): .
- `StoreState` (line 29): .

Top-level functions: `build_router` (line 34).

Public SQL object references: `app_user_profiles`, `automation_failures`, `ecommerce_stores`, `shipments`, `support_message_outbox`, `support_ticket_activity`, `support_tickets`, `tenants`, `users`, `wallet_topups`, `workspace_store_connections`.

## backend/database_tls.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/database_tls.py#L1)

Verified PostgreSQL TLS with explicit legacy-CA compatibility.


Top-level functions: `database_tls_context` (line 5).

## backend/delivery_quality.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/delivery_quality.py#L1)

Tenant-bound tracking readiness; status transport and quality are separate.


Top-level functions: `tracking_readiness` (line 7), `build_router` (line 42).

Public SQL object references: `carrier_accounts`, `partner_provider_options`, `shipments`, `tracking_events`.

## backend/dispatch_pdf.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/dispatch_pdf.py#L1)

Bounded, tenant-authorized print bundles of confirmed carrier PDFs.

Never manufactures a carrier label or renders ZPL as a pretend shipping label.
Only exact operator-approved HTTPS hosts are fetched, without redirects.

- `PrintSettings` (line 25): `hosts`.

Top-level functions: `invoice_pdf` (line 48), `fetch_pdf` (line 99), `merge_pdfs` (line 124), `bundle_shipments` (line 152).

## backend/dispatch_realtime.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/dispatch_realtime.py#L1)

Commit-time Postgres notifications fan out to authenticated tenant sockets.

- `DispatchUpdates` (line 11): `__init__`, `notified`, `publish`, `worker`.

Top-level functions: `build_router` (line 53).

## backend/dispatch_workspace.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/dispatch_workspace.py#L1)

Operational marketplace inbox. No credentials or financial ledger are exposed.

Webhooks are the default ingestion path. Explicitly enabled Shopify polling is
read-only; packing/customs preparation and purchase remain separate actions.

- `Selection` (line 35): .

Top-level functions: `permitted` (line 26), `decoded` (line 31), `poll_shopify` (line 54), `suggested_order` (line 122), `selected_rows` (line 141), `build_router` (line 154).

Public SQL object references: `ecommerce_stores`, `ecommerce_tracking_outbox`, `shipments`.

## backend/ecommerce_connectors.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/ecommerce_connectors.py#L1)

Native signed intake and opt-in Shopify fulfillment delivery.

Credentials remain server configuration. Amazon intake is a signed adapter
gateway, not a claim to implement Amazon SP-API/SNS authentication.

- `StoreConnector` (line 28): `secret_length`, `domain`, `configured`.
- `StoreConnectorSettings` (line 83): .
- `ShopifyFulfillment` (line 211): `__init__`, `graphql`, `deliver`.

Top-level functions: `single_header` (line 88), `receive_store_webhook` (line 95), `normalize_shopify` (line 153), `normalize_woocommerce` (line 175), `shopify_access_token` (line 192).

## backend/ecommerce_inbound.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/ecommerce_inbound.py#L1)

Authenticated Shopify intake and Amazon AWS API-destination order notifications.

- `AmazonInbound` (line 78): `__init__`, `receive`, `process_one`, `worker`.

Top-level functions: `amazon_order` (line 21), `fetch_amazon_order` (line 52), `build_router` (line 179).

Public SQL object references: `amazon_order_notifications`, `ecommerce_stores`.

## backend/ecommerce_sync.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/ecommerce_sync.py#L1)

Tenant-scoped imports and durable fulfillment delivery.

Normalized JWT intake and native signed intake share the database write path.
Delivery defaults to an explicit simulation; server-configured Shopify delivery
uses a durable send fence and remote reconciliation. Other outbound platforms
still require adapters. See ecommerce_connectors.py and the core pillar report.

- `Address` (line 28): `country`.
- `LineItem` (line 45): `decimal_values`, `goods_origin`, `dimensions`.
- `StoreOrder` (line 75): `identifier`.
- `ImportPayload` (line 94): .
- `ReturnReference` (line 141): .
- `EcommerceService` (line 145): `__init__`, `prepare_returns`, `push_live`, `import_order`, `queue_confirmed_tracking`, `push`, `retry_pending`.

Top-level functions: `parsed_order` (line 103), `tracking_link` (line 131), `configure_ecommerce_service` (line 347), `push_tracking_to_store` (line 352), `tracking_worker` (line 359), `build_router` (line 368).

Public SQL object references: `ecommerce_stores`, `ecommerce_tracking_outbox`, `shipments`, `tenants`, `users`.

## backend/help_center.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/help_center.py#L1)

Public, authored customer guidance with no account access or external actions.

- `Guide` (line 17): .

Top-level functions: `guide_source` (line 235), `rendered_guide` (line 245), `render_page` (line 273), `support_hub` (line 328), `support_asset` (line 333), `support_search_index` (line 341), `support_contact` (line 353), `support_source` (line 359), `support_guide` (line 368).

## backend/hubspot_crm.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/hubspot_crm.py#L1)

Optional HubSpot CRM synchronization with durable PostgreSQL jobs.

No credential prefix denotes test mode in HubSpot: pat-* tokens access the
account that issued them. Use a separate developer/test account for testing.

- `HubSpotSettings` (line 30): `optional_account`, `clean_token`, `safe_id`, `activated`.
- `CRMError` (line 88): `__init__`.
- `HubSpotClient` (line 127): `__init__`, `request`, `verify_schema`, `verify_account`, `find`, `record_id`, `upsert`, `onboard`, `milestone`.
- `HubSpotService` (line 284): `__init__`, `enqueue`, `sync`, `log_activity`, `totals`, `process`, `worker`.
- `SyncTenantInput` (line 444): .

Top-level functions: `spend_string` (line 95), `validate_profile` (line 103), `retry_seconds` (line 111), `configure_hubspot_service` (line 427), `sync_tenant_to_hubspot` (line 432), `log_shipping_activity` (line 438), `build_router` (line 449), `safe_process` (line 499), `sync_new_tenant_to_crm` (line 507), `sync_tenant_metrics_to_crm` (line 516).

Public SQL object references: `hubspot_sync_jobs`, `hubspot_tenant_links`, `shipments`, `tenants`, `wallets`.

## backend/hubspot_provisioning.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/hubspot_provisioning.py#L1)

Signed HubSpot deal events and durable, idempotent workspace provisioning.

CRM payloads identify deals only. Canonical company/contact data is fetched
using the account-scoped service key, never trusted from webhook body fields.

- `DealEvent` (line 23): .

Top-level functions: `verify_signature` (line 35), `webhook` (line 49), `safe_pending` (line 86), `association_id` (line 94), `provision` (line 104), `process_pending` (line 164).

Public SQL object references: `hubspot_activation_jobs`, `hubspot_tenant_links`, `tenants`, `wallets`.

## backend/identity.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/identity.py#L1)

Password-verified, revocable HS256 app sessions around Supabase Auth identity.

- `IdentityRoute` (line 16): `get_route_handler`.
- `Login` (line 38): .
- `ProfileUpdate` (line 44): .
- `RecoveryRequest` (line 254): .
- `ResetPassword` (line 259): .

Top-level functions: `unwrap_app_session` (line 50), `token` (line 75), `renew` (line 130), `current_identity` (line 209), `me` (line 224), `update_me` (line 234), `logout` (line 246), `recovery_limit` (line 266), `forgot_password` (line 281), `reset_password` (line 310), `register_account` (line 345), `verify_account` (line 349).

Public SQL object references: `admin_client_assistance_sessions`, `app_auth_sessions`, `app_login_limits`, `app_user_profiles`, `tenants`, `users`.

## backend/inspect_seed_schema.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/inspect_seed_schema.py#L1)

Export only schema metadata needed for relational sandbox fixtures.


Top-level functions: `run` (line 10).

## backend/integration_policy.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/integration_policy.py#L1)

Server-owned switches for new provider work; historical reads remain available.

- `IntegrationSettings` (line 10): .

Top-level functions: `integration_code` (line 21), `integration_enabled` (line 37), `require_integration` (line 44).

## backend/invoice_upload.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/invoice_upload.py#L1)

Bounded statement parsing and reproducible comparisons against server snapshots.

- `StatementLine` (line 35): `currency_code`, `printable`, `exact_numbers`.

Top-level functions: `parse_statement` (line 64), `compare_line` (line 123), `build_router` (line 159).

Public SQL object references: `billing_disputes`, `shipments`.

## backend/label_availability.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/label_availability.py#L1)

Known purchase gates checked before payment; live carrier acceptance is separate.


Top-level functions: `label_availability` (line 5), `require_label_purchase` (line 19).

## backend/logistics_media.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/logistics_media.py#L1)

Normalize real carrier assets and publish read-only, tenant-scoped signed images.

- `PublishedMedia` (line 25): .
- `QRMediaService` (line 89): `__init__`, `publish`.

Top-level functions: `normalize_image` (line 33), `inline_asset` (line 75), `publish_return_media` (line 129).

Public SQL object references: `logistics_media_assets`.

## backend/manifest_service.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/manifest_service.py#L1)

Fenced carrier close-out and explicit internal driver handover documents.

- `ManifestShipment` (line 34): `exact_weight`.
- `ManifestCandidateSummary` (line 51): .
- `ManifestResult` (line 60): .
- `PreviewManifest` (line 74): .
- `CloseManifest` (line 79): .
- `ManifestService` (line 137): `__init__`, `actor`, `warehouse`, `eligibility`, `origin_sql`, `selection_args`, `candidates`, `get_manifestable_summary`, `result`, `download_url`, `close_manifest`, `_close_manifest`, `finish_native`, `complete`, `status`, `document`.

Top-level functions: `postal_origin` (line 85), `manifest_shipment` (line 91), `driver_sheet` (line 107), `build_router` (line 385).

Public SQL object references: `admin_client_assistance_sessions`, `carrier_accounts`, `carrier_manifest_events`, `carrier_manifests`, `partner_cancellations`, `shipments`, `tenant_catalog_addresses`, `tenants`, `users`.

## backend/manifest_workflow.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/manifest_workflow.py#L1)

Read-only shipment action policy; never infer a booking or mutate a quote.


Top-level functions: `decoded` (line 35), `https_asset` (line 44), `workflow` (line 54), `requote_context` (line 92).

## backend/multi_label.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/multi_label.py#L1)

A group is confirmed only when every native package label is confirmed.


Top-level functions: `bundle_labels` (line 5).

## backend/order_csv.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/order_csv.py#L1)

Versioned CSV orders, tenant-scoped persistence and customs review.

The standard layout contains exactly the requested columns. Optional columns
carry facts that cannot be inferred from a shipping address or gross weight.

- `CSVCustomsReview` (line 185): `explicit_review`, `signer_text`, `reviewed_codes`.
- `CSVOrderService` (line 219): `__init__`, `save`, `process`, `review_and_quote`.

Top-level functions: `boolean` (line 38), `template` (line 44), `parse_batch_csv` (line 72), `public_result` (line 311), `country_state_requirements` (line 325), `draft_declaration` (line 330).

Public SQL object references: `ecommerce_stores`, `shipments`, `tenants`, `users`.

## backend/package_guidance.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/package_guidance.py#L1)

Route-scoped package guidance; reference limits never certify carrier eligibility.

- `PackageDimensions` (line 15): `decimal`.
- `PackageCheck` (line 27): `country`, `weight`, `dimensions_required`.
- `QuoteSupport` (line 128): .

Top-level functions: `evaluate_package` (line 66), `build_router` (line 134).

## backend/package_sets.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/package_sets.py#L1)

Exact physical package snapshots; carrier APIs receive individual boxes.

- `PackageInput` (line 7): `decimal`.

Top-level functions: `package_charge` (line 21), `validate_goods_allocation` (line 34), `persist_package_goods` (line 50).

Public SQL object references: `shipment_goods_items`, `shipments`.

## backend/paf_lookup.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/paf_lookup.py#L1)

Asynchronous licensed PAF lookup boundary. Postcode syntax is not delivery proof.

- `PAFLookupUnavailable` (line 14): .
- `PAFPremise` (line 25): `address`, `label`.
- `PAFClient` (line 50): `lookup`.
- `IdealPostcodesClient` (line 54): `__init__`, `lookup`.

Top-level functions: `uk_postcode` (line 18).

## backend/payment_gateway.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/payment_gateway.py#L1)

Environment-validated Checkout gateway over the shared, atomic wallet ledger service.

- `ReconciliationError` (line 25): .
- `SnapshotWebhookService` (line 47): `__init__`, `register`, `charge_topup`, `refund`, `failed`, `process`, `worker`.
- `CheckoutInput` (line 220): `fixed_amount`.

Top-level functions: `resource_id` (line 29), `minor_amount` (line 36), `safe_trace` (line 42), `snapshot_webhook` (line 189), `checkout_redirect` (line 233), `checkout_return_base` (line 241), `reconcile_topup` (line 256), `safe_checkout_url` (line 285), `require_payment_gateway` (line 297), `require_test_gateway` (line 305), `ensure_customer` (line 314), `build_router` (line 351).

Public SQL object references: `shipments`, `stripe_charge_refunds`, `stripe_webhook_events`, `tenants`, `wallet_ledger`, `wallet_reservations`, `wallet_topups`, `wallets`.

## backend/platform_carriers.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/platform_carriers.py#L1)

Owner-managed shared provider connections; tenant shipments retain isolated FKs.

- `PlatformConnection` (line 16): .

Top-level functions: `save` (line 21), `list_connections` (line 108), `create` (line 115), `update` (line 120), `retire` (line 126), `capabilities` (line 135), `upgrade_sendcloud` (line 142), `verify_connection` (line 207).

Public SQL object references: `carrier_accounts`, `platform_carrier_connections`, `platform_carrier_events`, `shipments`, `tenants`.

## backend/provider_routing.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/provider_routing.py#L1)

Bounded direct-first routing without sacrificing uncovered carrier options.


Top-level functions: `service_key` (line 11), `run_tiered_providers` (line 15).

## backend/rate_diagnostics.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/rate_diagnostics.py#L1)

Safe rate diagnostics; never expose upstream response bodies or credentials.

- `RateCurrencyUnavailable` (line 21): `__init__`.
- `RateHTTPRejected` (line 27): `__init__`.

Top-level functions: `record_quote_case` (line 4), `no_rates_message` (line 33).

Public SQL object references: `automation_failures`, `support_tickets`.

## backend/repair_local_config.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/repair_local_config.py#L1)

Repair identifiable dotenv formatting without printing credential values.


Top-level functions: `run` (line 12).

## backend/return_delivery.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/return_delivery.py#L1)

Payment-gated customer return documents and durable transactional notices.

- `ReturnDeliverySettings` (line 23): .
- `ReturnDeliveryWorker` (line 140): `__init__`, `drain`, `worker`.

Top-level functions: `configuration` (line 33), `document_base` (line 37), `delivery_capabilities` (line 47), `validate_delivery` (line 63), `label_ready` (line 76), `signed_document` (line 90), `customer_document` (line 99), `stage_notices` (line 122).

Public SQL object references: `return_customer_deliveries`, `return_review_sessions`, `shipments`, `tenants`, `users`, `wallet_topups`.

## backend/return_documents.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/return_documents.py#L1)

Optional carrier drop-off documents; never a second label purchase.


Top-level functions: `request_easypost_qr` (line 13), `public_return_links` (line 47), `verify_dropoff_token` (line 68), `recover_easypost_qr` (line 83).

Public SQL object references: `shipments`.

## backend/return_ingress.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/return_ingress.py#L1)

Signed normalized return commands from merchant and marketplace gateways.

Native refunds are deliberately not label-purchase commands. A merchant backend
must explicitly submit the reviewed full-parcel return and its charge bearer.


Top-level functions: `receive_return_webhook` (line 19).

Public SQL object references: `ecommerce_stores`, `tenants`, `users`.

## backend/return_review.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/return_review.py#L1)

Two-phase, tenant-bound return preparation and explicit service selection.

Preparation never buys postage. The original full-parcel command receipt is
claimed atomically before checkout; ambiguous purchases are never replayed.

- `ReturnEdits` (line 22): .
- `ReturnDelivery` (line 37): .
- `ReviewRequest` (line 44): .
- `SelectReturn` (line 54): .
- `ReturnReviewService` (line 85): `__init__`, `ready`, `context`, `prepare`, `select`, `status`.

Top-level functions: `assert_review_purchase` (line 59), `ordered_rates` (line 75), `build_router` (line 306).

Public SQL object references: `partner_shipping_offers`, `payment_carts`, `return_customer_deliveries`, `return_review_sessions`, `reverse_logistics_requests`, `shipments`, `tenant_catalog_addresses`, `wallet_topups`.

## backend/reverse_logistics.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/reverse_logistics.py#L1)

Authenticated, durable full-parcel returns over the existing booking ledger.

Provider calls run outside database transactions. A committed command receipt
fences interrupted requests; a repeated request can observe, never repurchase.

- `ReturnCommand` (line 22): `exact_price_limit`, `reference`.
- `ReverseLogisticsService` (line 66): `__init__`, `status`, `process`, `save`.

Top-level functions: `cheapest_return` (line 48), `process_batch` (line 197).

Public SQL object references: `reverse_logistics_requests`, `shipments`, `tenant_catalog_addresses`.

## backend/runtime_hosting.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/runtime_hosting.py#L1)

Process roles and supervised continuous jobs, independent of provider logic.

- `BackgroundJobs` (line 29): `__init__`, `start`, `close`, `wait_for_failure`.

Top-level functions: `resolve_role` (line 11), `pool_options` (line 17).

## backend/sandbox_hooks.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/sandbox_hooks.py#L1)

Real Stripe test-mode hooks and strict signed Twilio Sandbox requests.

- `InputModel` (line 30): .
- `TestTopupInput` (line 34): .
- `SandboxBillingService` (line 110): `__init__`, `check_tenant`, `check_topup`, `response`, `test_topup`.
- `WhatsAppSandboxSetup` (line 270): .

Top-level functions: `require_prepaid_funds` (line 39), `zero_balance_probe` (line 54), `require_sandbox_environment` (line 66), `simulate_stripe_test_payment` (line 75), `authenticated_twilio_form` (line 225), `build_router` (line 281).

Public SQL object references: `tenants`, `users`, `wallet_topups`, `wallets`, `whatsapp_bindings`, `whatsapp_routes`.

## backend/seed_rigorous_data.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/seed_rigorous_data.py#L1)

Apply or rollback-verify the complete relational seed in one transaction.


Top-level functions: `run` (line 13).

Public SQL object references: `carrier_accounts`, `fixture_seed_runs`, `shipments`, `tenants`, `users`, `wallets`.

## backend/sendcloud_adapter.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/sendcloud_adapter.py#L1)

Read-only Sendcloud v2 rates for explicitly configured contract methods.

No label creation occurs here. Methods need verified cargo/dimension limits;
neither an unknown tariff nor an unavailable price is turned into a quote.

- `SendcloudMethod` (line 18): `bounds`.

Top-level functions: `quote_sendcloud` (line 38), `sendcloud_credentials` (line 92), `quote_sendcloud_v3` (line 102).

Public SQL object references: `strip`.

## backend/shipment_protection.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/shipment_protection.py#L1)

XCover premium arithmetic and explicit integration readiness.

Documented parcel API: https://xcover-api-docs.covergenius.com/parcel_insurance.html
Paid checkout remains gated until partner credentials and product settings
are configured. Native headless claims use the separate XClaim JWT/FNOL/upload
API in backend/xcover_claims.py. Portal referral remains available while
partner claims credentials or insurer form bindings are not configured.

- `XCoverSettings` (line 87): `environment_alias`, `settings_customise_sources`, `unavailable_reason`, `base_url`.
- `PlatformSettlement` (line 185): `exact_payout`, `received_date`.
- `XCoverAddress` (line 213): `country_is_valid`.
- `XCoverGoods` (line 237): .
- `XCoverParcelQuote` (line 245): `aware_dates`, `payload`.
- `XCoverRejected` (line 332): .
- `XCoverUncertain` (line 336): .
- `XCoverClient` (line 340): `__init__`, `_request`, `resource_id`, `create_quote`, `get_quote`, `get_booking`, `book`, `confirmed_booking`.
- `ProtectionService` (line 620): `__init__`, `ready`, `prepare`, `public_quote`, `ledger`, `reserve`, `release`, `book`, `confirm`, `reconcile_pending`, `worker`, `credit_settlement`.

Top-level functions: `calculate_xcover_premium` (line 52), `load_xcover_settings` (line 174), `decimal_json` (line 294), `xcover_headers` (line 316), `verify_xcover_webhook` (line 488), `claims_portal_url` (line 529), `price_snapshot` (line 549), `supplier_address` (line 603), `book_xcover_policy` (line 1508), `require_claim_role` (line 1523), `decoded` (line 1528), `insurance_schema_ready` (line 1532), `validate_evidence` (line 1540), `insured_shipment` (line 1578), `build_router` (line 1601).

Public SQL object references: `insurance_claim_cases`, `insurance_claim_evidence`, `insurance_purchases`, `insurance_settlements`, `insurance_webhook_receipts`, `partner_shipping_offers`, `shipments`, `support_message_outbox`, `support_ticket_activity`, `support_tickets`, `tenants`, `users`, `wallet_ledger`, `wallets`, `whatsapp_bindings`, `workspace_dispatch_events`.

## backend/store_connections.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/store_connections.py#L1)

Write-only merchant setup; encrypted envelopes are bound to tenant and store.

- `ConnectionSetup` (line 14): .

Top-level functions: `resolve_connector` (line 34), `public_settings` (line 51), `build_router` (line 67).

Public SQL object references: `amazon_order_notifications`, `ecommerce_stores`, `workspace_store_connections`.

## backend/store_returns.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/store_returns.py#L1)

Native return tracking without forward fulfillment, refunds or restocking.

- `ShopifyReturnTracking` (line 9): `inspect`, `deliver`.

Top-level functions: `sync_return_jobs` (line 58).

Public SQL object references: `ecommerce_stores`, `ecommerce_tracking_outbox`, `shipments`.

## backend/support_alert_controls.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/support_alert_controls.py#L1)

Platform delivery controls separate from the recipient's verified consent.

- `AlertPause` (line 8): .

Top-level functions: `build_router` (line 13).

Public SQL object references: `tenants`, `whatsapp_bindings`.

## backend/support_delivery.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/support_delivery.py#L1)

Opt-in WhatsApp notification delivery with a durable uncertain-send fence.

An accepted Twilio request is not proof of delivery. Only signed callbacks can
advance the delivery state. Uncertain requests are never blindly resent.

- `DeliverySettings` (line 24): `configured`.
- `Consent` (line 42): .
- `SupportDelivery` (line 46): `__init__`, `drain`, `worker`, `callback`.

Top-level functions: `build_router` (line 146).

Public SQL object references: `shipments`, `support_message_outbox`, `support_tickets`, `tenants`, `users`, `whatsapp_bindings`.

## backend/support_workflow.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/support_workflow.py#L1)

Explicit internal review ownership and tenant-scoped append-only activity.


Top-level functions: `present_ticket` (line 9), `add_internal_note` (line 47).

Public SQL object references: `app_user_profiles`, `support_ticket_activity`, `support_tickets`, `users`.

## backend/tenant_catalogs.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/tenant_catalogs.py#L1)

Private, versioned tenant registries. No bookings, wallet changes or AI calls.

- `Input` (line 13): .
- `ProductInput` (line 18): `decimals`, `country`, `review`.
- `ArchiveInput` (line 45): .
- `TenantCatalogService` (line 83): `__init__`, `product_by_sku`, `list`, `save`, `archive`.

Top-level functions: `permission` (line 55), `public_record` (line 60), `database_error` (line 75), `build_router` (line 166).

Public SQL object references: `tenant_catalog_addresses`, `tenant_catalog_products`.

## backend/test_supabase_transaction.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/test_supabase_transaction.py#L1)

Explicit, persisted sandbox connectivity test. Creates no payments or labels.


Top-level functions: `run` (line 17).

Public SQL object references: `margin_rules`, `tenants`, `wallets`.

## backend/tools/__init__.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/tools/__init__.py#L1)

Explicitly invoked operational utilities; never run as application startup jobs.

## backend/tools/sme_lead_scraper.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/tools/sme_lead_scraper.py#L1)

Company-level UK logistics prospect discovery and unsent outreach drafts.

Uses the official Companies House API, not officer records or inferred ethnicity.
Run: python -m backend.tools.sme_lead_scraper --help

- `DiscoveryError` (line 35): .
- `CompaniesHouseDiscovery` (line 118): `__init__`, `page`, `discover`.

Top-level functions: `district` (line 39), `company_number` (line 46), `public_url` (line 53), `read_evidence` (line 61), `outreach_draft` (line 96), `write_report` (line 225), `main` (line 244).

## backend/tracking_and_support.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/tracking_and_support.py#L1)

Signed, tenant/account-scoped tracking and durable support staging.

Provider adapters normalize their webhook into TrackingEvent and sign the raw
body. No arbitrary delivery URL is fetched and no LLM receives carrier text.

- `TrackingKey` (line 36): `strong_key`.
- `TrackingSettings` (line 51): .
- `InternalTrackingSource` (line 57): .
- `TrackingEvent` (line 77): `optional_time`, `coherent_milestone`, `aware_time`, `printable`.
- `TrackingSupportService` (line 166): `__init__`, `ingest`, `stage_tickets`, `worker`, `report`.

Top-level functions: `load_tracking_settings` (line 64), `validate_pod_url` (line 121), `draft_remedy` (line 142), `money` (line 160), `build_router` (line 349), `native_easypost_webhook` (line 398).

Public SQL object references: `carrier_accounts`, `shipments`, `support_message_outbox`, `support_ticket_activity`, `support_tickets`, `tracking_events`, `users`, `wallet_topups`, `whatsapp_bindings`.

## backend/tracking_refresh.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/tracking_refresh.py#L1)

Bounded read-only reconciliation. Never create a tracker or retry a purchase.

- `TrackingCapabilities` (line 27): .
- `TrackingRateLimited` (line 33): `__init__`.
- `EasyPostTrackingAdapter` (line 44): `lookup`.
- `TrackingRefreshWorker` (line 93): `__init__`, `seed`, `enqueue`, `claim`, `process`, `worker`.
Public SQL object references: `carrier_accounts`, `shipments`, `tenants`, `tracking_provider_limits`, `tracking_refresh_jobs`, `users`.

## backend/tracking_workspace.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/tracking_workspace.py#L1)

Shared, tenant-bound tracking projections and revocable customer capabilities.

Existing tracking receipts and shipment/return states stay authoritative. This
module never buys labels, changes a carrier scan or infers a merchandise refund.

- `TrackingScope` (line 122): .
- `ShareRequest` (line 128): .
- `ResolveRequest` (line 135): .
- `CustomerRequest` (line 140): `readable`.
- `Preferences` (line 152): .
- `ReviewRequest` (line 161): .
- `TrackingWorkspace` (line 181): `__init__`, `initialise`, `require_ready`, `audit`, `preferences`, `row`, `detail`, `search`, `record_event`, `share`, `public_rate_limit`, `resolve`, `chat`, `customer_request`.

Top-level functions: `obj` (line 32), `iso` (line 41), `event_detail` (line 45), `scan_fingerprint` (line 49), `timeline_projection` (line 53), `shipment_projection` (line 72), `build_router` (line 443).

Public SQL object references: `carrier_accounts`, `ecommerce_tracking_outbox`, `shipments`, `tenants`, `tracking_case_reviews`, `tracking_customer_requests`, `tracking_events`, `tracking_notifications`, `tracking_operations_audit`, `tracking_preferences`, `tracking_refresh_jobs`, `tracking_share_links`, `users`.

## backend/verify_automation_sandbox.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/verify_automation_sandbox.py#L1)

Persist one clearly identified invalid-order support test; no carrier calls.


Top-level functions: `run` (line 13).

Public SQL object references: `automation_failures`, `support_tickets`, `wallets`.

## backend/verify_automation_writepath.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/verify_automation_writepath.py#L1)

Real PostgreSQL write-path probe with controlled rates and final rollback.

No HubSpot, Twilio, Stripe or carrier requests are made. Seed fixtures are
unchanged after the test transaction is rolled back.

- `BorrowedPool` (line 20): `__init__`, `acquire`.
- `DiagnosticConnection` (line 26): `__init__`, `__getattr__`, `execute`.

Top-level functions: `run` (line 36).

Public SQL object references: `carrier_accounts`, `shipments`, `tenants`, `users`.

## backend/verify_supabase.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/verify_supabase.py#L1)

Read-only connection/schema probe. Never log credentials or raw server errors.


Top-level functions: `run` (line 14).

Public SQL object references: `status_code`.

## backend/verify_tracking_support.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/verify_tracking_support.py#L1)

Real sandbox schema, tenant-scoped report and durable ticket-worker verification.


Top-level functions: `run` (line 14).

Public SQL object references: `shipments`.

## backend/web_registration.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/web_registration.py#L1)

Email-verified public account creation; passwords and OTPs are never stored locally.

- `RegistrationStart` (line 20): `match_profile`.
- `RegistrationVerify` (line 32): `numeric_code`.

Top-level functions: `start_registration` (line 48), `verify_registration` (line 75).

Public SQL object references: `app_user_profiles`, `tenants`, `users`, `wallets`, `web_registration_sessions`.

## backend/webhook_security.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/webhook_security.py#L1)

Query-secret redaction and optional trusted-proxy-aware webhook IP policy.

- `WebhookSecretFilter` (line 17): `filter`.

Top-level functions: `redact_query_secrets` (line 11), `install_webhook_log_redaction` (line 41), `enforce_shippo_source_ip` (line 52).

## backend/whatsapp_bot.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/whatsapp_bot.py#L1)

Signed WhatsApp ingress into the shared authenticated conversational gateway.

Booking commands return a signed selection link to authenticated web checkout.
Payment and label purchase require confirmation in the workspace.

- `WhatsAppConfiguration` (line 20): .

Top-level functions: `initialize_whatsapp` (line 28), `xml_message` (line 41), `format_quotes` (line 60), `whatsapp_webhook` (line 87).

## backend/whatsapp_ingress.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/whatsapp_ingress.py#L1)

Local ingress for tunneling only signed Twilio callbacks, never the app UI/API.


Top-level functions: `lifespan` (line 11), `identify_gateway` (line 23), `forward` (line 29), `incoming_message` (line 58), `delivery_status` (line 63), `media_status` (line 68).

## backend/whatsapp_onboarding.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/whatsapp_onboarding.py#L1)

Signed-phone registration with separate email proof and native Auth identities.

No model handles identity or verification codes. Provider IO occurs outside SQL
transactions. An uncertain Auth verification is fenced for operator review.

- `SupabaseSignupProvider` (line 53): `__init__`, `request`, `send_code`, `verify`, `bind_workspace`, `password_email`.
- `ConversationalSignupManager` (line 150): `__init__`, `digest`, `company`, `profile`, `ready`, `replay`, `receipt_reply`, `phones`, `handle`, `finish`, `duplicate`, `email_identity_blocked`, `advance`, `send_codes`, `lock`, `provision`.

Top-level functions: `now` (line 45), `decoded` (line 49), `onboarding_manager` (line 477).

Public SQL object references: `app_user_profiles`, `tenants`, `users`, `wallets`, `whatsapp_bindings`, `whatsapp_registration_queue`, `whatsapp_registration_receipts`.

## backend/whatsapp_queue.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/whatsapp_queue.py#L1)

Durable WhatsApp ingress and REST delivery; no carrier work in the HTTP ack.

- `OutboundPart` (line 29): `media`.
- `WhatsAppQueue` (line 130): `__init__`, `encrypt`, `enqueue`, `claim`, `mark`, `stage`, `dispatch`, `status_url`, `schedule_fallback`, `send_failure`, `drain`, `worker`.

Top-level functions: `inbound_digest` (line 47), `reply_parts` (line 53), `return_media` (line 62), `process_inbound` (line 84), `accept_whatsapp` (line 296), `build_media_status_router` (line 312).

Public SQL object references: `whatsapp_inbound_queue`, `whatsapp_reply_outbox`.

## backend/worker_runtime.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/worker_runtime.py#L1)

Dedicated queue consumer. Run with python -m backend.worker_runtime.


Top-level functions: `serve` (line 11), `main` (line 49).

## backend/workspace_personas.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/workspace_personas.py#L1)

Shared account profiles and exact consumer pricing; no parallel wallets.

- `PersonalProfile` (line 8): `name_text`.

Top-level functions: `storage_profile` (line 22), `individual_policy` (line 32).

Public SQL object references: `individual_pricing_settings`.

## backend/workspace_settings.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/workspace_settings.py#L1)

Tenant-owned settings, verified email invitations and durable dispute drafts.

- `Invite` (line 10): .
- `Accept` (line 16): .
- `MemberUpdate` (line 20): .
- `CompanyUpdate` (line 24): .
- `Draft` (line 29): .

Top-level functions: `owner` (line 33), `invitation_limit` (line 35), `headers` (line 45), `deliver_invitation` (line 49), `build_router` (line 69).

Public SQL object references: `app_auth_sessions`, `app_login_limits`, `carrier_accounts`, `partner_provider_options`, `partner_unbound_quotes`, `platform_carrier_connections`, `shipment_dispute_drafts`, `shipments`, `tenants`, `tracking_events`, `users`, `workspace_invitations`.

## backend/xcover_claims.py

[Open source](https://github.com/sync4ai-lab/easyinvio/blob/2c71251d1bb3b30a0a7cc38a92d8db3f667cbce2/backend/xcover_claims.py#L1)

Native XClaim JWT, FNOL, evidence, async claims and signed status events.

Partner-specific FNOL bindings and settlement field paths are configuration,
not guessed wire fields. See https://partner-docs.covergenius.com/xclaim.

- `XClaimClient` (line 51): `__init__`, `unavailable_reason`, `origin`, `partner_path`, `token`, `request`, `claim_type`, `fnol`, `upload`, `create`, `get_claim`, `get_reference`, `verify_signature`.
- `XClaimService` (line 274): `__init__`, `prepare_payload`, `submit_one`, `reconcile`, `webhook`, `drain`, `worker`.

Top-level functions: `json_pointer` (line 37).

Public SQL object references: `insurance_claim_cases`, `insurance_claim_evidence`, `tenants`, `xclaim_webhook_receipts`.

## Test and probe file index

- `tests/aggregator_lifecycle_database_probe.py`
- `tests/apply_support_migration.py`
- `tests/budget_strategy_browser.py`
- `tests/build_uat_artifacts.py`
- `tests/bulk_dispatch_browser.py`
- `tests/card_checkout_browser.py`
- `tests/card_checkout_database_probe.py`
- `tests/carrier_consolidation_database_probe.py`
- `tests/client_assistance_browser.py`
- `tests/client_assistance_database_probe.py`
- `tests/complete_matrix_seed_database_probe.py`
- `tests/configure_platform_owner.py`
- `tests/conversation_context_browser.py`
- `tests/conversational_chat_browser.py`
- `tests/core_pillars_database_probe.py`
- `tests/csv_database_probe.py`
- `tests/customer_checkout_browser.py`
- `tests/customer_checkout_database_probe.py`
- `tests/delivery_quality_browser.py`
- `tests/disabled_provider_database_probe.py`
- `tests/dispatcher_database_probe.py`
- `tests/dispatcher_wallet_lock_probe.py`
- `tests/enterprise_database_probe.py`
- `tests/format_frontend.py`
- `tests/frontend_contract.cjs`
- `tests/headless_returns_browser.py`
- `tests/help_center_browser.py`
- `tests/hubspot_database_probe.py`
- `tests/identity_database_probe.py`
- `tests/label_operations_browser.py`
- `tests/manifest_workflow_browser.py`
- `tests/multi_piece_browser.py`
- `tests/overview_cleanup_browser.py`
- `tests/package_guidance_browser.py`
- `tests/packaging_sizes_browser.py`
- `tests/payment_checkout_recovery_browser.py`
- `tests/payment_database_probe.py`
- `tests/pglite_tracking_bridge.cjs`
- `tests/platform_carriers_database_probe.py`
- `tests/quote_connection_browser.py`
- `tests/report_uat_remediation.py`
- `tests/reporting_browser.py`
- `tests/reporting_database_probe.py`
- `tests/return_workspace_browser.py`
- `tests/schema_upgrade_database_probe.py`
- `tests/sendcloud_pending_database_probe.py`
- `tests/session_lifecycle_browser.py`
- `tests/shipment_phone_browser.py`
- `tests/smoke_http.py`
- `tests/store_connections_database_probe.py`
- `tests/store_integrations_browser.py`
- `tests/stripe_snapshot_database_probe.py`
- `tests/support_alert_controls_database_probe.py`
- `tests/support_monitoring_database_probe.py`
- `tests/support_workflow_browser.py`
- `tests/support_workflow_database_probe.py`
- `tests/support_workflow_readiness.py`
- `tests/tenant_catalogs_browser.py`
- `tests/tenant_catalogs_database_probe.py`
- `tests/tenant_onboarding_database_probe.py`
- `tests/test_admin_portal.py`
- `tests/test_agents.py`
- `tests/test_aggregator_lifecycle.py`
- `tests/test_automation_freight.py`
- `tests/test_bulk_checkout.py`
- `tests/test_carrier_consolidation.py`
- `tests/test_carrier_consolidation_browser.py`
- `tests/test_carrier_disable.py`
- `tests/test_checkout_carrier_rejection.py`
- `tests/test_client_assistance.py`
- `tests/test_conversation_context.py`
- `tests/test_conversational_gateway.py`
- `tests/test_core_pillars.py`
- `tests/test_csv_browser.py`
- `tests/test_customer_checkout.py`
- `tests/test_dashboard_portal.py`
- `tests/test_delivery_quality_and_protection.py`
- `tests/test_direct_carrier_provisions.py`
- `tests/test_dispatch_workspace.py`
- `tests/test_dispatcher_browser.py`
- `tests/test_easyinvio_complete_matrix.py`
- `tests/test_ecommerce_sync.py`
- `tests/test_enterprise_browser.py`
- `tests/test_enterprise_security.py`
- `tests/test_headless_returns.py`
- `tests/test_help_center.py`
- `tests/test_hubspot_activation.py`
- `tests/test_hubspot_browser.py`
- `tests/test_hubspot_crm.py`
- `tests/test_identity.py`
- `tests/test_identity_browser.py`
- `tests/test_integration_remediation.py`
- `tests/test_label_failure_operations.py`
- `tests/test_logistics.py`
- `tests/test_logistics_media.py`
- `tests/test_manifest_migrations.cjs`
- `tests/test_manifest_service.py`
- `tests/test_manifest_workflow.py`
- `tests/test_manifest_workflow_postgres.py`
- `tests/test_margin_optimizer.py`
- `tests/test_modern_logistics.py`
- `tests/test_multi_piece_flow.py`
- `tests/test_native_provider_browser.py`
- `tests/test_optional_integrations.py`
- `tests/test_order_csv.py`
- `tests/test_owner_monitoring_browser.py`
- `tests/test_package_guidance.py`
- `tests/test_paf_lookup.py`
- `tests/test_partner_dispatch_security.py`
- `tests/test_password_recovery.py`
- `tests/test_password_recovery_browser.py`
- `tests/test_payment_browser.py`
- `tests/test_payment_gateway.py`
- `tests/test_payment_recovery.py`
- `tests/test_platform_carriers.py`
- `tests/test_project_folder_rename.py`
- `tests/test_quote_integrity.py`
- `tests/test_quote_support.py`
- `tests/test_rate_diagnostics.py`
- `tests/test_return_review_postgres.py`
- `tests/test_runtime_hosting.py`
- `tests/test_sandbox_hooks.py`
- `tests/test_seller_strategy.py`
- `tests/test_sendcloud_v3.py`
- `tests/test_sme_lead_scraper.py`
- `tests/test_status_guidance.py`
- `tests/test_store_connections.py`
- `tests/test_stripe_listener_setup.py`
- `tests/test_stripe_snapshots.py`
- `tests/test_support_monitoring.py`
- `tests/test_tenant_catalogs.py`
- `tests/test_three_partner_native.py`
- `tests/test_tracking_and_support.py`
- `tests/test_tracking_workspace.py`
- `tests/test_tracking_workspace_postgres.py`
- `tests/test_transactional_remediation.py`
- `tests/test_uat_remediation.py`
- `tests/test_ui_modernization.py`
- `tests/test_whatsapp_bot.py`
- `tests/test_whatsapp_ingress.py`
- `tests/test_whatsapp_onboarding.py`
- `tests/test_whatsapp_queue.py`
- `tests/test_workspace_personas.py`
- `tests/test_workspace_settings.py`
- `tests/test_xclaim.py`
- `tests/test_xcover_protection.py`
- `tests/three_partner_database_probe.py`
- `tests/tracking_workspace_browser.py`
- `tests/transactional_remediation_browser.py`
- `tests/transactional_remediation_database_probe.py`
- `tests/uat_automation_suite.py`
- `tests/uat_browser_probe.py`
- `tests/uat_bulk_isolation_probe.py`
- `tests/uat_database_probe.py`
- `tests/uat_finalize.py`
- `tests/uat_finance_capture_probe.py`
- `tests/uat_matrix_support.py`
- `tests/uat_post_apply.py`
- `tests/uat_provider_fault_probe.py`
- `tests/uat_real_auth_probe.py`
- `tests/uat_supplement_probe.py`
- `tests/vercel_hosting_browser.py`
- `tests/whatsapp_checkout_browser.py`
- `tests/whatsapp_database_probe.py`
- `tests/workspace_personas_browser.py`
- `tests/workspace_settings_browser.py`
- `tests/workspace_settings_database_probe.py`
- `tests/write_uat_report.py`
- `tests/xcover_browser.py`
- `tests/xcover_database_probe.py`
