"""Offline browser acceptance: no database, provider or notification calls."""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright, expect
from backend.platform_registry import PLATFORMS

BASE='http://127.0.0.1:8017'
SID='00000000-0000-4000-8000-000000000057'

async def main():
    errors=[];saves=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        context=await browser.new_context(permissions=['clipboard-read','clipboard-write'])
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def api(route):
            path=route.request.url.split('/api/v1/')[1].split('?')[0]
            if path=='integration/platforms':value={'platforms':[v.model_dump() for v in PLATFORMS.values()]}
            elif path=='workspace/stores':value={'stores':[{'id':SID,'display_name':'Fixture retailer','platform':'CUSTOM_WEBSITE','is_active':True}]}
            elif path.endswith('/connection'):
                value={'configured':True,'api_key_id':'fixture-key-id','has_webhook_secret':False,'live_delivery':False,'store_url':'https://retailer.example.test','sku_unit_grams':{}}
                if route.request.method=='PUT':saves.append(route.request.post_data_json)
            elif path.endswith('/returns-portal'):value={'store_slug':'fixture-retailer','return_policy':{'enabled':False}}
            elif path in {'config','auth/config'}:value={'mode':'configured','supabase_url':None,'publishable_key':None}
            else:value={'stores':[],'orders':[],'shipments':[],'tickets':[],'history':[]}
            await route.fulfill(json=value)
        await page.route('**/api/v1/**',api)
        await page.goto(BASE+'/workspace')
        await page.evaluate("""()=>{document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;state.session={access_token:'fixture',expires_at:9999999999};portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'00000000-0000-4000-8000-000000000001'};setView('stores');}""")
        await expect(page.locator('#store-catalogue article')).to_have_count(24)
        await page.locator('[data-store-settings]').click()
        output=Path(__file__).resolve().parents[1]/'output'/'integration-experience'
        output.mkdir(parents=True,exist_ok=True)
        for width in [375,1366]:
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.locator('#store-connection').evaluate('(d)=>d.scrollWidth<=d.clientWidth+1')
            await page.locator('#store-connection').screenshot(path=str(output/f'connection-{width}.png'))
        form=page.locator('#store-connection-form')
        await expect(form.locator('[name=display_store_id]')).to_have_value(SID)
        await expect(form.locator('[name=display_key_id]')).to_have_value('fixture-key-id')
        await expect(form.locator('[name=shop_domain]')).not_to_be_visible()
        await expect(form.locator('[name=amazon_seller_id]')).not_to_be_visible()
        await expect(form.locator('[name=weights]')).not_to_be_visible()
        await form.locator('#store-generate-secret').click()
        secret=await form.locator('[name=webhook_secret]').input_value()
        assert len(secret)==64 and all(c in '0123456789abcdef' for c in secret)
        await form.locator('[data-copy-field=webhook_secret]').click()
        assert await page.evaluate('navigator.clipboard.readText()')==secret
        await form.locator('button[type=submit]').click()
        await expect(page.locator('#store-connection')).not_to_be_visible()
        assert len(saves)==1 and saves[0]['webhook_secret']==secret
        assert await form.locator('[name=webhook_secret]').input_value()==''
        for code in ['SHOPIFY','WOOCOMMERCE','AMAZON','EBAY','BIGCOMMERCE','WIX','MAGENTO','ETSY','CUSTOM_WEBSITE']:
            await page.evaluate("""async code=>{await configureStoreConnectionUI({id:'00000000-0000-4000-8000-000000000057',platform:code},{has_webhook_secret:false,live_delivery:false});document.getElementById('store-connection').showModal();}""",code)
            if code=='EBAY':
                await expect(form.locator('[name=rest_access_token]')).to_be_visible()
                await expect(form.locator('[name=webhook_secret]')).not_to_be_visible()
                await expect(form.locator('[name=weights]')).to_be_visible()
                await expect(form.locator('[name=live_delivery]')).to_be_visible()
            if code=='AMAZON':await expect(form.locator('[name=live_delivery]')).not_to_be_visible()
            if code=='WOOCOMMERCE':await expect(form.locator('[name=woo_secret]')).to_be_visible()
            if code=='SHOPIFY':await expect(form.locator('[name=shop_domain]')).to_be_visible()
            if code in ['ETSY','CUSTOM_WEBSITE']:await expect(form.locator('#store-quick-credentials')).to_be_visible()
            await page.locator('#store-connection > .close').click()
        output=Path(__file__).resolve().parents[1]/'output'/'integration-experience'
        output.mkdir(parents=True,exist_ok=True)
        for width in [375,768,1366]:
            await page.set_viewport_size({'width':width,'height':1000})
            await page.goto(BASE+'/')
            await expect(page.locator('[data-integration]')).to_have_count(29)
            await page.locator('[data-integration-filter="Marketplaces"]').click()
            await expect(page.locator('.integration-card[data-category]:visible')).to_have_count(7)
            await page.locator('[data-integration-filter="All"]').click()
            await page.locator('[data-integration=AMAZON]').click()
            await expect(page.locator('#integration-detail')).to_be_visible()
            await expect(page.locator('#integration-benefits')).to_contain_text('not implemented')
            await expect(page.locator('#integration-connect')).to_have_attribute('href','/login?mode=signup&channel=AMAZON')
            await page.keyboard.press('Escape')
            await expect(page.locator('#integration-detail')).not_to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            await page.locator('#integrations').screenshot(path=str(output/f'directory-{width}.png'))
            await page.goto(BASE+'/help/connect-custom-website')
            await expect(page.locator('#owners-panel')).to_be_visible()
            await page.locator('#developers-tab').click()
            await expect(page.locator('#developers-panel')).to_be_visible()
            await page.locator('#orders-tab-1').click()
            await expect(page.locator('#orders-1')).to_be_visible()
            await page.locator('#orders-1 .copy-code').click()
            assert 'urllib.request' in await page.evaluate('navigator.clipboard.readText()')
            await page.locator('#orders-tab-1').focus();await page.keyboard.press('ArrowRight')
            await expect(page.locator('#orders-2')).to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            await page.screenshot(path=str(output/f'help-{width}.png'),full_page=True)
        assert not errors,errors
        await browser.close()
    print(json.dumps({'platform_forms':9,'directory_cards':29,'widths':[375,768,1366],'secret_generation_copy_save':True,'docs_tabs_copy_keyboard':True,'page_errors':errors}))

if __name__=='__main__':asyncio.run(main())
