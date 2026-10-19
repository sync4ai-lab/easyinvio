"""Offline browser contract for manual returns and identity cleanup."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
from playwright.async_api import async_playwright


async def run():
    html=Path('index.html').read_text(encoding='utf-8')
    output=Path('output/headless_returns');output.mkdir(parents=True,exist_ok=True)
    requests=[]
    child='11111111-1111-4111-8111-111111111111'
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch()
        page=await browser.new_page(viewport={'width':1280,'height':950})
        page.set_default_timeout(5000)
        await page.add_init_script('window.setInterval = () => 0')
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        async def route(handler):
            request=handler.request;parsed=urlsplit(request.url)
            if parsed.hostname!='returns.test':return await handler.abort()
            if parsed.path=='/':return await handler.fulfill(content_type='text/html',body=html)
            if parsed.path=='/api/v1/shipping/prepare-return':
                payload=json.loads(request.post_data);requests.append(payload)
                assert request.headers['authorization']=='Bearer offline-synthetic'
                result={'request_id':payload[0]['idempotency_key'],'status':'BOOKED','shipment_id':child,
                    'paperless_available':True,'qr_requires_workspace_login':False,
                    'label':{'label_url':'/api/v1/shipping/'+child+'/documents/label'},
                    'return_dropoff_qr_code_url':'https://returns.test/api/v1/shipping/return-dropoff?token=synthetic'}
                return await handler.fulfill(content_type='application/json',body=json.dumps({'results':[result]}))
            return await handler.fulfill(content_type='application/json',body=json.dumps({'mode':'local-preview'} if parsed.path=='/api/v1/config' else {}))
        await page.route('**/*',route)
        await page.goto('https://returns.test/',wait_until='networkidle')
        async def persona(role):
            await page.evaluate('''({role,id})=>{
                document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
                state.session={access_token:'offline-synthetic'};state.mode='configured';
                ensureActiveIdentitySession=async()=>{};
                portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:role,tenant_id:'fixture-tenant',workspace_type:'BUSINESS'};
                document.querySelectorAll('main > section').forEach(node=>node.hidden=true);
                document.querySelector('#manifest').hidden=false;
                state.manifest=[{id,reference:'ORDER-1',status:'BOOKED',label_status:'LABEL_CREATED',price:'4.25',currency:'GBP',origin_country:'GB',destination_country:'GB',tracking_lifecycle_type:'FORWARD_SHIPMENT'}];
                renderManifest();
            }''',{'role':role,'id':child})
        await persona('OWNER')
        await page.locator('[data-prepare-return]').click()
        await page.locator('#return-command-form [name="maximum_price"]').fill('10.00')
        await page.locator('#return-command-form [type="submit"]').click()
        await page.locator('#return-command-status').filter(has_text='Return booked').wait_for(timeout=5000)
        assert len(requests)==1 and requests[0][0]['maximum_price']=='10.00'
        assert await page.locator('#return-command-form [type="submit"]').is_disabled()
        assert await page.locator('#return-command-links a').get_attribute('rel')=='noopener noreferrer'
        assert await page.locator('#return-command-links button').text_content()=='Download return label'
        await page.screenshot(path=str(output/'booked-return.png'))
        await page.locator('#return-command-close').click()
        await persona('DISPATCHER')
        await page.locator('[data-prepare-return]').click()
        assert await page.locator('#return-command-form option[value="CUSTOMER_PAY"]').evaluate("node=>node.disabled")
        await page.set_viewport_size({'width':375,'height':900})
        bounds=await page.locator('#return-command-dialog').bounding_box()
        assert bounds['x']>=0 and bounds['x']+bounds['width']<=376
        await page.screenshot(path=str(output/'mobile-return.png'))
        await page.evaluate('clearSession()')
        assert not await page.locator('#return-command-dialog').evaluate('node=>node.open')
        assert await page.locator('#return-command-links').text_content()==''
        await persona('ACCOUNTANT')
        assert await page.locator('[data-prepare-return]').count()==0
        assert not errors,errors
        await browser.close()
    print('PASS: authenticated return batch, exact price limit, QR link, duplicate-submit fence, role restrictions, mobile and session cleanup.')


if __name__=='__main__':asyncio.run(run())
