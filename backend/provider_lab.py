"""Local-only FastAPI surface for the isolated provider simulator."""
from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import Field

from backend.provider_simulation import (ProviderSimulation, Workspace, DemoModel, QuoteInput,
    BookInput, ManifestInput, ClaimInput, InsurerEvent)


class ScanInput(DemoModel):
    status: Literal['IN_TRANSIT','DELIVERED','EXCEPTION']


class ChatInput(DemoModel):
    request_id: UUID = Field(default_factory=uuid4)
    text: str = Field(min_length=1,max_length=1000)


def build_lab(simulation: ProviderSimulation | None = None) -> FastAPI:
    service=simulation or ProviderSimulation()
    app=FastAPI(title='EasyInvio SIMULATED Provider Lab')
    app.state.simulation=service

    @app.middleware('http')
    async def headers(request: Request,call_next: Any) -> Response:
        origin=request.headers.get('origin')
        if request.method not in {'GET','HEAD','OPTIONS'} and origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
            return Response('Cross-origin demo mutation refused',status_code=403)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-EasyInvio-Simulated']='true'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get('/',response_class=HTMLResponse)
    async def page() -> str:
        return (Path(__file__).resolve().parents[1]/'frontend/provider_lab.html').read_text(encoding='utf-8')

    @app.get('/api/state')
    async def state(x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        data=service.state(x_demo_workspace)
        return service.public({'workspace':x_demo_workspace,'demo_payee':service.dummy_account,'dummy_balance_gbp':str(data['balance']),
            'shipments':list(data['shipments'].values()),'claims':list(data['claims'].values()),'ledger':data['ledger']})

    @app.post('/api/quotes')
    async def quotes(body: QuoteInput,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        return await service.quote(x_demo_workspace,body)

    @app.post('/api/bookings')
    async def book(body: BookInput,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        return await service.book(x_demo_workspace,body)

    @app.get('/api/bookings/{request_id}')
    async def reconcile(request_id: UUID,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        row=service.receipts.get((x_demo_workspace,'book',request_id))
        if not row:raise HTTPException(404,'No accepted demo booking with that request ID')
        return {**row[1],'reconciled':True}

    @app.post('/api/shipments/{identifier}/scan')
    async def scan(identifier: UUID,body: ScanInput,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        return await service.scan(x_demo_workspace,str(identifier),body.status)

    @app.post('/api/shipments/{identifier}/cancel')
    async def cancel(identifier: UUID,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        return await service.cancel(x_demo_workspace,str(identifier))

    @app.post('/api/shipments/{identifier}/return')
    async def returning(identifier: UUID,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        return await service.return_label(x_demo_workspace,str(identifier))

    @app.post('/api/manifests')
    async def manifest(body: ManifestInput,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        return await service.manifest(x_demo_workspace,body)

    @app.post('/api/claims')
    async def claim(body: ClaimInput,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        return await service.claim(x_demo_workspace,body)

    @app.post('/api/claims/{identifier}/evidence')
    async def evidence(identifier: UUID,request: Request,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>5_000_000:raise HTTPException(413,'Demo photo exceeds 5 MB')
        return await service.evidence(x_demo_workspace,str(identifier),bytes(data),request.headers.get('content-type','').split(';')[0])

    @app.post('/api/claims/{identifier}/submit')
    async def submit(identifier: UUID,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        return await service.submit_claim(x_demo_workspace,str(identifier))

    @app.post('/api/simulate-insurer-event')
    async def event(body: InsurerEvent,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        # This is an explicit lab control, not an insurer endpoint or user approval API.
        raw=body.model_dump_json().encode()
        signature=hmac.new(service.event_secret,raw,hashlib.sha256).hexdigest()
        return await service.insurer_event(x_demo_workspace,raw,signature)

    @app.get('/api/documents/{identifier}')
    async def document(identifier: str,x_demo_workspace: Workspace = Header(default='merchant-a')) -> Response:
        row=service.documents.get((x_demo_workspace,identifier))
        if row is None:raise HTTPException(404,'Demo document unavailable in this workspace')
        return Response(row[0],media_type=row[1],headers={'Content-Disposition':'attachment; filename="SIMULATED-document"'})

    @app.post('/api/chat')
    async def chat(body: ChatInput,x_demo_workspace: Workspace = Header(default='merchant-a')) -> dict[str,Any]:
        text=body.text.strip();state=service.state(x_demo_workspace)
        if text.lower() in {'hi','hello','help'}:
            return service.public({'message':'Welcome to the SIMULATED EasyInvio shipping lab. Try: Quote 2kg from LS12 6EJ to B69 3EB 25x20x15. Then Book 1 insured, Track <shipment ID>, Return <shipment ID>, or Claim <shipment ID> damaged. No WhatsApp message is sent.'})
        quote=re.fullmatch(r'quote ([0-9.]+)kg from ([A-Za-z0-9 ]+) to ([A-Za-z0-9 ]+) ([0-9.]+)[x?]([0-9.]+)[x?]([0-9.]+)(?: cm)?',text,re.I)
        if quote:
            try:
                values=QuoteInput(request_id=body.request_id,weight_kg=quote[1],origin_postcode=quote[2].strip(),destination_postcode=quote[3].strip(),length_cm=quote[4],width_cm=quote[5],height_cm=quote[6])
            except ValueError:raise HTTPException(422,'Use valid full UK postcodes, weight up to 20kg and positive box dimensions') from None
            result=await service.quote(x_demo_workspace,values)
            state['chat_offers']=[row['id'] for row in result['offers']]
            message='SIMULATED quote (dummy prices, GBP): '+ '; '.join(f"{i}. {r['carrier']} {r['service']} {r['price_gbp']}" for i,r in enumerate(result['offers'],1))+'. Reply Book 1 or Book 2. Add insured to rehearse consent with a dummy GBP25 goods value.'
            return {**result,'message':message}
        booking=re.fullmatch(r'book ([12])( insured)?',text,re.I)
        if booking:
            offers=state.get('chat_offers',[]);index=int(booking[1])-1
            if len(offers)<=index:raise HTTPException(409,'Request a demo quote first')
            # The explicit lab command includes demo protection consent, not real consent.
            insured=bool(booking[2])
            result=await service.book(x_demo_workspace,BookInput(request_id=body.request_id,offer_id=offers[index],confirm=True,protection_consent=insured,terms_accepted=insured))
            return {**result,'message':'SIMULATED booking '+result['shipment']['id']+'. Use the shipment controls below for scans, evidence and insurer events.'}
        command=re.fullmatch(r'(track|return|claim) ([a-f0-9-]{36})(?: (lost|damaged))?',text,re.I)
        if command:
            identifier=str(UUID(command[2]))
            if command[1].lower()=='track':return service.public({'message':'SIMULATED status: '+service.shipment(x_demo_workspace,identifier)['status']})
            if command[1].lower()=='return':return {**(await service.return_label(x_demo_workspace,identifier)),'message':'SIMULATED return; use document links below. No postage purchased.'}
            if command[3]:
                result=await service.claim(x_demo_workspace,ClaimInput(request_id=body.request_id,shipment_id=identifier,reason=command[3].upper(),description='Demo customer reports a '+command[3].lower()+' parcel',item_value_gbp='25'))
                return {**result,'message':'SIMULATED claim '+result['claim']['id']+'. '+('Upload a damage photo using the evidence control.' if command[3].lower()=='damaged' else 'Ready for review. No approval or payment.')}
        return service.public({'message':'For this offline chat use Hello; Quote 2kg from LS12 6EJ to B69 3EB 25x20x15; Book 1 insured; Track <shipment UUID>; Return <shipment UUID>; Claim <shipment UUID> damaged. Use the panels for the remaining rehearsal steps.'})

    return app
