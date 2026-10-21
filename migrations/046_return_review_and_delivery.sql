-- Apply after 045. Reviewed returns reuse the existing booking and card ledgers.
BEGIN;
SET LOCAL lock_timeout='10s';
DO $$
BEGIN
 IF to_regclass('public.reverse_logistics_requests') IS NULL OR
    to_regclass('public.partner_shipping_offers') IS NULL THEN
  RAISE EXCEPTION 'Migration 046 requires complete migrations 042 through 045';
 END IF;
END $$;
CREATE TABLE public.return_review_sessions (
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id), id uuid NOT NULL,
 original_shipment_id uuid NOT NULL, requested_by uuid NOT NULL REFERENCES auth.users(id),
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 charge_bearer text NOT NULL CHECK(charge_bearer IN ('RETAILER_PAY','CUSTOMER_PAY')),
 state text NOT NULL CHECK(state IN ('PREPARING','QUOTED','PROCESSING','PAYMENT_REQUIRED','BOOKED','REVIEW_REQUIRED')),
 return_shipment_id uuid, selected_offer_id uuid, response jsonb NOT NULL DEFAULT '{}'::jsonb,
 delivery jsonb NOT NULL DEFAULT '{}'::jsonb, expires_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id), CHECK(jsonb_typeof(response)='object' AND jsonb_typeof(delivery)='object'),
 FOREIGN KEY(tenant_id,original_shipment_id) REFERENCES public.shipments(tenant_id,id),
 FOREIGN KEY(tenant_id,return_shipment_id) REFERENCES public.shipments(tenant_id,id)
);
CREATE INDEX return_review_pending ON public.return_review_sessions(updated_at)
 WHERE state IN ('PROCESSING','PAYMENT_REQUIRED');
CREATE TABLE public.return_customer_deliveries (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, tenant_id uuid NOT NULL, review_id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('PAYMENT','LABEL')),
 channel text NOT NULL CHECK(channel IN ('EMAIL','WHATSAPP')),
 state text NOT NULL DEFAULT 'READY' CHECK(state IN ('READY','SENDING','ACCEPTED','FAILED','REVIEW_REQUIRED')),
 provider_reference text, error_code text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,review_id,kind,channel),
 FOREIGN KEY(tenant_id,review_id) REFERENCES public.return_review_sessions(tenant_id,id)
);
CREATE INDEX return_delivery_ready ON public.return_customer_deliveries(id) WHERE state='READY';
ALTER TABLE public.return_review_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.return_customer_deliveries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.return_review_sessions,public.return_customer_deliveries FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.return_review_sessions,public.return_customer_deliveries TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.return_customer_deliveries_id_seq TO service_role;
COMMENT ON TABLE public.return_customer_deliveries IS
 'Transactional customer return notices only. Commit SENDING before network dispatch. Ambiguous sends require reconciliation, never automatic replay. ACCEPTED is not delivery proof.';
COMMIT;
