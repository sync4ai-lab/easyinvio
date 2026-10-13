import asyncio,json,os
from pathlib import Path
from uuid import uuid4
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
 ids=[str(uuid4()),str(uuid4())];offers=[str(uuid4()),str(uuid4())];calls=[];errors=[];booked=False
 rates=[{'offer_id':offers[0],'carrier_code':'DHL','service_code':'Express','currency':'GBP','client_price_ex_tax':'12.50','delivery_days':2}, {'offer_id':offers[1],'carrier_code':'UPS','service_code':'Express Saver','currency':'GBP','client_price_ex_tax':'16.50','delivery_days':3}]
 rows=[{'id':ids[0],'reference':'QA-PARCEL-1','status':'QUOTED','currency':'GBP','price':'12.50','batch_import':True,'origin_country':'GB','destination_country':'GB'},{'id':ids[1],'reference':'QA-CUSTOMS-2','status':'PENDING_IMPORT','currency':'GBP','batch_import':True,'customs_required':True,'origin_country':'GB','destination_country':'US'}]
 async with async_playwright() as pw:
  browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':900});page.on('pageerror',lambda e:errors.append(str(e)))
  async def handler(route):
   nonlocal booked
   path=route.request.url.split('/api/v1/',1)[1]
   if path=='shipments/bulk/review':data={'orders':[{'shipment_id':ids[0],'reference':'QA-PARCEL-1','status':'QUOTED','customs_ready':True,'rates':rates,'batch_import':True},{'shipment_id':ids[1],'reference':'QA-CUSTOMS-2','status':'PENDING_IMPORT','customs_ready':False,'rates':[],'batch_import':True,'notice':'Complete customs and fetch fresh rates'}]}
   elif path=='shipments/bulk/checkout':
    calls.append(route.request.post_data_json);assert len(calls[-1]['offers'])==1;assert calls[-1]['offers'][0]['offer_id']==offers[1];assert calls[-1]['offers'][0]['expected_price']=='16.50'
    if len(calls)==1:await route.fulfill(status=402,json={'detail':'Insufficient available wallet funds for the selected total; no labels were purchased'});return
    booked=True;rows[0].update(status='BOOKED',booked_at='2026-10-13T00:00:00Z',tracking_number='QA-TRACK',price='16.50')
    data={'results':[{'shipment_id':ids[0],'reference':'QA-PARCEL-1','status':'BOOKED','label':{'tracking_number':'QA-TRACK'}}],'notice':'Each order is confirmed separately.'}
   elif path=='shipments/manifest':data={'shipments':rows}
   elif path in ('config','auth/config'):data={'mode':'configured','supabase_url':None,'publishable_key':None}
   elif path=='dispatch-workspace/orders':data={'orders':[],'stores':[],'more_available':False}
   else:data={'shipments':[],'stores':[],'orders':[],'tickets':[]}
   await route.fulfill(json=data)
  await page.route('**/api/v1/**',handler);await page.goto('http://127.0.0.1:8000/');await page.wait_for_function("state.mode!=='checking'")
  await page.evaluate('''(rows)=>{document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;state.session={access_token:'controlled',expires_at:9999999999};state.mode='configured';portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'00000000-0000-4000-8000-000000000001'};state.manifest=rows;setView('manifest');renderManifest();}''',rows)
  await expect(page.locator('#manifest-print-mode')).to_have_text('Carrier PDF downloads')
  await page.locator('[data-bulk-manifest]').first.check();await page.locator('[data-bulk-manifest]').nth(1).check();await page.locator('#manifest-bulk-review').click()
  await expect(page.locator('#bulk-checkout-dialog')).to_be_visible();await expect(page.locator('#bulk-checkout-total')).to_have_text('\u00a312.50')
  await page.locator('[data-bulk-service]').select_option(offers[1]);await expect(page.locator('#bulk-checkout-total')).to_have_text('\u00a316.50')
  assert await page.locator('[data-bulk-include]:checked').count()==1;assert await page.locator('[data-bulk-include]:disabled').count()==1
  for width in [375,768,1366]:
   await page.set_viewport_size({'width':width,'height':900});assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1
  await page.locator('#bulk-checkout-buy').click();await expect(page.locator('#bulk-checkout-error')).to_contain_text('Insufficient');assert not booked
  await page.locator('#bulk-checkout-buy').click();await expect(page.locator('#bulk-checkout-body')).to_contain_text('QA-TRACK');await expect(page.locator('#bulk-download-labels')).to_be_visible();assert booked
  await page.locator('#bulk-open-manifest').click();await expect(page.locator('#bulk-checkout-dialog')).not_to_be_visible();await expect(page.locator('[data-print]').first).to_have_text('Download carrier label PDF')
  await page.evaluate("setView('boxes');$('#weight_kg').value='7';applyBox(0)");assert await page.locator('#weight_kg').input_value()=='';assert await page.locator('#length_cm').input_value()!=''
  await page.evaluate('clearSession()');assert await page.locator('#bulk-checkout-body').inner_text()=='';assert not errors,errors
  await browser.close()
 report={'status':'PASS','boundary':'controlled API; no real purchases or messages','checks':['Manifest counts and Carrier PDF wording','Two service choices with exact selected total','Unprepared customs excluded from checkout','Wallet failure keeps review available','Successful exact-offer booking and label bundle action','375/768/1366px layouts','Packaging sizes never reuse packed weight','Logout clears bulk selection and results'],'javascript_errors':errors}
 Path('docs/bulk_dispatch/browser_report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(run())
