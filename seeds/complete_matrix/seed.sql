-- Apply after migration 036 in a dedicated Supabase UAT database as postgres.
-- Synthetic reference data only. No payments, labels, policies or messages.
-- Existing company b9f5260c-3f03-42d5-8753-84690af5f647 is deliberately untouched.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SELECT pg_advisory_xact_lock(hashtextextended('easyinvio-complete-matrix-v1', 0));

DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'Run this seed as the trusted UAT database administrator';
 END IF;
 IF to_regclass('public.tenant_catalog_products') IS NULL OR
    to_regprocedure('public.guard_carrier_credential_identity()') IS NULL THEN
  RAISE EXCEPTION 'Apply migrations through 036 before this seed';
 END IF;
END $$;

CREATE TEMP TABLE matrix_workspaces ON COMMIT DROP AS
SELECT * FROM (VALUES
 ('a0000000-0000-0000-0000-000000000001'::uuid, 'uat-matrix-alpha', 'UAT Matrix Alpha', 5000.00::numeric, 15.00::numeric, 1.50::numeric, 1),
 ('a0000000-0000-0000-0000-000000000002'::uuid, 'uat-matrix-beta', 'UAT Matrix Beta', 2500.00::numeric, 20.00::numeric, 2.00::numeric, 2)
) AS fixtures(tenant_id, slug, display_name, opening_balance, markup, minimum_markup, workspace_index);
ALTER TABLE pg_temp.matrix_workspaces ADD COLUMN created_now boolean NOT NULL DEFAULT false;

DO $$
DECLARE fixture record; principal uuid; membership uuid; role_name text; role_index integer;
        rule_id uuid; store_id uuid; catalog_id uuid; warehouse jsonb; existing public.tenants%ROWTYPE;
