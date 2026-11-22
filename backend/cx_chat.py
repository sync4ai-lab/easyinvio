"""Chat adapters for shared policy/claim services; no independent action authority."""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from backend.cx_claims import ClaimIntake, ClaimScope, ClaimTriageService, fetch_claim_photo, value_from_text
from backend.cx_policies import PolicyService


async def policy_chat(state: Any,context: Any,text: str,request_id: UUID) -> dict[str,Any]:
    runtime=getattr(getattr(state,'logistics_supervisor',None),'runtime',None)
    service=PolicyService(state.finance.pool,runtime)
    confirm=re.fullmatch(r'\s*confirm policy ([a-fA-F0-9-]{36})\s*',text,re.I)
    if confirm:
        return await service.confirm(context,UUID(confirm[1]))
    return await service.propose(context,text,request_id)


async def merchant_claim(state: Any,context: Any,text: str,request_id: UUID,reference: str | None,
                         description: str | None=None) -> dict[str,Any]:
    service=ClaimTriageService(state)
    update=re.fullmatch(r'\s*claim update ([a-fA-F0-9-]{36})\s+(.{1,1800})',text,re.I|re.S)
    if update:
        identifier=UUID(update[1])
        async with service.pool.acquire() as c:
            row=await c.fetchrow('SELECT shipment_id FROM public.cx_claim_dossiers WHERE id=$1 AND tenant_id=$2 AND actor_id=$3',identifier,context.tenant_id,context.user_id)
        if row is None:
            raise HTTPException(404,'Claim case unavailable in your account')
        scope=ClaimScope(context.tenant_id,row['shipment_id'],actor_id=context.user_id)
        value=value_from_text(update[2])
        notes=re.sub(r'(?:£|GBP\s*)\d+(?:\.\d{1,2})?','',update[2],flags=re.I).strip(' ;,.')
        return await service.update(scope,identifier,description=notes if len(notes)>=10 else None,value=value)
    if not reference:
        return {'message':'Send Claim followed by your shipment/tracking reference, lost or damaged, what happened, and item value in GBP. Example: Claim YOURREF damaged The box was crushed; GBP 25.'}
    scope=await service.merchant_scope(context,reference)
    reason='DAMAGED' if re.search(r'\bdamag',text,re.I) else 'LOST'
    return await service.create(scope,ClaimIntake(request_id=request_id,reference=reference,reason=reason,
        description=(description or text)[:1800],item_value_gbp=value_from_text(text)))


async def merchant_photo(state: Any,context: Any,form: Any) -> str:
    service=ClaimTriageService(state)
    async with service.pool.acquire() as c:
        rows=await c.fetch('''SELECT id,shipment_id FROM public.cx_claim_dossiers WHERE tenant_id=$1 AND actor_id=$2
            AND updated_at>now()-interval '15 minutes' ORDER BY updated_at DESC LIMIT 2''',context.tenant_id,context.user_id)
    if len(rows)!=1:
        return 'First send Claim plus your shipment reference, lost/damaged, incident description and item value in GBP. Then upload a JPEG/PNG photo, or use the secure claim form.'
    row=rows[0]
    scope=ClaimScope(context.tenant_id,row['shipment_id'],actor_id=context.user_id)
    try:
        image,mime=await fetch_claim_photo(state,form.get('MediaUrl0',''))
        result=await service.update(scope,row['id'],image=image,mime=mime)
        return result['message']
    except HTTPException as error:
        if error.status_code>=500:
            raise
        return str(error.detail)+'. Your claim remains available in the workspace claim form; no payment was made.'


async def consumer_claim(service: Any,draft: Any,text: str,request_id: UUID,form: Any) -> str | None:
    triage=ClaimTriageService(service.state)
    scope=ClaimScope(draft.tenant_id,draft.shipment_id,capability_sha256=draft.token_sha256)
    if form.get('NumMedia')=='0' and not re.search(r'\bdamag|\blost\b|\bclaim update\b',text,re.I) and value_from_text(text) is None:
        return None
    recent=await triage.recent(scope)
    is_damage=bool(re.search(r'\bdamag|\blost\b',text,re.I))
    is_update=bool(re.match(r'\s*claim update\b',text,re.I)) or recent is not None and value_from_text(text) is not None
    if form.get('NumMedia')!='0' and recent:
        try:
            image,mime=await fetch_claim_photo(service.state,form.get('MediaUrl0',''))
            return (await triage.update(scope,recent,image=image,mime=mime))['message']
        except HTTPException as error:
            if error.status_code>=500:raise
            return str(error.detail)+'. Ask your retailer for the secure evidence upload route.'
    if is_update and recent:
        explicit=re.match(r'\s*claim update\s+([a-fA-F0-9-]{36})\b',text,re.I)
        if explicit:recent=UUID(explicit[1])
        notes=re.sub(r'^\s*claim update(?:\s+[a-fA-F0-9-]{36})?\s*','',text,flags=re.I)
        notes=re.sub(r'(?:£|GBP\s*)\d+(?:\.\d{1,2})?','',notes,flags=re.I).strip(' ;,.')
        return (await triage.update(scope,recent,description=notes if len(notes)>=10 else None,value=value_from_text(text)))['message']
    if not is_damage:
        return None
    return (await triage.create(scope,ClaimIntake(request_id=request_id,reference=str(draft.shipment_id),reason='DAMAGED' if re.search(r'damag',text,re.I) else 'LOST',description=text[:1800],item_value_gbp=value_from_text(text))))['message']
