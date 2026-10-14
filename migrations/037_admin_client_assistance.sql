-- Apply after 036. Private, attributable platform support sessions and audit trail.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.admin_client_assistance_sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 operator_membership_id uuid NOT NULL,
 bearer_sha256 text NOT NULL CHECK(bearer_sha256 ~ '^[a-f0-9]{64}$'),
 reason text NOT NULL CHECK(length(btrim(reason)) BETWEEN 10 AND 500),
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL CHECK(expires_at>created_at),revoked_at timestamptz,
 UNIQUE(tenant_id,id),UNIQUE(id,actor_auth_user_id),
 FOREIGN KEY(tenant_id,operator_membership_id) REFERENCES public.users(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS assistance_actor_active ON public.admin_client_assistance_sessions(actor_auth_user_id,expires_at) WHERE revoked_at IS NULL;
CREATE TABLE IF NOT EXISTS public.admin_client_assistance_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 session_id uuid NOT NULL REFERENCES public.admin_client_assistance_sessions(id),
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),tenant_id uuid NOT NULL,
 event_type text NOT NULL CHECK(event_type IN ('SESSION_STARTED','SESSION_ENDED','REQUEST_STARTED','REQUEST_FINISHED')),
 request_id uuid,method text,path text,status_code integer CHECK(status_code BETWEEN 100 AND 599),
 detail jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(detail)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,session_id) REFERENCES public.admin_client_assistance_sessions(tenant_id,id),
 FOREIGN KEY(session_id,actor_auth_user_id) REFERENCES public.admin_client_assistance_sessions(id,actor_auth_user_id),
 CHECK((event_type IN ('SESSION_STARTED','SESSION_ENDED') AND request_id IS NULL)
  OR (event_type IN ('REQUEST_STARTED','REQUEST_FINISHED') AND request_id IS NOT NULL AND method IS NOT NULL AND path IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS assistance_events_workspace ON public.admin_client_assistance_events(tenant_id,id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS assistance_request_event_once ON public.admin_client_assistance_events(request_id,event_type) WHERE request_id IS NOT NULL;
CREATE OR REPLACE FUNCTION public.protect_assistance_event() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'Support audit events are append-only' USING ERRCODE='42501'; END $$;
REVOKE ALL ON FUNCTION public.protect_assistance_event() FROM PUBLIC;
DROP TRIGGER IF EXISTS assistance_event_immutable ON public.admin_client_assistance_events;
CREATE TRIGGER assistance_event_immutable BEFORE UPDATE OR DELETE ON public.admin_client_assistance_events
 FOR EACH ROW EXECUTE FUNCTION public.protect_assistance_event();
ALTER TABLE public.admin_client_assistance_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.admin_client_assistance_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.admin_client_assistance_sessions,public.admin_client_assistance_events FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.admin_client_assistance_sessions TO service_role;
GRANT SELECT,INSERT ON public.admin_client_assistance_events TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.admin_client_assistance_events_id_seq TO service_role;
COMMIT;
