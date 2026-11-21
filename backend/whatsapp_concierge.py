"""Short public WhatsApp guidance. No tenant context, account tools or spending.

Queue receipts own delivery idempotency. Public responses use durable inbound
counts and the existing shared public AI budget/cache, never a model for hello.
"""
import asyncio
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import HTTPException
from backend.public_experience import needs_workspace
from backend.whatsapp_provider import account, provider


def social(text):
    value=text.strip().lower().strip('!.,? ')
    if re.fullmatch(r'(?:hi|hello|hey|hiya|good (?:morning|afternoon|evening))(?: there| easyinvio)?',value):return 'WELCOME'
    if value in {'help','menu','services','options','what can you do','what can you do for me'}:return 'MENU'
    if value in {'thanks','thank you','cheers','thank you very much','bye','goodbye'}:return 'THANKS'
    return None


def welcome(known=False):
    opening='Hi, welcome back to EasyInvio!' if known else 'Hi, welcome to EasyInvio!'
    return (opening+' I can help with:\n'
        '• Shipping quotes and booking\n• Tracking, returns and delivery help\n'
        '• Getting started and connecting your store\n'
        'What would you like to do? You can ask in your own words.')


async def answer(request,form,*,known=False):
    state=request.app.state;s=state.settings
    text=form.get('Body','').strip()
    base=s.booking_page_url.rstrip('/')
    # Never store prompts or issue tenant authority in this helper. A bounded
    # indexed scan counts even duplicate provider-independent message attempts.
    async with state.whatsapp_queue.pool.acquire() as c:
        count=await c.fetchval('''SELECT count(*) FROM (
          SELECT 1 FROM public.whatsapp_inbound_queue
          WHERE provider=$1 AND provider_account=$2 AND sender_e164=$3 AND receiver_e164=$4
          AND created_at>now()-interval '24 hours' ORDER BY id DESC LIMIT 32) recent''',
          provider(s),account(s),form['From'].removeprefix('whatsapp:'),form['To'].removeprefix('whatsapp:'))
    if count>31:return None  # Do not pay for an endless limit-response loop.
    if count==31:return 'You have reached today’s WhatsApp guidance limit. Please continue at '+base+'/help or in your workspace.'
    kind=social(text)
    if kind in {'WELCOME','MENU'}:return welcome(known)
    if kind=='THANKS':return 'You’re welcome! Message us whenever you need shipping help.'
    if form.get('NumMedia')!='0':return 'Please send your question as text so I can help. Share parcel evidence through the retailer’s secure support channel.'
    if text.lower() in {'1','2','3'}:return 'Please tell me what you need in a few words, such as “get a shipping quote”, “track my parcel” or “connect Shopify”.'
    from backend.agents.rag_support import documentation_question
    from backend.agents.shipping_intents import classify
    if classify(text).intent=='CHANGE_ADDRESS':
        return ('Before booking, review the address and get a fresh quote in your workspace. After booking, changes need carrier review. '
                'Paste your secure tracking link for parcel help, or open '+base+'/workspace. No address has been changed.')
    if classify(text).knowledge_kind=='LOGISTICS_ADVICE':
        if count>20:return 'For more guidance today, please open '+base+'/help'
        from backend.agents.logistics_advisor import advice
        return await advice(request,text)
    from backend.cx_intents import cx_intent
    # Private actions never reach public retrieval, even if phrased politely.
    if needs_workspace(text) or (cx_intent(text) and not documentation_question(text)) or re.search(r'\b(?:track|tracking|complaint|damaged|missing parcel|my return|my refund)\b',text,re.I) and not documentation_question(text):
        return 'I can help with that. Please paste the secure EasyInvio tracking link from your retailer so I can access only the right parcel. For merchant account questions, open '+base+'/workspace.'
    if re.search(r'\b(?:pricing|plans?|subscriptions?)\b|\bwhatsapp\b.*\b(?:free|paid)\b',text,re.I):
        return ('Anyone can ask general questions or use a secure parcel link for delivery help. Merchant WhatsApp booking requires a verified workspace number and Velocity or Command. '
                'Your existing role and carrier/payment checks still apply. Compare plans: '+base+'/pricing')
    if re.search(r'\b(?:quote|book|rates?|cost|price|send|ship)\b',text,re.I) and not documentation_question(text):
        return ('For a live quote, use your signed-in workspace with the parcel’s weight, dimensions and addresses. '
            'WhatsApp booking requires a verified workspace number and Velocity or Command. Start here: '+base+'/login?mode=signin')
    if not documentation_question(text) and not re.search(r'\b(?:shipping|parcel|carrier|integrat\w*|shopify|amazon|woocommerce|pricing|plans?|wallet|labels?|returns?|easyinvio)\b',text,re.I):
        return 'I help with EasyInvio shipping. Are you looking to send a parcel, get delivery help, or set up your workspace?'
    if count>20:return 'For more detailed guidance today, please open '+base+'/help. You can also continue in your signed-in workspace.'
    from backend.agents.supervisor import supervisor
    try:
        async with asyncio.timeout(30):
            result=await supervisor(request).help.answer(SimpleNamespace(tenant_id='public-documentation',role='PUBLIC'),
                text[:1000],allow_web=False,concise=True)
    except (HTTPException,TimeoutError):
        return 'I can’t retrieve that guidance right now. Please try the Help Centre: '+base+'/help'
    if result.get('mode')=='NO_EVIDENCE':return 'I don’t have a verified EasyInvio answer for that yet. Please check '+base+'/help or tell me which shipping task you need help with.'
    # One short response, at most one published help link. Never forward raw
    # source metadata or capability URLs from a model response.
    reply=result['answer'].strip()
    if len(reply)>1050:reply=reply[:1050].rsplit(' ',1)[0]+'…'
    for source in result.get('sources',[]):
        path=source.get('url','');parsed=urlsplit(path)
        if path.startswith('/help/') and not parsed.netloc and not parsed.scheme:
            reply+='\nMore detail: '+base+path
            break
    return reply[:1500]
