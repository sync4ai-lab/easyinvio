"""Controlled UI verification; sample statistics are not written to the database."""
import asyncio,os
from pathlib import Path
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
 async with async_playwright() as pw:
  browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':950});errors=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  await page.goto('http://127.0.0.1:8000',wait_until='domcontentloaded')
  await page.wait_for_function("state.mode!=='checking'")
  await page.evaluate("""document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
    portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER'};renderPortal();setView('dispatch');
    const rates=[{provider:'EASYPOST',carrier_code:'DHL',service_code:'ExpressWorldwide',currency:'GBP',client_price_ex_tax:'24.00',delivery_days:2,on_time_rate:'98.4',avg_transit_days:'1.5',delivery_samples:125,route_risk_level:'LOW',fee_breakdown:{base_cost:'18',fuel_surcharge:'2',platform_markup:'4',wholesale_total:'20'}},
    {provider:'REGIONAL',carrier_code:'DPD',service_code:'NextDay',currency:'GBP',client_price_ex_tax:'28.00',delivery_days:1,on_time_rate:null,avg_transit_days:null,delivery_samples:0,route_risk_level:'HIGH_DELAY_ALERT',fee_breakdown:{wholesale_total:'20',platform_markup:'8'}}];
    window.testRateResult={rates,issues:[{provider:'SENDCLOUD',code:'unavailable'}],partial:true,simulated:true};renderRates(testRateResult);
  """)
  text=await page.locator('#rates').inner_text()
  assert all(name.lower() not in text.lower() for name in ['easypost','sendcloud','shippo','shiprocket'])
  assert '98.4%' in text and '1.5 days' in text and 'history unavailable' in text
  await expect(page.locator('.route-delay-alert')).to_have_count(1)
  await page.locator('#rates details summary').first.click()
  await expect(page.locator('#rates details').first).to_have_attribute('open','')
  Path('docs/carrier_consolidation').mkdir(parents=True,exist_ok=True)
  await page.locator('#rates').screenshot(path='docs/carrier_consolidation/rates.png')
  for width in [375,768,1366]:
   await page.set_viewport_size({'width':width,'height':950})
   assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  await page.evaluate("portal.profile.workspace_role='DISPATCHER';renderRates(testRateResult)")
  await expect(page.locator('#rates details')).to_have_count(0)
  assert not errors,errors
  await browser.close()
 print('PASS: carrier-only cards, performance badges, missing-data honesty, amber alerts, finance-only fee disclosures and mobile layout; controlled data only.')
if __name__=='__main__':asyncio.run(run())
