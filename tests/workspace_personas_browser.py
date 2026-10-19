"""Offline personal sign-up, persona masking and cohort chart acceptance."""
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
        page = await browser.new_page(viewport={'width':1100,'height':950})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        async def route(request_route):
            request = request_route.request
            if request.url.startswith('http://personas.test/'):
                if urlsplit(request.url).path == '/':
                    return await request_route.fulfill(content_type='text/html',body=html)
                data = {'mode':'local-preview'} if urlsplit(request.url).path == '/api/v1/config' else {}
                return await request_route.fulfill(content_type='application/json',body=json.dumps(data))
            await request_route.abort()

        await page.route('**/*',route)
        await page.goto('http://personas.test/',wait_until='domcontentloaded')
        await page.evaluate('''() => {
            window.personaRequests=[];
            api=async(path,options)=>{
                personaRequests.push({path,body:options?.body});
                if(path.endsWith('/register')) return {registration_id:'synthetic-session',registration_secret:'synthetic-local-secret',message:'Enter your email code'};
                if(path.endsWith('/register/verify')) return {message:'Account activated. Sign in.'};
                throw Error('Unexpected operation '+path);
            };
        }''')
        await page.locator('#identity-signup-open').click()
        await page.locator('[data-signup-persona="INDIVIDUAL"]').click()
        assert await page.locator('#identity-signup-corporate').is_hidden()
        assert await page.locator('#identity-signup-corporate input:enabled').count() == 0
        for name,value in {'full_name':'Alex Consumer','email':'alex@example.test','phone':'+447700900123','password':'synthetic-password-only'}.items():
            await page.locator(f'#identity-signup-form input[name="{name}"]').fill(value)
        await page.locator('#identity-signup-form button[type="submit"]').click()
        await page.wait_for_function('signupReceipt !== null')
        request = await page.evaluate('personaRequests[0]')
        assert request['body']['workspace_type'] == 'INDIVIDUAL'
        assert set(request['body']['profile']) == {'full_name','billing_email','phone_e164'}
        assert 'password' not in request['body']
        await page.locator('#identity-signup-form input[name="code"]').fill('12345678')
        await page.locator('#identity-signup-form button[type="submit"]').click()
        await page.wait_for_function("document.querySelector('#identity-login-status').textContent.includes('activated')")
        assert await page.locator('#identity-signup-form input[name="password"]').input_value() == ''
        assert await page.evaluate('signupReceipt') is None
        assert (await page.evaluate('personaRequests[1]'))['body']['code'] == '12345678'
        await page.evaluate('''() => renderPersonaReport({cohorts:{shipping:[
            {workspace_type:'BUSINESS',currency:'GBP',revenue:'100.00',margin:'20.00',package_count:4,label_count:3},
            {workspace_type:'INDIVIDUAL',currency:'GBP',revenue:'50.00',margin:'10.00',package_count:2,label_count:2}],
            tickets:[{workspace_type:'INDIVIDUAL',ticket_count:1}],accounts:[]}})''')
        assert await page.locator('#persona-report .persona-pair').count() == 6
        text = await page.locator('#persona-report').text_content()
        assert 'Business: 4' in text and 'Personal: 2' in text
        await page.locator('#identity-signup-open').click()
        assert await page.locator('#identity-signup-corporate').is_visible()
        assert await page.locator('#identity-signup-corporate input:enabled').count() == 7
        assert not errors, errors
        await browser.close()
    print('PASS: personal and business masking, verified signup requests, cleared secrets and separate cohort bars. Offline only.')


if __name__ == '__main__':
    asyncio.run(run())
