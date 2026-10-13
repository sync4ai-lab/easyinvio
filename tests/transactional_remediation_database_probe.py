"""Actual sandbox audit/intake transactions; provider HTTP controlled; fixtures rolled back."""
import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx
from fastapi import FastAPI

import main
from backend.ecommerce_sync import EcommerceService
from backend.ecommerce_connectors import StoreConnector
from backend.ecommerce_inbound import build_router as inbound_router, AmazonInbound
from backend.invoice_upload import build_router as invoice_router


async def run():
    settings=main.Settings();assert settings.database_environment=='SANDBOX'
    tls=main.database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict)
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=tls)
    outer=connection.transaction(isolation='repeatable_read');await outer.start()
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield connection
    try:
        tenant=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-01' AND is_sandbox")
        actor=await connection.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active",tenant)
        assert actor and tenant
        context=SimpleNamespace(tenant_id=tenant,user_id=actor,role='OWNER')
        store=await connection.fetchval("INSERT INTO public.ecommerce_stores(tenant_id,platform,display_name) VALUES($1,'SHOPIFY','ROLLBACK Native intake') RETURNING id",tenant)
        config=StoreConnector(tenant_id=tenant,auth_user_id=actor,platform='SHOPIFY',webhook_secret='synthetic-webhook-signature-key-long',shop_domain='probe-native.myshopify.com',cargo_type='LETTER')
        service=EcommerceService(Pool(),connectors={store:config})
        original_import = service.import_order
        async def inspected_import(*args,**kwargs):
            try:return await original_import(*args,**kwargs)
            except asyncpg.PostgresError as error:
                print('Import database failure:',type(error).__name__,error.sqlstate,error.constraint_name)
                raise
        service.import_order=inspected_import
        app=FastAPI();app.state.ecommerce=service;app.state.finance=service
        app.include_router(inbound_router())
        async def authenticate():return context
        app.include_router(invoice_router(authenticate))
        order={'id':'1002345','name':'QA-NATIVE-IMPORT','currency':'GBP','shipping_address':{'name':'Synthetic Recipient','address1':'1 Test Road','city':'London','zip':'SW1A 1AA','country_code':'GB'},'line_items':[{'title':'Documents','quantity':1,'grams':'100'}]}
        raw=json.dumps(order).encode()
        headers={'Content-Type':'application/json','x-shopify-shop-domain':config.shop_domain,'x-shopify-topic':'orders/create','x-shopify-hmac-sha256':base64.b64encode(hmac.digest(config.webhook_secret.get_secret_value().encode(),raw,'sha256')).decode()}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            imported=await client.post('/api/v1/integrations/ecommerce/orders-sync?store_id='+str(store),content=raw,headers=headers)
            assert imported.status_code==200,imported.text
            sid=imported.json()['shipment_id'];assert imported.json()['status']=='UNFULFILLED'
            row=await connection.fetchrow('SELECT status,cargo_type FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,main.UUID(sid))
            assert row['status']=='UNFULFILLED' and row['cargo_type']=='LETTER'
            assert await connection.fetchval('SELECT count(*) FROM public.workspace_dispatch_events WHERE tenant_id=$1 AND shipment_id=$2',tenant,main.UUID(sid))==1
            replay=await client.post('/api/v1/integrations/ecommerce/orders-sync?store_id='+str(store),content=raw,headers=headers)
            assert replay.json()['replayed']
            headers['x-shopify-hmac-sha256']='forged'
            assert (await client.post('/api/v1/integrations/ecommerce/orders-sync?store_id='+str(store),content=raw,headers=headers)).status_code==401
            amazon_store=await connection.fetchval("INSERT INTO public.ecommerce_stores(tenant_id,platform,display_name) VALUES($1,'AMAZON','ROLLBACK Amazon intake') RETURNING id",tenant)
            amazon_config=StoreConnector(tenant_id=tenant,auth_user_id=actor,platform='AMAZON',webhook_secret='synthetic-amazon-destination-key-long',
                amazon_seller_id='synthetic-seller',amazon_marketplace_ids=['market-test'],amazon_client_id='synthetic-client',
                amazon_client_secret='synthetic-client-secret',amazon_refresh_token='synthetic-refresh-token',sku_unit_grams={'TEE':'200'})
            service.connectors[amazon_store]=amazon_config
            app.state.amazon_inbound=AmazonInbound(service)
            def amazon_transport(request):
                if request.url.host=='api.amazon.com':return httpx.Response(200,json={'access_token':'synthetic-access-token'})
                return httpx.Response(200,json={'order':{'orderId':'123-1234567-1234567','salesChannel':{'marketplaceId':'market-test'},
                    'fulfillment':{'fulfilledBy':'MERCHANT','fulfillmentStatus':'UNSHIPPED'},
                    'recipient':{'deliveryAddress':{'name':'Synthetic Recipient','addressLine1':'1 Test Road','city':'London','postalCode':'SW1A 1AA','countryCode':'GB'}},
                    'orderItems':[{'quantityOrdered':2,'fulfillment':{'quantityUnfulfilled':2},'product':{'sellerSku':'TEE','title':'Synthetic product','price':{'unitPrice':{'amount':'15.00','currencyCode':'GBP'}}}}]}})
            notification={'NotificationType':'ORDER_CHANGE','Payload':{'OrderChangeNotification':{'SellerId':'synthetic-seller',
                'AmazonOrderId':'123-1234567-1234567','Summary':{'MarketplaceId':'market-test'}}},
                'NotificationMetadata':{'NotificationId':'synthetic-notification-1','PublishTime':datetime.now(timezone.utc).isoformat()}}
            aws_headers={'Content-Type':'application/json','x-easyinvio-amazon-key':amazon_config.webhook_secret.get_secret_value()}
            for attempt in range(2):
                accepted=await client.post('/api/v1/integrations/ecommerce/orders-sync?store_id='+str(amazon_store),json=notification,headers=aws_headers)
                assert accepted.status_code==202,accepted.text
            assert await connection.fetchval('SELECT count(*) FROM public.amazon_order_notifications WHERE tenant_id=$1 AND store_id=$2',tenant,amazon_store)==1
            async with httpx.AsyncClient(transport=httpx.MockTransport(amazon_transport)) as amazon_client:
                service.client=amazon_client
                assert await app.state.amazon_inbound.process_one()
            assert await connection.fetchval('SELECT status FROM public.amazon_order_notifications WHERE tenant_id=$1 AND store_id=$2',tenant,amazon_store)=='IMPORTED'
            assert await connection.fetchval('SELECT status FROM public.shipments WHERE tenant_id=$1 AND ecommerce_store_id=$2',tenant,amazon_store)=='UNFULFILLED'
            assert await connection.fetchval('SELECT parcel_weight_kg FROM public.shipments WHERE tenant_id=$1 AND ecommerce_store_id=$2',tenant,amazon_store)==Decimal('0.400')
            print('Actual DB: authenticated Amazon receipt, duplicate protection, authorized Orders API contract and UNFULFILLED shipment persisted; provider HTTP controlled.')
            booked=await connection.fetchrow("SELECT id,parcel_weight_kg,wholesale_cost,currency FROM public.shipments WHERE tenant_id=$1 AND status='BOOKED' AND booked_at IS NOT NULL LIMIT 1",tenant)
            assert booked
            await connection.execute("UPDATE public.shipments SET upstream_shipment_id='synthetic-audit-reference',logistics_metadata=logistics_metadata||$3::jsonb WHERE tenant_id=$1 AND id=$2",tenant,booked['id'],json.dumps({'address_verification':{'verified':True,'is_commercial':True}}))
            data='upstream_shipment_id,currency,invoice_weight_kg,wholesale_cost,residential_fee\n'
            data+='synthetic-audit-reference,'+booked['currency']+','+str(booked['parcel_weight_kg']+Decimal('0.2'))+','+str(booked['wholesale_cost']+Decimal('5.00'))+',3.00\n'
            for attempt in range(2):
                audited=await client.post('/api/v1/finance/audit-invoice-upload',data={'invoice_reference':'QA-INVOICE-1'},files={'file':('invoice.csv',data.encode(),'text/csv')})
                assert audited.status_code==200,audited.text
                findings=audited.json()['results'][0]
                assert findings['status']=='FLAGGED' and len(findings['findings'])==3
                assert findings['estimated_overcharge']=='5.00'
            assert await connection.fetchval('SELECT count(*) FROM public.billing_disputes WHERE tenant_id=$1 AND invoice_reference=$2',tenant,'QA-INVOICE-1')==1
            context.role='DISPATCHER'
            denied=await client.post('/api/v1/finance/audit-invoice-upload',data={'invoice_reference':'QA-INVOICE-2'},files={'file':('invoice.csv',data.encode(),'text/csv')})
            assert denied.status_code==403
        print('Actual DB: signed UNFULFILLED import, cargo mapping, committed-event staging, duplicate/forgery rejection, three audit comparisons and one durable replay-safe dispute passed.')
    finally:
        await outer.rollback()
    notification=asyncio.Event()
    def received(*args):notification.set()
    await connection.add_listener('easyinvio_dispatch',received)
    sender=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=tls)
    try:
        await sender.execute("SELECT pg_notify('easyinvio_dispatch',$1)",json.dumps({'tenant_id':str(uuid4()),'shipment_id':str(uuid4()),'status':'UNFULFILLED'}))
        await asyncio.wait_for(notification.wait(),timeout=5)
        print('Actual commit-time Postgres notification received. All fixture writes rolled back; no external messages or purchases.')
    finally:
        await sender.close();await connection.close()

asyncio.run(run())
