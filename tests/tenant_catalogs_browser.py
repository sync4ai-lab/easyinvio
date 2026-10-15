"""Isolated catalog UI and quote autofill verification with synthetic API records."""
import asyncio,json,os,socket,threading,time
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,unquote
from uuid import uuid4
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from playwright.async_api import async_playwright,expect

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())


async def run(origin):
    output=Path('output/tenant-catalogs');output.mkdir(parents=True,exist_ok=True)
    tenant=str(uuid4());calls=[];errors=[];tariff_calls=[];tariff_mode=['matches']
    address={'name':'Test Warehouse','company':'Northgate Test','line1':'9 Test Street','line2':'Unit 2','city':'Leeds','state':None,'postal_code':'LS1 1AA','country_code':'GB','phone':'+447123456789','email':'warehouse@example.test'}
    recipient={**address,'name':'Test Recipient','city':'Paris','postal_code':'75001','country_code':'FR'}
    records={'addresses':[{'id':str(uuid4()),'label':'Leeds dispatch','address':address,'address_role':'SENDER','is_default':True,'version':1}],
        'contacts':[{'id':str(uuid4()),'label':'Paris buyer','address':recipient,'version':1}],
        'products':[{'id':str(uuid4()),'sku':'SKU1','description':'Cotton knitted shirt','unit_weight_kg':'0.125','unit_value':'12.30','currency':'GBP','hs_code':'610910','origin_country':'GB','hs_reviewed':True,'version':1}]}
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch();page=await browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def handler(route):
            url=urlsplit(route.request.url);path=url.path;method=route.request.method
            if path=='/v1/rates':raise AssertionError('Unsupported freight must use manual intake, not parcel rate APIs')
            if path=='/api/v1/shipping/package-check':
                await route.fulfill(json={'blocking':True,'messages':[{'code':'FREIGHT_NOT_CONFIGURED'}]});return
            if path=='/api/v1/shipping/quote-support':
                data=route.request.post_data_json
                assert data['transport_mode']=='SEA' and data['origin_country']=='GB' and data['destination_country']=='FR'
                assert 'tenant_id' not in data and data['actual_weight_kg']=='1'
                calls.append((method,path,data))
                await route.fulfill(json={'case_id':str(uuid4()),'message':'Your request is saved for our shipping team.','booked':False});return
            if path=='/api/v1/checkout/hs-search':
                tariff_calls.append(route.request.post_data_json)
                assert route.request.post_data_json=={'description':'Steel bracket','official_only':True}
                if tariff_mode[0]=='unavailable':
                    await route.fulfill(status=503,json={'detail':'Official tariff lookup unavailable'});return
                if tariff_mode[0]=='empty':
                    await route.fulfill(json={'candidates':[],'question':'Describe the material and intended use.'});return
                await route.fulfill(json={'candidates':[{'hs_code':'732690','national_code':'7326909890',
                    'title':'Other articles of iron or steel','source':'UK Integrated Online Tariff'}]});return
            if path.startswith('/api/v1/catalog/'):
                parts=path.split('/');kind=parts[4];calls.append((method,path,route.request.post_data_json if method!='GET' else None))
                if '/by-sku/' in path:
                    sku=unquote(path.rsplit('/',1)[1]);record=next((row for row in records['products'] if row['sku'].lower()==sku.lower()),None)
                    await route.fulfill(status=200 if record else 404,json=record or {'detail':'SKU not found'});return
                if method=='GET':
                    params=parse_qs(url.query);q=params.get('q',[''])[0].lower();role=params.get('address_role',[None])[0]
                    items=[row for row in records[kind] if q in json.dumps(row).lower() and (role is None or row.get('address_role')==role)]
                    await route.fulfill(json={'items':items,'has_more':False,'offset':0,'limit':50});return
                data=route.request.post_data_json
                if method=='POST':
                    row={**data,'id':str(uuid4()),'version':1};records[kind].append(row);await route.fulfill(status=201,json=row);return
                if method=='PUT':
                    row=next(row for row in records[kind] if row['id']==parts[5]);row.update(data);row['version']+=1;await route.fulfill(json=row);return
                if method=='DELETE':
                    records[kind]=[row for row in records[kind] if row['id']!=parts[5]];await route.fulfill(json={'archived':True});return
            if path=='/api/v1/workspace/settings':
                await route.fulfill(json={'company':{'company_name':'Northgate Test','workspace_name':'Test dispatch','billing_email':'test@example.test'},'members':[],'invitations':[]});return
            await route.fulfill(json={'mode':'preview','supabase_url':None,'publishable_key':None})
        await page.route('**/api/v1/**',handler)
        await page.goto(origin+'/');await page.wait_for_function("document.querySelector('#catalog-tabs') || document.querySelector('#catalog-tab-products')")
        await page.evaluate('''tenant=>{document.body.classList.remove('auth-locked');document.querySelector('#loginContainer').hidden=true;portal.role='CLIENT';portal.profile={tenant_id:tenant,portal_role:'CLIENT',workspace_role:'OWNER'};state.session={access_token:'synthetic-browser-test',expires_at:Math.floor(Date.now()/1000)+3600};state.mode='configured';refreshEnterpriseNavigation();setView('settings');}''',tenant)
        await expect(page.locator('#catalog-records')).to_contain_text('Leeds dispatch')
        await expect(page.locator('.catalog-default')).to_contain_text('Default')
        await page.screenshot(path=str(output/'addresses.png'),full_page=True)
        await page.locator('#catalog-tab-contacts').click();await expect(page.locator('#catalog-records')).to_contain_text('Test Recipient')
        await page.locator('#catalog-tab-products').click();await expect(page.locator('#catalog-records')).to_contain_text('SKU1')
        await page.screenshot(path=str(output/'products.png'),full_page=True)
        await page.locator('#catalog-new').click();await expect(page.locator('#catalog-editor')).to_be_visible()
        await expect(page.locator('#catalog-form [name=hs_reviewed]')).to_be_disabled()
        await page.locator('#catalog-hs-search').click()
        await expect(page.locator('#catalog-hs-results')).to_contain_text('Add a product description')
        assert not tariff_calls
        for name,value in {'sku':'SKU2','description':'Steel bracket','unit_weight_kg':'0.250','unit_value':'4.50','origin_country':'GB'}.items():
            field=page.locator('#catalog-form [name='+name+']')
            if name=='origin_country':await field.select_option(value)
            else:await field.fill(value)
        await page.locator('#catalog-hs-search').click()
        await expect(page.locator('#catalog-hs-results')).to_contain_text('Other articles of iron or steel')
        await expect(page.locator('#catalog-hs-results a')).to_have_attribute('href','https://www.trade-tariff.service.gov.uk/commodities/7326909890')
        await page.locator('[data-catalog-hs-code]').click()
        await expect(page.locator('#catalog-form [name=hs_code]')).to_have_value('732690')
        await expect(page.locator('#catalog-form [name=hs_reviewed]')).not_to_be_checked()
        await page.locator('#catalog-form [name=hs_reviewed]').check()
        tariff_mode[0]='unavailable';await page.locator('#catalog-hs-search').click()
        await expect(page.locator('#catalog-hs-results')).to_contain_text('unavailable right now')
        await expect(page.locator('#catalog-form [name=hs_reviewed]')).not_to_be_checked()
        await expect(page.locator('#catalog-form [name=sku]')).to_have_value('SKU2')
        tariff_mode[0]='empty';await page.locator('#catalog-hs-search').click()
        await expect(page.locator('#catalog-hs-results')).to_contain_text('Describe the material')
        tariff_mode[0]='matches';await page.locator('#catalog-hs-search').click()
        await page.locator('[data-catalog-hs-code]').click()
        await page.locator('#catalog-form [name=hs_reviewed]').check()
        await page.locator('#catalog-form [name=hs_code]').fill('')
        await expect(page.locator('#catalog-form [name=hs_reviewed]')).to_be_disabled()
        await expect(page.locator('#catalog-form [name=hs_reviewed]')).not_to_be_checked()
        await page.locator('#catalog-hs-search').click();await page.locator('[data-catalog-hs-code]').click()
        await page.locator('#catalog-form [name=hs_reviewed]').check()
        await page.locator('#catalog-save').click();await expect(page.locator('#catalog-editor')).not_to_be_visible();await expect(page.locator('#catalog-records')).to_contain_text('SKU2')
        post=next(body for method,path,body in calls if method=='POST' and path.endswith('/products'))
        assert post['unit_weight_kg']=='0.250' and post['unit_value']=='4.50' and 'tenant_id' not in post
        await page.evaluate("setView('dispatch')")
        await expect(page.locator('#weight-result')).not_to_contain_text('body.actual_weight_kg')
        await expect(page.locator('#weight-result')).to_contain_text('Enter')
        await expect(page.locator('#shipment-hs-code')).to_be_hidden()
        assert await page.locator('label:has(#shipment-sku)').inner_text()=='Product SKU (type or search)'
        assert 'Enter these before requesting international goods rates' not in await page.locator('#quote-form').inner_text()
        records['addresses'][0]['address_role']='RETURN'
        await page.locator('[data-catalog-directory=origin]').click();await expect(page.locator('#catalog-directory-list')).to_contain_text('Leeds dispatch')
        await page.locator('#catalog-directory-search').fill('LEEDS')
        await expect(page.locator('#catalog-directory-list')).to_contain_text('Leeds dispatch')
        await page.locator('#catalog-directory-list button').first.click();await expect(page.locator('#origin-line1')).to_have_value('9 Test Street')
        await expect(page.locator('#origin-company')).to_have_value('Northgate Test')
        await page.locator('[data-catalog-directory=destination]').click();await page.locator('#catalog-directory-list button').first.click();await expect(page.locator('#destination-country_code')).to_have_value('FR')
        await page.locator('#shipment-sku').fill('SKU1');await expect(page.locator('#shipment-description')).to_have_value('Cotton knitted shirt');await expect(page.locator('#shipment-hs-code')).to_have_value('610910')
        await expect(page.locator('#shipment-unit-value')).to_have_value('12.30');assert await page.locator('#weight_kg').input_value()==''
        await page.locator('#catalog-add-item').click();extra=page.locator('.catalog-extra-item');await extra.locator('[data-catalog-sku]').fill('SKU2');await expect(extra.locator('[data-goods-field=description]')).to_have_value('Steel bracket')
        await expect(extra.locator('[data-goods-field=hs_code]')).to_be_hidden()
        await expect(extra.locator('h3')).to_have_text('Additional goods')
        assert 'Review the HS code before international shipping' not in await page.locator('#quote-form').inner_text()
        for field,value in {'length_cm':'30','width_cm':'20','height_cm':'15','weight_kg':'1'}.items():await page.locator('#'+field).fill(value)
        body=await page.evaluate('quotePayload()');assert len(body['shipment_items'])==2 and body['shipment_items'][0]['sku']=='SKU1' and body['shipment_items'][1]['hs_code']=='732690'
        await page.locator('#freight-quote-request').click()
        await expect(page.locator('#quote-support-dialog')).to_be_visible()
        await page.locator('#quote-support-mode').select_option('SEA')
        await page.locator('#quote-support-notes').fill('Synthetic freight request; two pallets')
        await page.locator('#quote-support-send').click()
        await expect(page.locator('#quote-support-status')).to_contain_text('Reference:')
        assert len([call for call in calls if call[1]=='/api/v1/shipping/quote-support'])==1
        await page.locator('#quote-support-close').click()
        await page.locator('#cargo-type').select_option('OVERLAND_FREIGHT')
        for field,value in {'length_cm':'120','width_cm':'80','height_cm':'100','weight_kg':'100'}.items():await page.locator('#'+field).fill(value)
        await expect(page.locator('#quote-btn')).to_have_text('Request a freight quote')
        await page.locator('#quote-btn').click()
        await expect(page.locator('#quote-support-dialog')).to_be_visible()
        await expect(page.locator('#quote-support-mode')).to_have_value('ROAD')
        await page.locator('#quote-support-close').click()
        await page.locator('#cargo-type').select_option('PARCEL')
        assert body['origin']['phone']=='+447123456789' and body['destination']['city']=='Paris'
        await page.locator('#shipment-description').fill('Different material');await expect(page.locator('#shipment-hs-code')).to_have_value('')
        await page.evaluate('resetQuoteForm()');assert await page.locator('.catalog-extra-item').count()==0
        await page.evaluate("portal.profile.workspace_role='ACCOUNTANT';setView('settings')");await expect(page.locator('#catalog-new')).to_be_hidden();await expect(page.locator('#catalog-tab-company')).to_be_hidden()
        await page.evaluate("portal.profile.workspace_role='OWNER';setView('settings')");await page.locator('#catalog-tab-products').click();await page.locator('#catalog-new').click()
        await page.set_viewport_size({'width':390,'height':844});assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        await page.screenshot(path=str(output/'product-modal-mobile.png'),full_page=True);await page.locator('#catalog-editor [data-catalog-close]').first.click()
        await page.evaluate("portal.profile.tenant_id='another-workspace';setView('dispatch')");await expect(page.locator('#origin-line1')).to_have_value('');await expect(page.locator('#destination-line1')).to_have_value('')
        await page.evaluate('''()=>{const base={offer_id:'test-offer',carrier_code:'DHL',service_code:'Express',currency:'GBP',client_price_ex_tax:'15.00',delivery_days:3,fee_breakdown:{},recommendation_badge:'EasyInvio Suggested Choice · Price and available delivery information considered'};state.quotes=[base,{...base,offer_id:'second-test-offer',carrier_code:'UPS',client_price_ex_tax:'16.00',recommendation_badge:null}];renderRates({rates:state.quotes,issues:[],partial:false,currency:'GBP'});}''')
        await expect(page.locator('.rate')).to_have_count(2)
        await expect(page.locator('.rate').first).to_contain_text('EasyInvio Suggested Choice')
        assert 'EasyInvio Suggested Choice' not in await page.locator('.rate').nth(1).inner_text()
        await page.screenshot(path=str(output/'recommendation-mobile.png'),full_page=True)
        assert not errors,errors
        await browser.close()
    print(json.dumps({'status':'PASS','page_errors':errors,'checks':['Catalog CRUD and exact decimal strings','Address/contact autofill','SKU and multi-item quote snapshots','HS invalidation and next-shipment reset','Accountant read-only access','Mobile layout','Workspace-change clearing'],'provider_calls':0,'database_calls':0},indent=2))


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
