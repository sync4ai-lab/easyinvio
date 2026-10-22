"""Build the offline architecture manual from source without starting lifespan."""
from __future__ import annotations
import argparse
import ast
import asyncio
import base64
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import importlib.metadata as metadata
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
import zipfile

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]
EXPORT=PROJECT/'output/EasyInvio-Architecture'
ARCHIVE=PROJECT/'output/EasyInvio-Architecture.zip'
METHODS={'get','post','put','patch','delete','options','head','trace'}
CHAPTERS=[('README.md','Start here'),('functional_architecture.md','Functional architecture'),
 ('technical_architecture.md','Technical architecture'),('agent_reference.md','Agent reference'),
 ('security_and_finance.md','Security and finance'),('integrations.md','Integrations'),
 ('data_model.md','Data model'),('operations_runbook.md','Operations runbook'),
 ('testing_and_release.md','Testing and release'),('llm_handoff.md','LLM handoff'),
 ('api_reference.md','API reference'),('configuration_reference.md','Configuration reference'),
 ('data_dictionary.md','Data dictionary'),('source_reference.md','Source and test catalog')]
PACKAGES={'API framework':'fastapi','ASGI server':'uvicorn','ASGI foundation':'starlette',
 'Validation':'pydantic','Configuration':'pydantic-settings','Async HTTP':'httpx',
 'PostgreSQL driver':'asyncpg','JWT':'PyJWT','Encryption':'cryptography','Payments SDK':'stripe',
 'Messaging SDK':'twilio','OpenAI client':'openai','Agents SDK':'openai-agents',
 'PDF generation':'reportlab','PDF merging':'pypdf','Spreadsheet input':'openpyxl',
 'Images':'Pillow','Carrier image rasterization':'PyMuPDF','Help rendering':'Markdown','Uploads':'python-multipart','Safe XML':'defusedxml',
 'Country codes':'pycountry','Environment files':'python-dotenv','Test runner':'pytest',
 'Async testing':'pytest-asyncio','Browser testing':'playwright'}
