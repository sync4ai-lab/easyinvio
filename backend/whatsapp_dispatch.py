# Durable selected-provider dispatch for proactive messages and Gupshup chat.
from __future__ import annotations
from uuid import NAMESPACE_URL,uuid5
import httpx
from fastapi import HTTPException
from backend.whatsapp_provider import provider,account,number,recipient_error,template,TwilioAdapter,GupshupAdapter

def legacy_response(result):
    if result.outcome=='ACCEPTED':return httpx.Response(201,json={'sid':result.external_id})
    if result.outcome=='UNCERTAIN':raise httpx.ReadError('WhatsApp send outcome requires reconciliation')
    return httpx.Response(409 if result.outcome=='REJECTED' and result.http_status==429 else result.http_status or 409,json={'code':result.code})

async def send_selected(settings,pool,client,payload,*,logical_key,kind,target_id,tenant_id=None,parameters=None,received_at=None,media_url=None):
    destination=payload['To'].removeprefix('whatsapp:')
    reason=recipient_error(settings,destination)
    if reason:raise HTTPException(409,reason)
    selected=provider(settings)
    binding=template(settings,kind) if selected=='GUPSHUP' and kind!='CHAT' else None
    if selected=='GUPSHUP' and kind!='CHAT' and binding is None:raise HTTPException(409,'APPROVED_GUPSHUP_TEMPLATE_REQUIRED:'+kind)
    # Legacy test doubles do not represent migration 049; actual Settings always does.
    durable=hasattr(settings,'whatsapp_provider')
    attempt=uuid5(NAMESPACE_URL,selected+':'+account(settings)+':'+logical_key)
    if durable:
        async with pool.acquire() as c:
            row=await c.fetchrow('''INSERT INTO public.whatsapp_delivery_attempts
                (id,provider,provider_account,logical_key,tenant_id,kind,target_id,source_e164,recipient_e164,category,template_name,template_id,template_language,state)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'SENDING') ON CONFLICT(provider,provider_account,logical_key) DO NOTHING RETURNING id''',
                attempt,selected,account(settings),logical_key,tenant_id,kind,str(target_id),number(settings),destination,
                binding.category if binding else 'SERVICE' if kind=='CHAT' or 'ContentSid' not in payload else 'PROVIDER_APPROVAL_UNKNOWN',
                kind if binding else None,binding.provider_id if binding else payload.get('ContentSid'),binding.language if binding else None)
            if row is None:
                old=await c.fetchrow('SELECT state,external_id FROM public.whatsapp_delivery_attempts WHERE id=$1',attempt)
                if old and old['state']=='ACCEPTED' and old['external_id']:return httpx.Response(201,json={'sid':old['external_id']})
                raise HTTPException(409,'WHATSAPP_ATTEMPT_REQUIRES_RECONCILIATION')
    reason=recipient_error(settings,destination)
    if reason:raise HTTPException(409,reason)
    if selected=='GUPSHUP':
        result=await GupshupAdapter(settings,client).send(destination,payload.get('Body',''),binding=binding,
            parameters=parameters,media_url=media_url,received_at=received_at)
    else:result=await TwilioAdapter(settings,client).send(payload)
    if durable:
        state={'ACCEPTED':'ACCEPTED','REJECTED':'FAILED','RETRYABLE':'FAILED','UNCERTAIN':'REVIEW_REQUIRED'}[result.outcome]
        async with pool.acquire() as c:
            await c.execute('''UPDATE public.whatsapp_delivery_attempts SET state=$2,external_id=$3,error_code=$4,updated_at=now()
                WHERE id=$1 AND state='SENDING' ''',attempt,state,result.external_id,result.code)
    return legacy_response(result)

