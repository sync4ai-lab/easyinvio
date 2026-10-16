-- Apply after 038. Private registration state only; no Auth users or funds are created here.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.whatsapp_registration_queue (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 phone_e164 text NOT NULL CHECK(phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
 receiver_e164 text NOT NULL CHECK(receiver_e164 ~ '^\+[1-9][0-9]{7,14}$'),
 current_state text NOT NULL CHECK(current_state IN
 ('PENDING_COMPANY','PENDING_PROFILE','PENDING_EMAIL','SENDING_EMAIL','PENDING_OTP','PROVISIONING','VERIFIED','LOCKED','EXPIRED','CANCELLED','RECONCILIATION_REQUIRED')),
 company_name text CHECK(length(company_name) BETWEEN 1 AND 200),
 company_reg_number text CHECK(company_reg_number ~ '^[A-Z0-9]{2,100}$'),
 country_code text CHECK(country_code ~ '^[A-Z]{2}$'),
 profile jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(profile)='object'),
 email_address text CHECK(length(email_address)<=254 AND email_address ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'),
 phone_otp_hmac text CHECK(phone_otp_hmac ~ '^[a-f0-9]{64}$'),
 otp_expires_at timestamptz, attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 send_attempts integer NOT NULL DEFAULT 0 CHECK(send_attempts BETWEEN 0 AND 3),
 last_sent_at timestamptz, auth_user_id uuid REFERENCES auth.users(id),
 tenant_id uuid NOT NULL DEFAULT gen_random_uuid(), member_id uuid NOT NULL DEFAULT gen_random_uuid(),
 busy_message_sid text, lease_until timestamptz,
 expires_at timestamptz NOT NULL DEFAULT now()+interval '30 minutes',
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(expires_at>created_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS whatsapp_registration_active_phone ON public.whatsapp_registration_queue(phone_e164,receiver_e164)
 WHERE current_state NOT IN ('EXPIRED','CANCELLED','LOCKED');
CREATE UNIQUE INDEX IF NOT EXISTS whatsapp_registration_active_email ON public.whatsapp_registration_queue(lower(email_address))
 WHERE email_address IS NOT NULL AND current_state NOT IN ('EXPIRED','CANCELLED','LOCKED','VERIFIED');
CREATE UNIQUE INDEX IF NOT EXISTS whatsapp_registration_active_company ON public.whatsapp_registration_queue(country_code,company_reg_number)
 WHERE company_reg_number IS NOT NULL AND current_state NOT IN ('EXPIRED','CANCELLED','LOCKED','VERIFIED');
CREATE TABLE IF NOT EXISTS public.whatsapp_registration_receipts (
 message_sid text PRIMARY KEY CHECK(message_sid ~ '^SM[0-9a-fA-F]{32}$'),
 phone_e164 text NOT NULL,receiver_e164 text NOT NULL,
 input_hmac text NOT NULL CHECK(input_hmac ~ '^[a-f0-9]{64}$'),
 reply_ciphertext bytea, key_id text,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK((reply_ciphertext IS NULL)=(key_id IS NULL))
);
CREATE INDEX IF NOT EXISTS whatsapp_registration_receipts_phone ON public.whatsapp_registration_receipts(phone_e164,created_at);
CREATE INDEX IF NOT EXISTS whatsapp_registration_queue_created ON public.whatsapp_registration_queue(receiver_e164,created_at);
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS onboarding_source text NOT NULL DEFAULT 'UNKNOWN' CHECK(onboarding_source IN ('UNKNOWN','WEB_PORTAL','WHATSAPP_INGRESS'));
COMMENT ON COLUMN public.tenants.onboarding_source IS 'Recorded account creation channel; it does not verify legal company ownership.';
ALTER TABLE public.whatsapp_registration_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.whatsapp_registration_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.whatsapp_registration_queue,public.whatsapp_registration_receipts FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.whatsapp_registration_queue,public.whatsapp_registration_receipts TO service_role;
COMMIT;
