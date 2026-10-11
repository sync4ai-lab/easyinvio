"""Rollback-only sandbox SQL lifecycle test; all carrier responses controlled."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import httpx
from cryptography.fernet import Fernet
from fastapi import HTTPException

import main
from backend.automation_freight_engine import AutomationService
from backend.automation_three_partners import PartnerLifecycleService, BookingRequest, ReturnRequest, VoidRequest, build_router
from backend.platform_carriers import retire


async def run():
    settings=main.Settings()
    assert settings.database_environment=='SANDBOX' and settings.provider_environment=='TEST'
    connection=await asyncpg.connect(settings.database_url.get_secret_value(),timeout=15,
        ssl=main.database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    transaction=connection.transaction(isolation='repeatable_read');await transaction.start()
    checks=[];calls=[];remote={};report={'executed_at':datetime.now(timezone.utc).isoformat(),
        'database':'actual Supabase SANDBOX','provider_responses':'controlled MockTransport',
        'external_api_calls':0,'database_writes_rolled_back':False}
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield connection
    try:
        tenant=await connection.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-03' AND is_sandbox")
        member=await connection.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active",tenant)
        context=main.TenantContext(tenant,member,'OWNER','')
        pid=uuid4();key_id=sorted(settings.credential_keys)[0];secret='synthetic-disable-probe'
        cipher=Fernet(settings.credential_keys[key_id].get_secret_value().encode()).encrypt(json.dumps({'platform_id':str(pid),'api_key':secret}).encode())
        await connection.execute('''INSERT INTO public.platform_carrier_connections
            (id,account_name,aggregator,api_base_url,environment,credentials_ciphertext,credential_key_id,is_active,priority,timeout_seconds)
            VALUES($1,'ROLLBACK Disable Lifecycle','EASYPOST','https://api.easypost.com/v2','TEST',$2,$3,true,10,30)''',pid,cipher,key_id)
        account_id=await connection.fetchval('SELECT id FROM public.carrier_accounts WHERE tenant_id=$1 AND platform_connection_id=$2',tenant,pid)
        account=main.CarrierAccount(account_id,tenant,'EASYPOST','https://api.easypost.com/v2',None,30,secret,pid)
        class Repository:
            async def accounts(self,ctx,*,historical_account_id=None):
                if ctx.tenant_id!=tenant:return []
                row=await connection.fetchrow('SELECT is_active FROM public.carrier_accounts WHERE tenant_id=$1 AND id=$2',ctx.tenant_id,account_id)
                return [account] if row and (row['is_active'] or historical_account_id==account_id) else []
        def transport(req):
            calls.append((req.method,req.url.path))
            if req.method=='POST' and req.url.path=='/v2/shipments':
                payload=json.loads(req.content)['shipment'];sid='shp_'+uuid4().hex;rid='rate_'+uuid4().hex
                body={'id':sid,'mode':'test','rates':[{'id':rid,'carrier':'UPS','service':'Ground','currency':'USD','rate':'10.00'}]}
                remote[sid]=body;remote[sid]['return_quote']=payload.get('is_return',False)
                return httpx.Response(201,json=body)
            parts=req.url.path.split('/');sid=parts[3]
            body=remote[sid]
            if req.method=='POST' and parts[-1]=='buy':
                body.update(selected_rate={'id':body['rates'][0]['id']},tracking_code='TEST-'+sid,
                    postage_label={'label_pdf_url':'https://easypost-files.s3.amazonaws.com/synthetic.pdf'})
            if req.method=='POST' and parts[-1]=='refund':body['refund_status']='refunded'
            return httpx.Response(200,json=body)
        pool=Pool();finance=main.FinanceEngine(pool,settings,None)
        await connection.execute('UPDATE public.wallets SET balance=1000,reserved_balance=0 WHERE tenant_id=$1',tenant)
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            rating=main.RatingService(client,Repository(),settings,pool=pool)
            automation=AutomationService(pool,rating,finance,Repository(),main.RatingRequest,client,settings)
            service=PartnerLifecycleService(automation,client)
            origin={'name':'Warehouse','line1':'417 Montgomery Street','city':'San Francisco','state':'CA','postal_code':'94104','country_code':'US'}
            destination={'name':'Buyer','line1':'228 Park Ave S','city':'New York','state':'NY','postal_code':'10003','country_code':'US'}
            raw={'idempotency_key':str(uuid4()),'order_reference':'ROLLBACK-DISABLE','origin':origin,'destination':destination,
                'currency':'USD','cargo':{'cargo_type':'PARCEL','actual_weight_kg':'1.00','length_cm':'20','width_cm':'15','height_cm':'10'}}
            prepared=await automation.process(context,raw,'QUOTE_ONLY');assert prepared['status']=='QUOTED',prepared
            shipment_id=UUID(prepared['shipment_id']);body=BookingRequest(tenant_id=tenant,offer_id=prepared['rate']['offer_id'])
            stale=await automation.process(context,{**raw,'idempotency_key':str(uuid4()),'order_reference':'ROLLBACK-STALE-QUOTE'},'QUOTE_ONLY')
            assert stale['status']=='QUOTED'
            permit=await finance.reserve(context,shipment_id);await finance.mark_submitted(permit,verified_test_environment=True)
            sid=prepared['rate']['upstream_shipment_id'];remote[sid].update(selected_rate={'id':prepared['rate']['upstream_rate_id']},
                tracking_code='TEST-'+sid,postage_label={'label_pdf_url':'https://easypost-files.s3.amazonaws.com/synthetic.pdf'})
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(finance=finance,partner_lifecycle=service)))
            await retire(pid,request,context)
            row=await connection.fetchrow('SELECT * FROM public.platform_carrier_connections WHERE id=$1',pid)
            assert not row['is_active'] and row['retired_at'] is None and bytes(row['credentials_ciphertext'])==cipher
            assert await connection.fetchval('SELECT count(*) FROM public.carrier_accounts WHERE platform_connection_id=$1 AND is_active',pid)==0
            checks.append('PASS: Disable preserves encrypted credentials and atomically excludes every mirrored tenant account from outbound selection')
            count=len(calls)
            try:await rating.quote(context,main.RatingRequest(origin=origin,destination=destination,currency='USD',weights_kg=['1'],dimensions=[{'length_cm':'20','width_cm':'15','height_cm':'10'}]))
            except HTTPException as exc:assert exc.status_code==503
            else:raise AssertionError('Disabled connection supplied new outbound rates')
            assert len(calls)==count
            try:await service.confirm(context,BookingRequest(tenant_id=tenant,offer_id=stale['rate']['offer_id']))
            except HTTPException as exc:assert exc.status_code==409
            else:raise AssertionError('Unsubmitted stale offer bought after disable')
            assert len(calls)==count
            checks.append('PASS: fresh outbound quotes and unsubmitted stale offers cannot use the disabled provider')
            booked=await service.confirm(context,body);assert booked['status']=='BOOKED'
            assert not any(path.endswith('/buy') for _,path in calls)
            assert await connection.fetchval("SELECT count(*) FROM public.wallet_ledger l JOIN public.wallet_reservations r ON r.id=l.reservation_id AND r.tenant_id=l.tenant_id WHERE r.shipment_id=$1 AND l.entry_type='CAPTURE'",shipment_id)==1
            checks.append('PASS: already submitted purchase reconciles and settles once after disable, without another buy request')
            return_endpoint=next(route.endpoint for route in build_router(lambda:None).routes if route.path.endswith('/prepare-return'))
            returned=await return_endpoint(ReturnRequest(tenant_id=tenant,shipment_id=shipment_id,idempotency_key=uuid4()),request,context)
            assert returned['status']=='QUOTED';assert remote[returned['rate']['upstream_shipment_id']]['return_quote']
            return_booked=await service.confirm(context,BookingRequest(tenant_id=tenant,offer_id=returned['rate']['offer_id']))
            assert return_booked['status']=='BOOKED'
            checks.append('PASS: authenticated original shipment obtains a fresh return quote and books a return through the disabled connection')
            balance=await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)
            original_amount=await connection.fetchval('SELECT amount FROM public.wallet_reservations WHERE tenant_id=$1 AND shipment_id=$2',tenant,shipment_id)
            assert (await service.void(context,VoidRequest(tenant_id=tenant,shipment_id=shipment_id)))['status']=='CANCELLED'
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==balance+original_amount
            await service.void(context,VoidRequest(tenant_id=tenant,shipment_id=shipment_id))
            assert await connection.fetchval('SELECT balance FROM public.wallets WHERE tenant_id=$1',tenant)==balance+original_amount
            checks.append('PASS: confirmed refund after disable credits the original captured amount exactly once')
        report.update(status='PASS',checks=checks)
    finally:
        await transaction.rollback();await connection.close();report['database_writes_rolled_back']=True
    output=Path('docs/connector_management/database_probe.json');output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':asyncio.run(run())
