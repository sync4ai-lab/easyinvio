"""Offline documentation QA. Does not start the application or providers."""
import asyncio
import json
import mimetypes
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import build_manual as builder


def content_checks():
    builder.validate(export=True)
    contracts=json.loads((builder.ROOT/'agent_contracts.json').read_text(encoding='utf-8'))
    assert {r['worker'] for r in contracts['model_calls']}=={
        'MarginOptimizerAgent','HelpSupportAgent','ConversationalIntentWorker','IngestionWorker',
        'CSVHeaderWorker','OfficialTariffRanker','CustomsHarmonizer'}
    assert {'ConversationalIntent','StrategicChoice','ConversationDraft','HSSelection','HeaderMapping','CitedAnswer'}<=set(contracts['schemas'])
    manual=(builder.ROOT/'manual.md').read_text(encoding='utf-8')
    for name in ['LogisticsSupervisor','IngestionWorkerAgent','CustomsHarmonizerAgent',
        'MarginOptimizerAgent','InvoiceSurchargeAuditorAgent','ProactiveClaimsSupportAgent',
        'HelpRetriever','ConversationalActionGateway','ConversationalSignupManager','ReverseLogisticsService',
        'TRIGGER_RETURN','PENDING_PERSONA','individual_global_markup_percent','reverse_logistics_requests']:
        assert name in manual,name
    # Detect likely actual credentials without printing any matching content.
    patterns=[r'\bsk_live_[A-Za-z0-9]{16,}',r'\bsb_secret_[A-Za-z0-9_-]{16,}',
        r'\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}',
        r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}']
    for file in builder.artifacts():
        if file.suffix in {'.md','.json','.html','.py','.svg','.mmd'}:
            text=file.read_text(encoding='utf-8')
            assert '\ufffd' not in text,'Invalid text encoding: '+file.name
            assert not any(re.search(pattern,text) for pattern in patterns),'Possible credential in '+file.name


async def browser_checks():
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(builder.PROJECT/'.playwright'))
    from playwright.async_api import async_playwright
    output=builder.PROJECT/'output/architecture-refresh/qa'
    output.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as driver:
        browser=await driver.chromium.launch()
        page=await browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
        page.set_default_timeout(10000)
        errors=[];external=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def route(handler):
            parsed=urlsplit(handler.request.url)
            if parsed.hostname!='architecture.test':
                external.append(parsed.hostname);return await handler.abort()
            name=unquote(parsed.path).lstrip('/') or 'overview.html'
            if Path(name).name!=name or not (builder.ROOT/name).is_file():return await handler.fulfill(status=404,body='Not found')
            mime=mimetypes.guess_type(name)[0] or 'application/octet-stream'
            return await handler.fulfill(content_type=mime,body=(builder.ROOT/name).read_bytes())
        await page.route('**/*',route)
        await page.goto('https://architecture.test/overview.html',wait_until='networkidle')
        assert await page.locator('article').count()==len(builder.CHAPTERS)
        assert await page.locator('#architecture-diagrams figure').count()==6
        assert await page.locator('#technology-versions tbody tr').count()==len(builder.PACKAGES)
        for term in ['TRIGGER_RETURN','PENDING_PERSONA','individual_global_markup_percent',
            'reverse_logistics_requests','/api/v1/shipping/prepare-return']:
            await page.locator('#manual-search').fill(term)
            await page.wait_for_function("term=>document.querySelector('#search-results')?.textContent.toLowerCase().includes(term.toLowerCase())",arg=term)
            await page.locator('#search-results li a').first.click()
            target=await page.evaluate('location.hash.slice(1)')
            assert await page.locator('[id="'+target+'"]').count()==1
        await page.locator('#manual-search').fill('zzzz_no_matching_manual_section_zzzz')
        await page.wait_for_function("document.querySelector('#search-status').textContent.startsWith('No matching')")
        await page.locator('#manual-search').fill('')
        for width in [375,768,1440]:
            await page.set_viewport_size({'width':width,'height':1000})
            await page.evaluate('window.scrollTo(0,0)')
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),width
            await page.screenshot(path=str(output/f'manual-{width}.png'),animations='disabled')
        await page.locator('aside nav a[href="#chapter-security-and-finance"]').click()
        await page.screenshot(path=str(output/'finance-chapter.png'),animations='disabled')
        for name in builder.DIAGRAMS:
            await page.set_content((builder.ROOT/(name+'.svg')).read_text(encoding='utf-8'))
            await page.evaluate('document.fonts.ready')
            bad=await page.locator('svg g[data-node]').evaluate_all('''groups=>groups.flatMap(g=>{
                const box=g.querySelector('rect').getBBox();
                return [...g.querySelectorAll('text')].filter(t=>{
                    const b=t.getBBox();return b.x<box.x+10||b.x+b.width>box.x+box.width-8||b.y<box.y+10||b.y+b.height>box.y+box.height-8;
                }).map(t=>({node:g.dataset.node,text:t.textContent}));
            })''')
            assert not bad,(name,bad)
        assert not errors,errors
        assert not external,external
        await browser.close()
    print('PASS: offline navigation/search, source/schema coverage, six unclipped diagrams, responsive widths, no external requests or likely credentials.')


if __name__=='__main__':
    content_checks()
    asyncio.run(browser_checks())
