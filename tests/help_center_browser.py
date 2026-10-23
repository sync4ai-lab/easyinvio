"""Isolated browser verification: public help only, no database or provider calls."""
import asyncio
import json
import os
import socket
import threading
import time
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright, expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.help_center import router

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())


async def run(origin):
    output = Path('output/help-center')
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context=await browser.new_context(viewport={'width':1440,'height':1100})
        page = await context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.route('**/api/v1/**', lambda route: route.fulfill(json={'mode': 'preview', 'supabase_url': None, 'publishable_key': None}))
        await page.goto(origin + '/')
        await expect(page.locator('#loginContainer a[href="/help"]')).to_be_visible()
        await page.locator('#loginContainer a[href="/help"]').click()
        await expect(page.get_by_role('heading', name='How can we help?')).to_be_visible()
        await expect(page.locator('.domain-card')).to_have_count(3)
        await page.locator('#supportSearch').fill('When is my wallet charged?')
        await page.get_by_role('button', name='Ask the help assistant').click()
        await expect(page.locator('#support-agent-answer')).to_contain_text('Sign in to ask')
        workspace=await page.context.new_page()
        await workspace.route('**/api/v1/**',lambda route:route.fulfill(json={'mode':'preview','supabase_url':None,'publishable_key':None}))
        await workspace.goto(origin+'/')
        await workspace.evaluate('''()=>{
          state.session={access_token:'synthetic-memory-only'};
          portal.profile={tenant_id:'synthetic-workspace',workspace_role:'OWNER'};
          api=async(path,options)=>{
            if(path!=='/api/v1/help/search-agent')throw Error('Unexpected bridge action');
            return (await fetch(path,{method:options.method,headers:{'Content-Type':'application/json'},body:JSON.stringify(options.body)})).json();
          };
        }''')
        await workspace.route('**/api/v1/help/search-agent', lambda route: route.fulfill(json={
            'answer': '<script>untrusted text</script> Wallet credit is captured after label confirmation.',
            'sources': [{'title': 'Booking guidance', 'url': '/help/features/labels-and-tracking'}],
            'mode': 'AI_CITED_ANSWER'}))
        await page.get_by_role('button', name='Ask the help assistant').click()
        await expect(page.locator('#support-agent-answer')).to_contain_text('Wallet credit is captured')
        assert await page.locator('#support-agent-answer script').count() == 0
        await expect(page.locator('#support-agent-answer .support-answer-sources a')).to_have_attribute('href', '/help/features/labels-and-tracking')
        await workspace.route('**/api/v1/help/search-agent', lambda route: route.fulfill(json={
            'answer': 'Your wallet is charged only after the shipping service confirms the label purchase.\n\nWhen you confirm a booking, the amount is reserved first. If the purchase is rejected, that reservation is released.',
            'sources': [{'title': 'When is my wallet charged?', 'url': '/help/booking-payments#wallet-charge'}],
            'mode': 'AI_CITED_ANSWER'}))
        await page.get_by_role('button', name='Ask the help assistant').click()
        await expect(page.locator('#support-agent-answer')).to_contain_text('the amount is reserved first')
        assert await page.locator('.help-hero #support-agent-answer').count() == 0
        assert await page.locator('#support-agent-answer').evaluate("element => getComputedStyle(element).textAlign === 'left' && element.getBoundingClientRect().width <= 860")
        await page.locator('#support-agent-answer').screenshot(path=str(output / 'assistant-desktop.png'))
        await page.set_viewport_size({'width': 390, 'height': 844})
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await page.locator('#support-agent-answer').screenshot(path=str(output / 'assistant-mobile.png'))
        await workspace.route('**/api/v1/help/search-agent', lambda route: route.fulfill(json={
            'answer': 'Related guides', 'sources': [{'title': 'Wallet charges', 'url': '/help/booking-payments#wallet-charge'}],
            'excerpts': [{'title': 'When is my wallet charged?', 'url': '/help/booking-payments#wallet-charge', 'text': 'Credit is reserved first. The charge completes after label confirmation.'}],
            'fallback_reason': 'AI_NOT_CONFIGURED', 'mode': 'DOCUMENT_EXCERPTS'}))
        await page.get_by_role('button', name='Ask the help assistant').click()
        await expect(page.locator('#support-agent-answer')).to_contain_text('AI answers are not enabled on this server')
        await expect(page.locator('#support-agent-answer .support-answer-guides')).to_contain_text('Credit is reserved first')
        assert await page.locator('#support-agent-answer ul').count() == 0
        await page.screenshot(path=str(output / 'assistant-fallback-mobile.png'), full_page=True)
        # Full authored setup answers survive the bridge and remain visible without AI.
        full_answer = 'From the EasyInvio Help Centre:\n\n1. Open Store Integrations.\n\n' + ('Documented setup detail. ' * 150) + '\n\n6. Verify the final Amazon import activity.'
        await workspace.route('**/api/v1/help/search-agent', lambda route: route.fulfill(json={
            'answer':full_answer,'sources':[{'title':'Connect Amazon','url':'/help/connect-amazon#setup-steps-with-a-uk-example'}],
            'excerpts':[],'mode':'DOCUMENT_EXCERPTS','fallback_reason':'AI_NOT_CONFIGURED'}))
        await page.get_by_role('button',name='Ask the help assistant').click()
        await expect(page.locator('#support-agent-answer')).to_contain_text('6. Verify the final Amazon import activity.')
        external='https://developer-docs.amazon/sp-api/docs/orders-api'
        await workspace.route('**/api/v1/help/search-agent', lambda route: route.fulfill(json={
            'answer':'General web guidance, not verified EasyInvio setup.\n\nCheck the official order API [1].',
            'sources':[{'title':'Amazon Orders API','url':external},{'title':'Unsafe','url':'https://127.0.0.1/private'}],
            'excerpts':[],'mode':'WEB_CITED_ANSWER'}))
        await page.get_by_role('button',name='Ask the help assistant').click()
        await expect(page.locator('#support-agent-answer .support-answer-body a')).to_have_attribute('href',external)
        assert await page.locator('#support-agent-answer a[href*="127"]').count()==0
        await expect(page.locator('#support-agent-answer .support-answer-badge')).to_have_text('General web guidance')
        # A response from a workspace that changed while answering must not cross scopes.
        requested=asyncio.Event();release=asyncio.Event()
        async def delayed(route):
            requested.set();await release.wait()
            await route.fulfill(json={'answer':'STALE_SCOPE_ANSWER','mode':'AI_CITED_ANSWER','sources':[]})
        await workspace.route('**/api/v1/help/search-agent',delayed)
        await page.get_by_role('button',name='Ask the help assistant').click()
        await asyncio.wait_for(requested.wait(),5)
        await workspace.evaluate("portal.profile.tenant_id='changed-synthetic-workspace'")
        release.set()
        await expect(page.locator('#support-agent-answer')).to_contain_text('Assistance is unavailable')
        assert 'STALE_SCOPE_ANSWER' not in await page.locator('#support-agent-answer').inner_text()
        await page.set_viewport_size({'width': 1440, 'height': 1100})
        assert await page.evaluate("localStorage.getItem('easyinvio.session')") is None
        await page.locator('#supportSearch').fill('')
        await expect(page.locator('#support-agent-answer')).to_be_hidden()
        await page.screenshot(path=str(output / 'desktop.png'), full_page=True)
        await page.locator('#supportSearch').fill('card payment')
        await expect(page.locator('#support-results-list')).to_contain_text('Add credit and check a card payment')
        await page.locator('#support-results-list a').filter(has_text='Add credit').click()
        await expect(page.get_by_role('heading', name='I paid, but the balance is unchanged')).to_be_visible()
        await page.screenshot(path=str(output / 'payment-guide.png'), full_page=True)
        await page.goto(origin + '/help?q=bulk')
        await expect(page.locator('#support-results-list .status')).to_have_text('Guide being prepared')
        await page.locator('#support-results-list a').click()
        await expect(page.locator('.help-article .notice')).to_contain_text('Guide being prepared')
        await page.goto(origin + '/help')
        await page.locator('#supportSearch').fill('zzzxqq-no-match')
        await expect(page.locator('#support-search-status')).to_contain_text('No matching guide')
        await page.locator('#support-search-clear').click()
        await expect(page.locator('#support-search-results')).to_be_hidden()
        await page.goto(origin + '/help/contact')
        await page.locator('[name=topic]').select_option('Wallet or card payment')
        await page.locator('[name=reference]').fill('QA-HELP-ONLY')
        await page.locator('[name=message]').fill('My card payment was confirmed but the balance is unchanged.')
        await page.get_by_role('button', name='Prepare email draft').click()
        draft = await page.locator('#help-email-draft').get_attribute('href')
        parsed = urlsplit(draft)
        assert parsed.scheme == 'mailto' and parsed.path == 'support@easyinvio.com'
        assert 'QA-HELP-ONLY' in parse_qs(parsed.query)['subject'][0]
        await expect(page.locator('#help-contact-status')).to_contain_text('Nothing has been sent yet')
        await page.screenshot(path=str(output / 'contact.png'), full_page=True)
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.goto(origin + '/help')
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await page.screenshot(path=str(output / 'mobile.png'), full_page=True)
        await page.locator('#supportSearch').fill('dimensions')
        await expect(page.locator('#support-results-list')).to_contain_text('Why size affects the price')
        await page.locator('#support-results-list a').filter(has_text='Why size').click()
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await page.goto(origin + '/help')
        await expect(page.locator('.feature-guide-grid > a')).to_have_count(6)
        await page.locator('#supportSearch').fill('ACTION_REQUIRED')
        await expect(page.locator('#support-results-list')).to_contain_text('Understand statuses')
        await page.locator('#support-results-list a').filter(has_text='Understand statuses').click()
        await expect(page.get_by_role('heading',name='Understand statuses and resolve unexpected results',exact=True)).to_be_visible()
        await expect(page.get_by_role('heading',name='Claims — ACTION_REQUIRED',exact=True)).to_be_visible()
        assert 10 < await page.locator('.guide-contents a').count() < 20
        await page.set_viewport_size({'width':390,'height':844})
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await page.screenshot(path=str(output/'status-guide-mobile.png'))
        await page.goto(origin+'/help')
        await page.locator('.feature-guide-grid a[href="/help/features/labels-and-tracking"]').click()
        await page.get_by_role('link', name='How delivery history is measured', exact=True).click()
        await expect(page.locator('#how-delivery-history-is-measured')).to_be_in_viewport()
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await page.screenshot(path=str(output / 'tracking-guide-mobile.png'), full_page=True)
        async with page.expect_download() as download_event:
            await page.get_by_role('link', name='Download this guide as Markdown').click()
        assert (await download_event.value).suggested_filename == 'docs_tracking_branding.md'
        await page.set_viewport_size({'width': 1440, 'height': 1100})
        await page.goto(origin + '/help/features/carrier-pickups')
        await expect(page.locator('.help-article')).to_contain_text('does not offer dashboard courier pickup scheduling')
        await page.screenshot(path=str(output / 'collection-guide.png'), full_page=True)
        await page.goto(origin + '/help/unknown')
        await expect(page.get_by_role('heading', name='We could not find that guide')).to_be_visible()
        assert not errors, errors
        await browser.close()
    report = {'status': 'PASS', 'desktop_width': 1440, 'mobile_width': 390, 'page_errors': errors,
              'checks': ['Signed-out help access', 'Assistant sign-in guidance', 'Memory-only authenticated help bridge', 'Workspace-switch response fencing', 'Cited assistant response with safe text rendering', 'Desktop and mobile layout', 'Search and guide navigation',
                         'Bookmarked search', 'Clearly labelled feature placeholders', 'No-results and clear controls',
                         'Encoded support email draft without sending', 'Useful missing-guide page', 'Six detailed guides including status reference', 'Markdown downloads', 'Contents anchors', 'Honest collection limitations'],
              'database_calls': 0, 'provider_calls': 0, 'messages_sent': 0}
    (output / 'browser-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    app = FastAPI()
    app.include_router(router)
    @app.get('/')
    async def frontend():
        return FileResponse('index.html')
    @app.get('/manifest-workflow.js')
    async def manifest_asset():
        return FileResponse('manifest-workflow.js',media_type='text/javascript')
    @app.get('/help-workspace-bridge.js')
    async def help_bridge():
        return FileResponse('help-workspace-bridge.js',media_type='text/javascript')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError('Isolated help server did not start')
            time.sleep(.05)
        asyncio.run(run(origin))
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
