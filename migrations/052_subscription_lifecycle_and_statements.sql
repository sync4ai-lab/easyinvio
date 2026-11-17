-- Apply once after 051. No provider calls or wallet mutations occur in this migration.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.tenants
 ADD COLUMN pending_plan varchar(20) CHECK(pending_plan IN ('STARTER','VELOCITY','COMMAND')),
 ADD COLUMN pending_billing_cycle varchar(15) CHECK(pending_billing_cycle IN ('MONTHLY','ANNUAL')),
 ADD COLUMN pending_plan_effective_at timestamptz,
 ADD COLUMN cancellation_requested_at timestamptz,
 ADD COLUMN cancellation_effective_at timestamptz,
 ADD COLUMN final_notice_prorated_amount numeric(12,2) CHECK(final_notice_prorated_amount>=0),
 ADD COLUMN final_notice_billed boolean NOT NULL DEFAULT false,
 ADD CONSTRAINT subscription_pending_complete CHECK((pending_plan IS NULL)=(pending_billing_cycle IS NULL) AND (pending_plan IS NULL)=(pending_plan_effective_at IS NULL)),
 ADD CONSTRAINT subscription_notice_order CHECK((cancellation_effective_at IS NULL)=(cancellation_requested_at IS NULL)
  AND (cancellation_effective_at IS NULL OR cancellation_effective_at>=cancellation_requested_at)),
 ADD CONSTRAINT subscription_schedule_exclusive CHECK(pending_plan IS NULL OR cancellation_requested_at IS NULL);
ALTER TABLE public.tenants DROP CONSTRAINT tenants_plan_status_check;
ALTER TABLE public.tenants ADD CONSTRAINT tenants_plan_status_check
 CHECK(plan_status IN ('ACTIVE','TRIALING','PAST_DUE','CANCELLED','PENDING_CANCELLATION'));
CREATE OR REPLACE FUNCTION public.effective_subscription_plan(plan text,status text,expires timestamptz) RETURNS text
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT CASE WHEN status IN ('ACTIVE','TRIALING','PENDING_CANCELLATION')
 AND (status NOT IN ('TRIALING','PENDING_CANCELLATION') OR expires IS NOT NULL)
 AND (expires IS NULL OR expires>now()) THEN plan ELSE 'STARTER' END $$;

CREATE TABLE public.subscription_operations(
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 actor_auth_user_id uuid REFERENCES auth.users(id),request_id uuid NOT NULL,
 action text NOT NULL CHECK(action IN ('UPGRADE','DOWNGRADE','CANCEL','NOTICE_CHARGE','DOWNGRADE_RENEWAL','ANNUAL_REFUND')),
 state text NOT NULL CHECK(state IN ('PREVIEW','AUTHORIZED','PROVIDER_PENDING','SCHEDULED','PAID','APPLIED','REVIEW','FAILED','EXPIRED')),
 source_plan text NOT NULL CHECK(source_plan IN ('STARTER','VELOCITY','COMMAND')),
 target_plan text NOT NULL CHECK(target_plan IN ('STARTER','VELOCITY','COMMAND')),
 billing_cycle text NOT NULL CHECK(billing_cycle IN ('MONTHLY','ANNUAL')),
 plan_version integer NOT NULL CHECK(plan_version>0),amount numeric(12,2) NOT NULL CHECK(amount>=0),currency text NOT NULL DEFAULT 'GBP' CHECK(currency='GBP'),
 funding text NOT NULL CHECK(funding IN ('STRIPE','WALLET','NONE')),
 effective_at timestamptz NOT NULL,preview_at timestamptz NOT NULL,expires_at timestamptz NOT NULL,
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),payload_sha256 text NOT NULL,
 provider_invoice_id text UNIQUE,provider_schedule_id text,provider_url text,error_code text,lease_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),applied_at timestamptz,
 UNIQUE(tenant_id,request_id),UNIQUE(tenant_id,id));
