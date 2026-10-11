-- Run this COMPLETE single statement; do not select an inner step.
DO $seed_pack$
BEGIN
  -- STEP 00_preflight.sql
  EXECUTE $step_0$
SET LOCAL lock_timeout='10s';
SET LOCAL statement_timeout='120s';
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND (rolsuper OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Run the seed as a trusted database administrator';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='shipments' AND column_name='cargo_type') THEN
    RAISE EXCEPTION 'Apply migrations through 013 before seeding';
  END IF;
END $$;
CREATE TABLE IF NOT EXISTS public.fixture_seed_runs (
  batch_tag text PRIMARY KEY,generated_at timestamptz NOT NULL DEFAULT now(),
  completed boolean NOT NULL DEFAULT false,expected_counts jsonb NOT NULL DEFAULT '{}',
  opening_balances jsonb NOT NULL DEFAULT '{}'
);
ALTER TABLE public.fixture_seed_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fixture_seed_runs FROM anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.fixture_seed_runs TO service_role;
INSERT INTO public.fixture_seed_runs(batch_tag) VALUES('veloce-rigorous-v1') ON CONFLICT DO NOTHING;
CREATE TEMP TABLE seed_context ON COMMIT DROP AS
SELECT batch_tag,generated_at AS anchor,NOT completed AS apply_new FROM public.fixture_seed_runs WHERE batch_tag='veloce-rigorous-v1';
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM public.tenants t JOIN generate_series(1,24) n ON t.tenant_id=md5('veloce-rigorous-v1:tenant:'||n)::uuid
    WHERE t.company_profile->>'fixture_batch' IS DISTINCT FROM 'veloce-rigorous-v1') THEN
    RAISE EXCEPTION 'Reserved fixture tenant ID collision; existing records will not be overwritten';
  END IF;
  IF EXISTS(SELECT 1 FROM auth.users u JOIN generate_series(1,24) n CROSS JOIN generate_series(1,3) r
    ON u.id=md5('veloce-rigorous-v1:auth:'||n||':'||r)::uuid
    WHERE u.raw_app_meta_data->>'fixture_batch' IS DISTINCT FROM 'veloce-rigorous-v1') THEN
    RAISE EXCEPTION 'Reserved fixture auth ID collision';
  END IF;
END $$;
-- Suppress only optional CRM queue hooks while inserting fixtures. All FK,
-- CHECK, tenant-protection and immutable-ledger triggers remain enabled.
CREATE TEMP TABLE seed_crm_triggers ON COMMIT DROP AS
SELECT c.relname AS table_name,g.tgname,g.tgenabled FROM pg_trigger g JOIN pg_class c ON c.oid=g.tgrelid
JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
AND ((c.relname='tenants' AND g.tgname='hubspot_tenant_created') OR (c.relname='shipments' AND g.tgname='hubspot_shipping_milestone'));
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT * FROM pg_temp.seed_crm_triggers LOOP
    EXECUTE format('ALTER TABLE public.%I DISABLE TRIGGER %I',r.table_name,r.tgname);
  END LOOP;
END $$;
$step_0$;

  -- STEP 01_tenants_and_auth.sql
  EXECUTE $step_1$
