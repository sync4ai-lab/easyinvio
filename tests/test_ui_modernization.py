"""Real-browser verification of cargo controls, exports and responsive portals."""
import asyncio, json, os
from pathlib import Path
from playwright.async_api import async_playwright, expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
OUT=Path('docs/ui_modernization');OUT.mkdir(exist_ok=True)
async def run():
 results=[];errors=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch()
  page=await browser.new_page(viewport={'width':1440,'height':1000})
  page.set_default_timeout(5000)
  page.on('pageerror',lambda e:errors.append(str(e)))
  await page.goto('http://127.0.0.1:8000',wait_until='domcontentloaded')
  await page.wait_for_timeout(1200)
  async def check(name,fn):
   try:
    evidence=await fn();results.append({'test':name,'status':'PASS','evidence':evidence})
   except Exception as e:results.append({'test':name,'status':'FAIL','error':str(e)})
  async def layouts():
   evidence=[]
   for width in [375,768,1024,1280,1440]:
    await page.set_viewport_size({'width':width,'height':1000})
    for view in ['dashboard','dispatch','manifest','wallet','boxes','customs']:
     await page.evaluate('(v)=>setView(v)',view)
     overflow=await page.evaluate('document.documentElement.scrollWidth-innerWidth')
     assert overflow<=1,(width,view,overflow)
     evidence.append([width,view,overflow])
   await page.evaluate("document.body.style.zoom='0.8';setView('dispatch')")
   assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1
   await page.evaluate("document.body.style.zoom='1'")
   return evidence
  await check('Fluid layouts, six views and 80% zoom',layouts)
  async def cargo():
   await page.evaluate("setView('dispatch')")
   await page.locator('#cargo-type').select_option('LETTER')
   assert await page.locator('#length_cm').is_disabled()
   await page.wait_for_timeout(500)
   assert '0.100' in await page.locator('#weight-result').inner_text()
   await page.locator('#cargo-type').select_option('PALLET')
   await page.wait_for_timeout(500)
   assert '700' in await page.locator('#weight-result').inner_text()
   await page.locator('#quote-btn').click();await page.wait_for_timeout(600)
   assert 'Regional Freight' in await page.locator('#rates').inner_text()
   await page.locator('#cargo-type').select_option('OVERLAND_FREIGHT')
   await page.wait_for_timeout(500)
   assert '1750' in await page.locator('#weight-result').inner_text()
   return 'Letter dimensions omitted; pallet floor 700 kg; road freight floor 1750 kg; sample freight rates rendered.'
  await check('Cargo calculations and sample rates',cargo)
  async def customs():
   await page.locator('#destination-country_code').fill('US')
   await page.locator('#destination-country_code').dispatch_event('input')
   assert await page.locator('#checkout-customs').is_visible()
   await page.locator('#checkout-customs summary').click()
   await page.locator('#qc-reviewed').check()
   await page.locator('#qc-generate').click()
   await expect(page.locator('#qc-json')).to_be_enabled()
   async with page.expect_download() as pending:await page.locator('#qc-json').click()
   download=await pending.value;doc=json.loads(Path(await download.path()).read_text())
   assert doc['document_type']=='COMMERCIAL_INVOICE' and doc['items'][0]['hs_code']=='610910'
   async with page.expect_download() as pending:await page.locator('#qc-print').click()
   download=await pending.value;html=Path(await download.path()).read_text()
   assert 'Signature' in html and 'Cotton knitted T-shirt' in html
   return 'Reviewed JSON and printable HTML downloaded; commodity and signature fields verified.'
  await check('International customs preview and exports',customs)
  async def manifest():
   await page.evaluate("setView('manifest')")
   text=await page.locator('#manifest-body').inner_text()
   assert all(s in text for s in ['IN_TRANSIT','DELIVERED','EXCEPTION','Out for delivery'])
   await page.locator('#manifest-filter').select_option('EXCEPTION')
   assert await page.locator('#manifest-body tr').count()==1
   await page.locator('[data-manifest-detail]').click()
   assert await page.locator('#shipment-dialog').is_visible()
   await page.locator('#shipment-dialog [data-close]').click()
   await page.locator('#manifest-filter').select_option('all')
   return 'Three labelled sample rows, milestone pipeline, exception filter and timeline dialog.'
  await check('Manifest status pipeline and actions',manifest)
  async def support():
   await page.evaluate("setView('dashboard')")
   await page.locator('[data-dispute-ticket]').first.click()
   assert await page.locator('#dispute-dialog').is_visible()
   assert 'not sent' in await page.locator('#dispute-draft').input_value()
   await page.locator('#dispute-dialog [data-close]').click()
   await page.evaluate('window.scrollTo(0,0)')
   await page.screenshot(path=str(OUT/'client-desktop.png'),full_page=True)
   return 'Dispute review opens without sending messages or making payments.'
  await check('Support surcharge dispute action',support)
  async def owner():
   await page.locator('#role-admin').click()
   assert 'Consolidated Gross Revenue' in await page.locator('#dashboard-metrics').inner_text()
   await page.screenshot(path=str(OUT/'owner-desktop.png'),full_page=True)
   await page.set_viewport_size({'width':375,'height':812})
   assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1
   await page.locator('#role-client').click()
   await page.evaluate("setView('customs')")
   assert await page.locator('#customs-backdrop').is_visible()
   await page.locator('#customs-close').click()
   await page.locator('#role-client').click()
   assert 'Consolidated Gross Revenue' not in await page.locator('#dashboard-metrics').inner_text()
   await page.evaluate('window.scrollTo(0,0)')
   await page.screenshot(path=str(OUT/'client-mobile.png'),full_page=True)
   return 'Owner macro metrics, client isolation, mobile owner layout and customs drawer.'
  await check('Owner/client portal and mobile drawers',owner)
  results.append({'test':'JavaScript runtime','status':'PASS' if not errors else 'FAIL','errors':errors})
  await browser.close()
 OUT.joinpath('results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
 print(json.dumps(results,indent=2))
if __name__=='__main__':asyncio.run(run())
