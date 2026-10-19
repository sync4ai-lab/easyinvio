"""Offline WhatsApp selection handoff; no paid or provider operations."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())
from playwright.async_api import async_playwright


async def run():
    html = Path('index.html').read_text(encoding='utf-8')
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        async def route(request_route):
            path = urlsplit(request_route.request.url).path
            if request_route.request.url.startswith('http://conversation.test/'):
                if path == '/':
                    return await request_route.fulfill(content_type='text/html', body=html)
                data = {'mode': 'local-preview'} if path == '/api/v1/config' else {}
                return await request_route.fulfill(content_type='application/json', body=json.dumps(data))
            await request_route.abort()

        await page.route('**/*', route)
        await page.goto('http://conversation.test/?t=synthetic-tenant&quote=synthetic-signed-choice', wait_until='domcontentloaded')
        assert 'quote=' not in page.url and 't=' not in page.url
        assert not await page.locator('#review-dialog').evaluate('(element)=>element.open')
        await page.evaluate('''() => {
            window.checkoutCalls=[];
            document.body.classList.remove('auth-locked');
            document.querySelector('#loginContainer').hidden=true;
            state.session={access_token:'synthetic-session'};
            state.mode='configured';
            portal.profile={tenant_id:'synthetic-tenant',workspace_role:'OWNER'};
            api=async(path,options)=>{
                checkoutCalls.push({path,method:options?.method||'GET'});
                if(path.startsWith('/v1/whatsapp/quote-choice')) return {
                    selected_rate:{offer_id:'synthetic-offer',carrier_code:'DPD',service_code:'EXPRESS',currency:'GBP',client_price_ex_tax:'23.45'},
                    rating_request:{origin:{country_code:'GB'},destination:{country_code:'GB'}},
                    expires_at:new Date(Date.now()+300000).toISOString()};
                if(path.startsWith('/api/v1/checkout/context')) return {
                    origin:{country_code:'GB'},destination:{country_code:'GB'},customs_required:false};
                if(path.includes('tracking-readiness'))return {};
                if(path.includes('protection-quote'))return {available:false,notice:'Unavailable in controlled test'};
                throw Error('Unexpected operation: '+path);
            };
        }''')
        await page.evaluate('resumeConversationQuote()')
        assert await page.locator('#review-dialog').evaluate('(element)=>element.open')
        assert await page.locator('#checkout-customs-yes').count() == 1
        assert await page.evaluate('state.quotes[0].offer_id') == 'synthetic-offer'
        calls = await page.evaluate('checkoutCalls')
        assert len(calls) == 4, calls
        assert all(call['method'] == 'GET' for call in calls), calls
        assert await page.evaluate('pendingConversationQuote') is None
        await page.evaluate('resumeConversationQuote()')
        assert await page.evaluate('checkoutCalls.length') == 4
        # Failed/expired resolution leaves no checkout or automatic purchase.
        await page.evaluate('''() => {
            document.querySelector('#review-dialog').close();
            pendingConversationQuote={token:'expired',tenant:'synthetic-tenant'};
            api=async()=>{throw Error('Quote link is invalid or expired');};
        }''')
        await page.evaluate('resumeConversationQuote()')
        assert not await page.locator('#review-dialog').evaluate('(element)=>element.open')
        assert not errors, errors
        await browser.close()
    print('PASS: sign-in-gated selection, URL scrub, existing checkout, no automatic payment, expiry failure.')


if __name__ == '__main__':
    asyncio.run(run())