async def reconcile_events(queue):
    # Callbacks persist before matching, including events racing REST acceptance.
    async with queue.pool.acquire() as c:
        async with c.transaction():
            events=await c.fetch('''SELECT e.* FROM public.whatsapp_delivery_events e WHERE NOT applied AND EXISTS(
                SELECT 1 FROM public.whatsapp_delivery_attempts a WHERE a.provider=e.provider AND a.provider_account=e.provider_account
                AND a.recipient_e164=e.recipient_e164 AND (a.external_id=e.external_id OR a.whatsapp_id=e.whatsapp_id))
                ORDER BY e.id LIMIT 50 FOR UPDATE OF e SKIP LOCKED''')
            for event in events:
                rows=await c.fetch('''SELECT * FROM public.whatsapp_delivery_attempts WHERE provider=$1 AND provider_account=$2
                    AND recipient_e164=$3 AND ((external_id=$4 AND $4::text IS NOT NULL) OR (whatsapp_id=$5 AND $5::text IS NOT NULL)) LIMIT 2 FOR UPDATE''',
                    event['provider'],event['provider_account'],event['recipient_e164'],event['external_id'],event['whatsapp_id'])
                if len(rows)!=1:continue
                row=rows[0]
                ranks={None:0,'ACCEPTED':1,'SENT':2,'FAILED':3,'DELIVERED':4,'READ':5}
                status=event['status'] if ranks[event['status']]>=ranks.get(row['delivery_status'],0) else row['delivery_status']
                await c.execute("UPDATE public.whatsapp_delivery_attempts SET delivery_status=$2,state='ACCEPTED',whatsapp_id=coalesce(whatsapp_id,$3),updated_at=now() WHERE id=$1",row['id'],status,event['whatsapp_id'])
                if row['kind']=='CHAT':
                    part=await c.fetchrow('''SELECT o.*,q.sender_e164,q.receiver_e164 FROM public.whatsapp_reply_outbox o JOIN public.whatsapp_inbound_queue q ON q.id=o.inbound_id
                        WHERE o.id=$1 AND q.provider=$2 AND q.provider_account=$3 FOR UPDATE OF o''',int(row['target_id']),row['provider'],row['provider_account'])
                    if part:
                        await c.execute("UPDATE public.whatsapp_reply_outbox SET delivery_status=$2,provider_message_sid=$3,state=CASE WHEN state IN ('SENDING','REVIEW_REQUIRED') THEN 'ACCEPTED' ELSE state END,updated_at=now() WHERE id=$1",part['id'],'queued' if status=='ACCEPTED' else 'failed' if status=='FAILED' else status.lower(),row['external_id'])
                        if status=='FAILED' and part['delivery_status'] not in {'read','delivered'}:
                            from backend.whatsapp_queue import OutboundPart
                            value=OutboundPart.model_validate_json(queue.ciphers[part['key_id']].decrypt(bytes(part['payload_ciphertext'])))
                            await queue.schedule_fallback({'id':part['inbound_id']},part,value,connection=c)
                        await c.execute("UPDATE public.whatsapp_inbound_queue SET state='READY',updated_at=now() WHERE id=$1 AND state IN ('ACCEPTED','REVIEW_REQUIRED')",part['inbound_id'])
                elif row['kind']=='SUPPORT':
                    await c.execute('''UPDATE public.support_message_outbox SET status=$2,provider_message_sid=$3,delivery_updated_at=now()
                        WHERE id=$1::uuid AND provider=$4 AND provider_account=$5''',row['target_id'],status,row['external_id'],row['provider'],row['provider_account'])
                else:
                    table={'SHIPMENT':'shipment_sender_notifications','RETURN':'return_customer_deliveries'}[row['kind']]
                    await c.execute("UPDATE public."+table+" SET delivery_status=$2,state=CASE WHEN state IN ('SENDING','REVIEW_REQUIRED') THEN 'ACCEPTED' ELSE state END,updated_at=now() WHERE id=$1 AND provider=$3 AND provider_account=$4",int(row['target_id']),status,row['provider'],row['provider_account'])
                await c.execute('UPDATE public.whatsapp_delivery_events SET applied=true WHERE id=$1',event['id'])
