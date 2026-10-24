"""Offline responsive branding checks using the real pages and static assets."""
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright
from tests import vercel_hosting_browser as hosting

ROOT=Path(__file__).resolve().parents[1]

async def check(origin: str) -> None:
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.playwright'))
    output=ROOT/'output/brand-qa';output.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page()
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        async def local_only(route):
            if route.request.url.startswith(origin):await route.continue_()
            else:await route.abort()
        await page.route('**/*',local_only)
        await page.goto(origin,wait_until='domcontentloaded')
        await page.wait_for_function("state.mode==='local-preview'")
        await page.evaluate("document.querySelector('#loginContainer').hidden=true;document.body.classList.remove('auth-locked');document.body.classList.add('auth-ready')")
        results=[]
        for role in ['OWNER','ADMIN','DISPATCHER','ACCOUNTANT']:
            await page.evaluate("role=>{portal.profile={tenant_id:'synthetic',workspace_role:role,portal_role:'CLIENT'};}",role)
            assert await page.locator('.topbar .brand-mark').is_visible()
        for width in [320,375,768,1440]:
            await page.set_viewport_size({'width':width,'height':900})
            logo=page.locator('.topbar .brand-mark')
            await logo.wait_for(state='visible')
            assert await logo.get_attribute('alt')=='EasyInvio.com'
            assert await logo.evaluate('(image)=>image.complete && image.naturalWidth>0')
            box=await logo.bounding_box()
            assert box and abs(box['height']-(30 if width<768 else 38))<.5,box
            assert box['x']>=0 and box['x']+box['width']<=width
            assert abs(box['width']/box['height']-96/112)<.01
            assert await page.locator('.topbar .brand').inner_text()==''
            results.append({'width':width,'logo_height':box['height'],'uncropped':True})
            if width in [320,1440]:await page.screenshot(path=str(output/f'header-{width}.png'))
        # Same vector on explicit dark and light surfaces; verify no decorative badge.
        await page.set_viewport_size({'width':640,'height':240})
        css=(ROOT/'brand.css').read_text(encoding='utf-8')
        await page.set_content('<style>'+css+'</style><div class="brand-on-dark" style="background:#020617;padding:30px;display:inline-block"><img class="brand-mark" src="'+origin+'/brand-mark.svg" alt="EasyInvio.com"></div><div class="brand-on-light" style="background:#fff;padding:30px;display:inline-block"><img class="brand-mark" src="'+origin+'/brand-mark.svg" alt="EasyInvio.com"></div>')
        await page.locator('img').last.wait_for()
        await page.wait_for_function('Array.from(document.images).every(image=>image.complete&&image.naturalWidth>0)')
        assert await page.locator('.brand-on-light img').evaluate('(image)=>getComputedStyle(image).filter')!='none'
        await page.screenshot(path=str(output/'surfaces.png'))
        await page.goto(origin+'/tracking.html',wait_until='domcontentloaded')
        assert await page.locator('header img').get_attribute('alt')=='EasyInvio.com'
        assert await page.locator('header img').evaluate('(image)=>image.complete&&image.naturalWidth>0')
        for name in ['brand-mark.svg','favicon.svg','favicon-32.png','apple-touch-icon.png','app-icon-192.png','app-icon-512.png','site.webmanifest','brand.css']:
            response=await page.request.get(origin+'/'+name)
            assert response.ok,(name,response.status)
        manifest=await (await page.request.get(origin+'/site.webmanifest')).json()
        assert {icon['sizes'] for icon in manifest['icons']}=={'192x192','512x512'}
        assert not errors,errors
        await browser.close()
        print(json.dumps({'branding':'passed','breakpoints':results,'surfaces':['dark','light'],'icons':'all eight assets served','javascript_errors':errors}))

if __name__=='__main__':
    hosting.check=check
    hosting.main()
