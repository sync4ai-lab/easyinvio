-- Apply once, after 047. This migration does not grant anybody staff access.
BEGIN;
SET LOCAL lock_timeout='10s';
CREATE TABLE public.platform_staff (
 auth_user_id uuid PRIMARY KEY REFERENCES auth.users(id),
 role text NOT NULL DEFAULT 'AGENT' CHECK(role='AGENT'),
 is_active boolean NOT NULL DEFAULT true,
 created_by uuid NOT NULL REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.platform_staff_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 staff_auth_user_id uuid NOT NULL REFERENCES auth.users(id),
 is_active boolean NOT NULL, reason text NOT NULL CHECK(length(reason) BETWEEN 10 AND 500),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION public.guard_staff_membership() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.auth_user_id::text,48001));
 IF NEW.is_active AND TG_TABLE_NAME='platform_staff' THEN
  IF EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=NEW.auth_user_id AND is_active) THEN
   RAISE EXCEPTION 'Deactivate customer membership before granting staff access' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.is_active AND TG_TABLE_NAME='users' THEN
  IF EXISTS(SELECT 1 FROM public.platform_staff WHERE auth_user_id=NEW.auth_user_id AND is_active) THEN
   RAISE EXCEPTION 'Platform staff must use audited client assistance' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.guard_staff_membership() FROM PUBLIC;
CREATE TRIGGER platform_staff_membership_guard BEFORE INSERT OR UPDATE ON public.platform_staff
 FOR EACH ROW EXECUTE FUNCTION public.guard_staff_membership();
CREATE TRIGGER customer_staff_membership_guard BEFORE INSERT OR UPDATE ON public.users
 FOR EACH ROW EXECUTE FUNCTION public.guard_staff_membership();
CREATE TRIGGER platform_staff_events_immutable BEFORE UPDATE OR DELETE ON public.platform_staff_events
 FOR EACH ROW EXECUTE FUNCTION public.protect_tracking_history();
ALTER TABLE public.platform_staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_staff_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.platform_staff,public.platform_staff_events FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.platform_staff TO service_role;
GRANT SELECT,INSERT ON public.platform_staff_events TO service_role;
GRANT USAGE,SELECT ON SEQUENCE public.platform_staff_events_id_seq TO service_role;
COMMENT ON TABLE public.platform_staff IS 'EasyInvio support agents only. Root remains in the server allowlist. Tenant OWNER/ADMIN grants no platform authority.';
COMMIT;
