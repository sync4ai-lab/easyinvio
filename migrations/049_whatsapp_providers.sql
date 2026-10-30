-- Apply once after 048. No identity/consent grants or sends.
BEGIN;
SET LOCAL lock_timeout='10s';
DO $$ BEGIN
 IF to_regclass('public.platform_staff') IS NULL OR to_regclass('public.shipment_sender_notifications') IS NULL
 OR to_regclass('public.whatsapp_registration_receipts') IS NULL THEN
 RAISE EXCEPTION '049 requires complete migrations through 048, including 039 and 043-047'; END IF;
END $$;
ALTER TABLE public.whatsapp_inbound_queue ADD COLUMN provider text NOT NULL DEFAULT 'TWILIO' CHECK(provider IN ('TWILIO','GUPSHUP')),
 ADD COLUMN provider_account text NOT NULL DEFAULT '', ADD COLUMN external_message_id text,
 ADD COLUMN provider_received_at timestamptz;
ALTER TABLE public.whatsapp_inbound_queue DROP CONSTRAINT whatsapp_inbound_queue_message_sid_check;
ALTER TABLE public.whatsapp_inbound_queue ADD CHECK(message_sid ~ '^SM[0-9a-fA-F]{32}$' OR message_sid ~ '^gs:[a-f0-9]{64}$');
CREATE UNIQUE INDEX whatsapp_external_identity ON public.whatsapp_inbound_queue(provider,provider_account,external_message_id) WHERE external_message_id IS NOT NULL;
ALTER TABLE public.whatsapp_registration_receipts DROP CONSTRAINT whatsapp_registration_receipts_message_sid_check;
ALTER TABLE public.whatsapp_registration_receipts ADD CHECK(message_sid ~ '^SM[0-9a-fA-F]{32}$' OR message_sid ~ '^gs:[a-f0-9]{64}$');
ALTER TABLE public.whatsapp_reply_outbox DROP CONSTRAINT whatsapp_reply_outbox_provider_message_sid_check;
ALTER TABLE public.whatsapp_reply_outbox DROP CONSTRAINT whatsapp_reply_outbox_provider_message_sid_key;
ALTER TABLE public.whatsapp_reply_outbox ADD COLUMN provider text NOT NULL DEFAULT 'TWILIO' CHECK(provider IN ('TWILIO','GUPSHUP')),
 ADD COLUMN provider_account text NOT NULL DEFAULT '';
CREATE UNIQUE INDEX whatsapp_reply_external_identity ON public.whatsapp_reply_outbox(provider,provider_account,provider_message_sid) WHERE provider_message_sid IS NOT NULL;
ALTER TABLE public.support_message_outbox ADD COLUMN provider text CHECK(provider IN ('TWILIO','GUPSHUP')), ADD COLUMN provider_account text NOT NULL DEFAULT '';
ALTER TABLE public.shipment_sender_notifications ADD COLUMN provider text CHECK(provider IN ('TWILIO','GUPSHUP')), ADD COLUMN provider_account text NOT NULL DEFAULT '', ADD COLUMN delivery_status text;
ALTER TABLE public.return_customer_deliveries ADD COLUMN provider text CHECK(provider IN ('TWILIO','GUPSHUP')), ADD COLUMN provider_account text NOT NULL DEFAULT '', ADD COLUMN delivery_status text;
UPDATE public.support_message_outbox SET provider='TWILIO';
DROP INDEX IF EXISTS public.support_message_provider_sid;
CREATE UNIQUE INDEX support_message_provider_sid ON public.support_message_outbox(provider,provider_account,provider_message_sid) WHERE provider_message_sid IS NOT NULL;
UPDATE public.shipment_sender_notifications SET provider='TWILIO' WHERE channel='WHATSAPP';
UPDATE public.return_customer_deliveries SET provider='TWILIO' WHERE channel='WHATSAPP';
CREATE TABLE public.whatsapp_delivery_attempts (
 id uuid PRIMARY KEY, provider text NOT NULL CHECK(provider IN ('TWILIO','GUPSHUP')),
 provider_account text NOT NULL, logical_key text NOT NULL, tenant_id uuid REFERENCES public.tenants(tenant_id),
 kind text NOT NULL CHECK(kind IN ('CHAT','SUPPORT','SHIPMENT','RETURN')), target_id text NOT NULL,
 source_e164 text NOT NULL, recipient_e164 text NOT NULL,
 category text NOT NULL, template_name text, template_id text, template_language text,
 state text NOT NULL CHECK(state IN ('SENDING','ACCEPTED','FAILED','REVIEW_REQUIRED')),
 external_id text, whatsapp_id text, delivery_status text, error_code text,
 monetary_cost numeric, cost_currency text, cost_state text NOT NULL DEFAULT 'UNKNOWN' CHECK(cost_state='UNKNOWN'),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(provider,provider_account,logical_key), UNIQUE(provider,provider_account,external_id)
);
CREATE TABLE public.whatsapp_delivery_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 provider text NOT NULL CHECK(provider='GUPSHUP'), provider_account text NOT NULL,
 event_sha256 text NOT NULL CHECK(event_sha256 ~ '^[a-f0-9]{64}$'), external_id text, whatsapp_id text,
 recipient_e164 text NOT NULL, status text NOT NULL CHECK(status IN ('ACCEPTED','SENT','DELIVERED','READ','FAILED')),
 occurred_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(), applied boolean NOT NULL DEFAULT false,
 UNIQUE(provider,provider_account,event_sha256)
);
CREATE INDEX whatsapp_unapplied_events ON public.whatsapp_delivery_events(id) WHERE NOT applied;
ALTER TABLE public.whatsapp_delivery_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.whatsapp_delivery_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.whatsapp_delivery_attempts,public.whatsapp_delivery_events FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.whatsapp_delivery_attempts,public.whatsapp_delivery_events TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.whatsapp_delivery_events_id_seq TO service_role;
COMMENT ON TABLE public.whatsapp_delivery_attempts IS 'Commit before external send. Unknown cost remains NULL/UNKNOWN. No provider failover or uncertain replay.';
COMMENT ON COLUMN public.whatsapp_inbound_queue.provider_account IS 'Legacy blank means unbackfilled Twilio account; encrypted payload identity is rechecked. No bindings or consent are migrated.';
COMMIT;
