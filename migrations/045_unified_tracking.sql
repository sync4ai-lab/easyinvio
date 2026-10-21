-- Apply after the complete 044. Tracking visibility is included, never a paid entitlement.
BEGIN;
SET LOCAL lock_timeout='10s';
DO $$
DECLARE name text;
BEGIN
 FOREACH name IN ARRAY ARRAY['auth.users','public.tenants','public.users','public.shipments',
   'public.carrier_accounts','public.tracking_events','public.carrier_manifests','public.ecommerce_tracking_outbox'] LOOP
  IF to_regclass(name) IS NULL THEN
   RAISE EXCEPTION 'Migration 045 prerequisite missing: %',name USING ERRCODE='55000',
    HINT='Apply the earlier migrations, including complete 043 and 044, in this same database before 045.';
  END IF;
 END LOOP;
END $$;
-- Preserve unmapped carrier facts without introducing UNKNOWN into the shipment
-- state machine. Existing allowed tracking-event values remain valid.
DO $$
DECLARE item record;
BEGIN
 FOR item IN SELECT conname,pg_get_expr(conbin,conrelid) expression FROM pg_constraint
  WHERE conrelid='public.tracking_events'::regclass AND contype='c'
  AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='public.tracking_events'::regclass AND attname='status')]::smallint[]
 LOOP
  IF position('UNKNOWN' in item.expression)=0 THEN
   EXECUTE format('ALTER TABLE public.tracking_events DROP CONSTRAINT %I',item.conname);
   EXECUTE format('ALTER TABLE public.tracking_events ADD CONSTRAINT %I CHECK ((%s) OR status=%L)',item.conname,item.expression,'UNKNOWN');
  END IF;
 END LOOP;
