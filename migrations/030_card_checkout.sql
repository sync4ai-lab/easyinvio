-- Durable card-funded baskets; no Stripe calls or wallet balance changes.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.payment_carts(
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES public.tenants(tenant_id),
 requested_by uuid NOT NULL REFERENCES auth.users(id),
 offers jsonb NOT NULL CHECK(jsonb_typeof(offers)='array' AND jsonb_array_length(offers) BETWEEN 1 AND 100),
 amount numeric(14,2) NOT NULL CHECK(amount>=1 AND amount<=10000),currency text NOT NULL CHECK(currency IN ('GBP','EUR','USD')),
 status text NOT NULL DEFAULT 'CREATING' CHECK(status IN ('CREATING','AWAITING_PAYMENT','BOOKING','COMPLETED','REVIEW_REQUIRED')),
 results jsonb,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS payment_cart_pending ON public.payment_carts(updated_at) WHERE status IN ('CREATING','AWAITING_PAYMENT','BOOKING');
ALTER TABLE public.payment_carts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.payment_carts FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.payment_carts TO service_role;
COMMIT;
