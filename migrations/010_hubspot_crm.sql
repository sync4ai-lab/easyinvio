-- Apply after 009. CRM is optional; no remote API requests occur in SQL.
BEGIN;
CREATE TABLE IF NOT EXISTS public.hubspot_sync_jobs (
  tenant_id uuid PRIMARY KEY REFERENCES public.tenants(tenant_id) ON DELETE CASCADE,
  revision bigint NOT NULL DEFAULT 1,
  attempts integer NOT NULL DEFAULT 0,
  blocked boolean NOT NULL DEFAULT false,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.hubspot_tenant_links (
  tenant_id uuid PRIMARY KEY REFERENCES public.tenants(tenant_id) ON DELETE CASCADE,
  company_id text NOT NULL UNIQUE,
  upsell_deal_id text,
  last_synced_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hubspot_pending_jobs ON public.hubspot_sync_jobs(next_attempt_at) WHERE NOT blocked;
ALTER TABLE public.hubspot_sync_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hubspot_tenant_links ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.hubspot_sync_jobs,public.hubspot_tenant_links FROM anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.hubspot_sync_jobs,public.hubspot_tenant_links TO service_role;

CREATE OR REPLACE FUNCTION public.queue_hubspot_sync() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  -- Browser table updates must not manufacture CRM events through this trigger.
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME='shipments' THEN
    IF NEW.status::text NOT IN ('BOOKED','DELIVERED') THEN RETURN NEW; END IF;
    IF TG_OP='UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status
      AND NEW.final_client_price IS NOT DISTINCT FROM OLD.final_client_price
      AND NEW.currency IS NOT DISTINCT FROM OLD.currency THEN RETURN NEW; END IF;
  END IF;
  BEGIN
    INSERT INTO public.hubspot_sync_jobs(tenant_id) VALUES(NEW.tenant_id)
    ON CONFLICT(tenant_id) DO UPDATE SET revision=public.hubspot_sync_jobs.revision+1,
      next_attempt_at=greatest(public.hubspot_sync_jobs.next_attempt_at,now());
  EXCEPTION WHEN OTHERS THEN
    -- CRM queue failures must not invalidate a paid label or tenant creation.
    -- Manual sync can rebuild current cumulative state after reconciliation.
    RAISE WARNING 'Optional CRM enqueue failed; tenant can be resynchronized';
  END;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS hubspot_tenant_created ON public.tenants;
CREATE TRIGGER hubspot_tenant_created AFTER INSERT OR UPDATE OF company_name,company_profile
  ON public.tenants FOR EACH ROW EXECUTE FUNCTION public.queue_hubspot_sync();
DROP TRIGGER IF EXISTS hubspot_shipping_milestone ON public.shipments;
CREATE TRIGGER hubspot_shipping_milestone AFTER INSERT OR UPDATE OF status,final_client_price,currency
  ON public.shipments FOR EACH ROW EXECUTE FUNCTION public.queue_hubspot_sync();
COMMIT;
