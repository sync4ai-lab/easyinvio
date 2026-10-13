"""Package guidance UI checks with controlled API responses, no provider calls."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright
from backend.package_guidance import PackageCheck,evaluate_package
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())

async def run():
 body={'origin_country':'GB','destination_country':'FR','cargo_type':'PARCEL','actual_weight_kg':'10','dimensions':{'length_cm':'80','width_cm':'60','height_cm':'90'}}
 warning=evaluate_package(PackageCheck.model_validate(body));small=evaluate_package(PackageCheck.model_validate({**body,'dimensions':{'length_cm':'40','width_cm':'30','height_cm':'20'}}))
 blocked=evaluate_package(PackageCheck.model_validate({**body,'cargo_type':'LETTER','actual_weight_kg':'0.5','dimensions':None}))
 async with async_playwright() as pw:
  browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':950});errors=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  await page.goto('http://127.0.0.1:8000/',wait_until='domcontentloaded');await page.wait_for_function("state.mode!=='checking'")
  initial_dimensions=await page.evaluate("['length_cm','width_cm','height_cm','weight_kg'].map(id=>document.querySelector('#'+id).value)")
  await page.evaluate('''(warning)=>{
   document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
   portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER'};renderPortal();setView('dispatch');state.session={access_token:'controlled-no-network-token'};
   quotePayload=()=>({origin:{city:'Leeds',country_code:'GB'},destination:{city:'Paris',country_code:'FR'},cargo_type:'PARCEL',weights_kg:['10'],dimensions:[{length_cm:'80',width_cm:'60',height_cm:'90'}]});
   window.quoteCalls=0;window.checkResponse=warning;api=async(path)=>{if(path.endsWith('package-check'))return checkResponse;if(path==='/v1/rates'){quoteCalls++;return {rates:[],issues:[],partial:false};}throw Error('Unexpected test request '+path);};
   document.querySelector('#quote-form').dispatchEvent(new Event('submit',{cancelable:true}));
  }''',warning)
  await page.wait_for_function("document.querySelector('#package-guidance-dialog').open")
  assert '370 cm' in await page.locator('#package-guidance-dialog-body').text_content()
  assert await page.evaluate('quoteCalls')==0
  for width in [375,768,1366]:
   await page.set_viewport_size({'width':width,'height':950});assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  await page.locator('#package-guidance-edit').click();await page.wait_for_function("!document.querySelector('#quote-btn').disabled")
  assert await page.evaluate('quoteCalls')==0
  assert await page.evaluate("['length_cm','width_cm','height_cm','weight_kg'].map(id=>document.querySelector('#'+id).value)")==initial_dimensions
  await page.evaluate("document.querySelector('#quote-form').dispatchEvent(new Event('submit',{cancelable:true}))")
  await page.wait_for_function("document.querySelector('#package-guidance-dialog').open");await page.locator('#package-guidance-continue').click()
  await page.wait_for_function('quoteCalls===1 && !document.querySelector("#quote-btn").disabled')
  await page.evaluate('(blocked)=>{checkResponse=blocked;document.querySelector("#quote-form").dispatchEvent(new Event("submit",{cancelable:true}));}',blocked)
  await page.wait_for_function("document.querySelector('#package-guidance-dialog').open")
  assert await page.locator('#package-guidance-continue').is_hidden()
  await page.locator('#package-guidance-edit').click();await page.wait_for_function("!document.querySelector('#quote-btn').disabled")
  assert await page.evaluate('quoteCalls')==1
  await page.evaluate('(small)=>{checkResponse=small;document.querySelector("#quote-form").dispatchEvent(new Event("submit",{cancelable:true}));}',small)
  await page.wait_for_function('quoteCalls===2 && !document.querySelector("#quote-btn").disabled')
  assert not errors,errors
  print(json.dumps({'checks':['large parcel warning before rate requests','edit/cancel does not call rates or change measurements','other carriers remain available after explicit continue','blocking guidance hides continue','normal package proceeds directly','375/768/1366px layouts'],'page_errors':errors}))
  await browser.close()
asyncio.run(run())
