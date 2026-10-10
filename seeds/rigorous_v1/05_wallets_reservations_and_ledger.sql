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
