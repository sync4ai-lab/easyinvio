-- Efficient observed-transit reporting from verified, applied tracking events.
BEGIN;
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='120s';
CREATE INDEX IF NOT EXISTS tracking_applied_transit_reporting
 ON public.tracking_events(tenant_id,shipment_id,occurred_at)
 WHERE status='IN_TRANSIT' AND response->>'applied'='true';
COMMIT;
