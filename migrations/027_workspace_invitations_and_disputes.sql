-- Workspace invitations and saved disputes; no emails or provider calls.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.workspace_invitations(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 email text NOT NULL CHECK(length(email)<=254),first_name text NOT NULL CHECK(length(first_name) BETWEEN 1 AND 100),
 last_name text NOT NULL CHECK(length(last_name) BETWEEN 1 AND 100),role text NOT NULL CHECK(role IN ('DISPATCHER','ACCOUNTANT')),
 invited_by uuid NOT NULL REFERENCES auth.users(id),auth_user_id uuid REFERENCES auth.users(id),
 status text NOT NULL DEFAULT 'SENDING' CHECK(status IN ('SENDING','PENDING','FAILED','ACCEPTED','CANCELLED')),
 created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT now()+interval '24 hours',accepted_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_workspace_invite ON public.workspace_invitations(lower(email)) WHERE status IN ('SENDING','PENDING');
CREATE INDEX IF NOT EXISTS workspace_invitation_lookup ON public.workspace_invitations(tenant_id,created_at DESC);
CREATE TABLE IF NOT EXISTS public.shipment_dispute_drafts(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,
 content text NOT NULL CHECK(length(content) BETWEEN 10 AND 12000),updated_by uuid NOT NULL REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,shipment_id),FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
ALTER TABLE public.workspace_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shipment_dispute_drafts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.workspace_invitations,public.shipment_dispute_drafts FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.workspace_invitations,public.shipment_dispute_drafts TO service_role;
COMMIT;
