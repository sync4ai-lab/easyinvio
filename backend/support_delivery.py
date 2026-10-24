"""Opt-in WhatsApp notification delivery with a durable uncertain-send fence.

An accepted Twilio request is not proof of delivery. Only signed callbacks can
advance the delivery state. Uncertain requests are never blindly resent.
"""
import asyncio
import json
import logging
import re
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.datastructures import FormData
from twilio.request_validator import RequestValidator

logger=logging.getLogger('veloce.support_delivery')


class DeliverySettings(BaseSettings):
    model_config=SettingsConfigDict(env_file='.env',extra='ignore',hide_input_in_errors=True)
    support_whatsapp_enabled: bool=False
    support_whatsapp_content_sid: str=''
    # Full external HTTPS URL ending /api/v1/support/whatsapp/status (no slash).
    support_whatsapp_status_url: str=''

    @model_validator(mode='after')
    def configured(self):
        if self.support_whatsapp_enabled:
            parsed=urlsplit(self.support_whatsapp_status_url)
            if ((self.support_whatsapp_content_sid and not re.fullmatch(r'HX[0-9a-fA-F]{32}',self.support_whatsapp_content_sid))
                or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or not parsed.path.endswith('/api/v1/support/whatsapp/status')):
                raise ValueError('Outbound support needs a valid optional template SID and exact HTTPS callback base')
        return self


class Consent(BaseModel):
    notification_opt_in: bool=Field(strict=True)


