-- Apply after 035. Private registries only; no shipment edits or provider calls.
BEGIN;
SET LOCAL lock_timeout='10s';
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
CREATE UNIQUE INDEX IF NOT EXISTS catalog_default_address_once ON public.tenant_catalog_addresses(tenant_id,address_role)
 WHERE is_default AND archived_at IS NULL;
CREATE INDEX IF NOT EXISTS catalog_address_workspace ON public.tenant_catalog_addresses(tenant_id,updated_at DESC,id) WHERE archived_at IS NULL;
CREATE TABLE IF NOT EXISTS public.tenant_catalog_contacts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 label text NOT NULL CHECK(length(btrim(label)) BETWEEN 1 AND 100),
 address jsonb NOT NULL CHECK(jsonb_typeof(address)='object' AND address ?& ARRAY['name','line1','city','postal_code','country_code']),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),created_by uuid NOT NULL REFERENCES auth.users(id),updated_by uuid NOT NULL REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),archived_at timestamptz,
 UNIQUE(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS catalog_contact_workspace ON public.tenant_catalog_contacts(tenant_id,updated_at DESC,id) WHERE archived_at IS NULL;
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
CREATE UNIQUE INDEX IF NOT EXISTS catalog_sku_workspace_once ON public.tenant_catalog_products(tenant_id,lower(sku)) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS catalog_product_workspace ON public.tenant_catalog_products(tenant_id,updated_at DESC,id) WHERE archived_at IS NULL;
ALTER TABLE public.tenant_catalog_addresses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_catalog_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_catalog_products ENABLE ROW LEVEL SECURITY;
-- Match existing private registries: JWT-authorized backend only. Every SQL query
-- additionally binds the verified tenant; browsers cannot access these tables directly.
REVOKE ALL ON public.tenant_catalog_addresses,public.tenant_catalog_contacts,public.tenant_catalog_products FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.tenant_catalog_addresses,public.tenant_catalog_contacts,public.tenant_catalog_products TO service_role;
COMMIT;
