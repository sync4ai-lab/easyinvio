-- Platform-owned provider credentials; tenant rows retain shipment FK isolation.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.platform_carrier_connections(
 id uuid PRIMARY KEY, account_name text NOT NULL, aggregator text NOT NULL CHECK(aggregator IN ('EASYPOST','REGIONAL')),
 regional_provider_code text, api_base_url text NOT NULL, upstream_account_id text,
 environment text NOT NULL CHECK(environment IN ('TEST','LIVE')),
 credentials_ciphertext bytea NOT NULL, credential_key_id text NOT NULL,
 priority integer NOT NULL CHECK(priority BETWEEN 0 AND 1000000),
 timeout_seconds integer NOT NULL CHECK(timeout_seconds BETWEEN 1 AND 120),
 is_active boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.platform_carrier_connections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.platform_carrier_connections FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.platform_carrier_connections TO service_role;
ALTER TABLE public.carrier_accounts ADD COLUMN IF NOT EXISTS platform_connection_id uuid REFERENCES public.platform_carrier_connections(id);
CREATE UNIQUE INDEX IF NOT EXISTS tenant_platform_connection ON public.carrier_accounts(tenant_id,platform_connection_id) WHERE platform_connection_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS public.platform_carrier_events(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 connection_id uuid NOT NULL REFERENCES public.platform_carrier_connections(id),
 action text NOT NULL CHECK(action IN ('SAVE','RETIRE')), snapshot jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.platform_carrier_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.platform_carrier_events FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.platform_carrier_events TO service_role;
-- Separate wrappers avoid accessing a record field not present on the other table.
CREATE OR REPLACE FUNCTION public.lock_platform_carrier_catalog() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('platform-carriers',0));
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS lock_platform_carrier_catalog ON public.platform_carrier_connections;
CREATE TRIGGER lock_platform_carrier_catalog BEFORE INSERT OR UPDATE ON public.platform_carrier_connections
 FOR EACH ROW EXECUTE FUNCTION public.lock_platform_carrier_catalog();
DROP TRIGGER IF EXISTS lock_tenant_platform_catalog ON public.tenants;
CREATE TRIGGER lock_tenant_platform_catalog BEFORE INSERT ON public.tenants
 FOR EACH ROW EXECUTE FUNCTION public.lock_platform_carrier_catalog();
CREATE OR REPLACE FUNCTION public.platform_carrier_changed() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 INSERT INTO public.carrier_accounts(id,tenant_id,platform_connection_id,account_name,aggregator,
  regional_provider_code,api_base_url,upstream_account_id,environment,credentials_ciphertext,credential_key_id,priority,timeout_seconds,is_active)
 SELECT gen_random_uuid(),t.tenant_id,NEW.id,NEW.account_name,NEW.aggregator,NEW.regional_provider_code,
  NEW.api_base_url,NEW.upstream_account_id,NEW.environment,NEW.credentials_ciphertext,NEW.credential_key_id,
  NEW.priority,NEW.timeout_seconds,NEW.is_active AND t.workspace_status='ACTIVE'
 FROM public.tenants t WHERE t.is_sandbox=(NEW.environment='TEST')
 ON CONFLICT(tenant_id,platform_connection_id) WHERE platform_connection_id IS NOT NULL DO UPDATE SET
  account_name=excluded.account_name,aggregator=excluded.aggregator,regional_provider_code=excluded.regional_provider_code,
  api_base_url=excluded.api_base_url,upstream_account_id=excluded.upstream_account_id,environment=excluded.environment,
  credentials_ciphertext=excluded.credentials_ciphertext,credential_key_id=excluded.credential_key_id,
  priority=excluded.priority,timeout_seconds=excluded.timeout_seconds,is_active=excluded.is_active;
 UPDATE public.carrier_accounts a SET is_active=false FROM public.tenants t
 WHERE a.tenant_id=t.tenant_id AND a.platform_connection_id=NEW.id AND t.is_sandbox<>(NEW.environment='TEST');
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION public.tenant_platform_carriers() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN RETURN NEW; END IF;
 INSERT INTO public.carrier_accounts(id,tenant_id,platform_connection_id,account_name,aggregator,
  regional_provider_code,api_base_url,upstream_account_id,environment,credentials_ciphertext,credential_key_id,priority,timeout_seconds,is_active)
 SELECT gen_random_uuid(),NEW.tenant_id,p.id,p.account_name,p.aggregator,p.regional_provider_code,p.api_base_url,
  p.upstream_account_id,p.environment,p.credentials_ciphertext,p.credential_key_id,p.priority,p.timeout_seconds,
  p.is_active AND NEW.workspace_status='ACTIVE' FROM public.platform_carrier_connections p WHERE NEW.is_sandbox=(p.environment='TEST')
 ON CONFLICT(tenant_id,platform_connection_id) WHERE platform_connection_id IS NOT NULL DO UPDATE SET is_active=excluded.is_active;
 UPDATE public.carrier_accounts a SET is_active=false FROM public.platform_carrier_connections p
 WHERE a.tenant_id=NEW.tenant_id AND a.platform_connection_id=p.id AND NEW.is_sandbox<>(p.environment='TEST');
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION public.guard_platform_carrier_link() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.platform_connection_id IS NOT NULL OR (TG_OP='UPDATE' AND OLD.platform_connection_id IS NOT NULL) THEN
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
   RAISE EXCEPTION 'Platform carrier links are server-owned' USING ERRCODE='42501';
  END IF;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS guard_platform_carrier_link ON public.carrier_accounts;
CREATE TRIGGER guard_platform_carrier_link BEFORE INSERT OR UPDATE ON public.carrier_accounts FOR EACH ROW EXECUTE FUNCTION public.guard_platform_carrier_link();
DROP TRIGGER IF EXISTS platform_carrier_changed ON public.platform_carrier_connections;
CREATE TRIGGER platform_carrier_changed AFTER INSERT OR UPDATE ON public.platform_carrier_connections FOR EACH ROW EXECUTE FUNCTION public.platform_carrier_changed();
DROP TRIGGER IF EXISTS tenant_platform_carriers ON public.tenants;
CREATE TRIGGER tenant_platform_carriers AFTER INSERT OR UPDATE OF is_sandbox,workspace_status ON public.tenants FOR EACH ROW EXECUTE FUNCTION public.tenant_platform_carriers();
COMMIT;