END $$;
CREATE TABLE public.tracking_share_links (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 anchor_shipment_id uuid NOT NULL, shipment_ids uuid[] NOT NULL CHECK(cardinality(shipment_ids) BETWEEN 1 AND 100),
 token_sha256 text NOT NULL UNIQUE CHECK(token_sha256 ~ '^[a-f0-9]{64}$'),
 created_by uuid NOT NULL REFERENCES auth.users(id), created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL CHECK(expires_at>created_at AND expires_at<=created_at+interval '30 days'),
 revoked_at timestamptz, UNIQUE(tenant_id,id),
 FOREIGN KEY(tenant_id,anchor_shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK(anchor_shipment_id=ANY(shipment_ids))
);
CREATE INDEX tracking_share_workspace ON public.tracking_share_links(tenant_id,anchor_shipment_id,created_at DESC);
CREATE OR REPLACE FUNCTION public.guard_tracking_share() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='INSERT' THEN
  IF cardinality(NEW.shipment_ids)<>(SELECT count(*) FROM public.shipments WHERE tenant_id=NEW.tenant_id AND id=ANY(NEW.shipment_ids)) THEN
   RAISE EXCEPTION 'Tracking share membership must belong to one workspace without duplicates' USING ERRCODE='23514';
  END IF;
 ELSIF (to_jsonb(NEW)-'revoked_at') IS DISTINCT FROM (to_jsonb(OLD)-'revoked_at')
   OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
  RAISE EXCEPTION 'Tracking capabilities are immutable; issue a new link' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_tracking_share() FROM PUBLIC;
CREATE TRIGGER tracking_share_membership BEFORE INSERT OR UPDATE ON public.tracking_share_links
 FOR EACH ROW EXECUTE FUNCTION public.guard_tracking_share();
CREATE TABLE public.tracking_customer_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,
 share_link_id uuid NOT NULL,request_id uuid NOT NULL,
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 note text NOT NULL CHECK(length(note) BETWEEN 10 AND 1000),
 state text NOT NULL DEFAULT 'OPEN' CHECK(state IN ('OPEN','ACKNOWLEDGED')),
 created_at timestamptz NOT NULL DEFAULT now(),acknowledged_at timestamptz,
 UNIQUE(share_link_id,request_id),FOREIGN KEY(tenant_id,share_link_id) REFERENCES public.tracking_share_links(tenant_id,id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE INDEX tracking_customer_queue ON public.tracking_customer_requests(tenant_id,shipment_id,state,created_at);
CREATE TABLE public.tracking_preferences (
 tenant_id uuid PRIMARY KEY REFERENCES public.tenants(tenant_id),
 in_app_enabled boolean NOT NULL DEFAULT true,
 categories text[] NOT NULL DEFAULT ARRAY['IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','RETURNED_TO_SENDER'],
 stale_hours integer NOT NULL DEFAULT 48 CHECK(stale_hours BETWEEN 12 AND 720),
 poll_interval_minutes integer NOT NULL DEFAULT 360 CHECK(poll_interval_minutes BETWEEN 60 AND 1440),
 updated_by uuid REFERENCES auth.users(id),updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(categories <@ ARRAY['IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','RETURNED_TO_SENDER','AVAILABLE_FOR_PICKUP'])
);
CREATE TABLE public.tracking_notifications (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
 shipment_id uuid NOT NULL, tracking_event_id uuid NOT NULL,
 event_sha256 text NOT NULL CHECK(event_sha256 ~ '^[a-f0-9]{64}$'),
 category text NOT NULL, channel text NOT NULL DEFAULT 'IN_APP' CHECK(channel='IN_APP'),
 state text NOT NULL DEFAULT 'READY' CHECK(state='READY'),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,id),UNIQUE(tenant_id,event_sha256),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 FOREIGN KEY(tenant_id,tracking_event_id) REFERENCES public.tracking_events(tenant_id,id)
);
CREATE INDEX tracking_notification_workspace ON public.tracking_notifications(tenant_id,created_at DESC,id);
CREATE TABLE public.tracking_refresh_jobs (
 tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,requested_by uuid NOT NULL REFERENCES auth.users(id),
 state text NOT NULL DEFAULT 'DUE' CHECK(state IN ('DUE','RUNNING','COMPLETE','DEAD','UNSUPPORTED')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 next_attempt_at timestamptz NOT NULL DEFAULT now(),lease_token uuid,lease_until timestamptz,
 last_attempt_at timestamptz,last_success_at timestamptz,error_code text,
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,shipment_id),FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK((state='RUNNING')=(lease_token IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE INDEX tracking_refresh_due ON public.tracking_refresh_jobs(next_attempt_at) WHERE state='DUE';
CREATE TABLE public.tracking_provider_limits (
 carrier_account_id uuid PRIMARY KEY REFERENCES public.carrier_accounts(id),
 next_allowed_at timestamptz NOT NULL
);
CREATE TABLE public.tracking_case_reviews (
 tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,
 state text NOT NULL CHECK(state IN ('ACKNOWLEDGED','IN_REVIEW','ESCALATED','RESOLVED')),
 assigned_to uuid REFERENCES auth.users(id),note text NOT NULL CHECK(length(note) BETWEEN 1 AND 1000),
 updated_by uuid NOT NULL REFERENCES auth.users(id),updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,shipment_id),FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE TABLE public.tracking_operations_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,tenant_id uuid REFERENCES public.tenants(tenant_id),
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),shipment_id uuid,
 action text NOT NULL CHECK(action IN ('SEARCH','DETAIL','SHARE','REVOKE','REFRESH','RETRY','REVIEW','PREFERENCES')),
 detail jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(detail)='object'),created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE INDEX tracking_operations_workspace ON public.tracking_operations_audit(tenant_id,created_at DESC);
CREATE OR REPLACE FUNCTION public.protect_tracking_history() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Tracking history is append-only' USING ERRCODE='42501'; END IF;
 -- Only the existing support worker's staging flag may change on a receipt.
 IF TG_TABLE_NAME<>'tracking_events' OR (to_jsonb(NEW)-'support_pending') IS DISTINCT FROM (to_jsonb(OLD)-'support_pending') THEN
  RAISE EXCEPTION 'Tracking history is append-only' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.protect_tracking_history() FROM PUBLIC;
CREATE TRIGGER tracking_events_immutable BEFORE UPDATE OR DELETE ON public.tracking_events
 FOR EACH ROW EXECUTE FUNCTION public.protect_tracking_history();
CREATE TRIGGER tracking_operations_immutable BEFORE UPDATE OR DELETE ON public.tracking_operations_audit
 FOR EACH ROW EXECUTE FUNCTION public.protect_tracking_history();
CREATE INDEX tracking_reference_search ON public.shipments(tenant_id,lower(customer_reference) text_pattern_ops);
CREATE INDEX tracking_number_search ON public.shipments(tenant_id,lower(tracking_number) text_pattern_ops);
CREATE INDEX tracking_store_order_search ON public.shipments(tenant_id,ecommerce_store_id,store_order_id);
CREATE INDEX tracking_period_workspace ON public.shipments(tenant_id,created_at DESC,id);
CREATE INDEX tracking_period_platform ON public.shipments(created_at DESC,id);
CREATE INDEX tracking_store_reference_search ON public.shipments(tenant_id,lower(store_order_id) text_pattern_ops);
CREATE INDEX tracking_return_reference_search ON public.ecommerce_tracking_outbox(tenant_id,store_return_reference,shipment_id);
CREATE INDEX tracking_event_timeline ON public.tracking_events(tenant_id,shipment_id,occurred_at,id);
DO $$
DECLARE name text;
BEGIN
 FOREACH name IN ARRAY ARRAY['tracking_share_links','tracking_customer_requests','tracking_preferences','tracking_notifications','tracking_refresh_jobs',
   'tracking_provider_limits','tracking_case_reviews','tracking_operations_audit'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',name);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated',name);
  IF name='tracking_operations_audit' THEN
   EXECUTE format('GRANT SELECT,INSERT ON public.%I TO service_role',name);
  ELSE
   EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.%I TO service_role',name);
  END IF;
 END LOOP;
END $$;
GRANT USAGE,SELECT ON SEQUENCE public.tracking_operations_audit_id_seq TO service_role;
COMMENT ON TABLE public.tracking_share_links IS 'Hashed bearer capabilities. Immutable shipment membership is validated server-side and tenant-filtered again on every read. No raw tokens.';
COMMENT ON TABLE public.tracking_notifications IS 'Free in-app milestone availability only. No outbound WhatsApp/SMS/email dispatch or customer consent is inferred.';
COMMIT;
