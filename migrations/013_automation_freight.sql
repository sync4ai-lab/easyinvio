BEGIN;
ALTER TABLE public.shipments ADD COLUMN IF NOT EXISTS cargo_type text NOT NULL DEFAULT 'PARCEL'
  CHECK(cargo_type IN ('LETTER','PARCEL','PALLET','OVERLAND_FREIGHT'));
ALTER TABLE public.shipments ALTER COLUMN parcel_length_cm DROP NOT NULL;
ALTER TABLE public.shipments ALTER COLUMN parcel_width_cm DROP NOT NULL;
ALTER TABLE public.shipments ALTER COLUMN parcel_height_cm DROP NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.shipments'::regclass AND conname='shipments_cargo_dimensions') THEN
    ALTER TABLE public.shipments ADD CONSTRAINT shipments_cargo_dimensions CHECK (
      (cargo_type='LETTER' AND parcel_weight_kg<0.5 AND parcel_length_cm IS NULL AND parcel_width_cm IS NULL AND parcel_height_cm IS NULL)
      OR (cargo_type<>'LETTER' AND parcel_length_cm IS NOT NULL AND parcel_width_cm IS NOT NULL AND parcel_height_cm IS NOT NULL));
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS automation_shipment_idempotency ON public.shipments(tenant_id,idempotency_key);
CREATE TABLE IF NOT EXISTS public.automation_failures (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
  idempotency_key uuid NOT NULL,order_reference text NOT NULL,shipment_id uuid,error_code text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,idempotency_key),UNIQUE(tenant_id,id),
  FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
ALTER TABLE public.support_tickets ADD COLUMN IF NOT EXISTS automation_failure_id uuid;
ALTER TABLE public.support_tickets ALTER COLUMN tracking_event_id DROP NOT NULL;
ALTER TABLE public.support_tickets ALTER COLUMN shipment_id DROP NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.support_tickets'::regclass AND conname='support_automation_failure_fk') THEN
    ALTER TABLE public.support_tickets ADD CONSTRAINT support_automation_failure_fk
      FOREIGN KEY(tenant_id,automation_failure_id) REFERENCES public.automation_failures(tenant_id,id);
    ALTER TABLE public.support_tickets ADD CONSTRAINT support_ticket_source CHECK(
      (tracking_event_id IS NOT NULL AND automation_failure_id IS NULL AND shipment_id IS NOT NULL)
      OR (tracking_event_id IS NULL AND automation_failure_id IS NOT NULL));
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS support_automation_failure_unique ON public.support_tickets(automation_failure_id);
ALTER TABLE public.automation_failures ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.automation_failures FROM anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.automation_failures TO service_role;
DO $$ DECLARE c record;
BEGIN
  FOR c IN SELECT conname,pg_get_expr(conbin,conrelid) AS expression FROM pg_constraint
    WHERE conrelid='public.ecommerce_stores'::regclass AND contype='c'
    AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='public.ecommerce_stores'::regclass AND attname='platform')]::smallint[]
  LOOP
    IF position('AMAZON' in c.expression)=0 THEN
      EXECUTE format('ALTER TABLE public.ecommerce_stores DROP CONSTRAINT %I',c.conname);
      EXECUTE format('ALTER TABLE public.ecommerce_stores ADD CONSTRAINT %I CHECK ((%s) OR platform=%L)',c.conname,c.expression,'AMAZON');
    END IF;
  END LOOP;
END $$;
COMMIT;
