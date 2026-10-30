# Gupshup Self-Service v2 ingress and encrypted queue compatibility boundary.
from __future__ import annotations
import asyncio,hashlib,json,re,copy
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode,parse_qsl
import asyncpg,httpx
from fastapi import APIRouter,HTTPException,Request,Response
from starlette.datastructures import FormData
from backend.whatsapp_provider import authenticate_gupshup_origin,account,number,provider,recipient_error,paused
from backend.whatsapp_queue import WhatsAppQueue,OutboundPart,inbound_digest,process_inbound
from backend.whatsapp_dispatch import send_selected,reconcile_events

def event_time(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)):raise ValueError('Missing event time')
    stamp=datetime.fromtimestamp(value/1000,timezone.utc)
    now=datetime.now(timezone.utc)
    if stamp>now+timedelta(minutes=5) or stamp<now-timedelta(days=8):raise ValueError('Event time outside acceptance horizon')
    return min(stamp,now)

def phone(value):
    if not isinstance(value,str) or not re.fullmatch(r'\+?[1-9][0-9]{7,14}',value):raise ValueError('Invalid phone')
    return '+'+value.lstrip('+')

def parse_event(data,settings):
    if not isinstance(data,dict) or data.get('app')!=settings.gupshup_app_name or data.get('version')!=2:
        raise ValueError('Wrong app or version')
    if data.get('phone') is not None and phone(data['phone'])!=number(settings):raise ValueError('Business source mismatch')
    received=event_time(data.get('timestamp'));payload=data.get('payload')
    if not isinstance(payload,dict):raise ValueError('Invalid event payload')
    kind=data.get('type')
    if kind=='message':
        external=payload.get('id')
        if not isinstance(external,str) or not re.fullmatch(r'[A-Za-z0-9_.:+/=-]{1,512}',external):raise ValueError('Invalid message ID')
        sender=phone(payload.get('source'))
        if payload.get('sender',{}).get('phone') and phone(payload['sender']['phone'])!=sender:raise ValueError('Sender mismatch')
        if payload.get('destination') and phone(payload['destination'])!=number(settings):raise ValueError('Receiver mismatch')
        media=payload.get('type')!='text'
        body=payload.get('payload',{}).get('text','') if not media else ''
        if not isinstance(body,str) or len(body)>1600:raise ValueError('Invalid text')
        internal='gs:'+hashlib.sha256((account(settings)+':'+external).encode()).hexdigest()
        form=FormData({'AccountSid':account(settings),'From':'whatsapp:'+sender,'To':'whatsapp:'+number(settings),
            'MessageSid':internal,'Body':body,'NumMedia':'1' if media else '0',
            'ProviderContentHash':hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
        return 'message',form,external,received
    if kind=='message-event':
        status={'enqueued':'ACCEPTED','sent':'SENT','delivered':'DELIVERED','read':'READ','failed':'FAILED'}.get(payload.get('type'))
        if status is None:raise ValueError('Unsupported delivery event')
        identifier=payload.get('id');gs=payload.get('gsId')
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_.:+/=-]{1,512}',identifier):raise ValueError('Invalid receipt ID')
        if gs is not None and (not isinstance(gs,str) or not re.fullmatch(r'[A-Za-z0-9_.:+/=-]{1,512}',gs)):raise ValueError('Invalid Gupshup ID')
        external=gs or (identifier if payload['type'] in {'enqueued','failed'} else None)
        wa=identifier if gs or payload['type'] in {'sent','delivered','read'} else payload.get('payload',{}).get('whatsappMessageId')
        if wa is not None and (not isinstance(wa,str) or not re.fullmatch(r'[A-Za-z0-9_.:+/=-]{1,512}',wa)):raise ValueError('Invalid WhatsApp ID')
        return 'receipt',{'external':external,'whatsapp':wa,'status':status,'recipient':phone(payload.get('destination'))},None,received
    if kind=='user-event' and payload.get('type')=='sandbox-start':return 'ignored',None,None,received
    # Opt-in events never create consent. Other event types are not user commands.
    if kind in {'user-event','system-event','template-event','account-event'}:return 'ignored',None,None,received
    raise ValueError('Unsupported event type')

class GupshupQueue(WhatsAppQueue):
    def __init__(self,pool,settings,application,client=None):
        # Avoid constructing a Twilio SDK client or requiring Twilio credentials.
        super().__init__(pool,settings,application,client=client or object())
        self.http=getattr(getattr(application.state,'rating',None),'client',None)
    async def enqueue_event(self,form,external,received):
        raw=urlencode(dict(form)).encode();digest=inbound_digest(raw)
        async with self.pool.acquire(timeout=.1) as c:
            async with c.transaction():
                await c.execute("SET LOCAL lock_timeout='80ms'")
                await c.execute("SET LOCAL statement_timeout='200ms'")
                row=await c.fetchrow('''INSERT INTO public.whatsapp_inbound_queue
                    (message_sid,sender_e164,receiver_e164,input_sha256,payload_ciphertext,key_id,provider,provider_account,external_message_id,provider_received_at)
                    VALUES($1,$2,$3,$4,$5,$6,'GUPSHUP',$7,$8,$9)
                    ON CONFLICT(message_sid) DO UPDATE SET message_sid=EXCLUDED.message_sid RETURNING input_sha256''',
                    form['MessageSid'],form['From'].removeprefix('whatsapp:'),number(self.settings),digest,self.encrypt(raw),self.key_id,account(self.settings),external,received)
                if row['input_sha256']!=digest:raise HTTPException(409,'Message identity reused with different business content')
    async def claim(self):
        async with self.pool.acquire() as c:
            async with c.transaction():
                row=await c.fetchrow('''SELECT q.* FROM public.whatsapp_inbound_queue q WHERE provider='GUPSHUP' AND provider_account=$1
                    AND q.state IN ('STAGED','READY') AND NOT EXISTS(SELECT 1 FROM public.whatsapp_inbound_queue earlier
                    WHERE earlier.provider=q.provider AND earlier.provider_account=q.provider_account
                    AND earlier.sender_e164=q.sender_e164 AND earlier.receiver_e164=q.receiver_e164 AND earlier.id<q.id
                    AND earlier.state NOT IN ('ACCEPTED','FAILED')) ORDER BY q.id FOR UPDATE OF q SKIP LOCKED LIMIT 1''',account(self.settings))
                if row:await c.execute("UPDATE public.whatsapp_inbound_queue SET state='PROCESSING',updated_at=now() WHERE id=$1",row['id'])
                return dict(row) if row else None
    async def dispatch(self,row):
        reason=recipient_error(self.settings,row['sender_e164'])
        if reason:
            await self.mark(row['id'],'READY',reason);return
        async with self.pool.acquire() as c:
            parts=await c.fetch('SELECT * FROM public.whatsapp_reply_outbox WHERE inbound_id=$1 ORDER BY part_index',row['id'])
        for part in parts:
            if part['state']=='ACCEPTED':continue
            if part['state']=='FAILED':
                async with self.pool.acquire() as c:
                    if await c.fetchval('SELECT id FROM public.whatsapp_reply_outbox WHERE fallback_for=$1',part['id']):continue
            if part['state']!='STAGED':
                await self.mark(row['id'],'REVIEW_REQUIRED','UNCERTAIN_SEND');return
            value=OutboundPart.model_validate_json(self.ciphers[part['key_id']].decrypt(bytes(part['payload_ciphertext'])))
            async with self.pool.acquire() as c:
                claimed=await c.fetchval("UPDATE public.whatsapp_reply_outbox SET state='SENDING',provider='GUPSHUP',provider_account=$2,updated_at=now() WHERE id=$1 AND state='STAGED' RETURNING id",part['id'],account(self.settings))
            if claimed is None:await self.mark(row['id'],'REVIEW_REQUIRED','SEND_STATE_CONFLICT');return
            async with self.pool.acquire() as c:
                tenants=await c.fetch('''SELECT b.tenant_id FROM public.whatsapp_bindings b JOIN public.users u ON u.tenant_id=b.tenant_id AND u.id=b.user_id
                    WHERE b.sender_e164=$1 AND b.receiver_e164=$2 AND b.is_active AND b.verified_at IS NOT NULL AND u.is_active LIMIT 2''',row['sender_e164'],row['receiver_e164'])
                tenant=tenants[0]['tenant_id'] if len(tenants)==1 else None
            try:
                r=await send_selected(self.settings,self.pool,self.http,{'To':'whatsapp:'+row['sender_e164'],'Body':value.body},
                    logical_key='chat:'+str(part['id']),kind='CHAT',target_id=part['id'],tenant_id=tenant,
                    media_url=value.media_url,received_at=row.get('provider_received_at') or row['created_at'])
            except Exception:
                await self.send_failure(row['id'],part['id'],False);return
            if r.status_code!=201:
                if value.media_url and value.fallback_view_url and r.status_code in {400,415,422}:
                    await self.schedule_fallback(row,part,value,definite_rejection=True);continue
                await self.send_failure(row['id'],part['id'],True);return
            async with self.pool.acquire() as c:
                await c.execute("UPDATE public.whatsapp_reply_outbox SET state='ACCEPTED',provider_message_sid=$2,updated_at=now() WHERE id=$1 AND state='SENDING'",part['id'],r.json()['sid'])
        async with self.pool.acquire() as c:
            pending=await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.whatsapp_reply_outbox WHERE inbound_id=$1 AND state='STAGED')",row['id'])
        await self.mark(row['id'],'READY' if pending else 'ACCEPTED')
    async def drain(self):
        await reconcile_events(self)
        if paused(self.settings):return False
        row=await self.claim()
        if row is None:return False
        try:
            reason=recipient_error(self.settings,row['sender_e164'])
            if reason:await self.mark(row['id'],'FAILED',reason);return True
            received=row.get('provider_received_at') or row['created_at']
            if received<datetime.now(timezone.utc)-timedelta(hours=23,minutes=59):await self.mark(row['id'],'FAILED','SERVICE_WINDOW_EXPIRED');return True
            raw=self.ciphers[row['key_id']].decrypt(bytes(row['payload_ciphertext']));form=FormData(parse_qsl(raw.decode(),keep_blank_values=True))
            if (inbound_digest(raw)!=row['input_sha256'] or form['AccountSid']!=account(self.settings) or form['MessageSid']!=row['message_sid']
                or form['From']!='whatsapp:'+row['sender_e164'] or form['To']!='whatsapp:'+number(self.settings) or row['receiver_e164']!=number(self.settings)):
                raise ValueError('Queued identity mismatch')
            if row['state']=='STAGED':
                request=Request({'type':'http','app':self.application,'method':'POST','path':'/internal/gupshup-worker','headers':[]})
                async with asyncio.timeout(180):parts=await process_inbound(request,form,received)
                await self.stage(row['id'],parts)
            await self.dispatch(row)
        except asyncio.CancelledError:raise
        except Exception:await self.mark(row['id'],'REVIEW_REQUIRED','PROCESSING_UNCONFIRMED')
        return True

