-- Execute this complete single statement AFTER rigorous_v1. Adds 3 sandbox tenants (27 total).
-- No real logins, provider credentials, payments or messages are created.
-- Opening wallet credits are synthetic fixtures, not payment receipts.
DO $uat_pack$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
  RAISE EXCEPTION 'Run UAT fixtures as a trusted database administrator';
 END IF;
 IF EXISTS(SELECT 1 FROM public.fixture_seed_runs WHERE batch_tag='veloce-uat100-v1' AND completed) THEN
  RAISE NOTICE 'UAT100 supplement already complete; no changes'; RETURN;
 END IF;
 IF EXISTS(SELECT 1 FROM public.tenants WHERE workspace_slug LIKE 'uat100-%') THEN
  RAISE EXCEPTION 'UAT100 namespace collision; refusing to overwrite records';
 END IF;
 EXECUTE $setup$
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='120s';
CREATE TEMP TABLE seed_crm_triggers ON COMMIT DROP AS
SELECT c.relname AS table_name,g.tgname,g.tgenabled FROM pg_trigger g JOIN pg_class c ON c.oid=g.tgrelid
JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
AND ((c.relname='tenants' AND g.tgname='hubspot_tenant_created') OR (c.relname='shipments' AND g.tgname='hubspot_shipping_milestone'));
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT * FROM pg_temp.seed_crm_triggers LOOP
    EXECUTE format('ALTER TABLE public.%I DISABLE TRIGGER %I',r.table_name,r.tgname);
  END LOOP;
END $$;
DO $$ DECLARE i int;r int;tid uuid;aid uuid;name text;cur text;plan text;addr jsonb;anchor timestamptz;
BEGIN
  anchor:=now();
  FOR i IN 1..3 LOOP
    tid:=md5('veloce-uat100-v1:tenant:'||i)::uuid;
    name:='UAT100 - '||(ARRAY['Harbor Commerce','Northstar Textiles','Orchard Electronics','Maple Components','Cedar Homewares','Riverside Books'])[1+(i-1)%6]||' '||lpad(i::text,2,'0');
    IF i=3 THEN name:='UAT100 - '||repeat('Long Company Name ',10); END IF;
    cur:='GBP';plan:=CASE WHEN i=3 THEN 'POSTPAID_30_DAY' ELSE 'PREPAID_WALLET' END;
    addr:=jsonb_build_object('line1',i||' Fixture Way','city','London','postal_code','SW1A 1AA','country_code','GB');
    INSERT INTO public.tenants(tenant_id,workspace_slug,workspace_name,legal_company_name,billing_email,billing_address,country_code,
      default_currency,billing_plan,billing_status,workspace_status,credit_limit,company_name,company_profile,is_sandbox,eori_number,vat_registration_number,created_at)
    VALUES(tid,'uat100-'||lpad(i::text,2,'0'),name,name,'uat100-billing-'||i||'@example.invalid',addr,'GB',cur,plan,
      CASE WHEN i%8=0 THEN 'SUSPENDED' WHEN i%7=0 THEN 'PAST_DUE' ELSE 'ACTIVE' END,
      CASE WHEN i%8=0 THEN 'SUSPENDED' ELSE 'ACTIVE' END,CASE WHEN plan='POSTPAID_30_DAY' THEN 5000 ELSE 0 END,
      name,jsonb_build_object('company_name',name,'billing_email','uat100-billing-'||i||'@example.invalid','fixture_batch','veloce-uat100-v1','synthetic',true),
      true,'GBSEED'||lpad(i::text,4,'0'),'SEEDVAT'||i,anchor-interval '40 days');
    -- Synthetic FK parents, banned indefinitely; no passwords or emails sent.
    FOR r IN 1..3 LOOP
      aid:=md5('veloce-uat100-v1:auth:'||i||':'||r)::uuid;
      INSERT INTO auth.users(id,instance_id,aud,role,email,encrypted_password,raw_app_meta_data,raw_user_meta_data,
        banned_until,is_sso_user,is_anonymous,created_at,updated_at)
      VALUES(aid,'00000000-0000-0000-0000-000000000000','authenticated','authenticated',
        'uat100-'||i||'-role-'||r||'@example.invalid','',
        jsonb_build_object('fixture_batch','veloce-uat100-v1','tenant_id',tid,'provider','email','providers',jsonb_build_array('email')),
        jsonb_build_object('synthetic',true),'infinity',false,false,anchor,anchor);
    END LOOP;
  END LOOP;
