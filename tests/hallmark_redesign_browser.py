"""Offline visual/navigation acceptance for the shared EasyInvio redesign.

Start scripts/dev.py --preview --port 8012 first, then run this script.
All APIs are intercepted; external hosts are blocked. No DB, paid quotes or purchases.
Uses installed Microsoft Edge. Screenshots contain synthetic data only.
"""
import asyncio, json, time, sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/hallmark-qa';OUT.mkdir(parents=True,exist_ok=True)
async def run():
 errors=[];requests=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  context=await browser.new_context(viewport={'width':1440,'height':900})
  async def handler(route):
   path=urlsplit(route.request.url).path
   if urlsplit(route.request.url).hostname!='127.0.0.1':return await route.abort()
   if not (path.startswith('/api/') or path=='/health'):return await route.continue_()
   requests.append(path)
   identity={'user_id':'00000000-0000-4000-8000-000000000001','email':'tester@example.invalid','role':'OWNER','full_name':'Local Design Review','phone_e164':None}
   profile={'portal_role':'CLIENT','workspace_role':'OWNER','tenant_id':'00000000-0000-4000-8000-000000000002','company_name':'Local Design Review','workspace_type':'BUSINESS','user_id':identity['user_id']}
   report={'totals_by_currency':[],'total_package_count':0,'start_date':'2026-11-01','end_date':'2026-11-23','active_tenants':1,'carriers':[],'lanes':[],'series':[],'statuses':[],'billing_pipeline':[],'payment_pipeline':[],'active_support':[],'cohorts':{'shipping':[],'tickets':[],'accounts':[]}}
   if path=='/health':data={'status':'ok','mode':'configured'}
   elif path=='/api/v1/config':data={'mode':'configured','supabase_url':None,'publishable_key':None}
   elif path=='/api/v1/public/session':data={'authenticated':False}
   elif path=='/api/v1/auth/browser-session/restore':return await route.fulfill(status=401,json={})
   elif path=='/api/v1/auth/token':data={'access_token':'synthetic-local-design','expires_at':int(time.time())+900,'absolute_expires_at':int(time.time())+3600,'user':{'id':identity['user_id'],'email':identity['email']},'bootstrap':{'identity':identity,'profile':profile}}
   elif path=='/api/v1/auth/me':data=identity
   elif path=='/api/v1/profile':data=profile
   elif '/analytics/' in path:data=report
   elif path=='/api/v1/workspace/settings':data={'company':{'company_name':'Local Design Review','billing_email':identity['email']},'members':[],'invitations':[]}
   elif path=='/api/v1/wallet':data={'balance':'0.00','reserved_balance':'0.00','available':'0.00','currency':'GBP','history':[]}
   else:data={**report,'shipments':[],'stores':[],'tickets':[],'tenants':[],'connections':[],'rules':[],'transactions':[],'items':[],'events':[],'orders':[],'notifications':[],'has_more':False,'company':{},'preferences':{'in_app_enabled':True,'categories':[],'stale_hours':48,'poll_interval_minutes':360},'capabilities':{},'providers':[],'alerts':[]}
   await route.fulfill(json=data)
  await context.route('**/*',handler)
  page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  for route,name in [('/','home'),('/login','login'),('/login?mode=signup','signup'),('/pricing','pricing')]:
   await page.goto('http://127.0.0.1:8012'+route,wait_until='networkidle')
   for width,height in [(1440,900),(390,844)]:
    await page.set_viewport_size({'width':width,'height':height});await page.screenshot(path=str(OUT/f'{name}-{width}.png'),full_page=True)
    await page.screenshot(path=str(OUT/f'{name}-{width}-fold.png'),full_page=False)
    print(name,width,'overflow',await page.evaluate('document.documentElement.scrollWidth>innerWidth'))
  await page.goto('http://127.0.0.1:8012/login',wait_until='networkidle')
  await page.locator('#identity-email').fill('tester@example.invalid');await page.locator('#identity-password').fill('synthetic-local-only')
  await page.locator('#identity-login-submit').click();await page.wait_for_function("document.body.classList.contains('auth-ready')")
  views=await page.locator('.sidebar nav button').evaluate_all('(els)=>els.map(e=>({id:e.id,label:e.textContent.trim()}))')
  print('Views',views)
  for view in views:
   await page.set_viewport_size({'width':1440,'height':900});await page.locator('#'+view['id']).click();await page.wait_for_timeout(100)
   await page.screenshot(path=str(OUT/f"{view['id']}-1440.png"),full_page=True)
   for width in [320,390,768,1440,1920]:
    await page.set_viewport_size({'width':width,'height':900});assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(view['id'],width)
   await page.set_viewport_size({'width':390,'height':844});await page.screenshot(path=str(OUT/f"{view['id']}-390.png"),full_page=True)
  # Exercise the mobile disclosure and its original, role-based destination handlers.
  await page.set_viewport_size({'width':390,'height':844})
  await page.locator('.mobile-workspace-menu>summary').click()
  assert await page.locator('.mobile-nav').is_visible()
  assert await page.locator('.mobile-nav').evaluate("e=>e.scrollWidth<=e.clientWidth+1 && getComputedStyle(e).display==='grid'")
  await page.locator('#mobile-dispatch').click()
  assert await page.locator('#quote-form').is_visible()
  assert not await page.locator('.mobile-nav').is_visible()
  await page.locator('.mobile-workspace-menu>summary').click()
  await page.screenshot(path=str(OUT/'mobile-menu-open.png'),full_page=False)
  await page.locator('.mobile-workspace-menu>summary').click()
  assert not await page.locator('.mobile-nav').is_visible()
  # Keyboard focus and reduced-motion presentation use the actual shared CSS.
  await page.keyboard.press('Tab')
  await page.locator('.mobile-workspace-menu>summary').focus()
  assert await page.locator('.mobile-workspace-menu>summary').evaluate("e=>getComputedStyle(e).outlineStyle!=='none'")
  await page.emulate_media(reduced_motion='reduce')
  assert await page.locator('.primary').first.evaluate("e=>parseFloat(getComputedStyle(e).transitionDuration)<=0.001")
  print('Errors',errors)
  assert not errors,errors
  (OUT/'qa.json').write_text(json.dumps({'errors':errors,'views':views,'api_requests_mocked':len(requests),'real_provider_calls':0},indent=2),encoding='utf8')
  await browser.close()
asyncio.run(run())
