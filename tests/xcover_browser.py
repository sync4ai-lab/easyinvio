"""Controlled protected-checkout and claims UI; no provider or billing calls."""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())


async def run():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 1366, 'height': 950});errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto('http://127.0.0.1:8000/', wait_until='domcontentloaded')
        await page.wait_for_function("state.mode!=='checking'")
        await page.evaluate('''()=>{
          document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
          portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'controlled-fixture'};
          renderPortal();setView('dispatch');state.session={access_token:'controlled-no-network-token'};
          window.confirmCalls=0;
          const offer={offer_id:'controlled-offer',carrier_code:'FEDEX',service_code:'TEST',currency:'GBP',client_price_ex_tax:'12.00',fee_breakdown:{wholesale_total:'10',platform_markup:'2'}};
          state.quotes=[offer];
          api=async(path,options={})=>{
            if(path.includes('checkout/context'))return {invoice_reference:'EINVIO-TEST',origin:{country_code:'GB'},destination:{country_code:'GB'},customs_required:false,items:[]};
            if(path.includes('protection-quote')&&options.method==='POST')return {insurance_quote_id:'controlled-policy-quote',premium:'1.20',tax_amount:'0.24',total_charge:'1.44',terms_url:'https://www.xcover.com/en/pds/controlled-test'};
            if(path.includes('protection-quote'))return {selection_available:true,premium_estimate:'1.20',notice:'Select protection to review the supplier tax and policy terms before purchasing.'};
            if(path.includes('checkout/prepare'))return {shipment_id:'controlled-shipment',invoice_reference:'EINVIO-TEST',offer,customs_required:false,price_changed:false};
            if(path.includes('confirm-booking')){window.confirmCalls++;if(!options.body.insurance_requested||!options.body.insurance_terms_accepted||options.body.insurance_quote_id!=='controlled-policy-quote')throw Error('Missing protection consent');return {shipment_id:'controlled-shipment',status:'BOOKED',label:{tracking_number:'CONTROLLED-TRACKING',label_url:'https://label.example.invalid/test.pdf'},insurance:{insured:true,policy_id:'CONTROLLED-POLICY',premium_charged:'1.44'}};}
            if(path.includes('insured-shipments'))return {available:true,notice:'Save a support case and file your insurer claim through XCover.',shipments:[{id:'controlled-shipment',reference:'EINVIO-TEST',tracking_number:'CONTROLLED-TRACKING'}]};
            if(path.includes('claims/'))return {status:'CLAIM_INGESTED',notice:'Insurer review and wallet credit are not confirmed.'};
            if(path.includes('wallet'))return {balance:'86.56',reserved_balance:'0',available_balance:'86.56',currency:'GBP'};
            throw Error('Unexpected controlled request '+path);
          };
          const originalFetch=fetch;
          fetch=async(url,options)=>{if(String(url).endsWith('/shipping/submit-claim'))return new Response(JSON.stringify({status:'CLAIM_INGESTED',notice:'Support case saved. Complete the insurer claim at XCover.',claims_portal_url:'https://www.xcover.com/claims/controlled-test'}),{status:200,headers:{'Content-Type':'application/json'}});return originalFetch(url,options);};
          document.querySelector('#review-dialog').showModal();
        }''')
        await page.evaluate('bookLive(0)')
        await page.locator('#checkout-protection input').check()
        await page.locator('#checkout-customs-yes').click()
        await page.wait_for_selector('#checkout-protection-consent')
        assert '£13.44' in await page.locator('#checkout-price').inner_text()
        assert 'Protection tax' in await page.locator('#checkout-price').inner_text()
        assert await page.locator('#checkout-pay-card').is_disabled()
        await page.locator('#checkout-purchase').click()
        assert await page.evaluate('window.confirmCalls') == 0
        await page.locator('#checkout-protection-consent').check()
        await page.locator('#checkout-purchase').click()
        await page.wait_for_function("document.querySelector('#review-content').textContent.includes('XCover protection confirmed')")
        assert await page.evaluate('window.confirmCalls') == 1
        assert '£1.44' in await page.locator('#review-content').inner_text()
        await page.locator('#review-dialog .close').click()
        await page.evaluate("document.querySelector('#insurance-claims-open').click()")
        await page.wait_for_function("!document.querySelector('#insurance-claims-submit').disabled")
        await page.locator('#insurance-claims-notes').fill('Controlled damage evidence; no genuine claim is filed.')
        await page.locator('#insurance-claims-submit').click()
        await page.wait_for_function("document.querySelector('#insurance-claims-progress').textContent.includes('Support case received')")
        text = await page.locator('#insurance-claims-progress').inner_text()
        assert 'Insurer review: not confirmed' in text and 'Wallet credit: not confirmed' in text
        assert await page.locator('#insurance-claims-progress a').get_attribute('href') == 'https://www.xcover.com/claims/controlled-test'
        for width in [375, 768, 1366]:
            await page.set_viewport_size({'width': width, 'height': 950})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        await page.locator('#insurance-claims-close').click()
        await page.wait_for_function("document.querySelector('#insurance-claims-notes').value===''")
        assert await page.locator('#insurance-claims-notes').input_value() == ''
        assert not errors, errors
        print(json.dumps({'checks': ['actual premium/tax combined total', 'policy terms consent gates purchase',
            'protected wallet checkout does not omit fees through Stripe', 'confirmed policy response',
            'claim support intake does not fake insurer review or wallet credit', 'supplied claims portal',
            '375/768/1366px claims modal and fresh-form reset'], 'page_errors': errors}))
        await browser.close()


if __name__ == '__main__':asyncio.run(run())
