"""Real Supabase login/role probes with disposable users and no outgoing emails."""
import asyncio,json,secrets,os
from types import SimpleNamespace
from pathlib import Path
from uuid import UUID
import httpx,asyncpg,jwt
from main import Settings,FinanceEngine
from backend.verify_automation_writepath import BorrowedPool
from backend.database_tls import database_tls_context
from playwright.async_api import async_playwright
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())

async def run():
 s=Settings();assert s.database_environment=='SANDBOX'
 c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=database_tls_context(s.database_ca_file,strict=s.database_tls_strict))
 created=[];results={};sessions={}
 admin={'apikey':s.supabase_service_role_key.get_secret_value(),'Authorization':'Bearer '+s.supabase_service_role_key.get_secret_value()}
 public={'apikey':s.supabase_publishable_key.get_secret_value()}
 async with httpx.AsyncClient(timeout=30) as http:
  try:
   tid=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
   for role in ['OWNER','ACCOUNTANT','DISPATCHER','INACTIVE','NO_TENANT']:
    email='uat-'+secrets.token_hex(10)+'@example.invalid';password=secrets.token_urlsafe(40)
    response=await http.post(f'{s.supabase_url}/auth/v1/admin/users',headers=admin,json={'email':email,'password':password,'email_confirm':True,'app_metadata':{} if role=='NO_TENANT' else {'tenant_id':str(tid)},'user_metadata':{'tenant_id':str(tid)} if role=='NO_TENANT' else {}})
    assert response.status_code in [200,201],f'Auth provisioning failed HTTP {response.status_code}'
    user=response.json();uid=UUID(user.get('id') or user['user']['id']);created.append(uid)
    await c.execute("INSERT INTO public.users(tenant_id,auth_user_id,role,full_name,is_active) VALUES($1,$2,$3,$4,$5)",tid,uid,'DISPATCHER' if role in ['INACTIVE','NO_TENANT'] else role,'Disposable UAT '+role,role!='INACTIVE')
    login=await http.post(f'{s.supabase_url}/auth/v1/token?grant_type=password',headers=public,json={'email':email,'password':password})
    assert login.status_code==200,f'Supabase password login HTTP {login.status_code}'
    token=login.json()['access_token'];sessions[role]=login.json()
    headers={'Authorization':'Bearer '+token}
    profile=await http.get('http://127.0.0.1:8000/api/v1/profile',headers=headers)
    claims=jwt.decode(token,options={'verify_signature':False})
    results[role]={'supabase_login':login.status_code,'profile_status':profile.status_code,'algorithm':jwt.get_unverified_header(token)['alg'],'has_top_level_tenant':bool(claims.get('tenant_id')),'has_server_app_metadata_tenant':bool(claims.get('app_metadata',{}).get('tenant_id'))}
    if profile.status_code==200:
     results[role]['profile_tenant_matches']=profile.json().get('tenant_id')==str(tid)
     report=await http.get('http://127.0.0.1:8000/api/v1/analytics/reports?start_date=2026-09-01&end_date=2026-10-31',headers=headers)
     results[role]['financial_reports_status']=report.status_code
     macro=await http.get('http://127.0.0.1:8000/api/v1/admin/analytics/dashboard?start_date=2026-09-01&end_date=2026-10-31',headers=headers)
     results[role]['platform_admin_status']=macro.status_code
     label_ship=await c.fetchval("SELECT id FROM public.shipments WHERE tenant_id=$1 AND customer_reference='SEED24-1-5'",tid)
     preview=await http.get(f'http://127.0.0.1:8000/api/v1/shipments/{label_ship}/label/preview',headers=headers)
     results[role]['sample_label_status']=preview.status_code
     if role=='DISPATCHER':
      transaction=c.transaction();await transaction.start()
      try:
       quoted=await c.fetchval("SELECT id FROM public.shipments WHERE tenant_id=$1 AND customer_reference='SEED24-1-2'",tid)
       await FinanceEngine(BorrowedPool(c),s,None).reserve(SimpleNamespace(tenant_id=tid,user_id=uid,role='DISPATCHER'),quoted)
       results[role]['actual_wallet_reservation_allowed']=True
      finally:await transaction.rollback()
     if role=='OWNER':
      a,b=await asyncio.gather(*(http.get('http://127.0.0.1:8000/api/v1/shipments/manifest',headers=headers) for _ in range(2)))
      results['TC-010']={'independent_concurrent_requests':a.status_code==b.status_code==200 and a.json()==b.json(),'scope':'Two concurrent real authenticated requests; browser contexts checked separately'}
      tamper=await http.get('http://127.0.0.1:8000/api/v1/profile?tenant_id=00000000-0000-0000-0000-000000000000',headers=headers)
      results['TC-004']={'session_identity_preserved':tamper.status_code==200 and tamper.json()['tenant_id']==str(tid)}
      injection=await http.get("http://127.0.0.1:8000/api/v1/support/tickets?tenant_id=' OR 1=1 --",headers=headers)
      results['TC-011']={'status':injection.status_code,'all_tickets_own_tenant':injection.status_code==200 and all(x['tenant_id']==str(tid) for x in injection.json()['tickets']),'scope':'Ignored injected tenant query parameter; authenticated identity remains authoritative'}
   async with async_playwright() as pw:
    browser=await pw.chromium.launch()
    for role in ['OWNER','ACCOUNTANT','DISPATCHER']:
     context=await browser.new_context(viewport={'width':1440,'height':1000});page=await context.new_page()
     await page.goto('http://127.0.0.1:8000',wait_until='networkidle')
     await page.evaluate('(session)=>{state.session=session;armSessionExpiry();renderAccount()}',sessions[role])
     await page.wait_for_function('portal.profile!==null && portal.report!==null',timeout=15000)
     results[role]['real_browser_dashboard_loaded']=True
     results[role]['super_admin_toggle_disabled']=await page.locator('#role-admin').is_disabled()
     if role=='ACCOUNTANT':
      results[role]['quote_button_disabled']=await page.locator('#quote-btn').is_disabled()
      await page.evaluate("setView('dispatch')")
      results[role]['quote_view_blocked']=not await page.locator('#dispatch').is_visible()
     if role=='DISPATCHER':
      await page.evaluate("setView('wallet')")
      results[role]['wallet_view_blocked']=not await page.locator('#wallet').is_visible()
      await page.evaluate("setView('dispatch')")
      results[role]['quote_view_allowed']=await page.locator('#dispatch').is_visible()
     if role=='OWNER':
      other=await browser.new_context(viewport={'width':375,'height':812});second=await other.new_page()
      await second.goto('http://127.0.0.1:8000',wait_until='networkidle');await second.evaluate('(session)=>{state.session=session;renderAccount()}',sessions[role])
      await second.wait_for_function('portal.report!==null',timeout=15000)
      results['TC-010']['two_browser_contexts_same_tenant']=await page.evaluate('portal.profile.tenant_id')==await second.evaluate('portal.profile.tenant_id')==str(tid)
      await page.evaluate("async()=>{history.replaceState(null,'','?tenant_id=00000000-0000-0000-0000-000000000000');await refreshPortal()}")
      results['TC-004']['browser_parameter_removed']=await page.evaluate("!new URL(location.href).searchParams.has('tenant_id')")
      results['TC-004']['browser_error_shown']='Tenant parameter rejected' in await page.locator('#toast').inner_text()
      await page.evaluate("setView('manifest')")
      await page.locator('#manifest-refresh').click()
      await page.wait_for_function('state.manifest.length>0')
      injection_results=[]
      for payload in ["' OR 1=1 --","'; DROP TABLE shipments; --",'<img src=x onerror=alert(1)>']:
       await page.locator('#manifest-search').fill(payload)
       injection_results.append(await page.locator('#manifest-count').inner_text())
      results['TC-011']['live_browser_search_counts']=injection_results
      assert injection_results==['0','0','0']
      await other.close()
     await context.close()
    await browser.close()
   results['cleanup']={'disposable_auth_users_created':len(created),'emails_sent':0,'passwords_or_tokens_saved':False}
  finally:
   for uid in created:
    await c.execute('DELETE FROM public.users WHERE auth_user_id=$1',uid)
    removed=await http.delete(f'{s.supabase_url}/auth/v1/admin/users/{uid}',headers=admin)
    assert removed.status_code in [200,204],f'Auth cleanup HTTP {removed.status_code}'
   await c.close()
 results['cleanup']['disposable_users_deleted']=len(created)
 Path('docs/uat_100/real_auth_evidence.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':asyncio.run(run())
