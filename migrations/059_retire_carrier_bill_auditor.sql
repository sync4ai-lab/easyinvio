-- Apply after 058, only after deploying the auditor removal.
-- Removes saved auditor findings. Existing support tickets and financial ledgers stay intact.
-- No CASCADE: unexpected dependencies abort rather than deleting unrelated objects.
BEGIN;
SET LOCAL lock_timeout='10s';
DROP TABLE IF EXISTS public.billing_disputes;
DROP TABLE IF EXISTS public.shipment_dispute_drafts;
COMMIT;