DIAGRAMS={
 'technical_architecture':('Technical architecture','Logical services in one FastAPI application; provider commits are independent of SQL.',[
  ('clients','Web and messaging','SPA; WhatsApp; merchant gateways|Role-aware forms and conversations'),
  ('auth','Identity and ingress','Auth/JWT; signed WhatsApp queue|Tenant binding; audited assistance'),
  ('api','FastAPI application','Routers; lifespan; shared clients|Pydantic validation; async pools'),
  ('ai','Optional AI layer','Supervisor; typed workers; budgets|Grounded advice; no wallet authority'),
  ('domain','Native domain services','Rating; booking; finance; returns|Customs; claims; dispatch; tracking'),
  ('external','External integrations','Carriers; Stripe; PAF; Auth; Twilio|Stores; insurer; CRM; tariff; OpenAI'),
  ('help','Published help corpus','Versioned guide chunks and citations|Lexical / local 256D vector retrieval'),
  ('db','Supabase data services','Postgres locks; ledger; manifests|Private QR Storage; receipts; audit'),
  ('jobs','Operational workers','Ordered WhatsApp; SQL outboxes|Polling; realtime; reconciliation')],
  [('clients','auth'),('auth','api'),('api','domain'),('ai','domain'),('ai','help'),('domain','external'),('domain','db'),('db','jobs'),('jobs','external')]),
 'functional_architecture':('Functional architecture','Business and individual workspaces share one shipping and financial lifecycle.',[
  ('join','01 Register and verify','Business or personal profile|Website / WhatsApp identity proof'),
  ('setup','02 Configure workspace','Team; addresses; contacts; products|Return warehouse; carrier access'),
  ('intake','03 Bring in orders','Manual; CSV; stores; marketplace|References and actionable row errors'),
  ('prepare','04 Prepare real shipment','Measured boxes; goods allocation|Real addresses; customs review'),
  ('rate','05 Compare eligible rates','Business rules or individual markup|Deterministic top ten; optional badge'),
  ('select','06 Confirm selected offer','Price; expiry; role; connection|No model authorizes purchase'),
  ('pay','07 Arrange payment','Workspace reservation or Stripe|Verified events; exact total/currency'),
  ('book','08 Buy and document','Native label confirmation; capture|PDF/forms; unknown outcomes retained'),
  ('track','09 Track and synchronize','Milestones; exceptions; eligible POD|Store and support outboxes'),
  ('returns','10 Return full parcel','Return warehouse; fresh quote|Retailer/customer pay; real QR or print'),
  ('resolve','11 Resolve and reconcile','Invoice disputes; eligible claims|Evidence; verified settlement'),
  ('operate','12 Operate platform','Cohort reports; margins; support|Audited client assistance')],
  [('join','setup'),('setup','intake'),('intake','prepare'),('prepare','rate'),('rate','select'),('select','pay'),('pay','book'),('book','track'),('track','returns'),('track','resolve'),('track','operate')]),
 'agent_architecture':('Agent responsibilities','Typed optional model output proposes facts or advice; native code owns actions.',[
  ('channels','Authenticated channels','Web chat; signed WhatsApp|Real user context; stable message IDs'),
  ('gateway','Conversational gateway','Typed intents; private turn drafts|Explicit action grammar; role checks'),
  ('native','Native action services','Quote; book; track; top-up|Claim intake; full-parcel return'),
  ('ingest','Worker 1 Ingestion','Quote/conversation facts; CSV headers|No invented facts, identifiers or units'),
  ('supervisor','LogisticsSupervisor','Workflow state; bounded delegation|Runtime: one turn; strict outputs'),
  ('customs','Worker 2 Customs','Reviewed catalog / supplied candidates|Official tariff ranker; human review'),
  ('rag','HelpRetriever','Published guide retrieval / citations|Lexical fallback; optional embeddings'),
  ('margin','Worker 3 Margin optimizer','Immutable priced shortlist|Budget eligibility; optional badge'),
  ('delegates','Workers 4 and 5','Exact invoice audit; native support|Deterministic delegates; no LLM call')],
  [('channels','gateway'),('gateway','native'),('gateway','supervisor'),('supervisor','ingest'),('supervisor','customs'),('supervisor','rag'),('supervisor','margin'),('supervisor','delegates')]),
 'booking_lifecycle':('Booking and financial outcomes','A reserved hold, submitted mutation, captured charge and refund are distinct.',[
  ('offer','Selected prepared offer','Tenant; role; goods; exact total|Current expiry and connection snapshot'),
  ('check','Validate environment','Approved connection; test/live mode|Ready customs; bookability; funding'),
  ('lock','Fence concurrent work','Advisory lock and idempotency key|Immutable selected price snapshot'),
  ('reserve','Reserve workspace funds','Wallet/billing row lock|Atomic reservation and ledger state'),
  ('submit','Commit submitted state','Write-ahead mutation fence|Never blindly duplicate a purchase'),
  ('provider','Native carrier purchase','Buy once; retain provider reference|Later retrieval uses GET only'),
  ('success','Confirmed success','Persist label/tracking; capture once|Queue appropriate store tracking'),
  ('reject','Definitive rejection','Native financial release|New quote before a new purchase'),
  ('unknown','Unknown or interrupted','Retain reserved credit/reference|GET/poll/review; no blind retry')],
  [('offer','check'),('check','lock'),('lock','reserve'),('reserve','submit'),('submit','provider'),('provider','success'),('provider','reject'),('provider','unknown')]),
 'returns_lifecycle':('Reviewed reverse logistics','Manual review and automated commands share native booking and payment fences.',[
  ('input','Return ingress','Authenticated UI/API/chat|Delivered original; tenant/store scoped'),
  ('receipt','Durable original-parent fence','Tenant; actor; source; input digest|One full-parcel return; replay observes'),
  ('parent','Restore and review','Original customer becomes origin|RETURN warehouse/version; edit packing/customs'),
  ('rate','Fresh return comparison','Manual: select an unexpired offer|Auto: authorized price cap and complete rates'),
  ('payer','Charge bearer','Retailer: native workspace billing|Customer: owner/admin Stripe link'),
  ('book','Native booking lifecycle','No label before verified customer pay|Existing locks and financial settlement'),
  ('qr','Confirmed drop-off document','Sendcloud labelless / USPS form|Real provider asset; scoped share link'),
  ('print','Printable fallback','No universal QR or location promise|Selected carrier eligible locations'),
  ('status','Customer instructions / observe','Private email/WhatsApp receipts; opted in|Payment link first; label after payment')],
  [('input','parent'),('parent','rate'),('rate','receipt'),('receipt','payer'),('payer','book'),('book','qr'),('book','print'),('qr','status'),('print','status')]),
 'onboarding_lifecycle':('Conversational onboarding','Deterministic state machine; identity proof precedes workspace activation.',[
  ('ingress','Signed inbound greeting','Unbound sender opts into signup|Scoped receipt and delivery fence'),
  ('persona','Choose account persona','Business or Individual|Server-owned workspace_type'),
  ('business','Business company/profile','Company and registration number|Required business profile facts'),
  ('individual','Individual email path','Skip corporate metadata|Personal name after proof'),
  ('email','Collect valid email','Identity collision checks|Supabase issues email OTP'),
  ('phone','Separate phone challenge','Six-digit code stored as HMAC|Expiry; resend and attempt budget'),
  ('verify','Verify two proofs','EMAIL_CODE then PHONE_CODE in chat|Email accepts 6-10 digits; phone six'),
  ('provision','Finalize workspace','Auth binding plus SQL transaction|Tenant; OWNER; zero GBP wallet'),
  ('desktop','Desktop password setup','Auth single-use recovery email|Allowlisted app origin; normal login')],
  [('ingress','persona'),('persona','business'),('persona','individual'),('business','email'),('individual','email'),('email','phone'),('phone','verify'),('verify','provision'),('provision','desktop')])}

def write(name,value):
    (ROOT/name).write_text(value.rstrip()+'\n',encoding='utf-8',newline='\n')

