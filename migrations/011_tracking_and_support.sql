-- Run the first DO block separately before BEGIN when using a SQL editor
-- that wraps scripts in one transaction. Enum additions must commit first.
DO $$
DECLARE typ text; label text;
BEGIN
  SELECT format('%I.%I',n.nspname,t.typname) INTO typ
  FROM pg_attribute a JOIN pg_type t ON t.oid=a.atttypid JOIN pg_namespace n ON n.oid=t.typnamespace
  WHERE a.attrelid='public.shipments'::regclass AND a.attname='status' AND t.typtype='e';
  IF typ IS NOT NULL THEN
    FOREACH label IN ARRAY ARRAY['IN_TRANSIT','DELIVERED','EXCEPTION'] LOOP
      EXECUTE format('ALTER TYPE %s ADD VALUE IF NOT EXISTS %L',typ,label);
    END LOOP;
  END IF;
END $$;
BEGIN;
ALTER TABLE public.shipments ADD COLUMN IF NOT EXISTS proof_of_delivery_url text;
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname,pg_get_expr(conbin,conrelid) AS expression FROM pg_constraint
    WHERE conrelid='public.shipments'::regclass AND contype='c'
    AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='public.shipments'::regclass AND attname='status')]::smallint[]
  LOOP
    IF position('EXCEPTION' in c.expression)=0 THEN
      EXECUTE format('ALTER TABLE public.shipments DROP CONSTRAINT %I',c.conname);
      EXECUTE format('ALTER TABLE public.shipments ADD CONSTRAINT %I CHECK ((%s) OR status::text IN (%L,%L,%L))',
        c.conname,c.expression,'IN_TRANSIT','DELIVERED','EXCEPTION');
    END IF;
  END LOOP;
END $$;
CREATE TABLE IF NOT EXISTS public.tracking_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL,
  shipment_id uuid NOT NULL,
  integration_key_id text NOT NULL,
  event_id text NOT NULL,
  body_sha256 text NOT NULL,
  status text NOT NULL CHECK(status IN ('IN_TRANSIT','DELIVERED','EXCEPTION')),
  occurred_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  raw_error text NOT NULL DEFAULT '',
  response jsonb NOT NULL,
  support_pending boolean NOT NULL DEFAULT false,
  UNIQUE(tenant_id,integration_key_id,event_id),
  UNIQUE(tenant_id,id),
  FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS public.support_tickets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, shipment_id uuid NOT NULL,
  tracking_event_id uuid NOT NULL UNIQUE,
  status text NOT NULL CHECK(status IN ('OPEN','RESOLVED')),
  ai_summary text NOT NULL, ai_method text NOT NULL, prompt_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,id),
  FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
  FOREIGN KEY(tenant_id,tracking_event_id) REFERENCES public.tracking_events(tenant_id,id)
);
CREATE TABLE IF NOT EXISTS public.support_message_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL, ticket_id uuid NOT NULL,
  recipient_e164 text NOT NULL, body text NOT NULL,
  channel text NOT NULL DEFAULT 'TWILIO_WHATSAPP',
  status text NOT NULL DEFAULT 'STAGED' CHECK(status IN ('STAGED','SENT','FAILED','CANCELLED')),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,ticket_id,recipient_e164),
  FOREIGN KEY(tenant_id,ticket_id) REFERENCES public.support_tickets(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS tracking_lookup ON public.shipments(tenant_id,carrier_account_id,tracking_number) WHERE tracking_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS tracking_support_pending ON public.tracking_events(received_at) WHERE support_pending;
CREATE INDEX IF NOT EXISTS support_tickets_tenant_created ON public.support_tickets(tenant_id,created_at DESC);
CREATE INDEX IF NOT EXISTS shipment_analytics_booked ON public.shipments(tenant_id,booked_at,currency) INCLUDE(parcel_count,final_client_price,profit_markup,status);
CREATE INDEX IF NOT EXISTS wallet_topups_analytics ON public.wallet_topups(tenant_id,created_at DESC,id DESC);
ALTER TABLE public.tracking_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.support_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.support_message_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tracking_events,public.support_tickets,public.support_message_outbox FROM anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.tracking_events,public.support_tickets,public.support_message_outbox TO service_role;
CREATE OR REPLACE FUNCTION public.guard_delivery_proof() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP='INSERT' AND NEW.proof_of_delivery_url IS NULL THEN RETURN NEW; END IF;
  IF TG_OP='UPDATE' AND NEW.proof_of_delivery_url IS NOT DISTINCT FROM OLD.proof_of_delivery_url THEN RETURN NEW; END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Delivery proof is server-owned' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS guard_delivery_proof ON public.shipments;
CREATE TRIGGER guard_delivery_proof BEFORE INSERT OR UPDATE OF proof_of_delivery_url
  ON public.shipments FOR EACH ROW EXECUTE FUNCTION public.guard_delivery_proof();
COMMIT;
