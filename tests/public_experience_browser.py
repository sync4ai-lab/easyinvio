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
    preview=False
    session_gate=asyncio.Event();session_gate.set()
    restore_gate=asyncio.Event();restore_gate.set()
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
                if path=='/health':data={'status':'ok','mode':'local-preview' if preview else 'configured'}
                elif path=='/api/v1/config':data={'mode':'local-preview' if preview else 'configured','supabase_url':None,'publishable_key':None}
                elif path=='/api/v1/public/tracking/resolve':
                    assert route.request.post_data_json=={'token':'A'*40}
                    data={'shipments':[{'order_reference':'DEMO-TRACK','carrier':'Synthetic Carrier','status':'IN_TRANSIT','tracking_number':'DEMO123'}]}
                elif path=='/api/v1/public/session':
                    await session_gate.wait()
                    data={'authenticated':signed,'name':'Test Operator'}
                elif path=='/api/v1/auth/browser-session/restore':
                    await restore_gate.wait()
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
        # New landing interactions use synthetic data and never purchase a label.
        assert await page.locator('#nav-ask').count()==0
        assert await page.locator('#solutions-toggle,#solutions-menu,#rate-tab,#rate-panel').count()==0
        await page.locator('[data-demo-confirm]').click()
        await expect(page.locator('.demo-confirmation')).to_be_visible()
        await expect(page.locator('.phone-thread')).to_contain_text('Demo expiry: 09:46')
        await expect(page.locator('.phone-thread')).to_contain_text('estimated 2–3 working days')
        assert await page.locator('#integrations .brand-badge').count()==13
        assert await page.locator('#integrations').count()==1
        assert await page.locator('.ecosystem-strip,.savings-calculator,#parcel-volume').count()==0
        assert 'Conversational execution' not in await page.locator('.hero').inner_text()
        assert 'Model your own postage comparison' not in await page.locator('#pricing').inner_text()
        assert await page.locator('#pricing .price-card').count()==2
        for key in ['royalmail','evri','dpd','dhl','ups','shopify','amazon','woocommerce','whatsapp','easypost','shippo','sendcloud','gupshup']:
            assert await page.locator(f'#integrations .ecosystem-grid use[href="#brand-{key}"]').count()==1
        assert await page.locator('.brand-sprite symbol').count()==13
        assert await page.locator('#integrations .ecosystem-group').count()==3
        assert await page.locator('.logo-run:not([aria-hidden]) .marquee-brand').count()==13
        assert await page.locator('.logo-run[aria-hidden="true"]').count()==1
        await page.locator('#logo-pause').click()
        await expect(page.locator('#ecosystem-motion')).to_have_attribute('data-paused','true')
        assert await page.locator('.logo-track').evaluate('(e)=>getComputedStyle(e).animationPlayState')=='paused'
        await page.locator('#logo-pause').click()
        await expect(page.locator('#logo-pause')).to_have_text('Pause logos')
        await page.emulate_media(reduced_motion='reduce')
        assert await page.locator('.logo-track').evaluate('(e)=>getComputedStyle(e).animationName')=='none'
        await page.emulate_media(reduced_motion='no-preference')
        assert await page.locator('.outcome-card').count()==3
        assert await page.locator('.operation').count()==9
        assert await page.locator('#intelligence .ai-service-card').count()==3
        await page.locator('[data-open-assistant]').click()
        await expect(page.locator('#ai-title')).to_have_text('Ask EasyInvio')
        await page.locator('#ai-close').click()
        await page.locator('[data-show-workflow="3"]').click()
        await expect(page.locator('#pillar-panel')).to_have_attribute('aria-labelledby','pillar-3')
        await page.locator('[data-show-workflow="0"]').click()
        await expect(page.locator('#pillar-panel')).to_have_attribute('aria-labelledby','pillar-0')
        await expect(page.locator('#analytics-chart')).to_contain_text('144 packages')
        await page.locator('#analytics-tab-spend').click()
        await expect(page.locator('#analytics-chart')).to_contain_text('£792')
        await expect(page.locator('#analytics-chart')).to_have_attribute('aria-labelledby','analytics-tab-spend')
        await page.locator('#analytics-tab-spend').press('ArrowLeft')
        await expect(page.locator('#analytics-tab-volume')).to_be_focused()
        await expect(page.locator('#analytics-chart')).to_contain_text('144 packages')
        assert 'fictional' in await page.locator('.analytics-demo-note').text_content()
        for target in ['services','intelligence','analytics']:
            await page.locator(f'.capability-jumps a[href="#{target}"]').click()
            await page.wait_for_timeout(1100)
            gap=await page.locator(f'#{target} .eyebrow').first.evaluate('(e)=>e.getBoundingClientRect().top-document.querySelector("#nav").getBoundingClientRect().bottom')
            assert 10<=gap<=75,(target,gap)


        assert await page.locator('.feedback-card').count()==8
        for card in await page.locator('.feedback-card').all():
            assert 'Not a customer review' in await card.text_content()
            assert 'fictional' in await card.inner_text()
        assert await page.locator('script[type="application/ld+json"]').count()==0

        assert await page.locator('.brand-sprite script,.brand-sprite foreignObject,.brand-sprite image').count()==0
        assert await page.locator('.brand-sprite [onload],.brand-sprite [onclick]').count()==0
        await expect(page.locator('#public-workspace')).to_be_hidden()
        await expect(page.locator('#public-register')).to_be_visible()
        for target in ['pricing','integrations']:
            await page.locator(f'.nav-links a[href="#{target}"]').click()
            await page.wait_for_timeout(1100)
            gap=await page.locator(f'#{target} .eyebrow').first.evaluate('(e)=>e.getBoundingClientRect().top-document.querySelector("#nav").getBoundingClientRect().bottom')
            assert 10<=gap<=75,(target,gap)
        assert await page.locator('#hero-rate,#rate-form,.widget-top,.hero [data-signup-cta]').count()==0
        await expect(page.locator('#track-title')).to_have_text('Track a Parcel')
        await page.locator('#track-input').fill('12345')
        await page.locator('#track-form button').click()
        await expect(page.locator('#track-result')).to_contain_text('complete secure tracking link')
        await page.locator('#track-input').fill('A'*40)
        await page.locator('#track-form button').click()
        await expect(page.locator('#track-result')).to_contain_text('DEMO-TRACK')
        await expect(page.locator('#track-input')).to_have_value('')
        for index in range(5):
            await page.locator(f'#pillar-{index}').click()
            await expect(page.locator('#pillar-panel')).to_have_attribute('aria-labelledby',f'pillar-{index}')
            await expect(page.locator('.product-demo')).to_be_visible()
        await page.locator('[data-currency="EUR"]').click()
        await expect(page.locator('#demo-wallet')).to_have_text('€95.70')
        await expect(page.locator('[data-currency="EUR"]')).to_have_attribute('aria-pressed','true')
        faqs=page.locator('.faq-list details')
        assert await faqs.count()==5
        await faqs.nth(0).locator('summary').click()
        await expect(faqs.nth(0)).to_have_attribute('open','')
        await faqs.nth(1).locator('summary').click()
        await expect(faqs.nth(0)).not_to_have_attribute('open','')
        await faqs.nth(1).locator('summary').click()
        await page.locator('#pillar-0').click()
        await page.set_viewport_size({'width':375,'height':950})
        await page.locator('#menu').click()
        await expect(page.locator('#public-register')).to_be_visible()
        await page.locator('#menu').click()
        await expect(page.locator('#menu')).to_have_attribute('aria-expanded','false')
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), await page.evaluate("[...document.querySelectorAll('.wrap,.hero-grid,.pillar-grid,.pillar-menu,.console,.feedback-grid,.operations-grid,.operation,.feedback-section')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&getComputedStyle(e).position!=='fixed').slice(0,18).map(e=>[e.tagName,e.className.baseVal||e.className,e.getBoundingClientRect().width,e.getBoundingClientRect().right])")
        await page.set_viewport_size({'width':1440,'height':1000})
        await page.locator('#pillar-0').click()
        await page.locator('#ai-open').click()
        await page.locator('[data-prompt]').first.click()
        await expect(page.locator('#public-chat-log')).to_contain_text('Published Amazon')
        await page.locator('#ai-close').click()
        await page.evaluate('scrollTo(0,0)')
        await page.locator('#ai-open').click()
        await page.locator('#ai-question').fill('How can I add Amazon for shipping?')
        await page.locator('#ai-form button').click()
        await expect(page.locator('#public-chat-log')).to_contain_text('Published Amazon')
        assert await page.locator('#public-chat-log script').count()==0
        await page.screenshot(path=str(output/'public-chat.png'))
        await page.locator('#ai-question').fill('Track my shipment')
        await page.locator('#ai-form button').click()
        await expect(page.locator('#public-chat-log')).to_contain_text('Sign in for account help')
        await page.locator('#ai-close').click()
        allowed={'/health','/api/v1/config','/api/v1/public/session','/api/v1/public/assistance','/api/v1/public/tracking/resolve'}
        assert set(requests)<=allowed,requests
        await page.locator('#intelligence').screenshot(path=str(output/'ai-services-desktop.png'))
        await page.locator('#analytics').screenshot(path=str(output/'analytics-desktop.png'))
        await page.locator('#services').screenshot(path=str(output/'services-desktop.png'))
        await page.locator('#integrations').screenshot(path=str(output/'integrations-desktop.png'))
        await page.evaluate("document.activeElement.blur(); document.getElementById('track-result').hidden=true; scrollTo({top:0,behavior:'instant'})")
        await page.wait_for_timeout(200)
        await page.screenshot(path=str(output/'landing-desktop.png'),full_page=True)
        await page.screenshot(path=str(output/'landing-hero.png'))
        for width in [375,768,1440]:
            await page.set_viewport_size({'width':width,'height':950})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        await page.set_viewport_size({'width':375,'height':950})
        await page.evaluate("scrollTo({top:0,behavior:'instant'})")
        await page.screenshot(path=str(output/'landing-mobile.png'),full_page=True)
        await page.screenshot(path=str(output/'landing-mobile-hero.png'))
        assert await page.locator('.feedback-grid').evaluate('(e)=>e.scrollWidth>e.clientWidth')
        await page.locator('#intelligence').screenshot(path=str(output/'ai-services-mobile.png'))
        await page.locator('#analytics').screenshot(path=str(output/'analytics-mobile.png'))
        await page.set_viewport_size({'width':1440,'height':1000})
        await page.locator('#public-register').click()
        await expect(page.locator('#identity-signup-form')).to_be_visible()
        await expect(page.locator('#identity-onboarding-intent')).to_have_value('')
        await expect(page.locator('#identity-onboarding-hint')).to_contain_text('change your workflow')
        # URL intent never controls the Business/Personal account type or authorizes work.
        await expect(page.locator('[data-signup-persona="BUSINESS"]')).to_have_attribute('aria-pressed','true')
        await expect(page.locator('#loginContainer h1')).to_have_text('Create an account')
        await expect(page.locator('#identity-login-form')).to_be_hidden()
        await page.locator('#identity-signup-back').click()
        await page.goto('https://experience.test/login?mode=signup&persona=%3Cscript%3Ebad%3C/script%3E')
        await expect(page.locator('#identity-signup-form')).to_be_visible()
        await expect(page.locator('#identity-onboarding-intent')).to_have_value('')
        assert await page.locator('#identity-onboarding-hint script').count()==0
        await page.goto('https://experience.test/login?mode=signin&persona=dispatch')
        await expect(page.locator('#identity-signup-form')).to_be_hidden()
        await expect(page.locator('#loginContainer')).to_be_visible()
        await page.locator('#identity-email').fill(profile['email'])
        await page.locator('#identity-password').fill('synthetic-password')
        await page.locator('#identity-login-submit').click()
        await expect(page.locator('#loginContainer')).to_be_hidden()
        assert await page.locator('.sidebar a[href="/"]').count()==0
        await page.locator('#identity-avatar').hover()
        await expect(page.locator('#identity-account-menu')).to_be_visible()
        await page.locator('#identity-profile-link').click()
        await expect(page.locator('#profile')).to_be_visible()
        await page.locator('#identity-avatar').focus()
        await page.keyboard.press('ArrowDown')
        await expect(page.locator('#identity-profile-link')).to_be_focused()
        await page.keyboard.press('Escape')
        await expect(page.locator('#identity-account-menu')).to_be_hidden()
        await page.locator('#identity-avatar').click()
        session_gate.clear()
        await page.locator('#identity-home-link').click()
        await expect(page.locator('#public-session-status')).to_be_visible()
        await expect(page.locator('#public-signin')).to_be_hidden()
        await expect(page.locator('#public-register')).to_be_hidden()
        session_gate.set()
        await expect(page.locator('#public-account-name')).to_contain_text('Test Operator')
        await expect(page.locator('#public-signin')).to_be_hidden()
        await page.screenshot(path=str(output/'signed-in-landing.png'))
        for width in [375,768,1024,1440]:
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Signed-in overflow at {width}'
        await page.set_viewport_size({'width':1440,'height':1000})
        assert await page.evaluate("localStorage.getItem('easyinvio.session')===null")
        await page.locator('#public-account summary').click()
        restore_gate.clear()
        await page.locator('#public-account a').click()
        await expect(page.locator('#identity-session-loading')).to_be_visible()
        await expect(page.locator('#loginContainer')).to_be_hidden()
        restore_gate.set()
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
        await page.locator('#public-account summary').click()
        async with page.expect_navigation(wait_until='load'):
            await page.locator('#public-logout').click()
        await expect(page.locator('#public-signin')).to_be_visible();assert not signed
        preview=True
        await page.goto('https://experience.test/')
        await expect(page.locator('#track-form')).to_be_visible()
        assert await page.locator('#rate-panel,#solutions-toggle').count()==0
        await expect(page.locator('#public-signin')).to_be_visible()
        await expect(page.locator('#public-workspace')).to_be_hidden()
        assert not errors,errors
        report={'passed':True,'page_errors':errors,'checks':['avatar menu hover, click and keyboard navigation','delayed session checks never show sign-in forms','direct account creation links','compact anchor spacing and no duplicate hero controls','tracking-only hero and removed Solutions navigation','secure public tracking resolves correctly','sanitized local brand SVGs and interactive illustrative phone demo','five visual showroom tabs and wallet currencies','single grouped integration directory and clear pricing cards','pausable integration marquee and reduced-motion alternative','three concrete outcome cards and nine shipping services','AI guidance cards and public assistant launch','illustrative analytics tabs, keyboard access and no private reporting requests','eight individually labelled fictional feedback examples','five accessible FAQs and assistant quick prompts','matching brand and palette','anonymous public requests only','public chat, account gate and text-only output','mobile overflow checks','login to landing preserves verified identity','workspace session restores on navigation and reload','workspace and landing logout return home','shared Ask EasyInvio title','no token in localStorage']}
        (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
        await browser.close()

if __name__=='__main__':asyncio.run(main())
