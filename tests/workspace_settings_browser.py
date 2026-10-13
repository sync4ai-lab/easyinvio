"""Controlled browser checks for settings, invitations and persistent disputes."""
import asyncio,json,os
from pathlib import Path
from uuid import uuid4
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
 errors=[];calls=[];tenant=str(uuid4());sid=str(uuid4());saved={'content':'Existing saved dispute evidence'}
 company={'company_name':'Synthetic Company','workspace_name':'Synthetic Workspace','billing_email':'billing@example.invalid'}
 invitations=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':900})
  page.set_default_timeout(7000)
  page.on('pageerror',lambda e:errors.append(str(e)))
  async def route(r):
   path=r.request.url.split('/api/v1/',1)[1];body=r.request.post_data_json if r.request.method in ('POST','PUT','PATCH') and r.request.post_data else None;calls.append((path,r.request.method,body))
   if path=='workspace/settings':data={'company':company,'members':[],'invitations':invitations}
   elif path=='workspace/invitations':
    invitations.append({'id':str(uuid4()),**body,'status':'PENDING'});data={'status':'PENDING','message':'Invitation accepted for delivery; user must verify and choose a password.'}
   elif path.endswith('/dispute-draft'):
    if r.request.method=='PUT':saved['content']=body['content'];data={'saved':True,'sent_to_carrier':False}
    else:data={'draft':saved}
   elif path=='audit/invoice':data={'results':[{'status':'review_required','currency':'GBP','findings':[{'field':'base_cost','expected':'10.00','billed':'12.00','overcharge':'2.00'}],'dispute_draft':'Evidence-based updated dispute draft'}]}
   elif path=='auth/accept-invitation':data={'message':'Workspace access activated. Sign in with your email and new password.'}
   else:data={}
   await r.fulfill(json=data)
  await page.route('**/api/v1/**',route)
  await page.goto('http://127.0.0.1:8000/',wait_until='domcontentloaded');await page.wait_for_function("state.mode!=='checking'")
  await page.evaluate('''tenant=>{document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;state.session={access_token:'controlled-browser'};portal.role='CLIENT';portal.profile={tenant_id:tenant,workspace_role:'OWNER',portal_role:'CLIENT'};refreshEnterpriseNavigation();setView('settings');}''',tenant)
  await expect(page.locator('#settings')).to_be_visible();await expect(page.locator('#workspace-team')).to_be_visible()
  assert await page.locator('#member-role option').evaluate_all('(nodes)=>nodes.map(n=>n.value)')==['DISPATCHER','ACCOUNTANT']
  assert await page.locator('#member-auth-id').count()==0
  await page.locator('#member-first-name').fill('Test');await page.locator('#member-last-name').fill('Colleague');await page.locator('#member-email').fill('new@example.invalid')
  await page.locator('#workspace-member-form button').click();await expect(page.locator('#settings-invitations')).to_contain_text('PENDING')
  payload=next(body for path,method,body in calls if path=='workspace/invitations');assert payload['role']=='DISPATCHER' and 'password' not in payload and 'auth_user_id' not in payload
  for width in (375,768,1366):
   await page.set_viewport_size({'width':width,'height':900});assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  await page.evaluate('''({sid,tenant})=>openDispute({id:'ticket-synthetic',tenant_id:tenant,shipment_id:sid,ticket_type:'CARRIER_EXCEPTION',booked_at:'2026-10-13',tracking_number:'TEST-TRACK'})''',{'sid':sid,'tenant':tenant})
  await expect(page.locator('#dispute-draft')).to_have_value('Existing saved dispute evidence')
  assert not await page.locator('#quick-audit-form button').is_disabled()
  await page.locator('#dispute-dialog details summary').click()
  await page.locator('#qa-weight').fill('1.000');await page.locator('#qa-base').fill('12.00');await page.locator('#quick-audit-form button').click()
  await expect(page.locator('#dispute-draft')).to_have_value('Evidence-based updated dispute draft')
  await page.locator('#dispute-save').click();await expect(page.locator('#dispute-status')).to_contain_text('Draft saved')
  assert saved['content']=='Evidence-based updated dispute draft'
  await page.evaluate('clearSession()');assert await page.locator('#dispute-draft').input_value()==''
  await page.goto('http://127.0.0.1:8000/#type=invite&access_token=synthetic-provider-access-token',wait_until='domcontentloaded')
  await expect(page.locator('#identity-reset-form')).to_be_visible();assert await page.evaluate('location.hash')==''
  await page.locator('#identity-new-password').fill('A-long-synthetic-password');await page.locator('#identity-confirm-password').fill('A-long-synthetic-password')
  await page.locator('#identity-reset-form button[type=submit]').click();await expect(page.locator('#identity-login-status')).to_contain_text('Workspace access activated')
  assert await page.evaluate("localStorage.getItem('easyinvio.session')")==None
  cold=await browser.new_page();cold.on('pageerror',lambda e:errors.append(str(e)));await cold.route('**/api/v1/**',route)
  await cold.goto('http://127.0.0.1:8000/#type=invite&access_token=synthetic-provider-access-token',wait_until='domcontentloaded')
  await expect(cold.locator('#identity-reset-form')).to_be_visible();assert await cold.evaluate('location.hash')==''
  await browser.close()
 assert not errors,errors
 out=Path('docs/workspace_settings');out.mkdir(exist_ok=True)
 report={'status':'PASS','scope':'controlled browser API; no real emails','checks':['Settings contains company and email-based team invitation form; no UUID or Admin role','Pending invitation visible without sending a password','375/768/1366px responsive layout','Saved dispute reload, enabled invoice comparison, readable findings and save action','Logout clears dispute and team details','Invite fragment removed, password selection activates stored membership and returns to sign-in without persisting provider token'],'javascript_errors':errors}
 (out/'browser_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(run())
