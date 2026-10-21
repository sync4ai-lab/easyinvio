"""Run manually against an isolated --local-preview server. All API data is synthetic."""
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.playwright'))
from playwright.async_api import async_playwright

IDENT='00000000-0000-4000-8000-000000000045'
EVENT={'status':'OUT_FOR_DELIVERY','occurred_at':'2026-10-21T10:15:00Z','received_at':'2026-10-21T10:16:00Z','applied':True,'source':'Carrier integration'}
ITEM={'id':IDENT,'order_reference':'SYNTHETIC-ORDER-45','store_order_reference':'WEB-45','carrier':'Royal Mail',
      'tracking_number':'SYNTHETIC-TRACK-45','status':'OUT_FOR_DELIVERY','shipment_status':'IN_TRANSIT',
      'last_event_at':EVENT['occurred_at'],'data_state':'RECORDED','latest_event':EVENT,'timeline':[EVENT],
      'parcels':[{'index':1,'tracking_number':'SYNTHETIC-TRACK-45','status':'OUT_FOR_DELIVERY'}],
      'lifecycle':'FORWARD_SHIPMENT','return_status':'NONE','estimated_delivery_at':None,
      'refresh':{'state':'DUE','last_success_at':None,'error_code':None},'review':{'state':None,'assigned_to':None},
      'tenant_name':'Synthetic QA workspace','tenant_id':'00000000-0000-4000-8000-000000000001','provider':'EASYPOST'}
LIST={'shipments':[ITEM],'counts':{'total':1,'in_transit':1,'out_for_delivery':1,'delivered':0,'exceptions':0,'stale':0,'returns':0,'customer_requests':1},'page':1,'has_more':False}
DETAIL={'anchor_id':IDENT,'order_reference':ITEM['order_reference'],'shipments':[ITEM],'returns':[],
        'refund':{'status':'UNAVAILABLE','message':'A purchase refund has not been confirmed by an authorized order/payment source.'},
        'customer_requests':[{'id':IDENT,'shipment_id':IDENT,'note':'Synthetic delivery question for the retailer team.','state':'OPEN','created_at':EVENT['occurred_at']}]}


