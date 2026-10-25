"""Owner CRM timeline links, escaping and responsive Client Accounts Hub."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from playwright.async_api import async_playwright, expect


async def run():
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
    env=os.environ.copy();env['PORT']='8006'
    server=subprocess.Popen([sys.executable,'main.py','--local-preview'],env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    errors=[]
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
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
            uid=str(uuid4())
            profile={'portal_role':'SUPER_ADMIN','user_id':uid,'tenant_id':None}
            identity={'user_id':uid,'email':'owner@example.invalid','role':'SUPER_ADMIN','full_name':'Synthetic Owner'}
            clients=[{'tenant_id':str(uuid4()),'company_name':'<script>bad</script>','billing_email':'test@example.invalid',
                'workspace_slug':'sample','billing_plan':'PREPAID_WALLET','default_currency':'GBP','workspace_status':'ACTIVE',
                'is_sandbox':True,'crm_scope':'UAT','hubspot_portal_id':'12345','hubspot_company_id':'67890'},
                {'tenant_id':str(uuid4()),'company_name':'Malformed CRM identity','is_sandbox':False,'crm_scope':'PRODUCTION',
                 'hubspot_portal_id':'12345','hubspot_company_id':'javascript:bad'}]
            async def mock(route):
                path=urlsplit(route.request.url).path
                if path=='/api/v1/auth/token':data={'access_token':'synthetic-owner','expires_at':int(time.time())+900,'absolute_expires_at':int(time.time())+3600,'user':{'id':uid,'email':identity['email']},'bootstrap':{'profile':profile,'identity':identity}}
                elif path=='/api/v1/auth/me':data=identity
                elif path=='/api/v1/profile':data=profile
                elif path=='/api/v1/config':data={'mode':'configured'}
                elif path=='/api/v1/admin/tenants':data={'tenants':clients,'crm':{'enabled':True,'environment':'PRODUCTION'}}
                else:data={'tickets':[],'shipments':[],'rules':[],'stores':[],'items':[],'notifications':[],'alerts':[],'has_more':False,'connections':[],'providers':[],'transactions':[],'totals_by_currency':[],'carriers':[],'active_support':[],'billing_pipeline':[],'payment_pipeline':[],'cohorts':{'shipping':[],'tickets':[],'accounts':[]}}
                await route.fulfill(json=data)
            await page.route('**/api/**',mock)
            await page.route('https://**',lambda route:route.abort())
            await page.goto('http://127.0.0.1:8006',wait_until='domcontentloaded')
            await page.wait_for_function("state.mode!=='checking'")
            await page.locator('#identity-email').fill(identity['email'])
            await expect(page.locator('#identity-email')).to_have_value(identity['email'])
            await page.locator('#identity-password').fill('synthetic-password')
            await page.locator('#identity-login-submit').click()
            await expect(page.locator('.app-shell')).to_be_visible()
            await page.evaluate("setView('admin-clients')")
            await expect(page.locator('#tenant-rows')).to_contain_text('UAT test account')
            link=page.locator('#tenant-rows a')
            await expect(link).to_have_count(1)
            await expect(link).to_have_attribute('href','https://app.hubspot.com/contacts/12345/record/0-2/67890')
            await expect(link).to_have_attribute('rel','noopener noreferrer')
            await expect(page.locator('#tenant-rows tr').nth(1)).to_contain_text('Not linked')
            await expect(page.locator('#tenant-rows tr').first).to_contain_text('UAT test account')
            assert await page.locator('#tenant-rows script').count()==0
            for width in [375,768,1024,1366]:
                await page.set_viewport_size({'width':width,'height':900})
                assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1
            await page.locator('#identity-logout').click()
            await expect(page.locator('#admin-clients')).to_be_hidden()
            assert not errors,errors
            await browser.close()
        print(json.dumps({'owner_timeline_link':True,'untrusted_ids_rejected':True,'company_text_escaped':True,
            'client_hub_hidden':True,'responsive_widths':[375,768,1024,1366],'javascript_errors':0}))
    finally:
        server.terminate();server.wait(timeout=15)


if __name__=='__main__': asyncio.run(run())
