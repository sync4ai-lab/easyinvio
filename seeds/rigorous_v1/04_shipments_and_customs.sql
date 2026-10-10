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
