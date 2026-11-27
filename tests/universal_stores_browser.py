import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright,expect
from backend.platform_registry import PLATFORMS

async def main():
    sid='00000000-0000-4000-8000-000000000057';calls=[];errors=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1366,'height':1000})
        page.on('pageerror',lambda e: errors.append(str(e)))
        async def route(r):
            path=r.request.url.split('/api/v1/')[1].split('?')[0]
            if path=='integration/platforms': value={'platforms':[v.model_dump() for v in PLATFORMS.values()]}
            elif path=='workspace/stores':value={'stores':[{'id':sid,'display_name':'Fixture Shop','platform':'CUSTOM_WEBSITE','is_active':True}]}
            elif path.endswith('/connection'):
                value={'configured':True,'live_delivery':False,'live_import':False,'live_returns':False,'store_url':'https://retailer.example.com','sku_unit_grams':{},'has_webhook_secret':True}
                if r.request.method=='PUT':calls.append(r.request.post_data_json)
            elif path.endswith('/test-connection'):value={'verified':False,'scope':'Signed bridge configured; submit a signed request.'}
            elif path.endswith('/returns-portal'):value={'store_slug':'fixture-shop','return_policy':{'enabled':False,'maximum_price':'10.00'}}
            elif path in {'config','auth/config'}:value={'mode':'configured','supabase_url':None,'publishable_key':None}
            else:value={'orders':[],'stores':[],'shipments':[],'tickets':[],'history':[]}
            await r.fulfill(json=value)
        await page.route('**/api/v1/**',route)
        await page.goto('http://127.0.0.1:8017/workspace')
        print('Initial page errors:',errors,flush=True)
        await page.evaluate("""()=>{document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;
            state.session={access_token:'fixture-only',expires_at:9999999999};portal.role='CLIENT';
            portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'00000000-0000-4000-8000-000000000001'};setView('stores');} """)
        await expect(page.locator('#store-catalogue article')).to_have_count(24)
        await page.locator('#store-category').select_option('Custom Website & API')
        await expect(page.locator('#store-catalogue article')).to_have_count(1)
        await page.locator('#store-category').select_option('All')
        await expect(page.locator('#store-list [data-store-settings]')).to_be_visible()
        await page.locator('[data-store-settings]').click()
        await expect(page.locator('#store-connection-form [name=store_url]')).to_have_value('https://retailer.example.com')
        await page.locator('#store-connection-form [name=tracking_callback_url]').fill('https://retailer.example.com/hooks/tracking')
        await page.locator('#store-connection-form [name=live_delivery]').check()
        await page.locator('#store-connection-form button[type=submit]').click()
        await expect(page.locator('#store-connection')).not_to_be_visible()
        assert calls and calls[0]['live_delivery'] is True and calls[0]['tracking_callback_url'].endswith('/hooks/tracking')
        await page.locator('#store-list [data-store-portal]').click()
        await expect(page.locator('#store-return-policy')).to_be_visible()
        await expect(page.locator('#store-return-policy-form [name=store_slug]')).to_have_value('fixture-shop')
        await page.locator('[data-close-portal]').click()
        for width in (375,768,1366):
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1
        # Public portal: all API calls mocked; no real order/customer is queried.
        await page.unroute('**/api/v1/**',route)
        async def portal(r):
            path=r.request.url
            if path.endswith('/verify'):value={'token':'fixture-token-do-not-use-for-authentication','items':[{'description':'Fixture shirt','quantity':1}],'notice':'No label purchased.'}
            elif path.endswith('/confirm'):value={'status':'BOOKED','label_url':'https://uat.easyinvio.com/fixture-label','qr_url':'https://uat.easyinvio.com/fixture-qr'}
            else:value={'store_name':'Fixture retailer','return_window_days':30,'notice':'Original single parcel only.'}
            await r.fulfill(json=value)
        await page.route('**/api/v1/public/store-returns/**',portal)
        await page.goto('http://127.0.0.1:8017/returns/fixture-shop')
        await expect(page.locator('#store-name')).to_have_text('Fixture retailer returns')
        await page.locator('[name=order_reference]').fill('#1042');await page.locator('[name=verification_value]').fill('LS12 6EJ')
        await page.locator('#verify button').click();await expect(page.locator('#items')).to_contain_text('Fixture shirt')
        await page.locator('#unchanged').check();await page.locator('#confirm').click()
        await expect(page.locator('#label')).to_be_visible();await expect(page.locator('#qr')).to_be_visible()
        assert not errors,errors
        await browser.close()
    print(json.dumps({'platforms':24,'widths':[375,768,1366],'settings_save':True,'portal':True,'page_errors':errors}))

asyncio.run(main())
