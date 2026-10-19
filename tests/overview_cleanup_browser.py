"""Offline overview cleanup across account types, roles and responsive widths."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())
from playwright.async_api import async_playwright


async def run():
    html = Path('index.html').read_text(encoding='utf-8')
    output = Path('output/overview_cleanup')
    output.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width':1366,'height':1000})
        errors = []
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def route(request_route):
            if request_route.request.url.startswith('http://overview.test/'):
                if urlsplit(request_route.request.url).path == '/':
                    return await request_route.fulfill(content_type='text/html',body=html)
                data = {'mode':'local-preview'} if urlsplit(request_route.request.url).path == '/api/v1/config' else {}
                return await request_route.fulfill(content_type='application/json',body=json.dumps(data))
            await request_route.abort()
        await page.route('**/*',route)
        await page.goto('http://overview.test/',wait_until='domcontentloaded')
        personas = [('BUSINESS','OWNER'),('INDIVIDUAL','OWNER'),('BUSINESS','ADMIN'),
            ('BUSINESS','ACCOUNTANT'),('BUSINESS','DISPATCHER'),('BUSINESS','SUPER_ADMIN'),('BUSINESS','ASSISTANCE')]
        for account,role in personas:
            await page.evaluate('''({account,role}) => {
                document.body.classList.remove('auth-locked');
                document.querySelector('#loginContainer').hidden=true;
                state.session={access_token:'offline-synthetic'};state.mode='configured';
                const admin=role==='SUPER_ADMIN';
                portal.role=admin?'SUPER_ADMIN':'CLIENT';
                portal.profile={portal_role:admin?'SUPER_ADMIN':'CLIENT',workspace_role:admin||role==='ASSISTANCE'?'OWNER':role,
                    tenant_id:admin?null:'synthetic-tenant',company_name:account==='INDIVIDUAL'?'Alex Personal':'Example Trading',workspace_type:account};
                state.assistance=role==='ASSISTANCE'?{company_name:'Example Trading'}:null;
                portal.report={totals_by_currency:[{currency:'GBP',revenue:'100.00',margin:'20.00',package_count:4}],
                    performance:{booked_shipments:4,delivered_shipments:2,in_transit_shipments:1,exception_shipments:0,
                        awaiting_transit_shipments:1,measured_deliveries:2,observed_transit_days:'2.00',
                        basis:'Current outcomes for shipments booked in this UTC period. Observed transit is the average time from the first accepted carrier in-transit update to delivery.'},
                    cohorts:{shipping:[],tickets:[],accounts:[]}};
                portal.lanes=[];
                enterprise.currentView=role==='DISPATCHER'?'workspace':'dashboard';
                renderPortal();renderCharts(admin,[{carrier:'DPD',volume:4}]);
                if(role==='DISPATCHER') {document.querySelector('#dashboard').hidden=true;document.querySelector('#workspace').hidden=false;}
            }''',{'account':account,'role':role})
            assert await page.locator('.sidebar-footer,.quick-grid,#dashboard-note,#chart-source,#trend-period').count() == 0
            assert 'Built for dispatch teams' not in await page.locator('.sidebar').text_content()
            if role != 'DISPATCHER':
                assert await page.locator('#transit-tooltip').is_hidden()
                if role != 'SUPER_ADMIN':
                    assert 'Current outcomes' not in await page.locator('#secondary-chart').text_content()
                    assert '2.00 days' in await page.locator('#secondary-chart').text_content()
                await page.locator('#transit-info').hover()
                assert await page.locator('#transit-tooltip').is_visible()
                await page.locator('#dashboard-title').hover()
                await page.locator('#transit-info').focus()
                assert await page.locator('#transit-tooltip').is_visible()
                await page.keyboard.press('Escape')
                assert await page.locator('#transit-tooltip').is_hidden()
                await page.locator('#transit-info').click()
                assert await page.locator('#transit-tooltip').is_visible()
                await page.locator('#dashboard-title').click()
                assert await page.locator('#transit-tooltip').is_hidden()
            for width in (375,768,1366):
                await page.set_viewport_size({'width':width,'height':1000})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(account,role,width)
                if width==1366 and role=='OWNER' and account=='BUSINESS':
                    await page.screenshot(path=str(output/'business-desktop.png'),animations='disabled',timeout=5000)
                if width==375 and role=='OWNER' and account=='INDIVIDUAL':
                    dates = await page.locator('#report-start').bounding_box()
                    assert dates['width'] >= 120
                    await page.locator('#transit-info').evaluate("element => element.scrollIntoView({block:'center',behavior:'instant'})")
                    await page.locator('#transit-info').click(timeout=5000)
                    tooltip = await page.locator('#transit-tooltip').bounding_box()
                    assert tooltip['x'] >= 8 and tooltip['x']+tooltip['width'] <= width-8
                    await page.keyboard.press('Escape')
                    await page.evaluate('window.scrollTo(0,0)')
                    await page.screenshot(path=str(output/'personal-mobile.png'),animations='disabled',timeout=5000)
                if width==1366 and role=='SUPER_ADMIN':
                    cards = page.locator('#owner-command-center .responsive-grid > .card')
                    left,right = await cards.nth(0).bounding_box(),await cards.nth(1).bounding_box()
                    assert abs(left['y']-right['y']) <= 1
                    assert abs(left['height']-right['height']) <= 1
                    await page.screenshot(path=str(output/'admin-desktop.png'),animations='disabled',timeout=5000)
        assert not errors,errors
        await browser.close()
    print('PASS: seven personas, 375/768/1366px, no stale selectors, hover/focus/touch tooltip and preserved transit values.')


if __name__ == '__main__':
    asyncio.run(run())
