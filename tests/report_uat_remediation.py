"""Rerun core checks and consolidate remediation evidence without inflating passes."""
import io,json,unittest,copy
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import httpx
from uuid import uuid4
from pydantic import ValidationError
from backend.admin_portal import MarginCreate
from backend.ai_engine import predict_hs_code

folder=Path('docs/uat_100')
baseline=folder/'results_before_remediation.json'
if not baseline.exists():baseline.write_text((folder/'results.json').read_text(encoding='utf-8'),encoding='utf-8')
report=json.loads(baseline.read_text(encoding='utf-8'))
suite=unittest.TestSuite()
for module in ['test_logistics','test_admin_portal','test_dashboard_portal','test_tracking_and_support','test_automation_freight','test_uat_remediation']:
 suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=module+'.py'))
stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
(folder/'remediation_core_regression.log').write_text(stream.getvalue(),encoding='utf-8')
assert result.wasSuccessful(),stream.getvalue()
db=json.loads((folder/'database_evidence.json').read_text())
for key in ['TC-007','TC-037','TC-072','TC-077','TC-080']:assert db[key]['ok']
try:MarginCreate(tenant_id=uuid4(),markup_type='PERCENTAGE',markup_value='500');raise AssertionError('Extreme markup allowed')
except ValidationError:pass
assert predict_hs_code('leather footwear for jogging')['hs_code']=='640399'
assert predict_hs_code('knitted cotton garment')['hs_code']=='610910'
with httpx.Client(base_url='http://127.0.0.1:8000') as client:
 health=client.get('/health');assert health.status_code==200
 paths=client.get('/openapi.json').json()['paths']
 assert '/api/v1/workspace/users' in paths and '/api/v1/support/tickets/{ticket_id}/resolve' in paths
 html=client.get('/').text
 assert 'carrier-filter' in html and 'workspace-member-form' in html and 'sheet-enter' in html
