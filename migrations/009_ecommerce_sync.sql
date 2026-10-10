-- Apply after 008. Run the entire file without an enclosing transaction:
-- PostgreSQL enum additions must commit before the new label is used.
DO $$
DECLARE typ text;
BEGIN
  SELECT format('%I.%I',n.nspname,t.typname) INTO typ
  FROM pg_attribute a JOIN pg_type t ON t.oid=a.atttypid
  JOIN pg_namespace n ON n.oid=t.typnamespace
  WHERE a.attrelid='public.shipments'::regclass AND a.attname='status' AND t.typtype='e';
  IF typ IS NOT NULL THEN
    EXECUTE format('ALTER TYPE %s ADD VALUE IF NOT EXISTS %L',typ,'PENDING_IMPORT');
  END IF;
END $$;
BEGIN;
CREATE TABLE IF NOT EXISTS public.ecommerce_stores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
  platform text NOT NULL CHECK (platform IN ('SHOPIFY','WOOCOMMERCE')),
  display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id,id)
);
ALTER TABLE public.shipments ADD COLUMN IF NOT EXISTS ecommerce_store_id uuid;
ALTER TABLE public.shipments ADD COLUMN IF NOT EXISTS store_order_id text;
ALTER TABLE public.shipments ADD COLUMN IF NOT EXISTS store_import_hash text;
DO $$
DECLARE c record;
BEGIN
  -- Extend single-column status CHECK constraints while preserving every old state.
  FOR c IN SELECT conname,pg_get_expr(conbin,conrelid) AS expression
    FROM pg_constraint WHERE conrelid='public.shipments'::regclass AND contype='c'
    AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='public.shipments'::regclass AND attname='status')]::smallint[]
  LOOP
    IF position('PENDING_IMPORT' in c.expression)=0 THEN
      EXECUTE format('ALTER TABLE public.shipments DROP CONSTRAINT %I',c.conname);
      EXECUTE format('ALTER TABLE public.shipments ADD CONSTRAINT %I CHECK ((%s) OR status::text=%L)',c.conname,c.expression,'PENDING_IMPORT');
    END IF;
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='public.shipments'::regclass AND conname='shipments_ecommerce_store_fk') THEN
    ALTER TABLE public.shipments ADD CONSTRAINT shipments_ecommerce_store_fk
      FOREIGN KEY (tenant_id,ecommerce_store_id) REFERENCES public.ecommerce_stores(tenant_id,id);
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS shipments_store_order_unique
  ON public.shipments(tenant_id,ecommerce_store_id,store_order_id) WHERE ecommerce_store_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS shipments_tenant_id_unique ON public.shipments(tenant_id,id);
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
CREATE INDEX IF NOT EXISTS ecommerce_pending_events ON public.ecommerce_tracking_outbox(created_at) WHERE status='PENDING';
ALTER TABLE public.ecommerce_stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ecommerce_tracking_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ecommerce_stores,public.ecommerce_tracking_outbox FROM anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.ecommerce_stores,public.ecommerce_tracking_outbox TO service_role;
-- Prevent browser table grants from forging store associations or import identity.
CREATE OR REPLACE FUNCTION public.guard_ecommerce_import_fields() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP='UPDATE' AND NEW.ecommerce_store_id IS NOT DISTINCT FROM OLD.ecommerce_store_id
    AND NEW.store_order_id IS NOT DISTINCT FROM OLD.store_order_id
    AND NEW.store_import_hash IS NOT DISTINCT FROM OLD.store_import_hash THEN RETURN NEW; END IF;
  IF TG_OP='INSERT' AND NEW.ecommerce_store_id IS NULL AND NEW.store_order_id IS NULL
    AND NEW.store_import_hash IS NULL THEN RETURN NEW; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Store import identity is server-owned' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS guard_ecommerce_import_fields ON public.shipments;
CREATE TRIGGER guard_ecommerce_import_fields BEFORE INSERT OR UPDATE OF ecommerce_store_id,store_order_id,store_import_hash
  ON public.shipments FOR EACH ROW EXECUTE FUNCTION public.guard_ecommerce_import_fields();
COMMIT;
