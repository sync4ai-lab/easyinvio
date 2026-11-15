"""Isolated public/workspace navigation QA. All APIs and sessions are synthetic."""
import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.playwright'))

async def main():
    output=ROOT/'output/public-experience-qa';output.mkdir(parents=True,exist_ok=True)
    signed=False
    errors=[]
    requests=[]
    profile={'user_id':'00000000-0000-4000-8000-000000000001','email':'tester@example.invalid','role':'SUPER_ADMIN','full_name':'Test Operator','phone_e164':None}
    async with async_playwright() as driver:
        browser=await driver.chromium.launch()
        context=await browser.new_context(viewport={'width':1440,'height':1000})
        page=await context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        def session():return {'access_token':'synthetic-session','expires_at':int(time.time())+900,'absolute_expires_at':int(time.time())+28800,'user':{'id':profile['user_id'],'email':profile['email']}}
        async def handler(route):
            nonlocal signed
            path=urlsplit(route.request.url).path
            if urlsplit(route.request.url).hostname!='experience.test':return await route.abort()
            if path in {'/','/index.html'}:return await route.fulfill(body=(ROOT/'frontend/landing/index.html').read_text(encoding='utf-8'),content_type='text/html')
            if path in {'/login','/workspace'}:return await route.fulfill(body=(ROOT/'index.html').read_text(encoding='utf-8'),content_type='text/html')
            if path.startswith('/api/') or path=='/health':
                requests.append(path)
                if path=='/health':data={'status':'ok','mode':'configured'}
                elif path=='/api/v1/config':data={'mode':'configured','supabase_url':None,'publishable_key':None}
                elif path=='/api/v1/public/session':data={'authenticated':signed,'name':'Test Operator'}
                elif path=='/api/v1/auth/browser-session/restore':
                    if not signed:return await route.fulfill(status=401,json={'detail':'Sign in'})
                    data=session()
                elif path=='/api/v1/auth/token':signed=True;data=session()
                elif path in {'/api/v1/auth/logout','/api/v1/public/session/logout'}:signed=False;data={'logged_out':True}
                elif path=='/api/v1/auth/me':data=profile
                elif path=='/api/v1/profile':data={'portal_role':'SUPER_ADMIN','user_id':profile['user_id'],'tenant_id':None}
                elif path=='/api/v1/public/assistance':
                    query=route.request.post_data_json['query'];private='my shipment' in query
                    data={'answer':'Open your workspace for shipment details.' if private else 'Published Amazon setup instructions. <script>unsafe()</script>','sources':[{'title':'Help Centre','url':'/help'}],'requires_login':private}
                elif path=='/api/v1/conversational/process-message':data={'status':'COMPLETED','conversational_reply':'Workspace guidance'}
                else:data={'active_tenants':0,'totals_by_currency':[],'carriers':[],'billing_pipeline':[],'payment_pipeline':[],'active_support':[],'tickets':[],'shipments':[],'transactions':[],'tenants':[],'environment':'SANDBOX'}
                return await route.fulfill(json=data)
            file=ROOT/path.lstrip('/')
            if file.is_file() and file.suffix in {'.js','.css','.svg'}:
                return await route.fulfill(body=file.read_bytes(),content_type={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}[file.suffix])
            return await route.fulfill(status=404,body='Not found')
        await page.route('**/*',handler)
        await page.goto('https://experience.test/')
        await expect(page.locator('#public-signin')).to_be_visible()
        assert await page.locator('.nav .brand-mark').get_attribute('src')=='/brand-mark.svg'
        assert await page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(15, 23, 42)'
        await page.locator('#ai-open').click()
        await page.locator('#ai-question').fill('How can I add Amazon for shipping?')
        await page.locator('#ai-form button').click()
        await expect(page.locator('#public-chat-log')).to_contain_text('Published Amazon')
        assert await page.locator('#public-chat-log script').count()==0
        await page.screenshot(path=str(output/'public-chat.png'))
        await page.locator('#ai-question').fill('Track my shipment')
        await page.locator('#ai-form button').click()
        await expect(page.locator('#public-chat-log')).to_contain_text('Open your workspace')
        await page.locator('#ai-close').click()
        allowed={'/health','/api/v1/config','/api/v1/public/session','/api/v1/public/assistance'}
        assert set(requests)<=allowed,requests
        await page.screenshot(path=str(output/'landing-desktop.png'),full_page=True)
        for width in [375,768,1440]:
            await page.set_viewport_size({'width':width,'height':950})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        await page.set_viewport_size({'width':375,'height':950})
        await page.screenshot(path=str(output/'landing-mobile.png'),full_page=True)
        await page.set_viewport_size({'width':1440,'height':1000})
        await page.goto('https://experience.test/login')
        await expect(page.locator('#loginContainer')).to_be_visible()
        await page.locator('#identity-email').fill(profile['email'])
        await page.locator('#identity-password').fill('synthetic-password')
        await page.locator('#identity-login-submit').click()
        await expect(page.locator('#loginContainer')).to_be_hidden()
        await page.locator('.sidebar a[href="/"]').click()
        await expect(page.locator('#public-account-name')).to_contain_text('Test Operator')
        await expect(page.locator('#public-signin')).to_be_hidden()
        await page.screenshot(path=str(output/'signed-in-landing.png'))
        for width in [375,768,1024,1440]:
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Signed-in overflow at {width}'
        await page.set_viewport_size({'width':1440,'height':1000})
        assert await page.evaluate("localStorage.getItem('easyinvio.session')===null")
        await page.locator('#public-account summary').click()
        await page.locator('#public-account a').click()
        await expect(page.locator('#loginContainer')).to_be_hidden()
        await expect(page.locator('#identity-avatar')).to_be_visible()
        await page.reload()
        await expect(page.locator('#identity-avatar')).to_be_visible()
        await page.locator('#conversation-open').click()
        await expect(page.locator('#conversation-title')).to_have_text('Ask EasyInvio')
        await page.locator('#conversation-close').click()
        await page.locator('#identity-logout').click()
        await page.wait_for_url('https://experience.test/')
        await expect(page.locator('#public-signin')).to_be_visible()
        assert not signed
        # A separately signed-in browser can also sign out directly on the landing page.
        signed=True;await page.reload()
        await expect(page.locator('#public-account-name')).to_contain_text('Test Operator')
        await page.locator('#public-account summary').click();await page.locator('#public-logout').click()
        await expect(page.locator('#public-signin')).to_be_visible();assert not signed
        assert not errors,errors
        report={'passed':True,'page_errors':errors,'checks':['matching brand and palette','anonymous public requests only','public chat, account gate and text-only output','mobile overflow checks','login to landing preserves verified identity','workspace session restores on navigation and reload','workspace and landing logout return home','shared Ask EasyInvio title','no token in localStorage']}
        (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
        await browser.close()

if __name__=='__main__':asyncio.run(main())
