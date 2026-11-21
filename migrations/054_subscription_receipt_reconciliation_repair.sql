-- Apply after 053. Repairs databases that applied an earlier revision of 052.
-- Metadata-only addition: no provider calls, charges, refunds or wallet changes.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.subscription_invoice_receipts
 ADD COLUMN IF NOT EXISTS reconciliation_attempted_at timestamptz;
COMMIT;