async def main():
    origin=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8768'
    output=ROOT/'output/tracking045-qa';output.mkdir(parents=True,exist_ok=True)
    report={'data':'SYNTHETIC_ONLY','roles':[],'errors':[]}
    async with async_playwright() as driver:
        browser=await driver.chromium.launch()
        for role in ('OWNER','ADMIN','DISPATCHER','ACCOUNTANT','INDIVIDUAL','SUPER_ADMIN'):
            page=await browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            async def offline(route):
                if not route.request.url.startswith(origin):return await route.abort()
                if '/api/' in route.request.url or '/v1/' in route.request.url:return await route.fulfill(status=503,json={'detail':'Synthetic browser test: disconnected API'})
                await route.continue_()
            await page.route('**/*',offline)
            await page.goto(origin,wait_until='domcontentloaded')
            await page.wait_for_selector('#tracking',state='attached')
            await page.evaluate('''({role,list,detail})=>{
              window.__trackingCalls=[];
              api=async function(path,options={}){window.__trackingCalls.push(path);
                if(path.endsWith('/health'))return {jobs:[],counts:{},polling_enabled:false};
                if(path.endsWith('/share-links'))return {links:[]};
                if(path.endsWith('/share'))return {id:detail.anchor_id,url:'https://app.example.test/track#'+'a'.repeat(43)};
                if(path.includes('/shipments?'))return list;
                if(path.endsWith('/review'))return {review_state:'IN_REVIEW'};
                if(path.endsWith('/refresh'))return {message:'Synthetic queued refresh'};
                if(path.includes('/shipments/'))return detail;
                return {};
              };
              state.session={access_token:'synthetic-test-session',expires_at:Math.floor(Date.now()/1000)+3600};
              portal.profile={portal_role:role==='SUPER_ADMIN'?'SUPER_ADMIN':'CLIENT',workspace_role:['SUPER_ADMIN','INDIVIDUAL'].includes(role)?'OWNER':role,workspace_type:role==='INDIVIDUAL'?'INDIVIDUAL':'BUSINESS',company_name:'Synthetic QA workspace'};
              portal.role=role==='SUPER_ADMIN'?'SUPER_ADMIN':'CLIENT';
              document.body.classList.remove('auth-locked');
              document.querySelectorAll('#identity-gate,[data-identity-gate]').forEach(n=>n.hidden=true);
              document.querySelectorAll('dialog[open]').forEach(n=>n.close());
              refreshEnterpriseNavigation();setView('tracking');
            }''',{'role':role,'list':LIST,'detail':DETAIL})
            await page.locator('#tracking-rows .tracking-ref').wait_for()
            await page.locator('#tracking-rows .tracking-ref').click()
            await page.locator('#tracking-detail-content .tracking-parcel').first.wait_for()
            assert await page.get_by_role('heading',name='Purchase refund',exact=True).is_visible()
            assert await page.locator('#tracking-detail-content').get_by_text('Synthetic delivery question',exact=False).is_visible()
            if role=='ACCOUNTANT':
                assert await page.locator('#tracking-share').count()==0
                assert await page.locator('[data-tracking-refresh]').count()==0
            elif role=='OWNER':
                await page.locator('#tracking-share').click()
                await page.locator('.tracking-link-output').wait_for()
                assert '/track#' in await page.locator('.tracking-link-output').get_attribute('href')
            await page.screenshot(path=str(output/(role.lower()+'-detail.png')))
            await page.locator('#tracking-detail-close').click()
            await page.set_viewport_size({'width':390,'height':844})
            await page.screenshot(path=str(output/(role.lower()+'-mobile.png')))
            overflow=await page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
            assert not overflow,f'{role}: page overflows on mobile'
            assert not errors,errors
            if role=='OWNER':
                await page.evaluate('''({list})=>{const previous=api;api=async(path,opts)=>path.includes('/shipments?')?new Promise(resolve=>window.__resolveTracking=()=>resolve(list)):previous(path,opts);setView('tracking');}''',{'list':LIST})
                await page.wait_for_function('typeof window.__resolveTracking==="function"')
                await page.evaluate('clearSession();window.__resolveTracking();')
                await page.wait_for_timeout(100)
                assert await page.locator('#tracking-rows .tracking-ref').count()==0
                assert not await page.locator('.tracking-drawer').first.evaluate('(node)=>node.open')
            report['roles'].append({'role':role,'desktop_detail':'passed','mobile_overflow':False,'page_errors':errors})
            await page.close()
        public=await browser.new_page(viewport={'width':390,'height':844})
        requests=[];public.on('request',lambda request:requests.append(request.url))
        async def public_routes(route):
            if route.request.url.endswith('/api/v1/public/tracking/resolve'):
                return await route.fulfill(json={'shipments':[ITEM],'support_message':'Synthetic tracking preview. Contact your retailer.','whatsapp':None})
            if route.request.url.endswith('/api/v1/public/tracking/help'):
                return await route.fulfill(status=202,json={'message':'Synthetic request received by retailer team.'})
            if not route.request.url.startswith(origin):return await route.abort()
            await route.continue_()
        await public.route('**/*',public_routes)
        token='z'*43
        await public.goto(origin+'/track#'+token)
        await public.get_by_role('heading',name=ITEM['order_reference']).wait_for()
        await public.get_by_text('Ask the retailer for help',exact=True).click()
        await public.locator('textarea').fill('Synthetic question about this delivery.')
        await public.get_by_role('button',name='Send request to retailer').click()
        await public.get_by_text('Synthetic request received',exact=False).wait_for()
        assert not await public.evaluate('document.documentElement.scrollWidth>innerWidth+2')
        assert all(token not in value for value in requests),'Capability leaked in an HTTP URL'
        await public.screenshot(path=str(output/'customer-mobile.png'),full_page=True)
        await public.unroute('**/*',public_routes)
        async def revoked(route):
            if route.request.url.endswith('/api/v1/public/tracking/resolve'):return await route.fulfill(status=404,json={'detail':'This tracking link has expired or was revoked.'})
            await route.continue_()
        await public.route('**/*',revoked)
        await public.get_by_role('button',name='Refresh recorded updates').click()
        await public.get_by_text('This tracking link has expired',exact=False).wait_for()
        assert await public.locator('#public-tracking-content section').count()==0
        await browser.close()
    report['customer_page']='passed';report['capability_in_http_urls']=False
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':asyncio.run(main())
