"""Browser identity flow with controlled API responses; never submits real passwords."""
import asyncio,json,os,time
from pathlib import Path
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())

async def run():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        page=await browser.new_page(viewport={'width':1366,'height':900})
        profile={'user_id':'117d268d-b034-4a74-ad4d-050813bf67ac','email':'satyakishore.mavuri@gmail.com','role':'SUPER_ADMIN','full_name':'Browser Test','phone_e164':None}
        async def mock(route):
            path=route.request.url.split('/api/v1/',1)[1]
            if path=='auth/token':data={'access_token':'controlled.identity.fixture','expires_at':int(time.time())+600,'user':{'email':profile['email']}}
            elif path=='profile':data={'portal_role':'SUPER_ADMIN','user_id':profile['user_id'],'tenant_id':None}
            elif path=='auth/me':
                if route.request.method=='PATCH':profile.update(route.request.post_data_json);data={'updated':True}
                else:data=profile
            elif path=='auth/logout':data={'logged_out':True}
            else:data={'active_tenants':0,'totals_by_currency':[],'carriers':[],'billing_pipeline':[],'payment_pipeline':[],'active_support':[],'tickets':[],'shipments':[],'transactions':[],'tenants':[],'environment':'SANDBOX'}
            await route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        await page.route('**/api/v1/auth/**',mock)
        await page.route('**/api/v1/profile',mock)
        await page.route('**/api/v1/admin/**',mock)
        await page.goto('http://127.0.0.1:8000',wait_until='domcontentloaded')
        await expect(page.locator('#loginContainer')).to_be_visible()
        await expect(page.locator('.app-shell')).not_to_be_visible()
        for width in [375,768,1366]:
            await page.set_viewport_size({'width':width,'height':900})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        await page.set_viewport_size({'width':1366,'height':900})
        Path('docs/identity').mkdir(parents=True,exist_ok=True)
        await page.wait_for_timeout(400)
        await page.screenshot(path='docs/identity/login.png')
        await page.locator('#identity-email').fill(profile['email'])
        await page.locator('#identity-password').fill('controlled-password-fixture')
        await page.locator('#identity-login-submit').click()
        await expect(page.locator('#loginContainer')).not_to_be_visible()
        await expect(page.locator('.app-shell')).to_be_visible()
        assert await page.evaluate("!!localStorage.getItem('easyinvio.session')")
        await page.locator('#identity-avatar').click()
        await expect(page.locator('#profile')).to_be_visible()
        await expect(page.locator('#identity-role')).to_contain_text('Platform Super-Admin')
        await page.locator('#identity-profile-form [name="full_name"]').fill('Updated Browser Test')
        await page.locator('#identity-profile-form [name="phone_e164"]').fill('+447700900123')
        await page.locator('#identity-profile-form button').click()
        await expect(page.locator('#identity-profile-form [name="full_name"]')).to_have_value('Updated Browser Test')
        await page.reload(wait_until='domcontentloaded')
        await expect(page.locator('#loginContainer')).not_to_be_visible()
        await page.locator('#identity-logout').click()
        await expect(page.locator('#loginContainer')).to_be_visible()
        await expect(page.locator('.app-shell')).not_to_be_visible()
        assert await page.evaluate("localStorage.getItem('easyinvio.session')===null && state.session===null")
        await browser.close()
    print('PASS: exclusive login gate, responsive layout, controlled login, verified role badge, profile edit, reload restoration, logout clears storage/memory. No real password or provider calls.')

if __name__=='__main__':asyncio.run(run())
