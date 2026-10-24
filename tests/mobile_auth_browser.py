"""Isolated authentication/mobile acceptance. No real credentials or provider calls."""
import asyncio,json,os,socket,threading,time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import uvicorn
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright,expect
from scripts.build_vercel import ASSETS
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/mobile-auth-qa'
async def run(origin):
 OUT.mkdir(parents=True,exist_ok=True)
 results=[];errors=[];calls=[];uid=str(uuid4());tenant=str(uuid4());role='OWNER';reject=False
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(headless=True)
  page=await browser.new_page(viewport={'width':393,'height':852})
  page.on('pageerror',lambda err:errors.append(str(err)))
  await page.add_init_script("window.shellFlashed=false;new MutationObserver(()=>{const shell=document.querySelector('.app-shell');if(shell&&!document.querySelector('#loginContainer')&&getComputedStyle(shell).display!=='none')window.shellFlashed=true;}).observe(document,{childList:true,subtree:true});")
  async def mock(route):
   req=route.request;path=urlsplit(req.url).path;calls.append(path)
   identity={'user_id':uid,'email':'tester@example.invalid','role':role,'full_name':'UAT Tester','phone_e164':None}
   profile={'portal_role':role if role in ('SUPER_ADMIN','AGENT') else 'CLIENT','user_id':uid,'tenant_id':None if role in ('SUPER_ADMIN','AGENT') else tenant}
   if profile['tenant_id']:profile.update(workspace_role=role,company_name='Synthetic test company',workspace_type='BUSINESS')
   report={'totals_by_currency':[],'total_package_count':0,'active_tenants':1,'carriers':[],'lanes':[],'series':[],'statuses':[],'billing_pipeline':[],'payment_pipeline':[],'active_support':[],'cohorts':{'shipping':[],'tickets':[],'accounts':[]}}
   if path=='/api/v1/config':data={'mode':'configured','supabase_url':None,'publishable_key':None,'uk_address_lookup_available':True}
   elif path=='/api/v1/auth/token':
    await asyncio.sleep(.15)
    if reject:return await route.fulfill(status=401,json={'detail':'Invalid email or password'})
    data={'access_token':'synthetic-'+role,'expires_at':int(time.time())+900,'absolute_expires_at':int(time.time())+3600,'user':{'id':uid,'email':identity['email']},'bootstrap':{'identity':identity,'profile':profile}}
   elif path=='/api/v1/auth/me':data=identity
   elif path=='/api/v1/profile':data=profile
   elif path=='/api/v1/auth/forgot-password':data={'message':'If this email is registered, a password reset link will arrive shortly. Check your spam folder.'}
   elif '/analytics/' in path:
    await asyncio.sleep(.6);data=report
   elif path=='/api/v1/wallet':data={'balance':'0.00','reserved_balance':'0.00','available':'0.00','currency':'GBP','history':[]}
   elif path=='/api/v1/dispatch-workspace/orders':data={'orders':[{'id':str(uuid4()),'customer_reference':'ORDER-WITH-A-LONG-REFERENCE-001','display_name':'Synthetic marketplace','cargo_type':'PARCEL','status':'PENDING_IMPORT','tracking_sync_status':'Not queued'}],'stores':[],'more_available':False}
   elif path=='/api/v1/workspace/settings':data={'company':{'company_name':'Synthetic test company','workspace_name':'Synthetic test company','billing_email':'test@example.invalid'},'members':[],'invitations':[]}
   elif '/catalog/' in path:data={'items':[],'total':0,'has_more':False}
   elif path=='/api/v1/dispatch/summary':data={'package_count':0,'order_count':0,'return_count':0,'status_counts':{}}
   else:data={**report,'shipments':[],'stores':[],'tickets':[],'tenants':[],'connections':[],'rules':[],'transactions':[],'items':[],'events':[],'orders':[],'notifications':[],'has_more':False,'company':{},'preferences':{'in_app_enabled':True,'categories':[],'stale_hours':48,'poll_interval_minutes':360},'capabilities':{},'providers':[],'alerts':[]}
   await route.fulfill(json=data)
  await page.route('**/api/**',mock);await page.route('**/health',lambda route:route.fulfill(json={'status':'ok','mode':'configured'}))
  await page.route('https://**',lambda route:route.abort())
  await page.goto(origin,wait_until='domcontentloaded');await expect(page.locator('#identity-login-form')).to_be_visible()
  assert not await page.evaluate('window.shellFlashed'),'Signed-out app shell flashed'
  await expect(page.locator('[data-password-for="identity-password"]')).to_be_visible()
  await page.locator('#identity-password').fill('synthetic-long-password')
  await page.locator('[data-password-for="identity-password"]').click();assert await page.locator('#identity-password').get_attribute('type')=='text'
  await page.locator('[data-password-for="identity-password"]').click();assert await page.locator('#identity-password').get_attribute('type')=='password'
  await page.locator('#identity-login-form').evaluate('f=>f.reset()')
  before=await page.locator('#identity-email').bounding_box();await page.locator('#identity-login-submit').click()
  after=await page.locator('#identity-email').bounding_box();assert abs(before['width']-after['width'])<1
  assert await page.locator('.identity-input .form-field-error').count()==0
  await page.screenshot(path=str(OUT/'validation-mobile.png'))
  await page.locator('#identity-login-form').evaluate('f=>f.reset()');reject=True
  await page.locator('#identity-email').fill('tester@example.invalid');await page.locator('#identity-password').fill('wrong-password')
  await page.locator('#identity-login-submit').click();await expect(page.locator('#identity-login-status')).to_have_text('Invalid email or password')
  after=await page.locator('#identity-email').bounding_box();assert abs(before['width']-after['width'])<1
  reject=False
  await page.locator('#identity-forgot').click();await page.locator('#identity-recovery-email').fill('tester@example.invalid');await page.locator('#identity-recovery-form [type=submit]').click()
  await expect(page.locator('#identity-recovery-notice')).to_be_visible();await page.locator('#identity-recovery-notice button').click()
  await expect(page.locator('#identity-login-form')).to_be_visible();await expect(page.locator('#identity-email')).to_have_value('')
  await page.locator('#identity-forgot').click();await page.locator('#identity-recovery-email').fill('tester@example.invalid');await page.locator('#identity-recovery-form [type=submit]').click()
  await expect(page.locator('#identity-recovery-notice')).to_be_visible();await expect(page.locator('#identity-login-form')).to_be_visible(timeout=6500)
  await page.evaluate("identityRecoveryView('reset')")
  for identifier in ['identity-new-password','identity-confirm-password']:
   await expect(page.locator('[data-password-for="'+identifier+'"]').first).to_be_visible()
  await page.evaluate("identityRecoveryView('login')")
  calls.clear();await page.locator('#identity-email').fill('tester@example.invalid');await page.locator('#identity-password').fill('synthetic-password')
  start=time.monotonic();await page.locator('#identity-login-submit').click();await expect(page.locator('.app-shell')).to_be_visible();elapsed=time.monotonic()-start
  assert calls.count('/api/v1/auth/token')==1 and '/api/v1/profile' not in calls and '/api/v1/auth/me' not in calls,calls
  assert elapsed<2,elapsed
  results.append({'login_shell_seconds_with_150ms_mock_auth':round(elapsed,3),'profile_requests_during_login':0})
  await page.evaluate("setView('dispatch')")
  await page.evaluate("""()=>{for(const prefix of ['origin','destination']){document.querySelector('#'+prefix+'-reuse-contact').click();}document.querySelector('#origin-contact-summary').textContent='10 Test Street\\nLondon\\nSW1A 1AA\\nGB';document.querySelector('#destination-contact-summary').textContent='Flat 2\\nLong Business Name\\n20 Other Street\\nLeeds\\nYorkshire\\nLS1 1AA\\nGB';}""")
  await page.wait_for_timeout(150)
  alignment=await page.evaluate("['company','line2','state','phone','email'].map(field=>({field,left:document.querySelector('#origin-'+field).getBoundingClientRect().top,right:document.querySelector('#destination-'+field).getBoundingClientRect().top}))")
  assert all(abs(row['left']-row['right'])<2 for row in alignment),alignment
  await page.locator('#address-fields').screenshot(path=str(OUT/'contacts-mobile.png'))
  await page.evaluate("document.getElementById('toast').hidden=true")
  for width in [320,393,768,1440]:
   await page.set_viewport_size({'width':width,'height':900})
   views=await page.evaluate('allowedEnterpriseViews()')
   for view in views:
    await page.evaluate('(view)=>setView(view)',view);await page.wait_for_timeout(80)
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(width,view,'page overflow')
    title=page.locator('#'+view+' > .pagehead h1')
    if await title.count() and await title.is_visible():
     bounds=await title.bounding_box();assert bounds and bounds['width']>180,(width,view,bounds)
    if view=='workspace':assert await page.locator('#workspace .scrolltable th').first.evaluate('e=>getComputedStyle(e).whiteSpace')=='nowrap'
    await page.evaluate('scrollTo(0,0)');await page.mouse.move(0,0)
    if width==393:await page.screenshot(path=str(OUT/(view+'-mobile.png')))
   results.append({'width':width,'views':views,'overflow':False})
  for persona in ['DISPATCHER','ACCOUNTANT','SUPER_ADMIN','AGENT']:
   role=persona
   await page.evaluate('clearSession()')
   await page.locator('#identity-email').fill('tester@example.invalid');await page.locator('#identity-password').fill('synthetic-password')
   await page.locator('#identity-login-submit').click();await expect(page.locator('.app-shell')).to_be_visible()
   for width in [393,1440]:
    await page.set_viewport_size({'width':width,'height':900})
    views=await page.evaluate('allowedEnterpriseViews()')
    for view in views:
     await page.evaluate('(view)=>setView(view)',view);await page.wait_for_timeout(100)
     assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(persona,width,view,'page overflow')
     title=page.locator('#'+view+' > .pagehead h1')
     if await title.count() and await title.is_visible():
      bounds=await title.bounding_box();assert bounds and bounds['width']>180,(persona,width,view,bounds)
    if width==393:
     assert await page.locator('.mobile-nav>button[data-enterprise-view]').first.evaluate('e=>e.getBoundingClientRect().width')>=86
    results.append({'persona':persona,'width':width,'views':views,'overflow':False})
  assert not errors,errors
  await browser.close()
 print(json.dumps({'status':'PASS','results':results,'page_errors':errors,'provider_calls':0},indent=2))
if __name__=='__main__':
 app=FastAPI()
 @app.get('/')
 async def home():return FileResponse(ROOT/'index.html')
 @app.get('/{asset}')
 async def asset(asset:str):
  if asset not in ASSETS:raise HTTPException(404)
  return FileResponse(ROOT/asset)
 listener=socket.socket();listener.bind(('127.0.0.1',0));origin='http://127.0.0.1:'+str(listener.getsockname()[1])
 server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False));thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
 try:
  deadline=time.monotonic()+15
  while not server.started:
   if time.monotonic()>deadline:raise RuntimeError('Isolated UI server did not start')
   time.sleep(.05)
  asyncio.run(run(origin))
 finally:server.should_exit=True;thread.join(timeout=10);listener.close()
