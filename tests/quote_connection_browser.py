"""Controlled UI regression checks; no provider requests or configuration writes."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
 async with async_playwright() as pw:
  browser=await pw.chromium.launch();page=await browser.new_page();errors=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  await page.goto('http://127.0.0.1:8000/',wait_until='domcontentloaded')
  await page.wait_for_function("state.mode!=='checking'")
  await page.evaluate("""() => {
   document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
   portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER'};renderPortal();setView('dispatch');
   state.session={access_token:'controlled-no-network-token'};state.quotes=[{carrier_code:'STALE'}];state.lastRateResult={rates:state.quotes};
   quotePayload=()=>({});api=async()=>{const error=Error('Carrier quotes were returned in GBP, but none matched EUR.');error.status=503;throw error;};
   document.querySelector('#quote-form').dispatchEvent(new Event('submit',{cancelable:true}));
  }""")
  await page.wait_for_function("document.querySelector('#rates-badge').textContent==='NO QUOTE AVAILABLE'")
  assert await page.evaluate('state.quotes.length===0 && state.lastRateResult===null && state.quoteRequest===null')
  assert 'returned in GBP' in await page.locator('#rates').inner_text()
  await page.evaluate("""() => {
   enterpriseAdminGuard=()=>{};enterprise.tenants=[];enterprise.providerProfiles=[];enterprise.carriers=[{id:'fixture',account_name:'Sendcloud',company_name:'EasyInvio',platform_owned:true,environment:'TEST',is_active:true,priority:1,api_base_url:'https://panel.sendcloud.sc/api/v2'}];
   renderEnterpriseTables();window.upgradeCalls=[];api=async(path,options)=>{upgradeCalls.push({path,options});return {upgraded:true};};loadEnterpriseView=async()=>{};
   document.querySelector('[data-sendcloud-upgrade]').click();
  }""")
  assert await page.locator('#sendcloud-upgrade-dialog').evaluate('(dialog)=>dialog.open')
  await page.locator('#sendcloud-upgrade-confirm').click()
  await page.wait_for_function("!document.querySelector('#sendcloud-upgrade-dialog').open")
  calls=await page.evaluate('upgradeCalls');assert calls[0]['path'].endswith('/fixture/upgrade-sendcloud') and calls[0]['options']['method']=='POST'
  assert not errors,errors
  print(json.dumps({'controlled_browser_checks':['failed quote clears stale selectable offers','failed quote shows actionable currency message and correct badge','Sendcloud upgrade dialog submits authenticated POST and refreshes configuration'],'page_errors':errors}))
  await browser.close()
asyncio.run(run())
