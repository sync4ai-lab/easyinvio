-- Apply after 055. No external calls, purchases, refunds or automatic settlements.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.tenants ALTER COLUMN public_status_lookup_enabled SET DEFAULT true;
-- Preserve every existing merchant's public publication choice.
ALTER TABLE public.tenants ALTER COLUMN plan_enforcement_enabled SET DEFAULT true;
UPDATE public.tenants SET plan_enforcement_enabled=true,plan_version=plan_version+1
 WHERE NOT plan_enforcement_enabled;
CREATE FUNCTION public.require_plan_enforcement() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog AS $$ BEGIN NEW.plan_enforcement_enabled:=true;RETURN NEW;END $$;
REVOKE ALL ON FUNCTION public.require_plan_enforcement() FROM PUBLIC;
CREATE TRIGGER aaa_require_plan_enforcement BEFORE INSERT OR UPDATE ON public.tenants
 FOR EACH ROW EXECUTE FUNCTION public.require_plan_enforcement();

ALTER TABLE public.whatsapp_consumer_return_policies
 ADD COLUMN allowed_countries text[] NOT NULL DEFAULT ARRAY['GB'],
 ADD COLUMN paperless_preferred boolean NOT NULL DEFAULT true,
 ADD COLUMN require_delivered_status boolean NOT NULL DEFAULT true CHECK(require_delivered_status),
 ADD CONSTRAINT return_policy_country_bounds CHECK(cardinality(allowed_countries) BETWEEN 1 AND 25);
UPDATE public.whatsapp_consumer_return_policies SET maximum_price_gbp=50 WHERE maximum_price_gbp>50;
ALTER TABLE public.whatsapp_consumer_return_policies ADD CONSTRAINT return_policy_cap CHECK(maximum_price_gbp<=50);
-- A tenant is inserted before its owner. Seed only when a real owner/admin exists.
CREATE FUNCTION public.seed_safe_return_policy() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF NEW.is_active AND NEW.role IN ('OWNER','ADMIN') THEN
 INSERT INTO public.whatsapp_consumer_return_policies
 (tenant_id,enabled,authorized_by,window_days,charge_bearer,maximum_price_gbp)
 VALUES(NEW.tenant_id,true,NEW.auth_user_id,14,'CUSTOMER_PAY',10)
 ON CONFLICT(tenant_id) DO NOTHING;
 END IF;RETURN NEW;END $$;
REVOKE ALL ON FUNCTION public.seed_safe_return_policy() FROM PUBLIC;
CREATE TRIGGER seed_safe_consumer_returns AFTER INSERT OR UPDATE ON public.users
 FOR EACH ROW EXECUTE FUNCTION public.seed_safe_return_policy();
INSERT INTO public.whatsapp_consumer_return_policies
 (tenant_id,enabled,authorized_by,window_days,charge_bearer,maximum_price_gbp)
 SELECT DISTINCT ON(u.tenant_id) u.tenant_id,true,u.auth_user_id,14,'CUSTOMER_PAY',10
 FROM public.users u JOIN public.tenants t USING(tenant_id)
 WHERE u.is_active AND u.role IN ('OWNER','ADMIN') AND t.workspace_status='ACTIVE'
 ORDER BY u.tenant_id,(u.role='OWNER') DESC,u.id
 ON CONFLICT(tenant_id) DO NOTHING;

CREATE TABLE public.cx_policy_proposals(
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 actor_id uuid NOT NULL REFERENCES auth.users(id),policy jsonb NOT NULL,
 expected_version integer NOT NULL,expires_at timestamptz NOT NULL,
 confirmed_at timestamptz,created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX cx_policy_actor ON public.cx_policy_proposals(tenant_id,actor_id,created_at DESC);
CREATE TABLE public.connector_tracking_setup(
 platform_connection_id uuid PRIMARY KEY REFERENCES public.platform_carrier_connections(id),
 state text NOT NULL DEFAULT 'DUE' CHECK(state IN ('DUE','RUNNING','READY','MANUAL_REQUIRED','REVIEW_REQUIRED','DISABLED')),
 callback_url text,secret_ciphertext bytea,key_id text,provider_reference text,
 attempts integer NOT NULL DEFAULT 0,next_attempt_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz,error_code text,verified_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now());
CREATE FUNCTION public.queue_connector_tracking_setup() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF NEW.is_active AND NEW.retired_at IS NULL THEN
 INSERT INTO public.connector_tracking_setup(platform_connection_id) VALUES(NEW.id)
 ON CONFLICT(platform_connection_id) DO UPDATE SET state='DUE',next_attempt_at=now(),updated_at=now()
 WHERE connector_tracking_setup.state IN ('DISABLED','MANUAL_REQUIRED');
 ELSE UPDATE public.connector_tracking_setup SET state='DISABLED',updated_at=now()
 WHERE platform_connection_id=NEW.id;END IF;RETURN NEW;END $$;
REVOKE ALL ON FUNCTION public.queue_connector_tracking_setup() FROM PUBLIC;
CREATE TRIGGER queue_tracking_setup AFTER INSERT OR UPDATE ON public.platform_carrier_connections
 FOR EACH ROW EXECUTE FUNCTION public.queue_connector_tracking_setup();
INSERT INTO public.connector_tracking_setup(platform_connection_id)
 SELECT id FROM public.platform_carrier_connections WHERE is_active AND retired_at IS NULL;

ALTER TABLE public.support_tickets ADD COLUMN claim_dossier jsonb;
CREATE TABLE public.cx_claim_dossiers(
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 shipment_id uuid NOT NULL,ticket_id uuid NOT NULL REFERENCES public.support_tickets(id),
 actor_id uuid REFERENCES auth.users(id),capability_sha256 text,
 dossier jsonb NOT NULL,input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),version integer NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK((actor_id IS NOT NULL) <> (capability_sha256 IS NOT NULL)));
CREATE TABLE public.cx_claim_evidence(
 id uuid PRIMARY KEY,dossier_id uuid NOT NULL REFERENCES public.cx_claim_dossiers(id),
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),content_sha256 text NOT NULL,
 content bytea NOT NULL,mime_type text NOT NULL CHECK(mime_type IN ('image/png','image/jpeg')),
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(dossier_id,content_sha256));
CREATE TABLE public.cx_worker_heartbeats(worker_name text NOT NULL,environment text NOT NULL CHECK(environment IN ('TEST','LIVE')),
 instance_id uuid NOT NULL,last_seen timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(worker_name,environment,instance_id));
CREATE TABLE public.cx_delay_incidents(
 tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,incident_key text NOT NULL,
 ticket_id uuid NOT NULL REFERENCES public.support_tickets(id),created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,shipment_id,incident_key),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id));
DO $$ DECLARE n text; BEGIN FOREACH n IN ARRAY ARRAY['cx_policy_proposals','connector_tracking_setup',
 'cx_claim_dossiers','cx_claim_evidence','cx_delay_incidents','cx_worker_heartbeats'] LOOP
 EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',n);
 EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated',n);
 EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO service_role',n);
 END LOOP;END $$;
COMMIT;
