-- Run the complete file after 049. No provider calls, debits or subscription charges.
-- Existing live tenants are grandfathered until explicitly enrolled by the platform owner.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.tenants
 ADD COLUMN subscription_plan varchar(20) NOT NULL DEFAULT 'STARTER' CHECK(subscription_plan IN ('STARTER','VELOCITY','COMMAND')),
 ADD COLUMN billing_cycle varchar(15) NOT NULL DEFAULT 'MONTHLY' CHECK(billing_cycle IN ('MONTHLY','ANNUAL')),
 ADD COLUMN plan_status varchar(20) NOT NULL DEFAULT 'ACTIVE' CHECK(plan_status IN ('ACTIVE','TRIALING','PAST_DUE','CANCELLED')),
 ADD COLUMN stripe_subscription_id text,
 ADD COLUMN plan_period_start timestamptz NOT NULL DEFAULT now(),
 ADD COLUMN plan_period_end timestamptz,
 ADD COLUMN dedicated_account_manager text CHECK(length(dedicated_account_manager)<=200),
 ADD COLUMN plan_enforcement_enabled boolean NOT NULL DEFAULT false,
 ADD COLUMN subscription_complimentary boolean NOT NULL DEFAULT false,
 ADD COLUMN plan_version integer NOT NULL DEFAULT 1 CHECK(plan_version>0),
 ADD CONSTRAINT subscription_period_valid CHECK(plan_period_end IS NULL OR plan_period_end>plan_period_start),
 ADD CONSTRAINT subscription_trial_end_required CHECK(plan_status<>'TRIALING' OR plan_period_end IS NOT NULL);