BEGIN
 FOR fixture IN SELECT * FROM pg_temp.matrix_workspaces ORDER BY workspace_index LOOP
  SELECT * INTO existing FROM public.tenants WHERE tenant_id=fixture.tenant_id FOR UPDATE;
  IF FOUND THEN
   IF NOT existing.is_sandbox OR existing.company_profile->>'fixture_batch' IS DISTINCT FROM 'easyinvio-complete-matrix-v1'
      OR existing.workspace_slug IS DISTINCT FROM fixture.slug THEN
    RAISE EXCEPTION 'Fixture tenant ID collision: %. No existing workspace was modified.', fixture.tenant_id;
   END IF;
   -- Idempotent reruns never reset consumed credit, reservations or credentials.
   CONTINUE;
  END IF;
  IF EXISTS (SELECT 1 FROM public.tenants WHERE workspace_slug=fixture.slug) THEN
   RAISE EXCEPTION 'Fixture workspace slug collision: %', fixture.slug;
  END IF;
  warehouse:=jsonb_build_object('name',fixture.display_name,'company',fixture.display_name,
   'line1','10 Fixture Street','city','Leeds','postal_code','LS1 1AA','country_code','GB');
  INSERT INTO public.tenants(tenant_id,workspace_slug,workspace_name,legal_company_name,billing_email,
   billing_address,country_code,default_currency,billing_plan,billing_status,workspace_status,
   credit_limit,company_name,company_profile,is_sandbox)
  VALUES(fixture.tenant_id,fixture.slug,fixture.display_name,fixture.display_name,
   fixture.slug||'@example.invalid',warehouse,'GB','GBP','PREPAID_WALLET','ACTIVE','ACTIVE',0,
   fixture.display_name,jsonb_build_object('fixture_batch','easyinvio-complete-matrix-v1','synthetic',true,
   'opening_balance',fixture.opening_balance::text),true);
  -- create_tenant_wallet supplies the FK-bound zero wallet. This is a synthetic
  -- opening balance, not a Stripe payment or a forged TOPUP ledger entry.
  UPDATE public.wallets SET balance=fixture.opening_balance,updated_at=now()
   WHERE tenant_id=fixture.tenant_id AND currency='GBP' AND balance=0 AND reserved_balance=0;
  IF NOT FOUND THEN RAISE EXCEPTION 'Expected new empty GBP wallet for %',fixture.tenant_id; END IF;
  UPDATE pg_temp.matrix_workspaces SET created_now=true WHERE tenant_id=fixture.tenant_id;

  FOR role_index IN 1..4 LOOP
   role_name:=(ARRAY['OWNER','ADMIN','DISPATCHER','ACCOUNTANT'])[role_index];
   principal:=CASE WHEN fixture.workspace_index=1 AND role_index=1
    THEN 'b0000000-0000-0000-0000-000000000001'::uuid
    ELSE md5('easyinvio-complete-matrix-v1:auth:'||fixture.workspace_index||':'||role_index)::uuid END;
   membership:=md5('easyinvio-complete-matrix-v1:member:'||fixture.workspace_index||':'||role_index)::uuid;
   IF EXISTS (SELECT 1 FROM auth.users WHERE id=principal) OR EXISTS (SELECT 1 FROM public.users WHERE id=membership) THEN
    RAISE EXCEPTION 'Fixture user ID collision: %',principal;
   END IF;
   INSERT INTO auth.users(id,instance_id,aud,role,email,encrypted_password,raw_app_meta_data,raw_user_meta_data,
    banned_until,is_sso_user,is_anonymous,created_at,updated_at)
   VALUES(principal,'00000000-0000-0000-0000-000000000000','authenticated','authenticated',
    fixture.slug||'-'||lower(role_name)||'@example.invalid','',
    jsonb_build_object('fixture_batch','easyinvio-complete-matrix-v1','tenant_id',fixture.tenant_id,
     'provider','email','providers',jsonb_build_array('email')),jsonb_build_object('synthetic',true),
    'infinity',false,false,now(),now());
   INSERT INTO public.users(id,tenant_id,auth_user_id,role,full_name,is_active)
   VALUES(membership,fixture.tenant_id,principal,role_name,fixture.display_name||' '||role_name,true);
  END LOOP;
  principal:=CASE WHEN fixture.workspace_index=1 THEN 'b0000000-0000-0000-0000-000000000001'::uuid
   ELSE md5('easyinvio-complete-matrix-v1:auth:2:1')::uuid END;
  rule_id:=md5('easyinvio-complete-matrix-v1:margin:'||fixture.workspace_index)::uuid;
  INSERT INTO public.margin_rules(id,tenant_id,rule_name,currency,markup_type,markup_value,minimum_markup,
   priority,is_active,valid_from)
  VALUES(rule_id,fixture.tenant_id,'UAT Matrix Baseline','GBP','PERCENTAGE',fixture.markup,
   fixture.minimum_markup,10,true,now()-interval '1 day');

  -- Tenant creation uses the existing platform catalog trigger to mirror TEST
  -- credentials. No fake ciphertext, invented key IDs or identity edits.
  -- Restrict these fixtures to implemented native API endpoints only.
  UPDATE public.carrier_accounts SET is_active=false WHERE tenant_id=fixture.tenant_id AND
   (environment<>'TEST' OR api_base_url NOT IN
    ('https://api.easypost.com/v2','https://panel.sendcloud.sc/api/v3','https://api.goshippo.com'));

  FOR role_index IN 1..3 LOOP
   store_id:=md5('easyinvio-complete-matrix-v1:store:'||fixture.workspace_index||':'||role_index)::uuid;
   INSERT INTO public.ecommerce_stores(id,tenant_id,platform,display_name,is_active)
   VALUES(store_id,fixture.tenant_id,(ARRAY['SHOPIFY','AMAZON','WOOCOMMERCE'])[role_index],
    fixture.display_name||' Mock '||(ARRAY['Shopify','Amazon','WooCommerce'])[role_index],false);
  END LOOP;
  -- Store FK parents are inactive until real store credentials are installed
  -- through the application. This seed does not pretend to connect a shop.
  FOR role_index IN 1..4 LOOP
   role_name:=(ARRAY['SENDER','RETURN','PICKUP','INVOICE'])[role_index];
   catalog_id:=md5('easyinvio-complete-matrix-v1:address:'||fixture.workspace_index||':'||role_index)::uuid;
   INSERT INTO public.tenant_catalog_addresses(id,tenant_id,label,address_role,address,is_default,created_by,updated_by)
   VALUES(catalog_id,fixture.tenant_id,'UAT '||role_name,role_name,warehouse,true,principal,principal);
  END LOOP;
  catalog_id:=md5('easyinvio-complete-matrix-v1:contact:'||fixture.workspace_index)::uuid;
  INSERT INTO public.tenant_catalog_contacts(id,tenant_id,label,address,created_by,updated_by)
  VALUES(catalog_id,fixture.tenant_id,'UAT New York Recipient',
   jsonb_build_object('name','UAT Recipient','line1','100 Broadway','city','New York','state','NY',
    'postal_code','10001','country_code','US'),principal,principal);
  catalog_id:=md5('easyinvio-complete-matrix-v1:product:'||fixture.workspace_index)::uuid;
  INSERT INTO public.tenant_catalog_products(id,tenant_id,sku,description,unit_weight_kg,unit_value,
   currency,hs_code,origin_country,created_by,updated_by)
  VALUES(catalog_id,fixture.tenant_id,'UAT-COTTON-01','Cotton knitted shirt',0.125,12.30,
   'GBP','610910','GB',principal,principal);
 END LOOP;
