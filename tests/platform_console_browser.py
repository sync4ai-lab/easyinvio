"""Populated platform console acceptance; synthetic records, no remote provider calls."""
import asyncio,json,os,socket,threading,time
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit,parse_qs
import uvicorn
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright,expect
from scripts.build_vercel import ASSETS
ROOT=Path(__file__).resolve().parents[1]
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.playwright')
OUT=ROOT/'output/platform-console-qa'
async def run(origin):
 OUT.mkdir(parents=True,exist_ok=True);errors=[];calls=[];changes=[]
 uid=str(uuid4());tid=str(uuid4());pid=str(uuid4())
 clients=[{'tenant_id':tid,'company_name':'Northgate Home and Lifestyle Wholesale Limited','workspace_slug':'northgate-uat','workspace_type':'BUSINESS','billing_email':'test@example.invalid','billing_plan':'PREPAID_WALLET','default_currency':'GBP','workspace_status':'ACTIVE','is_sandbox':True,'seller_classification':'STANDARD','crm_queued':True},
 {'tenant_id':pid,'company_name':'Personal Example','workspace_type':'INDIVIDUAL','billing_email':'personal@example.invalid','billing_plan':'PREPAID_WALLET','default_currency':'GBP','workspace_status':'ACTIVE','is_sandbox':True}]
 profile={'portal_role':'SUPER_ADMIN','user_id':uid,'tenant_id':None};identity={'user_id':uid,'email':'owner@example.invalid','role':'SUPER_ADMIN','full_name':'Synthetic Owner'}
 connections=[{'id':str(uuid4()),'account_name':'Shared shipping','company_name':'EasyInvio','platform_owned':True,'api_base_url':'https://api.easypost.com/v2','environment':'TEST','is_active':True,'priority':1},
 {'id':str(uuid4()),'account_name':'Legacy disabled fixture','company_name':'Synthetic Shop','platform_owned':False,'aggregator':'EASYPOST','environment':'TEST','is_active':False,'priority':10}]
 health={'monthly':[{'month':'2026-09-01','currency':'GBP','packages':20},{'month':'2026-10-01','currency':'GBP','packages':40}],
 'top_clients':[{'tenant_id':tid,'company_name':clients[0]['company_name'],'currency':'GBP','labels':30,'packages':40,'gross_revenue':'250.50','gross_markup':'25.50'}],
 'booking_states':[{'status':'BOOKED','shipments':30},{'status':'FAILED','shipments':2}],
 'wallet_exposure':[{'currency':'GBP','wallet_balance':'500.00','reserved_balance':'8.10'}]}
 report={'environment':'SANDBOX','start_date':'2026-09-01','end_date':'2026-10-24','totals_by_currency':[{'currency':'GBP','revenue':'250.50','margin':'25.50','package_count':40}],'active_tenants':2,'carriers':[{'carrier':'EVRI','volume':40}],
 'billing_pipeline':[],'payment_pipeline':[],'active_support':[],'cohorts':{'shipping':[],'tickets':[],'accounts':[]},'business_health':health}
 async with async_playwright() as pw:
  browser=await pw.chromium.launch(headless=True);page=await browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda error:errors.append(str(error)))
  async def mock(route):
   path=urlsplit(route.request.url).path;calls.append(route.request.url)
   if path=='/api/v1/auth/token':data={'access_token':'synthetic-owner','expires_at':int(time.time())+900,'absolute_expires_at':int(time.time())+3600,'user':{'id':uid,'email':identity['email']},'bootstrap':{'profile':profile,'identity':identity}}
   elif path=='/api/v1/auth/me':data=identity
   elif path=='/api/v1/profile':data=profile
   elif path=='/api/v1/config':data={'mode':'configured'}
   elif '/analytics/' in path:data=report
   elif '/seller-classification' in path:
    changes.append(route.request.post_data_json);clients[0]['seller_classification']=changes[-1]['seller_classification'];data={'updated':True}
   elif path=='/api/v1/admin/tenants':data={'tenants':clients,'crm':{'enabled':True,'environment':'SANDBOX'}}
   elif path=='/api/v1/admin/transactions':data={'transactions':[{'company_name':clients[0]['company_name'],'entry_type':'CAPTURE','balance_delta':'-8.10','reserved_delta':'-8.10','balance_after':'491.90','reserved_after':'0.00','currency':'GBP','created_at':'2026-10-24T12:00:00Z'}]}
   elif path=='/api/v1/admin/carriers':data={'connections':[connections[1]]}
   elif path=='/api/v1/admin/platform-carriers':data={'connections':[connections[0]]}
   elif path=='/api/v1/admin/platform-carriers/capabilities':data={'providers':[{'code':code,'name':name,'endpoint':endpoint,'label_purchase':True} for code,name,endpoint in [('EASYPOST','EasyPost','https://api.easypost.com/v2'),('SENDCLOUD_V3','Sendcloud v3','https://panel.sendcloud.sc/api/v3'),('SHIPPO','Shippo','https://api.goshippo.com')]]}
   elif path=='/api/v1/admin/marketplaces':
    environment=parse_qs(urlsplit(route.request.url).query)['environment'][0]
    data={'environment':environment,'limit':200,'stores':[{'company_name':clients[0]['company_name'],'display_name':'Example store','platform':'SHOPIFY','is_active':True,'credentials_saved':True,'imported_orders':3,'last_import_at':None}]}
   elif path=='/api/v1/admin/support/whatsapp/bindings':data={'configured':True,'controls_ready':True,'setup':'Configured test sender.','bindings':[{'id':str(uuid4()),'company_name':'Synthetic Shop','recipient_name':'Synthetic Recipient','is_sandbox':True,'number_suffix':'0123','is_active':True,'user_active':True,'verified':True,'notification_opt_in':False,'alerts_paused':False}]}
   else:data={'tickets':[],'shipments':[],'rules':[],'stores':[],'items':[],'notifications':[],'alerts':[],'has_more':False}
   await route.fulfill(json=data)
  await page.route('**/api/**',mock);await page.route('https://**',lambda route:route.abort())
  await page.goto(origin,wait_until='domcontentloaded');await page.locator('#identity-email').fill('owner@example.invalid');await page.locator('#identity-password').fill('synthetic-password');await page.locator('#identity-login-submit').click()
  await expect(page.locator('.app-shell')).to_be_visible();await expect(page.locator('#platform-business-health')).to_contain_text('Leading clients')
  await page.evaluate("setView('admin-clients')");await expect(page.locator('#tenant-rows')).to_contain_text('Sync queued')
  assert not await page.locator('[data-admin-source]').first.is_visible()
  await page.locator('[data-seller-choice="'+tid+'"]').select_option('HIGH_VOLUME_COST_SENSITIVE_SELLER');await page.locator('[data-seller-strategy="'+tid+'"]').click();await expect(page.locator('#transaction-rows')).to_contain_text('491.90')
  assert len(changes)==1 and changes[0]['seller_classification']=='HIGH_VOLUME_COST_SENSITIVE_SELLER'
  await expect(page.locator('#transaction-rows')).to_contain_text('Label charged')
  await page.evaluate("setView('admin-carriers')");await expect(page.locator('#provider-catalogue article')).to_have_count(3)
  assert 'Legacy disabled fixture' not in await page.locator('#carrier-rows').text_content()
  await page.locator('#carrier-show-legacy').check();assert 'Legacy disabled fixture' not in await page.locator('#carrier-rows').text_content()
  await page.locator('#carrier-show-removed').check();await expect(page.locator('#carrier-rows')).to_contain_text('Legacy disabled fixture')
  await expect(page.locator('#admin-alert-bindings')).to_contain_text('Number verified');await expect(page.locator('#admin-alert-bindings')).to_contain_text('Awaiting consent')
  for width in [320,393,768,1440]:
   await page.set_viewport_size({'width':width,'height':950})
   for view in ['dashboard','admin-clients','admin-carriers','admin-stores','admin-margins','manifest','profile']:
    await page.evaluate('(view)=>setView(view)',view);await page.wait_for_timeout(140)
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(width,view,'overflow')
    title=page.locator('#'+view+' > .pagehead h1')
    if await title.count() and await title.is_visible():assert (await title.bounding_box())['width']>180,(width,view,'heading')
    if view=='admin-carriers':
     tops=await page.locator('#provider-catalogue article').evaluate_all('nodes=>nodes.map(e=>e.getBoundingClientRect().top)')
     if width>=1440:assert max(tops)-min(tops)<2,tops
    if view=='admin-clients':
     assert await page.locator('#tenant-rows .tag').first.evaluate('e=>getComputedStyle(e).whiteSpace')=='nowrap'
    await page.evaluate("scrollTo(0,0);document.getElementById('toast').hidden=true")
    await page.screenshot(path=str(OUT/(view+'-'+str(width)+'.png')))
  for width in [320,1440]:
   await page.set_viewport_size({'width':width,'height':950})
   for identifier in ['tenant-admin-dialog','carrier-admin-dialog','margin-admin-dialog']:
    await page.locator('#'+identifier).evaluate('dialog=>dialog.showModal()')
    assert await page.locator('#'+identifier).evaluate('dialog=>dialog.scrollWidth<=dialog.clientWidth+1'),(width,identifier,'dialog overflow')
    control=page.locator('#'+identifier+' input:not([type=checkbox])').first
    assert (await control.bounding_box())['height']>=44,(width,identifier,'small control')
    await page.locator('#'+identifier).evaluate('dialog=>dialog.close()')
  await page.evaluate("setView('admin-stores')");await page.locator('#platform-store-environment').select_option('SANDBOX');await expect(page.locator('#platform-store-rows')).to_contain_text('Settings saved')
  assert any('/admin/marketplaces?environment=SANDBOX' in call for call in calls)
  await page.locator('#platform-store-search').fill('Northgate');await page.wait_for_timeout(500)
  assert any('search=Northgate' in call for call in calls)
  assert not errors,errors
  await browser.close()
 print(json.dumps({'status':'PASS','widths':[320,393,768,1440],'views':7,'checks':['executive charts','queued CRM','explicit strategy save','ledger balances','independent carrier filters','verified versus consent','marketplace environment and search'],'provider_calls':0,'page_errors':errors},indent=2))
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
  while not server.started:time.sleep(.05)
  asyncio.run(run(origin))
 finally:server.should_exit=True;thread.join(timeout=10);listener.close()
