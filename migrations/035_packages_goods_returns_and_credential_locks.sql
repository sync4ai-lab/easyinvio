-- Apply after 034. Schema preparation only; no provider calls or notifications.
-- Empty package arrays mean UNKNOWN, never repeated copies of the first box.
-- Return/exchange outbox jobs are fenced until their native adapter is implemented.
BEGIN;
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='120s';

CREATE OR REPLACE FUNCTION public.valid_multi_parcel_dimensions(packages jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
DECLARE item jsonb; position integer:=0; field text; value numeric;
BEGIN
 IF packages IS NULL OR jsonb_typeof(packages)<>'array' THEN RETURN false; END IF;
 IF jsonb_array_length(packages)>100 THEN RETURN false; END IF;
 FOR item IN SELECT element FROM jsonb_array_elements(packages) AS entries(element) LOOP
  position:=position+1;
  IF jsonb_typeof(item)<>'object' OR item->>'box_index' IS DISTINCT FROM position::text THEN RETURN false; END IF;
  FOREACH field IN ARRAY ARRAY['length_cm','width_cm','height_cm','actual_weight_kg'] LOOP
   IF jsonb_typeof(item->field) NOT IN ('number','string') OR item->>field IS NULL
      OR (item->>field)!~'^[0-9]+([.][0-9]+)?$' OR length(item->>field)>20 THEN RETURN false; END IF;
   value:=(item->>field)::numeric;
   IF value<=0 THEN RETURN false; END IF;
   IF field='actual_weight_kg' THEN
    IF value>30000 OR value<>trunc(value,3) THEN RETURN false; END IF;
   ELSE
    IF value>(CASE WHEN field='length_cm' THEN 1500 ELSE 1000 END) OR value<>trunc(value,2) THEN RETURN false; END IF;
   END IF;
  END LOOP;
 END LOOP;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.valid_multi_parcel_dimensions(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.valid_multi_parcel_dimensions(jsonb) TO service_role;

ALTER TABLE public.shipments
 ADD COLUMN IF NOT EXISTS multi_parcel_dimensions jsonb NOT NULL DEFAULT '[]'::jsonb,
 ADD COLUMN IF NOT EXISTS tracking_lifecycle_type text NOT NULL DEFAULT 'FORWARD_SHIPMENT',
 ADD COLUMN IF NOT EXISTS store_fulfillment_status text NOT NULL DEFAULT 'UNKNOWN',
 ADD COLUMN IF NOT EXISTS store_return_status text NOT NULL DEFAULT 'NONE',
 ADD COLUMN IF NOT EXISTS return_of_shipment_id uuid;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.shipments'::regclass AND conname='shipments_multi_parcel_shape') THEN
  ALTER TABLE public.shipments ADD CONSTRAINT shipments_multi_parcel_shape CHECK(
   public.valid_multi_parcel_dimensions(multi_parcel_dimensions)
   AND (jsonb_array_length(multi_parcel_dimensions)=0 OR (
    jsonb_array_length(multi_parcel_dimensions)=parcel_count
    AND parcel_weight_kg IS NOT NULL AND parcel_length_cm IS NOT NULL AND parcel_width_cm IS NOT NULL AND parcel_height_cm IS NOT NULL
    AND parcel_weight_kg=(multi_parcel_dimensions->0->>'actual_weight_kg')::numeric
    AND parcel_length_cm=(multi_parcel_dimensions->0->>'length_cm')::numeric
    AND parcel_width_cm=(multi_parcel_dimensions->0->>'width_cm')::numeric
    AND parcel_height_cm=(multi_parcel_dimensions->0->>'height_cm')::numeric)));
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.shipments'::regclass AND conname='shipments_store_lifecycle') THEN
  ALTER TABLE public.shipments ADD CONSTRAINT shipments_store_lifecycle CHECK(
   tracking_lifecycle_type IN ('FORWARD_SHIPMENT','RETURN_SHIPMENT','EXCHANGE_SHIPMENT')
   AND store_fulfillment_status IN ('UNKNOWN','UNFULFILLED','PARTIALLY_FULFILLED','FULFILLED','CANCELLED')
   AND store_return_status IN ('NONE','REQUESTED','APPROVED','IN_TRANSIT','RECEIVED','REVIEW_REQUIRED','RESOLVED')
   AND (return_of_shipment_id IS NULL OR (return_of_shipment_id<>id AND tracking_lifecycle_type<>'FORWARD_SHIPMENT')));
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.shipments'::regclass AND conname='shipments_return_parent_tenant') THEN
  ALTER TABLE public.shipments ADD CONSTRAINT shipments_return_parent_tenant
   FOREIGN KEY(tenant_id,return_of_shipment_id) REFERENCES public.shipments(tenant_id,id);
 END IF;
END $$;
DO $$ DECLARE expression text; BEGIN
 SELECT pg_get_expr(conbin,conrelid) INTO expression FROM pg_constraint
  WHERE conrelid='public.shipments'::regclass AND conname='shipments_dimensions_check';
 IF expression IS NULL THEN RAISE EXCEPTION 'Expected shipment dimension validation is missing'; END IF;
 IF position('multi_parcel_dimensions' in expression)=0 THEN
  ALTER TABLE public.shipments DROP CONSTRAINT shipments_dimensions_check;
  EXECUTE format('ALTER TABLE public.shipments ADD CONSTRAINT shipments_dimensions_check CHECK ((%s) OR
   (cargo_type=''PARCEL'' AND parcel_count BETWEEN 2 AND 100 AND public.valid_multi_parcel_dimensions(multi_parcel_dimensions)
    AND jsonb_array_length(multi_parcel_dimensions)=parcel_count))',expression);
 END IF;
END $$;
COMMENT ON COLUMN public.shipments.multi_parcel_dimensions IS
 'Canonical measured package snapshot. Ordered, 1-based box_index; length_cm, width_cm, height_cm and actual_weight_kg required per box. Legacy flat measurements mirror box 1, not the total. Empty means not captured; do not infer extra boxes.';
COMMENT ON COLUMN public.shipments.store_fulfillment_status IS
 'Last verified storefront sales fulfillment state. Independent of physical shipment and return states; UNKNOWN is not UNFULFILLED.';

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
CREATE INDEX IF NOT EXISTS shipment_goods_hs_origin ON public.shipment_goods_items(tenant_id,hs_code,origin_country) WHERE hs_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS shipment_goods_sku ON public.shipment_goods_items(tenant_id,sku) WHERE sku IS NOT NULL;
ALTER TABLE public.shipment_goods_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.shipment_goods_items FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.shipment_goods_items TO service_role;
COMMENT ON TABLE public.shipment_goods_items IS
 'Private normalized goods lines. Backend populates from reviewed snapshots; no guessed legacy backfill. package_index NULL means allocation pending, not assigned to box 1.';

CREATE OR REPLACE FUNCTION public.lock_goods_parent() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE parent public.shipments%ROWTYPE;
BEGIN
 IF TG_OP='UPDATE' AND (NEW.tenant_id,NEW.shipment_id,NEW.item_index) IS DISTINCT FROM (OLD.tenant_id,OLD.shipment_id,OLD.item_index) THEN
  RAISE EXCEPTION 'Goods line identity cannot be reassigned' USING ERRCODE='42501';
 END IF;
 SELECT * INTO parent FROM public.shipments WHERE tenant_id=CASE WHEN TG_OP='DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END
  AND id=CASE WHEN TG_OP='DELETE' THEN OLD.shipment_id ELSE NEW.shipment_id END FOR UPDATE;
 IF FOUND AND (parent.booked_at IS NOT NULL OR parent.status::text='BOOKING') THEN
  RAISE EXCEPTION 'Submitted shipment goods are immutable; create a new quote' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.lock_goods_parent() FROM PUBLIC;
DROP TRIGGER IF EXISTS shipment_goods_parent_lock ON public.shipment_goods_items;
CREATE TRIGGER shipment_goods_parent_lock BEFORE INSERT OR UPDATE OR DELETE ON public.shipment_goods_items
 FOR EACH ROW EXECUTE FUNCTION public.lock_goods_parent();

CREATE OR REPLACE FUNCTION public.check_shipment_goods_mass() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE tenant uuid; shipment uuid; boxes jsonb; packed numeric; goods numeric; allocated record; box_weight numeric;
BEGIN
 IF TG_TABLE_NAME='shipments' THEN
  IF TG_OP='UPDATE' AND (NEW.multi_parcel_dimensions,NEW.parcel_count,NEW.parcel_weight_kg)
    IS NOT DISTINCT FROM (OLD.multi_parcel_dimensions,OLD.parcel_count,OLD.parcel_weight_kg) THEN RETURN NULL; END IF;
  tenant:=NEW.tenant_id;shipment:=NEW.id;
 ELSIF TG_OP='DELETE' THEN tenant:=OLD.tenant_id;shipment:=OLD.shipment_id;
 ELSE tenant:=NEW.tenant_id;shipment:=NEW.shipment_id; END IF;
 SELECT multi_parcel_dimensions,CASE WHEN parcel_count=1 THEN parcel_weight_kg END INTO boxes,packed
  FROM public.shipments WHERE tenant_id=tenant AND id=shipment FOR UPDATE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF jsonb_array_length(boxes)>0 THEN
  SELECT sum((item->>'actual_weight_kg')::numeric) INTO packed FROM jsonb_array_elements(boxes) AS entries(item);
 END IF;
 SELECT coalesce(sum(total_net_weight_kg),0) INTO goods FROM public.shipment_goods_items WHERE tenant_id=tenant AND shipment_id=shipment;
 IF packed IS NOT NULL AND goods>packed THEN RAISE EXCEPTION 'Goods net weight exceeds packed weight' USING ERRCODE='23514'; END IF;
 FOR allocated IN SELECT package_index,sum(total_net_weight_kg) AS net FROM public.shipment_goods_items
  WHERE tenant_id=tenant AND shipment_id=shipment AND package_index IS NOT NULL GROUP BY package_index LOOP
  IF allocated.package_index>jsonb_array_length(boxes) THEN RAISE EXCEPTION 'Goods refer to an unknown package' USING ERRCODE='23514'; END IF;
  box_weight:=(boxes->(allocated.package_index-1)->>'actual_weight_kg')::numeric;
  IF allocated.net>box_weight THEN RAISE EXCEPTION 'Allocated goods exceed package weight' USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.check_shipment_goods_mass() FROM PUBLIC;
DROP TRIGGER IF EXISTS shipment_goods_mass ON public.shipment_goods_items;
CREATE CONSTRAINT TRIGGER shipment_goods_mass AFTER INSERT OR UPDATE OR DELETE ON public.shipment_goods_items
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.check_shipment_goods_mass();
DROP TRIGGER IF EXISTS shipment_package_goods_mass ON public.shipments;
CREATE CONSTRAINT TRIGGER shipment_package_goods_mass AFTER INSERT OR UPDATE ON public.shipments
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.check_shipment_goods_mass();
CREATE OR REPLACE FUNCTION public.freeze_submitted_package_snapshot() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (OLD.booked_at IS NOT NULL OR OLD.status::text='BOOKING') AND NEW.multi_parcel_dimensions IS DISTINCT FROM OLD.multi_parcel_dimensions THEN
  RAISE EXCEPTION 'Submitted package measurements are immutable; create a new quote' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.freeze_submitted_package_snapshot() FROM PUBLIC;
DROP TRIGGER IF EXISTS freeze_submitted_package_snapshot ON public.shipments;
CREATE TRIGGER freeze_submitted_package_snapshot BEFORE UPDATE ON public.shipments
 FOR EACH ROW EXECUTE FUNCTION public.freeze_submitted_package_snapshot();

UPDATE public.shipments SET tracking_lifecycle_type='RETURN_SHIPMENT',store_return_status='REVIEW_REQUIRED'
 WHERE tracking_lifecycle_type='FORWARD_SHIPMENT' AND
  (logistics_metadata->'automation_order'->>'is_return'='true' OR logistics_metadata->'automation_order'->>'return_of_shipment_id' IS NOT NULL);

ALTER TABLE public.ecommerce_tracking_outbox
 ADD COLUMN IF NOT EXISTS tracking_lifecycle_type text NOT NULL DEFAULT 'FORWARD_SHIPMENT',
 ADD COLUMN IF NOT EXISTS store_sync_error_code text,
 ADD COLUMN IF NOT EXISTS store_return_reference text;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.ecommerce_tracking_outbox'::regclass AND conname='store_outbox_lifecycle_check') THEN
  ALTER TABLE public.ecommerce_tracking_outbox ADD CONSTRAINT store_outbox_lifecycle_check CHECK(
   tracking_lifecycle_type IN ('FORWARD_SHIPMENT','RETURN_SHIPMENT','EXCHANGE_SHIPMENT')
   AND (store_sync_error_code IS NULL OR store_sync_error_code ~ '^[A-Z0-9_]{1,100}$')
   AND (store_return_reference IS NULL OR length(store_return_reference) BETWEEN 1 AND 200));
 END IF;
END $$;
CREATE OR REPLACE FUNCTION public.classify_store_tracking_job() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE lifecycle text; metadata jsonb;
BEGIN
 SELECT tracking_lifecycle_type,logistics_metadata INTO lifecycle,metadata FROM public.shipments WHERE tenant_id=NEW.tenant_id AND id=NEW.shipment_id;
 IF NOT FOUND THEN RAISE EXCEPTION 'Store tracking shipment is outside this workspace' USING ERRCODE='23503'; END IF;
 IF metadata->'automation_order'->>'is_return'='true' OR metadata->'automation_order'->>'return_of_shipment_id' IS NOT NULL THEN lifecycle:='RETURN_SHIPMENT'; END IF;
 IF lifecycle<>'FORWARD_SHIPMENT' THEN NEW.tracking_lifecycle_type:=lifecycle; END IF;
 IF NEW.tracking_lifecycle_type<>'FORWARD_SHIPMENT' AND NEW.status='PENDING' THEN
  NEW.status:='RECONCILIATION_REQUIRED';NEW.store_sync_error_code:='RETURN_ADAPTER_UPGRADE_REQUIRED';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.classify_store_tracking_job() FROM PUBLIC;
DROP TRIGGER IF EXISTS classify_store_tracking_job ON public.ecommerce_tracking_outbox;
CREATE TRIGGER classify_store_tracking_job BEFORE INSERT OR UPDATE ON public.ecommerce_tracking_outbox
 FOR EACH ROW EXECUTE FUNCTION public.classify_store_tracking_job();
UPDATE public.ecommerce_tracking_outbox o SET tracking_lifecycle_type=s.tracking_lifecycle_type,
 store_sync_error_code=CASE WHEN o.status IN ('DELIVERED','SIMULATED_DELIVERED') THEN 'HISTORICAL_RETURN_REVIEW_REQUIRED' ELSE o.store_sync_error_code END
 FROM public.shipments s WHERE s.tenant_id=o.tenant_id AND s.id=o.shipment_id AND s.tracking_lifecycle_type<>'FORWARD_SHIPMENT'
  AND o.tracking_lifecycle_type='FORWARD_SHIPMENT';
CREATE INDEX IF NOT EXISTS ecommerce_outbox_lifecycle_pending ON public.ecommerce_tracking_outbox(tracking_lifecycle_type,status,created_at,id)
 WHERE status IN ('PENDING','RECONCILIATION_REQUIRED');

ALTER TABLE public.carrier_accounts
 ADD COLUMN IF NOT EXISTS credential_write_locked boolean NOT NULL DEFAULT false,
 ADD COLUMN IF NOT EXISTS credentials_locked_at timestamptz,
 ADD COLUMN IF NOT EXISTS last_security_audit_at timestamptz;
CREATE OR REPLACE FUNCTION public.guard_carrier_credential_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE parent public.platform_carrier_connections%ROWTYPE; changed boolean;
BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.platform_connection_id IS NOT NULL THEN
   SELECT * INTO parent FROM public.platform_carrier_connections WHERE id=NEW.platform_connection_id;
   IF NOT FOUND OR (NEW.aggregator,NEW.regional_provider_code,NEW.api_base_url,NEW.environment,NEW.upstream_account_id,NEW.credentials_ciphertext,NEW.credential_key_id)
    IS DISTINCT FROM (parent.aggregator,parent.regional_provider_code,parent.api_base_url,parent.environment,parent.upstream_account_id,parent.credentials_ciphertext,parent.credential_key_id) THEN
    RAISE EXCEPTION 'Shared credentials must match their trusted platform catalog' USING ERRCODE='42501';
   END IF;
  END IF;
  NEW.credential_write_locked:=true;NEW.credentials_locked_at:=now();RETURN NEW;
 END IF;
 IF OLD.credential_write_locked AND (NOT NEW.credential_write_locked OR NEW.credentials_locked_at IS DISTINCT FROM OLD.credentials_locked_at) THEN
  RAISE EXCEPTION 'Credential lock cannot be removed' USING ERRCODE='42501';
 END IF;
 changed:=(NEW.tenant_id,NEW.id,NEW.platform_connection_id,NEW.aggregator,NEW.regional_provider_code,NEW.api_base_url,NEW.environment,
  NEW.upstream_account_id,NEW.credentials_ciphertext,NEW.credential_key_id,NEW.credential_version)
  IS DISTINCT FROM (OLD.tenant_id,OLD.id,OLD.platform_connection_id,OLD.aggregator,OLD.regional_provider_code,OLD.api_base_url,OLD.environment,
  OLD.upstream_account_id,OLD.credentials_ciphertext,OLD.credential_key_id,OLD.credential_version);
 IF OLD.credential_write_locked AND changed THEN
  IF OLD.platform_connection_id IS NULL OR NEW.platform_connection_id IS DISTINCT FROM OLD.platform_connection_id
    OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.id IS DISTINCT FROM OLD.id THEN
   RAISE EXCEPTION 'Locked credentials require a newly authorized replacement connection' USING ERRCODE='42501';
  END IF;
  SELECT * INTO parent FROM public.platform_carrier_connections WHERE id=OLD.platform_connection_id;
  IF NOT FOUND OR (NEW.aggregator,NEW.regional_provider_code,NEW.api_base_url,NEW.environment,NEW.upstream_account_id,NEW.credentials_ciphertext,NEW.credential_key_id)
    IS DISTINCT FROM (parent.aggregator,parent.regional_provider_code,parent.api_base_url,parent.environment,parent.upstream_account_id,parent.credentials_ciphertext,parent.credential_key_id)
    OR NEW.credential_version IS DISTINCT FROM OLD.credential_version THEN
   RAISE EXCEPTION 'Shared credentials must match their trusted platform catalog' USING ERRCODE='42501';
  END IF;
 END IF;
 IF NOT OLD.credential_write_locked THEN NEW.credential_write_locked:=true;NEW.credentials_locked_at:=now(); END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_carrier_credential_identity() FROM PUBLIC;
DROP TRIGGER IF EXISTS guard_carrier_credential_identity ON public.carrier_accounts;
CREATE TRIGGER guard_carrier_credential_identity BEFORE INSERT OR UPDATE ON public.carrier_accounts
 FOR EACH ROW EXECUTE FUNCTION public.guard_carrier_credential_identity();
UPDATE public.carrier_accounts SET credential_write_locked=true,credentials_locked_at=coalesce(credentials_locked_at,now()) WHERE NOT credential_write_locked;
COMMENT ON COLUMN public.carrier_accounts.last_security_audit_at IS 'Actual completed security audit time, not an inferred audit from row creation.';
COMMENT ON COLUMN public.carrier_accounts.credential_write_locked IS
 'Database-enforced identity lock. Standalone rotation replaces and retires the account after fresh platform-admin authentication. Shared mirrors may only follow their existing trusted catalog record.';
COMMIT;
