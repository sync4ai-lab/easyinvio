"""Actual downloaded CSV round trip and interactive customs review in preview."""
import asyncio
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright,expect

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())


async def run():
    env=os.environ.copy();env['PORT']='8002'
    server=subprocess.Popen([sys.executable,'main.py','--local-preview'],cwd=Path.cwd(),env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    evidence=[];errors=[]
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(40):
                if server.poll() is not None:raise RuntimeError('Preview server failed to start')
                try:
                    if (await client.get('http://127.0.0.1:8002/health')).status_code==200:break
                except httpx.HTTPError:pass
                await asyncio.sleep(.25)
            else:raise RuntimeError('Preview server did not become ready')
        from tests.smoke_http import run as smoke
        await asyncio.to_thread(smoke,'http://127.0.0.1:8002')
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch()
            page=await browser.new_page(viewport={'width':1366,'height':1000})
            page.on('pageerror',lambda error:errors.append(str(error)))
            await page.goto('http://127.0.0.1:8002',wait_until='domcontentloaded')
            await page.wait_for_function("state.mode==='local-preview'")
            await page.evaluate("setView('dispatch')")
            async with page.expect_download() as downloading:await page.locator('#csv-template').click()
            download=await downloading.value
            content=Path(await download.path()).read_bytes()
            rows=list(csv.DictReader(io.StringIO(content.decode('utf-8'))))
            assert len(rows)==4 and len(rows[0])==21
            assert rows[0]['recipient_phone']=="'+447700900001"
            await page.locator('#csv-file').set_input_files({'name':'downloaded.csv','mimeType':'text/csv','buffer':content})
            await page.locator('#batch-btn').click()
            await expect(page.locator('#batch-result')).to_contain_text('3/4 orders quoted')
            await expect(page.locator('#batch-result')).to_contain_text('1 need customs review')
            await expect(page.locator('#batch-result')).to_contain_text('SIMULATION')
            evidence.append('The actual standard download has 21 requested columns and uploads as three quotes plus one international review, with no writes.')
            await page.locator('[data-csv-review-row]').click()
            form=page.locator('#csv-review-form')
            await expect(form.locator('[name=description]')).to_have_value('Cotton T-shirt')
            await expect(form.locator('[name=hs_code]')).to_have_value('610910')
            await expect(form.locator('[name=origin_country]')).to_have_value('')
            await expect(form.locator('[name=unit_weight_kg]')).to_have_value('')
            await expect(form.locator('[name=hs_codes_reviewed]')).not_to_be_checked()
            for field,value in {'origin_country':'GB','unit_weight_kg':'2.000','customs_signer':'Browser Test Reviewer','destination_state':'NY'}.items():
                await form.locator(f'[name={field}]').fill(value)
            await form.locator('[name=postal_form]').select_option('CN23')
            await form.locator('[name=hs_codes_reviewed]').check()
            await form.locator('button[type=submit]').click()
            await expect(page.locator('#csv-review-output')).to_contain_text('Order quoted; no label purchased.')
            await expect(page.locator('#batch-result')).to_contain_text('4/4 orders quoted')
            doc=await page.evaluate('state.batch.results.find(r=>r.order_reference==="CSV-INTERNATIONAL-001").customs')
            assert doc['postal_form']=='CN23' and doc['items'][0]['hs_code']=='610910' and doc['ready_for_provider']
            evidence.append('Review prefilled description/value/HS suggestion but did not invent goods origin or net weight; explicit completion generated CN23-ready customs and refreshed the quote.')
            await page.locator('#csv-review-close').click()
            async with page.expect_download() as downloading:await page.locator('#batch-export').click()
            output=Path(await (await downloading.value).path()).read_text()
            assert 'Cargo' in output and 'CSV-INTERNATIONAL-001' in output
            evidence.append('Updated export preserves per-order cargo and processing results.')
            async with page.expect_download() as downloading:await page.locator('#csv-extended-template').click()
            extended=list(csv.DictReader(io.StringIO(Path(await (await downloading.value).path()).read_text())))
            assert 'store_id' in extended[0] and 'hs_codes_reviewed' in extended[0]
            evidence.append('Extended template includes customs-review facts and store association columns.')
            for width in [375,768,1366]:
                await page.set_viewport_size({'width':width,'height':1000})
                assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')==0
            assert not errors,errors
            await browser.close()
        Path('docs/bulk_csv').mkdir(exist_ok=True)
        result={'status':'PASS','checks':evidence,'javascript_errors':errors,'source':'real local-preview browser','database_writes':0}
        Path('docs/bulk_csv/browser_evidence.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)


if __name__=='__main__':asyncio.run(run())
