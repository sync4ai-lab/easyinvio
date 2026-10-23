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
    calls, errors, authorizations = [], [], []
    delayed = asyncio.Event()
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
                authorizations.append(route.request.headers.get('authorization'))
                if body['message_body'] == 'Delayed':
                    await delayed.wait()
                else:
                    await asyncio.sleep(.15)
                if body['message_body'] == 'Retry me' and not failed[0]:
                    failed[0] = True
                    await route.fulfill(status=503, json={'detail': 'Outcome could not be confirmed.'})
                    return
                data = {'status': 'COMPLETED', 'action_taken': 'HELP',
                    'conversational_reply': '<img src=x onerror=alert(1)>\nhttps://checkout.stripe.com/c/pay/synthetic\nhttps://developer-docs.amazon/sp-api/docs/orders-api\nhttps://127.0.0.1/private'}
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
        await expect(page.locator('#conversation-open')).to_have_attribute('aria-expanded', 'true')
        await page.locator('#conversation-message').fill('Help')
        await page.locator('#conversation-message').press('Enter')
        await page.locator('#conversation-message').press('Enter')
        await expect(page.locator('#conversation-log')).to_contain_text('<img src=x onerror=alert(1)>')
        assert await page.locator('#conversation-log img').count() == 0
        await expect(page.locator('#conversation-log a').first).to_have_attribute('rel', 'noopener noreferrer')
        assert await page.locator('#conversation-log a[href*=developer-docs]').count()==1
        assert await page.locator('#conversation-log a[href*="127"]').count()==0
        assert len(calls) == 1
        assert authorizations == ['Bearer synthetic-chat']
        assert calls[0]['channel'] == 'WEB_CHAT' and 'sender_id' not in calls[0]
        await page.locator('#conversation-message').fill('Retry me')
        await page.locator('#conversation-send').click()
        await expect(page.locator('#conversation-status')).to_contain_text('could not be confirmed')
        await page.locator('#conversation-send').click()
        await expect(page.locator('#conversation-message')).to_have_value('')
        assert calls[1]['request_id'] == calls[2]['request_id']
        assert await page.locator('.conversation-bubble[data-speaker=You]').count() == 2
        await page.locator('#conversation-message').fill('Two')
        await page.locator('#conversation-message').press('Shift+Enter')
        await expect(page.locator('#conversation-message')).to_have_value('Two\n')
        assert len(calls) == 3
        await page.locator('#conversation-message').press('Escape')
        await expect(page.locator('#conversation-dialog')).not_to_be_visible()
        await expect(page.locator('#conversation-open')).to_be_focused()
        await page.locator('#conversation-open').click()
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
        trigger_bounds = await page.locator('#conversation-open').bounding_box()
        nav_bounds = await page.locator('.mobile-nav').bounding_box()
        assert trigger_bounds['y'] + trigger_bounds['height'] < nav_bounds['y']
        assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] < trigger_bounds['y']
        await page.screenshot(path=str(target / 'mobile.png'))
        await page.locator('#conversation-message').fill('Delayed')
        await page.locator('#conversation-message').press('Enter')
        await expect(page.locator('#conversation-log')).to_have_attribute('aria-busy', 'true')
        await page.evaluate('clearSession()')
        delayed.set()
        await page.wait_for_timeout(250)
        await expect(page.locator('#conversation-dialog')).not_to_be_visible()
        assert await page.locator('#conversation-log').text_content() == ''
        assert len(authorizations) == 4 and all(value and value.startswith('Bearer ') for value in authorizations)
        assert not errors, errors
        await browser.close()
    print(json.dumps({'status': 'PASS', 'requests': len(calls), 'javascript_errors': errors,
        'checks': ['Bearer-authenticated payload', 'Duplicate-send protection', 'Keyboard controls', 'Text-only rendering', 'Safe Stripe links',
            'Stable retry request ID', 'Renewal preserves chat', 'Mobile floating panel fits', 'Logout clears chat and ignores late replies']}, indent=2))


if __name__ == '__main__':
    app = FastAPI()

    @app.get('/')
    async def frontend():
        return FileResponse('index.html')

    from scripts.build_vercel import ASSETS
    @app.get('/{asset}')
    async def frontend_asset(asset: str):
        if asset not in ASSETS:
            from fastapi import HTTPException
            raise HTTPException(404)
        return FileResponse(asset)

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