class SupportDelivery:
    def __init__(self,pool,client,settings,delivery):
        self.pool,self.client,self.settings,self.delivery=pool,client,settings,delivery

    async def drain(self):
        if not self.delivery.support_whatsapp_enabled or not self.settings.twilio_enabled:
            return 0
        async with self.pool.acquire() as c:
            async with c.transaction():
                row=await c.fetchrow('''SELECT o.id,o.tenant_id,o.recipient_e164,o.body,o.attempts
                  FROM public.support_message_outbox o JOIN public.support_tickets t ON t.tenant_id=o.tenant_id AND t.id=o.ticket_id
                  WHERE o.status='STAGED' AND o.next_attempt_at<=now() AND o.attempts<5
                   AND ((t.status IN ('OPEN','IN_REVIEW') AND EXISTS(SELECT 1 FROM public.shipments s
                     WHERE s.tenant_id=t.tenant_id AND s.id=t.shipment_id AND s.status='EXCEPTION'))
                     OR (t.status='CLOSED' AND to_jsonb(t)->>'insurance_claim_id' IS NOT NULL
                      AND to_jsonb(o)->>'message_kind'='INSURANCE_SETTLEMENT'))
                   AND EXISTS(SELECT 1 FROM public.tenants account WHERE account.tenant_id=o.tenant_id
                      AND account.workspace_status='ACTIVE' AND account.is_sandbox=$2)
                   AND EXISTS(SELECT 1 FROM public.whatsapp_bindings b JOIN public.users u ON u.tenant_id=b.tenant_id AND u.id=b.user_id
                     WHERE b.tenant_id=o.tenant_id AND b.sender_e164=o.recipient_e164 AND b.is_active AND b.notification_opt_in
                     AND b.verified_at IS NOT NULL
                     AND NOT coalesce((to_jsonb(b)->>'alerts_paused')::boolean,false)
                      AND b.receiver_e164=$1
                      AND ($3::boolean OR b.last_inbound_at>now()-interval '23 hours 59 minutes')
                      AND u.is_active AND u.role IN ('OWNER','ADMIN'))
                  ORDER BY o.next_attempt_at,o.id LIMIT 1 FOR UPDATE OF o SKIP LOCKED''',self.settings.twilio_whatsapp_number,getattr(self.settings,'twilio_whatsapp_sandbox_enabled',False),bool(self.delivery.support_whatsapp_content_sid))
                if row is None:return 0
                await c.execute("UPDATE public.support_message_outbox SET status='RECONCILIATION_REQUIRED',attempts=attempts+1,last_error_code=NULL WHERE id=$1",row['id'])
        callback=self.delivery.support_whatsapp_status_url+'/'+str(row['id'])
        payload={'From':'whatsapp:'+self.settings.twilio_whatsapp_number,'To':'whatsapp:'+row['recipient_e164'],'StatusCallback':callback}
        if self.delivery.support_whatsapp_content_sid:
            payload.update(ContentSid=self.delivery.support_whatsapp_content_sid,ContentVariables=json.dumps({'1':row['body']}))
        else:
            # The locked claim required verified inbound proof within the service window.
            payload['Body']=row['body']
        try:
            response=await self.client.post(f'https://api.twilio.com/2010-04-01/Accounts/{self.settings.twilio_account_sid}/Messages.json',
                auth=httpx.BasicAuth(self.settings.twilio_account_sid,self.settings.twilio_auth_token.get_secret_value()),
                data=payload,timeout=20,follow_redirects=False)
        except httpx.HTTPError:
            return 1  # Unknown outcome: durable fence remains for manual reconciliation.
        async with self.pool.acquire() as c:
            if response.status_code==429:
                state='STAGED' if row['attempts']+1<5 else 'FAILED'
                delay=min(300,2**(row['attempts']+1))
                await c.execute("UPDATE public.support_message_outbox SET status=$2,next_attempt_at=now()+$3::integer*interval '1 second',last_error_code='TWILIO_RATE_LIMIT' WHERE id=$1 AND status='RECONCILIATION_REQUIRED' AND provider_message_sid IS NULL",row['id'],state,delay)
            elif response.status_code in {400,401,403,404,422}:
                await c.execute("UPDATE public.support_message_outbox SET status='FAILED',last_error_code='TWILIO_REJECTED' WHERE id=$1 AND status='RECONCILIATION_REQUIRED' AND provider_message_sid IS NULL",row['id'])
            elif response.status_code==201:
                try:sid=response.json()['sid']
                except (ValueError,KeyError,TypeError):return 1
                if not isinstance(sid,str) or not re.fullmatch(r'SM[0-9a-fA-F]{32}',sid):return 1
                await c.execute("UPDATE public.support_message_outbox SET status='ACCEPTED',provider_message_sid=$2,delivery_updated_at=now() WHERE id=$1 AND status='RECONCILIATION_REQUIRED' AND (provider_message_sid IS NULL OR provider_message_sid=$2)",row['id'],sid)
        return 1

    async def worker(self):
        while True:
            try:
                if await self.drain():continue
            except (asyncpg.PostgresError,ValueError,TypeError):
                logger.warning('Optional support delivery deferred; durable state retained')
            await asyncio.sleep(2)

    async def callback(self,request,message_id):
        if not self.delivery.support_whatsapp_enabled or not self.settings.twilio_enabled:
            raise HTTPException(503,'Support messaging is disabled')
        if request.url.query or request.headers.get('content-type','').split(';')[0].lower()!='application/x-www-form-urlencoded':
            raise HTTPException(400,'Invalid callback structure')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>32768:raise HTTPException(413,'Callback too large')
        try:
            if re.search(rb'%(?![0-9A-Fa-f]{2})',raw):raise ValueError()
            form=FormData(parse_qsl(raw.decode('utf-8'),keep_blank_values=True,errors='strict',max_num_fields=100))
        except (ValueError,UnicodeError):raise HTTPException(400,'Invalid callback encoding') from None
        external=self.delivery.support_whatsapp_status_url+'/'+str(message_id)
        if (len(request.headers.getlist('x-twilio-signature'))!=1 or not RequestValidator(self.settings.twilio_auth_token.get_secret_value()).validate(external,form,request.headers['x-twilio-signature'])):
            raise HTTPException(403,'Invalid Twilio callback signature')
        for key in ('AccountSid','MessageSid','MessageStatus','To'):
            if len(form.getlist(key))!=1:raise HTTPException(400,'Invalid callback fields')
        if form['AccountSid']!=self.settings.twilio_account_sid or not re.fullmatch(r'SM[0-9a-fA-F]{32}',form['MessageSid']):
            raise HTTPException(403,'Unexpected messaging identity')
        mapped={'queued':'ACCEPTED','accepted':'ACCEPTED','sending':'ACCEPTED','sent':'SENT','delivered':'DELIVERED','read':'READ','failed':'FAILED','undelivered':'FAILED'}
        state=mapped.get(form['MessageStatus'])
        if state is None:raise HTTPException(422,'Unknown delivery state')
        rank={'RECONCILIATION_REQUIRED':0,'ACCEPTED':1,'SENT':2,'FAILED':3,'DELIVERED':4,'READ':5}
        async with self.pool.acquire() as c:
            async with c.transaction():
                row=await c.fetchrow('SELECT status,recipient_e164,provider_message_sid,attempts FROM public.support_message_outbox WHERE id=$1 FOR UPDATE',message_id)
                if (not row or row['attempts']<1 or form['To']!='whatsapp:'+row['recipient_e164']
                    or row['provider_message_sid'] not in (None,form['MessageSid'])):
                    raise HTTPException(404,'Notification receipt not found')
                if rank.get(row['status'],99)<=rank[state]:
                    code=form.get('ErrorCode','')
                    error='TWILIO_'+code if state=='FAILED' and len(form.getlist('ErrorCode'))==1 and re.fullmatch(r'\d{1,8}',code) else None
                    await c.execute('UPDATE public.support_message_outbox SET status=$2,provider_message_sid=$3,delivery_updated_at=now(),last_error_code=$4 WHERE id=$1',message_id,state,form['MessageSid'],error)
        return {'accepted':True}


