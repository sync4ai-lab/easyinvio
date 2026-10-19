-- Apply after 041. Durable return commands; existing wallet locks remain authoritative.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.reverse_logistics_requests (
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 id uuid NOT NULL,
 original_shipment_id uuid NOT NULL,
 requested_by uuid NOT NULL REFERENCES auth.users(id),
 source text NOT NULL CHECK(source IN ('API','WEB_CHAT','WHATSAPP','STOREFRONT','MARKETPLACE')),
 charge_bearer text NOT NULL CHECK(charge_bearer IN ('RETAILER_PAY','CUSTOMER_PAY')),
 input_sha256 text NOT NULL CHECK(input_sha256 ~ '^[a-f0-9]{64}$'),
 state text NOT NULL DEFAULT 'PROCESSING' CHECK(state IN ('PROCESSING','BOOKED','PAYMENT_REQUIRED','REVIEW_REQUIRED')),
 return_shipment_id uuid,
 response jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(response)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,original_shipment_id),
 FOREIGN KEY(tenant_id,original_shipment_id) REFERENCES public.shipments(tenant_id,id),
 FOREIGN KEY(tenant_id,return_shipment_id) REFERENCES public.shipments(tenant_id,id)
);
COMMENT ON TABLE public.reverse_logistics_requests IS
 'One full-parcel return command per outbound shipment. Interrupted commands require reconciliation, never automatic mutation replay. Customer payment uses the existing card basket ledger.';
CREATE INDEX IF NOT EXISTS reverse_logistics_workspace ON public.reverse_logistics_requests(tenant_id,created_at DESC);
ALTER TABLE public.reverse_logistics_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.reverse_logistics_requests FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.reverse_logistics_requests TO service_role;
COMMIT;
