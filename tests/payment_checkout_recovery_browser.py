"""Isolated payment recovery browser checks; no real Stripe/provider requests."""
import asyncio,json,os,socket,threading,time
from pathlib import Path
from uuid import uuid4
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())

async def run(origin):
    tenant,sid,offer,cart=[str(uuid4()) for _ in range(4)]
    errors=[];card_calls=[];mode=['stale']
    rate={'offer_id':offer,'carrier_code':'DPD UK','service_code':'Air Express','currency':'GBP',
          'client_price_ex_tax':'88.40','delivery_days':2,'fee_breakdown':{}}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':950})
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def handler(route):
            path=route.request.url.split('/api/v1/',1)[1]
            if path=='checkout/prepare':
                data={'shipment_id':sid,'invoice_reference':'SYNTHETIC-UAT','offer':rate,'customs_required':False,'price_changed':False}
            elif path=='shipping/confirm-booking':
                await route.fulfill(status=502,json={'detail':{'code':'CARRIER_UNAVAILABLE',
                    'message':'Carrier unavailable. Reserved wallet credit has been released.',
                    'retry_requires_fresh_quote':True,'reserved_credit_released':True}});return
            elif path=='billing/carts':
                card_calls.append(route.request.post_data_json)
                if mode[0]=='stale':
                    await route.fulfill(status=409,json={'detail':{'code':'FRESH_QUOTE_REQUIRED',
                        'message':'This booking needs fresh rates before either payment method can be used.',
                        'retry_requires_fresh_quote':True}});return
                if mode[0]=='unavailable':
                    await route.fulfill(status=503,json={'detail':'Card checkout is temporarily unavailable.'});return
                data={'cart_id':cart,'url':'https://checkout.stripe.com/c/pay/synthetic',
                      'amount':'88.40','currency':'GBP','mode':'TEST','notice':'Synthetic checkout only.'}
            elif path=='billing/carts/'+cart+'/complete':data={'status':'AWAITING_PAYMENT'}
            elif path in ('config','auth/config'):data={'mode':'configured','supabase_url':None,'publishable_key':None}
            else:data={'items':[],'has_more':False,'orders':[],'stores':[],'tickets':[],'shipments':[]}
            await route.fulfill(json=data)
        await page.route('**/api/v1/**',handler)
        await page.goto(origin,wait_until='domcontentloaded')
        await page.evaluate('''({tenant,rate})=>{
          document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;
          portal.role='CLIENT';portal.profile={tenant_id:tenant,workspace_role:'OWNER',portal_role:'CLIENT'};
          state.session={access_token:'synthetic-payment-test',expires_at:Math.floor(Date.now()/1000)+3600};state.mode='configured';
          state.quotes=[rate];window.paymentWindows=[];window.refreshRequests=0;
          window.open=()=>{const popup={closed:false,document:document.implementation.createHTMLDocument('Payment'),
            location:{replace:url=>{popup.redirected=url}},close:()=>{popup.closed=true}};paymentWindows.push(popup);return popup;};
          $('#quote-form').requestSubmit=()=>{refreshRequests++};
        }''',{'tenant':tenant,'rate':rate})
        async def prepare():
            await page.wait_for_timeout(100)
            await page.evaluate('''async()=>{
              for (const dialog of [$('#bulk-checkout-dialog'),$('#review-dialog')]) {
                if (dialog.open) await new Promise(resolve=>{dialog.addEventListener('close',resolve,{once:true});dialog.close()});
              }
              customerCheckout.generation++;
              customerCheckout.index=0;customerCheckout.insuranceRequested=false;
              $('#review-content').innerHTML='<div id="checkout-price"></div><div id="checkout-booking-error" role="alert" hidden></div><aside id="checkout-next"></aside>';
              $('#review-dialog').showModal();await prepareCustomerCheckout();
            }''')
        await prepare()
        await page.locator('#checkout-purchase').click()
        await expect(page.locator('#checkout-booking-error')).to_contain_text('credit has been released')
        await expect(page.locator('#checkout-purchase')).to_be_hidden()
        await expect(page.locator('#checkout-pay-card')).to_be_hidden()
        await page.locator('#checkout-fresh-rates').click()
        assert await page.evaluate('refreshRequests')==1 and not card_calls
        await prepare()
        await page.locator('#checkout-pay-card').click()
        await expect(page.locator('#checkout-booking-error')).to_contain_text('needs fresh rates')
        await expect(page.locator('#checkout-fresh-rates')).to_be_visible()
        assert await page.evaluate('paymentWindows.at(-1).closed') is False
        assert 'fresh rates' in await page.evaluate('paymentWindows.at(-1).document.body.textContent')
        mode[0]='unavailable';await prepare();await page.locator('#checkout-pay-card').click()
        await expect(page.locator('#checkout-booking-error')).to_contain_text('temporarily unavailable')
        assert await page.evaluate('paymentWindows.at(-1).closed') is False
        await expect(page.locator('#checkout-pay-card')).to_be_visible()
        mode[0]='success';await prepare()
        await page.evaluate("()=>{Storage.prototype.setItem=function(){throw new DOMException('Storage blocked','SecurityError')}}")
        await page.locator('#checkout-pay-card').click()
        await expect(page.locator('#bulk-checkout-dialog')).to_be_visible()
        await expect(page.locator('#bulk-checkout-body a')).to_have_attribute('href','https://checkout.stripe.com/c/pay/synthetic')
        assert await page.evaluate('paymentWindows.at(-1).redirected')=='https://checkout.stripe.com/c/pay/synthetic'
        assert len(card_calls)==3 and all(call['offers'][0]['expected_price']=='88.40' for call in card_calls)
        assert not errors,errors
        output=Path('output/payment-recovery');output.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(output/'card-checkout.png'),full_page=True)
        await browser.close()
    print(json.dumps({'status':'PASS','checks':['Definitive carrier rejection retires both payment buttons',
        'Fresh rates require an explicit customer action','Card validation error remains in checkout and popup',
        'Gateway failure does not silently close the popup','Blocked local storage does not block Stripe redirection'],
        'javascript_errors':errors,'provider_calls':0,'real_payments':0},indent=2))

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