CREATE UNIQUE INDEX one_authorized_subscription_change ON public.subscription_operations(tenant_id)
 WHERE state IN ('AUTHORIZED','PROVIDER_PENDING','PAID','REVIEW');
CREATE INDEX subscription_operation_due ON public.subscription_operations(effective_at) WHERE state IN ('AUTHORIZED','SCHEDULED','PAID');
CREATE TABLE public.subscription_change_events(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 operation_id uuid NOT NULL,event_type text NOT NULL,actor_auth_user_id uuid,
 amount numeric(12,2) NOT NULL DEFAULT 0,currency text NOT NULL DEFAULT 'GBP',
 effective_at timestamptz NOT NULL,breakdown jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,operation_id) REFERENCES public.subscription_operations(tenant_id,id),UNIQUE(operation_id,event_type));
CREATE INDEX subscription_change_tenant_period ON public.subscription_change_events(tenant_id,created_at,id);
CREATE TABLE public.billing_statements(
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 statement_number varchar(40) NOT NULL UNIQUE,period_start timestamptz NOT NULL,period_end timestamptz NOT NULL,
 currency varchar(3) NOT NULL CHECK(currency IN ('GBP','EUR','USD')),
 opening_balance numeric(18,2) NOT NULL,total_topups numeric(18,2) NOT NULL,
 subscription_net numeric(18,2) NOT NULL,shipping_net numeric(18,2) NOT NULL,refunds_net numeric(18,2) NOT NULL,
 tax_total numeric(18,2) NOT NULL,gross_total numeric(18,2) NOT NULL,closing_balance numeric(18,2) NOT NULL,
 statement_snapshot jsonb NOT NULL CHECK(jsonb_typeof(statement_snapshot)='object'),snapshot_sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),CHECK(period_end>period_start),
 UNIQUE(tenant_id,period_start,period_end,currency),UNIQUE(tenant_id,id));
CREATE INDEX billing_statements_tenant_period ON public.billing_statements(tenant_id,period_start DESC,id);
ALTER TABLE public.wallet_ledger ADD COLUMN subscription_operation_id uuid;
ALTER TABLE public.wallet_ledger ADD CONSTRAINT wallet_subscription_operation_scope
 FOREIGN KEY(tenant_id,subscription_operation_id) REFERENCES public.subscription_operations(tenant_id,id);
-- Extend only the established event-shape checks; retain all existing financial shapes.
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT conname,pg_get_expr(conbin,conrelid) AS expression FROM pg_constraint
 WHERE conrelid='public.wallet_ledger'::regclass AND contype='c'
 AND (SELECT attnum FROM pg_attribute WHERE attrelid='public.wallet_ledger'::regclass AND attname='entry_type')=ANY(conkey)
 LOOP
  EXECUTE format('ALTER TABLE public.wallet_ledger DROP CONSTRAINT %I',c.conname);
  EXECUTE format('ALTER TABLE public.wallet_ledger ADD CONSTRAINT %I CHECK ((%s) OR
   (entry_type::text=''SUBSCRIPTION_DEBIT'' AND balance_delta<0 AND reserved_delta=0
    AND subscription_operation_id IS NOT NULL AND reservation_id IS NULL AND topup_id IS NULL
    AND stripe_session_id IS NULL AND stripe_event_id IS NULL AND stripe_payment_intent_id IS NULL
    AND insurance_purchase_id IS NULL AND insurance_settlement_id IS NULL))',c.conname,c.expression);
 END LOOP;
END $$;
ALTER TABLE public.wallet_ledger ADD CONSTRAINT wallet_subscription_event_identity
 CHECK((entry_type::text='SUBSCRIPTION_DEBIT')=(subscription_operation_id IS NOT NULL));
