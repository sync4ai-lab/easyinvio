"""Offline store registration -> credentials -> read-only verification acceptance."""
import asyncio,json,sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.platform_registry import PLATFORMS
SID='00000000-0000-4000-8000-000000000059'

async def main():
    stores=[];calls=[];errors=[];eligible=False;verify=False
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge')
        page=await browser.new_page(viewport={'width':1366,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def route(r):
            url=urlsplit(r.request.url);path=url.path
            if url.hostname!='stores.test':return await r.abort()
            if path=='/workspace':return await r.fulfill(path=str(ROOT/'index.html'),content_type='text/html')
            if path.startswith('/api/'):
                calls.append((path,r.request.method))
                if path=='/api/v1/integration/platforms':data={'platforms':[v.model_dump() for v in PLATFORMS.values()]}
                elif path=='/api/v1/workspace/stores':
                    if r.request.method=='POST':
                        if not eligible:return await r.fulfill(status=402,json={'detail':{'code':'PLAN_QUOTA_EXCEEDED','quota':'STORES','limit':0,'current_plan':'STARTER'}})
                        data={'id':SID,**r.request.post_data_json,'is_active':True};stores.append(data)
                    else:data={'stores':stores}
                elif path.endswith('/connection'):
                    data={'configured':False,'sku_unit_grams':{}}
                    if r.request.method=='PUT':
                        body=r.request.post_data_json
                        assert body['shop_domain']=='easyinvio-qa.myshopify.com'
                        assert body['authorization_mode']=='CLIENT_CREDENTIALS'
                        assert body['live_import'] is True
                        assert body['live_delivery'] is False and body['live_returns'] is False
                        assert body['sku_unit_grams']=={'EI-TEE':'200'}
                        data={'configured':True}
                        stores[0]['connection_saved']=True
                elif path.endswith('/test-connection'):
                    if not verify:return await r.fulfill(status=503,json={'detail':'Shopify authorization failed. Check installation and app ownership.'})
                    data={'verified':True,'store_name':'EasyInvio QA','scope':'Read-only shop access; write scopes and webhook delivery are not tested'}
                elif path.endswith('/returns-portal'):data={'store_slug':None,'return_policy':{'enabled':False}}
                elif path.endswith('/sync/'+SID):data={'results':[],'notice':'No unfulfilled orders to import.'}
                elif path.endswith('/config'):data={'mode':'configured'}
                else:data={'stores':[],'orders':[],'shipments':[],'tickets':[],'history':[]}
                return await r.fulfill(json=data)
            file=ROOT/path.lstrip('/')
            if file.is_file() and file.suffix in {'.js','.css','.svg','.png','.webmanifest'}:return await r.fulfill(path=str(file))
            await r.abort()
        await page.route('**/*',route)
        await page.goto('https://stores.test/workspace',wait_until='domcontentloaded')
        await page.evaluate("""()=>{document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;
          state.session={access_token:'synthetic',expires_at:9999999999};portal.role='CLIENT';
          portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'00000000-0000-4000-8000-000000000001'};
          ensureActiveIdentitySession=async()=>state.session;setView('stores');}""")
        await expect(page.locator('[data-store-connect=SHOPIFY]')).to_be_visible()
        await page.locator('[data-store-connect=SHOPIFY]').click()
        await page.locator('#store-admin-form [name=display_name]').fill('EasyInvio QA Shopify')
        await page.locator('#store-admin-form button.primary').click()
        await expect(page.locator('#store-registration-status')).to_contain_text('plan’s store connection limit')
        await expect(page.locator('#store-registration-plan')).to_be_visible()
        assert stores==[]
        eligible=True
        await page.locator('#store-admin-form button.primary').click()
        await expect(page.locator('#store-admin-dialog')).not_to_be_visible()
        await expect(page.locator('#store-connection')).to_be_visible()
        await expect(page.locator('#store-connection-title')).to_have_text('Connect EasyInvio QA Shopify')
        form=page.locator('#store-connection-form')
        await form.locator('[name=shop_domain]').fill('easyinvio-qa.myshopify.com')
        await form.locator('[name=authorization_mode]').select_option('CLIENT_CREDENTIALS')
        await form.locator('[name=client_id]').fill('synthetic-client-id')
        await form.locator('[name=client_secret]').fill('synthetic-private-secret')
        await form.locator('[name=weights]').fill('EI-TEE = 200')
        await form.locator('button[type=submit]').click()
        await expect(page.locator('#store-connection-status')).to_contain_text('Shopify verification failed')
        await expect(page.locator('#store-connection')).to_be_visible()
        assert await form.locator('[name=client_secret]').input_value()==''
        verify=True
        await form.locator('[name=client_secret]').fill('synthetic-corrected-secret')
        for width in [390,1366]:
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.locator('#store-connection').evaluate('(d)=>d.scrollWidth<=d.clientWidth+1')
        await form.locator('button[type=submit]').click()
        await expect(page.locator('#store-connection')).not_to_be_visible()
        await expect(page.locator('#store-sync-result')).to_contain_text('Shopify read access verified')
        assert len(stores)==1
        await page.locator('[data-store-sync]').click()
        await expect(page.locator('#store-sync-result')).to_contain_text('No unfulfilled orders')
        assert not any('purchase' in path or 'booking' in path for path,_ in calls)
        assert not errors,errors
        await browser.close()
    print('PASS: visible Starter quota error, direct registration handoff, credential form, verification failure/retry, cleared secrets, responsive layout and separate order retrieval. Offline only.')

if __name__=='__main__':asyncio.run(main())
