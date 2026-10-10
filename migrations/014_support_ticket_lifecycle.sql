-- Extend support workflow without removing historical RESOLVED records.
BEGIN;
SET LOCAL lock_timeout='10s';
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT conname FROM pg_constraint WHERE conrelid='public.support_tickets'::regclass
  AND contype='c' AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='public.support_tickets'::regclass AND attname='status')]::smallint[]
 LOOP EXECUTE format('ALTER TABLE public.support_tickets DROP CONSTRAINT %I',c.conname); END LOOP;
 ALTER TABLE public.support_tickets ADD CONSTRAINT support_ticket_workflow_status
  CHECK(status IN ('OPEN','IN_REVIEW','RESOLVED','CLOSED'));
END $$;
ALTER TABLE public.support_tickets ADD COLUMN IF NOT EXISTS archived_at timestamptz;
CREATE INDEX IF NOT EXISTS support_ticket_active_lookup ON public.support_tickets(tenant_id,status,created_at DESC);
COMMIT;
