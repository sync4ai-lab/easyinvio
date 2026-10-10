"""Command center UI with controlled owner/profile/database responses."""
import asyncio,json,os,subprocess,sys
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from uuid import uuid4
import httpx
from playwright.async_api import async_playwright,expect


async def run():
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve());env=os.environ.copy();env['PORT']='8004'
    server=subprocess.Popen([sys.executable,'main.py','--local-preview'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    errors=[];calls=[]
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(50):
                try:
                    if (await client.get('http://127.0.0.1:8004/health')).status_code==200:break
                except httpx.HTTPError:pass
                await asyncio.sleep(.2)
            else:raise RuntimeError('Preview startup failed')
        async with async_playwright() as pw:
            browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
            async def route(r):
                url=urlsplit(r.request.url);calls.append(url.path);environment=parse_qs(url.query).get('environment',['PRODUCTION'])[0]
                if url.path=='/api/v1/profile':data={'portal_role':'SUPER_ADMIN','user_id':str(uuid4()),'tenant_id':None}
                elif url.path=='/api/v1/admin/analytics/dashboard':data={'environment':environment,'start_date':'2026-10-01','end_date':'2026-10-10','active_tenants':27,
                    'totals_by_currency':[{'currency':'GBP','revenue':'1234.50','margin':'246.90','package_count':12},{'currency':'USD','revenue':'200.33','margin':'40.07','package_count':4}],
                    'carriers':[{'carrier':'DHL','volume':12},{'carrier':'UPS','volume':4}],
                    'billing_pipeline':[{'billing_plan':'PREPAID_WALLET','billing_status':'ACTIVE','company_count':20}],
                    'payment_pipeline':[{'currency':'GBP','status':'CREDITED','payment_count':1,'amount':'100.00'}],
                    'active_support':[{'status':'OPEN','ticket_count':1}]}
                else:data={'tickets':[{'id':str(uuid4()),'tenant_id':str(uuid4()),'shipment_id':None,'status':'OPEN','ai_summary':'Verify postal code with merchant before asking carrier for correction.',
                    'ai_method':'DETERMINISTIC_MOCK','created_at':'2026-10-10','manual_note':'','company_name':'Example Client','tracking_number':'TRACK-NY-1','destination_country':'US',
                    'notifications':[{'status':'DELIVERED'}]}]}
                await r.fulfill(status=200,json=data)
            await page.route('**/api/v1/profile',route);await page.route('**/api/v1/admin/analytics/**',route);await page.route('**/api/v1/admin/support/tickets**',route)
            await page.goto('http://127.0.0.1:8004',wait_until='domcontentloaded');await page.wait_for_function("state.mode==='local-preview'")
            await page.evaluate("state.session={access_token:'controlled-owner-fixture'};state.mode='configured';portal.role='SUPER_ADMIN';portal.profile={portal_role:'SUPER_ADMIN',tenant_id:null};renderPortal();setView('dashboard')")
            await page.evaluate('refreshPortal()')
            await expect(page.locator('#owner-currency-rows')).to_contain_text('USD');await expect(page.locator('#owner-billing-pipeline')).to_contain_text('20 companies')
            await expect(page.locator('#owner-payment-pipeline')).to_contain_text('CREDITED');await expect(page.locator('#owner-active-threads')).to_contain_text('OPEN: 1')
            await expect(page.locator('#support-tickets')).to_contain_text('Example Client');await expect(page.locator('#support-tickets')).to_contain_text('WhatsApp: DELIVERED')
            await page.locator('#owner-environment').select_option('SANDBOX');await expect(page.locator('#owner-monitoring-source')).to_contain_text('SANDBOX DATA')
            for width in [375,768,1366]:
                await page.set_viewport_size({'width':width,'height':900});assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
            await page.evaluate("portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'fixture'};renderPortal()")
            assert not await page.locator('#owner-command-center').is_visible()
            assert await page.locator('#owner-currency-rows').inner_text()==''
            assert not errors,errors;await browser.close()
        print(json.dumps({'browser':'PASS','currency_billing_support_rendering':True,'environment_switch':True,'client_isolation':True,'widths':[375,768,1366],'javascript_errors':errors,'controlled_owner_API':True}))
    finally:server.terminate();server.wait(timeout=10)


if __name__=='__main__':asyncio.run(run())
