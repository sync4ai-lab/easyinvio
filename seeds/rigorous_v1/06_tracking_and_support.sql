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
