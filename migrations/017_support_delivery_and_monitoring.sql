-- Optional notification delivery and indexed owner monitoring. No remote calls.
BEGIN;
SET LOCAL lock_timeout='10s';
ALTER TABLE public.whatsapp_bindings ADD COLUMN IF NOT EXISTS notification_opt_in boolean NOT NULL DEFAULT false;
ALTER TABLE public.whatsapp_bindings ADD COLUMN IF NOT EXISTS last_inbound_at timestamptz;
ALTER TABLE public.support_message_outbox ADD COLUMN IF NOT EXISTS provider_message_sid text;
ALTER TABLE public.support_message_outbox ADD COLUMN IF NOT EXISTS attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0);
ALTER TABLE public.support_message_outbox ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.support_message_outbox ADD COLUMN IF NOT EXISTS delivery_updated_at timestamptz;
ALTER TABLE public.support_message_outbox ADD COLUMN IF NOT EXISTS last_error_code text;
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT conname FROM pg_constraint WHERE conrelid='public.support_message_outbox'::regclass
  AND contype='c' AND conkey=ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid='public.support_message_outbox'::regclass AND attname='status')]::smallint[]
 LOOP EXECUTE format('ALTER TABLE public.support_message_outbox DROP CONSTRAINT %I',c.conname); END LOOP;
 ALTER TABLE public.support_message_outbox ADD CONSTRAINT support_message_delivery_status
 CHECK(status IN ('STAGED','SENT','ACCEPTED','DELIVERED','READ','FAILED','CANCELLED','RECONCILIATION_REQUIRED'));
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS support_message_provider_sid ON public.support_message_outbox(provider_message_sid) WHERE provider_message_sid IS NOT NULL;
CREATE INDEX IF NOT EXISTS support_message_ready ON public.support_message_outbox(next_attempt_at,id) WHERE status='STAGED';
CREATE INDEX IF NOT EXISTS platform_booked_reporting ON public.shipments(booked_at,currency) INCLUDE(tenant_id,parcel_count,final_client_price,profit_markup,carrier_code,status);
CREATE INDEX IF NOT EXISTS platform_payment_reporting ON public.wallet_topups(created_at,currency,status) INCLUDE(tenant_id,amount);
CREATE INDEX IF NOT EXISTS platform_active_support ON public.support_tickets(created_at DESC,id) WHERE status IN ('OPEN','IN_REVIEW');
-- Opt-in is server-owned. Browser grants cannot expand notification audiences.
CREATE OR REPLACE FUNCTION public.guard_notification_consent() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' AND NEW.notification_opt_in IS NOT DISTINCT FROM OLD.notification_opt_in
  AND NEW.sender_e164 IS NOT DISTINCT FROM OLD.sender_e164 AND NEW.receiver_e164 IS NOT DISTINCT FROM OLD.receiver_e164
  AND NEW.tenant_id IS NOT DISTINCT FROM OLD.tenant_id AND NEW.user_id IS NOT DISTINCT FROM OLD.user_id
  AND NEW.verified_at IS NOT DISTINCT FROM OLD.verified_at AND NEW.is_active IS NOT DISTINCT FROM OLD.is_active
  AND NEW.last_inbound_at IS NOT DISTINCT FROM OLD.last_inbound_at THEN RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'Notification consent is server-owned' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS guard_notification_consent ON public.whatsapp_bindings;
CREATE TRIGGER guard_notification_consent BEFORE INSERT OR UPDATE OF notification_opt_in,sender_e164,receiver_e164,tenant_id,user_id,verified_at,is_active,last_inbound_at ON public.whatsapp_bindings
FOR EACH ROW EXECUTE FUNCTION public.guard_notification_consent();
COMMIT;
