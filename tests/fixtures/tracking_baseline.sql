-- Synthetic, disposable pre-043 schema. No production data or credentials.
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA auth;
CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE TABLE public.tenants(tenant_id uuid PRIMARY KEY,company_name text NOT NULL,workspace_status text NOT NULL DEFAULT 'ACTIVE');
CREATE TABLE public.users(id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants,
 auth_user_id uuid NOT NULL REFERENCES auth.users,role text NOT NULL,is_active boolean NOT NULL DEFAULT true,UNIQUE(tenant_id,id));
CREATE TABLE public.carrier_accounts(id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants,
 aggregator text NOT NULL DEFAULT 'EASYPOST',api_base_url text NOT NULL DEFAULT 'https://api.easypost.com/v2',
 environment text NOT NULL DEFAULT 'TEST',is_active boolean NOT NULL DEFAULT true,UNIQUE(tenant_id,id));
CREATE TABLE public.shipments(id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants,
 carrier_account_id uuid NOT NULL REFERENCES public.carrier_accounts,customer_reference text,store_order_id text,ecommerce_store_id uuid,
 tracking_number text,carrier_code text,upstream_shipment_id text,status text NOT NULL DEFAULT 'BOOKED'
 CHECK(status IN ('BOOKED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED','CANCELLED','FAILED')),
 last_tracking_event_at timestamptz,booked_at timestamptz DEFAULT now(),created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),created_by_user_id uuid,
 origin_country text DEFAULT 'GB',destination_country text DEFAULT 'GB',parcel_count integer NOT NULL DEFAULT 1,
 tracking_lifecycle_type text NOT NULL DEFAULT 'FORWARD_SHIPMENT',store_return_status text NOT NULL DEFAULT 'NONE',
 return_of_shipment_id uuid,logistics_metadata jsonb NOT NULL DEFAULT '{}',delivered_at timestamptz,proof_of_delivery_url text,
 UNIQUE(tenant_id,id),FOREIGN KEY(tenant_id,return_of_shipment_id) REFERENCES public.shipments(tenant_id,id));
CREATE TABLE public.tracking_events(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,
 integration_key_id text NOT NULL,event_id text NOT NULL,body_sha256 text NOT NULL,status text NOT NULL CHECK(status IN ('IN_TRANSIT','DELIVERED','EXCEPTION')),
 occurred_at timestamptz NOT NULL,received_at timestamptz NOT NULL DEFAULT now(),raw_error text NOT NULL DEFAULT '',
 response jsonb NOT NULL,support_pending boolean NOT NULL DEFAULT false,UNIQUE(tenant_id,id),UNIQUE(tenant_id,integration_key_id,event_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id));
CREATE TABLE public.ecommerce_tracking_outbox(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,
 shipment_id uuid,store_return_reference text);
CREATE TABLE public.support_tickets(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid,shipment_id uuid,
 tracking_event_id uuid,status text,archived_at timestamptz);
CREATE TABLE public.support_ticket_activity(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid,ticket_id uuid,
 actor_name text,activity_type text,note text);
CREATE TABLE public.support_message_outbox(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid,ticket_id uuid,status text);