DO $$ DECLARE i int;r int;tid uuid;aid uuid;name text;cur text;plan text;addr jsonb;anchor timestamptz;
BEGIN
  IF NOT (SELECT apply_new FROM pg_temp.seed_context) THEN RETURN; END IF;
  SELECT seed_context.anchor INTO anchor FROM pg_temp.seed_context;
  FOR i IN 1..24 LOOP
    tid:=md5('veloce-rigorous-v1:tenant:'||i)::uuid;
    name:='SEED24 - '||(ARRAY['Harbor Commerce','Northstar Textiles','Orchard Electronics','Maple Components','Cedar Homewares','Riverside Books'])[1+(i-1)%6]||' '||lpad(i::text,2,'0');
    cur:=(ARRAY['GBP','EUR','USD'])[1+(i-1)%3];plan:=CASE WHEN i%4=0 THEN 'POSTPAID_30_DAY' ELSE 'PREPAID_WALLET' END;
    addr:=jsonb_build_object('line1',i||' Fixture Way','city','London','postal_code','SW1A 1AA','country_code','GB');
    INSERT INTO public.tenants(tenant_id,workspace_slug,workspace_name,legal_company_name,billing_email,billing_address,country_code,
      default_currency,billing_plan,billing_status,workspace_status,credit_limit,company_name,company_profile,is_sandbox,eori_number,vat_registration_number,created_at)
    VALUES(tid,'seed24-'||lpad(i::text,2,'0'),name,name,'seed24-billing-'||i||'@example.invalid',addr,'GB',cur,plan,
      CASE WHEN i%8=0 THEN 'SUSPENDED' WHEN i%7=0 THEN 'PAST_DUE' ELSE 'ACTIVE' END,
      CASE WHEN i%8=0 THEN 'SUSPENDED' ELSE 'ACTIVE' END,CASE WHEN plan='POSTPAID_30_DAY' THEN 5000 ELSE 0 END,
      name,jsonb_build_object('company_name',name,'billing_email','seed24-billing-'||i||'@example.invalid','fixture_batch','veloce-rigorous-v1','synthetic',true),
      true,'GBSEED'||lpad(i::text,4,'0'),'SEEDVAT'||i,anchor-interval '40 days');
    -- Synthetic FK parents, banned indefinitely; no passwords or emails sent.
    FOR r IN 1..3 LOOP
      aid:=md5('veloce-rigorous-v1:auth:'||i||':'||r)::uuid;
      INSERT INTO auth.users(id,instance_id,aud,role,email,encrypted_password,raw_app_meta_data,raw_user_meta_data,
        banned_until,is_sso_user,is_anonymous,created_at,updated_at)
      VALUES(aid,'00000000-0000-0000-0000-000000000000','authenticated','authenticated',
        'seed24-'||i||'-role-'||r||'@example.invalid','',
        jsonb_build_object('fixture_batch','veloce-rigorous-v1','tenant_id',tid,'provider','email','providers',jsonb_build_array('email')),
        jsonb_build_object('synthetic',true),'infinity',false,false,anchor,anchor);
    END LOOP;
  END LOOP;
END $$;
$step_1$;

  -- STEP 02_members_and_carrier_accounts.sql
  EXECUTE $step_2$
DO $$ DECLARE i int;r int;a int;tid uuid;anchor timestamptz;
BEGIN
  IF NOT (SELECT apply_new FROM pg_temp.seed_context) THEN RETURN; END IF;
  SELECT seed_context.anchor INTO anchor FROM pg_temp.seed_context;
  FOR i IN 1..24 LOOP
    tid:=md5('veloce-rigorous-v1:tenant:'||i)::uuid;
    FOR r IN 1..3 LOOP
      INSERT INTO public.users(id,tenant_id,auth_user_id,role,full_name,is_active,created_at)
      VALUES(md5('veloce-rigorous-v1:user:'||i||':'||r)::uuid,tid,md5('veloce-rigorous-v1:auth:'||i||':'||r)::uuid,
        (ARRAY['OWNER','DISPATCHER','ACCOUNTANT'])[r],'SEED24 User '||i||' Role '||r,true,anchor);
    END LOOP;
    FOR a IN 1..2 LOOP
      INSERT INTO public.carrier_accounts(id,tenant_id,account_name,aggregator,regional_provider_code,api_base_url,environment,
        credentials_ciphertext,credential_key_id,is_active,priority)
      VALUES(md5('veloce-rigorous-v1:account:'||i||':'||a)::uuid,tid,'SEED24 Inactive '||a,
        CASE WHEN a=1 THEN 'EASYPOST' ELSE 'REGIONAL' END,CASE WHEN a=2 THEN 'SEED_LOCAL' ELSE NULL END,
        CASE WHEN a=1 THEN 'https://api.easypost.com/v2' ELSE 'https://seed-carrier.example.invalid' END,
        'TEST',decode('67414141414142717963685079356d7868694752705935783754715250335341534a6250676c7554514f44465a70764f705636623677574647504e3647456873555f38486f4b4a526d6b3945524f42456f51486f527631646e4339556538345a333874424e6f516d74544536557670793737684c5879366b55595f32656f513474334f544b35593251614936675f4369737944715f6d545463573038415468416e513d3d','hex'),'rigorous-v1',false,a*10);
    END LOOP;
  END LOOP;
