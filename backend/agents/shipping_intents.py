"""Cheap, grounded routing before any model call. Never executes an action."""
import re
from decimal import Decimal
from backend.agents.models import ConversationalIntent,ShippingIntent
from backend.agents.conversation_context import explicit_quote,location


def classify(text: str) -> ShippingIntent:
    value=text.strip()
    if re.search(r'\b(?:change|update|redirect|amend)\b.{0,40}\b(?:address|delivery|parcel)\b',value,re.I):
        return ShippingIntent(intent='CHANGE_ADDRESS')
    if re.search(r'\b(?:pack|packing|fragile|glass|batteries|battery|prohibited|volumetric|customs|lithium)\b',value,re.I) and re.search(r'\b(?:how|can|what|advice|safe|tips|explain)\b',value,re.I):
        return ShippingIntent(intent='KNOWLEDGE_QUERY',knowledge_kind='LOGISTICS_ADVICE')
    selection=re.fullmatch(r'(?:book|confirm|select)(?:\s+option)?\s+(10|[1-9])',value,re.I)
    if selection:return ShippingIntent(intent='BOOK_SELECTION',facts=ConversationalIntent(intent='BOOK_RESERVATION',selection_index=int(selection[1])))
    wants_quote=re.search(r'\b(?:quote|rates?|shipping price)\b',value,re.I) or re.search(r'\b(?:send|ship|post)\b.{0,40}\b(?:parcel|package|kg|to)\b',value,re.I)
    if wants_quote and not re.match(r'\s*(?:how|why|explain)\b',value,re.I):
        size=re.search(r'\b(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*cm\b',value,re.I)
        clean=(value[:size.start()]+value[size.end():]).strip(' ,;') if size else value
        weight=re.search(r'\b\d+(?:\.\d+)?\s*(?:kg|kilograms?)\b',clean,re.I)
        route_text=re.sub(r'\b\d+(?:\.\d+)?\s*(?:kg|kilograms?)\b','',clean,flags=re.I)
        facts=explicit_quote('Quote '+route_text) or ConversationalIntent(intent='QUOTE')
        if weight:facts=facts.model_copy(update={'weight_kg':str(Decimal(re.match(r'\d+(?:\.\d+)?',weight[0])[0]))})
        if not re.search(r'\bfrom\b',value,re.I):
            destination=re.search(r'\bto\s+(.+)$',route_text,re.I)
            if destination:facts=facts.model_copy(update={'destination_'+k:v for k,v in location(destination[1]).items()})
        if size:
            dims=[Decimal(x) for x in size.groups()]
            if any(x<=0 or x>1000 for x in dims):raise ValueError('Use positive dimensions up to 1000 cm')
            facts=facts.model_copy(update={'dimensions_cm':dims})
        if facts.weight_kg and not Decimal('0')<Decimal(facts.weight_kg)<=Decimal('1000'):raise ValueError('Use a packed weight between 0 and 1000 kg')
        if re.search(r'\bpallet\b',value,re.I):facts=facts.model_copy(update={'cargo_type':'PALLET'})
        elif re.search(r'\bfreight\b',value,re.I):facts=facts.model_copy(update={'cargo_type':'OVERLAND_FREIGHT'})
        return ShippingIntent(intent='QUOTE',facts=facts)
    if re.search(r'\b(?:refund|claim|void|lost|damaged)\b',value,re.I):return ShippingIntent(intent='REFUND_OR_CLAIM')
    if re.search(r'\breturn policy\b',value,re.I):return ShippingIntent(intent='KNOWLEDGE_QUERY',knowledge_kind='APP_FAQ')
    if re.search(r'\b(?:return|paperless|drop.?off qr)\b',value,re.I) and not re.match(r'\s*(?:how|what)\b',value,re.I):return ShippingIntent(intent='RETURN_REQUEST')
    if re.search(r'\b(?:track|tracking|where is my|status of)\b',value,re.I) and not re.match(r'\s*how\b',value,re.I):return ShippingIntent(intent='TRACK')
    if re.search(r'\b(?:complaint|support|missed collection|delivery exception|late delivery)\b',value,re.I):return ShippingIntent(intent='COMPLAINT_OR_SUPPORT')
    return ShippingIntent(intent='KNOWLEDGE_QUERY',knowledge_kind='APP_FAQ')