END $$;

-- Remove only optional CRM jobs generated by newly inserted synthetic tenants,
-- before they become visible to a background worker at commit.
DELETE FROM public.hubspot_sync_jobs WHERE tenant_id IN
 (SELECT tenant_id FROM pg_temp.matrix_workspaces WHERE created_now);

DO $$
DECLARE fixture record;
BEGIN
 FOR fixture IN SELECT * FROM pg_temp.matrix_workspaces LOOP
  IF (SELECT count(*) FROM public.users WHERE tenant_id=fixture.tenant_id AND is_active)<>4 THEN
   RAISE EXCEPTION 'Expected four fixture memberships for %',fixture.tenant_id;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.wallets WHERE tenant_id=fixture.tenant_id AND currency='GBP') THEN
   RAISE EXCEPTION 'Fixture wallet missing for %',fixture.tenant_id;
  END IF;
  IF (SELECT count(*) FROM public.margin_rules WHERE tenant_id=fixture.tenant_id AND rule_name='UAT Matrix Baseline')<>1 THEN
   RAISE EXCEPTION 'Fixture baseline margin rule missing for %',fixture.tenant_id;
  END IF;
  IF EXISTS (SELECT 1 FROM public.carrier_accounts WHERE tenant_id=fixture.tenant_id AND is_active AND
   (environment<>'TEST' OR platform_connection_id IS NULL OR NOT credential_write_locked)) THEN
   RAISE EXCEPTION 'Unexpected active carrier credential identity for %',fixture.tenant_id;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.carrier_accounts WHERE tenant_id=fixture.tenant_id AND is_active) THEN
   RAISE NOTICE 'Workspace % has no enabled native TEST carrier connection. Configure it in Admin before live sandbox rate tests.',fixture.tenant_id;
  END IF;
 END LOOP;
END $$;

SELECT f.tenant_id,f.display_name,w.currency,w.balance,w.reserved_balance,
 (SELECT count(*) FROM public.carrier_accounts a WHERE a.tenant_id=f.tenant_id AND a.is_active) AS active_test_connections,
 (SELECT count(*) FROM public.ecommerce_stores s WHERE s.tenant_id=f.tenant_id) AS mock_store_references
FROM pg_temp.matrix_workspaces f JOIN public.wallets w USING(tenant_id) ORDER BY f.workspace_index;
SELECT u.tenant_id,u.auth_user_id,u.role FROM public.users u
JOIN pg_temp.matrix_workspaces f USING(tenant_id) ORDER BY f.workspace_index,u.role;
SELECT a.tenant_id,a.id AS carrier_account_id,a.api_base_url,a.environment,a.is_active
FROM public.carrier_accounts a JOIN pg_temp.matrix_workspaces f USING(tenant_id)
ORDER BY f.workspace_index,a.priority,a.id;
SELECT s.tenant_id,s.id AS store_id,s.platform,s.is_active FROM public.ecommerce_stores s
JOIN pg_temp.matrix_workspaces f USING(tenant_id) ORDER BY f.workspace_index,s.platform;
COMMIT;
