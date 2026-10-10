-- Owner configuration changes are atomic with a credential-free audit record.
BEGIN;
CREATE TABLE IF NOT EXISTS public.admin_management_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 action text NOT NULL CHECK(action IN ('CREATE_CARRIER','UPDATE_CARRIER','RETIRE_CARRIER','UPDATE_MARGIN','RETIRE_MARGIN')),
 target_id uuid NOT NULL,
 snapshot jsonb NOT NULL CHECK(jsonb_typeof(snapshot)='object'),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS admin_management_tenant_time ON public.admin_management_events(tenant_id,created_at DESC);
ALTER TABLE public.admin_management_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.admin_management_events FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.admin_management_events TO service_role;
COMMIT;
