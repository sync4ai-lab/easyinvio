import asyncio,os
from pathlib import Path
from playwright.async_api import async_playwright
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
 async with async_playwright() as pw:
  browser=await pw.chromium.launch();page=await browser.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
  await page.route('**/api/v1/**',lambda route:route.fulfill(json={'mode':'preview','supabase_url':None,'publishable_key':None}))
  await page.goto('http://127.0.0.1:8000/');await page.wait_for_function("typeof checkoutProduct==='function'")
  await page.evaluate("""()=>{document.body.insertAdjacentHTML('beforeend','<div id="qa-goods">'+checkoutProduct({description:'Steel component',quantity:1,unit_value:'15',unit_weight_kg:'1',origin_country:'GB',hs_code:'732690',sku:'SKU <safe>',package_index:2})+'</div>');}""")
  assert await page.locator('#qa-goods [name=sku]').input_value()=='SKU <safe>'
  assert await page.locator('#qa-goods [name=package_index]').input_value()=='2'
  assert await page.locator('#qa-goods [name=quantity]').get_attribute('readonly') is not None
  assert await page.locator('#workspace-pack-form [name=multi_parcel_dimensions]').count()==1
  assert not errors,errors
  print('PASS: all controllers load; multi-box preparation field, escaped SKU, box assignment and read-only customs values verified in Chromium')
  await browser.close()
asyncio.run(run())