END $$;
$step_2$;

  -- STEP 03_margins_and_stores.sql
  EXECUTE $step_3$
DO $$ DECLARE i int;p int;tid uuid;cur text;anchor timestamptz;percent numeric;
BEGIN
  IF NOT (SELECT apply_new FROM pg_temp.seed_context) THEN RETURN; END IF;
  SELECT seed_context.anchor INTO anchor FROM pg_temp.seed_context;
  FOR i IN 1..24 LOOP
    tid:=md5('veloce-rigorous-v1:tenant:'||i)::uuid;cur:=(ARRAY['GBP','EUR','USD'])[1+(i-1)%3];percent:=10+(i%5)*5;
    INSERT INTO public.margin_rules(id,tenant_id,rule_name,currency,markup_type,markup_value,minimum_markup,priority,is_active,valid_from)
    VALUES(md5('veloce-rigorous-v1:margin:'||i||':1')::uuid,tid,'SEED24 Default Percentage',cur,'PERCENTAGE',percent,0,100,true,anchor-interval '60 days');
    INSERT INTO public.margin_rules(id,tenant_id,rule_name,carrier_account_id,destination_country,currency,markup_type,markup_value,minimum_markup,priority,is_active,valid_from)
    VALUES(md5('veloce-rigorous-v1:margin:'||i||':2')::uuid,tid,'SEED24 US Lane',md5('veloce-rigorous-v1:account:'||i||':1')::uuid,'US',cur,'PERCENTAGE',percent+5,0,10,true,anchor-interval '60 days');
    FOR p IN 1..3 LOOP
      INSERT INTO public.ecommerce_stores(id,tenant_id,platform,display_name)
      VALUES(md5('veloce-rigorous-v1:store:'||i||':'||p)::uuid,tid,(ARRAY['SHOPIFY','WOOCOMMERCE','AMAZON'])[p],'SEED24 Mock Store '||p);
    END LOOP;
  END LOOP;
END $$;
$step_3$;

  -- STEP 04_shipments_and_customs.sql
  EXECUTE $step_4$
DO $$ DECLARE i int;j int;tid uuid;sid uuid;uid uuid;account uuid;dest text;st text;cargo text;cur text;
  base numeric;markup numeric;percent numeric;is_customs boolean;items jsonb;anchor timestamptz;occur timestamptz;