CREATE UNIQUE INDEX tenants_stripe_subscription_unique ON public.tenants(stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL;
UPDATE public.tenants SET subscription_plan='COMMAND',subscription_complimentary=true,plan_enforcement_enabled=true WHERE is_sandbox;
ALTER TABLE public.web_registration_sessions
 ADD COLUMN requested_plan text NOT NULL DEFAULT 'STARTER' CHECK(requested_plan IN ('STARTER','VELOCITY','COMMAND')),
 ADD COLUMN requested_cycle text NOT NULL DEFAULT 'MONTHLY' CHECK(requested_cycle IN ('MONTHLY','ANNUAL'));
ALTER TABLE public.margin_rules ADD COLUMN subscription_baseline boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX subscription_margin_currency ON public.margin_rules(tenant_id,currency) WHERE subscription_baseline;
ALTER TABLE public.admin_configuration_events DROP CONSTRAINT admin_configuration_events_operation_check;
ALTER TABLE public.admin_configuration_events ADD CONSTRAINT admin_configuration_events_operation_check
 CHECK(operation IN ('CREATE_TENANT','CREATE_MARGIN','UPDATE_SUBSCRIPTION'));

CREATE FUNCTION public.effective_subscription_plan(plan text,status text,expires timestamptz) RETURNS text
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN status IN ('ACTIVE','TRIALING') AND (status<>'TRIALING' OR expires IS NOT NULL)
 AND (expires IS NULL OR expires>now()) THEN plan ELSE 'STARTER' END $$;
REVOKE ALL ON FUNCTION public.effective_subscription_plan(text,text,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.effective_subscription_plan(text,text,timestamptz) TO service_role;

CREATE FUNCTION public.subscription_usage_period(anchor timestamptz,at_time timestamptz DEFAULT now())
 RETURNS TABLE(period_start timestamptz,period_end timestamptz) LANGUAGE plpgsql STABLE SET search_path=pg_catalog AS $$
DECLARE a timestamp:=anchor AT TIME ZONE 'UTC'; b timestamp:=at_time AT TIME ZONE 'UTC'; n integer; first_day timestamp;
BEGIN
 n:=(extract(year FROM b)::int-extract(year FROM a)::int)*12+extract(month FROM b)::int-extract(month FROM a)::int;
 first_day:=a+make_interval(months=>n);
 IF first_day>b THEN n:=n-1;first_day:=a+make_interval(months=>n); END IF;
 RETURN QUERY SELECT first_day AT TIME ZONE 'UTC',(a+make_interval(months=>n+1)) AT TIME ZONE 'UTC';
END $$;
REVOKE ALL ON FUNCTION public.subscription_usage_period(timestamptz,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.subscription_usage_period(timestamptz,timestamptz) TO service_role;
CREATE VIEW public.v_tenant_monthly_usage WITH(security_invoker=true) AS
 SELECT t.tenant_id,p.period_start,p.period_end,
 coalesce(sum(greatest(coalesce(s.parcel_count,1),1)),0)::bigint AS parcels,count(s.id)::bigint AS shipments
 FROM public.tenants t CROSS JOIN LATERAL public.subscription_usage_period(t.plan_period_start) p
 LEFT JOIN public.shipments s ON s.tenant_id=t.tenant_id AND s.booked_at>=p.period_start AND s.booked_at<p.period_end
 GROUP BY t.tenant_id,p.period_start,p.period_end;
REVOKE ALL ON public.v_tenant_monthly_usage FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.v_tenant_monthly_usage TO service_role;
CREATE INDEX subscription_booked_usage ON public.shipments(tenant_id,booked_at) INCLUDE(parcel_count) WHERE booked_at IS NOT NULL;

CREATE TABLE public.subscription_parcel_reservations(
 tenant_id uuid NOT NULL,shipment_id uuid NOT NULL,period_start timestamptz NOT NULL,period_end timestamptz NOT NULL,
 parcels integer NOT NULL CHECK(parcels>0),state text NOT NULL CHECK(state IN ('HELD','BOOKED','RELEASED')),
 plan text NOT NULL CHECK(plan IN ('STARTER','VELOCITY','COMMAND')),
 projected_overage integer NOT NULL DEFAULT 0 CHECK(projected_overage>=0),
 overage_fee_gbp numeric(8,2) NOT NULL CHECK(overage_fee_gbp>=0),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,shipment_id),FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id));
CREATE INDEX subscription_held_parcels ON public.subscription_parcel_reservations(tenant_id) WHERE state='HELD';
ALTER TABLE public.subscription_parcel_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.subscription_parcel_reservations FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.subscription_parcel_reservations TO service_role;

CREATE FUNCTION public.guard_subscription_fields() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE protected boolean;
BEGIN
 protected:=TG_OP='INSERT';
 IF TG_OP='UPDATE' THEN
 -- Compare subscription fields directly; unrelated tenant changes are not blocked here.
 protected:=(to_jsonb(NEW)->'subscription_plan',to_jsonb(NEW)->'billing_cycle',to_jsonb(NEW)->'plan_status',NEW.stripe_subscription_id,NEW.plan_period_start,NEW.plan_period_end,NEW.dedicated_account_manager,NEW.plan_enforcement_enabled,NEW.subscription_complimentary,NEW.plan_version)
 IS DISTINCT FROM (to_jsonb(OLD)->'subscription_plan',to_jsonb(OLD)->'billing_cycle',to_jsonb(OLD)->'plan_status',OLD.stripe_subscription_id,OLD.plan_period_start,OLD.plan_period_end,OLD.dedicated_account_manager,OLD.plan_enforcement_enabled,OLD.subscription_complimentary,OLD.plan_version);
 END IF;
 IF protected AND NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
 RAISE EXCEPTION 'Subscription configuration is server-owned' USING ERRCODE='42501';END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_subscription_fields() FROM PUBLIC;
CREATE TRIGGER guard_subscription_fields BEFORE INSERT OR UPDATE ON public.tenants FOR EACH ROW EXECUTE FUNCTION public.guard_subscription_fields();

-- The same tenant row lock serializes seats, pending invitations and store registrations.
CREATE FUNCTION public.guard_subscription_capacity() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t public.tenants; p text; used bigint; cap integer; adding boolean;
BEGIN
 SELECT * INTO t FROM public.tenants WHERE tenant_id=NEW.tenant_id FOR UPDATE;
 IF NOT t.plan_enforcement_enabled THEN RETURN NEW;END IF;
 p:=public.effective_subscription_plan(t.subscription_plan,t.plan_status,t.plan_period_end);
 IF TG_TABLE_NAME='users' THEN
 adding:=NEW.is_active AND (TG_OP='INSERT' OR NOT OLD.is_active OR OLD.tenant_id<>NEW.tenant_id);
 IF NOT adding THEN RETURN NEW;END IF;
 cap:=CASE p WHEN 'COMMAND' THEN 10 WHEN 'VELOCITY' THEN 3 ELSE 1 END;
 SELECT (SELECT count(*) FROM public.users WHERE tenant_id=NEW.tenant_id AND is_active AND id<>NEW.id)+
 (SELECT count(*) FROM public.workspace_invitations WHERE tenant_id=NEW.tenant_id AND status IN ('SENDING','PENDING') AND expires_at>now() AND auth_user_id IS DISTINCT FROM NEW.auth_user_id) INTO used;
 ELSIF TG_TABLE_NAME='workspace_invitations' THEN
 adding:=NEW.status IN ('SENDING','PENDING') AND NEW.expires_at>now() AND (TG_OP='INSERT' OR OLD.status NOT IN ('SENDING','PENDING') OR OLD.expires_at<=now());
 IF NOT adding THEN RETURN NEW;END IF;
 cap:=CASE p WHEN 'COMMAND' THEN 10 WHEN 'VELOCITY' THEN 3 ELSE 1 END;
 SELECT (SELECT count(*) FROM public.users WHERE tenant_id=NEW.tenant_id AND is_active)+
 (SELECT count(*) FROM public.workspace_invitations WHERE tenant_id=NEW.tenant_id AND status IN ('SENDING','PENDING') AND expires_at>now() AND id<>NEW.id) INTO used;
 ELSE
 adding:=NEW.is_active AND (TG_OP='INSERT' OR NOT OLD.is_active);
 IF NOT adding THEN RETURN NEW;END IF;
 cap:=CASE p WHEN 'COMMAND' THEN 5 WHEN 'VELOCITY' THEN 2 ELSE 0 END;
 SELECT count(*) INTO used FROM public.ecommerce_stores WHERE tenant_id=NEW.tenant_id AND is_active AND id<>NEW.id;
 END IF;
 IF used>=cap THEN RAISE EXCEPTION 'PLAN_QUOTA_EXCEEDED' USING ERRCODE='P0001',DETAIL=TG_TABLE_NAME;END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_subscription_capacity() FROM PUBLIC;
CREATE TRIGGER subscription_user_quota BEFORE INSERT OR UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.guard_subscription_capacity();
CREATE TRIGGER subscription_invitation_quota BEFORE INSERT OR UPDATE ON public.workspace_invitations FOR EACH ROW EXECUTE FUNCTION public.guard_subscription_capacity();
CREATE TRIGGER subscription_store_quota BEFORE INSERT OR UPDATE ON public.ecommerce_stores FOR EACH ROW EXECUTE FUNCTION public.guard_subscription_capacity();

ALTER TABLE public.shipments ADD COLUMN subscription_quote_plan text,ADD COLUMN subscription_quote_version integer;
CREATE FUNCTION public.stamp_subscription_quote() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t public.tenants;
BEGIN
 SELECT * INTO t FROM public.tenants WHERE tenant_id=NEW.tenant_id;
 IF t.plan_enforcement_enabled THEN
 NEW.subscription_quote_plan:=public.effective_subscription_plan(t.subscription_plan,t.plan_status,t.plan_period_end);
 NEW.subscription_quote_version:=t.plan_version; END IF;RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.stamp_subscription_quote() FROM PUBLIC;
CREATE TRIGGER stamp_subscription_quote BEFORE INSERT OR UPDATE OF final_client_price,quote_expires_at ON public.shipments FOR EACH ROW EXECUTE FUNCTION public.stamp_subscription_quote();

CREATE FUNCTION public.reserve_subscription_parcels() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE t public.tenants; s public.shipments; p text; used bigint; held bigint; cap integer; excess integer; a timestamptz;b timestamptz;fee numeric;
BEGIN
 IF TG_OP='UPDATE' AND NEW.status::text IN ('CAPTURED','RELEASED') THEN
 UPDATE public.subscription_parcel_reservations SET state=CASE WHEN NEW.status::text='CAPTURED' THEN 'BOOKED' ELSE 'RELEASED' END,updated_at=now() WHERE tenant_id=NEW.tenant_id AND shipment_id=NEW.shipment_id;
 RETURN NEW;END IF;
 IF TG_OP<>'INSERT' OR NEW.status::text<>'RESERVED' THEN RETURN NEW;END IF;
 SELECT * INTO t FROM public.tenants WHERE tenant_id=NEW.tenant_id FOR UPDATE;
 IF NOT t.plan_enforcement_enabled THEN RETURN NEW;END IF;
 p:=public.effective_subscription_plan(t.subscription_plan,t.plan_status,t.plan_period_end);
 SELECT * INTO s FROM public.shipments WHERE tenant_id=NEW.tenant_id AND id=NEW.shipment_id;
 IF s.subscription_quote_plan IS DISTINCT FROM p OR s.subscription_quote_version IS DISTINCT FROM t.plan_version THEN RAISE EXCEPTION 'PLAN_CHANGED_REQUOTE_REQUIRED' USING ERRCODE='P0001';END IF;
 SELECT period_start,period_end,parcels INTO a,b,used FROM public.v_tenant_monthly_usage WHERE tenant_id=NEW.tenant_id;
 SELECT coalesce(sum(parcels),0) INTO held FROM public.subscription_parcel_reservations WHERE tenant_id=NEW.tenant_id AND state='HELD';
 cap:=CASE p WHEN 'COMMAND' THEN 4000 WHEN 'VELOCITY' THEN 2000 ELSE 150 END;
 fee:=CASE p WHEN 'COMMAND' THEN 0.02 WHEN 'VELOCITY' THEN 0.05 ELSE 0.15 END;
 excess:=greatest(0,used+held+greatest(coalesce(s.parcel_count,1),1)-cap);
 IF p='STARTER' AND excess>0 THEN RAISE EXCEPTION 'PLAN_PARCEL_QUOTA_EXCEEDED' USING ERRCODE='P0001';END IF;
 INSERT INTO public.subscription_parcel_reservations(tenant_id,shipment_id,period_start,period_end,parcels,state,plan,projected_overage,overage_fee_gbp)
 VALUES(NEW.tenant_id,NEW.shipment_id,a,b,greatest(coalesce(s.parcel_count,1),1),'HELD',p,excess,fee)
 ON CONFLICT(tenant_id,shipment_id) DO UPDATE SET state='HELD',period_start=excluded.period_start,period_end=excluded.period_end,parcels=excluded.parcels,plan=excluded.plan,projected_overage=excluded.projected_overage,overage_fee_gbp=excluded.overage_fee_gbp,updated_at=now();
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.reserve_subscription_parcels() FROM PUBLIC;
CREATE TRIGGER reserve_subscription_parcels BEFORE INSERT OR UPDATE OF status ON public.wallet_reservations FOR EACH ROW EXECUTE FUNCTION public.reserve_subscription_parcels();
COMMENT ON TABLE public.subscription_parcel_reservations IS 'Quota holds follow confirmed financial outcomes. Overages are indicators only: never automatic wallet debits.';

-- Stripe subscription cash receipts are separate from wallet top-ups and label revenue.
CREATE TABLE public.subscription_checkout_receipts(
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 auth_user_id uuid NOT NULL REFERENCES auth.users(id),plan text NOT NULL CHECK(plan IN ('VELOCITY','COMMAND')),
 cycle text NOT NULL CHECK(cycle IN ('MONTHLY','ANNUAL')),price_id text NOT NULL,
 state text NOT NULL CHECK(state IN ('CREATING','READY','REVIEW','COMPLETE','EXPIRED')),
 stripe_session_id text UNIQUE,checkout_url text,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX one_pending_subscription_checkout ON public.subscription_checkout_receipts(tenant_id) WHERE state IN ('CREATING','READY','REVIEW');
CREATE TABLE public.subscription_invoice_receipts(
 stripe_invoice_id text PRIMARY KEY,stripe_subscription_id text NOT NULL,stripe_event_id text NOT NULL UNIQUE,
 tenant_id uuid REFERENCES public.tenants(tenant_id),amount_paid_gbp numeric(18,2) NOT NULL CHECK(amount_paid_gbp>=0),
 paid_at timestamptz NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX subscription_invoice_tenant_period ON public.subscription_invoice_receipts(tenant_id,paid_at);
CREATE TABLE public.subscription_webhook_events(
 stripe_event_id text PRIMARY KEY,event_type text NOT NULL,subscription_id text,event_created_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE public.subscription_checkout_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscription_invoice_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscription_webhook_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.subscription_checkout_receipts,public.subscription_invoice_receipts,public.subscription_webhook_events FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.subscription_checkout_receipts,public.subscription_invoice_receipts TO service_role;
GRANT SELECT,INSERT ON public.subscription_webhook_events TO service_role;
COMMIT;
