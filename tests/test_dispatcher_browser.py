"""Real browser interaction with controlled workspace responses, no real login."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
import httpx
from playwright.async_api import async_playwright, expect


async def run():
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
    env=os.environ.copy();env['PORT']='8003'
    server=subprocess.Popen([sys.executable,'main.py','--local-preview'],env=env,stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    errors=[];calls=[];sid=str(uuid4());store=str(uuid4());body={}
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(50):
                try:
                    if (await client.get('http://127.0.0.1:8003/health')).status_code==200:break
                except httpx.HTTPError:pass
                await asyncio.sleep(.2)
            else:raise RuntimeError('Preview server failed')
        async with async_playwright() as pw:
            browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':1000})
            page.on('pageerror',lambda error:errors.append(str(error)))
            async def route(request_route):
                request=request_route.request;calls.append(request.url)
                path=request.url.split('/api/v1/dispatch-workspace',1)[1]
                if path.startswith('/sync/'):
                    data={'source':'WEBHOOK_INBOX','notice':'Inbox refreshed from signed webhooks.','results':[]}
                elif path==f'/orders/{sid}/prepare':
                    body.update(request.post_data_json)
                    data={'status':'QUOTED','all_rates':[{},{}]}
                elif path==f'/orders/{sid}':
                    data={'status':'PENDING_IMPORT','order':{'idempotency_key':sid,'order_reference':'#1024','store_id':store,'store_order_id':'1024','platform':'SHOPIFY','currency':'USD',
                        'origin':{'name':'Warehouse','line1':'1 Fixture Way','city':'London','postal_code':'SW1A 1AA','country_code':'GB'},
                        'destination':{'name':'Customer','line1':'1 Test Street','city':'New York','state':'NY','postal_code':'10001','country_code':'US','phone':'+12025550123'},
                        'cargo':{'cargo_type':'PARCEL','actual_weight_kg':'0.400','length_cm':None,'width_cm':None,'height_cm':None},
                        'items':[{'description':'Cotton T-shirt','quantity':2,'unit_value':'12.35','unit_weight_kg':'0.200','origin_country':'GB','hs_code':'610910'}]}}
                elif path=='/process':data={'results':[{'order_reference':'#1024','status':'QUOTED'}]}
                else:data={'stores':[{'id':store,'display_name':'Test Store','platform':'SHOPIFY','polling_enabled':False}],
                    'orders':[{'id':sid,'customer_reference':'#1024','display_name':'Test Store','cargo_type':'PARCEL','status':'PENDING_IMPORT','tracking_sync_status':None}],
                    'more_available':False,'offset':0}
                await request_route.fulfill(status=200,json=data)
            await page.route('**/api/v1/dispatch-workspace/**',route)
            await page.goto('http://127.0.0.1:8003',wait_until='domcontentloaded')
            await page.wait_for_function("state.mode==='local-preview'")
            await page.evaluate("state.session={access_token:'controlled-browser-fixture'};state.mode='configured';portal.profile={workspace_role:'DISPATCHER',portal_role:'CLIENT'};portal.role='CLIENT';renderPortal();setView('workspace')")
            await expect(page.locator('#workspace-rows')).to_contain_text('#1024')
            assert await page.locator('.sidebar [data-enterprise-view]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.enterpriseView)')==['workspace','dispatch','manifest']
            await page.locator('#workspace-sync').click();await expect(page.locator('#workspace-notice')).to_contain_text('signed webhooks')
            await page.locator('[data-workspace-pack]').click();await expect(page.locator('#workspace-pack-dialog')).to_be_visible()
            for name,value in {'actual_weight_kg':'2.500','length_cm':'40','width_cm':'30','height_cm':'20','customs_signer':'Reviewed Operator'}.items():
                await page.locator(f'#workspace-pack-form [name="{name}"]').fill(value)
            await page.locator('#workspace-pack-form [name="reviewed"]').check()
            await page.locator('#workspace-pack-save').click();await expect(page.locator('#workspace-pack-result')).to_contain_text('2 options')
            assert body['cargo']['length_cm']=='40' and body['hs_codes_reviewed'] is True and body['items'][0]['hs_code']=='610910'
            await page.locator('#workspace-pack-close').click();await page.locator('[data-workspace-select]').check()
            await page.locator('#workspace-quote').click();await expect(page.locator('#workspace-results')).to_contain_text('QUOTED')
            for width in [375,768,1366]:
                await page.set_viewport_size({'width':width,'height':900})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
            await page.evaluate("clearSession()")
            assert await page.locator('#workspace-rows').inner_text()==''
            assert not errors,errors
            await browser.close()
        print(json.dumps({'browser':'PASS','role_navigation':True,'sync_prepare_quote':True,'widths':[375,768,1366],'session_cleanup':True,'live_authentication':False,'controlled_API':True,'javascript_errors':errors}))
    finally:
        server.terminate();server.wait(timeout=10)


if __name__=='__main__':asyncio.run(run())
