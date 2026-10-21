"""Manual preview-only status/persona QA. Synthetic data; no carrier purchases."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.playwright'))
from playwright.async_api import async_playwright
from backend.manifest_workflow import workflow, requote_context


def fixtures():
    now=datetime.now(timezone.utc);result=[]
    statuses=['PENDING_IMPORT','UNFULFILLED','DRAFT','QUOTED','QUOTE_EXPIRED','QUOTE_UNAVAILABLE','FAILED','BOOKING','SYNC_PENDING','LABEL_CREATED','MANIFESTED','DISPATCHED','IN_TRANSIT','OUT_FOR_DELIVERY','EXCEPTION','DELIVERED','CANCELLED','RETURN_QR']
    for label in statuses:
        state={'QUOTE_EXPIRED':'QUOTED','QUOTE_UNAVAILABLE':'QUOTED','SYNC_PENDING':'BOOKING','LABEL_CREATED':'BOOKED','OUT_FOR_DELIVERY':'IN_TRANSIT','RETURN_QR':'BOOKED'}.get(label,label)
        booked=label in {'LABEL_CREATED','MANIFESTED','DISPATCHED','IN_TRANSIT','OUT_FOR_DELIVERY','EXCEPTION','DELIVERED','RETURN_QR'}
        row={'id':str(uuid4()),'tenant_id':str(uuid4()),'status':state,'reference':'SYNTHETIC-'+label,'customer_reference':'SYNTHETIC-'+label,
            'carrier_code':'ROYALMAIL','service_code':'TRACKED_48','currency':'GBP','price':'19.94','cargo_type':'PARCEL',
            'origin_country':'GB','destination_country':'GB','customs_required':True,
            'booked_at':now if booked else None,'tracking_number':'SYNTHETIC-TRACK-'+label if booked else None,
            'quote_expires_at':None if label=='QUOTE_UNAVAILABLE' else now+timedelta(minutes=-5 if label=='QUOTE_EXPIRED' else 5),
            'reservation_status':'CAPTURED' if booked else None,'billing_plan':'PREPAID_WALLET',
            'proof_of_delivery_url':'https://carrier.example.test/proof' if label in {'DELIVERED','FAILED'} else None,
            'tracking_lifecycle_type':'RETURN_SHIPMENT' if label=='RETURN_QR' else 'FORWARD_SHIPMENT'}
        goods=[{'description':'Synthetic books','quantity':1,'unit_value':'12.00','unit_weight_kg':'1.000','origin_country':'GB','package_index':1,'sku':'QA-BOOK','hs_code':'490199'},
               {'description':'Synthetic prints','quantity':1,'unit_value':'8.00','unit_weight_kg':'1.000','origin_country':'GB','package_index':2,'sku':'QA-PRINT'}]
        boxes=[{'actual_weight_kg':'2.000','length_cm':'24','width_cm':'16','height_cm':'8'},{'actual_weight_kg':'3.500','length_cm':'30','width_cm':'20','height_cm':'10'}]
        origin={'name':'Synthetic sender','company':'Synthetic warehouse','line1':'1 Test Street','line2':'Unit A','city':'Leeds','state':'','postal_code':'LS1 2TW','country_code':'GB','phone':'+447700900000','email':'sender@example.test'}
        destination={**origin,'name':'Synthetic recipient','line1':'2 Test Street','city':'London','postal_code':'SW1A 1AA'}
        metadata={'automation_order':{'origin':origin,'destination':destination,'cargo':{'cargo_type':'PARCEL','stackable':True},'packages':boxes,'items':goods,'customs_currency':'GBP'},
                  'automation_customs':{'required':True,'ready_for_provider':booked,'currency':'GBP','items':goods},
                  'label_lifecycle_status':'SYNC_PENDING' if label=='SYNC_PENDING' else 'LABEL_CREATED' if booked else None,
                  'tracking':{'milestone':'OUT_FOR_DELIVERY'} if label=='OUT_FOR_DELIVERY' else {}}
        if label=='PENDING_IMPORT':metadata['batch_csv']={}
        if booked:metadata['automation_label']={'label_url':'https://carrier.example.test/label.pdf'}
        if label=='RETURN_QR':metadata['automation_label']['return_dropoff_qr_code_base64']='synthetic-only'
        row.update(logistics_metadata=metadata,metadata=metadata,label_status=metadata['label_lifecycle_status'],customs_declaration=metadata['automation_customs'])
        row['workflow']=workflow(row,now=now)
        row['restore']=requote_context(row) if row['workflow']['can_requote'] else None
        result.append(row)
    return json.loads(json.dumps(result,default=lambda value:value.isoformat()))


async def main():
    origin=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8768'
    output=ROOT/'output/manifest-workflow-qa';output.mkdir(parents=True,exist_ok=True)
    rows=fixtures();report={'data':'SYNTHETIC_ONLY','statuses':18,'personas':[],'mutations':0}
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        for role in ['OWNER','ADMIN','DISPATCHER','ACCOUNTANT','INDIVIDUAL','SUPER_ADMIN']:
            page=await browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            async def offline(route):
                if not route.request.url.startswith(origin):return await route.abort()
                if '/api/' in route.request.url or '/v1/' in route.request.url:
                    if '/documents/' in route.request.url or route.request.url.endswith('.pdf'):
                        qr=route.request.url.endswith('return-qr')
                        return await route.fulfill(content_type='image/png' if qr else 'application/pdf',body=b'\x89PNG\r\n\x1a\nSYNTHETIC' if qr else b'%PDF-1.4 SYNTHETIC QA DOCUMENT')
                    return await route.fulfill(status=503,json={'detail':'Synthetic preview: disconnected backend'})
                await route.continue_()
            await page.route('**/*',offline)
            await page.goto(origin,wait_until='domcontentloaded')
            await page.wait_for_function("typeof ManifestWorkflow!=='undefined' && typeof manifestBulkSelected!=='undefined'")
            await page.evaluate('''({role,rows})=>{
              window.qaRows=rows;window.qaCalls=[];
              api=async(path,options={})=>{
                qaCalls.push({path,method:options.method||'GET'});
                if(path.endsWith('/requote-context'))return rows.find(row=>path.includes(row.id)).restore;
                if(path.endsWith('/bulk/review'))return {orders:options.body.shipment_ids.map(id=>({shipment_id:id,reference:'Synthetic checkout',status:'QUOTED',customs_ready:true,batch_import:false,rates:[{offer_id:'00000000-0000-4000-8000-000000000051',carrier_code:'ROYALMAIL',service_code:'TRACKED_48',client_price_ex_tax:'19.94',currency:'GBP',expires_at:rows[3].quote_expires_at}]}))};
                if(path.includes('/tracking/shipments/'))return {shipments:[{id:rows.find(row=>path.endsWith(row.id))?.id,timeline:[{status:'IN_TRANSIT',occurred_at:new Date().toISOString(),location:'Synthetic hub'}]}]};
                if(path.endsWith('/manifest'))return {shipments:rows,server_time:new Date().toISOString()};
                if(path.includes('/weight'))return {actual_weight_kg:'2.000',billable_weight_kg:'2.000',basis:'actual'};
                if(options.method&&options.method!=='GET')throw Error('Unexpected mutation '+path);
                return {};
              };
              state.session={access_token:'SYNTHETIC_ONLY',expires_at:Math.floor(Date.now()/1000)+3600};state.mode='configured';
              portal.role=role==='SUPER_ADMIN'?'SUPER_ADMIN':'CLIENT';
              portal.profile={tenant_id:rows[0].tenant_id,portal_role:portal.role,workspace_role:['INDIVIDUAL','SUPER_ADMIN'].includes(role)?'OWNER':role,workspace_type:role==='INDIVIDUAL'?'INDIVIDUAL':'BUSINESS'};
              document.body.classList.remove('auth-locked');document.querySelectorAll('#identity-gate,[data-identity-gate]').forEach(node=>node.hidden=true);
              document.querySelectorAll('dialog[open]').forEach(node=>node.close());
              refreshEnterpriseNavigation();setView('manifest');state.manifest=rows;renderManifest();
            }''',{'role':role,'rows':rows})
            dispatch=role in {'OWNER','ADMIN','DISPATCHER','INDIVIDUAL'}
            if role!='SUPER_ADMIN':
                await page.locator('#manifest-search').fill('ROYALMAIL')
                assert await page.locator('#manifest-body [data-manifest-detail]').count()==18
                await page.locator('#manifest-search').fill('')
                await page.locator('#manifest-filter').select_option('QUOTE_EXPIRED')
                assert await page.locator('#manifest-body [data-manifest-detail]').count()==1
                await page.locator('#manifest-filter').select_option('all')
            if role!='SUPER_ADMIN':await page.screenshot(path=str(output/f'{role.lower()}-manifest.png'))
            for row in rows:
                action=page.locator(f'#manifest-body [data-manifest-detail="{row["id"]}"]')
                assert await action.count()==1
                tr=action.locator('xpath=ancestor::tr')
                assert await tr.locator('[data-manifest-pod]').count()==int(row['workflow']['has_pod'])
                assert await tr.locator('[data-print]').count()==int(dispatch and row['workflow']['has_label'])
                assert await tr.locator('[data-manifest-qr]').count()==int(dispatch and row['workflow']['has_qr'])
                assert await tr.locator('[data-manifest-book]').count()==int(dispatch and row['workflow']['can_select'])
                assert await tr.locator('[data-manifest-requote]').count()==int(dispatch and row['workflow']['can_requote'])
                assert 'Not recorded' not in await tr.locator('td').nth(1).inner_text()
            # Admin cross-workspace manifest remains read-only, not tenant impersonation.
            if role!='SUPER_ADMIN':
                failed=rows[6]
                await page.locator(f'#manifest-body [data-manifest-detail="{failed["id"]}"]').click()
                assert await page.locator('#shipment-detail').get_by_text('Synthetic books',exact=True).count()==1
                assert await page.locator('#shipment-detail pre').count()==0
                assert await page.locator('#shipment-doc-print').is_hidden()
                await page.screenshot(path=str(output/f'{role.lower()}-details.png'))
                await page.locator('#shipment-dialog .close').click()
                delivered=rows[15]
                await page.locator(f'#manifest-body [data-manifest-detail="{delivered["id"]}"]').click()
                await page.locator('#shipment-detail').get_by_text('Synthetic hub',exact=True).wait_for()
                if role!='DISPATCHER':
                    async with page.expect_download() as receipt:
                        await page.locator('#shipment-receipt').click()
                    assert (await receipt.value).suggested_filename=='easyinvio-booking-receipt.pdf'
                async with page.expect_download() as invoice:
                    await page.locator('#shipment-doc-print').click()
                assert (await invoice.value).suggested_filename=='easyinvio-commercial-invoice.pdf'
                await page.locator('#shipment-dialog .close').click()
                await page.locator(f'#manifest-body [data-manifest-pod="{delivered["id"]}"]').click()
                assert await page.locator('#pod-content a').get_attribute('href')=='https://carrier.example.test/proof'
                await page.locator('#pod-dialog .close').click()
                if dispatch:
                    async with page.expect_download() as label:
                        await page.locator(f'#manifest-body [data-print="{delivered["id"]}"]').click()
                    assert (await label.value).suggested_filename=='easyinvio-shipping-label.pdf'
                    async with page.expect_download() as qr:
                        await page.locator(f'#manifest-body [data-manifest-qr="{rows[-1]["id"]}"]').click()
                    assert (await qr.value).suggested_filename=='easyinvio-carrier-drop-off-qr.png'
                    quoted=rows[3]
                    await page.locator(f'#manifest-body [data-manifest-book="{quoted["id"]}"]').click()
                    await page.locator('#bulk-checkout-dialog').wait_for(state='visible')
                    assert '19.94' in await page.locator('#bulk-checkout-body').inner_text()
                    await page.locator('#bulk-checkout-close').click()
                    await page.locator(f'#manifest-body [data-bulk-manifest="{quoted["id"]}"]').check()
                    assert '(1)' in await page.locator('#manifest-bulk-review').inner_text()
                    assert not await page.locator('#manifest-bulk-review').is_disabled()
                    # Expiry removes stale selection and the purchase action in-place.
                    await page.evaluate("state.manifest.find(row=>row.reference==='SYNTHETIC-QUOTED').quote_expires_at=new Date(Date.now()-1000).toISOString()")
                    await page.wait_for_function('manifestBulkSelected.size===0')
                    assert await page.locator('#manifest-bulk-review').is_disabled()
                    await page.locator(f'#manifest-body [data-manifest-requote="{rows[4]["id"]}"]').click()
                    await page.locator('#manifest-restored-packages').wait_for(state='visible')
                    assert await page.locator('#origin-line1').input_value()=='1 Test Street'
                    assert await page.locator('#destination-postal_code').input_value()=='SW1A 1AA'
                    payload=await page.evaluate('quotePayload()')
                    assert payload['weights_kg']==['2.000','3.500'] and len(payload['shipment_items'])==2
                    assert payload['shipment_items'][1]['package_index']==2 and payload['shipment_items'][1]['sku']=='QA-PRINT'
                    assert payload['dimensions'][1]['length_cm']=='30'
                    await page.screenshot(path=str(output/f'{role.lower()}-requote.png'))
            if role!='SUPER_ADMIN':await page.evaluate("setView('manifest');renderManifest()")
            else:assert await page.locator('#manifest').is_hidden()
            for width in (375,768,1440):
                await page.set_viewport_size({'width':width,'height':1000})
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                if width==375 and role!='SUPER_ADMIN':await page.screenshot(path=str(output/f'{role.lower()}-manifest-mobile.png'))
            assert not errors,errors
            assert not any(call['method']=='POST' and not (call['path'].endswith('/bulk/review') or '/logistics/' in call['path']) for call in await page.evaluate('qaCalls')),await page.evaluate('qaCalls')
            report['personas'].append({'role':role,'status_action_rows':18,'result':'passed','page_errors':errors})
            await page.close()
        await browser.close()
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':asyncio.run(main())
