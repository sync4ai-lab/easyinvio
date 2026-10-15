"""Isolated desktop/mobile chat checks with intercepted requests only."""
import asyncio
import json
import os
import socket
import threading
import time
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright, expect

os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(Path('.playwright').resolve())


async def run(origin):
    calls, errors = [], []
    failed = [False]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 1366, 'height': 900})
        page.on('pageerror', lambda error: errors.append(str(error)))

        async def intercept(route):
            path = route.request.url.split('/api/v1/', 1)[1]
            if path == 'conversational/process-message':
                body = route.request.post_data_json
                calls.append(body)
                if body['message_body'] == 'Retry me' and not failed[0]:
                    failed[0] = True
                    await route.fulfill(status=503, json={'detail': 'Outcome could not be confirmed.'})
                    return
                data = {'status': 'COMPLETED', 'action_taken': 'HELP',
                    'conversational_reply': '<img src=x onerror=alert(1)>\nhttps://checkout.stripe.com/c/pay/synthetic'}
            elif path in ('config', 'auth/config'):
                data = {'mode': 'configured', 'supabase_url': None, 'publishable_key': None}
            else:
                data = {'items': [], 'orders': [], 'stores': [], 'tickets': [], 'shipments': [], 'has_more': False}
            await route.fulfill(json=data)

        await page.route('**/api/v1/**', intercept)
        await page.goto(origin, wait_until='domcontentloaded')
        await page.evaluate('''tenant=>{
            document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;
            state.session={access_token:'synthetic-chat',expires_at:Math.floor(Date.now()/1000)+3600};
            state.mode='configured';portal.role='CLIENT';portal.profile={tenant_id:tenant,workspace_role:'OWNER',portal_role:'CLIENT'};
        }''', str(uuid4()))
        await page.locator('#conversation-open').click()
        await page.locator('#conversation-message').fill('Help')
        await page.locator('#conversation-send').click()
        await expect(page.locator('#conversation-log')).to_contain_text('<img src=x onerror=alert(1)>')
        assert await page.locator('#conversation-log img').count() == 0
        await expect(page.locator('#conversation-log a')).to_have_attribute('rel', 'noopener noreferrer')
        assert calls[0]['channel'] == 'WEB_CHAT' and 'sender_id' not in calls[0]
        await page.locator('#conversation-message').fill('Retry me')
        await page.locator('#conversation-send').click()
        await expect(page.locator('#conversation-status')).to_contain_text('could not be confirmed')
        await page.locator('#conversation-send').click()
        await expect(page.locator('#conversation-message')).to_have_value('')
        assert calls[1]['request_id'] == calls[2]['request_id']
        # Renewal mutates the same session object; it should retain this chat.
        await page.evaluate("state.session.access_token='renewed-synthetic-chat'")
        await page.wait_for_timeout(1100)
        await expect(page.locator('#conversation-dialog')).to_be_visible()
        target = Path('output/conversational-chat')
        target.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(target / 'desktop.png'))
        await page.set_viewport_size({'width': 390, 'height': 844})
        bounds = await page.locator('#conversation-dialog').bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
        await page.screenshot(path=str(target / 'mobile.png'))
        await page.evaluate('clearSession()')
        await expect(page.locator('#conversation-dialog')).not_to_be_visible()
        assert await page.locator('#conversation-log').text_content() == ''
        assert not errors, errors
        await browser.close()
    print(json.dumps({'status': 'PASS', 'requests': len(calls), 'javascript_errors': errors,
        'checks': ['Session-authenticated payload', 'Text-only rendering', 'Safe Stripe links',
            'Stable retry request ID', 'Renewal preserves chat', 'Mobile dialog fits', 'Logout clears chat']}, indent=2))


if __name__ == '__main__':
    app = FastAPI()

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
                raise RuntimeError('Isolated server did not start')
            time.sleep(.05)
        asyncio.run(run(origin))
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
