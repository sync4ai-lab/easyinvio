-- Apply after 054. No calls, purchases, refunds or public-lookup opt-ins.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.tenants ADD COLUMN public_status_lookup_enabled boolean NOT NULL DEFAULT false;
CREATE FUNCTION public.guard_public_status_policy() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.public_status_lookup_enabled IS DISTINCT FROM OLD.public_status_lookup_enabled
 AND NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
 RAISE EXCEPTION 'Public status policy is server-owned' USING ERRCODE='42501';END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_public_status_policy() FROM PUBLIC;
CREATE TRIGGER guard_public_status_policy BEFORE UPDATE ON public.tenants FOR EACH ROW EXECUTE FUNCTION public.guard_public_status_policy();
CREATE TABLE public.whatsapp_guest_drafts (
 provider text NOT NULL,provider_account text NOT NULL,sender_e164 text NOT NULL,receiver_e164 text NOT NULL,
 payload_ciphertext bytea NOT NULL,key_id text NOT NULL,expires_at timestamptz NOT NULL,
 PRIMARY KEY(provider,provider_account,sender_e164,receiver_e164)
);
ALTER TABLE public.whatsapp_guest_drafts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.whatsapp_guest_drafts FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.whatsapp_guest_drafts TO service_role;
CREATE INDEX whatsapp_guest_draft_expiry ON public.whatsapp_guest_drafts(expires_at);
CREATE INDEX whatsapp_public_tracking_reference ON public.shipments(tracking_number) WHERE tracking_number IS NOT NULL;
COMMIT;
