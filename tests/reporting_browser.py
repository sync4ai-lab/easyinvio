"""Controlled dashboard range, refresh, empty state, failure isolation and country tests."""
import asyncio,json,os
from pathlib import Path
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
 errors=[];requests=[];tenant=str(uuid4());today=datetime.now(timezone.utc).date();start=(today-timedelta(days=5)).isoformat();end=today.isoformat();wallet_down=False
 async with async_playwright() as p:
  b=await p.chromium.launch();page=await b.new_page(viewport={'width':1366,'height':900});page.set_default_timeout(7000);page.on('pageerror',lambda e:errors.append(str(e)))
  async def route(r):
   from urllib.parse import urlsplit,parse_qs
   path=urlsplit(r.request.url).path;query=parse_qs(urlsplit(r.request.url).query);requests.append(path)
   if path.endswith('/profile'):data={'tenant_id':tenant,'workspace_role':'OWNER','portal_role':'CLIENT','company_name':'Synthetic Workspace'}
   elif path.endswith('/analytics/reports'):
    populated=query['start_date'][0]==start
    data={'start_date':query['start_date'][0],'end_date':query['end_date'][0],'total_package_count':2 if populated else 0,'totals_by_currency':[{'currency':'GBP','shipping_spend':'50.00','package_count':2}] if populated else [],'lanes':[{'origin_country':'GB','destination_country':'JP','currency':'GBP','shipment_count':2,'package_count':2,'average_price':'25.00'}] if populated else [],'performance':{'booked_shipments':2 if populated else 0,'delivered_shipments':1 if populated else 0,'in_transit_shipments':1 if populated else 0,'exception_shipments':0,'awaiting_transit_shipments':0,'measured_deliveries':1 if populated else 0,'observed_transit_days':'2.00' if populated else None,'basis':'Current outcomes of shipments booked in the selected period.'}}
   elif path.endswith('/wallet'):
    if wallet_down:await r.fulfill(status=503,json={'detail':'Wallet temporarily unavailable'});return
    data={'balance':'100.00','reserved_balance':'0.00','available':'100.00','currency':'GBP'}
   elif path.endswith('/support/tickets'):data={'tickets':[]}
   else:data={}
   await r.fulfill(json=data)
  await page.route('**/api/v1/**',route);await page.goto('http://127.0.0.1:8000/',wait_until='domcontentloaded');await page.wait_for_function("state.mode!=='checking'")
  await page.evaluate('''tenant=>{document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;state.session={access_token:'controlled-browser'};state.mode='configured';portal.role='CLIENT';portal.profile={tenant_id:tenant,portal_role:'CLIENT',workspace_role:'OWNER'};setView('dashboard');}''',tenant)
  await page.locator('#report-start').fill(start);await page.locator('#report-end').fill(end);await page.locator('#dashboard-refresh').click()
  await expect(page.locator('#report-refresh-status')).to_contain_text('Updated: '+start);await expect(page.locator('#primary-chart')).to_contain_text('GB -> JP');await expect(page.locator('#secondary-chart')).to_contain_text('2.00 days')
  await expect(page.locator('#dashboard-metrics')).to_contain_text('50.00')
  wallet_down=True;await page.locator('#dashboard-refresh').click();await expect(page.locator('#dashboard-error')).to_contain_text('Report loaded');await expect(page.locator('#primary-chart')).to_contain_text('GB -> JP')
  await page.locator('#report-start').fill(end);await page.locator('#dashboard-refresh').click();await expect(page.locator('#report-refresh-status')).to_contain_text('no confirmed bookings');await expect(page.locator('#primary-chart')).to_contain_text('No confirmed bookings');await expect(page.locator('#secondary-chart')).to_contain_text('Not available')
  before=len(requests);future=(today+timedelta(days=1)).isoformat();await page.locator('#report-end').fill(future);await page.locator('#dashboard-refresh').click();await expect(page.locator('#dashboard-error')).to_contain_text('future');assert len(requests)==before
  assert await page.locator('#report-end').get_attribute('max')==end
  await page.evaluate("setView('dispatch')");await page.locator('#origin-country_code').select_option('GB');await page.locator('#destination-country_code').select_option('JP');assert await page.locator('#destination-country_code option[value=JN]').count()==0
  assert await page.locator('#destination-country_code option').count()==250
  for w in (375,768,1366):
   await page.set_viewport_size({'width':w,'height':900});assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  await b.close()
 assert not errors,errors
 out=Path('docs/reporting');out.mkdir(exist_ok=True);r={'status':'PASS','scope':'controlled browser API','checks':['Refresh uses selected dates and changes real report cards','Wallet failure cannot erase report','Empty booking period explicitly confirmed','Future dates blocked without requests; UTC bounds applied','Transit coverage and missing data shown','GB and Japan JP country selectors; invalid JN unavailable','375/768/1366px no horizontal overflow'],'javascript_errors':errors};(out/'browser_report.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');print(json.dumps(r,indent=2))
if __name__=='__main__':asyncio.run(run())
