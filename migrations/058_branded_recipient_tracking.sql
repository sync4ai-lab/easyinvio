-- Apply once after 057. No historical sends, provider calls or purchases.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.ecommerce_stores
 ADD COLUMN brand_display_name text CHECK(length(brand_display_name) BETWEEN 1 AND 100),
 ADD COLUMN brand_logo_url text CHECK(length(brand_logo_url)<=2048 AND brand_logo_url ~ '^https://'),
 ADD COLUMN brand_accent_hex text CHECK(brand_accent_hex ~ '^#[0-9A-Fa-f]{6}$'),
 ADD COLUMN support_url text CHECK(length(support_url)<=2048 AND support_url ~ '^https://'),
 ADD COLUMN buyer_notification_policy jsonb NOT NULL DEFAULT '{"email":false,"whatsapp":false,"categories":["IN_TRANSIT","OUT_FOR_DELIVERY","AVAILABLE_FOR_PICKUP","DELIVERED","EXCEPTION"]}' CHECK(jsonb_typeof(buyer_notification_policy)='object');
CREATE INDEX shipments_public_tracking_number ON public.shipments(tracking_number);
CREATE INDEX shipments_public_package_tracking ON public.shipments USING gin ((logistics_metadata->'automation_label'->'package_labels') jsonb_path_ops);
CREATE TABLE public.tracking_public_limits(
 subject_sha256 text NOT NULL CHECK(subject_sha256 ~ '^[a-f0-9]{64}$'),bucket bigint NOT NULL,
 requests integer NOT NULL CHECK(requests>0),expires_at timestamptz NOT NULL,
 PRIMARY KEY(subject_sha256,bucket));
CREATE INDEX tracking_public_limit_expiry ON public.tracking_public_limits(expires_at);
CREATE TABLE public.tracking_recipient_access(
 token_sha256 text PRIMARY KEY CHECK(token_sha256 ~ '^[a-f0-9]{64}$'),
 tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,share_link_id uuid NOT NULL UNIQUE,
 source_share_link_id uuid,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '30 minutes',created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 FOREIGN KEY(tenant_id,share_link_id) REFERENCES public.tracking_share_links(tenant_id,id),
 FOREIGN KEY(tenant_id,source_share_link_id) REFERENCES public.tracking_share_links(tenant_id,id));
CREATE INDEX tracking_recipient_access_expiry ON public.tracking_recipient_access(expires_at);
CREATE TABLE public.shipment_recipient_preferences(
 tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,
 email boolean NOT NULL DEFAULT false,whatsapp boolean NOT NULL DEFAULT false,
 contact_sha256 text NOT NULL CHECK(contact_sha256 ~ '^[a-f0-9]{64}$'),
 authorized_by uuid REFERENCES auth.users(id),capability_sha256 text,
 updated_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,shipment_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id),
 CHECK((authorized_by IS NOT NULL) <> (capability_sha256 IS NOT NULL)));
-- Reuse the existing durable delivery queue and SHIPMENT receipt reconciliation.
-- Older sender-only workers select READY. Keep unsent buyer jobs invisible to
-- those workers while Local/UAT and Production share the database.
ALTER TABLE public.shipment_sender_notifications DROP CONSTRAINT shipment_sender_notifications_state_check;
ALTER TABLE public.shipment_sender_notifications ADD CONSTRAINT shipment_notice_state CHECK(state IN ('READY','BUYER_READY','SENDING','ACCEPTED','FAILED','SKIPPED','REVIEW_REQUIRED'));
ALTER TABLE public.shipment_sender_notifications ADD COLUMN audience text NOT NULL DEFAULT 'SENDER' CHECK(audience IN ('SENDER','RECIPIENT'));
DO $$ DECLARE item record; BEGIN
 FOR item IN SELECT conname FROM pg_constraint WHERE conrelid='public.shipment_sender_notifications'::regclass AND contype='u'
 LOOP EXECUTE format('ALTER TABLE public.shipment_sender_notifications DROP CONSTRAINT %I',item.conname);END LOOP;
END $$;
ALTER TABLE public.shipment_sender_notifications ADD CONSTRAINT shipment_notice_audience_dedupe UNIQUE(tenant_id,shipment_id,category,channel,audience);
DO $$ DECLARE name text; BEGIN
 FOREACH name IN ARRAY ARRAY['tracking_public_limits','tracking_recipient_access','shipment_recipient_preferences'] LOOP
 EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',name);
 EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated',name);
 EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO service_role',name);
 END LOOP;
END $$;
COMMENT ON TABLE public.tracking_recipient_access IS '30-minute scoped access; hashed tokens only, source share revocation rechecked on every use.';
COMMENT ON COLUMN public.shipment_sender_notifications.audience IS 'Existing sender routing preserved. Buyer routing requires store policy, recorded recipient permission and configured delivery channels.';
COMMENT ON TABLE public.shipment_sender_notifications IS 'Durable sender and consented recipient SHIPMENT delivery; deduplicated by tenant, shipment, category, channel and audience. No historical buyer backfill.';
COMMIT;
