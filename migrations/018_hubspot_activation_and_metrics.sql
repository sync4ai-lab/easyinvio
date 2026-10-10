-- Apply after 017. No external CRM calls occur in this migration.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.hubspot_tenant_links ADD COLUMN IF NOT EXISTS contact_id text;
ALTER TABLE public.hubspot_tenant_links ADD COLUMN IF NOT EXISTS portal_id bigint;
CREATE UNIQUE INDEX IF NOT EXISTS hubspot_company_portal_identity ON public.hubspot_tenant_links(portal_id,company_id);
CREATE INDEX IF NOT EXISTS hubspot_lifetime_metrics ON public.shipments(tenant_id,status)
  INCLUDE(parcel_count,final_client_price,currency);
CREATE TABLE IF NOT EXISTS public.hubspot_activation_jobs (
  portal_id bigint NOT NULL CHECK(portal_id>0),
  deal_id text NOT NULL CHECK(deal_id ~ '^[0-9]+$'),
  tenant_id uuid REFERENCES public.tenants(tenant_id),
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
  blocked boolean NOT NULL DEFAULT false,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  PRIMARY KEY(portal_id,deal_id)
);
CREATE INDEX IF NOT EXISTS hubspot_activation_pending ON public.hubspot_activation_jobs(portal_id,next_attempt_at)
  WHERE completed_at IS NULL AND NOT blocked;
ALTER TABLE public.hubspot_activation_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.hubspot_activation_jobs FROM anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.hubspot_activation_jobs TO service_role;
CREATE OR REPLACE FUNCTION public.guard_hubspot_references() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP='INSERT' AND NOT (NEW.company_profile ? 'hubspot') THEN RETURN NEW; END IF;
  IF TG_OP='UPDATE' AND NEW.company_profile->'hubspot' IS NOT DISTINCT FROM OLD.company_profile->'hubspot' THEN RETURN NEW; END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
    RAISE EXCEPTION 'HubSpot references are server-owned' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS guard_hubspot_references ON public.tenants;
CREATE TRIGGER guard_hubspot_references BEFORE INSERT OR UPDATE OF company_profile ON public.tenants
  FOR EACH ROW EXECUTE FUNCTION public.guard_hubspot_references();
CREATE OR REPLACE FUNCTION public.queue_hubspot_wallet_sync() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP='UPDATE' AND NEW.balance IS NOT DISTINCT FROM OLD.balance
    AND NEW.currency IS NOT DISTINCT FROM OLD.currency THEN RETURN NEW; END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN RETURN NEW; END IF;
  -- Synthetic seed opening credits are deliberately excluded from CRM sync.
  IF EXISTS(SELECT 1 FROM public.tenants WHERE tenant_id=NEW.tenant_id AND company_profile ? 'fixture_batch') THEN RETURN NEW; END IF;
  BEGIN
    INSERT INTO public.hubspot_sync_jobs(tenant_id) VALUES(NEW.tenant_id)
    ON CONFLICT(tenant_id) DO UPDATE SET revision=public.hubspot_sync_jobs.revision+1,
      next_attempt_at=greatest(public.hubspot_sync_jobs.next_attempt_at,now());
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'Optional wallet CRM enqueue failed; reconcile with manual sync';
  END;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS hubspot_wallet_changed ON public.wallets;
CREATE TRIGGER hubspot_wallet_changed AFTER INSERT OR UPDATE OF balance,currency ON public.wallets
  FOR EACH ROW EXECUTE FUNCTION public.queue_hubspot_wallet_sync();
COMMIT;
