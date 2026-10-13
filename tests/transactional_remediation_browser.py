"""Live-update and financial upload UI; all HTTP and WebSocket responses controlled."""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.async_api import async_playwright, expect

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())


async def run():
    counts={'orders':0,'uploads':0};errors=[];sockets=[]
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch()
        page=await browser.new_page(viewport={'width':1366,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def api(route):
            path=route.request.url.split('/api/v1/')[1].split('?')[0]
            if path=='dispatch-workspace/orders':
                counts['orders']+=1;data={'orders':[],'stores':[],'more_available':False}
            elif path=='finance/audit-invoice-upload':
                counts['uploads']+=1
                assert 'multipart/form-data' in route.request.headers['content-type']
                assert b'QA-STATEMENT-1' in route.request.post_data_buffer
                data={'results':[{'upstream_shipment_id':'QA-NATIVE-1','status':'FLAGGED','confidence_level':100,'estimated_overcharge':'5.00','currency':'GBP','email_draft':'Subject: QA carrier statement review\nPlease review the stored discrepancy.'}]}
            elif path=='finance/billing-disputes':
                data={'disputes':[{'id':str(uuid4()),'invoice_reference':'QA-STATEMENT-1','status':'DRAFT','estimated_overcharge':'5.00','currency':'GBP','email_draft':'Subject: QA saved draft'}]}
            elif path=='wallet':data={'balance':'100.00','reserved_balance':'0.00','currency':'GBP'}
            elif path in {'config','auth/config'}:data={'mode':'configured','supabase_url':None,'publishable_key':None}
            else:data={'orders':[],'stores':[],'tickets':[],'shipments':[],'history':[],'totals_by_currency':[]}
            await route.fulfill(json=data)
        def websocket(socket):
            sockets.append(socket)
            def received(message):
                assert json.loads(message)['access_token']=='synthetic-session-token'
                socket.send(json.dumps({'type':'refresh_required'}))
            socket.on_message(received)
        await page.route('**/api/v1/**',api)
        await page.route_web_socket('**/dispatch-workspace/live',websocket)
        await page.goto('http://127.0.0.1:8000/')
        await page.evaluate("""()=>{document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;
            state.session={access_token:'synthetic-session-token',expires_at:9999999999};portal.role='CLIENT';
            portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'00000000-0000-4000-8000-000000000001'};
            setView('workspace');refreshEnterpriseNavigation();connectDispatchUpdates();} """)
        await page.wait_for_timeout(700)
        assert sockets and counts['orders']>=2
        prior=counts['orders'];sockets[-1].send(json.dumps({'type':'shipment_changed','shipment_id':str(uuid4()),'status':'EXCEPTION'}))
        await page.wait_for_timeout(700);assert counts['orders']>prior
        await page.evaluate("setView('wallet');refreshEnterpriseNavigation()")
        await expect(page.locator('#invoice-audit-panel')).to_be_visible()
        await page.locator('#invoice-upload-form [name=invoice_reference]').fill('QA-STATEMENT-1')
        await page.locator('#invoice-upload-form [name=file]').set_input_files({'name':'statement.csv','mimeType':'text/csv','buffer':b'upstream_shipment_id,currency,invoice_weight_kg,wholesale_cost,residential_fee\nQA-NATIVE-1,GBP,1.2,20,3\n'})
        await page.locator('#invoice-upload-form [type=submit]').click()
        await expect(page.locator('#invoice-audit-result')).to_contain_text('FLAGGED')
        assert counts['uploads']==1
        await page.locator('#invoice-disputes-refresh').click()
        await expect(page.locator('#invoice-audit-result')).to_contain_text('QA-STATEMENT-1')
        for width in [375,768,1366]:
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1
        await page.evaluate("state.session=null;portal.profile=null;refreshEnterpriseNavigation()")
        assert await page.evaluate('dispatchLive.socket===null')
        assert await page.locator('#invoice-audit-result').inner_text()==''
        assert not errors,errors
        await browser.close()
    print('Authenticated WebSocket contract, live inbox refresh, multipart audit, saved disputes, responsive layouts and logout clearing passed.')

asyncio.run(run())
