BEGIN;
ALTER TABLE public.support_tickets ADD COLUMN IF NOT EXISTS manual_note text NOT NULL DEFAULT '';
COMMIT;
