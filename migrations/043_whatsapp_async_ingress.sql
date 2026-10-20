-- Apply after 042. Signed ingress and encrypted, ordered conversational replies.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE public.whatsapp_inbound_queue (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 message_sid text NOT NULL UNIQUE CHECK(message_sid ~ '^SM[0-9a-fA-F]{32}$'),
 sender_e164 text NOT NULL CHECK(sender_e164 ~ '^\+[1-9][0-9]{7,14}$'),
 receiver_e164 text NOT NULL CHECK(receiver_e164 ~ '^\+[1-9][0-9]{7,14}$'),
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 payload_ciphertext bytea NOT NULL, key_id text NOT NULL,
 state text NOT NULL DEFAULT 'STAGED' CHECK(state IN ('STAGED','PROCESSING','READY','ACCEPTED','FAILED','REVIEW_REQUIRED')),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 error_code text
);
CREATE INDEX whatsapp_inbound_thread ON public.whatsapp_inbound_queue(receiver_e164,sender_e164,id)
 WHERE state NOT IN ('ACCEPTED','FAILED');
CREATE INDEX whatsapp_inbound_work ON public.whatsapp_inbound_queue(id) WHERE state IN ('STAGED','READY');
CREATE TABLE public.whatsapp_reply_outbox (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 inbound_id bigint NOT NULL REFERENCES public.whatsapp_inbound_queue(id),
 part_index integer NOT NULL CHECK(part_index>=0),
 payload_ciphertext bytea NOT NULL, key_id text NOT NULL,
 state text NOT NULL DEFAULT 'STAGED' CHECK(state IN ('STAGED','SENDING','ACCEPTED','FAILED','REVIEW_REQUIRED')),
 provider_message_sid text UNIQUE CHECK(provider_message_sid ~ '^SM[0-9a-fA-F]{32}$'),
 updated_at timestamptz NOT NULL DEFAULT now(), error_code text,
 UNIQUE(inbound_id,part_index)
);
ALTER TABLE public.whatsapp_inbound_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.whatsapp_reply_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.whatsapp_inbound_queue,public.whatsapp_reply_outbox FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.whatsapp_inbound_queue,public.whatsapp_reply_outbox TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.whatsapp_inbound_queue_id_seq,public.whatsapp_reply_outbox_id_seq TO service_role;
COMMENT ON TABLE public.whatsapp_inbound_queue IS
 'Server-only signed ingress. Encrypted raw events may contain OTPs. PROCESSING/REVIEW_REQUIRED never automatically replay actions. ACCEPTED means REST acceptance, not delivery.';
COMMENT ON TABLE public.whatsapp_reply_outbox IS
 'Encrypted ordered parts. Commit SENDING before REST; ambiguous sends require reconciliation, never automatic resend.';
COMMIT;
