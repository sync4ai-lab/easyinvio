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
