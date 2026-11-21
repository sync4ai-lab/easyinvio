"""Progressive public shipping assistance. Never purchases or issues tenant identity."""
from __future__ import annotations
import hashlib,json,re
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from typing import Literal,Any
from urllib.parse import urlencode
from uuid import UUID
import jwt
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,Field
from backend.agents.models import ConversationalIntent
from backend.agents.shipping_intents import classify
from backend.whatsapp_provider import provider,account


class GuestDraft(BaseModel):
    model_config=ConfigDict(extra='forbid')
    state:Literal['QUOTE','AWAITING_TRACKING_REF']
    quote:ConversationalIntent|None=None
    expires_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc)+timedelta(minutes=15))


class QuickQuoteToken(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token:str=Field(min_length=20,max_length=3000)


def requested_feature(text:str)->tuple[str,str]|None:
    if not re.search(r'\b(?:generate|build|automate|set|connect|use|enable|recommend|advise|predict)\b',text,re.I):return None
    for pattern,feature,label in [(r'\b(?:hs code|customs classification)\b','customs_hs_builder','HS code builder'),
        (r'\b(?:custom margin|margin rule)\b','custom_margin_rules','Custom margin rules'),
        (r'\b(?:byoc|own carrier contract|own carrier account)\b','byoc_carrier_accounts','Your own carrier contract'),
        (r'\b(?:carrier advisor|delay risk|carrier recommendation)\b','ai_carrier_advisor','Carrier advisor')]:
        if re.search(pattern,text,re.I):return feature,label
    return None


async def feature_handoff(request:Request,context:Any,text:str)->str|None:
    desired=requested_feature(text)
    if not desired:return None
    feature,label=desired;state=request.app.state;base=state.settings.booking_page_url.rstrip('/')
    from backend.entitlements import guard_feature
    try:await guard_feature(state.whatsapp.pool,state.settings,context.tenant_id,feature)
    except HTTPException as error:
        if error.status_code!=402:raise
        plan='Velocity' if feature=='ai_carrier_advisor' else 'Command'
        return label+' unlocks on '+plan+'. You can still use your current services. Compare plans: '+base+'/pricing'
    return label+' is available on your plan. Open your workspace to review the required details: '+base+'/workspace'+'. No settings, shipment or payment have been changed.'


def quote_link(settings:Any,facts:ConversationalIntent)->str:
    now=datetime.now(timezone.utc)
    # No identity, rates, payment authority or carrier reservation enters this JWT.
    fields=facts.model_dump(mode='json',include={'weight_kg','origin_country','destination_country','origin_city','destination_city','origin_postal_code','destination_postal_code','dimensions_cm','cargo_type'})
    token=jwt.encode({'aud':'easyinvio-quick-quote','purpose':'PREFILL_ONLY','iat':now,'exp':now+timedelta(minutes=15),'facts':fields},settings.quote_link_secret.get_secret_value(),algorithm='HS256')
    return settings.booking_page_url.rstrip('/')+'/login?'+urlencode({'mode':'signup','quick_quote':token})


def verify_quote(settings:Any,token:str)->dict:
    try:
        data=jwt.decode(token,settings.quote_link_secret.get_secret_value(),algorithms=['HS256'],audience='easyinvio-quick-quote',options={'require':['exp','iat','aud','purpose','facts']})
        if data['purpose']!='PREFILL_ONLY':raise ValueError()
        facts=ConversationalIntent(intent='QUOTE',**data['facts'])
        if facts.weight_kg and not Decimal('0')<Decimal(facts.weight_kg)<=1000:raise ValueError()
        return facts.model_dump(mode='json',exclude_none=True)
    except (jwt.PyJWTError,ValueError,TypeError):raise HTTPException(400,'That quick quote link is invalid or expired. Ask for a fresh quote.') from None


def quote_missing(facts:ConversationalIntent)->list[str]:
    missing=[]
    if not facts.weight_kg:missing.append('packed weight in kg')
    if not facts.origin_country:missing.append('pickup town/postcode and country')
    if not facts.destination_country:missing.append('delivery town/postcode and country')
    return missing


def ballpark(settings:Any,facts:ConversationalIntent)->str:
    missing=quote_missing(facts)
    if missing:return 'To estimate your shipping, send together: '+ '; '.join(missing)+'. Include box dimensions if known. Example: Quote 2kg from Leeds GB to London GB, 30x20x10 cm.'
    link=quote_link(settings,facts)
    if facts.origin_country!='GB' or facts.destination_country!='GB' or facts.cargo_type!='PARCEL':
        return 'I have your route and weight. International/freight prices need a live service check; I won’t guess a carrier price. Continue with your saved details: '+link
    from main import Address,Dimensions,RatingRequest
    from backend.advanced_logistics import preview_rates
    dims=facts.dimensions_cm or [Decimal(30),Decimal(20),Decimal(10)]
    address=Address(name='Illustrative sample',line1='Sample',city='Sample',postal_code='SW1A 1AA',country_code='GB')
    result=preview_rates(RatingRequest(origin=address,destination=address,weights_kg=[facts.weight_kg],dimensions=[Dimensions(**dict(zip(('length_cm','width_cm','height_cm'),dims)))]))
    rates=result['rates'][:2]
    lines=['*Illustrative UK estimate*',f'{facts.weight_kg} kg • '+('your supplied box size' if facts.dimensions_cm else 'assumed 30×20×10 cm box')]
    lines.extend(f'• Sample option {i}: £{r["client_price_ex_tax"]} excl. VAT' for i,r in enumerate(rates,1))
    lines.extend(['Examples only—not live carrier offers or guaranteed availability.','Get live rates with your saved details: '+link])
    return '\n'.join(lines)


class GuestShippingAssistant:
    def __init__(self,request:Request):
        self.request=request;self.state=request.app.state;self.settings=self.state.settings
        self.queue=self.state.whatsapp_queue;self.pool=self.queue.pool

    def key(self,form:Any)->tuple[str,...]:
        return (provider(self.settings),account(self.settings),form['From'].removeprefix('whatsapp:'),form['To'].removeprefix('whatsapp:'))

    async def load(self,form:Any)->GuestDraft|None:
        async with self.pool.acquire() as c:
            row=await c.fetchrow('''SELECT payload_ciphertext,key_id FROM public.whatsapp_guest_drafts
             WHERE provider=$1 AND provider_account=$2 AND sender_e164=$3 AND receiver_e164=$4 AND expires_at>now()''',*self.key(form))
        if not row:return None
        draft=GuestDraft.model_validate_json(self.queue.ciphers[row['key_id']].decrypt(bytes(row['payload_ciphertext'])))
        return draft if draft.expires_at>datetime.now(timezone.utc) else None

    async def save(self,form:Any,draft:GuestDraft)->None:
        async with self.pool.acquire() as c:
            await c.execute('''INSERT INTO public.whatsapp_guest_drafts(provider,provider_account,sender_e164,receiver_e164,payload_ciphertext,key_id,expires_at)
             VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(provider,provider_account,sender_e164,receiver_e164)
             DO UPDATE SET payload_ciphertext=excluded.payload_ciphertext,key_id=excluded.key_id,expires_at=excluded.expires_at''',
             *self.key(form),self.queue.encrypt(draft.model_dump_json().encode()),self.queue.key_id,draft.expires_at)

    async def clear(self,form:Any)->None:
        async with self.pool.acquire() as c:
            await c.execute('DELETE FROM public.whatsapp_guest_drafts WHERE provider=$1 AND provider_account=$2 AND sender_e164=$3 AND receiver_e164=$4',*self.key(form))

    async def public_status(self,reference:str)->str:
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',reference):return 'That reference format looks incomplete. Please try the full carrier tracking number, or paste your secure EasyInvio tracking link.'
        try:shipment_id=UUID(reference)
        except ValueError:shipment_id=None
        # An exact reference is not authentication. Merchants must explicitly
        # publish this small projection; ambiguity never identifies a tenant.
        async with self.pool.acquire() as c:
            rows=await c.fetch('''SELECT s.id,s.tenant_id,s.status::text AS status,s.carrier_code
             FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
             WHERE t.public_status_lookup_enabled AND (s.tracking_number=$1 OR s.id=$2::uuid) LIMIT 2''',reference,shipment_id)
            if len(rows)!=1:return 'I couldn’t find a publicly available status for that reference. Check it and try again, or paste your retailer’s secure tracking link. This does not mean the parcel does not exist.'
            row=rows[0]
            events=await c.fetch('''SELECT coalesce(response->'tracking_detail'->>'milestone',status) AS status,occurred_at FROM public.tracking_events
             WHERE tenant_id=$1 AND shipment_id=$2 AND response->>'applied'='true' ORDER BY occurred_at DESC LIMIT 3''',row['tenant_id'],row['id'])
        # Fixed status vocabulary only: no arbitrary carrier prose or location,
        # contacts, addresses, order IDs, prices or POD URLs can leave here.
        allowed={'DRAFT','QUOTED','BOOKED','LABEL_CREATED','IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','CANCELLED','RETURNED','PENDING','COLLECTED','FAILED','PRE_TRANSIT','AVAILABLE_FOR_PICKUP','RETURNED_TO_SENDER','CUSTOMS_PROCESSING','DELIVERY_ATTEMPTED','UNKNOWN'}
        latest=events[0]['status'] if events else row['status']
        status=latest if latest in allowed else 'PENDING'
        known={'ROYAL_MAIL':'Royal Mail','EVRI':'Evri','DPD':'DPD','DHL':'DHL','UPS':'UPS','FEDEX':'FedEx'}
        text='*Public parcel status*\n'+status.replace('_',' ').title()+' • '+known.get(row['carrier_code'],'Carrier service')
        for event in events:
            if event['status'] in allowed:text+='\n• '+event['status'].replace('_',' ').title()+' — '+event['occurred_at'].strftime('%d %b %H:%M UTC')
        return text+'\nFor private details or changes, sign in: '+self.settings.booking_page_url.rstrip('/')+'/login?mode=signin'

    async def handle(self,form:Any)->str|None:
        text=form['Body'].strip()
        from backend.whatsapp_concierge import social
        if social(text):return None
        if text.lower() in {'cancel','start over'}:
            await self.clear(form);return 'Your draft is cleared. What would you like to ship or check?'
        try:intent=classify(text)
        except ValueError:intent=None
        from backend.agents.rag_support import documentation_question
        if intent and intent.intent=='KNOWLEDGE_QUERY' and documentation_question(text):return None
        draft=await self.load(form)
        async with self.pool.acquire() as c:
            count=await c.fetchval('''SELECT count(*) FROM (SELECT 1 FROM public.whatsapp_inbound_queue
             WHERE provider=$1 AND provider_account=$2 AND sender_e164=$3 AND receiver_e164=$4
             AND created_at>now()-interval '24 hours' LIMIT 32) recent''',*self.key(form))
        if count>31:return ''
        if count==31:return 'Today’s public WhatsApp guidance limit is reached. Continue at '+self.settings.booking_page_url.rstrip('/')+'/help'
        if intent is None:return 'Please check the weight and dimensions. Example: Quote 2kg from Leeds GB to London GB, 30x20x10 cm.'
        if requested_feature(text):return 'I can explain the feature here. To use workspace tools, sign in first: '+self.settings.booking_page_url.rstrip('/')+'/login?mode=signin'
        if intent.intent=='QUOTE' or draft and draft.state=='QUOTE' and not re.search(r'\b(?:track|return|refund|address|how|what|help)\b',text,re.I):
            proposed=(intent.facts if intent.intent=='QUOTE' else classify('Quote '+text).facts)
            if proposed is None:return None
            values=draft.quote.model_dump() if draft and draft.state=='QUOTE' and draft.quote else {'intent':'QUOTE'}
            values.update(proposed.model_dump(exclude_none=True,exclude_defaults=True));values['intent']='QUOTE'
            facts=ConversationalIntent.model_validate(values)
            missing=quote_missing(facts)
            if missing:await self.save(form,GuestDraft(state='QUOTE',quote=facts,expires_at=draft.expires_at if draft else datetime.now(timezone.utc)+timedelta(minutes=15)))
            else:await self.clear(form)
            return ballpark(self.settings,facts)
        if intent.intent=='TRACK' or draft and draft.state=='AWAITING_TRACKING_REF' and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',text):
            reference=re.sub(r'^(?:track|tracking)(?:\s+(?:number|ref|parcel|shipment))?\s*','',text,flags=re.I).strip()
            if intent.intent=='TRACK' and not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',reference):
                await self.save(form,GuestDraft(state='AWAITING_TRACKING_REF'))
                return 'Sure—send the full carrier tracking number, or paste your secure EasyInvio tracking link. I can show published status here; private details stay protected.'
            result=await self.public_status(reference)
            await self.save(form,GuestDraft(state='AWAITING_TRACKING_REF',expires_at=draft.expires_at if draft else datetime.now(timezone.utc)+timedelta(minutes=15)))
            return result
        if intent.intent in {'CHANGE_ADDRESS','RETURN_REQUEST','REFUND_OR_CLAIM','BOOK_SELECTION','COMPLAINT_OR_SUPPORT'}:
            return ('I can help. For parcel-specific action, paste your secure EasyInvio tracking link, or sign in to verify your account: '+self.settings.booking_page_url.rstrip('/')+'/login?mode=signin'+
                    '\nNo address, payment or booking has been changed.')
        return None


def build_router(authenticate:Any)->APIRouter:
    router=APIRouter()
    @router.post('/api/v1/public/quick-quote')
    async def prefill(body:QuickQuoteToken,request:Request,response:Response):
        response.headers['Cache-Control']='no-store'
        return {'facts':verify_quote(request.app.state.settings,body.token),'authorizes_booking':False}
    @router.put('/api/v1/whatsapp/public-status-policy')
    async def policy(body:PublicStatusPolicy,request:Request,context=Depends(authenticate)):
        if not getattr(request.app.state.settings,'whatsapp_progressive_enabled',False):raise HTTPException(503,'Enable progressive assistance after migration 055')
        if context.role not in {'OWNER','ADMIN'} or getattr(context,'assistance_session_id',None):raise HTTPException(403,'A direct merchant Owner/Admin session is required')
        async with request.app.state.whatsapp_queue.pool.acquire() as c:
            if not await c.fetchval('''SELECT EXISTS(SELECT 1 FROM public.users u JOIN public.tenants t USING(tenant_id)
             WHERE u.tenant_id=$1 AND u.auth_user_id=$2 AND u.is_active AND u.role IN ('OWNER','ADMIN') AND t.workspace_status='ACTIVE')''',context.tenant_id,context.user_id):raise HTTPException(403,'Active merchant membership required')
            await c.execute('UPDATE public.tenants SET public_status_lookup_enabled=$2 WHERE tenant_id=$1',context.tenant_id,body.enabled)
        return {'enabled':body.enabled,'scope':'Status, carrier and scan timestamps only; no personal details'}
    return router


class PublicStatusPolicy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool=Field(strict=True)
