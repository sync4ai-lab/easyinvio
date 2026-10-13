"""Rollback-only actual Supabase checkout; all carrier HTTP is controlled."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID,uuid4

import asyncpg
import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pypdf import PdfReader

import main
from backend.automation_freight_engine import AutomationService
from backend.automation_three_partners import PartnerLifecycleService,BookingRequest
from backend.customer_checkout import build_router,CheckoutPrepare


async def run():
    settings=main.Settings();assert settings.provider_environment=='TEST' and settings.database_environment=='SANDBOX'
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),timeout=15,
        ssl=main.database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    outer=connection.transaction(isolation='repeatable_read');await outer.start()
    report={'executed_at':datetime.now(timezone.utc).isoformat(),'database':'actual Supabase SANDBOX',
            'provider_responses':'controlled MockTransport','external_carrier_calls':0,'checks':[]}
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield connection
    try:
        tenant=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
        assert tenant
        member=await connection.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active",tenant)
        context=main.TenantContext(tenant,member,'OWNER','')
        pid=uuid4();key_id=sorted(settings.credential_keys)[0];secret='synthetic-checkout-key'
        ciphertext=Fernet(settings.credential_keys[key_id].get_secret_value().encode()).encrypt(json.dumps({'platform_id':str(pid),'api_key':secret}).encode())
        await connection.execute('''INSERT INTO public.platform_carrier_connections
            (id,account_name,aggregator,api_base_url,environment,credentials_ciphertext,credential_key_id,is_active,priority,timeout_seconds)
            VALUES($1,'ROLLBACK Customer Checkout','EASYPOST','https://api.easypost.com/v2','TEST',$2,$3,true,10,30)''',pid,ciphertext,key_id)
        aid=await connection.fetchval('SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND platform_connection_id=$2',tenant,pid)
        account=main.CarrierAccount(aid,tenant,'EASYPOST','https://api.easypost.com/v2',None,30,secret,pid)
        class Repository:
            async def accounts(self,user,**kwargs):
                assert user.tenant_id==tenant;return [account]
        calls=[];remote={};customs_seen=[]
        def transport(request):
            calls.append((request.method,request.url.path))
            if request.method=='POST' and request.url.path=='/v2/shipments':
                payload=json.loads(request.content)['shipment'];customs=payload.get('customs_info')
                if customs:
                    customs_seen.append(customs);assert customs['customs_items'][0]['value']=='25.00'
                    assert customs['contents_type']=='other' and customs['contents_explanation']=='Exhibition demonstration'
                sid='shp_'+uuid4().hex;rid='rate_'+uuid4().hex
                body={'id':sid,'mode':'test','rates':[{'id':rid,'carrier':'DHL','service':'Express','currency':'GBP',
                    'rate':'12.00' if customs else '10.00','delivery_days':2}]}
                body['rates'].append({'id':'rate_'+uuid4().hex,'carrier':'UPS','service':'Express Saver','currency':'GBP','rate':'13.00' if customs else '11.00','delivery_days':3})
                remote[sid]=body;return httpx.Response(201,json=body)
            sid=request.url.path.split('/')[3];body=remote[sid]
            if request.method=='POST':
                assert request.url.path.endswith('/buy')
                body.update(selected_rate={'id':json.loads(request.content)['rate']['id']},tracking_code='TEST-'+sid[-12:],
                    postage_label={'label_pdf_url':'https://easypost-files.s3.amazonaws.com/synthetic-checkout.pdf'})
            return httpx.Response(200,json=body)
        pool=Pool();finance=main.FinanceEngine(pool,settings,None)
        await connection.execute('UPDATE public.wallets SET balance=1000,reserved_balance=0 WHERE tenant_id=$1',tenant)
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            repository=Repository();rating=main.RatingService(client,repository,settings,pool=pool)
            automation=AutomationService(pool,rating,finance,repository,main.RatingRequest,client,settings)
            service=PartnerLifecycleService(automation,client)
            origin={'name':'QA Exporter','line1':'1 Fixture Way','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
            destination={'name':'QA Buyer','line1':'228 Park Ave S','city':'New York','state':'NY','postal_code':'10003','country_code':'US'}
            quote_request=main.RatingRequest(origin=origin,destination=destination,currency='GBP',weights_kg=['2'],
                dimensions=[{'length_cm':'20','width_cm':'20','height_cm':'20'}],goods_currency='USD',shipment_items=[{'description':'Electric smoothing iron','quantity':1,'unit_value':'25.00','unit_weight_kg':'1.000','origin_country':'GB'}])
            quoted=await rating.quote(context,quote_request)
            await connection.execute('''INSERT INTO public.partner_unbound_quotes(tenant_id,request_id,request_payload,quote_payload,expires_at)
                VALUES($1,$2,$3::jsonb,$4::jsonb,$5)''',tenant,quoted.request_id,quote_request.model_dump_json(),quoted.model_dump_json(),quoted.expires_at)
            endpoints={route.path:route.endpoint for route in build_router(lambda:None).routes}
            req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(partner_lifecycle=service)))
            data=await endpoints['/api/v1/checkout/context'](quoted.rates[0].offer_id,req,context)
            assert data['goods_value_currency']=='USD' and data['customs_required']
            repeated=await endpoints['/api/v1/checkout/context'](quoted.rates[0].offer_id,req,context)
            assert repeated['invoice_reference']==data['invoice_reference']
            body=CheckoutPrepare(offer_id=quoted.rates[0].offer_id,customs={'items':[{'description':'Electric smoothing iron',
                'hs_code':'851640','origin_country':'GB','quantity':1,'unit_value':'25.00','unit_weight_kg':'1.000'}],
                'signer':'QA Shipper','reviewed':True,'currency':'USD','category':'OTHER','category_other':'Exhibition demonstration'})
            changed=body.model_copy(deep=True);changed.customs.items[0].quantity=2
            try:await endpoints['/api/v1/checkout/prepare'](changed,req,context)
            except HTTPException as exc:assert exc.status_code==409
            else:raise AssertionError('Quoted goods snapshot was editable')
            prepared=await endpoints['/api/v1/checkout/prepare'](body,req,context)
            assert prepared['price_changed'] and prepared['invoice_reference']==data['invoice_reference']
            sid=UUID(prepared['shipment_id']);invoice_endpoint=endpoints['/api/v1/checkout/{shipment_id}/commercial-invoice.pdf']
            receipt_endpoint=endpoints['/api/v1/checkout/{shipment_id}/receipt.pdf']
            try:await receipt_endpoint(sid,req,context)
            except HTTPException as exc:assert exc.status_code==409
            else:raise AssertionError('Receipt downloaded before booking')
            try:await invoice_endpoint(sid,req,context)
            except HTTPException as exc:assert exc.status_code==409
            else:raise AssertionError('Invoice downloaded before payment')
            assert customs_seen and not any(path.endswith('/buy') for _,path in calls)
            report['checks'].append('PASS: international customs are attached to native re-quote; invoice reference persists; final price changes require consent; PDF unavailable before payment')
            booked=await service.confirm(context,BookingRequest(tenant_id=tenant,offer_id=prepared['offer']['offer_id']))
            assert booked['status']=='BOOKED'
            replay=await service.confirm(context,BookingRequest(tenant_id=tenant,offer_id=prepared['offer']['offer_id']))
            assert replay['replayed'] and sum(path.endswith('/buy') for _,path in calls)==1
            amount=Decimal(prepared['offer']['client_price_ex_tax'])
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==Decimal('1000')-amount
            assert await connection.fetchval('SELECT reserved_balance FROM public.wallets WHERE tenant_id=$1',tenant)==0
            pdf=await invoice_endpoint(sid,req,context);text=''.join(page.extract_text() for page in PdfReader(BytesIO(pdf.body)).pages)
            assert data['invoice_reference'] in text and str(amount)+' GBP' in text and '25.00 USD' in text
            assert 'Exhibition demonstration' in text
            receipt=await receipt_endpoint(sid,req,context)
            receipt_text=''.join(page.extract_text() for page in PdfReader(BytesIO(receipt.body)).pages)
            assert data['invoice_reference'] in receipt_text and 'GBP '+str(amount) in receipt_text
            another=await rating.quote(context,quote_request)
            await connection.execute('''INSERT INTO public.partner_unbound_quotes(tenant_id,request_id,request_payload,quote_payload,expires_at)
                VALUES($1,$2,$3::jsonb,$4::jsonb,$5)''',tenant,another.request_id,quote_request.model_dump_json(),another.model_dump_json(),another.expires_at)
            another_data=await endpoints['/api/v1/checkout/context'](another.rates[0].offer_id,req,context)
            assert int(another_data['invoice_reference'].split('-')[-1])>int(data['invoice_reference'].split('-')[-1])
            report['checks'].append('PASS: immutable quoted goods; repeated checkout reference is stable; next booking gets a higher EINVIO number; receipt shares the reference and is unavailable before booking')
            report['checks'].append('PASS: one label purchase, one wallet capture, booking replay and branded PDF with linked reference, real shipping cost and separate goods currency')
            other=main.TenantContext(uuid4(),member,'OWNER','')
            try:await invoice_endpoint(sid,req,other)
            except HTTPException as exc:assert exc.status_code==404
            else:raise AssertionError('Foreign invoice accessible')
            report['checks'].append('PASS: foreign tenant invoice access rejected')
            from backend.bulk_checkout import review_orders,checkout_orders,CheckoutSelection
            from backend.dispatch_pdf import bundle_shipments
            from reportlab.pdfgen import canvas
            order={'idempotency_key':str(uuid4()),'order_reference':'ROLLBACK-BULK-REVIEW','origin':origin,'destination':origin,'currency':'GBP',
                'cargo':{'cargo_type':'PARCEL','actual_weight_kg':'2','length_cm':'20','width_cm':'20','height_cm':'20'},'items':[]}
            quoted_bulk=await automation.process(context,order,'QUOTE_ONLY');assert quoted_bulk['status']=='QUOTED'
            bulk_sid=UUID(quoted_bulk['shipment_id']);review=await review_orders(service,context,[bulk_sid]);assert len(review['orders'][0]['rates'])==2
            chosen=max(review['orders'][0]['rates'],key=lambda r:Decimal(r['client_price_ex_tax']))
            before=await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)
            selection=CheckoutSelection(offers=[{'shipment_id':bulk_sid,'offer_id':chosen['offer_id'],'expected_price':chosen['client_price_ex_tax'],'currency':chosen['currency']}])
            result=await checkout_orders(service,context,selection);assert result['results'][0]['status']=='BOOKED'
            assert await connection.fetchval('SELECT carrier_code FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,bulk_sid)=='UPS'
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before-Decimal(chosen['client_price_ex_tax'])
            purchases=sum(path.endswith('/buy') for _,path in calls);assert (await checkout_orders(service,context,selection))['results'][0]['replayed']
            assert sum(path.endswith('/buy') for _,path in calls)==purchases
            label=BytesIO();page=canvas.Canvas(label,pagesize=(288,432));page.drawString(20,390,'SYNTHETIC TEST CARRIER LABEL');page.save()
            shipment=await connection.fetchrow('SELECT * FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,bulk_sid)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=label.getvalue(),headers={'content-type':'application/pdf'}))) as pdf_client:
                bundle=await bundle_shipments([shipment],client=pdf_client,hosts=set(settings.partner_document_allowed_hosts));assert len(PdfReader(BytesIO(bundle)).pages)==1
            report['checks'].append('PASS: bulk review exposes two distinct services; explicit higher-priced UPS choice is purchased; selected price captured once; checkout replay buys nothing; confirmed label PDF bundle generated without external calls')


            from backend.card_checkout import create_cart,complete_cart,CardCart
            from backend.payment_gateway import reconcile_topup
            sessions={}
            async def checkout_create(params,options=None):
                session_id='cs_test_'+params['client_reference_id'];value=params['line_items'][0]['price_data']['unit_amount']
                sessions[session_id]={'id':session_id,'object':'checkout.session','customer':params['customer'],'mode':'payment','livemode':False,'payment_status':'unpaid',
                    'currency':'gbp','amount_total':value,'client_reference_id':params['client_reference_id'],'metadata':params['metadata'],
                    'payment_intent':{'id':'pi_'+params['client_reference_id'],'status':'succeeded','latest_charge':{'id':'ch_'+params['client_reference_id'],'paid':True,'amount_refunded':0}}}
                return SimpleNamespace(id=session_id,url='https://checkout.stripe.com/c/pay/'+session_id)
            async def retrieve(session_id,*args):return sessions[session_id]
            async def create_customer(*args,**kwargs):return SimpleNamespace(id='cus_synthetic_card',livemode=False)
            finance.stripe=SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=checkout_create,retrieve_async=retrieve)),customers=SimpleNamespace(create_async=create_customer)))
            await connection.execute('UPDATE public.wallets SET balance=0,reserved_balance=0 WHERE tenant_id=$1',tenant)
            before=await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)
            async def card_order(reference):
                value={**order,'idempotency_key':str(uuid4()),'order_reference':reference}
                q=await automation.process(context,value,'QUOTE_ONLY');assert q['status']=='QUOTED'
                row=(await review_orders(service,context,[UUID(q['shipment_id'])]))['orders'][0];chosen=row['rates'][0]
                body=CardCart(request_id=uuid4(),return_origin='http://127.0.0.1:8000',offers=[{'shipment_id':row['shipment_id'],'offer_id':chosen['offer_id'],'expected_price':chosen['client_price_ex_tax'],'currency':chosen['currency']}])
                cart=await create_cart(service,context,body)
                return body,cart
            body,cart=await card_order('ROLLBACK-CARD-LABEL')
            assert (await complete_cart(service,context,body.request_id))['status']=='AWAITING_PAYMENT'
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before
            session=sessions['cs_test_'+str(body.request_id)];session['payment_status']='paid'
            await connection.execute("UPDATE public.payment_carts SET updated_at=now()-interval '30 seconds' WHERE id=$1",body.request_id)
            done=await complete_cart(service,context,body.request_id);assert done['status']=='COMPLETED'
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before
            assert await connection.fetchval('SELECT reserved_balance FROM public.wallets WHERE tenant_id=$1',tenant)==0
            assert await connection.fetchval("SELECT count(*) FROM public.wallet_ledger WHERE topup_id=$1 AND entry_type='TOPUP'",body.request_id)==1
            buys=sum(path.endswith('/buy') for _,path in calls)
            assert (await complete_cart(service,context,body.request_id))['replayed']
            assert sum(path.endswith('/buy') for _,path in calls)==buys
            assert (await reconcile_topup(finance,context,body.request_id))['already_credited']
            await connection.execute("UPDATE public.shipments SET status='IN_TRANSIT' WHERE id=$1",body.offers[0].shipment_id)
            transit_replay=await checkout_orders(service,context,CheckoutSelection(offers=body.offers));assert transit_replay['results'][0]['replayed']
            assert sum(path.endswith('/buy') for _,path in calls)==buys
            card_receipt=await receipt_endpoint(body.offers[0].shipment_id,req,context)
            assert 'Card payment through Stripe' in ''.join(p.extract_text() for p in PdfReader(BytesIO(card_receipt.body)).pages)
            report['checks'].append('PASS: card basket unpaid does not credit or buy; paid Stripe API snapshot funds exact total, books label and captures once; zero initial wallet balance is sufficient for card checkout and stays zero after the label; card receipt and replay are correct')
            body2,cart2=await card_order('ROLLBACK-CARD-EXPIRED')
            sessions['cs_test_'+str(body2.request_id)]['payment_status']='paid'
            await connection.execute("UPDATE public.payment_carts SET updated_at=now()-interval '30 seconds' WHERE id=$1",body2.request_id)
            await connection.execute("UPDATE public.shipments SET quoted_at=now()-interval '20 seconds',quote_expires_at=now()-interval '1 second' WHERE id=$1",body2.offers[0].shipment_id)
            expired=await complete_cart(service,context,body2.request_id);assert expired['status']=='REVIEW_REQUIRED'
            assert sum(path.endswith('/buy') for _,path in calls)==buys
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before+Decimal(cart2['amount'])
            report['checks'].append('PASS: paid expired basket purchases nothing; verified funds remain available in the wallet for fresh rates')
        report['status']='PASS'
    finally:
        await outer.rollback();await connection.close();report['database_writes_rolled_back']=True
    path=Path('docs/card_checkout/database_probe.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(run())
