"""Offline provider contracts and isolated lifecycle rehearsal. Never a live adapter.

No network clients, database connections, real credentials or production registry
entries are constructed here. Demo state is in memory and disappears on restart.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from typing import Any, Literal
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.adapters.direct_contract import DirectLabel, DirectManifest, DirectParcel
from backend.paf_lookup import uk_postcode

Carrier = Literal['ROYALMAIL', 'EVRI']
Workspace = Literal['merchant-a', 'merchant-b']
NOTICE = 'SIMULATED - NOT VALID FOR SHIPPING OR INSURANCE. No real money moves.'


class DemoModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class QuoteInput(DemoModel):
    request_id: UUID = Field(default_factory=uuid4)
    weight_kg: Decimal = Field(gt=0, le=20, decimal_places=3)
    length_cm: Decimal = Field(gt=0, le=120)
    width_cm: Decimal = Field(gt=0, le=120)
    height_cm: Decimal = Field(gt=0, le=120)
    origin_postcode: str = Field(max_length=12)
    destination_postcode: str = Field(max_length=12)
    account_mode: Literal['PLATFORM', 'TENANT'] = 'PLATFORM'

    @field_validator('origin_postcode', 'destination_postcode')
    @classmethod
    def postcode(cls, value: str) -> str:
        return uk_postcode(value)


class BookInput(DemoModel):
    request_id: UUID = Field(default_factory=uuid4)
    offer_id: UUID
    confirm: Literal[True]
    protection_consent: bool = Field(default=False, strict=True)
    terms_accepted: bool = Field(default=False, strict=True)
    declared_value_gbp: Decimal = Field(default=Decimal('25'), gt=0, le=5000, decimal_places=2)
    scenario: Literal['NORMAL', 'REJECT', 'TIMEOUT_AFTER_ACCEPTANCE'] = 'NORMAL'


class ManifestInput(DemoModel):
    request_id: UUID = Field(default_factory=uuid4)
    carrier: Carrier
    shipment_ids: list[UUID] = Field(min_length=1, max_length=100)


class ClaimInput(DemoModel):
    request_id: UUID = Field(default_factory=uuid4)
    shipment_id: UUID
    reason: Literal['LOST', 'DAMAGED']
    description: str = Field(min_length=10, max_length=1800)
    item_value_gbp: Decimal = Field(gt=0, le=5000, decimal_places=2)


class SimulatedDirectContract:
    """Implements the existing internal contract; NOT Royal Mail/Evri wire APIs."""
    def __init__(self, carrier: Carrier, account_id: UUID) -> None:
        self.carrier, self.account_id = carrier, account_id
        self.labels: dict[str, DirectLabel] = {}

    async def quote(self, request: Any, parcel: DirectParcel) -> list[Any]:
        from main import WholesaleRate
        if request.currency != 'GBP' or parcel.weight_grams > 20000:
            return []
        base = Decimal('3.20') if self.carrier == 'EVRI' else Decimal('3.80')
        cost = base + max(Decimal(0), Decimal(parcel.weight_grams)/1000-2)*Decimal('.35')
        return [WholesaleRate(provider='REGIONAL', account_id=self.account_id,
            upstream_shipment_id='DEMO-QUOTE', upstream_rate_id='DEMO-STANDARD',
            carrier_code=self.carrier, service_code='DEMO_STANDARD', currency='GBP',
            wholesale_cost=cost.quantize(Decimal('.01')), delivery_days=3,
            execution_details={'simulated':True, 'display_service_name':'Demo Standard', 'notice':NOTICE})]

    async def purchase_label(self, shipment_data: dict[str, Any]) -> DirectLabel:
        identifier = str(UUID(str(shipment_data['request_id'])))
        if identifier not in self.labels:
            number = 'DEMO-'+self.carrier+'-'+identifier[:8]
            self.labels[identifier] = DirectLabel(tracking_number=number, provider_reference=number,
                format='PDF', document=demo_pdf('Shipping label', [number, 'Fictional parcel - do not post']))
        return self.labels[identifier]

    async def create_manifest(self, shipping_account_id: str) -> DirectManifest:
        if not shipping_account_id.startswith('DEMO-'):
            raise HTTPException(422, 'Only a dummy shipping account is accepted')
        return DirectManifest(provider_reference=shipping_account_id,
            document_pdf=demo_pdf('Manifest rehearsal', [shipping_account_id]))


def demo_pdf(title: str, lines: list[str]) -> bytes:
    from reportlab.pdfgen.canvas import Canvas
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(420, 595))
    canvas.setTitle('SIMULATED '+title)
    canvas.setFillColorRGB(.75, 0, 0)
    canvas.setFont('Helvetica-Bold', 20)
    canvas.drawString(20, 555, 'SIMULATED - DO NOT SHIP')
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setFont('Helvetica', 12)
    canvas.drawString(20, 520, title)
    for index, line in enumerate(lines[:16]):
        canvas.drawString(20, 490-index*22, line[:60])
    canvas.setFont('Helvetica', 9)
    canvas.drawString(20, 50, 'No carrier acceptance, policy coverage or real payment exists.')
    canvas.save()
    return buffer.getvalue()


def demo_qr() -> bytes:
    from reportlab.graphics import renderSVG
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.barcode.qr import QrCodeWidget
    drawing = Drawing(220, 240)
    drawing.add(QrCodeWidget('EASYINVIO-DEMO-ONLY-NOT-A-CARRIER-RETURN', x=35, y=40, barWidth=150, barHeight=150))
    drawing.add(String(15, 215, 'SIMULATED - DO NOT POST', fontSize=12))
    drawing.add(String(15, 20, 'This is not a carrier drop-off code', fontSize=10))
    return renderSVG.drawToString(drawing).encode()


class ProviderSimulation:
    def __init__(self, *, environment: str = 'SIMULATED', dummy_account: str = 'DEMO-EASYINVIO',
                 event_secret: str = 'DEMO-ONLY-DO-NOT-USE-IN-PRODUCTION') -> None:
        if environment != 'SIMULATED' or not dummy_account.startswith('DEMO-') or not event_secret.startswith('DEMO-'):
            raise ValueError('This runner accepts SIMULATED mode and DEMO-prefixed dummy settings only')
        self.dummy_account, self.event_secret = dummy_account, event_secret.encode()
        self.lock = asyncio.Lock()
        self.workspaces: dict[str, dict[str, Any]] = {}
        self.receipts: dict[tuple[str, str, UUID], tuple[str, dict[str, Any]]] = {}
        self.documents: dict[tuple[str, str], tuple[bytes, str]] = {}

    def state(self, workspace: Workspace) -> dict[str, Any]:
        if workspace not in {'merchant-a', 'merchant-b'}:
            raise HTTPException(404, 'Unknown dummy workspace')
        return self.workspaces.setdefault(workspace, {'balance':Decimal('100.00'), 'offers':{},
            'shipments':{}, 'claims':{}, 'events':{}, 'ledger':[]})

    @staticmethod
    def public(value: dict[str, Any]) -> dict[str, Any]:
        return {'simulated':True, 'notice':NOTICE, **value}

    def replay(self, workspace: Workspace, action: str, identifier: UUID, payload: BaseModel) -> dict[str, Any] | None:
        previous = self.receipts.get((workspace, action, identifier))
        digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        if previous:
            if previous[0] != digest:
                raise HTTPException(409, 'Request ID was already used with different details')
            return {**deepcopy(previous[1]), 'replayed':True}
        return None

    def remember(self, workspace: Workspace, action: str, identifier: UUID, payload: BaseModel,
                 result: dict[str, Any]) -> dict[str, Any]:
        result = self.public(result)
        self.receipts[(workspace,action,identifier)] = (hashlib.sha256(payload.model_dump_json().encode()).hexdigest(), deepcopy(result))
        return result

    def document(self, workspace: Workspace, identifier: str, data: bytes, mime: str = 'application/pdf') -> str:
        self.documents[(workspace,identifier)] = (data,mime)
        return '/api/documents/'+identifier

    async def quote(self, workspace: Workspace, body: QuoteInput) -> dict[str, Any]:
        from main import RatingRequest, CarrierAccount
        from backend.adapters.royal_mail_adapter import RoyalMailStrategy
        from backend.adapters.evri_adapter import EvriStrategy
        from types import SimpleNamespace
        async with self.lock:
            old = self.replay(workspace,'quote',body.request_id,body)
            if old:return old
            state = self.state(workspace)
            request = RatingRequest.model_validate({'origin':{'name':'Demo Sender','line1':'1 Fictional Street','city':'Demo town',
                'postal_code':body.origin_postcode,'country_code':'GB'},'destination':{'name':'Demo Recipient','line1':'2 Fictional Street',
                'city':'Demo town','postal_code':body.destination_postcode,'country_code':'GB'},'currency':'GBP',
                'weights_kg':[str(body.weight_kg)],'dimensions':[{'length_cm':str(body.length_cm),'width_cm':str(body.width_cm),'height_cm':str(body.height_cm)}]})
            offers=[]
            for carrier, strategy_type in [('ROYALMAIL',RoyalMailStrategy),('EVRI',EvriStrategy)]:
                account_id=uuid5(NAMESPACE_URL,'DEMO:'+carrier+('PLATFORM' if body.account_mode=='PLATFORM' else workspace))
                account=CarrierAccount(account_id,uuid5(NAMESPACE_URL,workspace),'REGIONAL','https://provider.invalid',None,1,'DEMO-ONLY')
                contract=SimulatedDirectContract(carrier,account_id)
                strategy=strategy_type(None,account,settings=SimpleNamespace(integration_royal_mail_enabled=True,integration_evri_enabled=True),contract=contract)
                for rate in await strategy.rates(request):
                    identifier=uuid5(body.request_id,carrier)
                    offer={'id':str(identifier),'carrier':carrier,'service':'Demo Standard','price_gbp':str(rate.wholesale_cost),
                        'days':rate.delivery_days,'account_mode':body.account_mode,'account_id':str(account_id),'expires_at':datetime.now(timezone.utc)+timedelta(minutes=10)}
                    state['offers'][str(identifier)]=offer
                    offers.append({k:v.isoformat() if isinstance(v,datetime) else v for k,v in offer.items()})
            return self.remember(workspace,'quote',body.request_id,body,{'offers':sorted(offers,key=lambda row:Decimal(row['price_gbp']))})

    async def book(self, workspace: Workspace, body: BookInput) -> dict[str, Any]:
        async with self.lock:
            old=self.replay(workspace,'book',body.request_id,body)
            if old:return old
            state=self.state(workspace);offer=state['offers'].get(str(body.offer_id))
            if not offer:raise HTTPException(404,'Offer unavailable in this workspace')
            if offer['expires_at']<=datetime.now(timezone.utc):raise HTTPException(410,'Demo offer expired; request a fresh quote')
            if body.scenario=='REJECT':raise HTTPException(422,'Simulated carrier rejection; no demo debit or label created')
            if body.protection_consent and not body.terms_accepted:raise HTTPException(422,'Accept the demo protection terms before booking')
            premium=Decimal('1.20') if body.protection_consent else Decimal(0)
            amount=Decimal(offer['price_gbp'])+premium
            if state['balance']<amount:raise HTTPException(402,'Insufficient dummy wallet funds')
            contract=SimulatedDirectContract(offer['carrier'],UUID(offer['account_id']))
            label=await contract.purchase_label({'request_id':str(body.request_id)})
            identifier=str(uuid5(body.request_id,'shipment'))
            path=self.document(workspace,'label-'+identifier,label.document)
            shipment={'id':identifier,'carrier':offer['carrier'],'tracking_number':label.tracking_number,'status':'BOOKED',
                'label_url':path,'shipping_gbp':offer['price_gbp'],'premium_gbp':str(premium),'total_gbp':str(amount),
                'policy_id':'DEMO-POLICY-'+identifier if body.protection_consent else None,'declared_value_gbp':str(body.declared_value_gbp),
                'scans':[],'return_id':None}
            state['shipments'][identifier]=shipment
            state['balance']-=amount;state['ledger'].append({'kind':'DEMO_BOOKING','amount':str(-amount),'reference':identifier})
            result=self.remember(workspace,'book',body.request_id,body,{'shipment':dict(shipment),'dummy_balance_gbp':str(state['balance'])})
            if body.scenario=='TIMEOUT_AFTER_ACCEPTANCE':
                raise HTTPException(503,{'message':'Simulated timeout after acceptance. Reconcile this request; do not make a new booking.',
                    'reconcile_url':'/api/bookings/'+str(body.request_id)})
            return result

    def shipment(self, workspace: Workspace, identifier: str) -> dict[str, Any]:
        row=self.state(workspace)['shipments'].get(identifier)
        if row is None:raise HTTPException(404,'Demo shipment unavailable in this workspace')
        return row

    async def scan(self, workspace: Workspace, identifier: str, status: str) -> dict[str, Any]:
        async with self.lock:
            row=self.shipment(workspace,identifier)
            allowed={'BOOKED':{'IN_TRANSIT','EXCEPTION'},'MANIFESTED':{'IN_TRANSIT','EXCEPTION'},
                'IN_TRANSIT':{'DELIVERED','EXCEPTION'},'EXCEPTION':{'IN_TRANSIT','DELIVERED'}}
            if status not in allowed.get(row['status'],set()):raise HTTPException(409,'Invalid demo tracking transition')
            row['status']=status;row['scans'].append({'status':status,'at':datetime.now(timezone.utc).isoformat()})
            return self.public({'shipment':dict(row)})

    async def cancel(self, workspace: Workspace, identifier: str) -> dict[str, Any]:
        async with self.lock:
            row=self.shipment(workspace,identifier);state=self.state(workspace)
            if row['status']=='CANCELLED':return self.public({'shipment':dict(row),'replayed':True})
            if row['status']!='BOOKED':raise HTTPException(409,'Demo cancellation requires an unmanifested booking')
            if any(case['shipment_id']==identifier for case in state['claims'].values()):
                raise HTTPException(409,'A demo claim is open; cancellation needs review')
            row['status']='CANCELLED';amount=Decimal(row['total_gbp']);state['balance']+=amount
            state['ledger'].append({'kind':'DEMO_CANCEL','amount':str(amount),'reference':identifier})
            return self.public({'shipment':dict(row),'dummy_balance_gbp':str(state['balance'])})

    async def manifest(self, workspace: Workspace, body: ManifestInput) -> dict[str, Any]:
        async with self.lock:
            old=self.replay(workspace,'manifest',body.request_id,body)
            if old:return old
            if len(set(body.shipment_ids))!=len(body.shipment_ids):raise HTTPException(422,'Duplicate manifest shipment')
            rows=[self.shipment(workspace,str(identifier)) for identifier in body.shipment_ids]
            if any(row['carrier']!=body.carrier or row['status']!='BOOKED' for row in rows):raise HTTPException(409,'Manifest needs unmanifested shipments from one carrier')
            document=demo_pdf('Manifest rehearsal',[body.carrier,*[row['tracking_number'] for row in rows]])
            path=self.document(workspace,'manifest-'+str(body.request_id),document)
            for row in rows:row['status']='MANIFESTED'
            return self.remember(workspace,'manifest',body.request_id,body,{'manifest_url':path,'shipment_ids':[r['id'] for r in rows],'carrier_closed':False})

    async def return_label(self, workspace: Workspace, identifier: str) -> dict[str, Any]:
        async with self.lock:
            row=self.shipment(workspace,identifier)
            if row['status']!='DELIVERED':raise HTTPException(409,'Demo return requires recorded delivery')
            if row['return_id']:return self.public({'return_id':row['return_id'],'replayed':True,
                'label_url':'/api/documents/return-'+identifier,'qr_url':'/api/documents/qr-'+identifier,'postage_purchased':False})
            row['return_id']='DEMO-RETURN-'+identifier
            path=self.document(workspace,'return-'+identifier,demo_pdf('Return rehearsal',[row['return_id']]))
            qr=self.document(workspace,'qr-'+identifier,demo_qr(),'image/svg+xml')
            return self.public({'return_id':row['return_id'],'label_url':path,'qr_url':qr,'payer':'CUSTOMER_PAY',
                'postage_purchased':False,'message':'Demo return only. Real flow requires a current policy, recipient verification and payment.'})

    async def claim(self, workspace: Workspace, body: ClaimInput) -> dict[str, Any]:
        async with self.lock:
            old=self.replay(workspace,'claim',body.request_id,body)
            if old:return old
            row=self.shipment(workspace,str(body.shipment_id))
            if row['status']=='CANCELLED':raise HTTPException(409,'Cancelled demo shipment cannot be claimed')
            if body.item_value_gbp>Decimal(row['declared_value_gbp']):raise HTTPException(422,'Claim exceeds the declared demo goods value')
            claim={'id':str(body.request_id),'shipment_id':row['id'],'reason':body.reason,'description':body.description,
                'item_value_gbp':str(body.item_value_gbp),'photos':[],
                'route':'DEMO_XCLAIM' if row['policy_id'] else 'MERCHANT_CARRIER_REVIEW','status':'NEEDS_EVIDENCE' if body.reason=='DAMAGED' else 'READY_FOR_REVIEW'}
            self.state(workspace)['claims'][str(body.request_id)]=claim
            return self.remember(workspace,'claim',body.request_id,body,{'claim':dict(claim),'wallet_credit':False})

    def claim_row(self, workspace: Workspace, identifier: str) -> dict[str, Any]:
        row=self.state(workspace)['claims'].get(identifier)
        if row is None:raise HTTPException(404,'Demo claim unavailable in this workspace')
        return row

    async def evidence(self, workspace: Workspace, identifier: str, data: bytes, mime: str) -> dict[str, Any]:
        from backend.shipment_protection import validate_evidence
        validate_evidence(data,mime)
        async with self.lock:
            row=self.claim_row(workspace,identifier)
            if row['status'] not in {'NEEDS_EVIDENCE','READY_FOR_REVIEW'}:raise HTTPException(409,'Demo claim evidence is already submitted')
            digest=hashlib.sha256(data).hexdigest()
            if digest not in row['photos']:
                if len(row['photos'])>=4:raise HTTPException(422,'Maximum four demo photos')
                row['photos'].append(digest)
            row['status']='READY_FOR_REVIEW'
            return self.public({'claim':dict(row),'wallet_credit':False})

    async def submit_claim(self, workspace: Workspace, identifier: str) -> dict[str, Any]:
        async with self.lock:
            row=self.claim_row(workspace,identifier)
            if row['route']!='DEMO_XCLAIM':return self.public({'claim':dict(row),'message':'No demo policy; retained for manual merchant/carrier review','wallet_credit':False})
            if row['status']=='SUBMITTED':return self.public({'claim':dict(row),'replayed':True,'wallet_credit':False})
            if row['status']!='READY_FOR_REVIEW':raise HTTPException(409,'Supply the missing damage photo before submission')
            row['status']='SUBMITTED'
            return self.public({'claim':dict(row),'wallet_credit':False})

    async def insurer_event(self, workspace: Workspace, raw: bytes, signature: str) -> dict[str, Any]:
        expected=hmac.new(self.event_secret,raw,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature):raise HTTPException(401,'Invalid simulated event signature')
        try:
            event=InsurerEvent.model_validate_json(raw)
        except ValueError:
            raise HTTPException(422,'Invalid simulated insurer event') from None
        async with self.lock:
            row=self.claim_row(workspace,str(event.claim_id));state=self.state(workspace)
            digest=hashlib.sha256(raw).hexdigest()
            previous=state['events'].get(str(event.event_id))
            if previous:
                if previous!=digest:raise HTTPException(409,'Simulated event ID reused with different details')
                return self.public({'claim':dict(row),'replayed':True,'wallet_credit':False})
            if row['route']!='DEMO_XCLAIM':raise HTTPException(409,'No simulated insurer policy for this case')
            if event.status=='PAID':
                if row['status']!='APPROVED' or not event.funds_received or event.payee!=self.dummy_account:
                    raise HTTPException(409,'Approval and confirmed demo master-account receipt required')
                if event.amount_gbp!=Decimal(row['item_value_gbp']):raise HTTPException(409,'Demo settlement amount mismatch')
                if any(entry['kind']=='DEMO_SETTLEMENT' and entry['reference']==row['id'] for entry in state['ledger']):raise HTTPException(409,'Demo settlement already recorded')
                state['balance']+=event.amount_gbp
                state['ledger'].append({'kind':'DEMO_SETTLEMENT','amount':str(event.amount_gbp),'reference':row['id']})
            elif row['status']!='SUBMITTED':raise HTTPException(409,'Demo insurer decision requires a submitted case')
            row['status']=event.status;state['events'][str(event.event_id)]=digest
            return self.public({'claim':dict(row),'dummy_balance_gbp':str(state['balance']),'wallet_credit':False,
                'dummy_ledger_credit':event.status=='PAID'})


class InsurerEvent(DemoModel):
    event_id: UUID = Field(default_factory=uuid4)
    claim_id: UUID
    status: Literal['APPROVED','DECLINED','PAID']
    amount_gbp: Decimal = Field(default=Decimal(0), ge=0, le=5000, decimal_places=2)
    funds_received: bool = Field(default=False, strict=True)
    payee: str = Field(default='', max_length=100)