BEGIN
  IF NOT (SELECT apply_new FROM pg_temp.seed_context) THEN RETURN; END IF;
  SELECT seed_context.anchor INTO anchor FROM pg_temp.seed_context;
  FOR i IN 1..24 LOOP
    tid:=md5('veloce-rigorous-v1:tenant:'||i)::uuid;uid:=md5('veloce-rigorous-v1:user:'||i||':2')::uuid;
    cur:=(ARRAY['GBP','EUR','USD'])[1+(i-1)%3];
    FOR j IN 1..8 LOOP
      sid:=md5('veloce-rigorous-v1:shipment:'||i||':'||j)::uuid;
      cargo:=CASE j WHEN 4 THEN 'PALLET' WHEN 5 THEN 'LETTER' WHEN 7 THEN 'OVERLAND_FREIGHT' ELSE 'PARCEL' END;
      account:=md5('veloce-rigorous-v1:account:'||i||':'||CASE WHEN j IN (4,7) THEN 2 ELSE 1 END)::uuid;
      dest:=CASE j WHEN 3 THEN 'US' WHEN 6 THEN 'DE' ELSE 'GB' END;is_customs:=j IN (3,6);
      st:=(ARRAY['DRAFT','QUOTED','BOOKED','IN_TRANSIT','DELIVERED','EXCEPTION','FAILED','BOOKING'])[j];
      IF j=8 AND (i%6 IN (0,3) OR i%4=0) THEN st:='QUOTED'; END IF;
      base:=CASE WHEN j=4 THEN 120+i*5.20 WHEN j=7 THEN 250+i*10.00 ELSE 12+i+j*3.20 END;
      percent:=10+(i%5)*5+CASE WHEN j=3 THEN 5 ELSE 0 END;markup:=round(base*percent/100,2);
      occur:=anchor-make_interval(days=>j*3);
      items:=CASE WHEN is_customs THEN jsonb_build_array(jsonb_build_object('description','Synthetic cotton T-shirt','quantity',2,
        'unit_value','12.50','unit_weight_kg','0.200','origin_country','GB','hs_code','610910')) ELSE '[]'::jsonb END;
      INSERT INTO public.shipments(id,tenant_id,created_by_user_id,carrier_account_id,applied_margin_rule_id,idempotency_key,
        customer_reference,internal_notes,status,carrier_code,service_code,tracking_number,tracking_url,label_storage_path,
        origin_country,destination_country,sender_address,recipient_address,parcel_weight_kg,parcel_length_cm,parcel_width_cm,parcel_height_cm,
        currency,wholesale_cost,profit_markup,tax_amount,pricing_snapshot,quoted_at,quote_expires_at,
        customs_required,customs_items,customs_content_type,customs_incoterm,ai_hs_status,ai_hs_suggestions,
        customs_reviewed_by_user_id,customs_reviewed_at,booked_at,dispatched_at,delivered_at,last_tracking_event_at,
        logistics_metadata,ecommerce_store_id,store_order_id,store_import_hash,cargo_type,proof_of_delivery_url,created_at)
      VALUES(sid,tid,uid,account,md5('veloce-rigorous-v1:margin:'||i||':'||CASE WHEN j=3 THEN 2 ELSE 1 END)::uuid,
        md5('veloce-rigorous-v1:order:'||i||':'||j)::uuid,'SEED24-'||i||'-'||j,'SYNTHETIC FIXTURE: no carrier purchase or real label',st,
        CASE WHEN j IN (4,7) THEN 'LOCAL_SEED' ELSE (ARRAY['DHL','UPS','DPD'])[1+(i+j)%3] END,'SEED_SERVICE',
        CASE WHEN j IN (3,4,5,6) THEN 'SEED24-TRACK-'||i||'-'||j END,
        CASE WHEN j IN (3,4,5,6) THEN 'https://seed-track.example.invalid/'||sid END,
        CASE WHEN j IN (3,4,5,6) THEN 'https://seed-labels.example.invalid/'||sid||'.zpl' END,
        'GB',dest,jsonb_build_object('name','SEED24 Warehouse','line1','1 Fixture Way','city','London','postal_code','SW1A 1AA','country_code','GB'),
        jsonb_build_object('name','SEED24 Recipient','line1','2 Fixture Way','city',CASE dest WHEN 'US' THEN 'New York' WHEN 'DE' THEN 'Berlin' ELSE 'London' END,
          'postal_code',CASE dest WHEN 'US' THEN '10001' WHEN 'DE' THEN '10115' ELSE 'SW1A 1AA' END,'country_code',dest),
        CASE cargo WHEN 'LETTER' THEN 0.100 WHEN 'PALLET' THEN 100.000 WHEN 'OVERLAND_FREIGHT' THEN 900.000 ELSE 2.500 END,
        CASE cargo WHEN 'LETTER' THEN NULL WHEN 'PALLET' THEN 120 WHEN 'OVERLAND_FREIGHT' THEN 200 ELSE 40 END,
        CASE cargo WHEN 'LETTER' THEN NULL WHEN 'PALLET' THEN 80 WHEN 'OVERLAND_FREIGHT' THEN 120 ELSE 30 END,
        CASE cargo WHEN 'LETTER' THEN NULL WHEN 'PALLET' THEN 100 WHEN 'OVERLAND_FREIGHT' THEN 100 ELSE 20 END,
        cur,base,markup,0,jsonb_build_object('markup_type','PERCENTAGE','markup_value',percent::text,'currency',cur,'fixture_batch','veloce-rigorous-v1'),
        CASE WHEN j IN (2,8) THEN anchor ELSE occur-interval '1 hour' END,
        CASE WHEN j IN (2,8) THEN anchor+interval '30 days' ELSE occur+interval '1 day' END,
        is_customs,items,CASE WHEN is_customs THEN 'MERCHANDISE' END,CASE WHEN is_customs THEN 'DAP' END,
        CASE WHEN is_customs THEN 'REVIEWED' ELSE 'NOT_REQUESTED' END,'[]',
        CASE WHEN is_customs THEN uid END,CASE WHEN is_customs THEN occur-interval '30 minutes' END,
        CASE WHEN j IN (3,4,5,6) THEN occur END,CASE WHEN j IN (4,5,6) THEN occur+interval '1 hour' END,
        CASE WHEN j=5 THEN occur+interval '2 days' END,CASE WHEN j IN (4,5,6) THEN occur+interval '2 days' END,
        jsonb_build_object('fixture_batch','veloce-rigorous-v1','synthetic',true,'carrier',CASE WHEN j IN (4,7) THEN 'LOCAL_SEED' ELSE (ARRAY['DHL','UPS','DPD'])[1+(i+j)%3] END,'destination',dest,'stackable',cargo<>'PALLET',
          'invoice_baseline',jsonb_build_object('currency',cur,'billable_weight_kg',CASE cargo WHEN 'LETTER' THEN '0.100' WHEN 'PALLET' THEN '700.000' WHEN 'OVERLAND_FREIGHT' THEN '900.000' ELSE '4.800' END,
            'base_cost',(base-3.50-CASE WHEN dest='US' THEN 2.00 ELSE 0 END)::text,'fuel_surcharge','2.50','remote_area_fee',CASE WHEN dest='US' THEN '2.00' ELSE '0.00' END,'residential_fee','1.00')),
        md5('veloce-rigorous-v1:store:'||i||':'||(1+(j-1)%3))::uuid,'SEED24-STORE-ORDER-'||i||'-'||j,md5(sid::text)||md5(sid::text),cargo,
        CASE WHEN j=5 THEN 'https://seed-pod.example.invalid/'||sid||'.jpg' END,occur-interval '2 hours');
    END LOOP;
  END LOOP;
