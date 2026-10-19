"""Offline authenticated claim-link and photo-drop UI acceptance check."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())
from playwright.async_api import async_playwright


async def run():
    case_id = 'a1000000-0000-4000-8000-000000000001'
    shipment_id = 'a2000000-0000-4000-8000-000000000001'
    html = Path('index.html').read_text(encoding='utf-8')
    submissions = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 1100, 'height': 850})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        async def route(request_route):
            request = request_route.request
            path = urlsplit(request.url).path
            if request.url.startswith('http://conversation.test/'):
                if path == '/':
                    return await request_route.fulfill(status=200, content_type='text/html', body=html)
                if path == '/api/v1/config':
                    return await request_route.fulfill(status=200, content_type='application/json', body=json.dumps({'mode': 'local-preview'}))
                if path == '/api/v1/shipping/submit-claim':
                    submissions.append(request.post_data_buffer)
                    return await request_route.fulfill(status=200, content_type='application/json', body=json.dumps({
                        'claim_id': case_id, 'status': 'SUBMISSION_PENDING', 'notice': 'Queued; insurer submission not confirmed.'}))
                return await request_route.fulfill(status=200, content_type='application/json', body='{}')
            await request_route.abort()

        await page.route('**/*', route)
        await page.goto('http://conversation.test/?claim_id=' + case_id, wait_until='domcontentloaded')
        assert not await page.locator('#insuranceClaimsModal').evaluate('(element)=>element.open')
        await page.evaluate('''({caseId,shipmentId}) => {
            document.body.classList.remove('auth-locked');
            document.querySelector('#loginContainer').hidden=true;
            state.session={access_token:'synthetic-no-provider-token'};
            state.mode='configured';
            api=async(path, options)=>{
                if(path.includes('insured-shipments'))return {available:true,headless_claims:true,notice:'Controlled eligibility',
                    shipments:[{id:shipmentId,reference:'TEST',tracking_number:'TEST123'}]};
                if(path.includes('claims/'))return {claim_id:caseId,shipment_id:shipmentId,status:'CLAIM_INGESTED',
                    reason:'PARCEL_LOST',notes:'My package is lost',notice:'Support case received; insurer filing not confirmed.'};
                return {};
            };
        }''', {'caseId': case_id, 'shipmentId': shipment_id})
        await page.evaluate('resumeConversationClaim()')
        assert await page.locator('#insuranceClaimsModal').evaluate('(element)=>element.open')
        assert await page.locator('#insurance-claims-shipment').input_value() == shipment_id
        assert await page.locator('#insurance-claims-notes').input_value() == 'My package is lost'
        assert 'claim_id=' not in page.url
        await page.evaluate('''() => {
            const transfer=new DataTransfer();
            transfer.items.add(new File(['synthetic-image'], 'photo.png', {type:'image/png'}));
            document.querySelector('#insurance-photos-drop').dispatchEvent(new DragEvent('drop', {dataTransfer:transfer,bubbles:true}));
        }''')
        assert await page.locator('#insurance-claims-photos').evaluate('(input)=>input.files.length') == 1
        await page.locator('#insurance-claims-submit').click()
        await page.wait_for_function("document.querySelector('#insurance-claims-notice').textContent.includes('saved privately')")
        assert len(submissions) == 1
        assert case_id.encode() in submissions[0] and b'photo.png' in submissions[0]
        assert await page.evaluate('insuranceCaseId') == case_id
        assert not errors, errors
        await browser.close()
    print('PASS: sign-in-gated claim link, correct case/shipment, photo drop and same-case multipart completion. No live providers.')


if __name__ == '__main__':
    asyncio.run(run())
