-- Optional performance index for the durable Sendcloud label worker; apply after 024.
-- No enum changes, external operations or data mutations.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE INDEX IF NOT EXISTS shipment_pending_label_poll
 ON public.shipments(updated_at,id)
 WHERE status='BOOKING' AND logistics_metadata->>'label_lifecycle_status'='SYNC_PENDING';
COMMIT;
