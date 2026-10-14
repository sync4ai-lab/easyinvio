"""Memory-only sign-in, active renewal and clean forms with isolated fake APIs."""
import asyncio,json,os,socket,threading,time
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright,expect

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())


async def run(origin):
    actor,tenant=str(uuid4()),str(uuid4());logins=0;renewals=0;deny_renewal=False;renew_delay=.15;errors=[]
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        page=await browser.new_page(viewport={'width':1366,'height':900})
        page.on('pageerror',lambda error:errors.append(str(error)))
        await page.add_init_script("localStorage.setItem('easyinvio.session',JSON.stringify({access_token:'old-persisted-token',expires_at:Math.floor(Date.now()/1000)+3600}));")
        async def handler(route):
            nonlocal logins,renewals
            path=urlsplit(route.request.url).path
            if path=='/api/v1/auth/token':
                logins+=1
                await route.fulfill(json={'access_token':'synthetic.session.login'+str(logins),'expires_at':int(time.time())+900,
                    'absolute_expires_at':int(time.time())+28800,'user':{'id':actor,'email':'operator@example.invalid'}});return
            if path=='/api/v1/auth/renew':
                renewals+=1;await asyncio.sleep(renew_delay)
                await route.fulfill(status=401 if deny_renewal else 200,json={'detail':'Session revoked'} if deny_renewal else {
                    'access_token':'synthetic.session.renewed'+str(renewals),'expires_at':int(time.time())+900,
                    'absolute_expires_at':int(time.time())+28800,'assistance_sessions':[]});return
            if path=='/api/v1/profile':
                await route.fulfill(json={'portal_role':'CLIENT','workspace_role':'OWNER','tenant_id':tenant,'user_id':actor,'company_name':'Session Test'});return
            if path=='/api/v1/auth/me':
                await route.fulfill(json={'role':'OWNER','email':'operator@example.invalid','full_name':'Session Operator','phone_e164':None});return
            if path=='/api/v1/auth/logout':await route.fulfill(json={'logged_out':True});return
            if path=='/api/v1/analytics/reports':
                await route.fulfill(json={'totals_by_currency':[],'total_package_count':0,'lanes':[],'series':[],'statuses':[],
                    'start_date':'2026-10-01','end_date':'2026-10-14'});return
            if path=='/api/v1/wallet':
                await route.fulfill(json={'currency':'GBP','balance':'100.00','reserved_balance':'0.00','available':'100.00','transactions':[]});return
            await route.fulfill(json={'mode':'configured','supabase_url':None,'publishable_key':None,'tickets':[],'items':[],'shipments':[],'has_more':False,'orders':[]})
        await page.route('**/api/v1/**',handler)
        await page.route('**/health',lambda route:route.fulfill(json={'mode':'configured','status':'ok'}))
        await page.goto(origin+'/')
        await expect(page.locator('#loginContainer')).to_be_visible()
        assert await page.evaluate("state.session===null && localStorage.getItem('easyinvio.session')===null")
        assert logins==0
        async def login():
            await page.locator('#identity-email').fill('operator@example.invalid')
            await page.locator('#identity-password').fill('synthetic-password')
            await page.locator('#identity-login-submit').click()
            await expect(page.locator('#loginContainer')).to_be_hidden()
        await login()
        await page.evaluate("document.querySelector('#origin-line1').value='Private old address';document.querySelector('#shipment-description').value='Private old goods';document.querySelector('#length_cm').value='40';")
        await page.evaluate("window.originalSession=state.session;state.session.expires_at=Math.floor(Date.now()/1000)+80;lastIdentityActivity=Date.now();armSessionExpiry();")
        await page.wait_for_function("state.session?.access_token.includes('renewed')")
        assert renewals==1
        assert await page.evaluate('window.originalSession===state.session')
        await expect(page.locator('#origin-line1')).to_have_value('Private old address')
        assert await page.evaluate("!JSON.stringify(localStorage).includes('synthetic.session')")
        await page.reload()
        await expect(page.locator('#loginContainer')).to_be_visible()
        assert logins==1
        await expect(page.locator('#origin-line1')).to_have_value('')
        await expect(page.locator('#shipment-description')).to_have_value('')
        await expect(page.locator('#length_cm')).to_have_value('')
        await login()
        await page.evaluate("document.querySelector('#cargo-type').value='LETTER';configureCargo(false);document.querySelector('#shipment-description').value='Clear me on sign-out';")
        await page.locator('#identity-logout').click()
        await expect(page.locator('#loginContainer')).to_be_visible()
        await expect(page.locator('#shipment-description')).to_have_value('')
        await expect(page.locator('#cargo-type')).to_have_value('PARCEL')
        await expect(page.locator('#length_cm')).to_be_enabled()
        await login()
        await page.evaluate("lastIdentityActivity=Date.now()-identityIdleMilliseconds-1;")
        await page.keyboard.press('Shift')
        await expect(page.locator('#loginContainer')).to_be_visible()
        assert renewals==1
        await login();renew_delay=2
        await page.evaluate("state.session.expires_at=Math.floor(Date.now()/1000)+1;lastIdentityActivity=Date.now();armSessionExpiry();")
        await expect(page.locator('#loginContainer')).to_be_visible()
        await page.wait_for_timeout(2300)
        assert await page.evaluate('state.session===null')
        await login();deny_renewal=True;renew_delay=.15
        await page.evaluate("state.session.expires_at=Math.floor(Date.now()/1000)+80;lastIdentityActivity=Date.now();armSessionExpiry();")
        await expect(page.locator('#loginContainer')).to_be_visible()
        assert await page.evaluate('state.session===null')
        assert not errors,errors
        await browser.close()
    print(json.dumps({'status':'PASS','checks':['No legacy localStorage login restoration','Active session renews before expiry',
        'Renewal preserves current form and session identity','Refresh requires explicit sign-in','Sign-out clears shipment forms',
        'Inactive session cannot renew','Late renewal cannot reopen an expired session','Revoked renewal returns to sign-in'],'page_errors':errors,'provider_calls':0,'database_calls':0},indent=2))


if __name__=='__main__':
    app=FastAPI()
    @app.get('/')
    async def frontend():return FileResponse('index.html')
    listener=socket.socket();listener.bind(('127.0.0.1',0));origin='http://127.0.0.1:'+str(listener.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False));thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        deadline=time.monotonic()+15
        while not server.started:
            if time.monotonic()>deadline:raise RuntimeError('Isolated server did not start')
            time.sleep(.05)
        asyncio.run(run(origin))
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
