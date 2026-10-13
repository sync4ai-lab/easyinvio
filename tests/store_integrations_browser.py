"""UI contract test: controlled merchant API, no actual merchant requests."""
import asyncio
import os
from pathlib import Path
from uuid import uuid4

from playwright.async_api import async_playwright, expect

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())


async def run():
    sid = str(uuid4()); calls = []; errors = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 1366, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        async def api(route):
            path = route.request.url.split('/api/v1/')[1].split('?')[0]
            if path == 'workspace/stores':
                data = {'stores': [{'id': sid, 'display_name': 'QA Shop', 'platform': 'SHOPIFY', 'is_active': True}]}
            elif path.endswith('/connection'):
                if route.request.method == 'PUT':
                    calls.append(route.request.post_data_json)
                data = {'configured': bool(calls), 'shop_domain': 'qa-shop.myshopify.com', 'sku_unit_grams': {'TEE': '200'}, 'live_import': True}
            elif path == 'dispatch-workspace/sync/' + sid:
                calls.append({'retrieved': True})
                data = {'results': [{'shipment_id': str(uuid4()), 'status': 'PENDING_IMPORT', 'replayed': False}], 'more_available': False}
            elif path in ('config', 'auth/config'): data = {'mode': 'configured', 'supabase_url': None, 'publishable_key': None}
            else: data = {'orders': [], 'stores': [], 'shipments': [], 'tickets': [], 'history': []}
            await route.fulfill(json=data)
        await page.route('**/api/v1/**', api)
        await page.goto('http://127.0.0.1:8000/')
        await page.evaluate("""()=>{document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;
            state.session={access_token:'controlled',expires_at:9999999999};portal.role='CLIENT';
            portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'00000000-0000-4000-8000-000000000001'};setView('stores');} """)
        await expect(page.locator('#store-catalogue article')).to_have_count(6)
        await expect(page.locator('#store-list [data-store-sync]')).to_be_visible()
        Path('docs/store_integrations').mkdir(parents=True, exist_ok=True)
        await page.screenshot(path='docs/store_integrations/catalogue.png', full_page=True)
        await page.locator('[data-store-guide="SHOPIFY"]').click()
        await expect(page.locator('#store-guide')).to_be_visible()
        await expect(page.locator('#store-guide-steps')).to_contain_text('Client ID')
        await page.locator('#store-guide .close').click()
        await page.locator('[data-store-settings]').click()
        await page.locator('#store-connection-form [name=access_token]').fill('controlled-private-token')
        for width in [375, 768, 1366]:
            await page.set_viewport_size({'width': width, 'height': 1000})
            assert await page.evaluate('document.documentElement.scrollWidth-innerWidth') <= 1
        await page.locator('#store-connection-form button').click()
        await expect(page.locator('#store-connection')).not_to_be_visible()
        assert calls[0]['access_token'] == 'controlled-private-token'
        assert await page.locator('#store-connection-form [name=access_token]').input_value() == ''
        await page.locator('[data-store-connect="EBAY"]').click()
        await expect(page.locator('#store-help')).to_be_visible()
        await expect(page.locator('#store-help')).to_contain_text('does not send it automatically')
        await page.locator('#store-help .close').click()
        await page.locator('[data-store-sync]').click()
        await expect(page.locator('#workspace')).to_be_visible()
        assert {'retrieved': True} in calls
        await page.evaluate("portal.profile.workspace_role='ACCOUNTANT';setView('stores');renderEnterpriseStores()")
        await expect(page.locator('#store-new')).not_to_be_visible()
        await expect(page.locator('[data-store-settings]')).to_have_count(0)
        assert not errors, errors
        await browser.close()
    print('Store catalogue, guides, encrypted setup contract, retrieval, role boundaries and responsive layouts passed.')

asyncio.run(run())