END $$;
DO $$ DECLARE i int;r int;a int;tid uuid;anchor timestamptz;
BEGIN
  anchor:=now();
  FOR i IN 1..3 LOOP
    tid:=md5('veloce-uat100-v1:tenant:'||i)::uuid;
    FOR a IN 1..2 LOOP
      INSERT INTO public.carrier_accounts(id,tenant_id,account_name,aggregator,regional_provider_code,api_base_url,environment,
        credentials_ciphertext,credential_key_id,is_active,priority)
      VALUES(md5('veloce-uat100-v1:account:'||i||':'||a)::uuid,tid,'UAT100 Inactive '||a,
        CASE WHEN a=1 THEN 'EASYPOST' ELSE 'REGIONAL' END,CASE WHEN a=2 THEN 'SEED_LOCAL' ELSE NULL END,
        CASE WHEN a=1 THEN 'https://api.easypost.com/v2' ELSE 'https://seed-carrier.example.invalid' END,
        'TEST',decode('67414141414142717963685079356d7868694752705935783754715250335341534a6250676c7554514f44465a70764f705636623677574647504e3647456873555f38486f4b4a526d6b3945524f42456f51486f527631646e4339556538345a333874424e6f516d74544536557670793737684c5879366b55595f32656f513474334f544b35593251614936675f4369737944715f6d545463573038415468416e513d3d','hex'),'rigorous-v1',false,a*10);
    END LOOP;
  END LOOP;
END $$;

DO $$ DECLARE i int; r int; tid uuid; BEGIN
 FOR i IN 1..3 LOOP
  tid:=md5('veloce-uat100-v1:tenant:'||i)::uuid;
  FOR r IN 1..3 LOOP
   INSERT INTO public.users(id,tenant_id,auth_user_id,role,full_name,is_active)
   VALUES(md5('veloce-uat100-v1:user:'||i||':'||r)::uuid,tid,md5('veloce-uat100-v1:auth:'||i||':'||r)::uuid,
    (ARRAY['OWNER','ADMIN','DISPATCHER'])[r],'UAT100 role '||r,NOT(i=2 AND r=3));
  END LOOP;
  UPDATE public.wallets SET balance=CASE i WHEN 1 THEN 100 WHEN 2 THEN 20 ELSE 0 END,reserved_balance=0 WHERE tenant_id=tid;
 END LOOP;
END $$;
-- Tenant 1 intentionally has no rules: fallback. Tenant 3 has no shipments: empty workspace.
INSERT INTO public.margin_rules(id,tenant_id,rule_name,currency,service_code,markup_type,markup_value,priority,valid_from)
VALUES
 (md5('veloce-uat100-v1:fixed')::uuid,md5('veloce-uat100-v1:tenant:2')::uuid,'UAT100 fixed 5.50','GBP','UAT_FIXED','FIXED',5.50,10,now()-interval '1 day'),
 (md5('veloce-uat100-v1:zero')::uuid,md5('veloce-uat100-v1:tenant:2')::uuid,'UAT100 zero','GBP','UAT_ZERO','PERCENTAGE',0,10,now()-interval '1 day'),
 (md5('veloce-uat100-v1:priority-low')::uuid,md5('veloce-uat100-v1:tenant:2')::uuid,'UAT100 priority 10','GBP','UAT_PRIORITY','PERCENTAGE',10,10,now()-interval '1 day'),
 (md5('veloce-uat100-v1:priority-high')::uuid,md5('veloce-uat100-v1:tenant:2')::uuid,'UAT100 priority 100','GBP','UAT_PRIORITY','PERCENTAGE',30,100,now()-interval '1 day');
INSERT INTO public.margin_rules(id,tenant_id,rule_name,currency,service_code,markup_type,markup_value,min_weight_kg,max_weight_kg,priority,valid_from)
VALUES
 (md5('veloce-uat100-v1:tier-low')::uuid,md5('veloce-uat100-v1:tenant:2')::uuid,'UAT100 below 20kg','GBP','UAT_TIER','PERCENTAGE',10,0,20,10,now()-interval '1 day'),
 (md5('veloce-uat100-v1:tier-high')::uuid,md5('veloce-uat100-v1:tenant:2')::uuid,'UAT100 at least 20kg','GBP','UAT_TIER','PERCENTAGE',25,20,NULL,10,now()-interval '1 day');
