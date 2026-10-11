-- Apply after 018. Server-owned durable Stripe snapshot reconciliation.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.wallet_topups ADD COLUMN IF NOT EXISTS transaction_state text NOT NULL DEFAULT 'PENDING'
  CHECK(transaction_state IN ('PENDING','SUCCESS','FAILED'));
UPDATE public.wallet_topups SET transaction_state=CASE WHEN status::text='CREDITED' THEN 'SUCCESS'
  WHEN status::text='FAILED' THEN 'FAILED' ELSE 'PENDING' END;
DO $$ DECLARE c record; BEGIN
  FOR c IN SELECT conname,pg_get_expr(conbin,conrelid) AS expression FROM pg_constraint
    WHERE conrelid='public.wallet_topups'::regclass AND contype='c'
    AND (SELECT attnum FROM pg_attribute WHERE attrelid='public.wallet_topups'::regclass AND attname='status')=ANY(conkey)
  LOOP
    IF position('FAILED' in c.expression)=0 THEN
      EXECUTE format('ALTER TABLE public.wallet_topups DROP CONSTRAINT %I',c.conname);
      EXECUTE format('ALTER TABLE public.wallet_topups ADD CONSTRAINT %I CHECK ((%s) OR
        (status::text=%L AND credited_at IS NULL))',c.conname,c.expression,'FAILED');
    END IF;
  END LOOP;
END $$;
CREATE OR REPLACE FUNCTION public.guard_stripe_transaction_trace() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
  IF TG_OP='INSERT' AND NEW.transaction_state='PENDING' AND NEW.stripe_payment_intent_id IS NULL THEN RETURN NEW; END IF;
  IF TG_OP='UPDATE' AND NEW.transaction_state IS NOT DISTINCT FROM OLD.transaction_state
    AND NEW.stripe_payment_intent_id IS NOT DISTINCT FROM OLD.stripe_payment_intent_id THEN RETURN NEW; END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Stripe transaction trace is server-owned' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS guard_stripe_transaction_trace ON public.wallet_topups;
CREATE TRIGGER guard_stripe_transaction_trace BEFORE INSERT OR UPDATE OF transaction_state,stripe_payment_intent_id
  ON public.wallet_topups FOR EACH ROW EXECUTE FUNCTION public.guard_stripe_transaction_trace();
CREATE TABLE IF NOT EXISTS public.stripe_webhook_events (
  event_id text PRIMARY KEY CHECK(event_id ~ '^evt_'),
  event_type text NOT NULL CHECK(event_type IN ('checkout.session.completed','charge.refunded','charge.failed')),
  api_version text,
  livemode boolean NOT NULL,
  payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
  payload_sha256 text NOT NULL,
  status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','DONE','RECONCILIATION_REQUIRED')),
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error text,
  result jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS stripe_pending_snapshot_events ON public.stripe_webhook_events(livemode,next_attempt_at) WHERE status='PENDING';
CREATE UNIQUE INDEX IF NOT EXISTS wallet_topups_tenant_identity ON public.wallet_topups(tenant_id,id);
-- A funding credit stays unique, while one top-up can have several refund debits.
DROP INDEX IF EXISTS public.wallet_ledger_topup_unique;
CREATE UNIQUE INDEX wallet_ledger_topup_unique ON public.wallet_ledger(tenant_id,topup_id)
  WHERE topup_id IS NOT NULL AND entry_type='TOPUP';
CREATE TABLE IF NOT EXISTS public.stripe_charge_refunds (
  charge_id text PRIMARY KEY CHECK(charge_id ~ '^ch_'),
  tenant_id uuid NOT NULL,
  topup_id uuid NOT NULL,
  payment_intent_id text NOT NULL,
  applied_refund_minor bigint NOT NULL DEFAULT 0 CHECK(applied_refund_minor>=0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(tenant_id,topup_id) REFERENCES public.wallet_topups(tenant_id,id)
);
ALTER TABLE public.stripe_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stripe_charge_refunds ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stripe_webhook_events,public.stripe_charge_refunds FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.stripe_webhook_events,public.stripe_charge_refunds TO service_role;
-- Preserve the existing credit/reserve/capture/release shape checks.
DO $$ DECLARE c record; BEGIN
  FOR c IN SELECT conname,pg_get_expr(conbin,conrelid) AS expression FROM pg_constraint
    WHERE conrelid='public.wallet_ledger'::regclass AND contype='c'
    AND (SELECT attnum FROM pg_attribute WHERE attrelid='public.wallet_ledger'::regclass AND attname='entry_type')=ANY(conkey)
  LOOP
    IF position('REFUND_DEBIT' in c.expression)=0 THEN
      EXECUTE format('ALTER TABLE public.wallet_ledger DROP CONSTRAINT %I',c.conname);
      EXECUTE format('ALTER TABLE public.wallet_ledger ADD CONSTRAINT %I CHECK ((%s) OR
        (entry_type::text=%L AND balance_delta<0 AND reserved_delta=0 AND topup_id IS NOT NULL
         AND reservation_id IS NULL AND stripe_session_id IS NULL AND stripe_payment_intent_id IS NULL
         AND stripe_event_id IS NOT NULL))',c.conname,c.expression,'REFUND_DEBIT');
    END IF;
  END LOOP;
END $$;
COMMIT;