END $$;
$step_4$;

  -- STEP 05_wallets_reservations_and_ledger.sql
  EXECUTE $step_5$
DO $$ DECLARE i int;j int;tid uuid;sid uuid;rid uuid;plan text;cur text;opening numeric;closing numeric;
  captured numeric;held numeric;balance numeric;reserved numeric:=0;amount numeric;anchor timestamptz;
BEGIN
  IF NOT (SELECT apply_new FROM pg_temp.seed_context) THEN RETURN; END IF;
  SELECT seed_context.anchor INTO anchor FROM pg_temp.seed_context;
  FOR i IN 1..24 LOOP
    tid:=md5('veloce-rigorous-v1:tenant:'||i)::uuid;
    SELECT billing_plan,default_currency INTO plan,cur FROM public.tenants WHERE tenant_id=tid;
    captured:=CASE WHEN plan='PREPAID_WALLET' THEN (SELECT sum(final_client_price) FROM public.shipments WHERE tenant_id=tid AND status IN ('BOOKED','IN_TRANSIT','DELIVERED','EXCEPTION')) ELSE 0 END;
    closing:=CASE WHEN plan='POSTPAID_30_DAY' OR i%6=0 THEN 0 WHEN i%6=3 THEN 10 ELSE 500+i*75 END;
    opening:=closing+captured;balance:=opening;reserved:=0;
    UPDATE public.fixture_seed_runs SET opening_balances=opening_balances||jsonb_build_object(tid::text,opening::text) WHERE batch_tag='veloce-rigorous-v1';
    -- These are fixture opening credits, not payments. No TOPUP/Stripe rows.
    FOR j IN REVERSE 6..3 LOOP
      sid:=md5('veloce-rigorous-v1:shipment:'||i||':'||j)::uuid;rid:=md5('veloce-rigorous-v1:reservation:'||i||':'||j)::uuid;
      SELECT final_client_price INTO amount FROM public.shipments WHERE tenant_id=tid AND id=sid;
      INSERT INTO public.wallet_reservations(id,tenant_id,shipment_id,billing_plan,amount,currency,status,created_at)
      VALUES(rid,tid,sid,plan,amount,cur,'CAPTURED',anchor-make_interval(days=>j*3));
      IF plan='PREPAID_WALLET' THEN
        INSERT INTO public.wallet_ledger(id,tenant_id,entry_type,balance_delta,reserved_delta,balance_after,reserved_after,currency,reservation_id,created_at)
        VALUES(md5('veloce-rigorous-v1:ledger-reserve:'||i||':'||j)::uuid,tid,'RESERVE',0,amount,balance,amount,cur,rid,anchor-make_interval(days=>j*3));
        balance:=balance-amount;
        INSERT INTO public.wallet_ledger(id,tenant_id,entry_type,balance_delta,reserved_delta,balance_after,reserved_after,currency,reservation_id,created_at)
        VALUES(md5('veloce-rigorous-v1:ledger-capture:'||i||':'||j)::uuid,tid,'CAPTURE',-amount,-amount,balance,0,cur,rid,anchor-make_interval(days=>j*3)+interval '1 minute');
      END IF;
    END LOOP;
    sid:=md5('veloce-rigorous-v1:shipment:'||i||':8')::uuid;
    IF (SELECT status FROM public.shipments WHERE tenant_id=tid AND id=sid)='BOOKING' THEN
      rid:=md5('veloce-rigorous-v1:reservation:'||i||':8')::uuid;
      SELECT final_client_price INTO amount FROM public.shipments WHERE tenant_id=tid AND id=sid;
      INSERT INTO public.wallet_reservations(id,tenant_id,shipment_id,billing_plan,amount,currency,status)
      VALUES(rid,tid,sid,plan,amount,cur,'RESERVED');reserved:=amount;
      INSERT INTO public.wallet_ledger(id,tenant_id,entry_type,balance_delta,reserved_delta,balance_after,reserved_after,currency,reservation_id)
      VALUES(md5('veloce-rigorous-v1:ledger-reserve:'||i||':8')::uuid,tid,'RESERVE',0,amount,balance,reserved,cur,rid);
    END IF;
    UPDATE public.wallets SET balance=opening-captured,reserved_balance=reserved,updated_at=anchor WHERE tenant_id=tid;
  END LOOP;