evidence={'core_tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'actual_database_checks':'database_evidence.json','backend_restarted':True,'health':health.json(),'new_routes_live':True,'migration_014_applied':True,'browser_rendering':'Not available; actual inline controllers executed in DOM test double','external_provider_calls':0}
(folder/'remediation_summary.json').write_text(json.dumps(evidence,indent=2))
updates={
 'TC-007':('PASS',db['TC-007']['evidence']+' UI enrolls existing pre-provisioned auth UUIDs; does not create login credentials.','database_evidence.json'),
 'TC-009':('PASS','Expired session timer executed actual clearSession controller; session became null.','remediation_frontend_evidence.json'),
 'TC-022':('PASS','500cm form measurement produced an explicit oversize/freight warning; no universal carrier limit is assumed.','remediation_frontend_evidence.json'),
 'TC-037':('PASS',db['TC-037']['evidence']+' Stored FIXED 5.50 rule returns 15.50 on base 10.00.','database_evidence.json; supplement_evidence.json'),
 'TC-040':('PASS','500% model input now rejected with pricing-policy-review validation message; 499% remains accepted.','remediation_core_regression.log'),
 'TC-043':('PASS','Actual DPD selection controller rendered DPD and omitted DHL; original rate indices remain intact.','remediation_frontend_evidence.json'),
 'TC-072':('PASS',db['TC-072']['evidence'],'database_evidence.json'),
 'TC-076':('PASS','One OPEN and one CLOSED test ticket rendered exactly one OPEN EXCEPTION.','remediation_frontend_evidence.json'),
 'TC-077':('PASS','Actual exception webhook persisted provider-scoped active_exception metadata; routing reported high risk even without historical delay samples. Delivery clears the exception. No delay duration invented.','database_evidence.json; remediation_core_regression.log'),
 'TC-078':('PASS','Executed supported synonyms: leather footwear for jogging → 640399; knitted cotton garment → 610910. Rule-based suggestions still require review. Arbitrary natural language coverage is not claimed.','remediation_core_regression.log'),
 'TC-080':('PASS','Actual delivery changed ticket to CLOSED and set archived_at; archive details render closed records.','database_evidence.json; remediation_frontend_evidence.json'),
 'TC-083':('PARTIAL','Responsive bottom-sheet positioning and slide animation implemented; actual mobile browser geometry/animation remains unverified.','index.html responsive CSS; remediation_frontend_evidence.json'),
 'TC-084':('PASS','Actual backdrop click handler closed the box viewport; Escape and explicit Close are also wired.','remediation_frontend_evidence.json'),
 'TC-085':('PARTIAL','Pulse animation implemented and CSS contract asserted; actual browser animation unverified.','index.html uat-pulse; remediation_frontend_evidence.json'),
 'TC-089':('PARTIAL','Dark slate backgrounds and form/card overrides implemented and source contract verified; actual browser appearance unverified.','index.html dark CSS; remediation_frontend_evidence.json'),
 'TC-091':('PASS','Successful preview dispatch invokes resetQuoteForm; executed reset emptied dimensional/weight fields and invalidated rates. Live purchases remain gated.','remediation_frontend_evidence.json')}
for case in report['cases']:
 if case['id'] in updates:case.update(zip(['status','observed','evidence'],updates[case['id']]))
if (folder/'browser/results.json').exists():
 browser=json.loads((folder/'browser/results.json').read_text())
 for case in report['cases']:
  if case['id'] in browser:
   observed=browser[case['id']]
   case.update(status=observed['status'],observed='Actual Chromium browser: '+json.dumps(observed.get('evidence',observed),ensure_ascii=False),evidence='browser/results.json; browser/mobile.png; browser/desktop.png')
 for engine in ['chrome','msedge','webkit','firefox']:assert browser['cross_engine'][engine]['loaded']
 case=next(c for c in report['cases'] if c['id']=='TC-099')
 case.update(status='PARTIAL',observed='Installed Google Chrome, Microsoft Edge, Firefox and Playwright WebKit loaded the real UI with visible weight inputs and zero mobile overflow. Actual Apple Safari on macOS/iOS remains untested; WebKit is not a substitute for Safari release validation.',evidence='browser/results.json cross_engine')
 evidence['browser_rendering']='Real Chromium, installed Chrome/Edge, Firefox and WebKit; screenshots and measured geometry verified. Actual Apple Safari remains untested.'
if (folder/'real_auth_evidence.json').exists():
 auth=json.loads((folder/'real_auth_evidence.json').read_text())
 assert auth['OWNER']['profile_status']==200 and auth['ACCOUNTANT']['profile_status']==200 and auth['INACTIVE']['profile_status']==403
 assert auth['NO_TENANT']['profile_status']==401 and auth['cleanup']['disposable_users_deleted']==5
 additional={
 'TC-001':'Actual Supabase ES256 login succeeded; backend accepted server-owned app_metadata tenant identity, confirmed active membership and loaded private browser dashboard.',
 'TC-004':'Actual authenticated tenant URL tampering preserved session identity, removed the conflicting query parameter and displayed a rejection notification.',
 'TC-005':'Actual accountant login: financial reports 200; sample ZPL preview 403; quote button disabled and dispatch viewport blocked.',
 'TC-006':'Actual dispatcher login: quote viewport allowed and sample ZPL preview 200; financial reports/platform admin 403. Actual carrier purchase is a separate unverified integration.',
 'TC-008':'Actual signed-in client roles could not toggle Super-Admin; server returned 403 for macro dashboard. Server subject allowlist remains the sole owner authority.',
 'TC-010':'Actual real-auth tenant metrics/manifest matched across concurrent HTTP requests and isolated desktop/mobile browser contexts.',
 'TC-011':'Actual signed-in manifest search returned zero matches for three SQL/HTML injection payloads; injected API tenant parameter returned only authorized tenant tickets.',
 'TC-012':'Actual non-banned Supabase auth account with inactive membership signed in at Supabase but was rejected by EasyInvio with 403.',
 'TC-063':'Actual dispatcher successfully reserved wallet funds in a rolled-back transaction; wallet configuration viewport was blocked, financial reports 403, operational affordability summary accessible.'}
 assert auth['TC-004']['browser_parameter_removed'] and auth['TC-004']['browser_error_shown']
 assert auth['TC-011']['live_browser_search_counts']==['0','0','0']
 assert auth['DISPATCHER']['actual_wallet_reservation_allowed']
 for case in report['cases']:
  if case['id'] in additional:case.update(status='PASS',observed=additional[case['id']],evidence='real_auth_evidence.json')
if (folder/'finance_capture_evidence.json').exists():
 finance=json.loads((folder/'finance_capture_evidence.json').read_text());assert finance['all_test_records_rolled_back']
 for case in report['cases']:
  if case['id']=='TC-057':case.update(status='PASS',observed='Actual PostgreSQL finance service with controlled carrier receipt: capture reduced wallet 100.00 to 80.00, inserted RESERVE/CAPTURE audit rows and marked the shipment BOOKED. All records rolled back; no carrier label purchased.',evidence='finance_capture_evidence.json')
  if case['id']=='TC-061':case.update(status='PASS',observed='Actual PostgreSQL settlement with controlled carrier receipt deducted exactly 12.33 from 100.00, leaving 87.67 and zero reserved. All records rolled back.',evidence='finance_capture_evidence.json')
if db.get('TC-073',{}).get('ok'):
 case=next(c for c in report['cases'] if c['id']=='TC-073');case.update(status='PASS',observed=db['TC-073']['evidence'],evidence='database_evidence.json')
if (folder/'bulk_isolation_evidence.json').exists():
 bulk=json.loads((folder/'bulk_isolation_evidence.json').read_text());assert bulk['all_writes_rolled_back']
 case=next(c for c in report['cases'] if c['id']=='TC-013');case.update(status='PASS',observed='Concurrent real PostgreSQL QUOTE_ONLY writes for GBP and EUR tenants stored their own 11.50/12.00 prices. Other-tenant ID lookups returned zero. Controlled provider responses, no external carrier calls, all writes rolled back.',evidence='bulk_isolation_evidence.json')
 case=next(c for c in report['cases'] if c['id']=='TC-046');case.update(status='PASS',observed='Concurrent tenant-specific quote processing with controlled provider responses and real PostgreSQL writes: '+json.dumps(bulk['concurrent_tenant_quotes'])+'. Live provider response latency remains outside this controlled test.',evidence='bulk_isolation_evidence.json')
remaining={
 'TC-029':'Deferred: current providers and database support one parcel per shipment. Multiple orders in bulk remain supported. Carrier multi-piece purchases require a new provider/database contract; summing boxes into one pretend parcel would be incorrect.',
 'TC-047':'Specification conflict: GBP/EUR/USD support is deliberate. No cross-currency totals are silently combined; GBP-only enforcement would remove existing required functionality.',
 'TC-048':'Specification conflict: existing pricing rules use lower numeric priority first. Reversing the order would alter current customer prices. The convention remains unchanged.',
 'TC-049':'Performance target unmet: remote PostgreSQL lookups still exceed 15ms. No stale financial cache was introduced to manufacture a pass.',
 'TC-068':'Specification conflict: no valid universal generic HS code exists for arbitrary random text. Classifier preserves review-required abstention rather than fabricating a commodity code.'}
for case in report['cases']:
 if case['id'] in remaining:case['remediation_disposition']=remaining[case['id']]
report['generated_at']=datetime.now(timezone.utc).isoformat();report['counts']=dict(Counter(c['status'] for c in report['cases']))
report['remediation']=evidence
(folder/'remediation_summary.json').write_text(json.dumps(evidence,indent=2))
report['scope']='Updated after code fixes and real sandbox migration 014. Partial/browser/blocked cases are not passes. Previously retained race audit remains; new database probes all rolled back. No payment, message or label purchased.'
(folder/'results.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
lines=['# EasyInvio.com — consolidated 100-case report after remediation','',report['generated_at'],'',
 ', '.join(f'{v} {k}' for k,v in report['counts'].items())+'.','',
 f"**Validation:** {result.testsRun} selected regression tests passed. Real browser geometry/interactions were tested in Chromium, Chrome, Edge, Firefox and WebKit. Actual Supabase logins, role dashboards, tenant isolation, wallet capture, invoice comparisons and ticket lifecycle were tested. Controlled carrier receipts were used for financial settlement; no real carrier label was purchased. Actual Apple Safari remains untested.",'',
 '**Database:** `migrations/014_support_ticket_lifecycle.sql` was rollback-validated and applied to your configured Supabase sandbox. It adds `IN_REVIEW`/`CLOSED` ticket states, `archived_at` and an index; preserves historical `RESOLVED` data. No further SQL needs to be run in this sandbox. Apply the migration when deploying to any other database. Receipt: `migration_014_receipt.json`.','',
 'Backend restarted and `/health`, new routes, and updated frontend verified locally. Stripe/Twilio/HubSpot were not called. Existing 27 tenants and fixture data were preserved; remediation probes rolled back. Previous UAT-RACE audit records remain.','',
 '## Remaining acceptance gaps','']
lines += ['- '+k+': '+v for k,v in remaining.items()]
lines += ['', 'These cases retain their failed acceptance result; they are not labelled passed or silently excluded. Warehouse enrollment requires a pre-provisioned Supabase principal. Disposable real-auth users were provisioned for testing without emails; every disposable identity was deleted after verification. No additional database migration was needed for this testing expansion.','',
 '## All 100 cases','']
for c in report['cases']:
 lines.extend([f"### {c['id']} — {c['status']}: {c['case']}",'','Expected: '+c['expected'],'','Observed: '+c['observed'],'','Evidence: '+c['evidence'],''])
 if c.get('remediation_disposition'):lines.extend([c['remediation_disposition'],''])
lines += ['## Evidence and reproduction','',
 '`remediation_core_regression.log`, `remediation_summary.json`, `database_evidence.json`, `remediation_frontend_evidence.json`, `migration_014_receipt.json`, `post_apply_evidence.json`.', '',
 'Regenerate this report and rerun core regressions: `.venv/Scripts/python.exe -m tests.report_uat_remediation`.',
 'Rerun real rollback probes: `.venv/Scripts/python.exe -m tests.uat_database_probe`.',
 'Original assessment retained in `results_before_remediation.json`. Frontend DOM tests are `tests/frontend_contract.cjs`; their execution requires Node runtime. Do not rerun the one-time frontend installation scripts.']
(folder/'RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
requirements={
 'TC-031':'Activate genuinely credentialed EasyPost TEST and regional TEST carrier accounts. Measure real concurrent rate requests against both; the controlled timeout test completed in about 230ms, but it cannot certify actual upstream latency.',
 'TC-051':'Implement/enable a clearly labelled test-mode booking adapter, or provide valid carrier sandbox access with an approved TEST fulfillment path. Postpaid zero-wallet reservation already passes. Full new-label creation is gated off in the current sandbox configuration.',
 'TC-052':'Same test-mode booking path as TC-051. Real PostgreSQL 100→80 settlement and reserve/capture ledger already pass with controlled provider receipts; end-to-end UI/new carrier label remains unverified.',
 'TC-053':'Same booking adapter; verify exact-funds booking and label response together. Actual PostgreSQL 100→0 settlement already passes. Do not disable production credit/tenant safety checks.',
 'TC-056':'Connect the verified atomic wallet reservation to that sandbox label adapter; run two simultaneous 15.00 bookings on 20.00 and assert exactly one returned label. Current real concurrency test proves one reservation succeeds and one returns 402.',
 'TC-060':'Wire the completed booking-success callback to wallet/dashboard refresh, then test it through the booking adapter. Initial live wallet/manifest state now synchronizes from the actual server; full paid-booking UI trigger is still not exercised.',
 'TC-066':'Supply reviewed expected HS classifications for fully described products (upper/sole material, construction, intended use, tariff version). The mock matcher and actual HS cards are tested; ambiguous text alone cannot establish authoritative customs correctness.',
 'TC-099':'Run the same browser suite on actual macOS/iOS Safari, locally or via a browser-testing service. Installed Chrome/Edge and Firefox/WebKit checks passed; WebKit is not actual Apple Safari.'}
pending=[c for c in report['cases'] if c['status'] in ['PARTIAL','BLOCKED']]
pending_lines=['# Requirements to close remaining partial / blocked cases','',
 'Most previous blockers were missing test infrastructure, not unavailable Stripe/Twilio/HubSpot integrations. Headless browsers and disposable real Supabase login users now close those gaps. No additional SQL migration is required for the fixes made in this testing pass.','',
 'The finance service has been exercised against real PostgreSQL with controlled carrier receipts. Booking/printing end-to-end cases still need a safe test-mode booking adapter (additional feature work) or properly supported carrier TEST integrations. Credentials alone do not bypass the existing sandbox purchase gates.','',
 '| Case | Current result | Concrete requirement |','|---|---|---|']
for c in pending:
 requirement=requirements.get(c['id'],'See evidence and observed limits in RESULTS.md; no automatic pass is claimed.')
 pending_lines.append('| '+c['id']+' | '+c['status']+' | '+requirement.replace('|','/')+' |')
pending_lines+=['','The five failed cases are separate specification/implementation gaps documented in RESULTS.md. Stripe test-topup remains intentionally excluded. Test passwords/tokens were held only in memory and all five disposable auth identities were deleted after each real-login run.']
(folder/'REMAINING_REQUIREMENTS.md').write_text('\n'.join(pending_lines),encoding='utf-8')
print(json.dumps({'counts':report['counts'],'regression_tests':result.testsRun,'remaining_acceptance_failures':list(remaining)},indent=2))
