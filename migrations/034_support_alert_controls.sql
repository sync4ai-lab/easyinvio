-- Administrative pause controls; never grants merchant notification consent.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.whatsapp_bindings ADD COLUMN IF NOT EXISTS alerts_paused boolean NOT NULL DEFAULT false;
COMMIT;
