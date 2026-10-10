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
