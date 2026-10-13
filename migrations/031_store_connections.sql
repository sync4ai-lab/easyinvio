-- Private tenant-bound store credentials. No marketplace requests or messages.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.workspace_store_connections (
 tenant_id uuid NOT NULL,
 store_id uuid NOT NULL,
 credentials_ciphertext bytea NOT NULL,
 credential_key_id text NOT NULL,
 updated_by uuid NOT NULL REFERENCES auth.users(id),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,store_id),
 FOREIGN KEY(tenant_id,store_id) REFERENCES public.ecommerce_stores(tenant_id,id)
);
ALTER TABLE public.workspace_store_connections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.workspace_store_connections FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.workspace_store_connections TO service_role;
COMMIT;
