"""Render checked-in vector branding into transparent platform icon sizes.

Maintenance command: python scripts/generate_brand_icons.py
Requires the existing development Playwright installation; no network requests.
"""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

async def main() -> None:
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.playwright'))
    source = (ROOT / 'brand-mark.svg').read_text(encoding='utf-8').replace('#34d399', '#047857')
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for filename, size in [('favicon-32.png',32), ('apple-touch-icon.png',180), ('app-icon-192.png',192), ('app-icon-512.png',512)]:
            page = await browser.new_page(viewport={'width':size,'height':size},device_scale_factor=1)
            await page.set_content('<style>html,body{margin:0;width:100%;height:100%;background:transparent}body{display:grid;place-items:center}svg{width:72%;height:80%;display:block}</style>'+source)
            await page.screenshot(path=str(ROOT/filename),omit_background=True)
            await page.close()
        await browser.close()
    print('Rendered four transparent app/favicon icons from brand-mark.svg')

if __name__ == '__main__':
    asyncio.run(main())
