"""Actual sandbox SQL with controlled native HTTP/signatures; no external sends."""
import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException
from starlette.datastructures import Headers, QueryParams

import main
from backend.automation_freight_engine import AutomationService
from backend.automation_three_partners import NativePartnerService, native_order_key
from backend.support_workflow import add_internal_note
from backend.tracking_and_support import TrackingSettings, TrackingSupportService, load_tracking_settings


async def run():
    settings=main.Settings()
    assert settings.database_environment=='SANDBOX' and settings.provider_environment=='TEST'
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),timeout=15,
        ssl=main.database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    transaction=connection.transaction(isolation='repeatable_read');await transaction.start()
    report={'executed_at':datetime.now(timezone.utc).isoformat(),'database':'actual Supabase SANDBOX',
        'native_http':'controlled MockTransport contracts','external_api_calls':0,'messages_sent':0,
        'database_writes_rolled_back':False,'checks':[]}
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield connection
    try:
        tenant=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-03' AND is_sandbox")
        user=await connection.fetchval("SELECT id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active",tenant)
        store=await connection.fetchval("SELECT id FROM public.ecommerce_stores WHERE tenant_id=$1 AND platform='SHOPIFY' LIMIT 1",tenant)
        actor=await connection.fetchval('SELECT auth_user_id FROM public.users WHERE id=$1',user)
        assert tenant and user and store and actor
        key_id=sorted(settings.credential_keys)[0];fernet=Fernet(settings.credential_keys[key_id].get_secret_value().encode())
        secret='synthetic-native-webhook-secret-32bytes'
        orders={};tests=[];calls=[]
        def transport(req):
            calls.append((req.method,req.url.host,req.url.path))
            if req.url.host=='api.easypost.com':
                remote_id=req.url.path.rsplit('/',1)[-1]
                tracked=next((value[3] for value in tests if value[4]==remote_id),None)
                return httpx.Response(200,json={'id':remote_id,'mode':'test','tracking_code':tracked,'postage_label':{'label_url':'https://pod.example.invalid/test.pdf'} if tracked else None})
            if req.method=='POST' and req.url.host=='api.goshippo.com':
                payload=json.loads(req.content);orders['sp1']=payload
                return httpx.Response(201,json={'object_id':'sp1','order_number':payload['order_number']})
            if req.method=='POST':
                payload=json.loads(req.content)[0];orders['77']=payload
                return httpx.Response(201,json={'data':[{'id':77,'order_id':payload['order_id']}]})
            if req.url.host=='api.goshippo.com':
                return httpx.Response(200,json={'object_id':'sp1','order_number':orders['sp1']['order_number'],
                    'order_status':'SHIPPED','transactions':['tx_synthetic']})
            return httpx.Response(200,json={'data':{'id':77,'order_id':orders['77']['order_id']}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            pool=Pool();tracking=TrackingSupportService(pool,load_tracking_settings())
            automation=AutomationService(pool,None,None,None,main.RatingRequest,client,settings)
            service=NativePartnerService(automation,client,tracking)
            for provider,endpoint,credential in [('EASYPOST','https://api.easypost.com/v2','synthetic'),
                ('SENDCLOUD','https://panel.sendcloud.sc/api/v3','{"public_key":"synthetic","secret_key":"synthetic"}'),
                ('SHIPPO','https://api.goshippo.com','shippo_test_synthetic')]:
                pid=uuid4();sid=uuid4();tracking_number='NATIVE-QA-'+str(sid)
                cipher=fernet.encrypt(json.dumps({'platform_id':str(pid),'api_key':credential}).encode())
                await connection.execute('''INSERT INTO public.platform_carrier_connections
                    (id,account_name,aggregator,regional_provider_code,api_base_url,environment,credentials_ciphertext,credential_key_id,is_active,priority,timeout_seconds)
                    VALUES($1,$2,$3,$4,$5,'TEST',$6,$7,true,10,30)''',pid,'ROLLBACK '+provider,
                    'EASYPOST' if provider=='EASYPOST' else 'REGIONAL',None if provider=='EASYPOST' else provider,endpoint,cipher,key_id)
                aid=await connection.fetchval('SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND platform_connection_id=$2',tenant,pid)
                assert aid
                await connection.execute('''INSERT INTO public.partner_provider_options
                    (platform_connection_id,order_sync_enabled,sendcloud_integration_id,webhook_enabled,webhook_secret,
                     credential_key_id,pod_allowed_hosts,sendcloud_status_map)
                    VALUES($1,true,7,true,$2,$3,'["pod.example.invalid"]','{"1":"IN_TRANSIT","2":"EXCEPTION","3":"DELIVERED"}')''',pid,fernet.encrypt(secret.encode()),key_id)
                address={'name':'Synthetic QA','line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
                order={'idempotency_key':str(uuid4()),'order_reference':'ROLLBACK-NATIVE-'+provider,
                    'origin':address,'destination':address,'currency':'USD','cargo':{'cargo_type':'PARCEL','actual_weight_kg':'1.000',
                    'length_cm':'20','width_cm':'15','height_cm':'10'},'items':[],'platform':'SHOPIFY','store_id':str(store),'store_order_id':str(sid)}
                data=await connection.fetchval("SELECT to_jsonb(s) FROM public.shipments s WHERE customer_reference='SEED24-3-2'")
                data=json.loads(data) if isinstance(data,str) else data
                upstream='shp_'+sid.hex if provider=='EASYPOST' else 'quote_'+sid.hex
                data.update(id=str(sid),tenant_id=str(tenant),created_by_user_id=str(user),carrier_account_id=str(aid),
                    idempotency_key=order['idempotency_key'],ecommerce_store_id=str(store),store_order_id=str(sid),
                    customer_reference=order['order_reference'],status='QUOTED',tracking_number=tracking_number,upstream_shipment_id=upstream,
                    pricing_snapshot={'markup_type':'MANUAL','markup_value':'0','currency':'USD'},
                    logistics_metadata={'fixture_batch':'three-partner-rollback-probe','automation_order':order,'automation_customs':{'required':False}})
                columns=await connection.fetchval("SELECT string_agg(quote_ident(attname),',' ORDER BY attnum) FROM pg_attribute WHERE attrelid='public.shipments'::regclass AND attnum>0 AND NOT attisdropped AND attgenerated=''")
                await connection.execute(f'INSERT INTO public.shipments({columns}) SELECT {columns} FROM jsonb_populate_record(NULL::public.shipments,$1)',json.dumps(data))
                assert await connection.fetchval('SELECT state FROM public.partner_order_jobs WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3',tenant,sid,aid)=='PENDING'
                assert (await service.sync_one(tenant,sid,aid))['state']=='SYNCED'
                before=len(calls);assert (await service.sync_one(tenant,sid,aid))['state']=='SYNCED';assert len(calls)==before
                report['checks'].append('PASS: '+provider+' automatic queue trigger, actual SQL send fence and duplicate sync protection with controlled native HTTP')
                remote_label=upstream if provider=='EASYPOST' else 'tx_synthetic' if provider=='SHIPPO' else 'shipment_synthetic'
                await connection.execute('''UPDATE public.shipments SET status='BOOKED',logistics_metadata=logistics_metadata||
                    jsonb_build_object('automation_label',$3::jsonb) WHERE tenant_id=$1 AND id=$2''',tenant,sid,
                    json.dumps({'upstream_id':remote_label,'tracking_number':tracking_number,'label_url':'https://pod.example.invalid/label.pdf'}))
                tests.append((provider,pid,sid,tracking_number,remote_label))
            await service.fulfillment_cycle()
            assert await connection.fetchval("SELECT count(*) FROM public.partner_order_jobs WHERE tenant_id=$1 AND shipment_id=ANY($2::uuid[]) AND fulfillment_state='CONFIRMED'",tenant,[value[2] for value in tests])==3
            report['checks'].append('PASS: native fulfillment confirmation/update for all three providers against actual SQL; controlled HTTP only')
            for provider,pid,sid,number,remote in tests:
                base=datetime.now(timezone.utc)-timedelta(seconds=10)
                def body_for(status,index):
                    moment=base+timedelta(seconds=index)
                    url='https://pod.example.invalid/'+str(sid)+'.jpg'
                    if provider=='EASYPOST':
                        result={'object':'Tracker','mode':'test','status':{'EXCEPTION':'failure','DELIVERED':'delivered','IN_TRANSIT':'in_transit'}[status],
                            'tracking_code':number,'shipment_id':remote,'updated_at':moment.isoformat(),'status_detail':'Customs postal code issue'}
                        if status=='DELIVERED':result['proof_of_delivery_url']=url
                        return {'description':'tracker.updated','id':'evt_'+sid.hex+'_'+str(index),'result':result}
                    if provider=='SENDCLOUD':
                        parcel={'tracking_number':number,'status':{'id':{'EXCEPTION':2,'DELIVERED':3,'IN_TRANSIT':1}[status],'message':'Customs postal code issue'}}
                        if status=='DELIVERED':parcel['proof_of_delivery_url']=url
                        return {'action':'parcel_status_changed','timestamp':int(moment.timestamp()),'parcel':parcel}
                    milestone={'status':{'EXCEPTION':'FAILURE','DELIVERED':'DELIVERED','IN_TRANSIT':'TRANSIT'}[status],
                        'status_date':moment.isoformat(),'status_details':'Customs postal code issue'}
                    if status=='DELIVERED':milestone['proof_of_delivery_url']=url
                    return {'event':'track_updated','test':True,'data':{'tracking_number':number,'transaction':remote,'tracking_status':milestone}}
                async def deliver(body,bad_signature=False):
                    raw=json.dumps(body,separators=(',',':')).encode()
                    if provider=='EASYPOST':header='x-hmac-signature';signature='hmac-sha256-hex='+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
                    elif provider=='SENDCLOUD':header='sendcloud-signature';signature=hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
                    else:
                        header='shippo-auth-signature';stamp=str(int(datetime.now(timezone.utc).timestamp()))
                        signature='t='+stamp+',v1='+hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
                    class Request:
                        headers=Headers({'content-type':'application/json',header:'invalid' if bad_signature else signature})
                        query_params=QueryParams('source='+str(pid))
                        async def stream(self):yield raw
                    return await service.receive_tracking(Request())
                assert (await deliver(body_for('IN_TRANSIT',0)))['applied']
                event=body_for('EXCEPTION',1)
                assert (await deliver(event))['support_queued']
                assert (await deliver(event))['replayed']
                await tracking.stage_tickets()
                assert await connection.fetchval('SELECT count(*) FROM public.support_tickets WHERE tenant_id=$1 AND shipment_id=$2',tenant,sid)==1
                ticket=await connection.fetchval('SELECT id FROM public.support_tickets WHERE tenant_id=$1 AND shipment_id=$2',tenant,sid)
                await connection.execute("UPDATE public.support_tickets SET manual_note='Earlier synthetic note' WHERE id=$1",ticket)
                before=await connection.fetchval('SELECT count(*) FROM public.support_message_outbox WHERE tenant_id=$1 AND ticket_id=$2',tenant,ticket)
                note=await add_internal_note(pool,ticket,actor,'Synthetic internal investigation',tenant_id=tenant,start_review=False)
                assert note['status']=='OPEN' and not note['merchant_notified']
                review=await add_internal_note(pool,ticket,actor,'Synthetic assigned review',tenant_id=tenant,start_review=True)
                assert review['status']=='IN_REVIEW'
                assert await connection.fetchval('SELECT reviewed_by_auth_user_id FROM public.support_tickets WHERE id=$1',ticket)==actor
                assert await connection.fetchval('SELECT count(*) FROM public.support_ticket_activity WHERE tenant_id=$1 AND ticket_id=$2',tenant,ticket)==3
                assert await connection.fetchval('SELECT count(*) FROM public.support_message_outbox WHERE tenant_id=$1 AND ticket_id=$2',tenant,ticket)==before
                try:await add_internal_note(pool,ticket,actor,'Wrong workspace',tenant_id=uuid4())
                except HTTPException as exc:assert exc.status_code==404
                else:raise AssertionError('Foreign note was accepted')
                delivery=body_for('DELIVERED',2)
                target=delivery['result'] if provider=='EASYPOST' else delivery['parcel'] if provider=='SENDCLOUD' else delivery['data']['tracking_status']
                target.pop('proof_of_delivery_url')
                assert (await deliver(delivery))['applied']
                assert await connection.fetchval('SELECT proof_of_delivery_url FROM public.shipments WHERE id=$1',sid) is None
                late=body_for('DELIVERED',2)
                if provider=='EASYPOST':late['id']+='-pod'
                assert (await deliver(late))['applied']
                assert await connection.fetchval('SELECT status FROM public.support_tickets WHERE id=$1',ticket)=='CLOSED'
                assert await connection.fetchval('SELECT count(*) FROM public.support_ticket_activity WHERE ticket_id=$1',ticket)==3
                row=await connection.fetchrow('SELECT status,proof_of_delivery_url FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant,sid)
                assert row['status']=='DELIVERED' and row['proof_of_delivery_url'].endswith('.jpg')
                assert not (await deliver(body_for('IN_TRANSIT',-1)))['applied']
                try:await deliver(event,bad_signature=True)
                except HTTPException as exc:assert exc.status_code==401
                else:raise AssertionError('Forged native signature accepted')
                report['checks'].append('PASS: '+provider+' signed native exception, duplicate event, one support ticket, approved POD mapping, terminal/stale protection and forged-signature rejection against actual SQL')
            report['checks'].append('PASS: all three signed IN_TRANSIT ? EXCEPTION ? internal note ? assigned review ? DELIVERED ? late POD; history retained, foreign note rejected and no note notification queued')
            report['status']='PASS'
    finally:
        await transaction.rollback();await connection.close();report['database_writes_rolled_back']=True
    output=Path('docs/support_workflow/database_probe.json');output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(run())
