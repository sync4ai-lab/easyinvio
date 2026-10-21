-- Apply after 043. Run as a complete script, without an enclosing transaction:
-- a newly extended shipment enum must commit before MANIFESTED is used.
BEGIN;
DO $$
DECLARE typ text;
BEGIN
 SELECT format('%I.%I',n.nspname,t.typname) INTO typ FROM pg_attribute a
 JOIN pg_type t ON t.oid=a.atttypid JOIN pg_namespace n ON n.oid=t.typnamespace
 WHERE a.attrelid='public.shipments'::regclass AND a.attname='status' AND t.typtype='e';
 IF typ IS NOT NULL THEN EXECUTE format('ALTER TYPE %s ADD VALUE IF NOT EXISTS %L',typ,'MANIFESTED'); END IF;
END $$;
COMMIT;
BEGIN;
SET LOCAL lock_timeout='10s';
DO $$
DECLARE c record;
BEGIN
 FOR c IN SELECT conname,pg_get_expr(conbin,conrelid) expression FROM pg_constraint
 WHERE conrelid='public.shipments'::regclass AND contype='c'
 AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='public.shipments'::regclass AND attname='status')]::smallint[]
 LOOP
  IF position('MANIFESTED' in c.expression)=0 THEN
   EXECUTE format('ALTER TABLE public.shipments DROP CONSTRAINT %I',c.conname);
   EXECUTE format('ALTER TABLE public.shipments ADD CONSTRAINT %I CHECK ((%s) OR status::text=%L)',c.conname,c.expression,'MANIFESTED');
  END IF;
 END LOOP;
END $$;
CREATE TABLE public.carrier_manifests (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 carrier_account_id uuid NOT NULL REFERENCES public.carrier_accounts(id), carrier_code varchar(50) NOT NULL,
 status varchar(30) NOT NULL CHECK(status IN ('DRAFT','SUBMITTED','FAILED','COMPLETED')),
 master_tracking_id varchar(100), manifest_document_url text,
 total_shipments integer NOT NULL CHECK(total_shipments BETWEEN 1 AND 1000),
 total_weight_kg numeric(10,3) NOT NULL CHECK(total_weight_kg>0),
 created_by uuid NOT NULL REFERENCES auth.users(id),
 request_id uuid NOT NULL, input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 provider_reference text, provider_document_url text, document_pdf bytea,
 document_kind text NOT NULL CHECK(document_kind IN ('CARRIER_MANIFEST','INTERNAL_HANDOVER')),
 snapshot jsonb NOT NULL CHECK(jsonb_typeof(snapshot)='array'),
 environment text NOT NULL CHECK(environment IN ('TEST','LIVE')), error_code text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,id), UNIQUE(tenant_id,carrier_account_id,id), UNIQUE(tenant_id,request_id),
 FOREIGN KEY(tenant_id,carrier_account_id) REFERENCES public.carrier_accounts(tenant_id,id),
 CHECK(status<>'COMPLETED' OR document_pdf IS NOT NULL)
);
CREATE INDEX carrier_manifests_workspace ON public.carrier_manifests(tenant_id,created_at DESC,id);
CREATE UNIQUE INDEX carrier_manifest_unconfirmed_once ON public.carrier_manifests(tenant_id,carrier_account_id)
 WHERE status IN ('DRAFT','SUBMITTED');
ALTER TABLE public.shipments ADD COLUMN manifest_id uuid;
ALTER TABLE public.shipments ADD CONSTRAINT shipment_manifest_workspace_fk FOREIGN KEY(tenant_id,manifest_id)
 REFERENCES public.carrier_manifests(tenant_id,id);
ALTER TABLE public.shipments ADD CONSTRAINT shipment_manifest_carrier_fk FOREIGN KEY(tenant_id,carrier_account_id,manifest_id)
 REFERENCES public.carrier_manifests(tenant_id,carrier_account_id,id);
CREATE OR REPLACE FUNCTION public.guard_manifest_assignment() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (NEW.manifest_id IS DISTINCT FROM OLD.manifest_id OR (NEW.status::text='MANIFESTED' AND NEW.status IS DISTINCT FROM OLD.status))
 AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'Manifest assignment is server-owned' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_manifest_assignment() FROM PUBLIC;
CREATE TRIGGER manifest_assignment_server_only BEFORE UPDATE OF manifest_id,status ON public.shipments
 FOR EACH ROW EXECUTE FUNCTION public.guard_manifest_assignment();
CREATE INDEX shipments_unmanifested ON public.shipments(tenant_id,carrier_account_id,status,manifest_id);
CREATE TABLE public.carrier_manifest_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, tenant_id uuid NOT NULL,
 manifest_id uuid NOT NULL, actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 event_type text NOT NULL CHECK(event_type IN ('SUBMITTED','FAILED','COMPLETED')),
 detail jsonb NOT NULL DEFAULT '{}'::jsonb,created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,manifest_id) REFERENCES public.carrier_manifests(tenant_id,id),
 UNIQUE(tenant_id,manifest_id,event_type)
);
CREATE OR REPLACE FUNCTION public.protect_manifest_event() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'Manifest audit events are append-only' USING ERRCODE='42501'; END $$;
REVOKE ALL ON FUNCTION public.protect_manifest_event() FROM PUBLIC;
CREATE TRIGGER manifest_event_immutable BEFORE UPDATE OR DELETE ON public.carrier_manifest_events
 FOR EACH ROW EXECUTE FUNCTION public.protect_manifest_event();
CREATE TABLE public.logistics_media_assets (
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),shipment_id uuid NOT NULL,
 object_key text NOT NULL,content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[a-f0-9]{64}$'),
 mime_type text NOT NULL CHECK(mime_type IN ('image/png','image/jpeg')),
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,shipment_id,content_sha256),
 CHECK(object_key LIKE tenant_id::text||'/'||shipment_id::text||'/%'),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
ALTER TABLE public.whatsapp_reply_outbox ADD COLUMN fallback_for bigint UNIQUE REFERENCES public.whatsapp_reply_outbox(id);
ALTER TABLE public.whatsapp_reply_outbox ADD COLUMN delivery_status text
 CHECK(delivery_status IN ('queued','sending','sent','delivered','read','failed','undelivered','rejected'));
ALTER TABLE public.carrier_manifests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.carrier_manifest_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.logistics_media_assets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.carrier_manifests,public.carrier_manifest_events,public.logistics_media_assets FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.carrier_manifests,public.logistics_media_assets TO service_role;
GRANT SELECT,INSERT ON public.carrier_manifest_events TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.carrier_manifest_events_id_seq TO service_role;
-- Private objects only. No public read or browser write policies are created.
DO $$ BEGIN
 IF to_regclass('storage.buckets') IS NOT NULL THEN
  INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
  VALUES('easyinvio-logistics','easyinvio-logistics',false,5000000,ARRAY['image/png','image/jpeg'])
  ON CONFLICT(id) DO NOTHING;
 END IF;
END $$;
DO $$ BEGIN
 IF to_regclass('storage.objects') IS NOT NULL AND NOT EXISTS(
   SELECT 1 FROM pg_policies WHERE schemaname='storage' AND tablename='objects' AND policyname='easyinvio_logistics_server_only') THEN
  CREATE POLICY easyinvio_logistics_server_only ON storage.objects AS RESTRICTIVE FOR ALL TO anon,authenticated
   USING(bucket_id<>'easyinvio-logistics') WITH CHECK(bucket_id<>'easyinvio-logistics');
 END IF;
END $$;
COMMIT;