CREATE UNIQUE INDEX wallet_subscription_debit_once ON public.wallet_ledger(tenant_id,subscription_operation_id) WHERE subscription_operation_id IS NOT NULL;
ALTER TABLE public.subscription_invoice_receipts ADD COLUMN invoice_net_gbp numeric(18,2),
 ADD COLUMN invoice_tax_gbp numeric(18,2),ADD COLUMN invoice_gross_gbp numeric(18,2),
 ADD COLUMN operation_id uuid REFERENCES public.subscription_operations(id),
 ADD COLUMN invoice_payment_intent_id text,ADD COLUMN invoice_refunded_gbp numeric(18,2) NOT NULL DEFAULT 0,
 ADD COLUMN reconciliation_attempted_at timestamptz;
ALTER TABLE public.subscription_invoice_receipts ADD CONSTRAINT invoice_receipt_tenant_identity UNIQUE(tenant_id,stripe_invoice_id);
CREATE TABLE public.subscription_refunds(
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),operation_id uuid NOT NULL,
 stripe_invoice_id text NOT NULL REFERENCES public.subscription_invoice_receipts(stripe_invoice_id),
 payment_intent_id text NOT NULL,net_amount numeric(12,2) NOT NULL CHECK(net_amount>=0),
 tax_amount numeric(12,2) NOT NULL CHECK(tax_amount>=0),gross_amount numeric(12,2) NOT NULL CHECK(gross_amount>0),
 provider_refund_id text UNIQUE,state text NOT NULL CHECK(state IN ('READY','SUBMITTED','SUCCEEDED','REVIEW')),
 created_at timestamptz NOT NULL DEFAULT now(),settled_at timestamptz,
 FOREIGN KEY(tenant_id,operation_id) REFERENCES public.subscription_operations(tenant_id,id),
 FOREIGN KEY(tenant_id,stripe_invoice_id) REFERENCES public.subscription_invoice_receipts(tenant_id,stripe_invoice_id),
 UNIQUE(operation_id,stripe_invoice_id));
ALTER TABLE public.subscription_refunds ADD CONSTRAINT refund_amount_parts CHECK(net_amount+tax_amount=gross_amount);
ALTER TABLE public.subscription_refunds ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.subscription_refunds FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.subscription_refunds TO service_role;

CREATE FUNCTION public.reject_billing_record_mutation() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'Billing records are append-only' USING ERRCODE='42501'; END $$;
REVOKE ALL ON FUNCTION public.reject_billing_record_mutation() FROM PUBLIC;
CREATE TRIGGER immutable_subscription_changes BEFORE UPDATE OR DELETE ON public.subscription_change_events FOR EACH ROW EXECUTE FUNCTION public.reject_billing_record_mutation();
CREATE TRIGGER immutable_billing_statements BEFORE UPDATE OR DELETE ON public.billing_statements FOR EACH ROW EXECUTE FUNCTION public.reject_billing_record_mutation();
CREATE FUNCTION public.guard_billing_schedule_fields() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (NEW.pending_plan,NEW.pending_billing_cycle,NEW.pending_plan_effective_at,NEW.cancellation_requested_at,
 NEW.cancellation_effective_at,NEW.final_notice_prorated_amount,NEW.final_notice_billed)
 IS DISTINCT FROM (OLD.pending_plan,OLD.pending_billing_cycle,OLD.pending_plan_effective_at,OLD.cancellation_requested_at,
 OLD.cancellation_effective_at,OLD.final_notice_prorated_amount,OLD.final_notice_billed)
 AND NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
 RAISE EXCEPTION 'Billing schedules are server-owned' USING ERRCODE='42501';END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_billing_schedule_fields() FROM PUBLIC;
CREATE TRIGGER guard_billing_schedule_fields BEFORE UPDATE ON public.tenants FOR EACH ROW EXECUTE FUNCTION public.guard_billing_schedule_fields();
ALTER TABLE public.subscription_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.subscription_change_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_statements ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.subscription_operations,public.subscription_change_events,public.billing_statements FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.subscription_operations TO service_role;
GRANT SELECT,INSERT ON public.subscription_change_events,public.billing_statements TO service_role;
COMMIT;
