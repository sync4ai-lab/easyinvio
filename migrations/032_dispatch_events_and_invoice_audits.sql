-- Durable workspace updates and private invoice findings; no external calls.
DO $$ DECLARE typ text; BEGIN
 SELECT format('%I.%I',n.nspname,t.typname) INTO typ FROM pg_attribute a
 JOIN pg_type t ON t.oid=a.atttypid JOIN pg_namespace n ON n.oid=t.typnamespace
 WHERE a.attrelid='public.shipments'::regclass AND a.attname='status' AND t.typtype='e';
 IF typ IS NOT NULL THEN EXECUTE format('ALTER TYPE %s ADD VALUE IF NOT EXISTS %L',typ,'UNFULFILLED'); END IF;
END $$;
BEGIN;
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT conname,pg_get_expr(conbin,conrelid) AS expression FROM pg_constraint
 WHERE conrelid='public.shipments'::regclass AND contype='c'
 AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='public.shipments'::regclass AND attname='status')]::smallint[] LOOP
  IF position('UNFULFILLED' in c.expression)=0 THEN
   EXECUTE format('ALTER TABLE public.shipments DROP CONSTRAINT %I',c.conname);
   EXECUTE format('ALTER TABLE public.shipments ADD CONSTRAINT %I CHECK ((%s) OR status::text=%L)',c.conname,c.expression,'UNFULFILLED');
  END IF;
 END LOOP;
END $$;
SET LOCAL lock_timeout='10s';
DO $$ DECLARE expression text; BEGIN
 SELECT pg_get_expr(conbin,conrelid) INTO expression FROM pg_constraint
 WHERE conrelid='public.shipments'::regclass AND conname='shipments_rated_carrier_required';
 IF expression IS NULL THEN RAISE EXCEPTION 'Expected rated carrier constraint is missing'; END IF;
 IF position('UNFULFILLED' in expression)=0 THEN
  ALTER TABLE public.shipments DROP CONSTRAINT shipments_rated_carrier_required;
  EXECUTE format('ALTER TABLE public.shipments ADD CONSTRAINT shipments_rated_carrier_required CHECK ((%s) OR
   (status::text=''UNFULFILLED'' AND ecommerce_store_id IS NOT NULL AND carrier_account_id IS NULL
    AND booked_at IS NULL AND tracking_number IS NULL AND label_storage_path IS NULL
    AND wholesale_cost=0 AND profit_markup=0))',expression);
 END IF;
END $$;
DO $$ DECLARE expression text; BEGIN
 SELECT pg_get_expr(conbin,conrelid) INTO expression FROM pg_constraint
 WHERE conrelid='public.shipments'::regclass AND conname='shipments_cargo_dimensions';
 IF expression IS NULL THEN RAISE EXCEPTION 'Expected cargo dimension constraint is missing'; END IF;
 IF position('UNFULFILLED' in expression)=0 THEN
  ALTER TABLE public.shipments DROP CONSTRAINT shipments_cargo_dimensions;
  EXECUTE format('ALTER TABLE public.shipments ADD CONSTRAINT shipments_cargo_dimensions CHECK ((%s) OR
   (status::text=''UNFULFILLED'' AND ecommerce_store_id IS NOT NULL AND booked_at IS NULL
    AND carrier_account_id IS NULL AND parcel_length_cm IS NULL AND parcel_width_cm IS NULL
    AND parcel_height_cm IS NULL AND wholesale_cost=0 AND profit_markup=0))',expression);
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS public.workspace_dispatch_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 shipment_id uuid NOT NULL,
 status text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS workspace_dispatch_events_tenant ON public.workspace_dispatch_events(tenant_id,id);
CREATE OR REPLACE FUNCTION public.emit_workspace_dispatch_event() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF TG_OP='INSERT' OR NEW.status IS DISTINCT FROM OLD.status THEN
  INSERT INTO public.workspace_dispatch_events(tenant_id,shipment_id,status)
  VALUES(NEW.tenant_id,NEW.id,NEW.status::text);
  PERFORM pg_notify('easyinvio_dispatch',json_build_object('tenant_id',NEW.tenant_id,
   'shipment_id',NEW.id,'status',NEW.status::text)::text);
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.emit_workspace_dispatch_event() FROM PUBLIC;
DROP TRIGGER IF EXISTS shipment_dispatch_update ON public.shipments;
CREATE TRIGGER shipment_dispatch_update AFTER INSERT OR UPDATE OF status ON public.shipments
 FOR EACH ROW EXECUTE FUNCTION public.emit_workspace_dispatch_event();
CREATE INDEX IF NOT EXISTS shipments_native_invoice_reference ON public.shipments(tenant_id,upstream_shipment_id) WHERE booked_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS shipments_transaction_invoice_reference ON public.shipments(tenant_id,(logistics_metadata->'automation_label'->>'upstream_id')) WHERE booked_at IS NOT NULL;
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
CREATE INDEX IF NOT EXISTS amazon_order_notification_pending ON public.amazon_order_notifications(next_attempt_at) WHERE status='RECEIVED';
ALTER TABLE public.workspace_dispatch_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_disputes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.amazon_order_notifications ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.workspace_dispatch_events,public.billing_disputes FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.workspace_dispatch_events TO service_role;
GRANT SELECT,INSERT,UPDATE ON public.billing_disputes TO service_role;
REVOKE ALL ON public.amazon_order_notifications FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.amazon_order_notifications TO service_role;
COMMIT;