def build_router(authenticate):
    router=APIRouter(prefix='/api/v1/support/whatsapp',tags=['Support notification delivery'])
    @router.post('/status/{message_id}')
    async def status(message_id:UUID,request:Request):
        return await request.app.state.support_delivery.callback(request,message_id)
    @router.get('/consent')
    async def consent_status(request:Request,context=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN'}:raise HTTPException(403,'Merchant notification permission required')
        async with request.app.state.finance.pool.acquire() as c:
            rows=await c.fetch("""SELECT right(b.sender_e164,4) AS number_suffix,b.notification_opt_in
                FROM public.whatsapp_bindings b JOIN public.users u ON u.id=b.user_id AND u.tenant_id=b.tenant_id
                WHERE b.tenant_id=$1 AND u.auth_user_id=$2 AND u.is_active AND b.is_active AND b.verified_at IS NOT NULL
                ORDER BY b.id""",context.tenant_id,context.user_id)
        return {'eligible':bool(rows),'notification_opt_in':bool(rows) and all(r['notification_opt_in'] for r in rows),
            'bindings':[dict(r) for r in rows]}
    @router.post('/consent')
    async def consent(body:Consent,request:Request,context=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN'}:raise HTTPException(403,'Merchant notification permission required')
        async with request.app.state.finance.pool.acquire() as c:
            result=await c.execute('''UPDATE public.whatsapp_bindings b SET notification_opt_in=$3 FROM public.users u
                WHERE b.tenant_id=$1 AND b.user_id=u.id AND u.tenant_id=b.tenant_id AND u.auth_user_id=$2
                 AND u.is_active AND (NOT $3::boolean OR (b.is_active AND b.verified_at IS NOT NULL))''',context.tenant_id,context.user_id,body.notification_opt_in)
        if result=='UPDATE 0' and body.notification_opt_in:
            raise HTTPException(409,'No verified WhatsApp number is linked to your account. Ask EasyInvio support to complete number verification before opting in.')
        return {'notification_opt_in':body.notification_opt_in}
    return router
