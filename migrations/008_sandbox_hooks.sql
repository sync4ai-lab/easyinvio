-- Apply after migrations 006 and 007 in a dedicated Supabase sandbox project.
BEGIN;
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS is_sandbox boolean NOT NULL DEFAULT false;
ALTER TABLE public.wallet_topups ADD COLUMN IF NOT EXISTS is_sandbox boolean NOT NULL DEFAULT false;
ALTER TABLE public.wallet_topups ADD COLUMN IF NOT EXISTS sandbox_test_token text;
ALTER TABLE public.wallet_topups ADD COLUMN IF NOT EXISTS stripe_payment_intent_id text;
ALTER TABLE public.wallet_ledger ADD COLUMN IF NOT EXISTS stripe_payment_intent_id text;
CREATE UNIQUE INDEX IF NOT EXISTS wallet_topups_payment_intent_unique
    ON public.wallet_topups(stripe_payment_intent_id) WHERE stripe_payment_intent_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS wallet_ledger_payment_intent_unique
    ON public.wallet_ledger(stripe_payment_intent_id) WHERE stripe_payment_intent_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS whatsapp_active_phone_binding_unique
    ON public.whatsapp_bindings(sender_e164,receiver_e164) WHERE is_active=true;

CREATE OR REPLACE FUNCTION public.guard_sandbox_flags()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF TG_OP='INSERT' THEN
        IF NOT NEW.is_sandbox THEN RETURN NEW; END IF;
    ELSIF NEW.is_sandbox IS NOT DISTINCT FROM OLD.is_sandbox THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Sandbox environment flags are server-owned' USING ERRCODE='42501';
    END IF;
    IF TG_TABLE_NAME='tenants' AND TG_OP='UPDATE' AND OLD.is_sandbox AND NOT NEW.is_sandbox THEN
        RAISE EXCEPTION 'Sandbox tenants cannot be converted into live accounts';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS guard_sandbox_flags ON public.tenants;
CREATE TRIGGER guard_sandbox_flags BEFORE INSERT OR UPDATE OF is_sandbox ON public.tenants
    FOR EACH ROW EXECUTE FUNCTION public.guard_sandbox_flags();
DROP TRIGGER IF EXISTS guard_sandbox_flags ON public.wallet_topups;
CREATE TRIGGER guard_sandbox_flags BEFORE INSERT OR UPDATE OF is_sandbox ON public.wallet_topups
    FOR EACH ROW EXECUTE FUNCTION public.guard_sandbox_flags();
COMMIT;