END $$;
$step_5$;

  -- STEP 06_tracking_and_support.sql
  EXECUTE $step_6$
DO $$ DECLARE i int;j int;tid uuid;sid uuid;eid uuid;st text;event_time timestamptz;
BEGIN
  IF NOT (SELECT apply_new FROM pg_temp.seed_context) THEN RETURN; END IF;
  FOR i IN 1..24 LOOP
    tid:=md5('veloce-rigorous-v1:tenant:'||i)::uuid;
    FOR j IN 4..6 LOOP
      sid:=md5('veloce-rigorous-v1:shipment:'||i||':'||j)::uuid;eid:=md5('veloce-rigorous-v1:event:'||i||':'||j)::uuid;
      SELECT status,last_tracking_event_at INTO st,event_time FROM public.shipments WHERE tenant_id=tid AND id=sid;
      INSERT INTO public.tracking_events(id,tenant_id,shipment_id,integration_key_id,event_id,body_sha256,status,occurred_at,raw_error,response,support_pending)
      VALUES(eid,tid,sid,'SEED24-NO-WEBHOOK','SEED24-EVENT-'||i||'-'||j,md5(eid::text)||md5(eid::text),st,event_time,
        CASE WHEN j=6 THEN 'SYNTHETIC customs hold: item description needs review' ELSE '' END,
        jsonb_build_object('synthetic',true,'applied',true,'shipment_id',sid,'status',st),false);
      IF j=6 THEN
        INSERT INTO public.support_tickets(id,tenant_id,shipment_id,tracking_event_id,status,ai_summary,ai_method,prompt_version)
        VALUES(md5('veloce-rigorous-v1:ticket:'||i)::uuid,tid,sid,eid,'OPEN',
          'SEED24 mock remedy: verify the commercial invoice and HS classification with the dispatcher. No message was sent.',
          'DETERMINISTIC_MOCK','seed24-v1');
      END IF;
    END LOOP;
  END LOOP;
