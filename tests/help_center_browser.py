"""Isolated browser verification: public help only, no database or provider calls."""
import asyncio
import json
import os
import socket
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright, expect
from backend.help_center import router

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())


async def run(origin):
    output = Path('output/help-center')
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 1440, 'height': 1100})
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.route('**/api/v1/**', lambda route: route.fulfill(json={'mode': 'preview', 'supabase_url': None, 'publishable_key': None}))
        await page.goto(origin + '/')
        await expect(page.locator('#loginContainer a[href="/help"]')).to_be_visible()
        await page.locator('#loginContainer a[href="/help"]').click()
        await expect(page.get_by_role('heading', name='How can we help?')).to_be_visible()
        await expect(page.locator('.domain-card')).to_have_count(3)
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
        await expect(page.locator('.feature-guide-grid > a')).to_have_count(5)
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
              'checks': ['Signed-out help access', 'Desktop and mobile layout', 'Search and guide navigation',
                         'Bookmarked search', 'Clearly labelled feature placeholders', 'No-results and clear controls',
                         'Encoded support email draft without sending', 'Useful missing-guide page', 'Five feature guide links', 'Markdown downloads', 'Contents anchors', 'Honest collection limitations'],
              'database_calls': 0, 'provider_calls': 0, 'messages_sent': 0}
    (output / 'browser-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    app = FastAPI()
    app.include_router(router)
    @app.get('/')
    async def frontend():
        return FileResponse('index.html')
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
