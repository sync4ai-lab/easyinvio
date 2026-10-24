-- Platform owner / Supabase SQL Editor only. Requires migration 048.
-- Default INSPECT is read-only. Edit the parameters, review results, then choose
-- ASSIGN_AGENT, DISABLE_AGENT or ASSIGN_CUSTOMER and run the complete transaction.
-- SUPER_ADMIN is configured in PLATFORM_ADMIN_USER_IDS, never assigned here.
BEGIN;
SET LOCAL lock_timeout='10s';
SET LOCAL easyinvio.access_action='INSPECT';
SET LOCAL easyinvio.target_email='replace-user@example.invalid';
SET LOCAL easyinvio.actor_id='00000000-0000-0000-0000-000000000000';
SET LOCAL easyinvio.tenant_id='00000000-0000-0000-0000-000000000000';
SET LOCAL easyinvio.customer_role='DISPATCHER';
SET LOCAL easyinvio.display_name='';
SET LOCAL easyinvio.access_reason='';

DO $$
DECLARE
 action text:=current_setting('easyinvio.access_action');
 principal uuid; actor uuid:=current_setting('easyinvio.actor_id')::uuid;
 workspace uuid:=current_setting('easyinvio.tenant_id')::uuid;
 wanted_role text:=current_setting('easyinvio.customer_role');
 display_name text:=nullif(trim(current_setting('easyinvio.display_name')),'');
 reason text:=trim(current_setting('easyinvio.access_reason'));
BEGIN
 IF action='INSPECT' THEN RETURN; END IF;
 IF action NOT IN ('ASSIGN_AGENT','DISABLE_AGENT','ASSIGN_CUSTOMER') THEN
  RAISE EXCEPTION 'Unsupported action';
 END IF;
 SELECT id INTO principal FROM auth.users
  WHERE lower(email)=lower(trim(current_setting('easyinvio.target_email')));
 IF principal IS NULL THEN RAISE EXCEPTION 'Create or find the Auth identity first'; END IF;
 IF principal=actor THEN RAISE EXCEPTION 'Do not change the platform owner into a customer or Agent'; END IF;
 IF NOT EXISTS(SELECT 1 FROM auth.users WHERE id=actor) OR length(reason) NOT BETWEEN 10 AND 500 THEN
  RAISE EXCEPTION 'Enter the actual platform-owner actor UUID and a reason of 10 to 500 characters';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(principal::text,48001));
 IF action='ASSIGN_AGENT' THEN
  UPDATE public.users SET is_active=false,updated_at=now() WHERE auth_user_id=principal AND is_active;
  INSERT INTO public.platform_staff(auth_user_id,role,is_active,created_by)
   VALUES(principal,'AGENT',true,actor)
   ON CONFLICT(auth_user_id) DO UPDATE SET is_active=true,updated_at=now();
  INSERT INTO public.platform_staff_events(actor_auth_user_id,staff_auth_user_id,is_active,reason)
   VALUES(actor,principal,true,reason);
 ELSIF action='DISABLE_AGENT' THEN
  UPDATE public.platform_staff SET is_active=false,updated_at=now() WHERE auth_user_id=principal;
  IF NOT FOUND THEN RAISE EXCEPTION 'This identity has no Agent grant'; END IF;
  INSERT INTO public.platform_staff_events(actor_auth_user_id,staff_auth_user_id,is_active,reason)
   VALUES(actor,principal,false,reason);
 ELSE
  IF wanted_role NOT IN ('OWNER','DISPATCHER','ACCOUNTANT') THEN RAISE EXCEPTION 'Invalid customer role'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.tenants WHERE tenant_id=workspace AND workspace_status='ACTIVE') THEN
   RAISE EXCEPTION 'Choose an existing active customer workspace';
  END IF;
  IF EXISTS(SELECT 1 FROM public.platform_staff WHERE auth_user_id=principal) THEN
   RAISE EXCEPTION 'Use a separate customer identity for a platform staff member';
  END IF;
  IF EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=principal AND is_active AND tenant_id<>workspace) THEN
   RAISE EXCEPTION 'Identity already has active access to another business';
  END IF;
  -- Serialize team changes in one business, including last-Owner protection.
  PERFORM 1 FROM public.tenants WHERE tenant_id=workspace FOR UPDATE;
  IF wanted_role<>'OWNER' AND EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=principal
    AND tenant_id=workspace AND role='OWNER' AND is_active)
   AND (SELECT count(*) FROM public.users WHERE tenant_id=workspace AND role='OWNER' AND is_active)<=1 THEN
   RAISE EXCEPTION 'Assign the replacement Owner before demoting the last Owner';
  END IF;
  INSERT INTO public.users(tenant_id,auth_user_id,role,full_name,is_active)
   VALUES(workspace,principal,wanted_role,coalesce(display_name,
    (SELECT full_name FROM public.app_user_profiles WHERE auth_user_id=principal),
    split_part(current_setting('easyinvio.target_email'),'@',1)),true)
   ON CONFLICT(tenant_id,auth_user_id) DO UPDATE SET role=excluded.role,
    full_name=coalesce(display_name,public.users.full_name),is_active=true,updated_at=now();
 END IF;
 IF display_name IS NOT NULL THEN
  INSERT INTO public.app_user_profiles(auth_user_id,full_name) VALUES(principal,display_name)
   ON CONFLICT(auth_user_id) DO UPDATE SET full_name=excluded.full_name,updated_at=now();
 END IF;
 DELETE FROM public.app_auth_sessions WHERE auth_user_id=principal;
 UPDATE public.admin_client_assistance_sessions SET revoked_at=now()
  WHERE actor_auth_user_id=principal AND revoked_at IS NULL;
END $$;

-- This shows DB grants, not the Vercel SUPER_ADMIN allowlist.
SELECT a.id AS auth_user_id,a.email,p.full_name,f.role AS staff_role,f.is_active AS staff_enabled,
       u.id AS membership_id,u.tenant_id,t.company_name,u.role AS customer_role,u.is_active AS membership_active
FROM auth.users a LEFT JOIN public.app_user_profiles p ON p.auth_user_id=a.id
LEFT JOIN public.platform_staff f ON f.auth_user_id=a.id
LEFT JOIN public.users u ON u.auth_user_id=a.id
LEFT JOIN public.tenants t ON t.tenant_id=u.tenant_id
WHERE lower(a.email)=lower(trim(current_setting('easyinvio.target_email')));
COMMIT;
