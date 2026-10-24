"""Offline admin strategy control and budget badge rendering."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())
from playwright.async_api import async_playwright
from scripts.build_vercel import ASSETS


async def run():
    html = Path('index.html').read_text(encoding='utf-8')
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        errors = []
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def route(request_route):
            if request_route.request.url.startswith('https://strategy.test/'):
                if urlsplit(request_route.request.url).path == '/':
                    return await request_route.fulfill(content_type='text/html',body=html)
                asset=urlsplit(request_route.request.url).path.lstrip('/')
                if asset in ASSETS:return await request_route.fulfill(path=str(Path(asset)))
                data = {'mode':'local-preview'} if urlsplit(request_route.request.url).path == '/api/v1/config' else {}
                return await request_route.fulfill(content_type='application/json',body=json.dumps(data))
            await request_route.abort()
        await page.route('**/*',route)
        await page.goto('https://strategy.test/',wait_until='domcontentloaded')
        await page.evaluate('''() => {
            document.body.classList.remove('auth-locked');
            document.querySelector('#loginContainer').hidden=true;
            state.session={access_token:'synthetic'};
            portal.role='SUPER_ADMIN';portal.profile={portal_role:'SUPER_ADMIN'};
            window.strategyRequests=[];
            window.testTenants=[{tenant_id:'business-test',company_name:'Business QA',workspace_type:'BUSINESS',seller_classification:'STANDARD'},
                {tenant_id:'personal-test',company_name:'Personal QA',workspace_type:'INDIVIDUAL',seller_classification:'STANDARD'}];
            enterprise.tenants=testTenants;
            enterprise.carriers=[];enterprise.margins=[];enterprise.transactions=[];
            api=async(path,options)=>{
                if(options?.method==='PATCH') {
                    strategyRequests.push({path,body:options.body});
                    testTenants[0].seller_classification=options.body.seller_classification;
                    return {updated:true};
                }
                if(path.endsWith('/tenants'))return {tenants:testTenants};
                if(path.split('?')[0].endsWith('/transactions'))return {transactions:[]};
                return {};
            };
            renderEnterpriseTables();
            document.querySelector('[data-seller-choice="business-test"]').value='HIGH_VOLUME_COST_SENSITIVE_SELLER';
            document.querySelector('[data-seller-strategy="business-test"]').click();
        }''')
        await page.wait_for_function('strategyRequests.length===1')
        request = await page.evaluate('strategyRequests[0]')
        assert request['path'] == '/api/v1/admin/tenants/business-test/seller-classification'
        assert request['body']['seller_classification'] == 'HIGH_VOLUME_COST_SENSITIVE_SELLER'
        assert await page.locator('[data-seller-strategy="personal-test"]').count()==0
        assert 'Automatic for personal accounts' in await page.locator('#tenant-rows').text_content()
        await page.evaluate('''() => {
            const rate={offer_id:'synthetic-offer',carrier_code:'EVRI',service_code:'STANDARD',currency:'GBP',client_price_ex_tax:'4.50',
                recommendation_badge:'EasyInvio Budget Choice \\u2022 Optimized low-cost e-commerce delivery lane'};
            state.quotes=[rate];renderRates({rates:[rate],partial:false});
        }''')
        assert 'EasyInvio Budget Choice' in await page.locator('#rates').text_content()
        assert not errors,errors
        await browser.close()
    print('PASS: explicit admin preference, automatic personal preference and visible budget badge. Offline only.')


if __name__ == '__main__':
    asyncio.run(run())
