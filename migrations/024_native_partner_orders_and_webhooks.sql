-- Apply after 023. Only opted-in provider connections export native orders.
BEGIN;
SET LOCAL lock_timeout='10s';
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
CREATE INDEX IF NOT EXISTS partner_orders_pending ON public.partner_order_jobs(created_at) WHERE state='PENDING';
ALTER TABLE public.partner_order_jobs ADD COLUMN IF NOT EXISTS fulfillment_state text NOT NULL DEFAULT 'PENDING'
 CHECK(fulfillment_state IN ('PENDING','CONFIRMED','FAILED'));
ALTER TABLE public.partner_order_jobs ADD COLUMN IF NOT EXISTS fulfillment_attempts integer NOT NULL DEFAULT 0 CHECK(fulfillment_attempts>=0);
CREATE INDEX IF NOT EXISTS partner_order_fulfillment_pending ON public.partner_order_jobs(updated_at) WHERE state='SYNCED' AND fulfillment_state<>'CONFIRMED';
ALTER TABLE public.partner_provider_options ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.partner_order_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.partner_provider_options,public.partner_order_jobs FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.partner_provider_options,public.partner_order_jobs TO service_role;
CREATE OR REPLACE FUNCTION public.queue_native_partner_order() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE enabled boolean;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN RETURN NEW; END IF;
 IF NEW.ecommerce_store_id IS NULL OR NOT (NEW.logistics_metadata ? 'automation_order') OR NEW.status::text<>'QUOTED' THEN RETURN NEW; END IF;
 SELECT o.order_sync_enabled INTO enabled FROM public.carrier_accounts a
 JOIN public.partner_provider_options o ON o.platform_connection_id=a.platform_connection_id
 WHERE a.tenant_id=NEW.tenant_id AND a.id=NEW.carrier_account_id AND a.is_active;
 IF NOT coalesce(enabled,false) THEN RETURN NEW; END IF;
 BEGIN
  INSERT INTO public.partner_order_jobs(tenant_id,shipment_id,carrier_account_id,payload)
  VALUES(NEW.tenant_id,NEW.id,NEW.carrier_account_id,jsonb_build_object(
   'order',NEW.logistics_metadata->'automation_order','customs',NEW.logistics_metadata->'automation_customs',
   'upstream_shipment_id',NEW.upstream_shipment_id,'placed_at',NEW.created_at))
  ON CONFLICT(tenant_id,shipment_id,carrier_account_id) DO NOTHING;
 EXCEPTION WHEN OTHERS THEN
  RAISE WARNING 'Optional native order enqueue deferred; reconcile through native order sync';
 END;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS native_partner_order_prepared ON public.shipments;
CREATE TRIGGER native_partner_order_prepared AFTER INSERT OR UPDATE OF status,carrier_account_id,logistics_metadata
 ON public.shipments FOR EACH ROW EXECUTE FUNCTION public.queue_native_partner_order();
COMMIT;
