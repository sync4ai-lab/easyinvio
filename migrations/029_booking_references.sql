-- Stable, sequential references for new checkouts; historical references are preserved.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE SEQUENCE IF NOT EXISTS public.easyinvio_booking_reference_sequence;
CREATE TABLE IF NOT EXISTS public.booking_references(
 tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),request_id uuid NOT NULL,
 invoice_reference text NOT NULL UNIQUE,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,request_id)
);
ALTER TABLE public.booking_references ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.booking_references FROM PUBLIC,anon,authenticated;
REVOKE ALL ON SEQUENCE public.easyinvio_booking_reference_sequence FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT ON public.booking_references TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.easyinvio_booking_reference_sequence TO service_role;
COMMIT;
