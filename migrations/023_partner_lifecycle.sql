-- Run after 022. No external API calls or payment-provider operations occur.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.platform_carrier_connections ADD COLUMN IF NOT EXISTS retired_at timestamptz;
CREATE TABLE IF NOT EXISTS public.partner_unbound_quotes(
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 request_id uuid NOT NULL,
 request_payload jsonb NOT NULL CHECK(jsonb_typeof(request_payload)='object'),
 quote_payload jsonb NOT NULL CHECK(jsonb_typeof(quote_payload)='object'),
 expires_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,request_id)
);
CREATE INDEX IF NOT EXISTS partner_quote_offer_lookup ON public.partner_unbound_quotes USING gin((quote_payload->'rates'));
ALTER TABLE public.partner_unbound_quotes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.partner_unbound_quotes FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,DELETE ON public.partner_unbound_quotes TO service_role;
CREATE TABLE IF NOT EXISTS public.partner_shipping_offers(
 tenant_id uuid NOT NULL,
 offer_id uuid NOT NULL,
 shipment_id uuid NOT NULL,
 rate_snapshot jsonb NOT NULL CHECK(jsonb_typeof(rate_snapshot)='object'),
 expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,offer_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE INDEX IF NOT EXISTS partner_offers_shipment ON public.partner_shipping_offers(tenant_id,shipment_id);
ALTER TABLE public.partner_shipping_offers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.partner_shipping_offers FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,DELETE ON public.partner_shipping_offers TO service_role;
-- Selected offers are private server snapshots, never browser-supplied rates.
CREATE UNIQUE INDEX IF NOT EXISTS shipments_selected_offer_identity
 ON public.shipments(tenant_id,(pricing_snapshot->'selected_rate'->>'offer_id'))
 WHERE pricing_snapshot->'selected_rate'->>'offer_id' IS NOT NULL;
CREATE TABLE IF NOT EXISTS public.partner_cancellations(
 tenant_id uuid NOT NULL,
 shipment_id uuid NOT NULL,
 state text NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','CREDITED')),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,shipment_id),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES public.shipments(tenant_id,id)
);
ALTER TABLE public.partner_cancellations ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0);
ALTER TABLE public.partner_cancellations ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS partner_cancellation_pending ON public.partner_cancellations(next_attempt_at) WHERE state='PENDING';
ALTER TABLE public.partner_cancellations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.partner_cancellations FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.partner_cancellations TO service_role;
-- Preserve every existing ledger rule and add a constrained booking reversal.
DO $$ DECLARE expression text; BEGIN
 SELECT pg_get_expr(conbin,conrelid) INTO expression FROM pg_constraint
 WHERE conrelid='public.wallet_ledger'::regclass AND conname='wallet_ledger_entry_check';
 IF expression IS NULL THEN RAISE EXCEPTION 'Expected wallet ledger validation constraint is missing'; END IF;
 IF position('SHIPMENT_REFUND' in expression)=0 THEN
  ALTER TABLE public.wallet_ledger DROP CONSTRAINT wallet_ledger_entry_check;
  EXECUTE format('ALTER TABLE public.wallet_ledger ADD CONSTRAINT wallet_ledger_entry_check CHECK ((%s) OR
   (entry_type=''SHIPMENT_REFUND'' AND balance_delta>0 AND reserved_delta=0
    AND reservation_id IS NOT NULL AND topup_id IS NULL AND stripe_session_id IS NULL
    AND stripe_event_id IS NULL AND stripe_payment_intent_id IS NULL))',expression);
 END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS wallet_one_shipment_refund
 ON public.wallet_ledger(tenant_id,reservation_id) WHERE entry_type='SHIPMENT_REFUND';
COMMIT;
