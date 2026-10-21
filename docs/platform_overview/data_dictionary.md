# Migration and data dictionary

The initial core schema is not fully checked in. Obtain an authorized baseline before applying the sequence. Definitions below reproduce source CREATE TABLE blocks; later ALTERs, indexes, triggers, policies and grants remain in linked migrations. This is not a live/final schema dump.

## Migration index

| File | Tables introduced | Tables altered | Functions introduced or replaced |
| --- | --- | --- | --- |
| [migrations/006_logistics_metadata.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/006_logistics_metadata.sql#L1) |  | shipments | guard_logistics_metadata |
| [migrations/007_admin_configuration.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/007_admin_configuration.sql#L1) | admin_configuration_events | admin_configuration_events, margin_rules, tenants | guard_platform_configuration |
| [migrations/008_sandbox_hooks.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/008_sandbox_hooks.sql#L1) |  | tenants, wallet_ledger, wallet_topups | guard_sandbox_flags |
| [migrations/009_ecommerce_sync.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/009_ecommerce_sync.sql#L1) | ecommerce_stores, ecommerce_tracking_outbox | ecommerce_stores, ecommerce_tracking_outbox, shipments | guard_ecommerce_import_fields |
| [migrations/010_hubspot_crm.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/010_hubspot_crm.sql#L1) | hubspot_sync_jobs, hubspot_tenant_links | hubspot_sync_jobs, hubspot_tenant_links | queue_hubspot_sync |
| [migrations/011_tracking_and_support.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/011_tracking_and_support.sql#L1) | tracking_events, support_tickets, support_message_outbox | shipments, support_message_outbox, support_tickets, tracking_events | guard_delivery_proof |
| [migrations/012_dashboard_portal.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/012_dashboard_portal.sql#L1) |  | support_tickets |  |
| [migrations/013_automation_freight.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/013_automation_freight.sql#L1) | automation_failures | automation_failures, ecommerce_stores, shipments, support_tickets |  |
| [migrations/014_support_ticket_lifecycle.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/014_support_ticket_lifecycle.sql#L1) |  | support_tickets |  |
| [migrations/015_admin_management.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/015_admin_management.sql#L1) | admin_management_events | admin_management_events |  |
| [migrations/016_core_pillars.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/016_core_pillars.sql#L1) |  | ecommerce_tracking_outbox, margin_rules, shipments |  |
| [migrations/017_support_delivery_and_monitoring.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/017_support_delivery_and_monitoring.sql#L1) |  | support_message_outbox, whatsapp_bindings | guard_notification_consent |
| [migrations/018_hubspot_activation_and_metrics.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/018_hubspot_activation_and_metrics.sql#L1) | hubspot_activation_jobs | hubspot_activation_jobs, hubspot_tenant_links | guard_hubspot_references, queue_hubspot_wallet_sync |
| [migrations/019_stripe_snapshot_reconciliation.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/019_stripe_snapshot_reconciliation.sql#L1) | stripe_webhook_events, stripe_charge_refunds | stripe_charge_refunds, stripe_webhook_events, wallet_ledger, wallet_topups | guard_stripe_transaction_trace |
| [migrations/020_platform_carriers.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/020_platform_carriers.sql#L1) | platform_carrier_connections, platform_carrier_events | carrier_accounts, platform_carrier_connections, platform_carrier_events | guard_platform_carrier_link, lock_platform_carrier_catalog, platform_carrier_changed, tenant_platform_carriers |
| [migrations/021_identity_sessions.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/021_identity_sessions.sql#L1) | app_auth_sessions, app_user_profiles, app_login_limits | app_auth_sessions, app_login_limits, app_user_profiles |  |
| [migrations/022_carrier_consolidation.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/022_carrier_consolidation.sql#L1) |  |  |  |
| [migrations/023_partner_lifecycle.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/023_partner_lifecycle.sql#L1) | partner_unbound_quotes, partner_shipping_offers, partner_cancellations | partner_cancellations, partner_shipping_offers, partner_unbound_quotes, platform_carrier_connections, wallet_ledger |  |
| [migrations/024_native_partner_orders_and_webhooks.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/024_native_partner_orders_and_webhooks.sql#L1) | partner_provider_options, partner_order_jobs | partner_order_jobs, partner_provider_options | queue_native_partner_order |
| [migrations/025_pending_label_poll_index.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/025_pending_label_poll_index.sql#L1) |  |  |  |
| [migrations/026_support_review_activity.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/026_support_review_activity.sql#L1) | support_ticket_activity | support_ticket_activity, support_tickets |  |
| [migrations/027_workspace_invitations_and_disputes.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/027_workspace_invitations_and_disputes.sql#L1) | workspace_invitations, shipment_dispute_drafts | shipment_dispute_drafts, workspace_invitations |  |
| [migrations/028_reporting_transit_index.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/028_reporting_transit_index.sql#L1) |  |  |  |
| [migrations/029_booking_references.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/029_booking_references.sql#L1) | booking_references | booking_references |  |
| [migrations/030_card_checkout.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/030_card_checkout.sql#L1) | payment_carts | payment_carts |  |
| [migrations/031_store_connections.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/031_store_connections.sql#L1) | workspace_store_connections | workspace_store_connections |  |
| [migrations/032_dispatch_events_and_invoice_audits.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/032_dispatch_events_and_invoice_audits.sql#L1) | workspace_dispatch_events, billing_disputes, amazon_order_notifications | amazon_order_notifications, billing_disputes, shipments, workspace_dispatch_events | emit_workspace_dispatch_event |
| [migrations/033_xcover_claim_cases.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/033_xcover_claim_cases.sql#L1) | insurance_purchases, insurance_claim_cases, insurance_settlements, insurance_claim_evidence, xclaim_webhook_receipts, insurance_webhook_receipts | insurance_claim_cases, insurance_claim_evidence, insurance_purchases, insurance_settlements, insurance_webhook_receipts, support_message_outbox, support_tickets, wallet_ledger, xclaim_webhook_receipts |  |
| [migrations/034_support_alert_controls.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/034_support_alert_controls.sql#L1) |  | whatsapp_bindings |  |
| [migrations/035_packages_goods_returns_and_credential_locks.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/035_packages_goods_returns_and_credential_locks.sql#L1) | shipment_goods_items | carrier_accounts, ecommerce_tracking_outbox, shipment_goods_items, shipments | check_shipment_goods_mass, classify_store_tracking_job, freeze_submitted_package_snapshot, guard_carrier_credential_identity, lock_goods_parent, valid_multi_parcel_dimensions |
| [migrations/036_tenant_catalogs.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/036_tenant_catalogs.sql#L1) | tenant_catalog_addresses, tenant_catalog_contacts, tenant_catalog_products | tenant_catalog_addresses, tenant_catalog_contacts, tenant_catalog_products |  |
| [migrations/037_admin_client_assistance.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/037_admin_client_assistance.sql#L1) | admin_client_assistance_sessions, admin_client_assistance_events | admin_client_assistance_events, admin_client_assistance_sessions | protect_assistance_event |
| [migrations/038_conversational_actions.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/038_conversational_actions.sql#L1) | conversational_messages | conversational_messages |  |
| [migrations/039_whatsapp_onboarding.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/039_whatsapp_onboarding.sql#L1) | whatsapp_registration_queue, whatsapp_registration_receipts | tenants, whatsapp_registration_queue, whatsapp_registration_receipts |  |
| [migrations/040_workspace_personas.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/040_workspace_personas.sql#L1) | individual_pricing_settings, individual_pricing_events, web_registration_sessions | individual_pricing_events, individual_pricing_settings, tenants, web_registration_sessions, whatsapp_registration_queue |  |
| [migrations/041_budget_seller_strategy.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/041_budget_seller_strategy.sql#L1) |  | admin_management_events, tenants | guard_workspace_strategy |
| [migrations/042_headless_returns.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/042_headless_returns.sql#L1) | reverse_logistics_requests | reverse_logistics_requests |  |
| [migrations/043_whatsapp_async_ingress.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/043_whatsapp_async_ingress.sql#L1) | whatsapp_inbound_queue, whatsapp_reply_outbox | whatsapp_inbound_queue, whatsapp_reply_outbox |  |
| [migrations/044_carrier_manifests_and_media.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/044_carrier_manifests_and_media.sql#L1) | carrier_manifests, carrier_manifest_events, logistics_media_assets | carrier_manifest_events, carrier_manifests, logistics_media_assets, shipments, whatsapp_reply_outbox | guard_manifest_assignment, protect_manifest_event |
| [migrations/045_unified_tracking.sql](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/045_unified_tracking.sql#L1) | tracking_share_links, tracking_customer_requests, tracking_preferences, tracking_notifications, tracking_refresh_jobs, tracking_provider_limits, tracking_case_reviews, tracking_operations_audit | public, tracking_events | guard_tracking_share, protect_tracking_history |

## Exact CREATE TABLE definitions

### admin_client_assistance_events

Source: [migrations/037_admin_client_assistance.sql:17](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/037_admin_client_assistance.sql#L17).

```sql
CREATE TABLE IF NOT EXISTS public.admin_client_assistance_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 session_id uuid NOT NULL REFERENCES public.admin_client_assistance_sessions(id),
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),tenant_id uuid NOT NULL,
 event_type text NOT NULL CHECK(event_type IN ('SESSION_STARTED','SESSION_ENDED','REQUEST_STARTED','REQUEST_FINISHED')),
 request_id uuid,method text,path text,status_code integer CHECK(status_code BETWEEN 100 AND 599),
 detail jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(detail)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,session_id) REFERENCES public.admin_client_assistance_sessions(tenant_id,id),
 FOREIGN KEY(session_id,actor_auth_user_id) REFERENCES public.admin_client_assistance_sessions(id,actor_auth_user_id),
 CHECK((event_type IN ('SESSION_STARTED','SESSION_ENDED') AND request_id IS NULL)
  OR (event_type IN ('REQUEST_STARTED','REQUEST_FINISHED') AND request_id IS NOT NULL AND method IS NOT NULL AND path IS NOT NULL))
);
```

### admin_client_assistance_sessions

Source: [migrations/037_admin_client_assistance.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/037_admin_client_assistance.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.admin_client_assistance_sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 operator_membership_id uuid NOT NULL,
 bearer_sha256 text NOT NULL CHECK(bearer_sha256 ~ '^[a-f0-9]{64}$'),
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 10 AND 500),
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL CHECK(expires_at>created_at),revoked_at timestamptz,
 UNIQUE(tenant_id,id),UNIQUE(id,actor_auth_user_id),
 FOREIGN KEY(tenant_id,operator_membership_id) REFERENCES public.users(tenant_id,id)
);
```

### admin_configuration_events

Source: [migrations/007_admin_configuration.sql:10](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/007_admin_configuration.sql#L10).

```sql
CREATE TABLE IF NOT EXISTS public.admin_configuration_events (
    id uuid PRIMARY KEY,
    actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
    operation text NOT NULL CHECK (operation IN ('CREATE_TENANT','CREATE_MARGIN')),
    request_id uuid NOT NULL,
    tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
    payload_sha256 text NOT NULL CHECK (length(payload_sha256)=64),
    response jsonb NOT NULL CHECK (jsonb_typeof(response)='object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_auth_user_id,operation,request_id)
);
```

### admin_management_events

Source: [migrations/015_admin_management.sql:3](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/015_admin_management.sql#L3).

```sql
CREATE TABLE IF NOT EXISTS public.admin_management_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 action text NOT NULL CHECK(action IN ('CREATE_CARRIER','UPDATE_CARRIER','RETIRE_CARRIER','UPDATE_MARGIN','RETIRE_MARGIN')),
 target_id uuid NOT NULL,
 snapshot jsonb NOT NULL CHECK(jsonb_typeof(snapshot)='object'),
 created_at timestamptz NOT NULL DEFAULT now()
);
```

### amazon_order_notifications

Source: [migrations/032_dispatch_events_and_invoice_audits.sql:88](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/032_dispatch_events_and_invoice_audits.sql#L88).

```sql
CREATE TABLE IF NOT EXISTS public.amazon_order_notifications (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,store_id uuid NOT NULL,
 notification_id text NOT NULL CHECK(length(notification_id) BETWEEN 1 AND 150),
 order_id text NOT NULL CHECK(order_id ~ '^[0-9]{3}-[0-9]{7}-[0-9]{7}$'),
 body_sha256 text NOT NULL CHECK(length(body_sha256)=64),
 status text NOT NULL DEFAULT 'RECEIVED' CHECK(status IN ('RECEIVED','IMPORTED','IGNORED','REVIEW_REQUIRED')),
 attempts integer NOT NULL DEFAULT 0,next_attempt_at timestamptz NOT NULL DEFAULT now(),
 last_error_code text,created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,store_id,notification_id),
 FOREIGN KEY(tenant_id,store_id) REFERENCES public.ecommerce_stores(tenant_id,id)
);
```

### app_auth_sessions

Source: [migrations/021_identity_sessions.sql:3](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/021_identity_sessions.sql#L3).

```sql
CREATE TABLE IF NOT EXISTS public.app_auth_sessions(
 id uuid PRIMARY KEY,auth_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 tenant_id uuid REFERENCES public.tenants(tenant_id),provider_token bytea NOT NULL,key_id text NOT NULL,
 expires_at timestamptz NOT NULL,created_at timestamptz NOT NULL DEFAULT now()
);
```

### app_login_limits

Source: [migrations/021_identity_sessions.sql:14](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/021_identity_sessions.sql#L14).

```sql
CREATE TABLE IF NOT EXISTS public.app_login_limits(
 bucket text PRIMARY KEY,window_start timestamptz NOT NULL DEFAULT now(),attempts integer NOT NULL CHECK(attempts>0)
);
```

### app_user_profiles

Source: [migrations/021_identity_sessions.sql:9](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/021_identity_sessions.sql#L9).

```sql
CREATE TABLE IF NOT EXISTS public.app_user_profiles(
 auth_user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
 full_name text NOT NULL DEFAULT '' CHECK(length(full_name)<=200),
 phone_e164 text CHECK(phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),updated_at timestamptz NOT NULL DEFAULT now()
);
```

### automation_failures

Source: [migrations/013_automation_freight.sql:15](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/013_automation_freight.sql#L15).

```sql
CREATE TABLE IF NOT EXISTS public.automation_failures (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
  idempotency_key uuid NOT NULL,order_reference text NOT NULL,shipment_id uuid,error_code text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,idempotency_key),UNIQUE(tenant_id,id),
  FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### billing_disputes

Source: [migrations/032_dispatch_events_and_invoice_audits.sql:69](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/032_dispatch_events_and_invoice_audits.sql#L69).

```sql
CREATE TABLE IF NOT EXISTS public.billing_disputes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id uuid NOT NULL,
 shipment_id uuid NOT NULL,
 invoice_reference text NOT NULL CHECK(length(invoice_reference) BETWEEN 1 AND 100),
 line_sha256 text NOT NULL CHECK(length(line_sha256)=64),
 findings jsonb NOT NULL CHECK(jsonb_typeof(findings)='array'),
 baseline jsonb NOT NULL CHECK(jsonb_typeof(baseline)='object'),
 invoice_line jsonb NOT NULL CHECK(jsonb_typeof(invoice_line)='object'),
 confidence_level integer NOT NULL CHECK(confidence_level=100),
 estimated_overcharge numeric(14,2) NOT NULL CHECK(estimated_overcharge>=0),
 currency text NOT NULL CHECK(currency IN ('GBP','EUR','USD')),
 email_draft text NOT NULL CHECK(length(email_draft)<=12000),
 status text NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','SUBMITTED','RESOLVED')),
 created_by uuid NOT NULL REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,invoice_reference,shipment_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### booking_references

Source: [migrations/029_booking_references.sql:5](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/029_booking_references.sql#L5).

```sql
CREATE TABLE IF NOT EXISTS public.booking_references(
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),request_id uuid NOT NULL,
 invoice_reference text NOT NULL UNIQUE,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,request_id)
);
```

### carrier_manifest_events

Source: [migrations/044_carrier_manifests_and_media.sql:146](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/044_carrier_manifests_and_media.sql#L146).

```sql
CREATE TABLE public.carrier_manifest_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, tenant_id uuid NOT NULL,
 manifest_id uuid NOT NULL, actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 event_type text NOT NULL CHECK(event_type IN ('SUBMITTED','FAILED','COMPLETED')),
 detail jsonb NOT NULL DEFAULT '{}'::jsonb,created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,manifest_id) REFERENCES public.carrier_manifests(tenant_id,id),
 UNIQUE(tenant_id,manifest_id,event_type)
);
```

### carrier_manifests

Source: [migrations/044_carrier_manifests_and_media.sql:107](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/044_carrier_manifests_and_media.sql#L107).

```sql
CREATE TABLE public.carrier_manifests (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 carrier_account_id uuid NOT NULL REFERENCES public.carrier_accounts(id), carrier_code varchar(50) NOT NULL,
 status varchar(30) NOT NULL CHECK(status IN ('DRAFT','SUBMITTED','FAILED','COMPLETED')),
 master_tracking_id varchar(100), manifest_document_url text,
 total_shipments integer NOT NULL CHECK(total_shipments BETWEEN 1 AND 1000),
 total_weight_kg numeric(10,3) NOT NULL CHECK(total_weight_kg>0),
 created_by uuid NOT NULL REFERENCES auth.users(id),
 request_id uuid NOT NULL, input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 provider_reference text, provider_document_url text, document_pdf bytea,
 document_kind text NOT NULL CHECK(document_kind IN ('CARRIER_MANIFEST','INTERNAL_HANDOVER')),
 snapshot jsonb NOT NULL CHECK(jsonb_typeof(snapshot)='array'),
 environment text NOT NULL CHECK(environment IN ('TEST','LIVE')), error_code text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,id), UNIQUE(tenant_id,carrier_account_id,id), UNIQUE(tenant_id,request_id),
 FOREIGN KEY(tenant_id,carrier_account_id) REFERENCES public.carrier_accounts(tenant_id,id),
 CHECK(status<>'COMPLETED' OR document_pdf IS NOT NULL)
);
```

### conversational_messages

Source: [migrations/038_conversational_actions.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/038_conversational_actions.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.conversational_messages (
 id uuid PRIMARY KEY,
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 channel text NOT NULL CHECK(channel IN ('WHATSAPP','WEB_CHAT')),
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 state text NOT NULL DEFAULT 'PROCESSING' CHECK(state IN ('PROCESSING','COMPLETED','REVIEW_REQUIRED')),
 response jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(response)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz,
 UNIQUE(tenant_id,id)
);
```

### ecommerce_stores

Source: [migrations/009_ecommerce_sync.sql:15](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/009_ecommerce_sync.sql#L15).

```sql
CREATE TABLE IF NOT EXISTS public.ecommerce_stores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
  platform text NOT NULL CHECK (platform IN ('SHOPIFY','WOOCOMMERCE')),
  display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id,id)
);
```

### ecommerce_tracking_outbox

Source: [migrations/009_ecommerce_sync.sql:48](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/009_ecommerce_sync.sql#L48).

```sql
CREATE TABLE IF NOT EXISTS public.ecommerce_tracking_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL,
  shipment_id uuid NOT NULL,
  store_id uuid NOT NULL,
  store_order_id text NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
  status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SIMULATED_DELIVERED')),
  attempts integer NOT NULL DEFAULT 0,
  response jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz,
  UNIQUE (tenant_id,shipment_id),
  FOREIGN KEY (tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
  FOREIGN KEY (tenant_id,store_id) REFERENCES public.ecommerce_stores(tenant_id,id)
);
```

### hubspot_activation_jobs

Source: [migrations/018_hubspot_activation_and_metrics.sql:9](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/018_hubspot_activation_and_metrics.sql#L9).

```sql
CREATE TABLE IF NOT EXISTS public.hubspot_activation_jobs (
  portal_id bigint NOT NULL CHECK(portal_id>0),
  deal_id text NOT NULL CHECK(deal_id ~ '^[0-9]+$'),
  tenant_id uuid REFERENCES public.tenants(tenant_id),
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
  blocked boolean NOT NULL DEFAULT false,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  PRIMARY KEY(portal_id,deal_id)
);
```

### hubspot_sync_jobs

Source: [migrations/010_hubspot_crm.sql:3](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/010_hubspot_crm.sql#L3).

```sql
CREATE TABLE IF NOT EXISTS public.hubspot_sync_jobs (
  tenant_id uuid PRIMARY KEY REFERENCES public.tenants(tenant_id) ON DELETE CASCADE,
  revision bigint NOT NULL DEFAULT 1,
  attempts integer NOT NULL DEFAULT 0,
  blocked boolean NOT NULL DEFAULT false,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

### hubspot_tenant_links

Source: [migrations/010_hubspot_crm.sql:12](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/010_hubspot_crm.sql#L12).

```sql
CREATE TABLE IF NOT EXISTS public.hubspot_tenant_links (
  tenant_id uuid PRIMARY KEY REFERENCES public.tenants(tenant_id) ON DELETE CASCADE,
  company_id text NOT NULL UNIQUE,
  upsell_deal_id text,
  last_synced_at timestamptz NOT NULL DEFAULT now()
);
```

### individual_pricing_events

Source: [migrations/040_workspace_personas.sql:21](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/040_workspace_personas.sql#L21).

```sql
CREATE TABLE IF NOT EXISTS public.individual_pricing_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),request_id uuid NOT NULL,
 previous_percent numeric(5,2) NOT NULL,new_percent numeric(5,2) NOT NULL,
 previous_version integer NOT NULL,version integer NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(actor_auth_user_id,request_id)
);
```

### individual_pricing_settings

Source: [migrations/040_workspace_personas.sql:14](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/040_workspace_personas.sql#L14).

```sql
CREATE TABLE IF NOT EXISTS public.individual_pricing_settings (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 individual_global_markup_percent numeric(5,2) NOT NULL DEFAULT 20.00 CHECK(individual_global_markup_percent>=0),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 updated_by uuid REFERENCES auth.users(id),updated_at timestamptz NOT NULL DEFAULT now()
);
```

### insurance_claim_cases

Source: [migrations/033_xcover_claim_cases.sql:44](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/033_xcover_claim_cases.sql#L44).

```sql
CREATE TABLE IF NOT EXISTS public.insurance_claim_cases (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, shipment_id uuid NOT NULL,
 policy_id text NOT NULL CHECK(length(policy_id) BETWEEN 1 AND 150),
 reason text NOT NULL CHECK(reason IN ('PARCEL_LOST','PARCEL_DAMAGED')),
 state text NOT NULL DEFAULT 'CLAIM_INGESTED' CHECK(state IN ('CLAIM_INGESTED','SUBMISSION_PENDING','SUBMISSION_SUBMITTED','INSURER_SUBMITTED','UNDER_INSURER_REVIEW','ACTION_REQUIRED','DECLINED','CLOSED','INSURER_PAYMENT_REPORTED','RECONCILIATION_REQUIRED','REFUND_APPROVED_AND_CREDITED')),
 submission_payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(submission_payload)='object'),
 upstream_claim_id uuid,upstream_claim_reference text,insurer_status text,last_error_code text,
 updated_at timestamptz NOT NULL DEFAULT now(),
 notes text NOT NULL CHECK(length(notes) BETWEEN 10 AND 2000),
 created_by uuid NOT NULL REFERENCES auth.users(id),
 payload_sha256 text NOT NULL CHECK(payload_sha256 ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### insurance_claim_evidence

Source: [migrations/033_xcover_claim_cases.sql:91](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/033_xcover_claim_cases.sql#L91).

```sql
CREATE TABLE IF NOT EXISTS public.insurance_claim_evidence (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, case_id uuid NOT NULL,
 content_type text NOT NULL CHECK(content_type IN ('image/jpeg','image/png')),
 content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[a-f0-9]{64}$'),
 content bytea NOT NULL CHECK(octet_length(content) BETWEEN 1 AND 5000000),
 upstream_file_id uuid,upload_state text NOT NULL DEFAULT 'PENDING' CHECK(upload_state IN ('PENDING','SUBMITTED','CONFIRMED')),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,case_id) REFERENCES public.insurance_claim_cases(tenant_id,id)
);
```

### insurance_purchases

Source: [migrations/033_xcover_claim_cases.sql:5](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/033_xcover_claim_cases.sql#L5).

```sql
CREATE TABLE IF NOT EXISTS public.insurance_purchases (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,offer_id uuid NOT NULL,
 declared_value numeric(12,2) NOT NULL CHECK(declared_value>0 AND declared_value<=5000),
 premium numeric(12,2),tax_amount numeric(12,2),total_charge numeric(12,2),reported_commission numeric(12,2),
 package_id text,quote_id uuid,terms_url text,
 state text NOT NULL CHECK(state IN ('QUOTE_PENDING','QUOTED','RESERVED','POLICY_SUBMITTED','INSURED','FAILED','RECONCILIATION_REQUIRED')),
 requested_by uuid NOT NULL REFERENCES auth.users(id),expires_at timestamptz NOT NULL,
 terms_accepted_at timestamptz,terms_accepted_by uuid REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,id),UNIQUE(tenant_id,shipment_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK(state IN ('QUOTE_PENDING','RECONCILIATION_REQUIRED') OR
  (premium IS NOT NULL AND tax_amount IS NOT NULL AND total_charge IS NOT NULL AND
  premium>=1.20 AND tax_amount>=0 AND total_charge=premium+tax_amount AND package_id IS NOT NULL AND quote_id IS NOT NULL AND terms_url IS NOT NULL)),
 CHECK(reported_commission IS NULL OR (reported_commission>=0 AND reported_commission<=premium))
);
```

### insurance_settlements

Source: [migrations/033_xcover_claim_cases.sql:62](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/033_xcover_claim_cases.sql#L62).

```sql
CREATE TABLE IF NOT EXISTS public.insurance_settlements (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,case_id uuid NOT NULL,shipment_id uuid NOT NULL,
 approved_amount numeric(12,2) NOT NULL CHECK(approved_amount>0 AND approved_amount<=5000),
 currency text NOT NULL CHECK(currency='GBP'),insurer_payment_reference text NOT NULL UNIQUE CHECK(length(insurer_payment_reference) BETWEEN 5 AND 150),
 received_at timestamptz NOT NULL,verified_by uuid REFERENCES auth.users(id),
 verification_source text NOT NULL DEFAULT 'PLATFORM_OPERATOR' CHECK(verification_source IN ('PLATFORM_OPERATOR','XCLAIM_API')),
 provider_response_sha256 text,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,id),UNIQUE(tenant_id,case_id),
 FOREIGN KEY(tenant_id,case_id) REFERENCES public.insurance_claim_cases(tenant_id,id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK((verification_source='PLATFORM_OPERATOR' AND verified_by IS NOT NULL)
  OR (verification_source='XCLAIM_API' AND provider_response_sha256 ~ '^[a-f0-9]{64}$' AND provider_response_sha256 IS NOT NULL))
);
```

### insurance_webhook_receipts

Source: [migrations/033_xcover_claim_cases.sql:108](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/033_xcover_claim_cases.sql#L108).

```sql
CREATE TABLE IF NOT EXISTS public.insurance_webhook_receipts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, shipment_id uuid NOT NULL,
 policy_id text NOT NULL CHECK(length(policy_id) BETWEEN 1 AND 150),
 body_sha256 text NOT NULL CHECK(body_sha256 ~ '^[a-f0-9]{64}$'),
 event text NOT NULL CHECK(event IN ('BOOKING_CREATED','BOOKING_UPDATED','BOOKING_CANCELLED')),
 verified_status text NOT NULL CHECK(verified_status IN ('CONFIRMED','CANCELLED')),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,body_sha256),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### logistics_media_assets

Source: [migrations/044_carrier_manifests_and_media.sql:160](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/044_carrier_manifests_and_media.sql#L160).

```sql
CREATE TABLE public.logistics_media_assets (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),shipment_id uuid NOT NULL,
 object_key text NOT NULL,content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[a-f0-9]{64}$'),
 mime_type text NOT NULL CHECK(mime_type IN ('image/png','image/jpeg')),
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,shipment_id,content_sha256),
 CHECK(object_key LIKE tenant_id::text||'/'||shipment_id::text||'/%'),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### partner_cancellations

Source: [migrations/023_partner_lifecycle.sql:35](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/023_partner_lifecycle.sql#L35).

```sql
CREATE TABLE IF NOT EXISTS public.partner_cancellations(
 tenant_id uuid NOT NULL,
 shipment_id uuid NOT NULL,
 state text NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','CREDITED')),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,shipment_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### partner_order_jobs

Source: [migrations/024_native_partner_orders_and_webhooks.sql:17](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/024_native_partner_orders_and_webhooks.sql#L17).

```sql
CREATE TABLE IF NOT EXISTS public.partner_order_jobs(
 tenant_id uuid NOT NULL,
 shipment_id uuid NOT NULL,
 carrier_account_id uuid NOT NULL,
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
 state text NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','SENDING','SYNCED','FAILED','RECONCILIATION_REQUIRED','SUPERSEDED')),
 remote_object_id text,
 remote_object_type text,
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 last_error text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,shipment_id,carrier_account_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 FOREIGN KEY(tenant_id,carrier_account_id) REFERENCES public.carrier_accounts(tenant_id,id)
);
```

### partner_provider_options

Source: [migrations/024_native_partner_orders_and_webhooks.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/024_native_partner_orders_and_webhooks.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.partner_provider_options(
 platform_connection_id uuid PRIMARY KEY REFERENCES public.platform_carrier_connections(id),
 order_sync_enabled boolean NOT NULL DEFAULT false,
 sendcloud_integration_id bigint CHECK(sendcloud_integration_id>0),
 webhook_enabled boolean NOT NULL DEFAULT false,
 webhook_auth text NOT NULL DEFAULT 'HMAC' CHECK(webhook_auth IN ('HMAC','URL_TOKEN')),
 webhook_secret bytea,
 credential_key_id text,
 pod_allowed_hosts jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(pod_allowed_hosts)='array'),
 sendcloud_status_map jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(sendcloud_status_map)='object'),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(NOT webhook_enabled OR (webhook_secret IS NOT NULL AND credential_key_id IS NOT NULL))
);
```

### partner_shipping_offers

Source: [migrations/023_partner_lifecycle.sql:17](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/023_partner_lifecycle.sql#L17).

```sql
CREATE TABLE IF NOT EXISTS public.partner_shipping_offers(
 tenant_id uuid NOT NULL,
 offer_id uuid NOT NULL,
 shipment_id uuid NOT NULL,
 rate_snapshot jsonb NOT NULL CHECK(jsonb_typeof(rate_snapshot)='object'),
 expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,offer_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### partner_unbound_quotes

Source: [migrations/023_partner_lifecycle.sql:5](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/023_partner_lifecycle.sql#L5).

```sql
CREATE TABLE IF NOT EXISTS public.partner_unbound_quotes(
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 request_id uuid NOT NULL,
 request_payload jsonb NOT NULL CHECK(jsonb_typeof(request_payload)='object'),
 quote_payload jsonb NOT NULL CHECK(jsonb_typeof(quote_payload)='object'),
 expires_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,request_id)
);
```

### payment_carts

Source: [migrations/030_card_checkout.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/030_card_checkout.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.payment_carts(
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 requested_by uuid NOT NULL REFERENCES auth.users(id),
 offers jsonb NOT NULL CHECK(jsonb_typeof(offers)='array' AND jsonb_array_length(offers) BETWEEN 1 AND 100),
 amount numeric(14,2) NOT NULL CHECK(amount>=1 AND amount<=10000),currency text NOT NULL CHECK(currency IN ('GBP','EUR','USD')),
 status text NOT NULL DEFAULT 'CREATING' CHECK(status IN ('CREATING','AWAITING_PAYMENT','BOOKING','COMPLETED','REVIEW_REQUIRED')),
 results jsonb,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now()
);
```

### platform_carrier_connections

Source: [migrations/020_platform_carriers.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/020_platform_carriers.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.platform_carrier_connections(
 id uuid PRIMARY KEY, account_name text NOT NULL, aggregator text NOT NULL CHECK(aggregator IN ('EASYPOST','REGIONAL')),
 regional_provider_code text, api_base_url text NOT NULL, upstream_account_id text,
 environment text NOT NULL CHECK(environment IN ('TEST','LIVE')),
 credentials_ciphertext bytea NOT NULL, credential_key_id text NOT NULL,
 priority integer NOT NULL CHECK(priority BETWEEN 0 AND 1000000),
 timeout_seconds integer NOT NULL CHECK(timeout_seconds BETWEEN 1 AND 120),
 is_active boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now()
);
```

### platform_carrier_events

Source: [migrations/020_platform_carriers.sql:18](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/020_platform_carriers.sql#L18).

```sql
CREATE TABLE IF NOT EXISTS public.platform_carrier_events(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 connection_id uuid NOT NULL REFERENCES public.platform_carrier_connections(id),
 action text NOT NULL CHECK(action IN ('SAVE','RETIRE')), snapshot jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
```

### reverse_logistics_requests

Source: [migrations/042_headless_returns.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/042_headless_returns.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.reverse_logistics_requests (
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 id uuid NOT NULL,
 original_shipment_id uuid NOT NULL,
 requested_by uuid NOT NULL REFERENCES auth.users(id),
 source text NOT NULL CHECK(source IN ('API','WEB_CHAT','WHATSAPP','STOREFRONT','MARKETPLACE')),
 charge_bearer text NOT NULL CHECK(charge_bearer IN ('RETAILER_PAY','CUSTOMER_PAY')),
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 state text NOT NULL DEFAULT 'PROCESSING' CHECK(state IN ('PROCESSING','BOOKED','PAYMENT_REQUIRED','REVIEW_REQUIRED')),
 return_shipment_id uuid,
 response jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(response)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,original_shipment_id),
 FOREIGN KEY(tenant_id,original_shipment_id) REFERENCES public.shipments(tenant_id,id),
 FOREIGN KEY(tenant_id,return_shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### shipment_dispute_drafts

Source: [migrations/027_workspace_invitations_and_disputes.sql:14](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/027_workspace_invitations_and_disputes.sql#L14).

```sql
CREATE TABLE IF NOT EXISTS public.shipment_dispute_drafts(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,
 content text NOT NULL CHECK(length(content) BETWEEN 10 AND 12000),updated_by uuid NOT NULL REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,shipment_id),FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### shipment_goods_items

Source: [migrations/035_packages_goods_returns_and_credential_locks.sql:80](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/035_packages_goods_returns_and_credential_locks.sql#L80).

```sql
CREATE TABLE IF NOT EXISTS public.shipment_goods_items (
 tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,item_index integer NOT NULL CHECK(item_index BETWEEN 1 AND 1000),
 package_index integer CHECK(package_index BETWEEN 1 AND 100),
 description text NOT NULL CHECK(length(btrim(description)) BETWEEN 1 AND 500),
 quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 100000),
 unit_weight_kg numeric(12,3) NOT NULL CHECK(unit_weight_kg>0 AND unit_weight_kg<=30000),
 unit_value numeric(14,2) NOT NULL CHECK(unit_value>=0 AND unit_value<=999999999999.99),currency text NOT NULL CHECK(currency IN ('GBP','EUR','USD')),
 sku text CHECK(length(sku)<=200),hs_code text CHECK(hs_code ~ '^([0-9]{6}|[0-9]{8}|[0-9]{10})$'),
 origin_country text NOT NULL CHECK(origin_country ~ '^[A-Z]{2}$'),
 total_net_weight_kg numeric(18,3) GENERATED ALWAYS AS (quantity*unit_weight_kg) STORED,
 total_value numeric(20,2) GENERATED ALWAYS AS (quantity*unit_value) STORED,
 PRIMARY KEY(tenant_id,shipment_id,item_index),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### stripe_charge_refunds

Source: [migrations/019_stripe_snapshot_reconciliation.sql:55](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/019_stripe_snapshot_reconciliation.sql#L55).

```sql
CREATE TABLE IF NOT EXISTS public.stripe_charge_refunds (
  charge_id text PRIMARY KEY CHECK(charge_id ~ '^ch_'),
  tenant_id uuid NOT NULL,
  topup_id uuid NOT NULL,
  payment_intent_id text NOT NULL,
  applied_refund_minor bigint NOT NULL DEFAULT 0 CHECK(applied_refund_minor>=0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(tenant_id,topup_id) REFERENCES public.wallet_topups(tenant_id,id)
);
```

### stripe_webhook_events

Source: [migrations/019_stripe_snapshot_reconciliation.sql:34](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/019_stripe_snapshot_reconciliation.sql#L34).

```sql
CREATE TABLE IF NOT EXISTS public.stripe_webhook_events (
  event_id text PRIMARY KEY CHECK(event_id ~ '^evt_'),
  event_type text NOT NULL CHECK(event_type IN ('checkout.session.completed','charge.refunded','charge.failed')),
  api_version text,
  livemode boolean NOT NULL,
  payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
  payload_sha256 text NOT NULL,
  status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','DONE','RECONCILIATION_REQUIRED')),
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error text,
  result jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
```

### support_message_outbox

Source: [migrations/011_tracking_and_support.sql:57](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/011_tracking_and_support.sql#L57).

```sql
CREATE TABLE IF NOT EXISTS public.support_message_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, ticket_id uuid NOT NULL,
  recipient_e164 text NOT NULL, body text NOT NULL,
  channel text NOT NULL DEFAULT 'TWILIO_WHATSAPP',
  status text NOT NULL DEFAULT 'STAGED' CHECK(status IN ('STAGED','SENT','FAILED','CANCELLED')),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,ticket_id,recipient_e164),
  FOREIGN KEY(tenant_id,ticket_id) REFERENCES public.support_tickets(tenant_id,id)
);
```

### support_ticket_activity

Source: [migrations/026_support_review_activity.sql:6](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/026_support_review_activity.sql#L6).

```sql
CREATE TABLE IF NOT EXISTS public.support_ticket_activity (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id uuid NOT NULL,
 ticket_id uuid NOT NULL,
 actor_auth_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
 actor_name text NOT NULL CHECK(length(actor_name)<=200),
 activity_type text NOT NULL CHECK(activity_type IN ('INTERNAL_NOTE','INTERNAL_REVIEW','RESOLVED')),
 note text NOT NULL DEFAULT '' CHECK(length(note)<=2000),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,ticket_id) REFERENCES public.support_tickets(tenant_id,id)
);
```

### support_tickets

Source: [migrations/011_tracking_and_support.sql:48](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/011_tracking_and_support.sql#L48).

```sql
CREATE TABLE IF NOT EXISTS public.support_tickets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, shipment_id uuid NOT NULL,
  tracking_event_id uuid NOT NULL UNIQUE,
  status text NOT NULL CHECK(status IN ('OPEN','RESOLVED')),
  ai_summary text NOT NULL, ai_method text NOT NULL, prompt_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,id),
  FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
  FOREIGN KEY(tenant_id,tracking_event_id) REFERENCES public.tracking_events(tenant_id,id)
);
```

### tenant_catalog_addresses

Source: [migrations/036_tenant_catalogs.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/036_tenant_catalogs.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.tenant_catalog_addresses (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 label text NOT NULL CHECK(length(btrim(label)) BETWEEN 1 AND 100),
 address_role text NOT NULL CHECK(address_role IN ('SENDER','RETURN','PICKUP','INVOICE')),
 address jsonb NOT NULL CHECK(jsonb_typeof(address)='object' AND address ?& ARRAY['name','line1','city','postal_code','country_code']),
 is_default boolean NOT NULL DEFAULT false,version integer NOT NULL DEFAULT 1 CHECK(version>0),
 created_by uuid NOT NULL REFERENCES auth.users(id),updated_by uuid NOT NULL REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),archived_at timestamptz,
 UNIQUE(tenant_id,id),CHECK(archived_at IS NULL OR NOT is_default)
);
```

### tenant_catalog_contacts

Source: [migrations/036_tenant_catalogs.sql:17](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/036_tenant_catalogs.sql#L17).

```sql
CREATE TABLE IF NOT EXISTS public.tenant_catalog_contacts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 label text NOT NULL CHECK(length(btrim(label)) BETWEEN 1 AND 100),
 address jsonb NOT NULL CHECK(jsonb_typeof(address)='object' AND address ?& ARRAY['name','line1','city','postal_code','country_code']),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),created_by uuid NOT NULL REFERENCES auth.users(id),updated_by uuid NOT NULL REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),archived_at timestamptz,
 UNIQUE(tenant_id,id)
);
```

### tenant_catalog_products

Source: [migrations/036_tenant_catalogs.sql:26](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/036_tenant_catalogs.sql#L26).

```sql
CREATE TABLE IF NOT EXISTS public.tenant_catalog_products (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 sku text NOT NULL CHECK(length(btrim(sku)) BETWEEN 1 AND 200),description text NOT NULL CHECK(length(btrim(description)) BETWEEN 3 AND 500),
 unit_weight_kg numeric(12,3) NOT NULL CHECK(unit_weight_kg>0 AND unit_weight_kg<=30000),
 unit_value numeric(14,2) NOT NULL CHECK(unit_value>0 AND unit_value<=1000000),currency text NOT NULL CHECK(currency IN ('GBP','EUR','USD')),
 hs_code text CHECK(hs_code ~ '^([0-9]{6}|[0-9]{8}|[0-9]{10})$'),origin_country text NOT NULL CHECK(origin_country ~ '^[A-Z]{2}$'),
 hs_reviewed_at timestamptz,hs_reviewed_by uuid REFERENCES auth.users(id),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),created_by uuid NOT NULL REFERENCES auth.users(id),updated_by uuid NOT NULL REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),archived_at timestamptz,
 UNIQUE(tenant_id,id),CHECK((hs_reviewed_at IS NULL AND hs_reviewed_by IS NULL) OR
 (hs_reviewed_at IS NOT NULL AND hs_reviewed_by IS NOT NULL AND hs_code IS NOT NULL))
);
```

### tracking_case_reviews

Source: [migrations/045_unified_tracking.sql:103](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/045_unified_tracking.sql#L103).

```sql
CREATE TABLE public.tracking_case_reviews (
 tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,
 state text NOT NULL CHECK(state IN ('ACKNOWLEDGED','IN_REVIEW','ESCALATED','RESOLVED')),
 assigned_to uuid REFERENCES auth.users(id),note text NOT NULL CHECK(length(note) BETWEEN 1 AND 1000),
 updated_by uuid NOT NULL REFERENCES auth.users(id),updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,shipment_id),FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### tracking_customer_requests

Source: [migrations/045_unified_tracking.sql:57](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/045_unified_tracking.sql#L57).

```sql
CREATE TABLE public.tracking_customer_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,
 share_link_id uuid NOT NULL,request_id uuid NOT NULL,
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 note text NOT NULL CHECK(length(note) BETWEEN 10 AND 1000),
 state text NOT NULL DEFAULT 'OPEN' CHECK(state IN ('OPEN','ACKNOWLEDGED')),
 created_at timestamptz NOT NULL DEFAULT now(),acknowledged_at timestamptz,
 UNIQUE(share_link_id,request_id),FOREIGN KEY(tenant_id,share_link_id) REFERENCES public.tracking_share_links(tenant_id,id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### tracking_events

Source: [migrations/011_tracking_and_support.sql:31](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/011_tracking_and_support.sql#L31).

```sql
CREATE TABLE IF NOT EXISTS public.tracking_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL,
  shipment_id uuid NOT NULL,
  integration_key_id text NOT NULL,
  event_id text NOT NULL,
  body_sha256 text NOT NULL,
  status text NOT NULL CHECK(status IN ('IN_TRANSIT','DELIVERED','EXCEPTION')),
  occurred_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  raw_error text NOT NULL DEFAULT '',
  response jsonb NOT NULL,
  support_pending boolean NOT NULL DEFAULT false,
  UNIQUE(tenant_id,integration_key_id,event_id),
  UNIQUE(tenant_id,id),
  FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### tracking_notifications

Source: [migrations/045_unified_tracking.sql:77](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/045_unified_tracking.sql#L77).

```sql
CREATE TABLE public.tracking_notifications (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
 shipment_id uuid NOT NULL, tracking_event_id uuid NOT NULL,
 event_sha256 text NOT NULL CHECK(event_sha256 ~ '^[a-f0-9]{64}$'),
 category text NOT NULL, channel text NOT NULL DEFAULT 'IN_APP' CHECK(channel='IN_APP'),
 state text NOT NULL DEFAULT 'READY' CHECK(state='READY'),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,id),UNIQUE(tenant_id,event_sha256),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 FOREIGN KEY(tenant_id,tracking_event_id) REFERENCES public.tracking_events(tenant_id,id)
);
```

### tracking_operations_audit

Source: [migrations/045_unified_tracking.sql:110](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/045_unified_tracking.sql#L110).

```sql
CREATE TABLE public.tracking_operations_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,tenant_id uuid REFERENCES public.tenants(tenant_id),
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),shipment_id uuid,
 action text NOT NULL CHECK(action IN ('SEARCH','DETAIL','SHARE','REVOKE','REFRESH','RETRY','REVIEW','PREFERENCES')),
 detail jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(detail)='object'),created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
```

### tracking_preferences

Source: [migrations/045_unified_tracking.sql:68](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/045_unified_tracking.sql#L68).

```sql
CREATE TABLE public.tracking_preferences (
 tenant_id uuid PRIMARY KEY REFERENCES public.tenants(tenant_id),
 in_app_enabled boolean NOT NULL DEFAULT true,
 categories text[] NOT NULL DEFAULT ARRAY['IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','RETURNED_TO_SENDER'],
 stale_hours integer NOT NULL DEFAULT 48 CHECK(stale_hours BETWEEN 12 AND 720),
 poll_interval_minutes integer NOT NULL DEFAULT 360 CHECK(poll_interval_minutes BETWEEN 60 AND 1440),
 updated_by uuid REFERENCES auth.users(id),updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(categories <@ ARRAY['IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','RETURNED_TO_SENDER','AVAILABLE_FOR_PICKUP'])
);
```

### tracking_provider_limits

Source: [migrations/045_unified_tracking.sql:99](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/045_unified_tracking.sql#L99).

```sql
CREATE TABLE public.tracking_provider_limits (
 carrier_account_id uuid PRIMARY KEY REFERENCES public.carrier_accounts(id),
 next_allowed_at timestamptz NOT NULL
);
```

### tracking_refresh_jobs

Source: [migrations/045_unified_tracking.sql:88](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/045_unified_tracking.sql#L88).

```sql
CREATE TABLE public.tracking_refresh_jobs (
 tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,requested_by uuid NOT NULL REFERENCES auth.users(id),
 state text NOT NULL DEFAULT 'DUE' CHECK(state IN ('DUE','RUNNING','COMPLETE','DEAD','UNSUPPORTED')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 next_attempt_at timestamptz NOT NULL DEFAULT now(),lease_token uuid,lease_until timestamptz,
 last_attempt_at timestamptz,last_success_at timestamptz,error_code text,
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,shipment_id),FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK((state='RUNNING')=(lease_token IS NOT NULL AND lease_until IS NOT NULL))
);
```

### tracking_share_links

Source: [migrations/045_unified_tracking.sql:30](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/045_unified_tracking.sql#L30).

```sql
CREATE TABLE public.tracking_share_links (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 anchor_shipment_id uuid NOT NULL, shipment_ids uuid[] NOT NULL CHECK(cardinality(shipment_ids) BETWEEN 1 AND 100),
 token_sha256 text NOT NULL UNIQUE CHECK(token_sha256 ~ '^[a-f0-9]{64}$'),
 created_by uuid NOT NULL REFERENCES auth.users(id), created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL CHECK(expires_at>created_at AND expires_at<=created_at+interval '30 days'),
 revoked_at timestamptz, UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,anchor_shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK(anchor_shipment_id=ANY(shipment_ids))
);
```

### web_registration_sessions

Source: [migrations/040_workspace_personas.sql:31](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/040_workspace_personas.sql#L31).

```sql
CREATE TABLE IF NOT EXISTS public.web_registration_sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),secret_sha256 text NOT NULL CHECK(secret_sha256 ~ '^[a-f0-9]{64}$'),
 email_address text NOT NULL,workspace_type text NOT NULL CHECK(workspace_type IN ('BUSINESS','INDIVIDUAL')),
 profile jsonb NOT NULL CHECK(jsonb_typeof(profile)='object'),
 state text NOT NULL CHECK(state IN ('SENDING_EMAIL','PENDING_OTP','PROVISIONING','VERIFIED','RECONCILIATION_REQUIRED')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 tenant_id uuid NOT NULL DEFAULT gen_random_uuid(),auth_user_id uuid REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT now()+interval '15 minutes'
);
```

### whatsapp_inbound_queue

Source: [migrations/043_whatsapp_async_ingress.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/043_whatsapp_async_ingress.sql#L4).

```sql
CREATE TABLE public.whatsapp_inbound_queue (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 message_sid text NOT NULL UNIQUE CHECK(message_sid ~ '^SM[0-9a-fA-F]{32}$'),
 sender_e164 text NOT NULL CHECK(sender_e164 ~ '^\+[1-9][0-9]{7,14}$'),
 receiver_e164 text NOT NULL CHECK(receiver_e164 ~ '^\+[1-9][0-9]{7,14}$'),
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 payload_ciphertext bytea NOT NULL, key_id text NOT NULL,
 state text NOT NULL DEFAULT 'STAGED' CHECK(state IN ('STAGED','PROCESSING','READY','ACCEPTED','FAILED','REVIEW_REQUIRED')),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 error_code text
);
```

### whatsapp_registration_queue

Source: [migrations/039_whatsapp_onboarding.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/039_whatsapp_onboarding.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.whatsapp_registration_queue (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 phone_e164 text NOT NULL CHECK(phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
 receiver_e164 text NOT NULL CHECK(receiver_e164 ~ '^\+[1-9][0-9]{7,14}$'),
 current_state text NOT NULL CHECK(current_state IN
 ('PENDING_COMPANY','PENDING_PROFILE','PENDING_EMAIL','SENDING_EMAIL','PENDING_OTP','PROVISIONING','VERIFIED','LOCKED','EXPIRED','CANCELLED','RECONCILIATION_REQUIRED')),
 company_name text CHECK(length(company_name) BETWEEN 1 AND 200),
 company_reg_number text CHECK(company_reg_number ~ '^[A-Z0-9]{2,100}$'),
 country_code text CHECK(country_code ~ '^[A-Z]{2}$'),
 profile jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(profile)='object'),
 email_address text CHECK(length(email_address)<=254 AND email_address ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'),
 phone_otp_hmac text CHECK(phone_otp_hmac ~ '^[a-f0-9]{64}$'),
 otp_expires_at timestamptz, attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 send_attempts integer NOT NULL DEFAULT 0 CHECK(send_attempts BETWEEN 0 AND 3),
 last_sent_at timestamptz, auth_user_id uuid REFERENCES auth.users(id),
 tenant_id uuid NOT NULL DEFAULT gen_random_uuid(), member_id uuid NOT NULL DEFAULT gen_random_uuid(),
 busy_message_sid text, lease_until timestamptz,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '30 minutes',
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(expires_at>created_at)
);
```

### whatsapp_registration_receipts

Source: [migrations/039_whatsapp_onboarding.sql:31](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/039_whatsapp_onboarding.sql#L31).

```sql
CREATE TABLE IF NOT EXISTS public.whatsapp_registration_receipts (
 message_sid text PRIMARY KEY CHECK(message_sid ~ '^SM[0-9a-fA-F]{32}$'),
 phone_e164 text NOT NULL,receiver_e164 text NOT NULL,
 input_hmac text NOT NULL CHECK(input_hmac ~ '^[a-f0-9]{64}$'),
 reply_ciphertext bytea, key_id text,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK((reply_ciphertext IS NULL)=(key_id IS NULL))
);
```

### whatsapp_reply_outbox

Source: [migrations/043_whatsapp_async_ingress.sql:18](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/043_whatsapp_async_ingress.sql#L18).

```sql
CREATE TABLE public.whatsapp_reply_outbox (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 inbound_id bigint NOT NULL REFERENCES public.whatsapp_inbound_queue(id),
 part_index integer NOT NULL CHECK(part_index>=0),
 payload_ciphertext bytea NOT NULL, key_id text NOT NULL,
 state text NOT NULL DEFAULT 'STAGED' CHECK(state IN ('STAGED','SENDING','ACCEPTED','FAILED','REVIEW_REQUIRED')),
 provider_message_sid text UNIQUE CHECK(provider_message_sid ~ '^SM[0-9a-fA-F]{32}$'),
 updated_at timestamptz NOT NULL DEFAULT now(), error_code text,
 UNIQUE(inbound_id,part_index)
);
```

### workspace_dispatch_events

Source: [migrations/032_dispatch_events_and_invoice_audits.sql:44](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/032_dispatch_events_and_invoice_audits.sql#L44).

```sql
CREATE TABLE IF NOT EXISTS public.workspace_dispatch_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 shipment_id uuid NOT NULL,
 status text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
```

### workspace_invitations

Source: [migrations/027_workspace_invitations_and_disputes.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/027_workspace_invitations_and_disputes.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.workspace_invitations(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 email text NOT NULL CHECK(length(email)<=254),first_name text NOT NULL CHECK(length(first_name) BETWEEN 1 AND 100),
 last_name text NOT NULL CHECK(length(last_name) BETWEEN 1 AND 100),role text NOT NULL CHECK(role IN ('DISPATCHER','ACCOUNTANT')),
 invited_by uuid NOT NULL REFERENCES auth.users(id),auth_user_id uuid REFERENCES auth.users(id),
 status text NOT NULL DEFAULT 'SENDING' CHECK(status IN ('SENDING','PENDING','FAILED','ACCEPTED','CANCELLED')),
 created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT now()+interval '24 hours',accepted_at timestamptz
);
```

### workspace_store_connections

Source: [migrations/031_store_connections.sql:4](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/031_store_connections.sql#L4).

```sql
CREATE TABLE IF NOT EXISTS public.workspace_store_connections (
 tenant_id uuid NOT NULL,
 store_id uuid NOT NULL,
 credentials_ciphertext bytea NOT NULL,
 credential_key_id text NOT NULL,
 updated_by uuid NOT NULL REFERENCES auth.users(id),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,store_id),
 FOREIGN KEY(tenant_id,store_id) REFERENCES public.ecommerce_stores(tenant_id,id)
);
```

### xclaim_webhook_receipts

Source: [migrations/033_xcover_claim_cases.sql:101](https://github.com/sync4ai-lab/veloce.ai/blob/f765127ce4203eb2333c2f834fa6af183a3d674a/migrations/033_xcover_claim_cases.sql#L101).

```sql
CREATE TABLE IF NOT EXISTS public.xclaim_webhook_receipts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,case_id uuid NOT NULL,
 body_sha256 text NOT NULL CHECK(body_sha256 ~ '^[a-f0-9]{64}$'),
 event text NOT NULL CHECK(event IN ('claim.status-update','claim.status-category-update','claim.deleted')),
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,body_sha256),
 FOREIGN KEY(tenant_id,case_id) REFERENCES public.insurance_claim_cases(tenant_id,id)
);
```
