-- Run after the original tenancy, shipment and financial migrations.
-- Adds audit/tracking metadata without altering existing grants or RLS.
BEGIN;
ALTER TABLE public.shipments
    ADD COLUMN IF NOT EXISTS logistics_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN public.shipments.logistics_metadata IS
    'Server-recorded invoice_baseline, tracking history and logistics metadata. Never accept audit baselines from invoice uploaders.';
-- Table-level UPDATE grants can otherwise permit clients to forge baselines.
-- Preserve existing RLS and only restrict writes to this server-owned column.
CREATE OR REPLACE FUNCTION public.guard_logistics_metadata()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE changed boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        changed := NEW.logistics_metadata IS DISTINCT FROM '{}'::jsonb;
    ELSE
        changed := NEW.logistics_metadata IS DISTINCT FROM OLD.logistics_metadata;
    END IF;
    IF changed AND NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = current_user AND (rolsuper OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'Logistics audit metadata is server-owned' USING ERRCODE = '42501';
    END IF;
    IF jsonb_typeof(NEW.logistics_metadata) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'Logistics metadata must be a JSON object';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS guard_logistics_metadata ON public.shipments;
CREATE TRIGGER guard_logistics_metadata BEFORE INSERT OR UPDATE OF logistics_metadata
    ON public.shipments FOR EACH ROW EXECUTE FUNCTION public.guard_logistics_metadata();
COMMIT;
