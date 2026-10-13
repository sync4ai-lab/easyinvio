"""Controlled quote comparison and protection disclosure browser checks."""
import asyncio,json,os
from pathlib import Path
from uuid import uuid4
from playwright.async_api import async_playwright
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
 async with async_playwright() as pw:
  browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':950});errors=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  await page.goto('http://127.0.0.1:8000/',wait_until='domcontentloaded');await page.wait_for_function("state.mode!=='checking'")
  await page.evaluate('''()=>{
   document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
   portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'fixture'};renderPortal();setView('dispatch');state.session={access_token:'controlled-no-network-token'};
   api=async(path)=>{if(path.includes('tracking-readiness'))return {reasons:['Tracking receivers are disabled. No completed LIVE deliveries exist on this route.'],method:'Measured transit uses verified dispatch and delivery timestamps.'};if(path.includes('checkout/context'))return {invoice_reference:'EINVIO-TEST',customs_required:false,origin:{country_code:'GB'},destination:{country_code:'FR'},items:[],shipping_currency:'GBP',shipping_cost:'12.00'};if(path.includes('protection-quote'))return {available:false,premium_estimate:'1.20',notice:'Shipsurance UK-origin coverage and API contract are pending; no fee is charged.'};throw Error('Unexpected test request '+path);};
   state.quoteRequest={origin:{country_code:'GB'},destination:{country_code:'FR'}};
   const base={offer_id:'fixture',carrier_code:'FEDEX',currency:'GBP',delivery_days:null,fee_breakdown:{wholesale_total:'8',platform_markup:'2'},route_risk_level:'LOW'};
   state.quotes=[{...base,service_code:'Cheap',client_price_ex_tax:'10.00',on_time_rate:'80.0',avg_transit_days:'3.0',delivery_samples:12,on_time_samples:10,metric_scope:'SERVICE_ROUTE'},
    {...base,service_code:'Reliable',client_price_ex_tax:'12.00',on_time_rate:'98.0',avg_transit_days:'1.0',delivery_samples:100,on_time_samples:99,metric_scope:'SERVICE_ROUTE'},
    {...base,service_code:'Unknown',client_price_ex_tax:'11.00',on_time_rate:null,avg_transit_days:null,delivery_samples:0}];
   state.lastRateResult={rates:state.quotes,partial:false,issues:[]};renderRates(state.lastRateResult);
  }''')
  await page.wait_for_function("document.querySelector('#delivery-quality-readiness').textContent.includes('receivers are disabled')")
  assert 'Cheap' in await page.locator('.rate h3').first.inner_text()
  await page.locator('#rate-sort').select_option('on_time');assert 'Reliable' in await page.locator('.rate h3').first.inner_text()
  assert 'Unknown' in await page.locator('.rate h3').last.inner_text()
  assert 'LOWEST CUSTOMER PRICE' not in await page.locator('.rate').first.inner_text()
  await page.locator('#rate-sort').select_option('transit');assert 'Reliable' in await page.locator('.rate h3').first.inner_text()
  assert 'This service on this route' in await page.locator('.rate').first.inner_text()
  await page.locator('.rate').first.locator('summary').click()
  assert 'does not assess or collect VAT' in await page.locator('.rate').first.inner_text()
  await page.evaluate("document.querySelector('#review-dialog').showModal();bookLive(0)")
  await page.wait_for_function("document.querySelector('#checkout-protection')!==null")
  assert await page.locator('#checkout-protection input').is_disabled()
  assert 'no fee is charged' in await page.locator('#checkout-protection').inner_text()
  assert 'not purchased cover' in await page.locator('#checkout-protection').inner_text()
  await page.locator('#review-dialog .close').click()
  for width in [375,768,1366]:
   await page.set_viewport_size({'width':width,'height':950});assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  assert not errors,errors
  print(json.dumps({'checks':['quality sort separates measured values from unknowns','cheapest badge remains correct after quality sort','service-specific samples and readiness explanation','VAT and separate charges disclosed','protection estimate clearly unavailable and not charged','375/768/1366px layouts'],'page_errors':errors}))
  await browser.close()
asyncio.run(run())
