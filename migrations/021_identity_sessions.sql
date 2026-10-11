BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.app_auth_sessions(
 id uuid PRIMARY KEY,auth_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 tenant_id uuid REFERENCES public.tenants(tenant_id),provider_token bytea NOT NULL,key_id text NOT NULL,
 expires_at timestamptz NOT NULL,created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_sessions_expiry ON public.app_auth_sessions(expires_at);
CREATE TABLE IF NOT EXISTS public.app_user_profiles(
 auth_user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
 full_name text NOT NULL DEFAULT '' CHECK(length(full_name)<=200),
 phone_e164 text CHECK(phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.app_login_limits(
 bucket text PRIMARY KEY,window_start timestamptz NOT NULL DEFAULT now(),attempts integer NOT NULL CHECK(attempts>0)
);
ALTER TABLE public.app_auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_login_limits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.app_auth_sessions,public.app_user_profiles,public.app_login_limits FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.app_auth_sessions,public.app_user_profiles,public.app_login_limits TO service_role;
COMMIT;
