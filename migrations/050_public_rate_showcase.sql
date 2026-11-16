-- Stores sanitized marketing examples only. No customer addresses, quote IDs or credentials.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE IF NOT EXISTS public.public_rate_showcase_cache (
 source_key text PRIMARY KEY CHECK(source_key ~ '^[a-f0-9]{64}$'),
 attempted_at timestamptz NOT NULL,
 payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(payload)='object')
);
ALTER TABLE public.public_rate_showcase_cache ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.public_rate_showcase_cache FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.public_rate_showcase_cache TO service_role;
COMMENT ON TABLE public.public_rate_showcase_cache IS 'Fixed public marketing comparisons. Read only through sanitized API projection; refreshed only from explicitly approved LIVE workspace connections.';
COMMIT;
