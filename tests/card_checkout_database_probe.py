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
        calls=[];remote={};customs_seen=[];reject_purchase=[False]
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
            if request.url.path.startswith('/v2/orders'):
                if request.method=='POST' and request.url.path=='/v2/orders':
                    pieces=json.loads(request.content)['order']['shipments'];assert len(pieces)==2
                    oid='order_'+uuid4().hex
                    body={'id':oid,'mode':'test','rates':[{'id':'rate_'+uuid4().hex,'carrier':'UPS','service':'Ground','currency':'GBP','rate':'18.00'}],
                          'shipments':[{'id':'shp_'+uuid4().hex,'mode':'test'} for piece in pieces]}
                    remote[oid]=body;return httpx.Response(201,json=body)
                oid=request.url.path.split('/')[3];body=remote[oid]
                if request.method=='POST':
                    for index,piece in enumerate(body['shipments']):
                        piece.update(selected_rate={'id':'rate_'+str(index),'carrier':'UPS','service':'Ground'},tracking_code='GROUP-'+piece['id'][-12:],postage_label={'label_pdf_url':'https://easypost-files.s3.amazonaws.com/box'+str(index)+'.pdf'})
                return httpx.Response(200,json=body)
            sid=request.url.path.split('/')[3];body=remote[sid]
            if request.method=='POST':
                assert request.url.path.endswith('/buy')
                if reject_purchase[0]:return httpx.Response(400,json={'error':{'code':'controlled_rejection'}})
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
            reject_purchase[0]=True
            failed_order={**order,'idempotency_key':str(uuid4()),'order_reference':'ROLLBACK-REJECTED-LABEL'}
            failed_quote=await automation.process(context,failed_order,'QUOTE_ONLY')
            failed_id=UUID(failed_quote['shipment_id']);failed_review=await review_orders(service,context,[failed_id]);failed_rate=failed_review['orders'][0]['rates'][0]
            before=await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)
            try:await service.confirm(context,BookingRequest(tenant_id=tenant,offer_id=UUID(failed_rate['offer_id'])))
            except HTTPException as exc:assert exc.status_code==502
            else:raise AssertionError('Rejected label falsely booked')
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before
            assert await connection.fetchval('SELECT reserved_balance FROM public.wallets WHERE tenant_id=$1',tenant)==0
            failure=await connection.fetchrow("SELECT status,logistics_metadata->'purchase_failure' AS diagnostic FROM public.shipments WHERE id=$1",failed_id)
            assert failure['status']=='FAILED' and json.loads(failure['diagnostic'])['http_status']==400
            assert await connection.fetchval("SELECT count(*) FROM public.wallet_ledger l JOIN public.wallet_reservations r ON r.id=l.reservation_id WHERE r.shipment_id=$1 AND l.entry_type='CAPTURE'",failed_id)==0
            report['checks'].append('PASS: definitive provider rejection releases reservation, captures nothing, keeps wallet funds and persists private diagnostics; no false booking')
            body3,cart3=await card_order('ROLLBACK-CARD-REJECTED')
            before=await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)
            sessions['cs_test_'+str(body3.request_id)]['payment_status']='paid'
            await connection.execute("UPDATE public.payment_carts SET updated_at=now()-interval '30 seconds' WHERE id=$1",body3.request_id)
            rejected_cart=await complete_cart(service,context,body3.request_id)
            assert rejected_cart['status']=='REVIEW_REQUIRED'
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before+Decimal(cart3['amount'])
            assert await connection.fetchval('SELECT reserved_balance FROM public.wallets WHERE tenant_id=$1',tenant)==0
            assert (await complete_cart(service,context,body3.request_id))['replayed']
            report['checks'].append('PASS: verified card payment followed by rejected label retains exact card-funded wallet credit, releases reservations and does not retry the rejected purchase on replay')

            reject_purchase[0]=False
            from backend.automation_freight_engine import Order
            from backend.tracking_and_support import TrackingSupportService,TrackingSettings,TrackingKey,TrackingEvent
            from tests.test_multi_piece_flow import boxes
            group_order=Order(idempotency_key=uuid4(),order_reference='ROLLBACK-MULTI-BOX',origin=origin,destination=origin,multi_parcel_dimensions=boxes(),items=[{'description':'Steel component','quantity':1,'unit_value':'15','unit_weight_kg':'1','origin_country':'GB','sku':'QA-PART','package_index':2}])
            group_quote=await automation.process(context,group_order,'QUOTE_ONLY')
            assert group_quote['status']=='QUOTED',group_quote
            group_sid=UUID(group_quote['shipment_id'])
            before=await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)
            group_booking=await service.confirm(context,BookingRequest(tenant_id=tenant,offer_id=group_quote['rate']['offer_id']))
            assert group_booking['status']=='BOOKED',group_booking
            metadata=json.loads(await connection.fetchval('SELECT logistics_metadata FROM public.shipments WHERE id=$1',group_sid))
            labels=metadata['automation_label']['package_labels'];assert len(labels)==2
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==before-Decimal(group_quote['rate']['client_price_ex_tax'])
            assert await connection.fetchval("SELECT count(*) FROM public.wallet_ledger l JOIN public.wallet_reservations r ON r.id=l.reservation_id WHERE r.shipment_id=$1 AND l.entry_type='CAPTURE'",group_sid)==1
            assert await connection.fetchval('SELECT package_index FROM public.shipment_goods_items WHERE shipment_id=$1',group_sid)==2
            key=TrackingKey(tenant_id=tenant,carrier_account_id=aid,secret='synthetic-tracking-signature-32-bytes')
            tracker=TrackingSupportService(pool,TrackingSettings(_env_file=None,tracking_webhook_keys={}))
            from datetime import timedelta
            now=datetime.now(timezone.utc)
            for index,piece in enumerate(labels):
                event=TrackingEvent(event_id='group-'+str(index),tracking_number=piece['tracking_number'],status='DELIVERED',occurred_at=now-timedelta(minutes=index+1))
                result=await tracker.ingest('rollback-multi-piece',key,event,str(index)*64);assert result['applied']
                expected='IN_TRANSIT' if index==0 else 'DELIVERED'
                assert await connection.fetchval('SELECT status FROM public.shipments WHERE id=$1',group_sid)==expected
            from backend.ecommerce_sync import EcommerceService
            from backend.store_returns import sync_return_jobs
            from unittest.mock import AsyncMock,patch
            store_id=uuid4()
            await connection.execute("INSERT INTO public.ecommerce_stores(id,tenant_id,platform,display_name) VALUES($1,$2,'SHOPIFY','ROLLBACK Return Store')",store_id,tenant)
            await connection.execute("UPDATE public.shipments SET ecommerce_store_id=$2,store_order_id='123' WHERE id=$1",group_sid,store_id)
            await connection.execute("UPDATE public.shipments SET tracking_lifecycle_type='RETURN_SHIPMENT',return_of_shipment_id=$2,logistics_metadata=jsonb_set(jsonb_set(logistics_metadata,'{automation_order,is_return}','true'),'{automation_order,store_return_reference}',to_jsonb('gid://shopify/ReverseFulfillmentOrder/456'::text)) WHERE id=$1",sid,group_sid)
            ecommerce=EcommerceService(pool,client=client)
            tracking_number=await connection.fetchval('SELECT tracking_number FROM public.shipments WHERE id=$1',sid)
            assert await ecommerce.queue_confirmed_tracking(connection,tenant,sid,tracking_number,'DHL')=='123'
            job=await connection.fetchrow('SELECT * FROM public.ecommerce_tracking_outbox WHERE shipment_id=$1',sid)
            assert job['status']=='RECONCILIATION_REQUIRED' and job['tracking_lifecycle_type']=='RETURN_SHIPMENT' and job['store_return_reference'].endswith('/456')
            parent_status=await connection.fetchval('SELECT store_fulfillment_status FROM public.shipments WHERE id=$1',group_sid)
            config=SimpleNamespace(tenant_id=tenant,platform='SHOPIFY',live_delivery=True)
            with patch('backend.store_connections.resolve_connector',AsyncMock(return_value=config)),patch('backend.store_returns.ShopifyReturnTracking.deliver',AsyncMock(return_value={'return_tracking_attached':True,'original_fulfillment_changed':False})) as reverse_delivery:
                await sync_return_jobs(ecommerce);await sync_return_jobs(ecommerce)
                reverse_delivery.assert_awaited_once()
            assert await connection.fetchval('SELECT status FROM public.ecommerce_tracking_outbox WHERE shipment_id=$1',sid)=='DELIVERED'
            assert await connection.fetchval('SELECT store_fulfillment_status FROM public.shipments WHERE id=$1',group_sid)==parent_status
            report['checks'].append('PASS: return outbox derives original store without a duplicate store-order row, starts fenced from forward fulfillment, sends reverse tracking once and leaves original fulfillment status unchanged')
            from backend.admin_portal import PlatformOwner
            from backend.credential_rotation import replace_credentials,CredentialReplacement
            import time
            old_id=uuid4();new_id=uuid4()
            old_secret=Fernet(settings.credential_keys[key_id].get_secret_value().encode()).encrypt(json.dumps({'tenant_id':str(tenant),'account_id':str(old_id),'api_key':'synthetic-old-key'}).encode())
            await connection.execute('''INSERT INTO public.carrier_accounts(id,tenant_id,account_name,aggregator,api_base_url,environment,credentials_ciphertext,credential_key_id,is_active)
                VALUES($1,$2,'ROLLBACK Sealed Standalone','EASYPOST','https://api.easypost.com/v2','TEST',$3,$4,false)''',old_id,tenant,old_secret,key_id)
            rotation_request=SimpleNamespace(state=SimpleNamespace(platform_auth_claims={'amr':[{'method':'password','timestamp':time.time()}]}),app=SimpleNamespace(state=SimpleNamespace(settings=settings,finance=finance)))
            result=await replace_credentials(old_id,CredentialReplacement(request_id=new_id,new_api_key='synthetic-new-key',reason='Rollback-only rotation verification'),rotation_request,PlatformOwner(member))
            assert result['credential_write_locked'] and not result['is_active']
            replacement=await connection.fetchrow('SELECT credential_write_locked,credential_version,credentials_ciphertext,last_security_audit_at FROM public.carrier_accounts WHERE id=$1',new_id)
            assert replacement['credential_write_locked'] and replacement['credential_version']==2 and replacement['last_security_audit_at']
            envelope=json.loads(Fernet(settings.credential_keys[key_id].get_secret_value().encode()).decrypt(bytes(replacement['credentials_ciphertext'])))
            assert envelope['account_id']==str(new_id) and envelope['tenant_id']==str(tenant)
            assert not await connection.fetchval('SELECT is_active FROM public.carrier_accounts WHERE id=$1',old_id)
            report['checks'].append('PASS: fresh-admin replacement creates a new sealed, disabled connection with tenant/account-bound ciphertext and audit timestamp; historical connection retained')
            await connection.execute('SET CONSTRAINTS ALL IMMEDIATE')
            report['checks'].append('PASS: two differently sized boxes, allocated normalized goods, two confirmed labels, one exact wallet capture; first delivered box leaves shipment in transit; older event for second box completes delivery; all deferred SQL constraints pass')
        report['status']='PASS'
    finally:
        await outer.rollback();await connection.close();report['database_writes_rolled_back']=True
    path=Path('docs/card_checkout/database_probe.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(run())
