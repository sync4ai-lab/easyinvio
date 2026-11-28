"""Offline pricing-page regression; all HTTP traffic is intercepted locally."""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect

ROOT=Path(__file__).resolve().parents[1]

async def main():
    errors=[]
    async with async_playwright() as driver:
        browser=await driver.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge'))
        page=await browser.new_page(viewport={'width':1440,'height':950})
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def route(request):
            url=urlsplit(request.request.url)
            if url.hostname!='pricing.test':return await request.abort()
            if url.path=='/api/v1/public/session':return await request.fulfill(json={'authenticated':False})
            if url.path=='/pricing':
                return await request.fulfill(body=(ROOT/'frontend/landing/pricing.html').read_bytes(),content_type='text/html')
            path=ROOT/url.path.lstrip('/')
            if path.is_file() and path.suffix in {'.js','.css','.svg'}:
                return await request.fulfill(body=path.read_bytes(),content_type={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}[path.suffix])
            return await request.fulfill(status=404,body='Not found')
        await page.route('**/*',route)
        await page.goto('https://pricing.test/pricing')
        assert await page.locator('.tier').count()==3
        assert await page.locator('.comparison-table .category').count()==7
        await expect(page.locator('[data-plan-price="velocity"]')).to_have_text('£25')
        await expect(page.locator('[data-plan-price="command"]')).to_have_text('£75')
        assert await page.locator('#estimator,#parcel-volume,#net-saving,.soon').count()==0
        assert await page.locator('body').evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(255, 255, 255)'
        assert 'Planned' not in await page.locator('.tiers').inner_text()
        assert '30-day postpaid billing' not in await page.locator('.tiers').inner_text()
        await page.locator('#billing-annual').click()
        await expect(page.locator('[data-plan-price="velocity"]')).to_have_text('£20')
        await expect(page.locator('[data-plan-price="command"]')).to_have_text('£60')
        await expect(page.locator('[data-bill-detail="velocity"]')).to_contain_text('£240.00')
        await expect(page.locator('[data-bill-detail="command"]')).to_contain_text('£720.00')
        await expect(page.locator('[data-compare-price="velocity"]')).to_have_text('£20')
        for width in [375,768,1440]:
            await page.set_viewport_size({'width':width,'height':950})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            table=page.locator('.comparison-scroll')
            await table.scroll_into_view_if_needed()
            await table.evaluate('(el)=>el.scrollTop=500')
            header=await page.locator('.comparison-table thead').bounding_box()
            cell=await page.locator('.comparison-table thead th').first.bounding_box()
            bounds=await table.bounding_box()
            assert abs(cell['y']-bounds['y'])<3,(width,cell,bounds)
            await table.evaluate('(el)=>el.scrollTop=0')
        await page.locator('#billing-annual').click()
        assert await page.locator('[data-plan-link="velocity"]').first.get_attribute('href')=='/login?mode=signup&plan=velocity&cycle=annual'
        output=ROOT/'output/pricing-qa'
        output.mkdir(parents=True,exist_ok=True)
        await page.set_viewport_size({'width':1440,'height':1000});await page.evaluate('scrollTo(0,0)');await page.screenshot(path=str(output/'pricing-hero.png'))
        for width in [1440,375]:
            await page.set_viewport_size({'width':width,'height':950})
            await page.evaluate('scrollTo(0,0)')
            await page.screenshot(path=str(output/f'pricing-{width}.png'),full_page=True)
        assert not errors,errors
        await browser.close()
    print('Pricing browser checks passed: prices, annual totals, shared daylight theme, removed calculator/planned features, sticky table, signup links and three viewport sizes.')

if __name__=='__main__':asyncio.run(main())
