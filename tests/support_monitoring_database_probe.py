"""Additive migration and real PostgreSQL Flow 2/3 verification.

Functional writes roll back; only migration 017 persists. Provider HTTP is
MockTransport: no real webhook subscription or merchant message is created.
"""
import asyncio
import hashlib
import hmac
import json
import re
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import uuid4

import asyncpg
import httpx
from fastapi import FastAPI
from pydantic import SecretStr
from twilio.request_validator import RequestValidator
from main import Settings,WhatsAppService
from backend.database_tls import database_tls_context
from backend.verify_automation_writepath import BorrowedPool
from backend.tracking_and_support import TrackingKey,TrackingSettings,TrackingSupportService,build_router as tracking_router
from backend.support_delivery import SupportDelivery,DeliverySettings,build_router as delivery_router
from backend.dashboard_portal import build_router as dashboard_router
from backend.admin_portal import authenticate_platform_owner


async def run():
    settings=Settings();assert settings.database_environment=='SANDBOX'
    c=await asyncpg.connect(settings.database_url.get_secret_value(),ssl=database_tls_context(settings.database_ca_file,strict=settings.database_tls_strict))
    evidence={}
    try:
        sql=Path('migrations/017_support_delivery_and_monitoring.sql').read_text()
        sql=re.sub(r'^(BEGIN;|COMMIT;)\s*$','',sql,flags=re.M)
        tx=c.transaction();await tx.start()
        try:await c.execute(sql)
        finally:await tx.rollback()
        async with c.transaction():await c.execute(sql)
        evidence['migration_017_rollback_validated_and_applied']=True
        indexes=['support_message_provider_sid','support_message_ready','platform_booked_reporting','platform_payment_reporting','platform_active_support']
        assert await c.fetchval("SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND indexname=ANY($1::text[])",indexes)==5
        evidence['five_delivery_and_reporting_indexes_present']=True
        tx=c.transaction(isolation='repeatable_read');await tx.start()
        try:
            row=await c.fetchrow("SELECT id,tenant_id,carrier_account_id,tracking_number FROM public.shipments WHERE customer_reference='SEED24-1-3'")
            assert row
            tenant=row['tenant_id'];owner=await c.fetchval("SELECT id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active",tenant)
            phone='+447700900'+str(uuid4().int%1000).zfill(3)
            assert not await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.whatsapp_bindings WHERE sender_e164=$1 AND receiver_e164=$2 AND is_active)',phone,'+14155238886')
            await c.execute('INSERT INTO public.whatsapp_bindings(tenant_id,user_id,sender_e164,receiver_e164,verified_at,is_active,notification_opt_in) VALUES($1,$2,$3,$4,now(),true,true)',tenant,owner,phone,'+14155238886')
            principal=await c.fetchval('SELECT auth_user_id FROM public.users WHERE id=$1',owner)
            try:
                async with c.transaction():
                    await c.execute("SELECT set_config('request.jwt.claims',$1,true)",json.dumps({'sub':str(principal),'role':'authenticated','tenant_id':str(tenant)}))
                    await c.execute('SET LOCAL ROLE authenticated')
                    await c.execute('UPDATE public.whatsapp_bindings SET notification_opt_in=false WHERE sender_e164=$1',phone)
                    raise AssertionError('Browser notification identity/consent writes were accepted')
            except asyncpg.InsufficientPrivilegeError:pass
            evidence['browser_notification_writes_blocked']=True
            pool=BorrowedPool(c)
            key=TrackingKey(tenant_id=tenant,carrier_account_id=row['carrier_account_id'],secret='controlled-webhook-secret-'+'x'*32,easypost_mode='test')
            tracking=TrackingSupportService(pool,TrackingSettings(_env_file=None,tracking_webhook_keys={'probe':key}))
            sid='SM'+uuid4().hex;requests=[]
            def transport(request):
                requests.append(request)
                return httpx.Response(201,json={'sid':sid,'status':'queued'})
            fake=SimpleNamespace(twilio_enabled=True,twilio_account_sid='AC'+'1'*32,twilio_auth_token=SecretStr('controlled-token'),twilio_whatsapp_number='+14155238886',twilio_whatsapp_sandbox_enabled=True)
            config=DeliverySettings(_env_file=None,support_whatsapp_enabled=True,support_whatsapp_content_sid='HX'+'2'*32,support_whatsapp_status_url='https://test.example.com/api/v1/support/whatsapp/status')
            async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as provider:
                delivery=SupportDelivery(pool,provider,fake,config)
                app=FastAPI();app.state.tracking_support=tracking;app.state.support_delivery=delivery;app.state.finance=SimpleNamespace(pool=pool)
                app.include_router(tracking_router(lambda:None));app.include_router(delivery_router(lambda:None));app.include_router(dashboard_router(lambda:None))
                app.dependency_overrides[authenticate_platform_owner]=lambda:SimpleNamespace(user_id=uuid4())
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
                    now=datetime.now(timezone.utc);eid='evt_'+uuid4().hex
                    event={'id':eid,'description':'tracker.updated','result':{'object':'Tracker','mode':'test','status':'failure','updated_at':now.isoformat(),'tracking_code':row['tracking_number'],
                        'tracking_details':[{'datetime':now.isoformat(),'message':'Held in New York customs: incorrect postal code layout'}]}}
                    raw=json.dumps(event).encode();signature='hmac-sha256-hex='+hmac.new(key.secret.get_secret_value().encode(),raw,hashlib.sha256).hexdigest()
                    headers={'content-type':'application/json','x-hmac-signature':signature}
                    result=await client.post('/api/v1/tracking/webhook?integration_key=probe',content=raw,headers=headers)
                    assert result.status_code==200 and result.json()['support_queued'],result.text
                    replay=await client.post('/api/v1/tracking/webhook?integration_key=probe',content=raw,headers=headers)
                    assert replay.json()['replayed']
                    await tracking.stage_tickets();await tracking.stage_tickets()
                    ticket=await c.fetchrow('''SELECT t.id,t.status,t.ai_summary FROM public.support_tickets t JOIN public.tracking_events e
                        ON e.tenant_id=t.tenant_id AND e.id=t.tracking_event_id WHERE e.event_id=$1''',eid)
                    assert ticket['status']=='OPEN' and 'postal-code' in ticket['ai_summary']
                    message=await c.fetchrow('SELECT id,status,body FROM public.support_message_outbox WHERE tenant_id=$1 AND ticket_id=$2',tenant,ticket['id'])
                    assert message['status']=='STAGED' and row['tracking_number'] in message['body']
                    session_config=DeliverySettings(_env_file=None,support_whatsapp_enabled=True,support_whatsapp_status_url=config.support_whatsapp_status_url)
                    session_delivery=SupportDelivery(pool,provider,fake,session_config)
                    assert await session_delivery.drain()==0 and not requests
                    inbound=WhatsAppService(pool,fake,None)
                    context=SimpleNamespace(tenant_id=tenant,user_id=principal,role='OWNER')
                    inbound_sid='SM'+uuid4().hex
                    await inbound.process(context,inbound_sid,'hello',phone)
                    await c.execute("UPDATE public.whatsapp_bindings SET last_inbound_at=now()-interval '20 hours' WHERE sender_e164=$1",phone)
                    before=await c.fetchval('SELECT last_inbound_at FROM public.whatsapp_bindings WHERE sender_e164=$1',phone)
                    await inbound.process(context,inbound_sid,'hello',phone)
                    assert await c.fetchval('SELECT last_inbound_at FROM public.whatsapp_bindings WHERE sender_e164=$1',phone)==before
                    assert await session_delivery.drain()==1
                    assert b'Body=' in requests[0].content and b'ContentSid=' not in requests[0].content
                    evidence['verified_inbound_window_and_replay_guard']=True
                    assert await c.fetchval('SELECT status FROM public.support_message_outbox WHERE id=$1',message['id'])=='ACCEPTED'
                    assert await delivery.drain()==0 and len(requests)==1
                    evidence['native_exception_replay_ticket_remedy_controlled_acceptance']=True
                    params={'AccountSid':fake.twilio_account_sid,'MessageSid':sid,'MessageStatus':'delivered','To':'whatsapp:'+phone}
                    callback=config.support_whatsapp_status_url+'/'+str(message['id'])
                    signed=RequestValidator('controlled-token').compute_signature(callback,params)
                    result=await client.post('/api/v1/support/whatsapp/status/'+str(message['id']),content=urlencode(params),headers={'content-type':'application/x-www-form-urlencoded','x-twilio-signature':signed})
                    assert result.status_code==200,result.text
                    assert await c.fetchval('SELECT status FROM public.support_message_outbox WHERE id=$1',message['id'])=='DELIVERED'
                    evidence['signed_controlled_delivery_receipt']=True
                    start=(now-timedelta(days=60)).date();end=now.date()
                    report=await client.get(f'/api/v1/admin/analytics/dashboard?start_date={start}&end_date={end}&environment=SANDBOX')
                    assert report.status_code==200,report.text
                    data=report.json();assert data['active_tenants']>0 and data['billing_pipeline'] and data['active_support']
                    expected=await c.fetch('''SELECT currency,sum(final_client_price) AS revenue,sum(profit_markup) AS margin FROM public.shipments s
                        JOIN public.tenants t ON t.tenant_id=s.tenant_id WHERE t.is_sandbox AND booked_at>=$1 AND booked_at<$2
                         AND status IN ('BOOKED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED') GROUP BY currency''',datetime.combine(start,datetime.min.time(),timezone.utc),datetime.combine(end+timedelta(days=1),datetime.min.time(),timezone.utc))
                    actual={r['currency']:r for r in data['totals_by_currency']}
                    for r in expected:assert Decimal(actual[r['currency']]['revenue'])==r['revenue'] and Decimal(actual[r['currency']]['margin'])==r['margin']
                    assert sum(r['volume'] for r in data['carriers'])==sum(r['package_count'] for r in data['totals_by_currency'])
                    threads=await client.get('/api/v1/admin/support/tickets?environment=SANDBOX&active_only=true')
                    found=next(t for t in threads.json()['tickets'] if t['id']==str(ticket['id']))
                    assert found['company_name'] and found['notifications'][0]['status']=='DELIVERED'
                    evidence['macro_currency_reconciliation_billing_carriers_threads']=True
                    event['id']='evt_'+uuid4().hex;event['result']['status']='delivered';event['result']['updated_at']=(now+timedelta(seconds=1)).isoformat()
                    raw=json.dumps(event).encode();headers['x-hmac-signature']='hmac-sha256-hex='+hmac.new(key.secret.get_secret_value().encode(),raw,hashlib.sha256).hexdigest()
                    done=await client.post('/api/v1/tracking/webhook?integration_key=probe',content=raw,headers=headers);assert done.status_code==200
                    assert await c.fetchval('SELECT status FROM public.support_tickets WHERE id=$1',ticket['id'])=='CLOSED'
                    active=await client.get('/api/v1/admin/support/tickets?environment=SANDBOX&active_only=true')
                    assert not any(t['id']==str(ticket['id']) for t in active.json()['tickets'])
                    archived=await client.get('/api/v1/admin/support/tickets?environment=SANDBOX&active_only=false')
                    assert any(t['id']==str(ticket['id']) and t['status']=='CLOSED' for t in archived.json()['tickets'])
                    evidence['delivered_closes_support_thread']=True
        finally:await tx.rollback()
        assert not await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.tracking_events WHERE event_id=$1)',eid)
        evidence.update(actual_supabase=True,functional_writes_rolled_back=True,real_whatsapp_messages=0,real_carrier_calls=0)
    finally:await c.close()
    Path('docs/support_monitoring').mkdir(parents=True,exist_ok=True)
    Path('docs/support_monitoring/database_evidence.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence))


if __name__=='__main__':asyncio.run(run())
