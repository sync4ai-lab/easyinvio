-- Optional performance query index; no rates, wallets or existing records changed.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE INDEX IF NOT EXISTS shipments_carrier_history_lane
ON public.shipments(tenant_id,destination_country,(COALESCE(delivered_at,last_tracking_event_at,booked_at,created_at)))
WHERE logistics_metadata->>'synthetic' IS DISTINCT FROM 'true' AND NOT (logistics_metadata ? 'fixture_batch');
COMMIT;
