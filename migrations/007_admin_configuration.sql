-- Apply after the original tenancy/pricing migrations and migration 006.
-- Existing tenants/margin_rules/wallets/users columns used by main.py remain
-- the base schema contract; this migration adds platform-owned profile/audit data.
BEGIN;
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS company_name text NOT NULL DEFAULT '';
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS company_profile jsonb NOT NULL DEFAULT '{}'::jsonb;
-- Keep Decimal writes exact even if the original column has a narrow scale.
ALTER TABLE public.margin_rules ALTER COLUMN markup_value TYPE numeric USING markup_value::numeric;

CREATE TABLE IF NOT EXISTS public.admin_configuration_events (
    id uuid PRIMARY KEY,
    actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
    operation text NOT NULL CHECK (operation IN ('CREATE_TENANT','CREATE_MARGIN')),
    request_id uuid NOT NULL,
    tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
    payload_sha256 text NOT NULL CHECK (length(payload_sha256)=64),
    response jsonb NOT NULL CHECK (jsonb_typeof(response)='object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(actor_auth_user_id,operation,request_id)
);
ALTER TABLE public.admin_configuration_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.admin_configuration_events FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.admin_configuration_events TO service_role;

CREATE INDEX IF NOT EXISTS margin_rules_tenant_currency_priority_idx
    ON public.margin_rules (tenant_id,currency,priority,created_at,id) WHERE is_active=true;
-- Preserve read policies, but prevent clients from bypassing the owner-only
-- controller through existing broad PostgREST UPDATE grants/policies.
CREATE OR REPLACE FUNCTION public.guard_platform_configuration()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE protected_change boolean := true;
BEGIN
    IF TG_TABLE_NAME='tenants' AND TG_OP='UPDATE' THEN
        protected_change :=
            NEW.billing_plan IS DISTINCT FROM OLD.billing_plan OR
            NEW.default_currency IS DISTINCT FROM OLD.default_currency OR
            NEW.billing_status IS DISTINCT FROM OLD.billing_status OR
            NEW.workspace_status IS DISTINCT FROM OLD.workspace_status OR
            NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id;
    END IF;
    IF protected_change AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname=current_user AND (rolsuper OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'Platform configuration is server-owned' USING ERRCODE='42501';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS guard_platform_configuration ON public.margin_rules;
CREATE TRIGGER guard_platform_configuration BEFORE INSERT OR UPDATE OR DELETE
    ON public.margin_rules FOR EACH ROW EXECUTE FUNCTION public.guard_platform_configuration();
DROP TRIGGER IF EXISTS guard_platform_configuration ON public.tenants;
CREATE TRIGGER guard_platform_configuration BEFORE INSERT OR UPDATE OR DELETE
    ON public.tenants FOR EACH ROW EXECUTE FUNCTION public.guard_platform_configuration();
COMMENT ON COLUMN public.tenants.company_profile IS 'Validated B2B company and billing profile recorded by platform administration.';
COMMIT;
