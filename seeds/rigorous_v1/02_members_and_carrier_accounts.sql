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
