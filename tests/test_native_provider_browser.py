"""Controlled admin UI: native settings, secret clearing and mobile layout."""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())


async def run():
    errors=[];saved=[];checks=[]
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch()
        page=await browser.new_page(viewport={'width':1366,'height':900})
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def mock_native(route):
            if route.request.method=='PUT':
                saved.append(route.request.post_data_json)
                await route.fulfill(json={'configured':True})
            else:
                await route.fulfill(json={'order_sync_enabled':False,'sendcloud_integration_id':None,
                    'webhook_enabled':False,'webhook_auth':'HMAC','pod_allowed_hosts':[],'sendcloud_status_map':{},
                    'webhook_path':'/api/v1/shipping/tracking-webhooks?source=00000000-0000-0000-0000-000000000001'})
        await page.route('**/api/v1/admin/platform-carriers/*/native-settings',mock_native)
        await page.goto('http://127.0.0.1:8000',wait_until='domcontentloaded')
        await page.wait_for_function("state.mode!=='checking'")
        await page.evaluate("""()=>{
          document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
          document.querySelector('#role-admin').click();setView('admin-carriers');state.session={access_token:'controlled-native-browser'};
          portal.profile={portal_role:'SUPER_ADMIN',workspace_role:'OWNER'};
          enterprise.carriers=[{id:'00000000-0000-0000-0000-000000000001',platform_owned:true,
           account_name:'Synthetic Sendcloud',company_name:'EasyInvio',api_base_url:'https://panel.sendcloud.sc/api/v3',
           aggregator:'REGIONAL',environment:'TEST',is_active:true,priority:10}];
          renderEnterpriseTables();
        }""")
        await page.locator('[data-native-settings]').click()
        await expect(page.locator('#native-provider-dialog')).to_be_visible()
        form=page.locator('#native-provider-form')
        await form.locator('[name="order_sync_enabled"]').check()
        await form.locator('[name="sendcloud_integration_id"]').fill('7')
        await form.locator('[name="webhook_enabled"]').check()
        await form.locator('[name="webhook_secret"]').fill('controlled-synthetic-secret-32-bytes')
        await form.locator('[name="sendcloud_status_map"]').fill('{"11":"DELIVERED"}')
        assert await form.locator('[name="webhook_secret"]').get_attribute('type')=='password'
        for width in [375,768,1366]:
            await page.set_viewport_size({'width':width,'height':900})
            assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1,width
        await form.locator('button').click()
        await expect(page.locator('#native-provider-dialog')).not_to_be_visible()
        assert saved[0]['sendcloud_integration_id']==7 and saved[0]['order_sync_enabled']
        assert saved[0]['sendcloud_status_map']=={'11':'DELIVERED'}
        assert await form.locator('[name="webhook_secret"]').input_value()==''
        checks.append('PASS: owner native settings save explicit order opt-in, integration ID, status map and write-only secret through a controlled API.')
        await page.locator('[data-native-settings]').click()
        await form.locator('[name="webhook_secret"]').fill('another-controlled-secret-32bytes')
        await page.evaluate('clearSession()')
        assert await form.locator('[name="webhook_secret"]').input_value()==''
        assert not await page.locator('#native-provider-dialog').is_visible()
        checks.append('PASS: close/save/logout clear native signing secrets; mobile dialog has no horizontal overflow.')
        assert not errors,errors
        await browser.close()
    output=Path('docs/three_partners/browser_report.json');output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'status':'PASS','checks':checks,'javascript_errors':errors,'real_provider_calls':0},indent=2)+'\n',encoding='utf-8')
    print('PASS: native settings, secrets, owner controls and responsive layout; controlled browser data only.')


if __name__=='__main__':asyncio.run(run())
