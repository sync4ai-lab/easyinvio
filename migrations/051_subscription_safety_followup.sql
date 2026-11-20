-- Migration 050 has already been applied. Run this follow-up once; do not rerun 050.
BEGIN;
SET LOCAL lock_timeout='10s';
-- A left join with no shipments must report zero parcels, not one.
CREATE OR REPLACE VIEW public.v_tenant_monthly_usage WITH(security_invoker=true) AS
 SELECT t.tenant_id,p.period_start,p.period_end,
 coalesce(sum(greatest(coalesce(s.parcel_count,1),1)) FILTER(WHERE s.id IS NOT NULL),0)::bigint AS parcels,
 count(s.id)::bigint AS shipments
 FROM public.tenants t CROSS JOIN LATERAL public.subscription_usage_period(t.plan_period_start) p
 LEFT JOIN public.shipments s ON s.tenant_id=t.tenant_id AND s.booked_at>=p.period_start AND s.booked_at<p.period_end
 GROUP BY t.tenant_id,p.period_start,p.period_end;
REVOKE ALL ON public.v_tenant_monthly_usage FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.v_tenant_monthly_usage TO service_role;

-- Defense in depth for every tenant-specific carrier/rule writer, including staff tools.
-- Shared platform carrier connections are separate and unaffected.
CREATE FUNCTION public.guard_subscription_commercial_feature() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t public.tenants;
BEGIN
 SELECT * INTO t FROM public.tenants WHERE tenant_id=NEW.tenant_id FOR UPDATE;
 IF NOT t.plan_enforcement_enabled THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='margin_rules' THEN
   IF NEW.subscription_baseline OR NOT NEW.is_active THEN RETURN NEW; END IF;
 ELSIF TG_TABLE_NAME='carrier_accounts' THEN
   IF NOT NEW.is_active OR NEW.platform_connection_id IS NOT NULL THEN RETURN NEW; END IF;
 END IF;
 IF public.effective_subscription_plan(t.subscription_plan,t.plan_status,t.plan_period_end)<>'COMMAND' THEN
   RAISE EXCEPTION 'PLAN_UPGRADE_REQUIRED' USING ERRCODE='P0001',DETAIL=TG_TABLE_NAME;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_subscription_commercial_feature() FROM PUBLIC;
CREATE TRIGGER subscription_margin_feature BEFORE INSERT OR UPDATE ON public.margin_rules
 FOR EACH ROW EXECUTE FUNCTION public.guard_subscription_commercial_feature();
CREATE TRIGGER subscription_byoc_feature BEFORE INSERT OR UPDATE ON public.carrier_accounts
 FOR EACH ROW EXECUTE FUNCTION public.guard_subscription_commercial_feature();
COMMENT ON FUNCTION public.guard_subscription_commercial_feature() IS 'Command bespoke pricing and tenant-specific BYOC; never changes customer roles or shared platform connections.';
COMMIT;