def build_router():
    router=APIRouter(tags=['Gupshup self-service WhatsApp'])
    @router.post('/api/v1/integrations/whatsapp/gupshup/webhook')
    async def ingress(request:Request):
        selected=request.app.state.settings
        s=copy.copy(selected)
        s.whatsapp_provider='GUPSHUP'  # Original provider identity for late callbacks after rollback.
        authenticate_gupshup_origin(request,s)
        if request.url.query or request.headers.get('content-type','').split(';')[0]!='application/json':raise HTTPException(400,'Expected JSON callback without query')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>32768:raise HTTPException(413,'Callback exceeds 32 KB')
        try:
            def no_duplicates(pairs):
                value={}
                for key,item in pairs:
                    if key in value:raise ValueError('Repeated JSON key')
                    value[key]=item
                return value
            data=json.loads(raw,object_pairs_hook=no_duplicates)
            kind,value,external,received=parse_event(data,s)
        except (ValueError,KeyError,TypeError,AttributeError,OverflowError):raise HTTPException(422,'Invalid Gupshup event') from None
        q=getattr(request.app.state,'whatsapp_queue',None)
        if kind=='message' and provider(selected)!='GUPSHUP':raise HTTPException(503,'Gupshup commands are disabled for the selected provider')
        if not isinstance(q,GupshupQueue):
            if q is None:raise HTTPException(503,'Messaging queue unavailable for receipt storage')
            q=GupshupQueue(q.pool,s,request.app)
        try:
            async with asyncio.timeout(.7):
                if kind=='message':
                    reason=recipient_error(s,value['From'].removeprefix('whatsapp:'))
                    if reason:raise HTTPException(409,reason)
                    await q.enqueue_event(value,external,received)
                elif kind=='receipt':
                    digest=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
                    async with q.pool.acquire(timeout=.1) as c:
                        await c.execute('''INSERT INTO public.whatsapp_delivery_events(provider,provider_account,event_sha256,external_id,whatsapp_id,recipient_e164,status,occurred_at)
                            VALUES('GUPSHUP',$1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING''',account(s),digest,value['external'],value['whatsapp'],value['recipient'],value['status'],received)
        except (TimeoutError,asyncpg.PostgresError):raise HTTPException(503,'Callback storage busy; retry delivery') from None
        return Response(status_code=200)
    return router
