"""Live sandbox setup, isolated contract execution, cleanup and audit reporting."""
import asyncio,csv,importlib,io,json,os,secrets,subprocess,sys,time,unittest
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID
import asyncpg,httpx
from pydantic import ValidationError

class Runtime:
 def __init__(self,root,cases):
  self.root=root;self.cases=cases;self.results=[];self.sessions={};self.created=[];self.readiness={};self.cleanup_errors=[]
  self.client=httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False,timeout=35)
 def prepare(self):
  from main import Settings
  self.settings=Settings()
  if self.settings.database_environment!='SANDBOX':raise RuntimeError('UAT writes require SANDBOX database')
  try: self.readiness['backend_http']=self.client.get('/health').status_code
  except httpx.HTTPError:self.readiness['backend_http']='unreachable'
  try:asyncio.run(self.prepare_database())
  except Exception as exc:self.readiness['auth_setup_error']=type(exc).__name__
  self.provider_readiness()
  self.generate_csv()
 def provider_readiness(self):
  s=self.settings
  self.readiness['stripe_enabled']=s.stripe_enabled
  if s.stripe_secret_key.get_secret_value().startswith('sk_test_'):
   try:self.readiness['stripe_account_http']=httpx.get('https://api.stripe.com/v1/account',auth=(s.stripe_secret_key.get_secret_value(),''),trust_env=False,timeout=15).status_code
   except httpx.HTTPError:self.readiness['stripe_account_http']='unreachable'
  self.readiness['twilio_enabled']=s.twilio_enabled
  if s.twilio_account_sid and s.twilio_auth_token.get_secret_value():
   try:self.readiness['twilio_account_http']=httpx.get(f'https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}.json',auth=(s.twilio_account_sid,s.twilio_auth_token.get_secret_value()),trust_env=False,timeout=15).status_code
   except httpx.HTTPError:self.readiness['twilio_account_http']='unreachable'
  from backend.hubspot_crm import HubSpotSettings
  try:
   h=HubSpotSettings();self.readiness.update(hubspot_enabled=h.hubspot_enabled,hubspot_environment=h.hubspot_environment,hubspot_provisioning_enabled=h.hubspot_provisioning_enabled)
   if h.hubspot_access_token:
    try:self.readiness['hubspot_companies_http']=httpx.get('https://api.hubapi.com/crm/v3/objects/companies',params={'limit':1},headers={'Authorization':'Bearer '+h.hubspot_access_token.get_secret_value()},trust_env=False,timeout=15).status_code
    except httpx.HTTPError:self.readiness['hubspot_companies_http']='unreachable'
  except Exception:self.readiness['hubspot_configuration']='invalid'
 async def connect(self):
  from main import database_tls_context
  return await asyncpg.connect(self.settings.database_url.get_secret_value(),ssl=database_tls_context(self.settings.database_ca_file,strict=self.settings.database_tls_strict))
 async def prepare_database(self):
  connection=await self.connect();s=self.settings
  headers={'apikey':s.supabase_service_role_key.get_secret_value(),'Authorization':'Bearer '+s.supabase_service_role_key.get_secret_value()}
  try:
   self.readiness['sandbox_tenants']=await connection.fetchval('SELECT count(*) FROM public.tenants WHERE is_sandbox')
   self.readiness['active_test_carriers']=await connection.fetchval("SELECT count(*) FROM public.carrier_accounts WHERE is_active AND environment='TEST'")
   self.readiness['active_stores']=await connection.fetchval('SELECT count(*) FROM public.ecommerce_stores WHERE is_active')
   tenant=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox AND workspace_status='ACTIVE'")
   if not tenant:raise RuntimeError('Missing seed24-01 sandbox tenant')
   self.foreign_tenant=str(await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-02' AND is_sandbox"))
   self.foreign_shipment=str(await connection.fetchval('SELECT id FROM public.shipments WHERE tenant_id=$1 LIMIT 1',UUID(self.foreign_tenant)))
   for role in ['OWNER','DISPATCHER','ACCOUNTANT']:
    email=f'uat200-{secrets.token_hex(10)}@example.invalid';password=secrets.token_urlsafe(40)
    response=httpx.post(s.supabase_url+'/auth/v1/admin/users',headers=headers,json={'email':email,'password':password,'email_confirm':True},trust_env=False,timeout=25)
    if response.status_code not in (200,201):raise RuntimeError(f'Auth provisioning HTTP {response.status_code}')
    user=UUID(response.json()['id']);self.created.append(user)
    await connection.execute('INSERT INTO public.users(tenant_id,auth_user_id,role,full_name,is_active) VALUES($1,$2,$3,$4,true)',tenant,user,role,'Disposable UAT200 '+role)
    login=self.client.post('/api/v1/auth/token',json={'email':email,'password':password})
    if login.status_code!=200:raise RuntimeError(f'App login HTTP {login.status_code}')
    self.sessions[role]={'token':login.json()['access_token'],'tenant':str(tenant)}
   self.readiness['real_password_verified_roles']=list(self.sessions)
  finally:await connection.close()
 def generate_csv(self):
  from backend.order_csv import template
  sample=template(True);self.csv_fields=sample['columns'];base=dict(zip(self.csv_fields,sample['examples'][3]))
  rows=[]
  for i in range(150):
   row=dict(base);row.update(order_reference=f'UAT200-INTERNATIONAL-{i+1:03}');rows.append(row)
  output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=self.csv_fields);writer.writeheader();writer.writerows(rows)
  self.csv_bytes=output.getvalue().encode();(self.root/'tests/uat_200/veloce_bulk_test_150.csv').write_bytes(self.csv_bytes)
 def cleanup(self):
  try:asyncio.run(self.cleanup_database())
  except Exception as exc:self.cleanup_errors.append(type(exc).__name__)
  self.sessions.clear();self.client.close()
 async def cleanup_database(self):
  connection=await self.connect();s=self.settings
  headers={'apikey':s.supabase_service_role_key.get_secret_value(),'Authorization':'Bearer '+s.supabase_service_role_key.get_secret_value()}
  try:
   for user in self.created:
    await connection.execute('DELETE FROM public.users WHERE auth_user_id=$1',user)
    removed=httpx.delete(s.supabase_url+'/auth/v1/admin/users/'+str(user),headers=headers,trust_env=False,timeout=25)
    if removed.status_code not in (200,204):self.cleanup_errors.append('Auth cleanup HTTP '+str(removed.status_code))
   self.readiness['disposable_identities_cleaned']=not self.cleanup_errors
  finally:await connection.close()
 def report(self):
  report=self.root/'docs/uat_200';report.mkdir(exist_ok=True,parents=True)
  counts=Counter(r['status'] for r in self.results)
  payload={'executed_at_utc':datetime.now(timezone.utc).isoformat(),'readiness':self.readiness,'counts':dict(counts),'cleanup_errors':self.cleanup_errors,'cases':self.results}
  (report/'results.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
  lines=['# EasyInvio 200-case UAT execution audit','',f"Run UTC: {payload['executed_at_utc']}",'',f'Executed: {len(self.results)} / 200. Results: {dict(counts)}.','',
   '**Acceptance rule:** PASS means only the stated scope passed. PARTIAL means controlled contract checks passed but the requested genuine end-to-end workflow is unproven. BLOCKED means a prerequisite or human/provider action prevented execution. No blocked or mocked case is represented as a live integration pass.','',
   'The explicit specification ranges contain 35 cases each for A–E and 25 for F. These are used instead of the contradictory phrase “split evenly”.','',
   'Sandbox writes: disposable Supabase Auth users/member/session rows were created for genuine password login and removed after execution. Financial database probes roll back their writes. No genuine merchant password, personal-phone message, charge or carrier dispatch was fabricated.','',
   '## Live prerequisite checks','', '```json',json.dumps(self.readiness,indent=2),'```','',
   f'Cleanup errors: {self.cleanup_errors or "none"}.','',
   '## Release decision','', 'Not accepted for production: partial/blocked live workflows and any failures require resolution before claiming full readiness.','',
   '## Required next actions','',
   '- TC-032 is an HTTP rejection contract failure, not an observed tenant leak: foreign tenant query parameters are ignored and own rows returned. Decide whether to explicitly reject tenant override parameters; do not change assertions just to get a green result.',
   '- Configure an active platform-owned EasyPost TEST connection. Native sandbox label purchase is currently fenced in the application, so credentials alone will not unlock the requested real label scenarios.',
   '- Complete a sandbox Stripe Checkout card/payment/callback lifecycle and refund/decline exercises. Account authentication and rolled-back ledger probes are not equivalent to this evidence.',
   '- Provide a genuine HubSpot test account with Companies/Contacts read/write scopes. Current account configuration is PRODUCTION, synchronization/provisioning are disabled, and Companies read access returns 403. Validate the low-credit property requirement separately; current contract coverage does not prove it exists.',
   '- Use the joined WhatsApp sandbox phone for inbound commands and confirm outbound delivery receipts after carriers are enabled. A valid Twilio account response is not a delivered message.',
   '- Complete the 150-order customs review/signature and configure a genuine test storefront before asserting combined native labels and marketplace fulfillment pushback.',
   '- Supplemental browser checks cover login/recovery, navigation, dark-control contrast and exception actions using controlled data; they do not certify every live provider journey. See docs/uat_200/README.md.',
   '']
  for row in self.results:
   lines.extend([f"## {row['id']} · {row['category']} · {row['focus']}",'',f"**Status:** {row['status']} · **Scope:** {row['scope']} · **Time:** {row['elapsed_ms']} ms",'', '**Execution steps:**',''])
   lines.extend(f'{i}. {step}' for i,step in enumerate(row['steps'],1))
   assertion=row['assertions']
   if row['scope']=='contract':assertion='Assertions in the referenced executable contract test (controlled dependencies), not a live remote record assertion.'
   lines.extend(['', '**Assertions:** '+assertion,'','**Evidence:** '+str(row['evidence']),''])
  (self.root/'UAT_EXECUTION_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')


def execute(case,run):
 kind=case['kind']
 if kind=='http':
  headers={}
  if case.get('mode')=='malformed':headers['Authorization']='Bearer spoofed.invalid.token'
  if case.get('role'):
   identity=run.sessions.get(case['role'])
   if not identity:return 'BLOCKED','Disposable verified identity could not be provisioned: '+str(run.readiness.get('auth_setup_error'))
   headers['Authorization']='Bearer '+identity['token']
  path=case['path']
  if 'tenant_id=00000000' in path:path=path.replace('00000000-0000-4000-8000-000000000001',run.foreign_tenant)
  elif '/customs/00000000' in path:path=path.replace('00000000-0000-4000-8000-000000000001',run.foreign_shipment)
  response=run.client.request(case['method'],path,headers=headers)
  foreign_rows=0
  if response.status_code==200 and '/manifest' in path:
   foreign_rows=sum(str(row.get('tenant_id'))!=identity['tenant'] for row in response.json().get('shipments',[]))
  if response.status_code not in case['expected']:
   return 'FAIL',f"Expected {case['expected']}, observed HTTP {response.status_code}; foreign manifest rows={foreign_rows}. Foreign tenant query parameter tested against a real other sandbox tenant."

  if response.status_code==200 and '/manifest' in case['path']:
   data=response.json();rows=data.get('shipments',[]) if isinstance(data,dict) else data
   assert all(str(row.get('tenant_id',identity['tenant']))==identity['tenant'] for row in rows),'Cross-tenant row detected'
  return 'PASS',f"Live local API HTTP {response.status_code}; real Supabase-backed authentication where role specified."
 if kind=='contract':
  module,cls,method=case['target'].split('.')
  instance=getattr(importlib.import_module(module),cls)(method);result=unittest.TestResult();instance.run(result)
  assert result.testsRun==1
  if result.errors or result.failures:
   error=(result.errors+result.failures)[0][1];raise AssertionError(error[-1600:])
  if result.skipped:return 'BLOCKED','Existing contract skipped: '+result.skipped[0][1]
  status='PARTIAL' if case['category'] in ['C','D','E','F'] else 'PASS'
  return status,'Contract assertions passed: '+case['target']+'; controlled dependencies, no genuine provider transaction.'
 if kind=='cargo-positive':
  from backend.automation_freight_engine import Cargo,calculate_cargo_charge
  result=calculate_cargo_charge(Cargo.model_validate(case['cargo']))
  assert Decimal(result['billable_weight_kg'])==Decimal(case['expected_weight']),result
  return 'PASS',f"Actual Decimal calculation: {result}"
 if kind=='cargo':
  from backend.automation_freight_engine import Cargo,calculate_cargo_charge
  data={'cargo_type':'PARCEL','length_cm':'60','width_cm':'50','height_cm':'40','actual_weight_kg':'2.5'};data[case['axis']]=case['value']
  try:calculate_cargo_charge(Cargo.model_validate(data))
  except (ValidationError,ValueError,ArithmeticError):return 'PASS','Invalid cargo rejected by actual application model/Decimal calculation.'
  raise AssertionError('Invalid cargo entered charging logic')
 if kind=='probe':
  env={**os.environ,'PYTHONPATH':str(run.root)+os.pathsep+str(run.root/'tests')}
  response=subprocess.run([sys.executable,str(run.root/'tests'/case['probe'])],cwd=run.root,env=env,capture_output=True,text=True,timeout=60)
  assert response.returncode==0,'Real DB probe failed; see probe implementation, no raw credential logs included.'
  return 'PASS','Real Supabase probe assertions passed; all mutations rolled back: '+case['probe']
 if kind=='csv':
  from backend.order_csv import parse_batch_csv
  from main import RatingRequest
  rows=list(csv.DictReader(io.StringIO(run.csv_bytes.decode())))
  if case['variant']=='missing_zip':rows[74]['destination_postal_code']=''
  if case['variant']=='bad_weight':rows[74]['weight_kg']='NaN'
  if case['variant']=='duplicate_reference':rows[74]['order_reference']=rows[0]['order_reference']
  output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=run.csv_fields);writer.writeheader();writer.writerows(rows)
  parsed=parse_batch_csv(output.getvalue().encode(),RatingRequest)
  assert len(parsed)==150
  errors=sum(bool(row.get('error')) for row in parsed)
  assert errors==(0 if case['variant']=='valid150' else 1),f'Expected isolated errors, observed {errors}'
  valid=[row for row in parsed if not row.get('error')]
  assert all(row['customs_required'] for row in valid),'International customs flag lost'
  assert all(row['hs_suggestion'] for row in valid),'HS suggestion absent'
  assert all('hs_codes_reviewed' in row['missing_fields'] for row in valid),'Unreviewed HS codes accepted automatically'
  return 'PARTIAL',f'150 rows parsed; {errors} isolated errors; model/customs staging only, no actual labels or marketplace transactions.'
 if kind=='blocked':
  dep=case['dependency']
  if dep=='hubspot':reason=f"HubSpot enabled={run.readiness.get('hubspot_enabled')}; companies endpoint HTTP={run.readiness.get('hubspot_companies_http')}; genuine CRM lifecycle writes not executed."
  elif dep=='twilio':reason=f"Twilio account HTTP={run.readiness.get('twilio_account_http')}; actual phone roundtrip/delivery not automated; active TEST carriers={run.readiness.get('active_test_carriers')}."
  else:reason=f"Active TEST carriers={run.readiness.get('active_test_carriers')}; native sandbox purchases are fenced; genuine card completion/store dispatch not executed."
  return 'BLOCKED',reason
 raise AssertionError('Unknown case kind')
