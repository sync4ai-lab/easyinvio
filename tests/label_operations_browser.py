"""Controlled role, notification-control and quote-only UX checks."""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())


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
          state.session={access_token:'controlled-no-network'};portal.role='CLIENT';
          portal.profile={portal_role:'CLIENT',workspace_role:'OWNER'};renderPortal();setView('dashboard');
          window.alertPaused=false;window.pauseCalls=[];
          api=async(path,options)=>{
            if(path==='/api/v1/admin/support/whatsapp/bindings')return {configured:false,controls_ready:true,setup:'Verified recipients and opt-in are required.',bindings:[{id:'fixture-binding',company_name:'Fixture Company',number_suffix:'0123',is_active:true,verified:true,notification_opt_in:true,alerts_paused:alertPaused,is_sandbox:true}]};
            if(path.endsWith('/fixture-binding')){alertPaused=options.body.paused;pauseCalls.push(alertPaused);return {alerts_paused:alertPaused};}
            if(path.endsWith('/capabilities'))return {providers:defaultProviderProfiles};
            if(path.endsWith('/tenants'))return {tenants:[]};
            if(path.endsWith('/carriers')||path.endsWith('/platform-carriers'))return {connections:[]};
            if(path.includes('tracking-readiness'))return {reasons:[],method:'Controlled'};
            throw Error('Unexpected test request '+path);
          };
        }""")
        assert await page.locator('#support-tickets').is_hidden()
        assert await page.locator('#wallet #support-opt-in').count() == 0
        await page.evaluate("portal.profile={portal_role:'SUPER_ADMIN',workspace_role:'OWNER'};portal.role='SUPER_ADMIN';renderPortal();setView('dashboard')")
        assert await page.locator('#support-tickets').is_visible()
        await page.evaluate("setView('admin-carriers')")
        await page.wait_for_function("document.querySelector('[data-alert-binding]')")
        await page.locator('[data-alert-binding]').click()
        await page.wait_for_function('alertPaused && pauseCalls.length===1')
        await page.locator('[data-alert-binding]').click()
        await page.wait_for_function('!alertPaused && pauseCalls.length===2')
        await page.evaluate("""() => {
          portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER'};renderPortal();setView('dispatch');
          state.quotes=[{offer_id:'fixture-rate',carrier_code:'FEDEX',service_code:'FEDEX:INTERNATIONALCONNECT',currency:'GBP',client_price_ex_tax:'12.00',delivery_days:null,label_purchase_available:false,label_purchase_notice:'Quote only: this test connection cannot issue shipping labels.',fee_breakdown:{}}];
          state.quoteRequest={origin:{country_code:'GB'},destination:{country_code:'FR'}};
          renderRates({rates:state.quotes,currency:'GBP',issues:[]});
        }""")
        assert await page.locator('[data-review]').is_disabled()
        assert 'QUOTE ONLY' in await page.locator('#rates').inner_text()
        for width in [375, 768, 1440]:
            await page.set_viewport_size({'width': width, 'height': 1000})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert not errors, errors
        print(json.dumps({'checks': ['internal support admin only', 'wallet alert controls removed', 'admin pause/resume', 'quote-only services cannot enter checkout', '375/768/1440 layouts'], 'page_errors': errors}))
        await browser.close()


asyncio.run(run())
