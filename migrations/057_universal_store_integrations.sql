-- Apply after 056. Configuration only; no provider calls or automatic activation.
BEGIN;
SET LOCAL lock_timeout='10s';
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT conname FROM pg_constraint WHERE conrelid='public.ecommerce_stores'::regclass
  AND contype='c' AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='public.ecommerce_stores'::regclass AND attname='platform')]::smallint[]
 LOOP EXECUTE format('ALTER TABLE public.ecommerce_stores DROP CONSTRAINT %I',c.conname); END LOOP;
END $$;
ALTER TABLE public.ecommerce_stores ADD CONSTRAINT ecommerce_store_platform CHECK(platform IN
 ('SHOPIFY','WOOCOMMERCE','AMAZON','CUSTOM_WEBSITE','EBAY','ETSY','TIKTOK_SHOP','BIGCOMMERCE','WIX',
 'SQUARESPACE','MAGENTO','PRESTASHOP','SHOPWARE','ECWID','SQUARE','WEEBLY','OPENCART','ONBUY',
 'MANOMANO','MIRAKL','KAUFLAND','LINNWORKS','CHANNELENGINE','CSV_SFTP'));
ALTER TABLE public.ecommerce_stores
 ADD COLUMN store_slug text UNIQUE CHECK(store_slug ~ '^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])$'),
 ADD COLUMN return_policy jsonb NOT NULL DEFAULT '{"enabled":false}' CHECK(jsonb_typeof(return_policy)='object'),
 ADD COLUMN return_policy_authorized_by uuid REFERENCES auth.users(id);
ALTER TABLE public.ecommerce_tracking_outbox ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now();
CREATE TABLE public.store_api_usage (
 store_id uuid NOT NULL REFERENCES public.ecommerce_stores(id),subject_sha256 text NOT NULL,
 bucket bigint NOT NULL,requests integer NOT NULL CHECK(requests>0),
 PRIMARY KEY(store_id,subject_sha256,bucket)
);
CREATE TABLE public.store_checkout_cache (
 tenant_id uuid NOT NULL,store_id uuid NOT NULL,input_sha256 text NOT NULL,response jsonb NOT NULL,expires_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,store_id,input_sha256),FOREIGN KEY(tenant_id,store_id) REFERENCES public.ecommerce_stores(tenant_id,id)
);
ALTER TABLE public.store_checkout_cache ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.store_checkout_cache FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.store_checkout_cache TO service_role;
CREATE TABLE public.store_return_sessions (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,store_id uuid NOT NULL,shipment_id uuid NOT NULL,
 request_id uuid NOT NULL,token_sha256 text NOT NULL UNIQUE CHECK(token_sha256 ~ '^[a-f0-9]{64}$'),
 policy_sha256 text NOT NULL CHECK(policy_sha256 ~ '^[a-f0-9]{64}$'),
 state text NOT NULL DEFAULT 'VERIFIED' CHECK(state IN ('VERIFIED','PROCESSING','SUBMITTED','REVIEW_REQUIRED')),
 expires_at timestamptz NOT NULL DEFAULT now()+interval '24 hours',created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,store_id) REFERENCES public.ecommerce_stores(tenant_id,id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE INDEX store_return_session_expiry ON public.store_return_sessions(expires_at);
CREATE TABLE public.store_callback_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,store_id uuid NOT NULL,shipment_id uuid NOT NULL,
 source_event text NOT NULL,payload jsonb NOT NULL,state text NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','RETRY','DELIVERED')),
 attempts integer NOT NULL DEFAULT 0,next_attempt_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,shipment_id,source_event),
 FOREIGN KEY(tenant_id,store_id) REFERENCES public.ecommerce_stores(tenant_id,id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
ALTER TABLE public.store_callback_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.store_callback_events FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.store_callback_events TO service_role;
ALTER TABLE public.store_api_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.store_return_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.store_api_usage,public.store_return_sessions FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.store_api_usage,public.store_return_sessions TO service_role;
-- Repair only demonstrably simulated LIVE events; never represent them as delivered.
-- Historical environment cannot be inferred reliably from outbox alone, so no automatic requeue.
COMMIT;
