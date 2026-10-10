BEGIN;
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='120s';
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Run the seed as a trusted database administrator';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='shipments' AND column_name='cargo_type') THEN
    RAISE EXCEPTION 'Apply migrations through 013 before seeding';
  END IF;
END $$;
CREATE TABLE IF NOT EXISTS public.fixture_seed_runs (
  batch_tag text PRIMARY KEY,generated_at timestamptz NOT NULL DEFAULT now(),
  completed boolean NOT NULL DEFAULT false,expected_counts jsonb NOT NULL DEFAULT '{}',
  opening_balances jsonb NOT NULL DEFAULT '{}'
);
ALTER TABLE public.fixture_seed_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fixture_seed_runs FROM anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.fixture_seed_runs TO service_role;
INSERT INTO public.fixture_seed_runs(batch_tag) VALUES('veloce-rigorous-v1') ON CONFLICT DO NOTHING;
CREATE TEMP TABLE seed_context ON COMMIT DROP AS
SELECT batch_tag,generated_at AS anchor,NOT completed AS apply_new FROM public.fixture_seed_runs WHERE batch_tag='veloce-rigorous-v1';
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM public.tenants t JOIN generate_series(1,24) n ON t.tenant_id=md5('veloce-rigorous-v1:tenant:'||n)::uuid
    WHERE t.company_profile->>'fixture_batch' IS DISTINCT FROM 'veloce-rigorous-v1') THEN
    RAISE EXCEPTION 'Reserved fixture tenant ID collision; existing records will not be overwritten';
  END IF;
  IF EXISTS(SELECT 1 FROM auth.users u JOIN generate_series(1,24) n CROSS JOIN generate_series(1,3) r
    ON u.id=md5('veloce-rigorous-v1:auth:'||n||':'||r)::uuid
    WHERE u.raw_app_meta_data->>'fixture_batch' IS DISTINCT FROM 'veloce-rigorous-v1') THEN
    RAISE EXCEPTION 'Reserved fixture auth ID collision';
  END IF;
END $$;
-- Suppress only optional CRM queue hooks while inserting fixtures. All FK,
-- CHECK, tenant-protection and immutable-ledger triggers remain enabled.
CREATE TEMP TABLE seed_crm_triggers ON COMMIT DROP AS
SELECT c.relname AS table_name,g.tgname,g.tgenabled FROM pg_trigger g JOIN pg_class c ON c.oid=g.tgrelid
JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
AND ((c.relname='tenants' AND g.tgname='hubspot_tenant_created') OR (c.relname='shipments' AND g.tgname='hubspot_shipping_milestone'));
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT * FROM pg_temp.seed_crm_triggers LOOP
    EXECUTE format('ALTER TABLE public.%I DISABLE TRIGGER %I',r.table_name,r.tgname);
  END LOOP;
END $$;