-- Copy only insertable columns, excluding PostgreSQL generated financial totals.
DO $$ DECLARE cols text; selected text; i int; j int; data jsonb; BEGIN
 SELECT string_agg(quote_ident(attname),',' ORDER BY attnum),string_agg('x.'||quote_ident(attname),',' ORDER BY attnum)
 INTO cols,selected FROM pg_attribute WHERE attrelid='public.shipments'::regclass AND attnum>0 AND NOT attisdropped AND attgenerated='';
 FOR i IN 1..2 LOOP FOR j IN 1..4 LOOP
  SELECT to_jsonb(s) INTO data FROM public.shipments s WHERE customer_reference='SEED24-1-2';
  IF data IS NULL THEN RAISE EXCEPTION 'Run rigorous_v1 pack first'; END IF;
  data:=data||jsonb_build_object('id',md5('veloce-uat100-v1:shipment:'||i||':'||j)::uuid,
   'tenant_id',md5('veloce-uat100-v1:tenant:'||i)::uuid,'created_by_user_id',md5('veloce-uat100-v1:user:'||i||':1')::uuid,
   'carrier_account_id',md5('veloce-uat100-v1:account:'||i||':1')::uuid,'applied_margin_rule_id',NULL,'ecommerce_store_id',NULL,'store_order_id',NULL,'store_import_hash',NULL,
   'idempotency_key',md5('veloce-uat100-v1:order:'||i||':'||j)::uuid,'customer_reference','UAT100-'||i||'-'||j,
   'internal_notes','SYNTHETIC UAT: no carrier purchase','status','QUOTED','currency','GBP','wholesale_cost',CASE j WHEN 1 THEN 20 WHEN 2 THEN 15 WHEN 3 THEN 15 ELSE 12.33 END,
   'profit_markup',0,'tax_amount',0,'parcel_weight_kg',0.155,
   'pricing_snapshot',jsonb_build_object('markup_type','MANUAL','markup_value','0.00','currency','GBP'),
   'logistics_metadata',jsonb_build_object('fixture_batch','veloce-uat100-v1','synthetic',true),
   'quoted_at',now(),'quote_expires_at',now()+interval '30 days','created_at',now(),'updated_at',now());
  EXECUTE format('INSERT INTO public.shipments(%s) SELECT %s FROM jsonb_populate_record(NULL::public.shipments,$1) x',cols,selected) USING data;
 END LOOP; END LOOP;
END $$;
DO $$ DECLARE r record;mode text;
BEGIN
  FOR r IN SELECT * FROM pg_temp.seed_crm_triggers LOOP
    mode:=CASE r.tgenabled WHEN 'O' THEN 'ENABLE' WHEN 'A' THEN 'ENABLE ALWAYS' WHEN 'R' THEN 'ENABLE REPLICA' ELSE 'DISABLE' END;
    EXECUTE format('ALTER TABLE public.%I %s TRIGGER %I',r.table_name,mode,r.tgname);
  END LOOP;
END $$;

DO $$ BEGIN
 IF (SELECT count(*) FROM public.tenants WHERE company_profile->>'fixture_batch'='veloce-uat100-v1' AND is_sandbox)<>3 THEN RAISE EXCEPTION 'Tenant verification failed'; END IF;
 IF (SELECT count(*) FROM public.users u JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-uat100-v1')<>9 THEN RAISE EXCEPTION 'Member verification failed'; END IF;
 IF (SELECT count(*) FROM public.shipments WHERE logistics_metadata->>'fixture_batch'='veloce-uat100-v1')<>8 THEN RAISE EXCEPTION 'Shipment verification failed'; END IF;
 IF (SELECT count(*) FROM public.carrier_accounts a JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-uat100-v1' AND NOT a.is_active AND a.environment='TEST')<>6 THEN RAISE EXCEPTION 'Carrier parent verification failed'; END IF;
 IF (SELECT count(*) FROM public.margin_rules m JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-uat100-v1')<>6 THEN RAISE EXCEPTION 'Pricing fixture verification failed'; END IF;
 IF (SELECT count(*) FROM auth.users WHERE raw_app_meta_data->>'fixture_batch'='veloce-uat100-v1' AND banned_until='infinity'::timestamptz AND encrypted_password='')<>9 THEN RAISE EXCEPTION 'Synthetic auth verification failed'; END IF;
 IF (SELECT count(*) FROM public.wallets w JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-uat100-v1' AND w.currency='GBP' AND w.reserved_balance=0)<>3 THEN RAISE EXCEPTION 'Wallet verification failed'; END IF;
 IF EXISTS(SELECT 1 FROM public.hubspot_sync_jobs j JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-uat100-v1') THEN RAISE EXCEPTION 'Unexpected CRM queue'; END IF;
END $$;
INSERT INTO public.fixture_seed_runs(batch_tag,completed,expected_counts)
VALUES('veloce-uat100-v1',true,'{"tenants":3,"members":9,"shipments":8,"margin_rules":6}') ON CONFLICT(batch_tag) DO UPDATE SET completed=true,expected_counts=excluded.expected_counts;
$setup$;
END $uat_pack$;