def dump(name,value):
    write(name,json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')

def sha(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_sha(path):
    import hashlib
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()

def rel(path):return Path(path).resolve().relative_to(PROJECT).as_posix()
def cell(value):return str(value).replace('|','&#124;').replace('\n',' ')
def link(file,line,rev):return f'https://github.com/sync4ai-lab/easyinvio/blob/{rev}/{file}#L{line}'
def chapter_id(name):return 'chapter-'+Path(name).stem.lower().replace('_','-')

def routes(router,prefix=''):
    for route in router.routes:
        if hasattr(route,'original_router'):
            yield from routes(route.original_router,prefix+getattr(route.include_context,'prefix',''))
        elif hasattr(route,'endpoint'):yield prefix+getattr(route,'path_format',getattr(route,'path','')),route

def dependencies(dependant):
    result=[]
    for dep in getattr(dependant,'dependencies',[]):
        result.append(getattr(dep.call,'__name__',type(dep.call).__name__))
        result.extend(dependencies(dep))
    return sorted(set(result))

def endpoint_source(endpoint):
    try:
        file=rel(inspect.getsourcefile(endpoint));body,line=inspect.getsourcelines(endpoint)
        tree=ast.parse(textwrap.dedent(''.join(body)))
        guards=sorted({ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call) and re.search(r'auth|permitted|permission|require_|validate_tenant|signature|authorize',ast.unparse(n.func),re.I)})
        roles=[ast.unparse(n) for n in ast.walk(tree) if isinstance(n,ast.Compare) and '.role' in ast.unparse(n.left)]
        return {'file':file,'line':line,'function':endpoint.__qualname__,'guard_calls':guards,'inline_role_conditions':roles}
    except (OSError,TypeError,ValueError,SyntaxError):
        return {'file':None,'line':None,'function':getattr(endpoint,'__qualname__','framework'),'guard_calls':[],'inline_role_conditions':[]}

def auth(path,deps):
    if any('platform_owner' in d for d in deps):return 'Platform owner dependency; additional source/helper guards apply'
    if 'authenticate' in deps:return 'Authenticated workspace dependency; endpoint/helper role and tenant guards apply'
    if path.endswith('/return-dropoff'):return 'Scoped signed return-document capability token'
    if 'webhook' in path or 'insurance-updates' in path:return 'Callback-specific signature/identity/tenant checks in handler and service'
    if path.startswith('/api/v1/auth/'):return 'Identity/registration/recovery-specific validation and limits'
    if path.startswith('/api/v1/admin/'):return 'Platform administrative handler/helper validation; inspect source'
    if '/assistance' in path:return 'Operator/session-specific validation; inspect source'
    if 'preview' in path:return 'Preview/configuration guard; not live integration evidence'
    if path.startswith('/help') or path in {'/','/set-password','/health','/api/v1/config'}:return 'Public UI/help/health/config surface; inspect projection'
    return 'Handler/service validation; declared dependencies are not the full security policy'

def build_api(spec,app,revision):
    mapped={};sockets=[];extra=[]
    for path,route in routes(app):
        info=endpoint_source(route.endpoint)|{'dependencies':dependencies(getattr(route,'dependant',None))}
        if type(route).__name__.endswith('WebSocketRoute'):
            sockets.append({'path':path,**info});continue
        for method in sorted(getattr(route,'methods',[]) or []):
            mapped[method.lower(),path]=info
            if method.lower() not in spec.get('paths',{}).get(path,{}):extra.append({'method':method,'path':path,**info})
    operations=[]
    for path,items in sorted(spec['paths'].items()):
        for method,op in sorted(items.items()):
            if method not in METHODS:continue
            info=mapped.get((method,path))
            if info is None:raise ValueError('Missing route mapping: '+method+' '+path)
            operations.append({'method':method.upper(),'path':path,'operation_id':op.get('operationId'),
                'summary':op.get('summary',''),'tags':op.get('tags',[]),'authorization_summary':auth(path,info['dependencies']),**info,
                'parameters':op.get('parameters',[]),'request_body':op.get('requestBody'),'responses':op.get('responses',{}),
                'declared_security':op.get('security',[]),'source_url':link(info['file'],info['line'],revision) if info['file'] else None,
                'anchor':'op-'+re.sub('[^a-z0-9]+','-',method+'-'+path.lower()).strip('-')})
    dump('api_inventory.json',{'operations':operations,'websockets':sockets,'non_schema_routes':extra,
        'note':'Dependency metadata is not a complete authorization policy. No lifespan was started.'})
    lines=['# API reference','',f'{len(operations)} OpenAPI HTTP operations across {len(spec["paths"])} paths are listed below, followed by WebSocket/non-schema routes and every request/response component. This export imports the app without starting lifespan.','',
      'Use [openapi.json](openapi.json) for structural contracts and [api_inventory.json](api_inventory.json) for source/dependency mapping. Custom Python validators can impose stricter rules than generated JSON Schema, including rejecting floats on a Decimal field. Empty response schemas do not prove an empty response; read the handler/service when no response model is declared.','',
      'Workspace Bearer authentication, platform-owner allowlisting, callback signatures, scoped document tokens and preview guards are different. Missing OpenAPI security metadata never establishes anonymous access. Guards may live in called helpers.','',
      '## Shared conventions','',
      '- Preserve exact decimal strings and currency as required by the component schema. NaN/infinity and unsupported floats are not money.','- Keep a stable request/idempotency UUID for one semantic action; changed payloads conflict. Never resubmit an uncertain charge as a new key.','- Inspect every batch item and count; HTTP success does not prove every item booked.','- 401 concerns identity/signature, 403 scope/permission/activation, 404 scoped lookup, 409 conflict/review/expiry, 422 validation/readiness. A timeout/5xx can retain an unknown outcome; handlers may document more specific statuses.','',
      '## HTTP operation index','', '| Method | Path | Summary |','| --- | --- | --- |']
    for row in operations:lines.append(f'| {row["method"]} | [{cell(row["path"])}](#{row["anchor"]}) | {cell(row["summary"])} |')
    lines+=['','## Operation contracts','']
    for row in operations:
        lines += [f'<a id="{row["anchor"]}"></a>',f'### {row["method"]} {row["path"]}','',row['authorization_summary']+'.','',
          f'Implementation: [{row["file"]}:{row["line"]}]({row["source_url"]}), `{row["function"]}`.','',
          'Declared dependencies: '+(', '.join('`'+d+'`' for d in row['dependencies']) or 'none')+'.',
          'Guard/helper calls in handler: '+(', '.join('`'+d+'`' for d in row['guard_calls']) or 'follow linked implementation and service')+'.','']
        if row['inline_role_conditions']:lines+=['Inline role conditions: '+'; '.join('`'+d+'`' for d in row['inline_role_conditions'])+'.','']
        if row['parameters']:
            lines+=['Parameters:','','```json',json.dumps(row['parameters'],indent=2,ensure_ascii=False),'```','']
        lines+=['Request body:','','```json',json.dumps(row['request_body'],indent=2,ensure_ascii=False),'```','',
            'Documented responses:','','```json',json.dumps(row['responses'],indent=2,ensure_ascii=False),'```','']
    lines+=['## WebSocket contract','',
      '`/api/v1/dispatch-workspace/live` requires an approved Origin, rejects URL query tokens, and expects the first JSON message within ten seconds to contain access_token. Assistance adds assistance_session_id when applicable. It applies normal authentication and revalidates membership while sending events. Messages include refresh_required, shipment_changed and heartbeat. A bounded queue overflow or listener reconnect requires HTTP refresh. The broker enforces a maximum of 100 sockets; these are notifications, not booking or wallet commands.','']
    for row in sockets:lines.append(f'- `{row["path"]}` — [{row["file"]}:{row["line"]}]({link(row["file"],row["line"],revision)}).')
    lines+=['','## Routes excluded from OpenAPI','', '| Method | Path | Handler |','| --- | --- | --- |']
    for row in extra:lines.append(f'| {row["method"]} | `{cell(row["path"])}` | `{cell(row["function"])}` |')
    lines+=['','## Component schema dictionary','',
      'All schema branches, constraints, required fields and defaults are retained. Follow nested $ref entries through openapi.json. Source defaults are not active account configuration.','']
    for name,definition in sorted(spec.get('components',{}).get('schemas',{}).items()):
        lines+=['### '+name,'','```json',json.dumps(definition,indent=2,ensure_ascii=False),'```','']
    write('api_reference.md','\n'.join(lines)+'\n')
    return operations,sockets,extra

def build_sources(revision):
    modules=[];settings=[];calls=[]
    sources=[PROJECT/'main.py',*sorted((PROJECT/'backend').rglob('*.py'))]
    parsed={path:ast.parse(path.read_text(encoding='utf-8-sig')) for path in sources}
    # Include fields declared on inherited settings classes without instantiating
    # them or reading private environment values.
    settings_names={'BaseSettings'}
    while True:
        found={node.name for tree in parsed.values() for node in tree.body
               if isinstance(node,ast.ClassDef) and any(
                   (base.id if isinstance(base,ast.Name) else base.attr if isinstance(base,ast.Attribute) else '')
                   in settings_names for base in node.bases)}
        if found.issubset(settings_names):break
        settings_names.update(found)
    for path in sources:
        text=path.read_text(encoding='utf-8-sig');tree=parsed[path];file=rel(path);classes=[];functions=[]
        for node in tree.body:
            if isinstance(node,ast.ClassDef):
                classes.append({'name':node.name,'line':node.lineno,'methods':[{'name':m.name,'line':m.lineno,'async':isinstance(m,ast.AsyncFunctionDef)} for m in node.body if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef))]})
                if node.name in settings_names:
                    prefix=''
                    for item in node.body:
                        if isinstance(item,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='model_config' for t in item.targets) and isinstance(item.value,ast.Call):
                            prefix=next((k.value.value for k in item.value.keywords if k.arg=='env_prefix' and isinstance(k.value,ast.Constant)),'')
                    for item in node.body:
                        if isinstance(item,ast.AnnAssign) and isinstance(item.target,ast.Name):
                            settings.append({'file':file,'line':item.lineno,'class':node.name,'field':item.target.id,'environment_name':prefix+item.target.id.upper(),
                                'annotation':ast.unparse(item.annotation),'default_expression':ast.unparse(item.value) if item.value else 'required'})
            elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                functions.append({'name':node.name,'line':node.lineno,'async':isinstance(node,ast.AsyncFunctionDef)})
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='run' and 'runtime' in ast.unparse(node.func.value) and len(node.args)>=4:
                calls.append({'file':file,'line':node.lineno,'worker':node.args[1].value if isinstance(node.args[1],ast.Constant) else ast.unparse(node.args[1]),
                    'instructions':node.args[2].value if isinstance(node.args[2],ast.Constant) else ast.unparse(node.args[2]),
                    'output_type':next((ast.unparse(k.value) for k in node.keywords if k.arg=='output_type'),None),
                    'tools':next((ast.unparse(k.value) for k in node.keywords if k.arg=='tools'),None)})
        modules.append({'file':file,'sha256':source_sha(path),'docstring':ast.get_docstring(tree),'classes':classes,'functions':functions,
            'referenced_public_sql_objects':sorted(set(re.findall(r'\bpublic\.([a-z_][a-z0-9_]*)',text,re.I))),'source_url':link(file,1,revision)})
    tests=[{'file':rel(p),'sha256':source_sha(p)} for p in sorted((PROJECT/'tests').iterdir()) if p.is_file() and p.suffix in {'.py','.cjs','.sql'}]
    dump('source_map.json',{'modules':modules,'test_and_probe_files':tests,'hash_format':'SHA-256 with CRLF normalized to LF','note':'Diagnostic/probe filenames do not authorize execution. Review side effects first.'})
    from backend.agents import models
    from pydantic import BaseModel
    schemas={n:v.model_json_schema() for n,v in vars(models).items() if isinstance(v,type) and issubclass(v,BaseModel) and v.__module__==models.__name__}
    from backend.agents.margin_optimizer import StrategicChoice
    from backend.agents.conversation_context import ConversationDraft
    schemas.update(StrategicChoice=StrategicChoice.model_json_schema(),ConversationDraft=ConversationDraft.model_json_schema())
    dump('agent_contracts.json',{'model_calls':calls,'schemas':schemas,'settings':[r for r in settings if r['class']=='AgentSettings']})
    names=[m[1] for line in (PROJECT/'.env.example').read_text(encoding='utf-8').splitlines() if (m:=re.match(r'^([A-Z][A-Z0-9_]*)=',line))]
    dump('configuration.json',{'source_fields':settings,'example_variable_names':names,'privacy':'Source expressions and example variable names only. No settings class was instantiated; no private .env values were read.'})
    lines=['# Configuration reference','',
      'Source declarations below are not private environment values or active settings. Field expressions retain bounds/validators/aliases. Variable names include declared env_prefix; consult any validation_alias expression for accepted alternatives.','',
      '| Environment name | Owner/field | Type | Source default or constraints | Source |','| --- | --- | --- | --- | --- |']
    for r in settings:lines.append(f'| `{r["environment_name"]}` | `{r["class"]}.{r["field"]}` | `{cell(r["annotation"])}` | `{cell(r["default_expression"])}` | [{r["file"]}:{r["line"]}]({link(r["file"],r["line"],revision)}) |')
    lines+=['','## Environment example variable names','',', '.join('`'+name+'`' for name in names),'']
    write('configuration_reference.md','\n'.join(lines))
    lines=['# Source and test catalog','',
      'Repository module/class/function locations are listed below. Source links reference the recorded revision. Diagnostic/apply/seed scripts can have live effects; review before execution. Source fingerprints in source_map.json normalize CRLF to LF for portable checkouts; artifact hashes remain exact bytes.','']
    for r in modules:
        lines+=['## '+r['file'],'',f'[Open source]({r["source_url"]})','']
        if r['docstring']:lines += [r['docstring'],'']
        for cls in r['classes']:lines.append(f'- `{cls["name"]}` (line {cls["line"]}): '+', '.join('`'+m['name']+'`' for m in cls['methods'])+'.')
        if r['functions']:lines+=['','Top-level functions: '+', '.join(f'`{f["name"]}` (line {f["line"]})' for f in r['functions'])+'.','']
        if r['referenced_public_sql_objects']:lines+=['Public SQL object references: '+', '.join('`'+v+'`' for v in r['referenced_public_sql_objects'])+'.','']
    lines+=['## Test and probe file index','',*['- `'+r['file']+'`' for r in tests],'']
    write('source_reference.md','\n'.join(lines))
    return modules,tests,settings,calls

