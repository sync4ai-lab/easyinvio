-- Add optional pricing selectors and permit genuinely unpacked store imports.
-- Existing rules and booked/quoted shipment constraints retain their behavior.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.margin_rules
 ADD COLUMN IF NOT EXISTS billing_plan text CHECK(billing_plan IN ('PREPAID_WALLET','POSTPAID_30_DAY')),
 ADD COLUMN IF NOT EXISTS cargo_type text CHECK(cargo_type IN ('LETTER','PARCEL','PALLET','OVERLAND_FREIGHT')),
 ADD COLUMN IF NOT EXISTS min_volume_m3 numeric(18,9) CHECK(min_volume_m3>=0),
 ADD COLUMN IF NOT EXISTS max_volume_m3 numeric(18,9) CHECK(max_volume_m3>0);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.margin_rules'::regclass AND conname='margin_volume_bounds') THEN
  ALTER TABLE public.margin_rules ADD CONSTRAINT margin_volume_bounds
   CHECK(max_volume_m3 IS NULL OR min_volume_m3 IS NULL OR max_volume_m3>min_volume_m3);
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS margin_active_cargo_tier
 ON public.margin_rules(tenant_id,currency,billing_plan,cargo_type,priority,created_at,id) WHERE is_active;
ALTER TABLE public.shipments ALTER COLUMN carrier_account_id DROP NOT NULL;
ALTER TABLE public.shipments DROP CONSTRAINT IF EXISTS shipments_cargo_dimensions;
ALTER TABLE public.shipments ADD CONSTRAINT shipments_cargo_dimensions CHECK(
 (status='PENDING_IMPORT' AND cargo_type='PARCEL' AND parcel_length_cm IS NULL AND parcel_width_cm IS NULL AND parcel_height_cm IS NULL)
 OR (cargo_type='LETTER' AND parcel_weight_kg<0.5 AND parcel_length_cm IS NULL AND parcel_width_cm IS NULL AND parcel_height_cm IS NULL)
 OR (cargo_type<>'LETTER' AND parcel_length_cm IS NOT NULL AND parcel_width_cm IS NOT NULL AND parcel_height_cm IS NOT NULL));
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.shipments'::regclass AND conname='shipments_rated_carrier_required') THEN
  ALTER TABLE public.shipments ADD CONSTRAINT shipments_rated_carrier_required
   CHECK(status='PENDING_IMPORT' OR carrier_account_id IS NOT NULL);
 END IF;
END $$;
-- Ambiguous external fulfillment results require reconciliation, not blind retries.
ALTER TABLE public.ecommerce_tracking_outbox DROP CONSTRAINT IF EXISTS ecommerce_tracking_outbox_status_check;
ALTER TABLE public.ecommerce_tracking_outbox ADD CONSTRAINT ecommerce_tracking_outbox_status_check
 CHECK(status IN ('PENDING','SIMULATED_DELIVERED','DELIVERED','RECONCILIATION_REQUIRED'));
COMMIT;
