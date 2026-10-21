"""Synthetic browser journeys; no provider calls, messages, labels or payments."""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.async_api import async_playwright
from manifest_workflow_browser import fixtures

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.playwright'))


async def main():
    target=ROOT/'output/return-workspace-qa';target.mkdir(parents=True,exist_ok=True)
    rows=fixtures()
    delivered=next(r for r in rows if r['status']=='DELIVERED')
    original=delivered['metadata']['automation_order']
    facts={'shipment_id':delivered['id'],'reference':delivered['reference'],'origin':original['destination'],
        'destination':original['origin'],'currency':'GBP','edits':{
            'cargo':{'cargo_type':'PARCEL','actual_weight_kg':'2.000','length_cm':'24','width_cm':'16','height_cm':'8','stackable':True},
            'items':[{'description':'Cotton shirt','quantity':1,'unit_value':'12.00','unit_weight_kg':'0.500','origin_country':'GB','hs_code':'610910'}],
            'customs_currency':'GBP','incoterm':'DAP','hs_codes_reviewed':False},
        'delivery_capabilities':{'email':False,'whatsapp':False,'notice':'Notifications disabled for synthetic QA.'},'notice':'Review original return details.'}
    offer=str(uuid4());report=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        for persona in ['OWNER','ADMIN','DISPATCHER','ACCOUNTANT','INDIVIDUAL','SUPER_ADMIN']:
            page=await browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            async def offline(route):
                if not route.request.url.startswith('http://127.0.0.1:8768'):return await route.abort()
                if '/api/' in route.request.url or '/v1/' in route.request.url:return await route.fulfill(status=503,json={'detail':'Synthetic disconnected API'})
                await route.continue_()
            await page.route('**/*',offline)
            await page.route_web_socket('**/*',lambda ws:ws.close())
            await page.goto('http://127.0.0.1:8768',wait_until='domcontentloaded')
            await page.evaluate('''({rows,facts,persona,offer})=>{
              window.returnCalls=[];window.testPayer='RETAILER_PAY';window.testOutcome='BOOKED';
              api=async(path,options={})=>{
                returnCalls.push({path,...options});
                if(path.endsWith('/manifest'))return{shipments:rows,server_time:new Date().toISOString()};
                if(path.endsWith('/preparation-context'))return facts;
                if(path.endsWith('/returns/review')){window.testRequest=options.body.request_id;return{status:'QUOTED',request_id:testRequest,
                  expires_at:new Date(Date.now()+300000).toISOString(),charge_bearer:options.body.charge_bearer,
                  rates:[{offer_id:offer,carrier_code:'EVRI',service_code:'STANDARD',client_price_ex_tax:'4.25',currency:'GBP',delivery_days:3}]};}
                if(path.endsWith('/select')||path.includes('/returns/reviews/'))return testOutcome==='BOOKED'
                  ?{status:'BOOKED',label_path:'/api/v1/shipping/'+facts.shipment_id+'/documents/label',notifications:[]}
                  :{status:'PAYMENT_REQUIRED',checkout_url:'https://checkout.stripe.com/c/pay/synthetic',notifications:[{kind:'PAYMENT',channel:'EMAIL',state:'READY'}]};
                return{};
              };
              state.session={access_token:'SYNTHETIC_ONLY',expires_at:Math.floor(Date.now()/1000)+3600};state.mode='configured';
              portal.role=persona==='SUPER_ADMIN'?'SUPER_ADMIN':'CLIENT';
              portal.profile={tenant_id:rows[0].tenant_id,portal_role:portal.role,
                workspace_role:['INDIVIDUAL','SUPER_ADMIN'].includes(persona)?'OWNER':persona,workspace_type:persona==='INDIVIDUAL'?'INDIVIDUAL':'BUSINESS'};
              document.body.classList.remove('auth-locked');document.body.classList.add('auth-ready');document.querySelectorAll('#identity-gate,#loginContainer,[data-identity-gate]').forEach(n=>n.style.display='none');
              refreshEnterpriseNavigation();setView('manifest');state.manifest=rows;renderManifest();
            }''',{'rows':rows,'facts':facts,'persona':persona,'offer':offer})
            allowed=persona in {'OWNER','ADMIN','DISPATCHER','INDIVIDUAL'}
            if persona!='SUPER_ADMIN':
                for row in rows:
                    count=await page.locator(f'[data-prepare-return="{row["id"]}"]').count()
                    assert bool(count)==(allowed and row['workflow']['can_return']),(persona,row['status'],count)
            if allowed:
                await page.locator(f'[data-prepare-return="{delivered["id"]}"]').first.click()
                await page.locator('#return-review-form').wait_for()
                assert await page.locator('#return-workspace').is_visible()
                assert await page.locator('#return-review-form [name=actual_weight_kg]').input_value()=='2.000'
                assert not await page.locator('#return-review-form [name=hs_codes_reviewed]').is_checked()
                assert not await page.locator('#return-workspace [name=maximum_price]').count()
                assert await page.locator('#return-review-form [name=send_email]').is_disabled()
                await page.locator('#return-review-form [name=actual_weight_kg]').fill('2.500')
                await page.get_by_role('button',name='Compare return services',exact=True).click()
                await page.get_by_role('heading',name='Choose a return service').wait_for()
                assert '4.25' in await page.locator('[data-return-options]').inner_text()
                sent=await page.evaluate('returnCalls.find(c=>c.path.endsWith("/returns/review")).body')
                assert sent['edits']['cargo']['actual_weight_kg']=='2.500'
                await page.get_by_role('button',name='Pay and create selected return label',exact=True).click()
                await page.get_by_role('button',name='Download return label PDF').wait_for()
                assert await page.evaluate('returnCalls.filter(c=>c.path.endsWith("/select")).length')==1
                if persona!='DISPATCHER':
                    await page.get_by_role('button',name='Back to Manifest & Labels',exact=True).click()
                    await page.locator(f'[data-prepare-return="{delivered["id"]}"]').first.click()
                    await page.locator('#return-review-form').wait_for()
                    await page.locator('[name=charge_bearer]').select_option('CUSTOMER_PAY')
                    await page.evaluate("testOutcome='PAYMENT_REQUIRED'")
                    await page.get_by_role('button',name='Compare return services',exact=True).click()
                    await page.get_by_role('button',name='Create payment link for selected service',exact=True).click()
                    await page.get_by_role('link',name='Open or copy customer payment link').wait_for()
                    assert not await page.get_by_role('button',name='Download return label PDF').count()
                    await page.get_by_role('button',name='Refresh payment, label and notification status').click()
                    assert 'EMAIL: READY' in await page.locator('[data-return-result]').inner_text()
                for width in (375,768,1440):
                    await page.set_viewport_size({'width':width,'height':1000})
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(persona,width)
                    if persona == 'OWNER':
                        await page.screenshot(path=str(target/f'return-{width}.png'),full_page=True)
                await page.evaluate('clearSession()')
                assert not await page.locator('#return-workspace').is_visible()
                assert await page.locator('#return-workspace').inner_text()==''
            assert not errors,(persona,errors)
            report.append({'persona':persona,'return_access':allowed,'result':'PASS'})
            await page.close()
        await browser.close()
    (target/'browser_report.json').write_text(json.dumps({'data':'SYNTHETIC_ONLY','personas':report},indent=2))
    print(json.dumps(report))


if __name__=='__main__':asyncio.run(main())
