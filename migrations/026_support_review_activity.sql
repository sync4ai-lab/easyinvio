-- Apply after 025. Internal support audit only; no customer messages are sent.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.support_tickets ADD COLUMN IF NOT EXISTS reviewed_by_auth_user_id uuid REFERENCES auth.users(id);
ALTER TABLE public.support_tickets ADD COLUMN IF NOT EXISTS review_started_at timestamptz;
CREATE TABLE IF NOT EXISTS public.support_ticket_activity (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 tenant_id uuid NOT NULL,
 ticket_id uuid NOT NULL,
 actor_auth_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
 actor_name text NOT NULL CHECK(length(actor_name)<=200),
 activity_type text NOT NULL CHECK(activity_type IN ('INTERNAL_NOTE','INTERNAL_REVIEW','RESOLVED')),
 note text NOT NULL DEFAULT '' CHECK(length(note)<=2000),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,ticket_id) REFERENCES public.support_tickets(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS support_activity_timeline ON public.support_ticket_activity(tenant_id,ticket_id,created_at,id);
ALTER TABLE public.support_ticket_activity ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.support_ticket_activity FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.support_ticket_activity TO service_role;
COMMIT;
