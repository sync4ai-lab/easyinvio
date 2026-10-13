"""Controlled packaging UX checks; no carrier, booking or payment requests."""
import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())
OUT = Path('output/packaging_sizes')
OUT.mkdir(parents=True, exist_ok=True)


async def run():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto('http://127.0.0.1:8000/', wait_until='domcontentloaded')
        await page.wait_for_function("state.mode !== 'checking'")
        await page.evaluate("""() => {
          document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;
          portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER'};
          state.session={access_token:'controlled-no-network'};renderPortal();setView('dispatch');
          api=async(path)=> { if(path.includes('weight')) return {actual_weight_kg:'10',billable_weight_kg:'10',basis:'actual'};throw Error('Unexpected request '+path); };
          $('#origin-country_code').value='GB';$('#destination-country_code').value='FR';
          $('#weight_kg').value='10';$('#shipment-description').value='Controlled goods';
          $('#shipment-quantity').value='2';$('#shipment-unit-weight').value='3';
          $('#origin-city').value='Leeds';$('#destination-city').value='Paris';
          state.quotes=[{offer_id:'old-fixture'}];state.quoteRequest={old:true};
        }""")
        assert await page.locator('.sidebar [data-enterprise-view="boxes"]').count() == 0
        await page.locator('#quote-form [data-packaging-open]').click()
        await page.wait_for_function("packagingDialog.open", timeout=3000)
        assert await page.locator('.packaging-card').count() == 4
        assert await page.locator('[data-packaging-choice="1"]').count() == 3
        assert 'up to 31 kg' in await page.locator('#packaging-route-guidance').inner_text()
        for width in [375, 768, 1440]:
            await page.set_viewport_size({'width': width, 'height': 1000})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            assert await page.locator('#packaging-size-dialog').evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
        await page.screenshot(path=str(OUT / 'packaging-picker.png'))
        await page.locator('[data-packaging-choice="1"][data-packaging-size="1"]').click()
        assert await page.evaluate("['cargo-type','length_cm','width_cm','height_cm','weight_kg'].map(id=>$('#'+id).value)") == ['PARCEL', '40', '30', '20', '10']
        assert await page.evaluate("[$('#shipment-description').value,$('#shipment-quantity').value,$('#origin-city').value,$('#destination-city').value]") == ['Controlled goods', '2', 'Leeds', 'Paris']
        assert await page.evaluate('state.quotes.length===0 && state.quoteRequest===null')
        await page.locator('#quote-form [data-packaging-open]').click()
        await page.locator('[data-packaging-choice="2"][data-packaging-size="0"]').click()
        assert await page.evaluate("['cargo-type','length_cm','width_cm','height_cm','weight_kg'].map(id=>$('#'+id).value)") == ['PALLET', '120', '80', '', '10']
        assert await page.locator('#height_cm').evaluate('(node)=>document.activeElement===node')
        await page.locator('#quote-form [data-packaging-open]').click()
        await page.locator('[data-packaging-choice="0"]').click()
        assert await page.locator('#cargo-type').input_value() == 'LETTER'
        assert await page.locator('#length_cm').is_disabled()
        assert await page.locator('#weight_kg').input_value() == '10'
        assert not await page.locator('#weight_kg').evaluate('(node)=>node.checkValidity()')
        await page.evaluate("setView('boxes')")
        await page.keyboard.press('Escape')
        assert not await page.evaluate('packagingDialog.open')
        assert await page.locator('#dispatch').is_visible()
        await page.evaluate("setView('boxes');setView('manifest')")
        assert not await page.evaluate('packagingDialog.open')
        assert await page.locator('#manifest').is_visible()
        assert not errors, errors
        print(json.dumps({'checks': ['four matching classifications', 'three parcel examples', 'route-scoped carrier limits', '375/768/1440 layouts', 'classification and dimensions prefilled', 'weight, goods and addresses preserved', 'stale offers invalidated', 'pallet height requires measurement', 'letter weight remains validated', 'Escape and legacy navigation'], 'page_errors': errors}))
        await browser.close()


asyncio.run(run())
