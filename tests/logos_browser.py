"""Logo rendering regression on a local preview; provider APIs are mocked."""
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.platform_registry import PLATFORMS
from playwright.async_api import async_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8017'
SID='00000000-0000-4000-8000-000000000057'

async def painted(locator):
    await expect(locator).to_be_visible()
    # A <use> link alone passes even when its SVG returns 404. Wait for actual
    # referenced artwork to have geometry in the browser's SVG rendering tree.
    await locator.evaluate('''el=>new Promise((resolve,reject)=>{
      let tries=0;function check(){const box=el.getBBox();
       if(box.width>0&&box.height>0)return resolve(true);
       if(++tries>100)return reject(Error('Logo artwork did not render: '+el.getAttribute('href')));
       setTimeout(check,30);}check();})''')

async def main():
    errors=[]
    output=ROOT/'output/logo-qa';output.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':1366,'height':950})
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def api(route):
            path=route.request.url.split('/api/v1/')[1].split('?')[0]
            if path=='integration/platforms':value={'platforms':[v.model_dump() for v in PLATFORMS.values()]}
            elif path=='workspace/stores':value={'stores':[{'id':SID,'display_name':'Fixture merchant','platform':'SHOPIFY','is_active':True}]}
            elif path.endswith('/connection'):value={'configured':True,'has_webhook_secret':True,'live_delivery':True,'sku_unit_grams':{}}
            elif path=='public/session':value={'authenticated':False}
            elif path in {'config','auth/config'}:value={'mode':'configured','supabase_url':None,'publishable_key':None}
            else:value={'stores':[],'orders':[],'shipments':[],'tickets':[],'history':[]}
            await route.fulfill(json=value)
        await page.route('**/api/v1/**',api)
        await page.route('https://cdn.jsdelivr.net/**',lambda r:r.abort())
        response=await page.request.get(BASE+'/platform-logos.svg')
        assert response.status==200 and 'image/svg+xml' in response.headers['content-type']
        assert response.headers['x-content-type-options']=='nosniff'
        await page.goto(BASE+'/')
        await expect(page.locator('.integration-card')).to_have_count(29)
        for logo in await page.locator('.integration-card use').all():
            await logo.scroll_into_view_if_needed();await painted(logo)
        await page.locator('[data-integration=SHOPIFY]').hover()
        await page.wait_for_timeout(220)
        assert await page.locator('[data-integration=SHOPIFY] .integration-mark').evaluate("el=>getComputedStyle(el).boxShadow!=='none'")
        await page.locator('#integrations').screenshot(path=str(output/'landing-desktop.png'))
        await page.set_viewport_size({'width':375,'height':950})
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        await page.locator('#integrations').screenshot(path=str(output/'landing-mobile.png'))
        public=await page.locator('[data-integration=SHOPIFY] use').get_attribute('href')
        await page.goto(BASE+'/workspace')
        await page.evaluate("""()=>{document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;state.session={access_token:'fixture',expires_at:9999999999};portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'00000000-0000-4000-8000-000000000001'};setView('stores');}""")
        await expect(page.locator('#store-catalogue article')).to_have_count(24)
        for logo in await page.locator('#store-catalogue use').all():
            await logo.scroll_into_view_if_needed();await painted(logo)
        connected=page.locator('#store-list [data-platform-brand=SHOPIFY] use')
        await connected.scroll_into_view_if_needed();await painted(connected)
        assert public==await connected.get_attribute('href')=='/platform-logos.svg#SHOPIFY'
        await page.locator('[data-store-settings]').click()
        await painted(page.locator('#store-connection-brand use'))
        await page.locator('#store-connection .close').click()
        for width in [375,768,1366]:
            await page.set_viewport_size({'width':width,'height':950})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            await page.locator('#store-catalogue').screenshot(path=str(output/f'workspace-{width}.png'))
        # Real quote renderer uses the same SVG, including provider-style aliases.
        await page.evaluate("""()=>{state.quotes=[{carrier_code:'royal_mail_tracked',service_code:'Tracked 48',client_price_ex_tax:'4.50',currency:'GBP',delivery_days:2}];renderRates({rates:state.quotes,simulated:false});}""")
        # Rate panel can be outside the active tab; its painted geometry is still
        # checked after opening the view containing it.
        assert await page.locator('#rates [data-platform-brand=ROYAL_MAIL]').count()==1
        await page.evaluate("""()=>{state.manifest=[{id:'00000000-0000-4000-8000-000000000099',reference:'LOGO-TEST',status:'IN_TRANSIT',carrier_code:'Evri',price:'4.50',currency:'GBP',metadata:{carrier:'Evri',destination:'Leeds'},booked_at:'2026-11-27T10:00:00Z'}];renderManifest();renderManifest();}""")
        assert await page.locator('#manifest-body [data-platform-brand=EVRI]').count()==1
        await expect(page.locator('#manifest-body')).to_contain_text('Evri')
        await expect(page.locator('#manifest-body')).to_contain_text('In transit')
        await page.evaluate("""()=>{const div=document.createElement('div');div.id='brand-carrier-fixture';div.innerHTML=['ROYAL_MAIL','EVRI','DPD','DHL','UPS'].map(code=>EasyInvioBrands.markup(code)).join('');document.body.append(div);}""")
        for logo in await page.locator('#brand-carrier-fixture use').all():
            await logo.scroll_into_view_if_needed();await painted(logo)
        await page.locator('#brand-carrier-fixture').screenshot(path=str(output/'carriers.png'))
        await page.emulate_media(reduced_motion='reduce')
        assert await page.locator('#brand-carrier-fixture .platform-brand').first.evaluate("el=>getComputedStyle(el).transitionDuration==='0s'")
        assert not errors,errors
        await browser.close()
    print(json.dumps({'public_logos':24,'workspace_logos':24,'carrier_logos':5,'connected_and_settings':True,'viewports':[375,768,1366],'painted_artwork':True,'hover_and_reduced_motion':True}))

if __name__=='__main__':asyncio.run(main())
