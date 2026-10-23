"""Real browser check of hosted polling and logout, with no real credentials."""
import asyncio
import json
import os
from pathlib import Path
import socket
import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright
import uvicorn

ROOT = Path(__file__).resolve().parents[1]


async def check(origin: str) -> None:
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.playwright')
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 1366, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        async def route(request):
            if request.request.url.startswith(origin):
                await request.continue_()
            else:
                await request.abort()

        await page.route('**/*', route)
        await page.goto(origin, wait_until='domcontentloaded')
        await page.wait_for_function("state.mode === 'local-preview'")
        await page.clock.install()
        await page.evaluate("""() => {
          window.hostingChecks = {refreshes: 0, sockets: 0};
          window.WebSocket = function() { hostingChecks.sockets++; throw Error('Unexpected socket'); };
          state.config.dispatch_updates_mode = 'POLLING';
          state.session = {access_token: 'synthetic-offline-session'};
          portal.profile = {tenant_id:'synthetic', workspace_role:'OWNER', portal_role:'CLIENT'};
          enterprise.currentView = 'workspace';
          loadDispatchWorkspace = async () => { hostingChecks.refreshes++; };
          connectDispatchUpdates();
          connectDispatchUpdates();
        }""")
        await page.clock.fast_forward(15001)
        await page.wait_for_function('hostingChecks.refreshes === 1')
        await page.clock.fast_forward(15001)
        await page.wait_for_function('hostingChecks.refreshes === 2')
        assert await page.evaluate('hostingChecks.sockets') == 0
        await page.evaluate('state.session = null; refreshEnterpriseNavigation();')
        await page.clock.fast_forward(30001)
        assert await page.evaluate('hostingChecks.refreshes') == 2
        assert await page.evaluate('dispatchLive.poll') is None
        assert not errors, errors
        await browser.close()
        print(json.dumps({'browser': 'passed', 'polling': 'single timer',
                          'websockets_in_web_mode': 0, 'logout': 'timer cleared'}))


def main() -> None:
    application = FastAPI()

    @application.get('/health')
    async def health():
        return {'status': 'ok', 'mode': 'local-preview'}

    @application.get('/api/v1/config')
    async def config():
        return {'mode': 'local-preview', 'supabase_url': None, 'publishable_key': None}

    @application.get('/')
    async def index():
        return FileResponse(ROOT / 'index.html')

    from scripts.build_vercel import ASSETS

    @application.get('/{asset}')
    async def asset(asset: str):
        if asset not in ASSETS:
            from fastapi import HTTPException
            raise HTTPException(404)
        return FileResponse(ROOT / asset)

    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(application, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        asyncio.run(check(f'http://127.0.0.1:{listener.getsockname()[1]}'))
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()


if __name__ == '__main__':
    main()
