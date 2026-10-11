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
COMMIT;
SELECT batch_tag,generated_at,completed,expected_counts FROM public.fixture_seed_runs WHERE batch_tag='veloce-rigorous-v1';
