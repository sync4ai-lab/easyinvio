"""Synthetic browser coverage for shared navigation, preferences and concurrent reads."""
import asyncio
import json
import os
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect
from tests import vercel_hosting_browser as hosting
from tests.tracking_workspace_browser import LIST, DETAIL


async def check(origin):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(hosting.ROOT / '.playwright')
    report = []
    async with async_playwright() as driver:
        browser = await driver.chromium.launch()
        for role in ['OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT', 'INDIVIDUAL', 'SUPER_ADMIN']:
            page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors, calls = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            admin_reads, admin_gate = set(), asyncio.Event()
            prefs = dict(in_app_enabled=True, categories=['IN_TRANSIT'], stale_hours=48, poll_interval_minutes=360)
            async def route(request):
                path = urlsplit(request.request.url).path
                method = request.request.method
                calls.append((path, method))
                admin_paths = {'/api/v1/admin/carriers', '/api/v1/admin/platform-carriers', '/api/v1/admin/platform-carriers/capabilities', '/api/v1/admin/tenants'}
                if path in admin_paths:
                    admin_reads.add(path)
                    if len(admin_reads) == 4: admin_gate.set()
                    await asyncio.wait_for(admin_gate.wait(), 5)
                    return await request.fulfill(json={'connections': [], 'providers': [], 'tenants': []})
                if path.endswith('/preferences'):
                    await asyncio.sleep(.15)
                    if method == 'PUT':
                        prefs.update(request.request.post_data_json)
                        return await request.fulfill(json=prefs)
                    return await request.fulfill(json={'preferences': prefs, 'refresh_enabled': False})
                if '/shipments?' in request.request.url: return await request.fulfill(json=LIST)
                if path.endswith('/notifications'): return await request.fulfill(json={'notifications': []})
                if path.endswith('/tracking/health'): return await request.fulfill(json={'jobs': [], 'polling_enabled': False})
                if path.endswith('/share-links'): return await request.fulfill(json={'links': []})
                if '/tracking/shipments/' in path: return await request.fulfill(json=DETAIL)
                if path.endswith('/read-fixture') or path.endswith('/write-fixture'):
                    await asyncio.sleep(.1)
                    return await request.fulfill(json={'items': ['fixture']})
                if path.endswith('/config'): return await request.fulfill(json={'mode':'local-preview', 'dispatch_updates_mode':'POLLING'})
                return await request.fulfill(json={'shipments': [], 'stores': [], 'orders': [], 'entries': [], 'members': [], 'invitations': []})
            async def local_only(request):
                if request.request.url.startswith(origin): await request.continue_()
                else: await request.abort()
            await page.route('**/*', local_only)
            await page.route('**/api/v1/**', route)
            await page.goto(origin, wait_until='domcontentloaded')
            await page.wait_for_function("state.mode === 'local-preview'")
            await page.evaluate("""role => {
              state.session = {access_token:'synthetic-'+role, expires_at:Math.floor(Date.now()/1000)+3600};
              portal.session=state.session; renderAccount();
              portal.profile = {tenant_id:'00000000-0000-4000-8000-000000000001',
                workspace_role:['INDIVIDUAL','SUPER_ADMIN'].includes(role)?'OWNER':role,
                workspace_type:role==='INDIVIDUAL'?'INDIVIDUAL':'BUSINESS',
                portal_role:role==='SUPER_ADMIN'?'SUPER_ADMIN':'CLIENT'};
              portal.role=role==='SUPER_ADMIN'?'SUPER_ADMIN':'CLIENT';
              identityProfile = {email:'tester@example.invalid', role}; showIdentityGate();
              state.mode='configured'; refreshEnterpriseNavigation();
              setView('tracking');
            }""", role)
            try:
                await expect(page.locator('#tracking-rows .tracking-ref')).to_have_count(1)
            except AssertionError:
                print('DEBUG', role, errors, calls, await page.locator('#tracking-message').text_content(), await page.evaluate('({allowed:allowedEnterpriseViews(),profile:portal.profile,view:enterprise.currentView})'))
                raise
            await expect(page.locator('#modebar')).to_be_hidden()
            await expect(page.locator('#account-btn')).to_be_hidden()
            await expect(page.locator('.sidebar-caption')).to_be_hidden()
            assert await page.locator('.sidebar [data-enterprise-view=tracking]').count() == 0
            assert await page.locator('.mobile-nav [data-enterprise-view=tracking]').count() == 0
            assert await page.locator('#dispatch .readiness [data-packaging-open]').count() == 0
            assert not await page.locator('#dispatch').get_by_text('Open tracking manifest', exact=True).count()
            assert await page.locator('#identity-logout').evaluate('(node)=>!!node.closest(".sidebar-account")')
            assert await page.locator('#identity-avatar').evaluate('(node)=>!!node.closest(".topbar-actions")')
            assert await page.locator('.tracking-global input').get_attribute('placeholder') == 'Find an Order'
            assert await page.locator('.topbar-actions').evaluate('(node)=>node.querySelector(".tracking-global").compareDocumentPosition(node.querySelector("#identity-avatar")) & Node.DOCUMENT_POSITION_FOLLOWING')
            await expect(page.locator('#identity-logout')).to_be_visible()
            await expect(page.locator('#tracking .pagehead #tracking-preferences')).to_have_count(1)
            if role != 'SUPER_ADMIN':
                await page.locator('#tracking-preferences').click()
                await expect(page.locator('#tracking-pref-message')).to_have_text('Loading preferences...')
                await expect(page.locator('#tracking-pref-events input')).to_have_count(6)
                await expect(page.locator('#tracking-pref-interval')).to_be_hidden()
                assert 'Polling is off' not in await page.locator('#tracking-pref-form').inner_text()
                assert 'Visibility is included' not in await page.locator('#tracking-pref-form').inner_text()
                await page.locator('#tracking-pref-form summary').click()
                checkbox = page.locator('[name=category][value=AVAILABLE_FOR_PICKUP]')
                if role in ['OWNER', 'ADMIN', 'INDIVIDUAL']:
                    await checkbox.check()
                    await expect(page.locator('#tracking-pref-message')).to_have_text('Unsaved changes.')
                    await page.locator('#tracking-pref-form [type=submit]').click()
                    await expect(page.locator('#tracking-pref-message')).to_contain_text('Preferences saved.')
                    assert 'AVAILABLE_FOR_PICKUP' in prefs['categories']
                    await page.locator('#tracking-pref-close').click()
                    await page.locator('#tracking-preferences').click()
                    await expect(checkbox).to_be_checked()
                else:
                    await expect(checkbox).to_be_disabled()
                    await expect(page.locator('#tracking-pref-form [type=submit]')).to_be_hidden()
                await page.locator('#tracking-pref-close').click()
            else:
                await expect(page.locator('#tracking-preferences')).to_be_hidden()
                await page.evaluate("loadEnterpriseView('admin-carriers')")
                assert len(admin_reads) == 4
            # Repeated read actions share only their active network request.
            before = len([c for c in calls if c[0].endswith('/read-fixture')])
            await page.evaluate("Promise.all([api('/api/v1/read-fixture',{auth:true}),api('/api/v1/read-fixture',{auth:true})])")
            assert len([c for c in calls if c[0].endswith('/read-fixture')]) == before+1
            await page.evaluate("api('/api/v1/read-fixture',{auth:true})")
            assert len([c for c in calls if c[0].endswith('/read-fixture')]) == before+2
            await page.evaluate("Promise.all([api('/api/v1/write-fixture',{method:'POST',body:{},auth:true}),api('/api/v1/write-fixture',{method:'POST',body:{},auth:true})])")
            assert len([c for c in calls if c[0].endswith('/write-fixture')]) == 2
            await page.set_viewport_size({'width':390,'height':844})
            await expect(page.locator('#identity-avatar')).to_be_visible()
            await expect(page.locator('#identity-logout')).to_be_visible()
            target = await page.locator('#identity-logout').evaluate('(node)=>{const r=node.getBoundingClientRect();return {rect:r.toJSON(),top:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.outerHTML,hit:node.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};}')
            assert target['hit'], target
            assert await page.locator('#identity-avatar').evaluate('(node)=>node.getBoundingClientRect().left >= document.querySelector(".tracking-global button").getBoundingClientRect().right')
            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth+2'), role
            if role == 'OWNER':
                folder=hosting.ROOT/'tmp'/'workspace-cleanup-preview'; folder.mkdir(exist_ok=True)
                await page.screenshot(path=str(folder/'mobile.png'), full_page=True)
                await page.set_viewport_size({'width':1440,'height':1000})
                await page.screenshot(path=str(folder/'desktop.png'), full_page=True)
                await page.locator('.tracking-global input').fill('SYNTHETIC-ORDER-45')
                await page.locator('.tracking-global button').click()
                await expect(page.locator('#tracking-search')).to_have_value('SYNTHETIC-ORDER-45')
            await page.locator('#identity-logout').click()
            await expect(page.locator('#loginContainer')).to_be_visible()
            await expect(page.locator('#identity-logout')).to_be_hidden()
            assert await page.evaluate('state.session === null')
            assert not errors, errors
            report.append({'role':role,'navigation':'passed','preferences':'passed','read_coalescing':'passed','mobile':'passed'})
            await page.close()
        await browser.close()
    print(json.dumps(report))


if __name__ == '__main__':
    hosting.check = check
    hosting.main()
