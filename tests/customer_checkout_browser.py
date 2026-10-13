"""Customer booking journeys in a real browser with controlled API boundaries."""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.async_api import async_playwright,expect

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())


async def run():
    output=Path('docs/customer_checkout');output.mkdir(parents=True,exist_ok=True)
    errors=[];calls=[];tenant=str(uuid4());offer=str(uuid4());sid=str(uuid4());invoice='EINVIO-00000001'
    rate={'offer_id':offer,'carrier_code':'DHL','service_code':'Express','currency':'GBP','client_price_ex_tax':'62.70',
          'delivery_days':2,'fee_breakdown':{'wholesale_total':'55.49','platform_markup':'7.21','fuel_surcharge':None}}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':1366,'height':900})
        page.on('pageerror',lambda error:errors.append(str(error)))
        address={'name':'Test','line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
        async def route_handler(route):
            path=route.request.url.split('/api/v1/',1)[1]
            if path.startswith('checkout/context'):
                data={'invoice_reference':invoice,'customs_required':True,'goods_value_currency':'USD','shipping_currency':'GBP',
                      'shipping_cost':'62.70','origin':address,'destination':{**address,'country_code':'US'},'gross_weight_kg':'2','items':[{'description':'Electric steam iron','quantity':1,'unit_value':'25.00','unit_weight_kg':'1.000','origin_country':'GB'}]}
            elif path=='checkout/hs-search':
                calls.append(('hs',route.request.post_data_json))
                data={'candidates':[{'hs_code':'851640','title':'Electric smoothing irons','source':'UK Integrated Online Tariff'}]}
            elif path=='checkout/prepare':
                calls.append(('prepare',route.request.post_data_json))
                data={'shipment_id':sid,'invoice_reference':invoice,'offer':{**rate,'offer_id':str(uuid4()),'client_price_ex_tax':'64.20'},
                      'price_changed':True,'customs_required':True}
            elif path=='shipping/confirm-booking':
                calls.append(('purchase',route.request.post_data_json))
                data={'shipment_id':sid,'status':'BOOKED','label':{'tracking_number':'TEST-TRACK-1',
                      'label_url':'/api/v1/shipping/'+sid+'/documents/label','carrier_forms':[]}}
            elif path in ('config','auth/config'):data={'mode':'configured','supabase_url':None,'publishable_key':None}
            else:data={'shipments':[],'tickets':[],'orders':[],'stores':[],'balance':'1000.00','reserved_balance':'0.00','currency':'GBP'}
            await route.fulfill(json=data)
        await page.route('**/api/v1/**',route_handler)
        await page.goto('http://127.0.0.1:8000/',wait_until='domcontentloaded')
        await page.wait_for_function("state.mode!=='checking'")
        assert await page.locator('#item-description').input_value()==''
        assert await page.locator('#length_cm').input_value()==''
        assert await page.locator('#origin-name').input_value()==''
        await page.evaluate('''({tenant,rate,address})=>{
          document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;
          portal.role='CLIENT';portal.profile={tenant_id:tenant,portal_role:'CLIENT',workspace_role:'OWNER'};
          state.session={access_token:'controlled-browser',expires_at:Math.floor(Date.now()/1000)+3600};state.mode='configured';
          setView('dispatch');state.quotes=[rate];state.quoteRequest={origin:address,destination:{...address,country_code:'US'},currency:'GBP'};
          renderRates({rates:state.quotes,issues:[],partial:false});
        }''',{'tenant':tenant,'rate':rate,'address':address})
        await page.evaluate('''()=>{
          const varied=['DHL','DPD UK','UPS'].map((carrier,i)=>({...state.quotes[0],offer_id:'controlled-'+i,carrier_code:carrier}));
          state.quotes=varied;renderRates({rates:varied,issues:[],partial:false});
          document.querySelector('#carrier-filter').value='DPD UK';
          renderRates({rates:varied,issues:[],partial:false});
        }''')
        await expect(page.locator('#carrier-filter')).to_have_value('')
        assert await page.locator('[data-review]').count()==3
        await page.evaluate('''(rate)=>{state.quotes=[rate];renderRates({rates:[rate],issues:[],partial:false});}''',rate)
        await page.locator('[data-review]').click()
        await expect(page.locator('#review-dialog')).to_be_visible()
        review=await page.locator('#review-content').inner_text()
        assert 'Wholesale' not in review and 'markup' not in review and 'Provider did not supply' not in review
        assert 'Commercial customs document preview' not in review
        assert 'Label cost' in review and '£62.70' in review
        await page.locator('#confirm-preview').click()
        await expect(page.locator('#checkout-customs-yes')).to_be_visible()
        await page.locator('#checkout-customs-yes').click()
        form=page.locator('#customer-customs-form')
        await expect(form.locator('[name=description]')).to_have_value('Electric steam iron')
        await expect(form.locator('[name=hs_code]')).to_have_value('')
        await expect(form.locator('[name=invoice_reference]')).to_have_value(invoice)
        await expect(form.locator('[name=currency]')).to_have_value('USD')
        await expect(form.locator('input[readonly]').nth(1)).to_have_value('£62.70')
        await form.locator('[name=description]').fill('Electric smoothing iron for clothing')
        await form.locator('[data-checkout-hs]').click()
        await form.locator('[data-tariff-code]').click()
        await expect(form.locator('[name=hs_code]')).to_have_value('851640')
        await form.locator('[name=description]').fill('Electric steam iron for clothing')
        await expect(form.locator('[name=hs_code]')).to_have_value('')
        await form.locator('[data-checkout-hs]').click();await form.locator('[data-tariff-code]').click()
        for field in ['origin_country','quantity','unit_value','unit_weight_kg']:assert await form.locator('[name='+field+']').get_attribute('readonly') is not None
        await expect(form.locator('[name=unit_weight_kg]')).to_have_value('1.000')
        await form.locator('[name=category]').select_option('OTHER');await expect(page.locator('#checkout-other-field')).to_be_visible()
        await form.locator('[name=category_other]').fill('Exhibition demonstration')
        await form.locator('[name=signer]').fill('Test Shipper');await form.locator('[name=reviewed]').check()
        for width in (375,768,1366):
            await page.set_viewport_size({'width':width,'height':900})
            assert await page.evaluate('document.documentElement.scrollWidth-innerWidth')<=1
            assert await page.locator('#review-dialog').evaluate('(el)=>el.scrollWidth-el.clientWidth')<=1
        await page.set_viewport_size({'width':1366,'height':900})
        await page.screenshot(path=str(output/'customs-checkout.png'),full_page=True)
        await page.locator('#checkout-prepare-btn').click()
        await expect(page.locator('#checkout-purchase')).to_be_visible()
        await expect(page.locator('#checkout-next')).to_contain_text('price changed')
        await expect(page.locator('#checkout-price')).to_contain_text('£64.20')
        assert not any(kind=='purchase' for kind,_ in calls)
        await page.locator('#checkout-purchase').click()
        await expect(page.locator('#review-content')).to_contain_text('Shipment booked successfully')
        await expect(page.locator('#checkout-downloads')).to_contain_text('Commercial invoice PDF')
        await expect(page.locator('#checkout-downloads')).to_contain_text('Booking receipt PDF')
        assert sum(kind=='purchase' for kind,_ in calls)==1
        saved=next(body for kind,body in calls if kind=='prepare')['customs']
        assert saved['items'][0]['hs_code']=='851640' and saved['category_other']=='Exhibition demonstration'
        await page.screenshot(path=str(output/'booking-complete.png'),full_page=True)
        await page.locator('#checkout-new-shipment').click()
        await expect(page.locator('#review-dialog')).not_to_be_visible()
        assert await page.locator('#weight_kg').input_value()==''
        assert not errors,errors
        await browser.close()
    report={'status':'PASS','provider_boundary':'controlled API responses','javascript_errors':errors,
            'checks':['New quotes reset stale carrier filters; three distinct carriers remain visible','Customer price excludes wholesale and markup disclosures','No pre-booking customs preview or JSON downloads',
                'Saved goods snapshot with read-only quantity, value, net weight and origin; stable invoice reference and shipping cost',
                'Official tariff selection and stale-HS invalidation','OTHER category requires free text',
                '375/768/1366px responsive checkout','Changed price requires confirmation before one purchase',
                'Booking completion, label/invoice downloads and next-shipment reset']}
    (output/'browser_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(run())
