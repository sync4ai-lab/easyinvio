-- Apply after 040. Explicit commercial classification, never demographic inference.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS seller_classification text NOT NULL DEFAULT 'STANDARD'
 CHECK(seller_classification IN ('STANDARD','HIGH_VOLUME_COST_SENSITIVE_SELLER'));
ALTER TABLE public.admin_management_events DROP CONSTRAINT IF EXISTS admin_management_events_action_check;
ALTER TABLE public.admin_management_events ADD CONSTRAINT admin_management_events_action_check CHECK(action IN
 ('CREATE_CARRIER','UPDATE_CARRIER','RETIRE_CARRIER','UPDATE_MARGIN','RETIRE_MARGIN','UPDATE_SELLER_CLASSIFICATION'));
CREATE OR REPLACE FUNCTION public.guard_workspace_strategy() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (NEW.workspace_type IS DISTINCT FROM OLD.workspace_type OR NEW.seller_classification IS DISTINCT FROM OLD.seller_classification)
 AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'Workspace strategy is server-owned' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_workspace_strategy() FROM PUBLIC;
DROP TRIGGER IF EXISTS guard_workspace_strategy ON public.tenants;
CREATE TRIGGER guard_workspace_strategy BEFORE UPDATE OF workspace_type,seller_classification ON public.tenants
 FOR EACH ROW EXECUTE FUNCTION public.guard_workspace_strategy();
COMMIT;
