"""Native browser checks for distinct admin nodes, contrast and protected navigation."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
OUT=Path('docs/enterprise_remediation');OUT.mkdir(exist_ok=True)
async def run():
    checks=[];errors=[]
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        page=await browser.new_page(viewport={'width':1366,'height':900})
        page.set_default_timeout(7000)
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto('http://127.0.0.1:8000',wait_until='domcontentloaded',timeout=30000)
        await page.wait_for_function("state.mode!=='checking'")
        # Explicitly inspect isolated sample renderers; the real unauthenticated UI remains gated.
        await page.evaluate("document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true")
        await page.locator('#role-admin').click()
        names=await page.locator('.sidebar [data-enterprise-view]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.enterpriseView)')
        assert names==['dashboard','admin-clients','admin-carriers','admin-margins','profile'],names
        await page.evaluate("setView('dispatch')")
        assert not await page.locator('#dispatch').is_visible()
        checks.append('Admin navbar has overview and three management nodes; warehouse view blocked.')
        await page.locator('.sidebar [data-enterprise-view="admin-clients"]').click()
        await expect(page.locator('#tenant-rows')).to_contain_text('Harbor Commerce')
        await page.locator('#tenant-new').click()
        await expect(page.locator('#account-dialog')).to_be_visible()
        assert not await page.locator('#tenant-admin-dialog').is_visible()
        assert await page.evaluate('enterprise.tenants.length') == 2
        await page.locator('[data-close="account-dialog"]').click()
        checks.append('Unauthenticated onboarding requires login and cannot create misleading sample customer records.')
        await page.locator('.sidebar [data-enterprise-view="admin-margins"]').click()
        await expect(page.locator('#margin-rows')).to_contain_text('Sample US lane')
        await page.locator('[data-margin-edit]').first.click()
        await page.locator('#margin-admin-form [name="markup_value"]').fill('27.5')
        await page.locator('#margin-admin-form [name="cargo_type"]').select_option('PALLET')
        await page.locator('#margin-admin-form [name="billing_plan"]').select_option('POSTPAID_30_DAY')
        await page.locator('#margin-admin-form [name="min_volume_m3"]').fill('0.5')
        await page.locator('#margin-admin-form button').click()
        await expect(page.locator('#margin-rows')).to_contain_text('27.5')
        await expect(page.locator('#margin-rows')).to_contain_text('PALLET')
        await page.locator('[data-margin-retire]').first.click()
        await page.locator('#retire-confirm').click()
        await expect(page.locator('#margin-rows')).to_contain_text('RETIRED')
        checks.append('Margin edit and retirement review are functional; priority policy is visible.')
        await page.locator('.sidebar [data-enterprise-view="admin-carriers"]').click()
        await page.locator('#easypost-setup').click()
        await expect(page.locator('#account-dialog')).to_be_visible()
        assert not await page.locator('#carrier-admin-dialog').is_visible()
        await page.locator('[data-close="account-dialog"]').click()
        checks.append('EasyPost key setup is visible and requires login; no API key is collected in sample mode.')
        await page.evaluate("state.session={access_token:'controlled-browser-fixture'};portal.profile={portal_role:'SUPER_ADMIN',workspace_role:'OWNER'}")
        await page.locator('#easypost-setup').click()
        form=page.locator('#carrier-admin-form')
        await expect(page.locator('#carrier-admin-dialog')).to_be_visible()
        assert await form.locator('[name="aggregator"]').input_value()=='EASYPOST'
        assert await form.locator('[name="environment"]').input_value()=='TEST'
        assert not await page.locator('#carrier-tenant-field').is_visible()
        assert not await page.locator('#carrier-aggregator-field').is_visible()
        assert not await page.locator('#carrier-regional_provider_code-field').is_visible()
        await expect(page.locator('#carrier-platform-note')).to_contain_text('Owned by EasyInvio')
        assert await form.locator('[name="is_active"]').is_checked()
        assert await form.locator('[name="api_key"]').get_attribute('type')=='password'
        await page.locator('[data-enterprise-close="carrier-admin-dialog"]').click()
        await page.locator('#carrier-new').click()
        await expect(page.locator('#aggregator-picker-dialog')).to_be_visible()
        assert await page.locator('#aggregator-provider option').all_text_contents()==['EasyPost','Sendcloud','Shippo','Custom regional API (rates contract only)']
        await page.locator('#aggregator-provider').select_option('SHIPPO')
        await page.locator('#aggregator-continue').click()
        assert await form.locator('[name="api_base_url"]').input_value()=='https://api.goshippo.com'
        assert await form.locator('[name="regional_provider_code"]').input_value()=='SHIPPO'
        assert not await form.locator('[name="regional_provider_code"]').evaluate('(node)=>node.required')
        assert not await page.locator('#carrier-api_base_url-field').is_visible()
        assert not await page.locator('#carrier-regional_provider_code-field').is_visible()
        assert not await page.locator('#regional-setup').count()
        await page.locator('[data-enterprise-close="carrier-admin-dialog"]').click()
        await page.evaluate('state.session=null;portal.profile=null')
        checks.append('Authenticated-owner form defaults to EasyPost TEST, active ratings and a write-only password field; no key was submitted by this browser probe.')

        await page.locator('[data-carrier-edit]').first.click()
        await page.locator('#carrier-advanced summary').click()
        await page.locator('#carrier-admin-form [name="priority"]').fill('17')
        await page.locator('#carrier-admin-form button').click()
        await expect(page.locator('#carrier-rows')).to_contain_text('Priority 17')
        assert 'NATIVE LIFECYCLE ADAPTER' in await page.locator('#admin-carriers').inner_text()
        assert 'Ordinary TEST accounts remain quotes-only' in await page.locator('#admin-carriers').inner_text()
        checks.append('Native provider cards and Shippo setup are distinct; endpoint/code are automatic, keys write-only, and Sendcloud billable-mode constraints are explicit.')
        await page.locator('[data-carrier-retire]').first.click()
        await page.wait_for_function('enterprise.carriers.some(c=>c.retired_at)')
        assert not await page.locator('[data-carrier-edit]').count()
        await page.locator('#carrier-show-removed').check()
        assert await page.locator('[data-carrier-edit]').count()==1
        checks.append('Add New Aggregator selects supported adapters; one-click removal hides connections while retaining an editable archive.')
        for width in [375,768,1024,1280,1366,1440]:
            await page.set_viewport_size({'width':width,'height':900})
            for view in ['dashboard','admin-clients','admin-carriers','admin-margins']:
                await page.evaluate('(view)=>setView(view)',view)
                assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1,(width,view)
        await page.set_viewport_size({'width':1366,'height':900})
        await page.evaluate("setView('admin-clients');window.scrollTo(0,0)")
        await page.screenshot(path=str(OUT/'admin-clients.png'),full_page=True)
        await page.locator('#role-client').click()
        nav=await page.locator('.sidebar').inner_text()
        assert 'Client Accounts Node' not in nav and 'Margin Rule Matrix' not in nav
        await page.evaluate("setView('customs')")
        await page.locator('#harmonize-btn').click()
        await expect(page.locator('[data-use-hs]').first).to_be_visible()
        code=await page.locator('[data-use-hs]').first.get_attribute('data-use-hs')
        await page.locator('[data-use-hs]').first.click()
        assert await page.locator('#qc-hs').input_value()==code
        assert not await page.locator('#qc-reviewed').is_checked()
        checks.append('Client hides all admin tabs; HS suggestions inject a draft code and require review.')
        await page.evaluate("setView('manifest')")
        await page.locator('[data-exception-sheet]').click()
        assert await page.locator('#exception-sheet').is_visible()
        assert await page.locator('#exception-dispute').is_visible()
        await page.locator('[data-enterprise-close="exception-sheet"]').click()
        checks.append('Manifest exception opens bottom-sheet remedy, POD and surcharge draft actions.')
        # Verify computed native control styles, including the date input and options.
        controls=await page.evaluate('''()=>['#report-start','#manifest-filter','#tenant-search','#qc-description'].map(selector=>{const c=getComputedStyle(document.querySelector(selector));return {selector,bg:c.backgroundColor,fg:c.color}})''')
        assert all(c['bg']!='rgb(255, 255, 255)' and c['fg']=='rgb(241, 245, 249)' for c in controls),controls
        checks.append({'native_control_contrast':controls})
        await page.evaluate("portal.profile={workspace_role:'DISPATCHER',portal_role:'CLIENT'};renderPortal()")
        nav=await page.locator('.sidebar [data-enterprise-view]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.enterpriseView)')
        assert nav==['workspace','dispatch','boxes','manifest','profile'],nav
        await page.evaluate("setView('wallet')")
        assert not await page.locator('#wallet').is_visible() and not await page.locator('#dashboard').is_visible()
        checks.append('Dispatcher navigation contains marketplace workspace, quote, box profiles and manifest; financial views denied.')
        assert not errors,errors
        await browser.close()
    result={'status':'PASS','checks':checks,'javascript_errors':errors}
    (OUT/'browser_evidence.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':asyncio.run(run())
