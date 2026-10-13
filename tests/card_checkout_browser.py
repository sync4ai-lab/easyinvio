import asyncio,json,os,time
from pathlib import Path
from uuid import uuid4
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
 tenant,sid,offer,cart=[str(uuid4()) for _ in range(4)];paid=False;failure=False;calls=[];errors=[]
 rate={'offer_id':offer,'carrier_code':'DHL','service_code':'Express','currency':'GBP','client_price_ex_tax':'16.50','delivery_days':2}
 async with async_playwright() as pw:
  browser=await pw.chromium.launch();page=await browser.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  saved={'access_token':'controlled-payment-browser','expires_at':int(time.time())+3600,'user':{'email':'qa@example.invalid'}}
  await page.add_init_script('localStorage.setItem("easyinvio.session",JSON.stringify('+json.dumps(saved)+'));')
  async def handler(route):
   path=route.request.url.split('/api/v1/',1)[1]
   if path=='profile':
    if failure:await route.fulfill(status=503,json={'detail':'Temporary profile error'});return
    data={'portal_role':'CLIENT','workspace_role':'OWNER','tenant_id':tenant,'user_id':str(uuid4()),'company_name':'Synthetic QA'}
   elif path=='auth/me':data={'email':'qa@example.invalid','full_name':'QA Owner','role':'OWNER','user_id':str(uuid4()),'tenant_id':tenant}
   elif path=='billing/carts':
    body=route.request.post_data_json;calls.append(body);assert body['offers'][0]['expected_price']=='16.50';assert body['return_origin']=='http://127.0.0.1:8000'
    data={'cart_id':cart,'topup_id':cart,'url':'https://checkout.stripe.com/c/pay/synthetic','amount':'16.50','currency':'GBP','notice':'Unused credit remains in your wallet.'}
   elif path=='billing/carts/'+cart+'/complete':data={'cart_id':cart,'status':'COMPLETED','outcome':{'results':[{'shipment_id':sid,'status':'BOOKED','reference':'EINVIO-00000099','label':{'tracking_number':'QA-CARD-TRACK'}}],'notice':'Selected label confirmed.'}} if paid else {'cart_id':cart,'status':'AWAITING_PAYMENT'}
   elif path=='wallet':data={'balance':'100.00','reserved_balance':'0.00','currency':'GBP'}
   elif path=='shipments/manifest':data={'shipments':[]}
   elif path in ('config','auth/config'):data={'mode':'configured','supabase_url':None,'publishable_key':None}
   else:data={'orders':[],'stores':[],'tickets':[],'shipments':[],'totals_by_currency':[],'history':[]}
   await route.fulfill(json=data)
  await page.route('**/api/v1/**',handler);await page.goto('http://127.0.0.1:8000/');await expect(page.locator('#loginContainer')).not_to_be_visible()
  await page.evaluate('''({sid,rate})=>{window.open=()=>({opener:null,document:{body:{textContent:''}},location:{replace:()=>{}},close:()=>{}});bulkDispatch.orders=[{shipment_id:sid,reference:'QA-CARD',status:'QUOTED',rates:[rate],customs_ready:true}];renderBulkCheckout();$('#bulk-checkout-dialog').showModal();}''',{'sid':sid,'rate':rate})
  await expect(page.locator('#bulk-checkout-buy')).to_contain_text('Pay from wallet');await expect(page.locator('#bulk-pay-card')).to_be_visible();await page.locator('#bulk-pay-card').click();await expect(page.locator('#label-card-status')).to_be_visible();assert len(calls)==1
  paid=True;await page.goto('http://127.0.0.1:8000/?payment=success&cart_id='+cart+'&topup_id='+cart)
  await expect(page.locator('#loginContainer')).not_to_be_visible();await expect(page.locator('#bulk-checkout-body')).to_contain_text('QA-CARD-TRACK');assert await page.evaluate('state.wallet===10000n')
  assert await page.evaluate('localStorage.getItem("easyinvio.session")') is not None
  failure=True;await page.reload();await expect(page.locator('#identity-login-status')).to_contain_text('saved session is retained');assert await page.evaluate('localStorage.getItem("easyinvio.session")') is not None
  failure=False;await page.reload();await expect(page.locator('#loginContainer')).not_to_be_visible();assert not errors,errors
  await browser.close()
 report={'status':'PASS','boundary':'controlled browser API; no real payments','checks':['Wallet and Stripe card buttons visible for owner','Exact selected amount and current return origin sent','Payment return restores authenticated session and completes label basket','Card-funded label keeps previous wallet balance','Transient profile failure retains saved session for retry'],'javascript_errors':errors}
 Path('docs/card_checkout/browser_report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(run())