END $$;
$step_6$;

  -- STEP 07_verify_and_commit.sql
  EXECUTE $step_7$
-- Restore the exact original CRM trigger state before verifying/committing.
DO $$ DECLARE r record;mode text;
BEGIN
  FOR r IN SELECT * FROM pg_temp.seed_crm_triggers LOOP
    mode:=CASE r.tgenabled WHEN 'O' THEN 'ENABLE' WHEN 'A' THEN 'ENABLE ALWAYS' WHEN 'R' THEN 'ENABLE REPLICA' ELSE 'DISABLE' END;
    EXECUTE format('ALTER TABLE public.%I %s TRIGGER %I',r.table_name,mode,r.tgname);
  END LOOP;
END $$;
DO $$ DECLARE n int; BEGIN
  SELECT count(*) INTO n FROM public.tenants WHERE company_profile->>'fixture_batch'='veloce-rigorous-v1';
  IF n<>24 THEN RAISE EXCEPTION 'Expected 24 tenants, got %',n; END IF;
  IF (SELECT count(*) FROM public.users u JOIN public.tenants t USING(tenant_id) JOIN auth.users a ON a.id=u.auth_user_id WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1' AND a.raw_app_meta_data->>'fixture_batch'='veloce-rigorous-v1')<>72 THEN RAISE EXCEPTION 'Member count mismatch'; END IF;
  IF (SELECT count(*) FROM public.carrier_accounts a JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1')<>48 THEN RAISE EXCEPTION 'Carrier count mismatch'; END IF;
  IF (SELECT count(*) FROM public.margin_rules m JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1')<>48 THEN RAISE EXCEPTION 'Margin count mismatch'; END IF;
  IF (SELECT count(*) FROM public.ecommerce_stores s JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1')<>72 THEN RAISE EXCEPTION 'Store count mismatch'; END IF;
  IF (SELECT count(*) FROM public.shipments WHERE logistics_metadata->>'fixture_batch'='veloce-rigorous-v1')<>192 THEN RAISE EXCEPTION 'Shipment count mismatch'; END IF;
  IF (SELECT count(*) FROM auth.users WHERE raw_app_meta_data->>'fixture_batch'='veloce-rigorous-v1' AND banned_until='infinity'::timestamptz AND encrypted_password='')<>72 THEN RAISE EXCEPTION 'Synthetic auth-principal validation failed'; END IF;
  IF (SELECT count(*) FROM public.tracking_events e JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1')<>72 THEN RAISE EXCEPTION 'Tracking count mismatch'; END IF;
  IF (SELECT count(*) FROM public.support_tickets e JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1')<>24 THEN RAISE EXCEPTION 'Support count mismatch'; END IF;
  IF EXISTS(SELECT 1 FROM public.wallet_topups p JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1') THEN RAISE EXCEPTION 'Unexpected payment-provider fixture'; END IF;
  IF EXISTS(SELECT 1 FROM public.whatsapp_bindings p JOIN public.tenants t USING(tenant_id) JOIN public.users u ON u.id=p.user_id AND u.tenant_id=p.tenant_id JOIN auth.users a ON a.id=u.auth_user_id WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1' AND a.raw_app_meta_data->>'fixture_batch'='veloce-rigorous-v1') THEN RAISE EXCEPTION 'Unexpected WhatsApp fixture'; END IF;
  IF EXISTS(SELECT 1 FROM public.hubspot_sync_jobs p JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1') THEN RAISE EXCEPTION 'Unexpected CRM queue fixture'; END IF;
  IF EXISTS(SELECT 1 FROM public.tenants WHERE company_profile->>'fixture_batch'='veloce-rigorous-v1' AND NOT is_sandbox) THEN RAISE EXCEPTION 'Non-sandbox fixture'; END IF;
  IF EXISTS(SELECT 1 FROM public.carrier_accounts a JOIN public.tenants t USING(tenant_id) WHERE t.company_profile->>'fixture_batch'='veloce-rigorous-v1' AND (a.is_active OR a.environment<>'TEST')) THEN RAISE EXCEPTION 'Active/live seeded carrier'; END IF;
  IF EXISTS(SELECT 1 FROM public.wallets w JOIN public.tenants t USING(tenant_id) JOIN public.fixture_seed_runs f ON f.batch_tag='veloce-rigorous-v1'
    WHERE t.company_profile->>'fixture_batch'=f.batch_tag AND
      (w.currency<>t.default_currency OR w.balance<0 OR w.reserved_balance>w.balance
       OR w.balance<>(f.opening_balances->>w.tenant_id::text)::numeric+coalesce((SELECT sum(balance_delta) FROM public.wallet_ledger l WHERE l.tenant_id=w.tenant_id),0)
       OR w.reserved_balance<>coalesce((SELECT sum(reserved_delta) FROM public.wallet_ledger l WHERE l.tenant_id=w.tenant_id),0)
       OR w.reserved_balance<>coalesce((SELECT sum(amount) FROM public.wallet_reservations r WHERE r.tenant_id=w.tenant_id AND r.billing_plan='PREPAID_WALLET' AND r.status IN ('RESERVED','SUBMITTED')),0))) THEN
    RAISE EXCEPTION 'Wallet/ledger/reservation reconciliation failed';
  END IF;
  IF EXISTS(SELECT 1 FROM public.shipments s WHERE s.logistics_metadata->>'fixture_batch'='veloce-rigorous-v1'
    AND (s.final_client_price<>s.wholesale_cost+s.profit_markup+s.tax_amount OR NOT veloce_private.valid_customs_items(s.customs_items)
      OR (s.logistics_metadata->'invoice_baseline'->>'base_cost')::numeric+(s.logistics_metadata->'invoice_baseline'->>'fuel_surcharge')::numeric+
         (s.logistics_metadata->'invoice_baseline'->>'remote_area_fee')::numeric+(s.logistics_metadata->'invoice_baseline'->>'residential_fee')::numeric<>s.wholesale_cost)) THEN RAISE EXCEPTION 'Financial/customs validation failed'; END IF;
  -- Negative test: a cross-tenant carrier must be rejected by its composite FK.
  BEGIN
    UPDATE public.shipments SET carrier_account_id=md5('veloce-rigorous-v1:account:2:1')::uuid WHERE id=md5('veloce-rigorous-v1:shipment:1:1')::uuid;
    RAISE EXCEPTION 'Cross-tenant FK unexpectedly accepted';
  EXCEPTION WHEN foreign_key_violation THEN NULL; END;
  BEGIN
    UPDATE public.shipments SET parcel_weight_kg=0.500 WHERE id=md5('veloce-rigorous-v1:shipment:1:5')::uuid;
    RAISE EXCEPTION 'Overweight letter unexpectedly accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
END $$;
-- Verify actual authenticated-role RLS without minting a login token.
SELECT set_config('request.jwt.claims',jsonb_build_object('sub',md5('veloce-rigorous-v1:auth:1:1')::uuid,'role','authenticated','tenant_id',md5('veloce-rigorous-v1:tenant:1')::uuid)::text,true);
SELECT set_config('request.jwt.claim.sub',md5('veloce-rigorous-v1:auth:1:1')::uuid::text,true);
SET LOCAL ROLE authenticated;
DO $$ BEGIN
  IF (SELECT count(*) FROM public.shipments)<>8 THEN RAISE EXCEPTION 'RLS: owner should see exactly eight own shipments'; END IF;
  IF EXISTS(SELECT 1 FROM public.shipments WHERE tenant_id=md5('veloce-rigorous-v1:tenant:2')::uuid) THEN RAISE EXCEPTION 'RLS tenant leakage'; END IF;
END $$;
RESET ROLE;
UPDATE public.fixture_seed_runs SET completed=true,expected_counts=jsonb_build_object('tenants',24,'auth_principals',72,'members',72,'carrier_accounts',48,'margin_rules',48,'stores',72,'shipments',192,'tracking_events',72,'support_tickets',24)
WHERE batch_tag='veloce-rigorous-v1';

$step_7$;
END
$seed_pack$;
