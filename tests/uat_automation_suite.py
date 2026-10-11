"""Exactly 200 UAT cases. Outcomes never conflate mocked contracts with live workflows."""
import ast, importlib, json, sys, time, unittest
from pathlib import Path
import httpx, pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from uat_200.runtime import Runtime, execute


def contract_cases(files, limit, exclude=()):
    result=[]
    for name in files:
        path=ROOT/'tests'/f'{name}.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        for cls in tree.body:
            if not isinstance(cls,ast.ClassDef):continue
            for fn in cls.body:
                if isinstance(fn,(ast.FunctionDef,ast.AsyncFunctionDef)) and fn.name.startswith('test_'):
                    target=f'{name}.{cls.name}.{fn.name}'
                    if any(part in target for part in exclude):continue
                    result.append({'kind':'contract','focus':fn.name[5:].replace('_',' '),'target':target,
                        'source':f'tests/{name}.py:{fn.lineno}',
                        'steps':[f'Run isolated existing test {target}; its provider/database dependencies are controlled fixtures.'],
                        'assertions':ast.get_source_segment(path.read_text(encoding='utf-8-sig'),fn)})
    assert len(result)>=limit,(files,len(result),limit)
    return result[:limit]


def build_cases():
    groups={}
    # Real local API calls with disposable, password-verified Supabase identities.
    endpoints=[('/api/v1/shipments/manifest','GET'),('/api/v1/wallet','GET'),('/api/v1/profile','GET'),
        ('/api/v1/admin/tenants','GET'),('/api/v1/admin/margins','GET'),('/api/v1/admin/carriers','GET'),
        ('/api/v1/admin/platform-carriers','GET'),('/api/v1/admin/transactions','GET'),
        ('/api/v1/support/tickets','GET'),('/api/v1/dispatch-workspace/orders','GET')]
    groups['A']=[{'kind':'http','focus':f'{mode} authorization on {path}','path':path,'method':method,'mode':mode,'expected':[401],
        'steps':[f'{method} {path} with {mode} bearer credentials'],'assertions':'HTTP 401; no tenant records returned.'}
        for path,method in endpoints for mode in ['missing','malformed']]
    for role,path,expected in [
        ('DISPATCHER','/api/v1/profile',[200]),('OWNER','/api/v1/profile',[200]),('ACCOUNTANT','/api/v1/profile',[200]),
        ('DISPATCHER','/api/v1/shipments/manifest',[200]),('OWNER','/api/v1/shipments/manifest',[200]),
        ('DISPATCHER','/api/v1/wallet',[403]),('ACCOUNTANT','/api/v1/wallet',[200]),
        ('DISPATCHER','/api/v1/admin/tenants',[403]),('OWNER','/api/v1/admin/tenants',[403]),
        ('ACCOUNTANT','/api/v1/admin/transactions',[403]),('DISPATCHER','/api/v1/admin/platform-carriers',[403]),
        ('DISPATCHER','/api/v1/shipments/manifest?tenant_id=00000000-0000-4000-8000-000000000001',[400,403,422]),
        ('OWNER','/api/v1/automation/customs/00000000-0000-4000-8000-000000000001',[403,404]),
        ('DISPATCHER','/api/v1/analytics/reports?start_date=2026-09-01&end_date=2026-10-31',[403]),
        ('OWNER','/api/v1/admin/analytics/dashboard?start_date=2026-09-01&end_date=2026-10-31',[403])]:
        groups['A'].append({'kind':'http','focus':f'{role} boundary {path}','role':role,'path':path,'method':'GET','expected':expected,
            'steps':['Provision disposable auth principal and member in an existing synthetic sandbox tenant.', 'POST /api/v1/auth/token with generated password.',f'GET {path} with verified app JWT.'],
            'assertions':f'HTTP {expected}; manifest rows, when returned, must all belong to the authenticated tenant.'})
    groups['B']=contract_cases(['test_logistics'],2)+contract_cases(['test_automation_freight'],1)
    for cargo,weight,length,width,height,stackable,expected in [
        ('PARCEL','2.5','60','50','40',True,'24.000'),
        ('PARCEL','30','60','50','40',True,'30.000'),
        ('PARCEL','0.1','10.01','10','10',True,'0.201'),
        ('LETTER','0.499',None,None,None,True,'0.499'),
        ('LETTER','0.100',None,None,None,True,'0.100'),
        ('PALLET','100','120','80','100',False,'700.000'),
        ('PALLET','100','120','80','100',True,'319.680'),
        ('OVERLAND_FREIGHT','900','200','120','100',False,'1750.000')]:
        groups['B'].append({'kind':'cargo-positive','focus':f'{cargo} {weight}kg {length}x{width}x{height} stackable={stackable}',
            'cargo':{'cargo_type':cargo,'actual_weight_kg':weight,'length_cm':length,'width_cm':width,'height_cm':height,'stackable':stackable},'expected_weight':expected,
            'steps':['Validate Cargo and execute strict Decimal cargo charging.'],'assertions':f'Billable weight exactly {expected} kg.'})
    for axis in ['length_cm','width_cm','height_cm','actual_weight_kg']:
        for value in ['0','-1','alphabetical','NaN','Infinity',True]:
            groups['B'].append({'kind':'cargo','focus':f'PARCEL rejects {axis}={value!r}','axis':axis,'value':value,
                'steps':['Validate Cargo input and calculate Decimal charge if validation permits it.'],'assertions':'Invalid dimension/weight rejected; no float or NaN enters pricing.'})
    groups['C']=contract_cases(['test_payment_gateway','test_stripe_snapshots','test_sandbox_hooks'],25,exclude=['WhatsApp','SandboxHTTP'])
    for probe in ['dispatcher_wallet_lock_probe.py','stripe_snapshot_database_probe.py']:
        groups['C'].append({'kind':'probe','focus':f'Real sandbox database {probe}','probe':probe,
            'steps':[f'Run tests/{probe} against configured Supabase with transactions rolled back.'],'assertions':'Process exits 0; real lock/financial assertions pass; no fixture balance persists.'})
    for focus in ['Funded 1000 GBP wallet purchases 15 GBP native label','10 GBP wallet blocks 12 GBP native purchase before carrier',
        'Ten identical concurrent native purchases produce one label','Real Stripe Checkout card authorization and completion callback',
        'Real charge refund reconciles wallet debit','Real declined card changes pending topup to FAILED',
        'Webhook replay over public Stripe delivery produces one credit','Real delayed callback eventually reconciles paid wallet']:
        groups['C'].append({'kind':'blocked','focus':focus,'dependency':'carrier-and-payment','steps':['Check sandbox readiness for genuine carrier purchase and real card callback.'],'assertions':'Requires genuine native label purchase or customer/card action; contract tests do not prove this workflow.'})
    groups['D']=contract_cases(['test_hubspot_crm','test_hubspot_activation'],21)
    for focus in ['New tenant Company creation','Primary Contact creation','Contact to Company association','Company reference persisted to Supabase',
        'Lifetime parcel count PATCH','Lifetime spend PATCH','Wallet balance PATCH','Low-credit company lifecycle property',
        'Closed-won webhook authentication','Closed-won workspace provisioning','Closed-won empty wallet creation',
        'HubSpot 429 eventual delivery','CRM event replay deduplication','Non-blocking sync while labels finalize']:
        groups['D'].append({'kind':'blocked','focus':focus,'dependency':'hubspot','steps':['Read live HubSpot settings and companies API scope readiness.'],'assertions':'Real CRM object mutation and matching local state required.'})
    groups['E']=contract_cases(['test_whatsapp_bot','test_sandbox_hooks','test_whatsapp_ingress'],18,exclude=['BillingTests','SandboxHTTP'])
    for focus in ['Real personal-phone quote 5kg GB to US','Real personal-phone three calibrated offers','Live carrier cheapest-offer ordering',
        'Real click-to-book links','Zero-wallet warning delivered to phone','Reserved-wallet warning delivered to phone',
        'Malformed weight instruction delivered','Invalid XYZ country instruction delivered','Missing destination instruction delivered',
        'Unbound phone registration reply delivered','Disabled binding registration reply delivered','Wrong sandbox receiver rejected',
        'Real Twilio webhook retry returns same quote','Carrier timeout message delivered','WhatsApp exception remedy sent',
        'WhatsApp delivery callback commits receipt','Long multi-message quote delivered']:
        groups['E'].append({'kind':'blocked','focus':focus,'dependency':'twilio','steps':['Read real Twilio account and active carrier readiness; verify required phone action/delivery evidence.'],'assertions':'Must include an actual Twilio delivery or inbound phone event; locally signed HTTP alone is insufficient.'})
    groups['F']=contract_cases(['test_order_csv','test_ecommerce_sync','test_dispatch_workspace'],20)
    for variant in ['valid150','missing_zip','bad_weight','duplicate_reference']:
        groups['F'].append({'kind':'csv','focus':f'150-row CSV {variant} parsing and isolation','variant':variant,
            'steps':['Read generated veloce_bulk_test_150.csv.',f'Apply {variant} variation; parse every row through real CSV/model controller.'],
            'assertions':'150 result rows; expected invalid rows isolated; international data retained and customs staging applied.'})
    groups['F'].append({'kind':'blocked','focus':'150 real international labels, customs bundle and live marketplace pushback','dependency':'carrier-and-store',
        'steps':['Verify live carrier and connected store prerequisites.'],'assertions':'All 150 native labels and genuine store fulfillment updates required; preview documents do not count.'})
    assert {k:len(v) for k,v in groups.items()}=={'A':35,'B':35,'C':35,'D':35,'E':35,'F':25}
    cases=[]
    for category,items in groups.items():
        for item in items:
            item.update(id=f'TC-{len(cases)+1:03}',category=category);cases.append(item)
    return cases

CASES=build_cases()
@pytest.fixture(scope='session')
def runtime():
    run=Runtime(ROOT,CASES)
    try:
        run.prepare()
        yield run
    finally:
        run.cleanup()
        run.report()

@pytest.mark.parametrize('case',CASES,ids=[c['id'] for c in CASES])
def test_uat(case,runtime):
    start=time.perf_counter()
    result={'id':case['id'],'category':case['category'],'focus':case['focus'],'steps':case['steps'],'assertions':case['assertions'],'scope':case['kind']}
    try:
        status,evidence=execute(case,runtime)
        result.update(status=status,evidence=evidence)
    except Exception as exc:
        result.update(status='FAIL',evidence=f'{type(exc).__name__}: {str(exc)[:1200]}')
    finally:
        result['elapsed_ms']=round((time.perf_counter()-start)*1000,2);runtime.results.append(result)
    if result['status']=='FAIL':pytest.fail(str(result['evidence']))
    if result['status'] in ['BLOCKED','PARTIAL']:pytest.skip(f"{result['status']}: {result['evidence']}")
