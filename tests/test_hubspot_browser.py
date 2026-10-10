"""Owner CRM timeline links, escaping and responsive Client Accounts Hub."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
from playwright.async_api import async_playwright, expect


async def run():
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
    env=os.environ.copy();env['PORT']='8006'
    server=subprocess.Popen([sys.executable,'main.py','--local-preview'],env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    errors=[]
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(50):
                try:
                    if (await client.get('http://127.0.0.1:8006/health')).status_code==200: break
                except httpx.HTTPError: pass
                await asyncio.sleep(.2)
            else: raise RuntimeError('Preview startup failed')
        async with async_playwright() as pw:
            browser=await pw.chromium.launch()
            page=await browser.new_page(viewport={'width':1366,'height':900})
            page.on('pageerror',lambda e:errors.append(str(e)))
            await page.goto('http://127.0.0.1:8006',wait_until='domcontentloaded')
            await page.wait_for_function("state.mode!=='checking'")
            await page.locator('#role-admin').click()
            await page.locator('.sidebar [data-enterprise-view="admin-clients"]').click()
            await page.evaluate("""() => {
                enterprise.tenants=[{tenant_id:'test-owner-tenant',company_name:'<script>bad</script>',billing_email:'test@example.invalid',
                    workspace_slug:'sample',billing_plan:'PREPAID_WALLET',default_currency:'GBP',workspace_status:'ACTIVE',is_sandbox:true,
                    hubspot_portal_id:'12345',hubspot_company_id:'67890'},
                    {tenant_id:'test-malformed',company_name:'Malformed CRM identity',hubspot_portal_id:'12345',hubspot_company_id:'javascript:bad'}];
                renderEnterpriseTables();refreshIcons();
            }""")
            link=page.locator('#tenant-rows a')
            await expect(link).to_have_count(1)
            await expect(link).to_have_attribute('href','https://app.hubspot.com/contacts/12345/record/0-2/67890')
            await expect(link).to_have_attribute('rel','noopener noreferrer')
            await expect(page.locator('#tenant-rows tr').nth(1)).to_contain_text('Not synchronized')
            assert await page.locator('#tenant-rows script').count()==0
            for width in [375,768,1024,1366]:
                await page.set_viewport_size({'width':width,'height':900})
                assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1
            await page.locator('#role-client').click()
            await expect(page.locator('#admin-clients')).to_be_hidden()
            assert not errors,errors
            await browser.close()
        print(json.dumps({'owner_timeline_link':True,'untrusted_ids_rejected':True,'company_text_escaped':True,
            'client_hub_hidden':True,'responsive_widths':[375,768,1024,1366],'javascript_errors':0}))
    finally:
        server.terminate();server.wait(timeout=15)


if __name__=='__main__': asyncio.run(run())
