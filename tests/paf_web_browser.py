"""Synthetic browser coverage of independent, race-safe UK address selection."""
import asyncio
import json
import os
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, expect
from tests import vercel_hosting_browser as hosting


async def check(origin):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(hosting.ROOT / '.playwright')
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width':1366, 'height':950})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        async def handler(route):
            path = urlsplit(route.request.url).path
            if path.endswith('/addresses/uk/lookup'):
                await route.fulfill(json={'source':'ROYAL_MAIL_PAF', 'postcode':'CB2 1TQ', 'addresses':[
                    {'id':'123', 'label':'Flat 2, 10 Trinity Street, CAMBRIDGE, CB2 1TQ', 'address':{
                        'line1':'10 Trinity Street', 'line2':'Flat 2', 'city':'CAMBRIDGE', 'postal_code':'CB2 1TQ', 'country_code':'GB'}}]})
            elif path == '/api/v1/config':
                await route.fulfill(json={'mode':'local-preview', 'supabase_url':None, 'publishable_key':None})
            else:
                await route.fulfill(json={'items':[], 'shipments':[], 'orders':[], 'members':[]})
        await page.route('**/api/v1/**', handler)
        await page.goto(origin, wait_until='domcontentloaded')
        await page.wait_for_function("state.mode === 'local-preview'")
        await page.evaluate("""() => {
            document.body.classList.remove('auth-locked'); document.querySelector('#loginContainer').hidden = true;
            portal.role = 'CLIENT'; portal.profile = {tenant_id:'synthetic', workspace_role:'OWNER', portal_role:'CLIENT'};
            state.session = {access_token:'synthetic', expires_at:Math.floor(Date.now()/1000)+3600};
            refreshEnterpriseNavigation(); setView('dispatch');
        }""")
        for role in ['OWNER','ADMIN','DISPATCHER','ACCOUNTANT']:
            await page.evaluate("role => { portal.profile.workspace_role=role; }", role)
            await page.locator('#origin-line1').fill('21 Warehouse Street')
            await page.locator('#origin-city').fill('LEEDS')
            await page.locator('#origin-postal_code').fill('LS1 2EJ')
            await page.locator('#origin-country_code').select_option('GB')
            await page.locator('#destination-country_code').select_option('GB')
            await page.locator('#destination-postal_code').fill('CB2')
            assert not await page.locator('#destination-postal_code').evaluate('(e) => e.validity.valid')
            await page.locator('#destination-postal_code').fill('cb21tq')
            await page.locator('#destination-lookup').click()
            await expect(page.locator('#destination-premises')).to_be_visible()
            await page.locator('#destination-premises').select_option('0')
            await expect(page.locator('#destination-city')).to_have_value('CAMBRIDGE')
            await expect(page.locator('#destination-line2')).to_have_value('Flat 2')
            await expect(page.locator('#origin-line1')).to_have_value('21 Warehouse Street')
            await expect(page.locator('#origin-city')).to_have_value('LEEDS')
            await expect(page.locator('#destination-address-check')).to_have_text('')
            await expect(page.locator('#paf-match-notice')).to_contain_text('matched to Royal Mail PAF')
            await page.get_by_role('button',name='Close address validation message').click()
            await expect(page.locator('#paf-match-notice')).to_have_count(0)
            await page.locator('#destination-city').fill('PARIS')
            await expect(page.locator('#destination-address-check')).to_contain_text('Address not verified')
        await page.locator('#destination-country_code').select_option('FR')
        await expect(page.locator('#destination-lookup')).to_be_visible()
        await expect(page.locator('#destination-address-check')).to_contain_text('does not verify international')
        await page.set_viewport_size({'width':390,'height':844})
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await page.clock.install()
        await page.evaluate('showAddressMatchNotice()')
        await expect(page.locator('#paf-match-notice')).to_be_visible()
        await page.clock.fast_forward(5001)
        await expect(page.locator('#paf-match-notice')).to_have_count(0)
        await page.set_viewport_size({'width':320,'height':844})
        await page.evaluate("document.querySelector('#package-guidance-dialog').showModal()")
        box=await page.locator('#package-guidance-dialog').bounding_box()
        assert box and box['x']>=19 and box['y']>=19 and box['x']+box['width']<=301
        output=hosting.ROOT/'output/quote-controls-qa';output.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(output/'packaging-mobile.png'))
        await expect(page.locator('#package-guidance-close')).to_have_text('\u00d7')
        await page.locator('#package-guidance-close').click()
        await expect(page.locator('#package-guidance-dialog')).not_to_be_visible()
        assert not errors, errors
        await browser.close()
        print(json.dumps({'paf_web':'passed', 'personas':4, 'pickup_preserved':True, 'edits_clear_verification':True, 'mobile':'passed'}))


if __name__ == '__main__':
    hosting.check = check
    hosting.main()
