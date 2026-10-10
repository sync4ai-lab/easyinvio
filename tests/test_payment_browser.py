"""Payment popup, role boundary and server-confirmed credit with controlled APIs."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import httpx
from playwright.async_api import async_playwright, expect


async def run():
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve());env=os.environ.copy();env['PORT']='8007'
    server=subprocess.Popen([sys.executable,'main.py','--local-preview'],env=env,stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    calls=[];errors=[];status_reads=0;tenant_id=str(uuid4());topup_id=str(uuid4())
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(50):
                try:
                    if (await client.get('http://127.0.0.1:8007/health')).status_code==200:break
                except httpx.HTTPError:pass
                await asyncio.sleep(.2)
            else:raise RuntimeError('Preview startup failed')
        async with async_playwright() as pw:
            browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':900})
            page.on('pageerror',lambda error:errors.append(str(error)))
            async def route(r):
                nonlocal status_reads
                if r.request.url.endswith('/api/v1/billing/create-checkout'):
                    calls.append(r.request.post_data_json)
                    return await r.fulfill(json={'url':'https://checkout.stripe.com/c/pay/cs_test_browser','topup_id':topup_id,'mode':'TEST'})
                if '/api/v1/billing/topups/' in r.request.url:
                    status_reads+=1
                    return await r.fulfill(json={'status':'PENDING' if status_reads==1 else 'CREDITED','amount':'250.00','currency':'GBP'})
                if r.request.url.endswith('/api/v1/wallet'):
                    return await r.fulfill(json={'balance':'350.00','reserved_balance':'0.00','currency':'GBP'})
                await r.continue_()
            await page.route('**/api/v1/**',route)
            await page.goto('http://127.0.0.1:8007',wait_until='domcontentloaded');await page.wait_for_function("state.mode!=='checking'")
            await page.locator('#role-client').click();await page.evaluate("setView('wallet')")
            await page.locator('#stripe-topup-open').click()
            await expect(page.locator('#stripe-payment-proceed')).to_be_disabled()
            await page.locator('#stripe-payment-close').click()
            await page.evaluate('''tenant => {
                state.mode='configured';state.session={access_token:'controlled-token'};
                portal.profile={tenant_id:tenant,workspace_role:'OWNER',portal_role:'CLIENT'};portal.role='CLIENT';
                state.wallet=10000n;state.walletCurrency='GBP';renderWallet();
                window.open=()=>({opener:null,document:{title:'',body:{textContent:''}},location:{replace:url=>window.testCheckoutURL=url},close:()=>{}});
            }''',tenant_id)
            await page.locator('#stripe-topup-open').click();await page.locator('[data-stripe-amount="250.00"]').click()
            await page.locator('#stripe-payment-proceed').click()
            await expect(page.locator('#stripe-payment-status')).to_contain_text('Awaiting the signed Stripe webhook')
            await expect(page.locator('#wallet-balance')).to_contain_text('100.00')
            await expect(page.locator('#stripe-payment-status')).to_contain_text('Payment verified',timeout=10000)
            await expect(page.locator('#wallet-balance')).to_contain_text('350.00')
            assert calls[0]['tenant_id']==tenant_id and calls[0]['topup_amount']=='250.00'
            assert await page.evaluate('window.testCheckoutURL')=='https://checkout.stripe.com/c/pay/cs_test_browser'
            for width in [375,768,1366]:
                await page.set_viewport_size({'width':width,'height':900})
                assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1
            await page.locator('#stripe-payment-close').click()
            assert not errors,errors
            await browser.close()
        print(json.dumps({'unsigned_checkout_disabled':True,'tiers_and_popup':True,'pending_does_not_credit':True,
            'server_verified_credit_refresh':True,'responsive_widths':[375,768,1366],'javascript_errors':0,'real_stripe_calls':0}))
    finally:
        server.terminate();server.wait(timeout=15)


if __name__=='__main__':asyncio.run(run())
