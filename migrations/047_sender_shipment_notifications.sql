-- Apply after complete 046. Transactional sender updates; no retroactive sends.
BEGIN;
SET LOCAL lock_timeout='10s';
DO $$ BEGIN
 IF to_regclass('public.shipments') IS NULL OR to_regclass('public.tracking_events') IS NULL
 OR to_regclass('public.return_customer_deliveries') IS NULL THEN
  RAISE EXCEPTION 'Migration 047 requires complete migrations through 046' USING ERRCODE='55000';
 END IF;
END $$;
CREATE TABLE public.shipment_sender_notifications (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 tenant_id uuid NOT NULL, shipment_id uuid NOT NULL,
 category text NOT NULL CHECK(category IN ('BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','OUT_FOR_DELIVERY','AVAILABLE_FOR_PICKUP','DELIVERED','EXCEPTION','RETURNED_TO_SENDER','CANCELLED')),
 channel text NOT NULL CHECK(channel IN ('EMAIL','WHATSAPP')),
 environment text NOT NULL CHECK(environment IN ('TEST','LIVE')),
 state text NOT NULL DEFAULT 'READY' CHECK(state IN ('READY','SENDING','ACCEPTED','FAILED','SKIPPED','REVIEW_REQUIRED')),
 provider_reference text, error_code text,
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
 next_attempt_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,shipment_id,category,channel),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE INDEX shipment_sender_notification_ready ON public.shipment_sender_notifications(next_attempt_at,id) WHERE state='READY';
ALTER TABLE public.shipment_sender_notifications ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.shipment_sender_notifications FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.shipment_sender_notifications TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.shipment_sender_notifications_id_seq TO service_role;
CREATE FUNCTION public.queue_sender_shipment_milestone() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE shipment public.shipments%ROWTYPE; category text; preferences jsonb; environment text;
BEGIN
 IF TG_TABLE_NAME='tracking_events' THEN
  IF NEW.response->>'applied' IS DISTINCT FROM 'true' THEN RETURN NEW; END IF;
  SELECT * INTO shipment FROM public.shipments WHERE tenant_id=NEW.tenant_id AND id=NEW.shipment_id;
  category:=coalesce(NEW.response->'tracking_detail'->>'milestone',NEW.status::text);
  IF category='DELIVERED' AND shipment.status::text<>'DELIVERED' THEN RETURN NEW; END IF;
 ELSE
  IF TG_OP='UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status THEN RETURN NEW; END IF;
  shipment:=NEW; category:=NEW.status::text;
 END IF;
 IF category NOT IN ('BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','OUT_FOR_DELIVERY','AVAILABLE_FOR_PICKUP','DELIVERED','EXCEPTION','RETURNED_TO_SENDER','CANCELLED') THEN RETURN NEW; END IF;
 IF shipment.booked_at IS NULL THEN RETURN NEW; END IF;
 SELECT CASE WHEN is_sandbox THEN 'TEST' ELSE 'LIVE' END INTO environment FROM public.tenants WHERE tenant_id=shipment.tenant_id;
 preferences:=coalesce(shipment.logistics_metadata->'automation_order'->'sender_notifications','{}'::jsonb);
 IF preferences->>'email' IS DISTINCT FROM 'false' AND
    coalesce(shipment.logistics_metadata->'automation_order'->'origin'->>'email',shipment.sender_address->>'email','')<>'' THEN
  INSERT INTO public.shipment_sender_notifications(tenant_id,shipment_id,category,channel,environment)
  VALUES(shipment.tenant_id,shipment.id,category,'EMAIL',environment) ON CONFLICT DO NOTHING;
 END IF;
 IF preferences->>'whatsapp'='true' AND preferences->>'whatsapp_permission_confirmed'='true' AND
    coalesce(shipment.logistics_metadata->'automation_order'->'origin'->>'phone',shipment.sender_address->>'phone','')<>'' THEN
  INSERT INTO public.shipment_sender_notifications(tenant_id,shipment_id,category,channel,environment)
  VALUES(shipment.tenant_id,shipment.id,category,'WHATSAPP',environment) ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.queue_sender_shipment_milestone() FROM PUBLIC;
CREATE TRIGGER shipment_sender_status_notice AFTER INSERT OR UPDATE OF status ON public.shipments
 FOR EACH ROW EXECUTE FUNCTION public.queue_sender_shipment_milestone();
CREATE TRIGGER shipment_sender_tracking_notice AFTER INSERT ON public.tracking_events
 FOR EACH ROW EXECUTE FUNCTION public.queue_sender_shipment_milestone();
COMMENT ON TABLE public.shipment_sender_notifications IS
 'Sender transactional milestones once per category/channel. No raw contacts or tokens. Commit SENDING before network; ambiguous sends require review. No historical backfill. ACCEPTED is not delivery proof.';
COMMIT;
