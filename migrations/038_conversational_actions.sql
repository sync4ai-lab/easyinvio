-- Apply after 037. Private conversational receipts; no changes to financial locks.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.conversational_messages (
 id uuid PRIMARY KEY,
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 channel text NOT NULL CHECK(channel IN ('WHATSAPP','WEB_CHAT')),
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 state text NOT NULL DEFAULT 'PROCESSING' CHECK(state IN ('PROCESSING','COMPLETED','REVIEW_REQUIRED')),
 response jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(response)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),
 completed_at timestamptz,
 UNIQUE(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS conversational_latest_quote ON public.conversational_messages
 (tenant_id,auth_user_id,channel,created_at DESC,id DESC)
 WHERE state='COMPLETED' AND response->>'action_taken'='QUOTE';
CREATE UNIQUE INDEX IF NOT EXISTS conversational_one_processing ON public.conversational_messages
 (tenant_id,auth_user_id,channel) WHERE state='PROCESSING';
ALTER TABLE public.conversational_messages ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.conversational_messages FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.conversational_messages TO service_role;
COMMENT ON TABLE public.conversational_messages IS
 'Authenticated message receipts and ordered quote choices. No raw prompts. PROCESSING after an interruption requires reconciliation, never automatic action replay.';
COMMIT;