def balanced(text,start):
    depth=0;quote=None;i=start
    while i<len(text):
        ch=text[i]
        if quote:
            if ch==quote:
                if i+1<len(text) and text[i+1]==quote:i+=1
                else:quote=None
        elif ch in "'\"":quote=ch
        elif ch=='(':depth+=1
        elif ch==')':
            depth-=1
            if depth==0:return text[start:i+1]
        i+=1
    raise ValueError('Unclosed CREATE TABLE definition')

def build_data(revision):
    migrations=[];tables=[]
    for path in sorted((PROJECT/'migrations').glob('*.sql')):
        text=path.read_text(encoding='utf-8-sig');file=rel(path)
        row={'file':file,'sha256':source_sha(path),'created_tables':[],
            'alter_table_targets':sorted(set(re.findall(r'ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?([a-z_][a-z0-9_]*)',text,re.I))),
            'created_functions':sorted(set(re.findall(r'CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?([a-z_][a-z0-9_]*)',text,re.I)))}
        for m in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([a-z_][a-z0-9_]*)\s*(\()',text,re.I):
            tables.append({'name':m[1],'file':file,'line':text.count('\n',0,m.start())+1,'create_definition':text[m.start():m.start(2)]+balanced(text,m.start(2))+';'})
            row['created_tables'].append(m[1])
        migrations.append(row)
    dump('data_inventory.json',{'migrations':migrations,'hash_format':'SHA-256 with CRLF normalized to LF','create_table_definitions':tables,
      'scope':'Exact repository CREATE TABLE blocks; not live introspection or a final flattened schema after all ALTERs.',
      'baseline_not_fully_in_repository':['tenants','users','carrier_accounts','margin_rules','shipments','wallets','wallet_topups','wallet_reservations','wallet_ledger','whatsapp_bindings','whatsapp_routes','whatsapp_quote_choices','whatsapp_receipts']})
    lines=['# Migration and data dictionary','',
      'The initial core schema is not fully checked in. Obtain an authorized baseline before applying the sequence. Definitions below reproduce source CREATE TABLE blocks; later ALTERs, indexes, triggers, policies and grants remain in linked migrations. This is not a live/final schema dump.','',
      '## Migration index','', '| File | Tables introduced | Tables altered | Functions introduced or replaced |','| --- | --- | --- | --- |']
    for r in migrations:lines.append(f'| [{r["file"]}]({link(r["file"],1,revision)}) | {cell(", ".join(r["created_tables"]))} | {cell(", ".join(r["alter_table_targets"]))} | {cell(", ".join(r["created_functions"]))} |')
    lines+=['','## Exact CREATE TABLE definitions','']
    for r in sorted(tables,key=lambda x:(x['name'],x['file'])):
        lines+=['### '+r['name'],'',f'Source: [{r["file"]}:{r["line"]}]({link(r["file"],r["line"],revision)}).','','```sql',r['create_definition'],'```','']
    write('data_dictionary.md','\n'.join(lines))
    return migrations,tables

def build_versions():
    installed={}
    for package in PACKAGES.values():
        try:installed[package]=metadata.version(package)
        except metadata.PackageNotFoundError:installed[package]='not installed in documentation interpreter'
    result={'captured_at':datetime.now(timezone.utc).isoformat(),'python':sys.version.split()[0],'local_environment':installed,
        'declared_files':{n:(PROJECT/n).read_text(encoding='utf-8').splitlines() for n in ['requirements.txt','requirements.lock.txt','requirements-dev.txt','requirements-test.txt']},
        'frontend':{'framework':'HTML / vanilla JavaScript / CSS','tailwind':'browser CDN major 4; patch not pinned','lucide':'0.468.0'},
        'remote_versions':'Hosted Auth/database and external provider API versions were not queried.'}
    dump('versions.json',result);return result

def build_diagrams():
    dump('diagram_definitions.json',DIAGRAMS)
    for name,(title,subtitle,nodes,edges) in DIAGRAMS.items():
        rows=(len(nodes)+2)//3;height=210+rows*278+90
        svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="{height}" viewBox="0 0 1500 {height}" role="img">',
            f'<title>{escape(title)}</title><desc>{escape(subtitle)}</desc>',
            '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="#64748b"/></marker></defs>',
            f'<rect width="1500" height="{height}" fill="#f8fafc"/>',
            f'<text x="48" y="65" style="font:700 34px Arial,sans-serif;fill:#0f172a">EasyInvio | {escape(title)}</text>',
            f'<text x="48" y="105" style="font:19px Arial,sans-serif;fill:#475569">{escape(subtitle)}</text>']
        positions={n[0]:(48+i%3*478,160+i//3*278) for i,n in enumerate(nodes)}
        for origin,target in edges:
            x1,y1=positions[origin];x2,y2=positions[target]
            if y1==y2:
                start=(x1+440,y1+110) if x2>x1 else (x1,y1+110)
                end=(x2,y2+110) if x2>x1 else (x2+440,y2+110)
            else:start=(x1+220,y1+220) if y2>y1 else (x1+220,y1);end=(x2+220,y2) if y2>y1 else (x2+220,y2+220)
            svg.append(f'<path d="M{start[0]} {start[1]}L{end[0]} {end[1]}" stroke="#94a3b8" stroke-width="2" fill="none" marker-end="url(#arrow)"/>')
        for i,(key,head,description) in enumerate(nodes):
            x,y=positions[key];color='#4f46e5' if i%3==1 else '#059669'
            svg += [f'<g data-node="{key}"><rect x="{x}" y="{y}" width="440" height="220" rx="16" fill="white" stroke="#cbd5e1"/>',f'<rect x="{x}" y="{y}" width="6" height="220" rx="3" fill="{color}"/>']
            ypos=y+38
            for line in textwrap.wrap(head,31):
                svg.append(f'<text x="{x+22}" y="{ypos}" style="font:700 22px Arial,sans-serif;fill:#0f172a">{escape(line)}</text>');ypos+=26
            ypos+=14
            for sentence in description.split('|'):
                for line in textwrap.wrap(sentence,43):
                    svg.append(f'<text x="{x+22}" y="{ypos}" style="font:18px Arial,sans-serif;fill:#334155">{escape(line)}</text>');ypos+=24
            if ypos>y+216:raise ValueError('Diagram overflow: '+name+' '+key)
            svg.append('</g>')
        footer='Logical summary only. Tenant guards, exact money, provider readiness and unknown-outcome reconciliation remain authoritative.'
        for i,line in enumerate(textwrap.wrap(footer,125)):
            svg.append(f'<text x="48" y="{height-54+i*24}" style="font:17px Arial,sans-serif;fill:#475569">{escape(line)}</text>')
        svg.append('</svg>');write(name+'.svg','\n'.join(svg))
        mmd=['%% Same logical nodes/edges as the SVG; detailed contracts are in the manual.','flowchart TB']
        for key,head,description in nodes:mmd.append(f'    {key}["{head}<br/>{description.replace(chr(124),"<br/>")}"]')
        for origin,target in edges:mmd.append(f'    {origin} --> {target}')
        write(name+'.mmd','\n'.join(mmd)+'\n')

CSS='''
:root{color-scheme:light;--ink:#152536;--muted:#475569;--line:#cbd5e1;--accent:#3730a3}*{box-sizing:border-box}html{scroll-padding-top:24px}body{margin:0;font:16px/1.65 system-ui,sans-serif;color:var(--ink);background:#f8fafc}a{color:var(--accent);overflow-wrap:anywhere}aside{position:fixed;inset:0 auto 0 0;width:265px;padding:28px 20px;background:#0f172a;color:#e2e8f0;overflow:auto}aside strong{font-size:21px}aside nav{display:grid;gap:4px;margin-top:24px}aside a{color:#c7d2fe;padding:7px 0;text-decoration:none}aside a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid #10b981;outline-offset:3px}main{max-width:1450px;margin-left:265px;padding:40px 44px}h1{font-size:34px;line-height:1.2}h2{font-size:26px;margin-top:38px}h3{font-size:20px;margin-top:28px}article{border-top:2px solid var(--line);padding:24px 0;margin-top:36px}h1,h2,h3,h4,h5,h6,p,li,td,th,code{overflow-wrap:anywhere}.intro{font-size:18px;max-width:950px}.notice{background:#e0e7ff;border-left:4px solid #4f46e5;padding:18px;border-radius:8px}label{display:block;font-weight:650}input{font:inherit;width:100%;padding:12px;border:1px solid #94a3b8;border-radius:9px;background:white}button{font:inherit;border:1px solid #94a3b8;border-radius:8px;padding:9px 14px;background:white;color:var(--ink);cursor:pointer}pre{white-space:pre;max-width:100%;overflow:auto;padding:18px;background:#0f172a;color:#e2e8f0;border-radius:9px;font-size:13px;line-height:1.55}pre code{overflow-wrap:normal}code{font-size:.88em}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td,th{border:1px solid var(--line);padding:10px;text-align:left;vertical-align:top;max-width:520px}th{background:#e2e8f0}.table-wrap{max-width:100%;overflow-x:auto}img{display:block;width:100%;height:auto;background:white;border:1px solid var(--line)}figure{margin:26px 0}figcaption{font-size:14px;margin-top:8px}small,.muted{color:var(--muted)}#search-results{padding-left:22px}#search-results small{display:block;white-space:normal}.downloads{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0}.skip{position:absolute;left:-10000px}.skip:focus{left:280px;top:8px;background:white;padding:10px}body{overflow-x:clip}@media(max-width:900px){aside{position:static;width:auto;padding:18px}aside nav{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:12px;max-height:220px;overflow:auto}main{margin:0;padding:24px 18px}h1{font-size:28px}h2{font-size:23px}td,th{min-width:130px}.skip:focus{left:10px}}@media print{aside,.search,.downloads,button,.skip{display:none!important}main{margin:0;padding:0;max-width:none}body{background:white;font-size:11pt}pre{white-space:pre-wrap;background:#f1f5f9;color:#111;overflow:visible}article{break-before:page}figure,tr{break-inside:avoid}h1,h2,h3{break-after:avoid}a{color:#111;text-decoration:none}img{max-height:250mm;object-fit:contain}.table-wrap{overflow:visible}td,th{min-width:0;max-width:none;font-size:9pt}}
'''
JS='''
const input=document.querySelector('#manual-search'),results=document.querySelector('#search-results'),status=document.querySelector('#search-status');
const index=[...document.querySelectorAll('article h1,article h2,article h3')].map(h=>{let text=h.textContent,n=h.nextElementSibling;while(n&&!/^H[1-3]$/.test(n.tagName)){text+=' '+n.textContent;n=n.nextElementSibling;}return{id:h.id,title:h.textContent,chapter:h.closest('article').dataset.chapter,text};});
let timer;input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>{results.replaceChildren();const q=input.value.trim().toLowerCase();if(!q){status.textContent='';return;}const terms=q.split(/\\s+/),matches=index.filter(r=>terms.every(t=>r.text.toLowerCase().includes(t)));status.textContent=matches.length?matches.length+' matching sections':'No matching sections. Try a feature, module, API path or state.';for(const r of matches.slice(0,60)){const li=document.createElement('li'),a=document.createElement('a'),small=document.createElement('small');a.href='#'+r.id;a.textContent=r.chapter+' / '+r.title;const offset=Math.max(0,r.text.toLowerCase().indexOf(terms[0])-60);small.textContent=r.text.slice(offset,offset+240);li.append(a,small);results.append(li);}},120);});
document.querySelector('#print-manual').addEventListener('click',()=>window.print());
'''

def build_html(version,count,revision):
    import markdown
    nav=[];articles=[]
    for filename,title in CHAPTERS:
        rendered=markdown.markdown((ROOT/filename).read_text(encoding='utf-8'),extensions=['tables','fenced_code','toc','sane_lists'])
        for other,_ in CHAPTERS:rendered=rendered.replace('href="'+other+'"','href="#'+chapter_id(other)+'"')
        prefix=chapter_id(filename)
        rendered=re.sub(r'(<h[1-6] id=")([^"]+)(")',lambda m:m[1]+prefix+'-'+m[2]+m[3],rendered)
        rendered=re.sub(r'href="#(?!op-|chapter-)([^"]+)"',lambda m:'href="#'+prefix+'-'+m[1]+'"',rendered)
        rendered=re.sub(r'(<table>.*?</table>)',r'<div class="table-wrap">\1</div>',rendered,flags=re.S)
        articles.append(f'<article id="{prefix}" data-chapter="{escape(title)}">{rendered}</article>')
        nav.append(f'<a href="#{prefix}">{escape(title)}</a>')
    figures=[]
    for name,(title,_,_,_) in DIAGRAMS.items():
        figures.append(f'<figure><h3>{escape(title)}</h3><img src="{name}.svg" alt="{escape(title)}" loading="lazy"><figcaption><a href="{name}.svg" download>SVG</a> · <a href="{name}.png" download>PNG</a> · <a href="{name}.mmd" download>Mermaid source</a></figcaption></figure>')
    stack=''.join(f'<tr><td>{escape(purpose)}</td><td>{escape(package)}</td><td>{escape(version["local_environment"][package])}</td></tr>' for purpose,package in PACKAGES.items())
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EasyInvio application manual</title><style>'''+CSS+'''</style></head><body><a class="skip" href="#manual-content">Skip navigation</a><aside><strong>EasyInvio.com</strong><p>Application manual</p><nav>'''+''.join(nav)+'''<a href="#architecture-diagrams">Architecture diagrams</a><a href="#technology-versions">Technology versions</a></nav></aside><main id="manual-content"><h1>EasyInvio application manual</h1><p class="intro">Functional and technical architecture, implemented agents, APIs, integrations, data ownership, financial safeguards and operating procedures for engineers and LLM collaborators.</p><p class="notice">Source revision <code>'''+escape(revision)+'''</code>. Migration coverage through 045. Provider activation and live acceptance are environment-specific. No secrets or customer exports are included.</p><div class="downloads"><a href="manual.md" download>Complete Markdown manual</a><a href="openapi.json" download>OpenAPI JSON</a><a href="api_inventory.json" download>API inventory</a><a href="versions.json" download>Versions</a><button id="print-manual" type="button">Print or save PDF</button></div><section class="search"><label for="manual-search">Search the manual</label><input id="manual-search" type="search" placeholder="Try TRIGGER_RETURN, OTP, wallet, Worker 3, or an API path"><p id="search-status" role="status" aria-live="polite"></p><ol id="search-results"></ol></section><section id="technology-versions"><h2>Technology and local versions</h2><p>Python '''+escape(version['python'])+''' in the documentation interpreter; '''+str(count)+''' OpenAPI operations. Installed versions are not deployed-server versions. Full declarations/lock entries are in versions.json.</p><div class="table-wrap"><table><thead><tr><th>Purpose</th><th>Package</th><th>Installed version</th></tr></thead><tbody>'''+stack+'''</tbody></table></div></section><section id="architecture-diagrams"><h2>Architecture diagrams</h2><p>Logical summaries generated from the same node/edge definitions as the Mermaid files. Detailed guards and field contracts remain in the chapters.</p>'''+''.join(figures)+'''</section>'''+''.join(articles)+'''</main><script>'''+JS+'''</script></body></html>'''
    write('overview.html',html)
    write('manual.md','\n\n'.join(['# EasyInvio complete application manual',f'Source revision: `{revision}`. Read README.md for scope and generation rules.',*[(ROOT/n).read_text(encoding='utf-8') for n,_ in CHAPTERS]])+'\n')

async def render():
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(PROJECT/'.playwright'))
    from playwright.async_api import async_playwright
    async with async_playwright() as driver:
        browser=await driver.chromium.launch();page=await browser.new_page(device_scale_factor=1)
        for name in DIAGRAMS:
            svg=(ROOT/(name+'.svg')).read_bytes();width,height=map(int,re.search(rb'width="(\d+)" height="(\d+)"',svg).groups())
            await page.set_viewport_size({'width':width,'height':height})
            await page.set_content('<body style="margin:0"><img style="display:block" src="data:image/svg+xml;base64,'+base64.b64encode(svg).decode()+'"></body>')
            await page.locator('img').screenshot(path=str(ROOT/(name+'.png')),timeout=10000)
            from PIL import Image, PngImagePlugin
            path=ROOT/(name+'.png');info=PngImagePlugin.PngInfo()
            info.add_text('source_svg_sha256',sha(ROOT/(name+'.svg')))
            with Image.open(path) as image:
                image.save(path,pnginfo=info)
        await browser.close()

class Links(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.links=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.append(attrs['id'])
        if tag=='a' and 'href' in attrs:self.links.append(attrs['href'])
        if tag=='img' and 'src' in attrs:self.links.append(attrs['src'])

def artifacts():return sorted(p for p in ROOT.iterdir() if p.is_file() and p.name!='manifest.json')

def validate(export=False):
    manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    for name,value in manifest['files'].items():
        if not (ROOT/name).is_file() or sha(ROOT/name)!=value:raise ValueError('Stale artifact: '+name)
    source=json.loads((ROOT/'source_map.json').read_text(encoding='utf-8'))
    current_sources={rel(p) for p in [PROJECT/'main.py',*sorted((PROJECT/'backend').rglob('*.py'))]}
    if current_sources!={r['file'] for r in source['modules']}:raise ValueError('Source module inventory changed; rebuild the manual')
    for row in [*source['modules'],*source['test_and_probe_files']]:
        if not (PROJECT/row['file']).is_file() or source_sha(PROJECT/row['file'])!=row['sha256']:
            raise ValueError('Source/test changed; rebuild manual: '+row['file'])
    data=json.loads((ROOT/'data_inventory.json').read_text(encoding='utf-8'))
    if {rel(p) for p in (PROJECT/'migrations').glob('*.sql')}!={r['file'] for r in data['migrations']}:
        raise ValueError('Migration inventory changed; rebuild the manual')
    for row in data['migrations']:
        if source_sha(PROJECT/row['file'])!=row['sha256']:raise ValueError('Migration changed: '+row['file'])
    parser=Links();parser.feed((ROOT/'overview.html').read_text(encoding='utf-8'))
    if len(parser.ids)!=len(set(parser.ids)):raise ValueError('Duplicate HTML anchors')
    for href in parser.links:
        if href.startswith('#'):
            if href[1:] not in parser.ids:raise ValueError('Missing anchor '+href)
        elif not re.match(r'^(https?:|mailto:|data:)',href):
            target=href.split('#',1)[0]
            if target and not (ROOT/target).is_file():raise ValueError('Missing linked artifact '+href)
    spec=json.loads((ROOT/'openapi.json').read_text(encoding='utf-8'));inventory=json.loads((ROOT/'api_inventory.json').read_text(encoding='utf-8'))
    count=sum(k in METHODS for row in spec['paths'].values() for k in row)
    if count!=len(inventory['operations']) or count!=manifest['counts']['http_operations']:raise ValueError('API coverage mismatch')
    def refs(value):
        if isinstance(value,dict):
            if '$ref' in value and value['$ref'].startswith('#/'):
                current=spec
                for k in value['$ref'][2:].split('/'):current=current[k.replace('~1','/').replace('~0','~')]
            for v in value.values():refs(v)
        elif isinstance(value,list):
            for v in value:refs(v)
    refs(spec)
    for name in DIAGRAMS:
        import xml.etree.ElementTree as ET
        ET.parse(ROOT/(name+'.svg'))
        if (ROOT/(name+'.png')).read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid diagram PNG '+name)
        from PIL import Image
        with Image.open(ROOT/(name+'.png')) as image:
            if image.info.get('source_svg_sha256')!=sha(ROOT/(name+'.svg')):
                raise ValueError('PNG is stale; rebuild with --render: '+name)
    if export:
        with zipfile.ZipFile(ARCHIVE) as archive:
            for p in [*artifacts(),ROOT/'manifest.json']:
                if not (EXPORT/p.name).is_file() or sha(p)!=sha(EXPORT/p.name):raise ValueError('Export differs '+p.name)
                if archive.read('EasyInvio-Architecture/'+p.name)!=p.read_bytes():raise ValueError('ZIP differs '+p.name)
    print(json.dumps({'validation':'passed',**manifest['counts'],'export_checked':export}))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render',action='store_true');parser.add_argument('--export',action='store_true');parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if not (PROJECT/'main.py').is_file():raise SystemExit('Run the builder within the project checkout.')
    if args.check:validate(EXPORT.is_dir() and ARCHIVE.is_file());return
    sys.path.insert(0,str(PROJECT))
    import main as application
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,text=True).strip()
    spec=application.app.openapi();dump('openapi.json',spec)
    operations,sockets,extra=build_api(spec,application.app,revision)
    modules,tests,settings,calls=build_sources(revision);migrations,tables=build_data(revision)
    version=build_versions();build_diagrams();build_html(version,len(operations),revision)
    if args.render:asyncio.run(render())
    counts={'http_operations':len(operations),'openapi_paths':len(spec['paths']),'openapi_components':len(spec.get('components',{}).get('schemas',{})),
      'websockets':len(sockets),'non_schema_http_routes':len(extra),'python_modules':len(modules),'test_and_probe_files':len(tests),
      'source_settings':len(settings),'model_call_contracts':len(calls),'migration_files':len(migrations),'create_table_blocks':len(tables),
      'diagrams':len(DIAGRAMS),'chapters':len(CHAPTERS)}
    dump('manifest.json',{'source_revision':revision,'generated_at':datetime.now(timezone.utc).isoformat(),
      'scope':'Source and installed packages only; no lifespan/live provider/database inspection.',
      'counts':counts,'files':{p.name:sha(p) for p in artifacts()}})
    validate()
    if args.export:
        EXPORT.mkdir(parents=True,exist_ok=True)
        for p in [*artifacts(),ROOT/'manifest.json']:shutil.copy2(p,EXPORT/p.name)
        ARCHIVE.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(ARCHIVE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for p in [*artifacts(),ROOT/'manifest.json']:archive.write(p,'EasyInvio-Architecture/'+p.name)
        validate(True)

if __name__=='__main__':main()
