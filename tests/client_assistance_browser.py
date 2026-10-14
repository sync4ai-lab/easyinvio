"""Isolated browser verification of client switching; no database or provider calls."""
import asyncio
import json
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit, parse_qs

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright, expect

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())


async def run(origin):
    errors=[];calls=[];ended=[];active={};actor=str(uuid4())
    clients=[{'tenant_id':str(uuid4()),'company_name':name,'workspace_name':name,
        'billing_email':email,'workspace_status':'ACTIVE','is_sandbox':True}
        for name,email in [('Northgate Test','alpha@example.invalid'),('Harbor Retail','beta@example.invalid')]]
    report={'totals_by_currency':[],'total_package_count':0,'active_tenants':2,'carriers':[],
        'lanes':[],'series':[],'statuses':[],'start_date':'2026-10-01','end_date':'2026-10-14',
        'billing_pipeline':[],'payment_pipeline':[],'active_support':[]}
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def handler(route):
            request=route.request;parts=urlsplit(request.url);path=parts.path;method=request.method
            aid=request.headers.get('x-easyinvio-assistance');calls.append((path,method,aid))
            if path=='/api/v1/admin/client-assistance/clients':
                assert not aid
                q=parse_qs(parts.query).get('q',[''])[0].lower()
                await route.fulfill(json={'clients':[row for row in clients if q in json.dumps(row).lower()]});return
            if path=='/api/v1/admin/client-assistance/sessions':
                assert not aid
                body=request.post_data_json;client=next(row for row in clients if row['tenant_id']==body['tenant_id'])
                assert len(body['reason'])>=10
                result={**client,'session_id':str(uuid4()),'actor_user_id':actor,
                    'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),'workspace_role':'OWNER'}
                active[result['session_id']]=result;await route.fulfill(status=201,json=result);return
            if path.startswith('/api/v1/admin/client-assistance/sessions/'):
                assert method=='DELETE' and not aid
                ended.append(path.rsplit('/',1)[1]);await route.fulfill(json={'ended':True});return
            if path=='/api/v1/admin/client-assistance/events':
                assert not aid
                rows=[]
                if active:
                    current=next(iter(active.values()))
                    rows=[{'company_name':current['company_name'],'actor_auth_user_id':actor,'event_type':'REQUEST_FINISHED',
                        'method':'PATCH','path':'/api/v1/catalog/products/test','status_code':200,
                        'reason':'Investigate the reported label problem','request_id':str(uuid4()),'session_id':current['session_id'],
                        'created_at':datetime.now(timezone.utc).isoformat(),
                        'detail':{'requested_change':{'description':'<script>untrusted catalog text</script>','unit_value':'12.30'}}}]
                await route.fulfill(json={'events':rows});return
            if path=='/api/v1/profile':
                await route.fulfill(json={'portal_role':'CLIENT','workspace_role':'OWNER','tenant_id':active[aid]['tenant_id'],
                    'company_name':active[aid]['company_name'],'user_id':actor} if aid else {'portal_role':'SUPER_ADMIN','tenant_id':None,'user_id':actor});return
            if path=='/api/v1/auth/me':
                assert not aid
                await route.fulfill(json={'role':'SUPER_ADMIN','email':'operator@example.invalid','full_name':'Support Operator','phone_e164':None});return
            if path.endswith('/analytics/reports') or path.endswith('/analytics/dashboard'):
                await route.fulfill(json=report);return
            if path=='/api/v1/wallet':
                await route.fulfill(json={'currency':'GBP','balance':'5000.00','reserved_balance':'0.00','available':'5000.00','history':[]});return
            if path.endswith('/support/tickets'):
                await route.fulfill(json={'tickets':[]});return
            if path=='/api/v1/config':
                await route.fulfill(json={'mode':'configured','supabase_url':None,'publishable_key':None});return
            await route.fulfill(json={'mode':'configured','shipments':[],'items':[],'has_more':False,'orders':[],'events':[]})
        await page.route('**/api/v1/**',handler)
        await page.route('**/health',lambda route:route.fulfill(json={'mode':'configured','status':'ok'}))
        await page.goto(origin+'/')
        await page.wait_for_function("typeof state !== 'undefined' && document.querySelector('#assistance-dialog')")
        await page.evaluate('''actor=>{state.session={access_token:'synthetic-admin-token',expires_at:Math.floor(Date.now()/1000)+3600};state.mode='configured';identityProfile={email:'operator@example.invalid',role:'SUPER_ADMIN'};portal.profile={portal_role:'SUPER_ADMIN',tenant_id:null,user_id:actor};portal.role='SUPER_ADMIN';showIdentityGate();renderAccount();renderPortal();setView('dashboard');}''',actor)
        await page.locator('#role-client').click()
        await expect(page.locator('#assistance-dialog')).to_be_visible()
        await page.locator('#assistance-search').fill('alpha@example.invalid')
        await expect(page.locator('.assistance-choice')).to_have_count(1)
        await page.locator('.assistance-choice').click()
        await page.locator('#assistance-reason').fill('Investigate the reported label problem')
        await page.locator('#assistance-start').click()
        await expect(page.locator('#assistance-banner')).to_be_visible()
        await expect(page.locator('#assistance-client-name')).to_contain_text('Northgate Test')
        await expect(page.locator('#mode-label')).to_contain_text('CLIENT ASSISTANCE')
        await page.wait_for_function("portal.profile?.company_name === 'Northgate Test'")
        assert await page.evaluate('portal.profile.tenant_id')==clients[0]['tenant_id']
        assert await page.evaluate('state.session.access_token')=='synthetic-admin-token'
        assert any(path=='/api/v1/profile' and aid for path,_,aid in calls)
        await page.evaluate("state.quotes=[{offer_id:'stale-client-offer'}];state.manifest=[{id:'stale-client-shipment'}]")
        await page.locator('#role-admin').click()
        await expect(page.locator('#assistance-banner')).to_be_hidden()
        await page.wait_for_function("portal.role === 'SUPER_ADMIN' && !state.assistance")
        assert await page.evaluate('state.quotes.length')==0
        assert await page.evaluate('state.manifest.length')==0
        assert len(ended)==1
        await page.locator('#role-client').click()
        await page.locator('#assistance-search').fill(clients[1]['tenant_id'])
        await expect(page.locator('.assistance-choice')).to_have_count(1)
        await expect(page.locator('.assistance-choice')).to_contain_text('Harbor Retail')
        await page.locator('.assistance-choice').click()
        await page.locator('#assistance-reason').fill('Review a different client issue')
        await page.locator('#assistance-start').click()
        await expect(page.locator('#assistance-client-name')).to_contain_text('Harbor Retail')
        await page.set_viewport_size({'width':390,'height':844})
        await expect(page.locator('#assistance-return')).to_be_visible()
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        folder=Path('output/client-assistance');folder.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(folder/'client-support-mobile.png'))
        await page.locator('#assistance-return').click()
        await page.set_viewport_size({'width':1440,'height':1000})
        await expect(page.locator('#assistance-audit')).to_be_visible()
        await expect(page.locator('#assistance-audit-results tbody tr')).to_have_count(1)
        await page.locator('#assistance-audit summary').click()
        await expect(page.locator('#assistance-audit pre')).to_contain_text('<script>untrusted catalog text</script>')
        await page.locator('#assistance-audit').scroll_into_view_if_needed()
        await page.screenshot(path=str(folder/'admin-assistance-audit.png'))
        assert not errors,errors
        await browser.close()
    print(json.dumps({'status':'PASS','checks':['Client search by email and UUID','Original admin identity retained',
        'Tenant-scoped profile requests','Explicit return and server revocation','Stale offers and shipments cleared',
        'Second client switching','Mobile banner and no horizontal overflow','Admin-only audit panel'],
        'page_errors':errors,'provider_calls':0,'database_calls':0},indent=2))


if __name__=='__main__':
    app=FastAPI()
    @app.get('/')
    async def frontend():return FileResponse('index.html')
    listener=socket.socket();listener.bind(('127.0.0.1',0));origin='http://127.0.0.1:'+str(listener.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        deadline=time.monotonic()+15
        while not server.started:
            if time.monotonic()>deadline:raise RuntimeError('Isolated server did not start')
            time.sleep(.05)
        asyncio.run(run(origin))
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
