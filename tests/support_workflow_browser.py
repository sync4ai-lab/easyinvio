"""Browser-only support presentation and note handling, controlled API boundary."""
import asyncio,json,os
from pathlib import Path
from uuid import uuid4
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
    tid=str(uuid4());sid=str(uuid4());errors=[];notes=[]
    ticket={'id':tid,'status':'OPEN','ticket_type':'PROCESSING_ISSUE','tracking_number':'QUOTE-SYNTHETIC','ai_summary':'Shipment preparation issue (ORDER_SERVICE_FAILED). Internal support should review.','responsibility':'EasyInvio internal support','pod_state':'NOT_BOOKED','activity':[],'notifications':[],'notification_explanation':'No merchant alert is queued for an internal preparation issue. Notes stay inside EasyInvio.'}
    async with async_playwright() as p:
        browser=await p.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':900})
        page.on('pageerror',lambda e:errors.append(str(e)))
        async def route(r):
            path=r.request.url.split('/api/v1/',1)[1]
            if path.endswith('/intervene'):
                body=r.request.post_data_json;notes.append(body);ticket['manual_note']=body['note'];ticket['status']='IN_REVIEW' if body['start_review'] else 'OPEN';ticket['reviewer_name']='Test reviewer' if body['start_review'] else None
                ticket['activity'].append({'actor':'Test reviewer','created_at':'2026-10-13','note':body['note'],'type':'INTERNAL_NOTE'})
                data={'status':ticket['status'],'merchant_notified':False,'carrier_contacted':False}
            elif path.startswith('support/tickets'):data={'tickets':[ticket]}
            else:data={}
            await r.fulfill(json=data)
        await page.route('**/api/v1/**',route)
        await page.goto('http://127.0.0.1:8000/',wait_until='domcontentloaded')
        await page.wait_for_function("state.mode!=='checking'")
        await page.evaluate('''ticket=>{
            document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
            portal.role='CLIENT';portal.profile={workspace_role:'OWNER'};state.session={access_token:'controlled-browser'};state.mode='configured';
            setView('dashboard');portal.tickets=[ticket];renderTickets();
        }''',ticket)
        card=page.locator('#support-tickets');await expect(card).to_contain_text('Shipment preparation issue')
        assert 'Bulk order' not in await card.inner_text() and 'Not staged' not in await card.inner_text()
        assert await card.locator('[data-ticket-action="pod"]').count()==0
        assert await card.locator('[data-dispute-ticket]').count()==0
        await card.locator('[data-ticket-action="intervene"]').click()
        assert not await page.locator('#intervention-start-review').is_checked()
        await page.locator('#intervention-note').fill('Checked internal order preparation')
        await page.locator('#intervention-form button').click();await expect(page.locator('#ticket-dialog')).not_to_be_visible()
        await expect(card).to_contain_text('Checked internal order preparation');assert notes[-1]['start_review'] is False
        await card.locator('[data-ticket-action="intervene"]').click();assert await page.locator('#intervention-note').input_value()==''
        await page.locator('#intervention-note').fill('I own the internal review');await page.locator('#intervention-start-review').check()
        await page.locator('#intervention-form button').click();await expect(page.locator('#ticket-dialog')).not_to_be_visible()
        await expect(card).to_contain_text('Test reviewer');await expect(card).to_contain_text('IN_REVIEW')
        for width in (375,768,1366):
            await page.set_viewport_size({'width':width,'height':900})
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await browser.close()
    assert not errors,errors
    report={'status':'PASS','boundary':'controlled browser API; no real messages','checks':['Processing issue classified separately; no invalid POD/dispute actions','Internal note shown with history and no implicit assignment','Explicit assigned review identifies reviewer','New note starts empty','375/768/1366px no horizontal overflow'],'javascript_errors':errors}
    out=Path('docs/support_workflow');out.mkdir(exist_ok=True);(out/'browser_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(run())
