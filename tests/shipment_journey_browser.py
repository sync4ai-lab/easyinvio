"""Browser regression for domestic checkout, PAF visibility and test QR delivery."""
import asyncio
import json
import os
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from urllib.parse import urlsplit
from playwright.async_api import async_playwright,expect
from tests import vercel_hosting_browser as hosting

async def check(origin):
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(hosting.ROOT/'.playwright')
    errors=[];calls=[];fail_prepare=True
    offer=str(uuid4());shipment=str(uuid4());tenant=str(uuid4())
    rate={'offer_id':offer,'carrier_code':'EVRI','service_code':'ParcelShop','currency':'GBP','client_price_ex_tax':'8.01',
          'delivery_days':2,'fee_breakdown':{'wholesale_total':'7.00','platform_markup':'1.01'}}
    address={'name':'Sender','line1':'1 Example Street','city':'Leeds','postal_code':'LS1 2EJ','country_code':'GB','email':'sender@example.test','phone':'+447700900111'}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def handler(route):
            nonlocal fail_prepare
            path=urlsplit(route.request.url).path
            if path.endswith('/checkout/context'):
                data={'invoice_reference':'EINVIO-TEST','customs_required':False,'origin':address,'destination':address,
                      'quote_expires_at':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
            elif path.endswith('/checkout/prepare'):
                calls.append(('prepare',route.request.post_data_json))
                if fail_prepare:
                    fail_prepare=False
                    await route.fulfill(status=503,json={'detail':'Synthetic temporary preparation failure. Please retry.'});return
                data={'shipment_id':shipment,'invoice_reference':'EINVIO-TEST','offer':rate,'customs_required':False,'price_changed':False}
            elif path.endswith('/shipping/confirm-booking'):
                calls.append(('purchase',route.request.post_data_json))
                data={'shipment_id':shipment,'status':'BOOKED','environment':'TEST','paperless_available':True,
                      'return_dropoff_qr_code_url':'/api/v1/shipping/'+shipment+'/documents/return-qr',
                      'label':{'tracking_number':'00000000000000','label_url':'/api/v1/shipping/'+shipment+'/documents/label','carrier_forms':[]}}
            elif path.endswith('/sender-notifications'):
                data={'available':True,'items':[{'channel':'EMAIL','state':'READY','error_code':None}]}
            elif '/catalog/' in path:
                data={'items':[{'id':str(uuid4()),'label':'Saved sender','address_role':'PICKUP','is_default':True,'address':address}]}
            elif path in ['/api/v1/config','/api/v1/auth/config']:
                data={'mode':'local-preview','supabase_url':None,'publishable_key':None}
            elif path.endswith('/shipping/protection-quote'):
                data={'available':False,'selection_available':False,'notice':'Not configured'}
            else:data={'items':[],'shipments':[],'orders':[]}
            await route.fulfill(json=data)
        await page.route('**/api/v1/**',handler)
        await page.goto(origin,wait_until='domcontentloaded')
        await page.wait_for_function("state.mode==='local-preview'")
        await page.evaluate('''data=>{
            document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
            portal.role='CLIENT';portal.profile={tenant_id:data.tenant,portal_role:'CLIENT',workspace_role:'OWNER'};
            state.session={access_token:'synthetic',expires_at:Date.now()/1000+3600};state.mode='configured';setView('dispatch');
            state.quotes=[data.rate];state.quoteRequest={origin:data.address,destination:data.address,currency:'GBP'};
        }''',{'tenant':tenant,'rate':rate,'address':address})
        await page.locator('[data-catalog-directory=origin]').click()
        await expect(page.locator('#catalog-directory-list button')).to_have_count(2)
        text=await page.locator('#catalog-directory-list button').first.inner_text()
        assert '?' not in text and 'Leeds, LS1 2EJ' in text
        await page.locator('#catalog-directory-list button').first.click()
        await expect(page.locator('#origin-lookup')).to_be_visible()
        await page.evaluate("document.querySelector('#destination-line1').value='99 Separate Street';document.querySelector('#destination-reuse-contact').click()")
        await expect(page.locator('#destination-email')).to_have_value('sender@example.test')
        await expect(page.locator('#destination-line1')).to_have_value('99 Separate Street')
        await page.evaluate('rate=>{state.quotes=[rate];state.quoteRequest={origin:{country_code:"GB"},destination:{country_code:"GB"},currency:"GBP"};}',rate)
        # A transient preparation error is visible, never a dead Continue button.
        await page.evaluate("document.querySelector('#review-dialog').showModal();bookLive(0).catch(()=>{})")
        await expect(page.locator('#review-content')).to_contain_text('Synthetic temporary preparation failure')
        assert 'Continue without export documents' not in await page.locator('#review-content').inner_text()
        await page.evaluate("bookLive(0)")
        await expect(page.locator('#checkout-purchase')).to_be_visible()
        assert not any(kind=='purchase' for kind,_ in calls)
        await page.locator('#checkout-purchase').click()
        await expect(page.locator('#review-content')).to_contain_text('Test tracking reference: 00000000000000')
        await expect(page.locator('#checkout-downloads')).to_contain_text('View carrier drop-off QR code')
        await expect(page.locator('#sender-notification-status')).to_contain_text('email ready')
        assert sum(kind=='purchase' for kind,_ in calls)==1
        assert all(body['customs'] is None for kind,body in calls if kind=='prepare')
        assert not errors,errors
        await browser.close()
        print(json.dumps({'domestic_checkout':'passed','visible_retry_error':True,'test_tracking_label':True,'carrier_qr':True,'contact_copy_preserves_street':True,'saved_formatting':True}))

if __name__=='__main__':
    hosting.check=check
    hosting.main()
