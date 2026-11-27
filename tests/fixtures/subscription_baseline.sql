-- Minimal pre-050 schema for disposable, synthetic PostgreSQL tests only.
CREATE ROLE anon;CREATE ROLE authenticated;CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA auth;CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE TABLE public.tenants(tenant_id uuid PRIMARY KEY,company_name text NOT NULL DEFAULT 'Synthetic workspace',
 is_sandbox boolean NOT NULL DEFAULT false,workspace_type text NOT NULL DEFAULT 'BUSINESS',workspace_status text NOT NULL DEFAULT 'ACTIVE',
 billing_plan text NOT NULL DEFAULT 'PREPAID_WALLET',default_currency text NOT NULL DEFAULT 'GBP',stripe_customer_id text,billing_email text);
CREATE TABLE public.users(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants,
 auth_user_id uuid NOT NULL REFERENCES auth.users,role text NOT NULL DEFAULT 'OWNER',is_active boolean NOT NULL DEFAULT true);
CREATE TABLE public.workspace_invitations(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants,
 auth_user_id uuid,email text,status text NOT NULL DEFAULT 'SENDING',expires_at timestamptz NOT NULL DEFAULT now()+interval '24 hours');
CREATE TABLE public.ecommerce_stores(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants,is_active boolean NOT NULL DEFAULT true);
CREATE TABLE public.web_registration_sessions(id uuid PRIMARY KEY DEFAULT gen_random_uuid());
CREATE TABLE public.margin_rules(id uuid PRIMARY KEY,rule_name text NOT NULL UNIQUE,tenant_id uuid NOT NULL REFERENCES public.tenants,currency text NOT NULL,
 markup_type text NOT NULL,markup_value numeric(18,2) NOT NULL,priority integer NOT NULL,is_active boolean NOT NULL DEFAULT true,valid_from timestamptz NOT NULL);
CREATE TABLE public.admin_configuration_events(id uuid PRIMARY KEY,actor_auth_user_id uuid NOT NULL,
 operation text NOT NULL CHECK(operation IN ('CREATE_TENANT','CREATE_MARGIN')),request_id uuid NOT NULL,tenant_id uuid NOT NULL,
 payload_sha256 text NOT NULL,response jsonb NOT NULL,UNIQUE(actor_auth_user_id,operation,request_id));
CREATE TABLE public.carrier_accounts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants,is_active boolean NOT NULL DEFAULT true,platform_connection_id uuid);
CREATE TABLE public.shipments(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants,
 parcel_count integer NOT NULL DEFAULT 1,booked_at timestamptz,final_client_price numeric(18,2) NOT NULL DEFAULT 10,
 profit_markup numeric(18,2) NOT NULL DEFAULT 1,currency text NOT NULL DEFAULT 'GBP',carrier_code text,status text NOT NULL DEFAULT 'DRAFT',quote_expires_at timestamptz,
 UNIQUE(tenant_id,id));
CREATE TABLE public.wallet_reservations(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,
 shipment_id uuid NOT NULL,status text NOT NULL DEFAULT 'RESERVED',FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id));
CREATE TABLE public.wallets(tenant_id uuid PRIMARY KEY,currency text NOT NULL DEFAULT 'GBP',balance numeric NOT NULL DEFAULT 0);
CREATE TABLE public.wallet_ledger(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 currency text DEFAULT 'GBP',entry_type text,balance_delta numeric,reserved_delta numeric,balance_after numeric,reserved_after numeric,reservation_id uuid);
