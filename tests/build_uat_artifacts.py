"""Build the supplemental fixture SQL and a reproducible core regression receipt."""
import io,json,re,unittest
from pathlib import Path

out=Path('docs/uat_100');out.mkdir(exist_ok=True)
attachment=Path('C:/Users/veera/.codex/attachments/6f992aa4-e6f3-45be-8445-b01a00b02e79/Pasted text.txt').read_text(encoding='utf-8')
cases=[]
for line in attachment.splitlines():
    match=re.search(r'(TC-\d{3}):\s*(.*?)\s*—\s*Expected:\s*(.*)',line)
    if match:cases.append(dict(zip(['id','case','expected'],match.groups())))
assert len(cases)==100
(out/'cases.json').write_text(json.dumps(cases,indent=2,ensure_ascii=False),encoding='utf-8')
suite=unittest.TestSuite()
for module in ['test_logistics','test_admin_portal','test_dashboard_portal','test_tracking_and_support','test_automation_freight']:
    suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=module+'.py'))
stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
(out/'core_regression.log').write_text(stream.getvalue(),encoding='utf-8')
(out/'core_regression.json').write_text(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'scope':'Controlled in-process tests; not live-provider or browser UAT.'},indent=2))

tenant=Path('seeds/rigorous_v1/01_tenants_and_auth.sql').read_text()
tenant=tenant.replace('  IF NOT (SELECT apply_new FROM pg_temp.seed_context) THEN RETURN; END IF;\n','').replace('  SELECT seed_context.anchor INTO anchor FROM pg_temp.seed_context;','  anchor:=now();').replace('1..24','1..3').replace('veloce-rigorous-v1','veloce-uat100-v1').replace('seed24','uat100').replace('SEED24','UAT100').replace("cur:=(ARRAY['GBP','EUR','USD'])[1+(i-1)%3];plan:=CASE WHEN i%4=0", "cur:='GBP';plan:=CASE WHEN i=3")
tenant=tenant.replace("    cur:='GBP';", "    IF i=3 THEN name:='UAT100 - '||repeat('Long Company Name ',10); END IF;\n    cur:='GBP';")
membership="""
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
"""
accounts=Path('seeds/rigorous_v1/02_members_and_carrier_accounts.sql').read_text()
accounts=accounts.replace('  IF NOT (SELECT apply_new FROM pg_temp.seed_context) THEN RETURN; END IF;\n','').replace('  SELECT seed_context.anchor INTO anchor FROM pg_temp.seed_context;','  anchor:=now();').replace('1..24','1..3').replace('veloce-rigorous-v1','veloce-uat100-v1').replace('SEED24','UAT100')
start=accounts.index('    FOR r IN 1..3 LOOP');end=accounts.index('    FOR a IN 1..2 LOOP')
accounts=accounts[:start]+accounts[end:]
preflight=Path('seeds/rigorous_v1/00_preflight.sql').read_text()
disable=preflight[preflight.index('CREATE TEMP TABLE seed_crm_triggers'):]
restore=Path('seeds/rigorous_v1/07_verify_and_commit.sql').read_text()
restore=restore[restore.index('DO $$ DECLARE r record;mode text;'):restore.index('DO $$ DECLARE n int;')]
sql="""-- Execute this complete single statement AFTER rigorous_v1. Adds 3 sandbox tenants (27 total).
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
"""+disable+tenant+accounts+membership+restore+"""
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
"""
seed=Path('seeds/uat_100');seed.mkdir(exist_ok=True)
(seed/'01_supplemental_data.sql').write_text(sql,encoding='utf-8')
print('Created 100-case catalog, core regression receipt and supplemental SQL; SQL not committed.')
