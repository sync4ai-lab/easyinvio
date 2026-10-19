-- Apply after 039. Existing workspaces remain BUSINESS; no funds are changed.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS workspace_type text NOT NULL DEFAULT 'BUSINESS'
 CHECK(workspace_type IN ('BUSINESS','INDIVIDUAL'));
ALTER TABLE public.whatsapp_registration_queue ADD COLUMN IF NOT EXISTS workspace_type text NOT NULL DEFAULT 'BUSINESS'
 CHECK(workspace_type IN ('BUSINESS','INDIVIDUAL'));
ALTER TABLE public.whatsapp_registration_queue DROP CONSTRAINT IF EXISTS whatsapp_registration_queue_current_state_check;
ALTER TABLE public.whatsapp_registration_queue ADD CONSTRAINT whatsapp_registration_queue_current_state_check CHECK(current_state IN
 ('PENDING_PERSONA','PENDING_COMPANY','PENDING_PROFILE','PENDING_EMAIL','SENDING_EMAIL','PENDING_OTP','PROVISIONING','VERIFIED','LOCKED','EXPIRED','CANCELLED','RECONCILIATION_REQUIRED'));
ALTER TABLE public.tenants ALTER COLUMN legal_company_name DROP NOT NULL;
ALTER TABLE public.tenants ALTER COLUMN country_code DROP NOT NULL;
ALTER TABLE public.tenants ALTER COLUMN company_registration_number DROP NOT NULL;
CREATE TABLE IF NOT EXISTS public.individual_pricing_settings (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 individual_global_markup_percent numeric(5,2) NOT NULL DEFAULT 20.00 CHECK(individual_global_markup_percent>=0),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 updated_by uuid REFERENCES auth.users(id),updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.individual_pricing_settings(singleton) VALUES(true) ON CONFLICT(singleton) DO NOTHING;
CREATE TABLE IF NOT EXISTS public.individual_pricing_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),request_id uuid NOT NULL,
 previous_percent numeric(5,2) NOT NULL,new_percent numeric(5,2) NOT NULL,
 previous_version integer NOT NULL,version integer NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(actor_auth_user_id,request_id)
);
DROP TRIGGER IF EXISTS individual_pricing_event_immutable ON public.individual_pricing_events;
CREATE TRIGGER individual_pricing_event_immutable BEFORE UPDATE OR DELETE ON public.individual_pricing_events
 FOR EACH ROW EXECUTE FUNCTION public.protect_assistance_event();
CREATE TABLE IF NOT EXISTS public.web_registration_sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),secret_sha256 text NOT NULL CHECK(secret_sha256 ~ '^[a-f0-9]{64}$'),
 email_address text NOT NULL,workspace_type text NOT NULL CHECK(workspace_type IN ('BUSINESS','INDIVIDUAL')),
 profile jsonb NOT NULL CHECK(jsonb_typeof(profile)='object'),
 state text NOT NULL CHECK(state IN ('SENDING_EMAIL','PENDING_OTP','PROVISIONING','VERIFIED','RECONCILIATION_REQUIRED')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 tenant_id uuid NOT NULL DEFAULT gen_random_uuid(),auth_user_id uuid REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT now()+interval '15 minutes'
);
ALTER TABLE public.individual_pricing_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.individual_pricing_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.web_registration_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.individual_pricing_settings,public.individual_pricing_events,public.web_registration_sessions FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.individual_pricing_settings,public.web_registration_sessions TO service_role;
GRANT SELECT,INSERT ON public.individual_pricing_events TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.individual_pricing_events_id_seq TO service_role;
CREATE INDEX IF NOT EXISTS tenants_persona_analytics ON public.tenants(workspace_type,is_sandbox,workspace_status);
CREATE INDEX IF NOT EXISTS web_registration_email ON public.web_registration_sessions(lower(email_address),created_at DESC);
COMMIT;
