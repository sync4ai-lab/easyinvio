"""Cargo-aware bulk rating, confirmed EasyPost purchase and customs bundles.

Freight tariff factors are contract settings, not a universal NMFC class.
Regional purchasing is enabled only through an explicitly registered adapter.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, localcontext
from typing import Any, Literal
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import asyncpg
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.ai_engine import country_code, predict_hs_code, strict_decimal, record_invoice_baseline

EU_CUSTOMS_AREA = frozenset('AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE'.split())
_scope: ContextVar[tuple[Any, UUID] | None] = ContextVar('automation_customs_scope', default=None)
logger=logging.getLogger('veloce.automation')


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)


class Cargo(StrictInput):
    cargo_type: Literal['LETTER', 'PARCEL', 'PALLET', 'OVERLAND_FREIGHT'] = 'PARCEL'
    actual_weight_kg: Decimal = Field(gt=0, le=30000, decimal_places=3)
    length_cm: Decimal | None = Field(default=None, gt=0, le=1500, decimal_places=2)
    width_cm: Decimal | None = Field(default=None, gt=0, le=300, decimal_places=2)
    height_cm: Decimal | None = Field(default=None, gt=0, le=400, decimal_places=2)
    stackable: bool = True

    @model_validator(mode='before')
    @classmethod
    def strip_letter_dimensions(cls,value):
        if isinstance(value,dict) and value.get('cargo_type')=='LETTER':
            return {**value,'length_cm':None,'width_cm':None,'height_cm':None}
        return value

    @field_validator('actual_weight_kg', 'length_cm', 'width_cm', 'height_cm', mode='before')
    @classmethod
    def decimals(cls, value):
        return None if value is None else strict_decimal(value)

    @model_validator(mode='after')
    def rules(self):
        if self.cargo_type == 'LETTER':
            if self.actual_weight_kg >= Decimal('.5'):
                raise ValueError('LETTER must weigh strictly below 0.5 kg')
            self.length_cm = self.width_cm = self.height_cm = None
        elif any(value is None for value in [self.length_cm,self.width_cm,self.height_cm]):
            raise ValueError('Non-letter cargo requires all three dimensions')
        if self.cargo_type == 'PARCEL' and (self.actual_weight_kg > 1000 or any(v > 1000 for v in [self.length_cm,self.width_cm,self.height_cm])):
            raise ValueError('Express parcel limits are 1000 kg and 1000 cm')
        return self


def calculate_cargo_charge(cargo: Cargo, *, kg_per_m3=Decimal('333'), kg_per_loading_metre=Decimal('1750'), deck_width_m=Decimal('2.4')) -> dict:
    with localcontext() as ctx:
        ctx.prec=50
        actual=cargo.actual_weight_kg
        if cargo.cargo_type=='LETTER':
            return {'cargo_type':'LETTER','actual_weight_kg':str(actual),'billable_weight_kg':str(actual),'basis':'actual','dimensions_required':False}
        volume=cargo.length_cm*cargo.width_cm*cargo.height_cm/Decimal('1000000')
        if cargo.cargo_type=='PARCEL':
            volumetric=volume*Decimal('200')
            floor=Decimal(0)
            ldm=Decimal(0)
        else:
            factors=[strict_decimal(v) for v in (kg_per_m3,kg_per_loading_metre,deck_width_m)]
            if any(v<=0 for v in factors):
                raise ValueError('Freight tariff factors must be positive')
            volumetric=volume*factors[0]
            ldm=(cargo.length_cm/100)*(cargo.width_cm/100)/factors[2]
            floor=Decimal(0) if cargo.stackable else ldm*factors[1]
        charged=max(actual,volumetric,floor).quantize(Decimal('.001'),rounding=ROUND_CEILING)
        return {'cargo_type':cargo.cargo_type,'actual_weight_kg':str(actual),'volume_m3':str(volume),
                'volumetric_weight_kg':str(volumetric),'loading_metres':str(ldm),'floor_weight_kg':str(floor),
                'billable_weight_kg':str(charged),'basis':'actual' if charged==actual else 'floor' if floor>=volumetric and floor>=actual else 'volumetric',
                'tariff_profile':'EXPRESS_5000' if cargo.cargo_type=='PARCEL' else 'CONFIGURED_ROAD_FREIGHT',
                'kg_per_m3':str(kg_per_m3),'kg_per_loading_metre':str(kg_per_loading_metre),'deck_width_m':str(deck_width_m)}


class Goods(StrictInput):
    description: str = Field(min_length=3,max_length=500)
    quantity: int = Field(strict=True,ge=1,le=10000)
    unit_value: Decimal = Field(gt=0,le=1000000,decimal_places=2)
    unit_weight_kg: Decimal = Field(gt=0,le=30000,decimal_places=3)
    origin_country: str
    hs_code: str | None = Field(default=None,pattern=r'^\d{6}(?:\d{2})?(?:\d{2})?$')

    @field_validator('unit_value','unit_weight_kg',mode='before')
    @classmethod
    def decimals(cls,value): return strict_decimal(value)
    @field_validator('origin_country')
    @classmethod
    def origin(cls,value): return country_code(value)


class Order(StrictInput):
    idempotency_key: UUID
    order_reference: str = Field(min_length=1,max_length=100)
    platform: Literal['SHOPIFY','WOOCOMMERCE','AMAZON','MANUAL'] = 'MANUAL'
    store_id: UUID | None = None
    store_order_id: str | None = Field(default=None,min_length=1,max_length=150)
    origin: dict
    destination: dict
    cargo: Cargo
    currency: Literal['GBP','EUR','USD'] = 'GBP'
    items: list[Goods] = Field(default_factory=list,max_length=100)
    sender_eori: str | None = Field(default=None,max_length=40)
    recipient_eori: str | None = Field(default=None,max_length=40)
    sender_vat: str | None = Field(default=None,max_length=40)
    recipient_vat: str | None = Field(default=None,max_length=40)
    customs_signer: str | None = Field(default=None,min_length=1,max_length=200)
    hs_codes_reviewed: bool = False
    postal_form: Literal['CN22','CN23'] | None = None
    customs_required_override: bool = False
    incoterm: Literal['DAP','DDP','FCA','EXW'] = 'DAP'
    is_return: bool = False
    return_of_shipment_id: UUID | None = None
    original_invoice_number: str | None = Field(default=None, max_length=40)
    return_data: dict | None = None

    @model_validator(mode='after')
    def store_pair(self):
        if bool(self.is_return)!=bool(self.return_of_shipment_id):
            raise ValueError('Returns require an original shipment reference')
        for party in [self.origin,self.destination]:
            if 'country_code' in party:
                party['country_code']=country_code(party['country_code'])
        if bool(self.store_id)!=bool(self.store_order_id):
            raise ValueError('Store UUID and order ID must be provided together')
        return self


def customs_matrix(shipment_id: UUID, order: Order, tenant: dict) -> dict:
    origin=country_code(order.origin['country_code']);destination=country_code(order.destination['country_code'])
    required=order.customs_required_override or (origin!=destination and not {origin,destination}<=EU_CUSTOMS_AREA)
    if not required:
        return {'required':False,'reason':'Domestic or common EU customs area; special territories require an explicit override','print_documents':[]}
    if not order.items:
        raise HTTPException(422,'Cross-border goods require item descriptions, values, origins and weights')
    items=[];value=Decimal(0);weight=Decimal(0);ready=bool(order.customs_signer and order.hs_codes_reviewed)
    with localcontext() as ctx:
        ctx.prec=50
        for item in order.items:
            prediction=predict_hs_code(item.description) if item.hs_code is None else None
            code=item.hs_code or (prediction or {}).get('hs_code')
            if not code:
                ready=False
            line_value=item.unit_value*item.quantity;line_weight=item.unit_weight_kg*item.quantity
            value+=line_value;weight+=line_weight
            items.append({**item.model_dump(mode='json'),'hs_code':code,'hs_prediction':prediction,
                          'line_value':format(line_value,'.2f'),'line_weight_kg':str(line_weight)})
        if weight>order.cargo.actual_weight_kg:
            raise HTTPException(422,'Goods net weight exceeds cargo gross weight')
    return {'required':True,'shipment_id':str(shipment_id),'document_type':'COMMERCIAL_INVOICE',
            'invoice_number':order.original_invoice_number or str(shipment_id),
            'export_reason':'returned_goods' if order.is_return else 'commercial_goods',
            'return_data':order.return_data,
            'postal_form':order.postal_form,'status':'prepared' if ready else 'requires_customs_data',
            'ready_for_provider':ready,'currency':order.currency,'incoterm':order.incoterm,
            'sender':{**order.origin,'eori':order.sender_eori or (None if order.is_return else tenant.get('eori_number')),
                      'vat_registration':order.sender_vat or (None if order.is_return else tenant.get('vat_registration_number'))},
            'recipient':{**order.destination,'eori':order.recipient_eori,'vat_registration':order.recipient_vat},
            'items':items,'totals':{'goods_value':format(value,'.2f'),'net_weight_kg':str(weight),'gross_weight_kg':str(order.cargo.actual_weight_kg)},
            'declaration_statement':'I certify that the particulars given in this declaration are correct and that this consignment does not contain dangerous or prohibited goods.',
            'signer':order.customs_signer,'print_documents':['COMMERCIAL_INVOICE']+([order.postal_form] if order.postal_form else []),
            'hs_notice':'Predictions are simulated suggestions; postal eligibility, territory exceptions and national tariff requirements must be verified.'}


@contextmanager
def customs_scope(service,tenant_id):
    token=_scope.set((service,tenant_id))
    try: yield
    finally: _scope.reset(token)


async def generate_customs_declaration(shipment_id: UUID) -> dict:
    scope=_scope.get()
    if scope is None:
        raise HTTPException(403,'Use an authenticated tenant customs scope')
    service,tenant_id=scope
    async with service.pool.acquire() as connection:
        row=await connection.fetchrow('SELECT * FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant_id,shipment_id)
        tenant=await connection.fetchrow('SELECT eori_number,vat_registration_number FROM public.tenants WHERE tenant_id=$1',tenant_id)
    if row is None or tenant is None:
        raise HTTPException(404,'Shipment not found')
    metadata=json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'],str) else row['logistics_metadata']
    if 'automation_order' in metadata:
        order=Order.model_validate(metadata['automation_order'])
    else:
        def decode(value): return json.loads(value) if isinstance(value,str) else value
        items=decode(row['customs_items'])
        try:
            order=Order.model_validate({'idempotency_key':row['idempotency_key'],'order_reference':row['customer_reference'] or str(shipment_id),
                'origin':decode(row['sender_address']),'destination':decode(row['recipient_address']),'currency':row['currency'],
                'cargo':{'cargo_type':row['cargo_type'],'actual_weight_kg':row['parcel_weight_kg'],'length_cm':row['parcel_length_cm'],
                         'width_cm':row['parcel_width_cm'],'height_cm':row['parcel_height_cm']},
                'items':[{**{k:item[k] for k in ['description','quantity','unit_value','origin_country']},
                          'hs_code':item.get('hs_code'),'unit_weight_kg':item.get('unit_weight_kg',item.get('unit_net_weight_kg'))} for item in items],
                'customs_signer':metadata.get('customs_signer'),'hs_codes_reviewed':metadata.get('hs_codes_reviewed',False)})
        except (ValueError,KeyError,TypeError):
            raise HTTPException(422,'Stored shipment customs items require complete unit values, origins and weights') from None
    return customs_matrix(shipment_id,order,dict(tenant))


class PurchaseUncertain(Exception): pass
class PurchaseRejected(Exception): pass


class EasyPostPurchase:
    """Use the already-rated immutable shipment; never retry an ambiguous buy."""
    def __init__(self,client): self.client=client
    async def request(self,account,path,method='GET',body=None):
        try:
            response=await self.client.request(method,account.base_url+path,auth=httpx.BasicAuth(account.api_key,''),json=body,timeout=30,follow_redirects=False)
        except httpx.HTTPError:
            raise PurchaseUncertain() from None
        if response.status_code in {400,401,403,404,422} and method=='POST':
            raise PurchaseRejected()
        if not 200<=response.status_code<300 or len(response.content)>2000000:
            raise PurchaseUncertain()
        try: return response.json()
        except ValueError: raise PurchaseUncertain() from None
    async def buy(self,account,rate):
        body=await self.request(account,'/shipments/'+quote(rate.upstream_shipment_id,safe='')+'/buy','POST',{'rate':{'id':rate.upstream_rate_id}})
        return self.label(body,rate)
    async def reconcile(self,account,rate):
        body=await self.request(account,'/shipments/'+quote(rate.upstream_shipment_id,safe=''))
        return self.label(body,rate)
    def label(self,body,rate):
        try:
            url=body['postage_label'].get('label_pdf_url') or body['postage_label']['label_url']; tracking=body['tracking_code']
            if body.get('id')!=rate.upstream_shipment_id or body.get('selected_rate',{}).get('id')!=rate.upstream_rate_id:
                raise ValueError()
            if body.get('mode')!='production':
                raise ValueError()
            parsed=urlsplit(url)
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or not isinstance(tracking,str) or not tracking.strip():
                raise ValueError()
            forms=[]
            for form in body.get('forms',[]):
                link=form.get('form_url')
                if isinstance(link,str) and urlsplit(link).scheme=='https':
                    forms.append({'document_type':form.get('form_type','CUSTOMS_FORM'),'url':link})
            return {'tracking_number':tracking,'label_url':url,'carrier_forms':forms}
        except (KeyError,TypeError,ValueError):
            raise PurchaseUncertain() from None


class AutomationService:
    def __init__(self,pool,rating,finance,repository,rating_model,http_client,settings):
        self.pool,self.rating,self.finance,self.repository=pool,rating,finance,repository
        self.rating_model,self.settings=rating_model,settings
        self.adapters={'EASYPOST':EasyPostPurchase(http_client)}
        self.order_limiter=asyncio.Semaphore(min(4,max(1,settings.db_pool_max_size//2-1)))
    def register_purchase_adapter(self,provider,adapter):
        if provider not in {'REGIONAL','EASYPOST'} or not callable(getattr(adapter,'buy',None)) or not callable(getattr(adapter,'reconcile',None)):
            raise ValueError('Provider adapter must implement async buy and reconcile')
        self.adapters[provider]=adapter

    async def reconcile(self,context,shipment_id):
        if context.role not in {'OWNER','ADMIN','DISPATCHER'}:
            raise HTTPException(403,'Dispatch permission required')
        from main import BookingPermit,ClientRate
        async with self.pool.acquire() as connection:
            row=await connection.fetchrow('SELECT status,tracking_number,label_storage_path,pricing_snapshot,logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2',context.tenant_id,shipment_id)
            reservation=await connection.fetchrow('SELECT id,status,amount,currency,billing_plan FROM public.wallet_reservations WHERE tenant_id=$1 AND shipment_id=$2',context.tenant_id,shipment_id)
        if row is None or reservation is None: raise HTTPException(404,'Booking not found')
        if row['status']=='BOOKED':
            return {'status':'BOOKED','label':{'tracking_number':row['tracking_number'],'label_url':row['label_storage_path']}}
        permit=BookingPermit(context.tenant_id,shipment_id,reservation['id'],reservation['amount'],reservation['currency'],reservation['billing_plan'])
        if reservation['status']=='RESERVED':
            await self.finance.finish_booking(permit,'NOT_SUBMITTED')
            return {'status':'FAILED','reservation_released':True,'provider_called':False}
        if reservation['status']!='SUBMITTED': raise HTTPException(409,'Booking already finalized')
        snapshot=json.loads(row['pricing_snapshot']) if isinstance(row['pricing_snapshot'],str) else row['pricing_snapshot']
        rate=ClientRate.model_validate(snapshot.get('selected_rate',snapshot))
        accounts=await self.repository.accounts(context)
        account=next((a for a in accounts if a.id==rate.account_id),None)
        adapter=self.adapters.get(rate.provider)
        if account is None or adapter is None: raise HTTPException(503,'Purchase reconciliation adapter unavailable')
        try: label=await adapter.reconcile(account,rate)
        except (PurchaseUncertain,PurchaseRejected):
            raise HTTPException(409,'Purchase remains uncertain; reservation retained') from None
        await self.finance.finish_booking(permit,'SUCCESS',tracking_number=label['tracking_number'],label_storage_path=label['label_url'],carrier_name=rate.carrier_code,label_documents=label)
        metadata=json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'],str) else row['logistics_metadata']
        return {'status':'BOOKED','label':label,'customs':metadata.get('automation_customs'),'purchase_retried':False}

    async def fail_ticket(self,tenant_id,key,reference,shipment_id,code):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                failure_id=await connection.fetchval("""INSERT INTO public.automation_failures
                    (tenant_id,idempotency_key,order_reference,shipment_id,error_code)
                    VALUES($1,$2,$3,$4,$5) ON CONFLICT(tenant_id,idempotency_key) DO UPDATE SET error_code=$5 RETURNING id""",tenant_id,key,reference[:100],shipment_id,code)
                await connection.execute("""INSERT INTO public.support_tickets
                    (tenant_id,shipment_id,automation_failure_id,status,ai_summary,ai_method,prompt_version)
                    VALUES($1,$2,$3,'OPEN',$4,'DETERMINISTIC_MOCK','bulk-remediation-v1')
                    ON CONFLICT(automation_failure_id) DO UPDATE SET ai_summary=$4,status='OPEN'""",tenant_id,shipment_id,failure_id,
                    'Bulk order needs attention: '+code+'. Verify its address, packing, customs data, carrier configuration and wallet availability before retrying.')

    async def process(self,context,raw,mode,*,private_quote=None):
        shipment_id=None; permit=None;submitted=False;order=None
        reference=str(raw.get('order_reference','Invalid order'))[:100] if isinstance(raw,dict) else 'Invalid order'
        failure_key=uuid5(NAMESPACE_URL,str(context.tenant_id)+':'+hashlib.sha256(json.dumps(raw,sort_keys=True,default=str).encode()).hexdigest())
        try:
            order=Order.model_validate(raw);failure_key=order.idempotency_key
            request=self.rating_model.model_validate({'origin':order.origin,'destination':order.destination,'currency':order.currency,
                'cargo_type':order.cargo.cargo_type,'stackable':order.cargo.stackable,'weights_kg':[str(order.cargo.actual_weight_kg)],
                'dimensions':[] if order.cargo.cargo_type=='LETTER' else [{'length_cm':str(order.cargo.length_cm),'width_cm':str(order.cargo.width_cm),'height_cm':str(order.cargo.height_cm)}],
                'is_return':order.is_return})
            fingerprint=hashlib.sha256(order.model_dump_json().encode()).hexdigest()
            # Dedicated session lock prevents duplicate purchases across batches.
            async with self.pool.acquire() as lock:
                lock_key=f'automation:{context.tenant_id}:{order.idempotency_key}'
                if not await lock.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))',lock_key):
                    raise HTTPException(409,'ORDER_PROCESSING')
                try:
                    existing=await lock.fetchrow('SELECT id,status,logistics_metadata,tracking_number,label_storage_path,ecommerce_store_id,store_order_id FROM public.shipments WHERE tenant_id=$1 AND idempotency_key=$2',context.tenant_id,order.idempotency_key)
                    if existing:
                        shipment_id=existing['id'];metadata=json.loads(existing['logistics_metadata']) if isinstance(existing['logistics_metadata'],str) else existing['logistics_metadata']
                        imported=existing['status']=='PENDING_IMPORT'
                        if imported and (existing['ecommerce_store_id']!=order.store_id or existing['store_order_id']!=order.store_order_id):
                            raise HTTPException(409,'IMPORTED_STORE_IDENTITY_MISMATCH')
                        if not imported and metadata.get('automation_fingerprint')!=fingerprint:
                            raise HTTPException(409,'IDEMPOTENCY_CONFLICT')
                        if existing['status']=='BOOKED':
                            label=metadata.get('automation_label') or {'tracking_number':existing['tracking_number'],'label_url':existing['label_storage_path']}
                            return {'order_reference':reference,'shipment_id':str(shipment_id),'status':'BOOKED','replayed':True,'label':label,'customs':metadata.get('automation_customs'),
                                    'print_bundle':{'shipping_label':label['label_url'],'carrier_documents':label.get('carrier_forms',[]),'customs_metadata':metadata.get('automation_customs'),'printer_broadcast':False}}
                        if existing['status']=='BOOKING':
                            raise HTTPException(409,'BOOKING_RECONCILIATION_REQUIRED')
                        if existing['status'] not in {'DRAFT','QUOTED','PENDING_IMPORT'}:
                            raise HTTPException(409,'ORDER_REQUIRES_MANUAL_RECONCILIATION')
                    tenant=await lock.fetchrow('SELECT * FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
                    if tenant is None or tenant['workspace_status']!='ACTIVE' or tenant['billing_status']!='ACTIVE':
                        raise HTTPException(403,'ACCOUNT_INACTIVE')
                    return_account_id=None
                    if order.is_return:
                        from backend.carrier_access import verified_return_parent
                        return_account_id=await verified_return_parent(lock,context.tenant_id,order.return_of_shipment_id,order.origin,order.destination)
                    if mode=='FULFILL':
                        if tenant['is_sandbox'] or self.settings.provider_environment!='LIVE' or getattr(self.settings,'database_environment','LIVE')!='LIVE' or not getattr(self.settings,'automation_purchase_enabled',False):
                            raise HTTPException(403,'PURCHASE_DISABLED_FOR_THIS_ENVIRONMENT')
                        if tenant['billing_plan']=='PREPAID_WALLET':
                            wallet=await lock.fetchrow('SELECT currency,balance,reserved_balance FROM public.wallets WHERE tenant_id=$1',context.tenant_id)
                            from backend.sandbox_hooks import require_prepaid_funds
                            require_prepaid_funds(wallet,Decimal('.01'),order.currency)
                    accounts=await self.repository.accounts(context,historical_account_id=return_account_id) if return_account_id else await self.repository.accounts(context)
                    if not accounts: raise HTTPException(503,'NO_CARRIER_ACCOUNTS')
                    user_id=await lock.fetchval('SELECT id FROM public.users WHERE tenant_id=$1 AND auth_user_id=$2 AND is_active',context.tenant_id,context.user_id)
                    if user_id is None: raise HTTPException(403,'ACTIVE_MEMBER_REQUIRED')
                    if order.store_id:
                        store=await lock.fetchrow('SELECT platform FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2 AND is_active',context.tenant_id,order.store_id)
                        if store is None or store['platform']!=order.platform: raise HTTPException(404,'STORE_NOT_FOUND')
                    shipment_id=shipment_id or uuid4()
                    declaration=customs_matrix(shipment_id,order,dict(tenant))
                    if declaration['required']:
                        if not declaration['ready_for_provider']: raise HTTPException(422,'CUSTOMS_DATA_REQUIRES_REVIEW')
                        if order.currency!='USD' and any(a.provider=='EASYPOST' for a in accounts):
                            # EasyPost CustomsItem values are USD. Never pretend
                            # GBP/EUR are USD; regional providers retain currency.
                            accounts=[a for a in accounts if a.provider!='EASYPOST']
                            if not accounts: raise HTTPException(422,'EASYPOST_CUSTOMS_REQUIRES_USD_VALUES')
                        request=request.model_copy(update={'customs_document':declaration})
                    dims=request.dimensions[0] if request.dimensions else None
                    metadata={'automation_order':order.model_dump(mode='json'),'automation_fingerprint':fingerprint,'automation_customs':declaration}
                    await lock.execute("""INSERT INTO public.shipments
                        (id,tenant_id,created_by_user_id,carrier_account_id,idempotency_key,customer_reference,status,
                         origin_country,destination_country,sender_address,recipient_address,parcel_weight_kg,
                         parcel_length_cm,parcel_width_cm,parcel_height_cm,currency,wholesale_cost,profit_markup,
                         pricing_snapshot,quoted_at,quote_expires_at,logistics_metadata,customs_required,customs_items,ai_hs_suggestions,
                         ecommerce_store_id,store_order_id,cargo_type,customs_content_type,customs_incoterm,
                         customs_reviewed_by_user_id,customs_reviewed_at,ai_hs_status)
                        VALUES($1,$2,$3,$4,$5,$6,'DRAFT',$7,$8,$9::jsonb,$10::jsonb,$11,$12,$13,$14,$15,0,0,
                          jsonb_build_object('markup_type','MANUAL','markup_value','0','currency',$15::text),now(),now()+interval '15 minutes',
                          $16::jsonb,$17,$18::jsonb,'[]',$19,$20,$21,
                          CASE WHEN $17 THEN 'MERCHANDISE' END,CASE WHEN $17 THEN $22::text END,
                          CASE WHEN $17 THEN $3::uuid END,CASE WHEN $17 THEN now() END,
                          CASE WHEN $17 THEN 'REVIEWED' ELSE 'NOT_REQUESTED' END)
                        ON CONFLICT(tenant_id,idempotency_key) DO UPDATE SET
                          status=EXCLUDED.status,created_by_user_id=EXCLUDED.created_by_user_id,
                          carrier_account_id=EXCLUDED.carrier_account_id,customer_reference=EXCLUDED.customer_reference,
                          origin_country=EXCLUDED.origin_country,destination_country=EXCLUDED.destination_country,
                          sender_address=EXCLUDED.sender_address,recipient_address=EXCLUDED.recipient_address,
                          parcel_weight_kg=EXCLUDED.parcel_weight_kg,parcel_length_cm=EXCLUDED.parcel_length_cm,
                          parcel_width_cm=EXCLUDED.parcel_width_cm,parcel_height_cm=EXCLUDED.parcel_height_cm,
                          currency=EXCLUDED.currency,pricing_snapshot=EXCLUDED.pricing_snapshot,
                          quoted_at=EXCLUDED.quoted_at,quote_expires_at=EXCLUDED.quote_expires_at,
                          logistics_metadata=public.shipments.logistics_metadata||EXCLUDED.logistics_metadata,
                          customs_required=EXCLUDED.customs_required,customs_items=EXCLUDED.customs_items,
                          cargo_type=EXCLUDED.cargo_type,customs_content_type=EXCLUDED.customs_content_type,
                          customs_incoterm=EXCLUDED.customs_incoterm,customs_reviewed_by_user_id=EXCLUDED.customs_reviewed_by_user_id,
                          customs_reviewed_at=EXCLUDED.customs_reviewed_at,ai_hs_status=EXCLUDED.ai_hs_status
                        WHERE public.shipments.status='PENDING_IMPORT'""",shipment_id,context.tenant_id,user_id,accounts[0].id,order.idempotency_key,reference,
                        request.origin.country_code,request.destination.country_code,request.origin.model_dump_json(),request.destination.model_dump_json(),order.cargo.actual_weight_kg,
                        dims.length_cm if dims else None,dims.width_cm if dims else None,dims.height_cm if dims else None,order.currency,json.dumps(metadata),declaration['required'],json.dumps(declaration.get('items',[])),order.store_id,order.store_order_id,order.cargo.cargo_type,order.incoterm)
                    quote_result=private_quote if private_quote is not None else (await self.rating.quote(context,request,return_of_shipment_id=order.return_of_shipment_id) if order.is_return else await self.rating.quote(context,request))
                    if mode=='FULFILL' and getattr(quote_result,'partial',False):
                        raise HTTPException(503,'PARTIAL_RATE_RESULTS_REQUIRE_RETRY')
                    rate=min(quote_result.rates,key=lambda r:(r.client_price_ex_tax,r.provider,str(r.account_id),r.upstream_rate_id))
                    wholesale=strict_decimal(rate.fee_breakdown['wholesale_total']);markup=rate.client_price_ex_tax-wholesale
                    snapshot=json.dumps({'markup_type':'MANUAL','markup_value':format(markup,'.2f'),'currency':order.currency,'selected_rate':rate.model_dump(mode='json')})
                    await lock.execute("""UPDATE public.shipments SET status='QUOTED',carrier_account_id=$3,wholesale_cost=$4,profit_markup=$5,
                        tax_amount=0,pricing_snapshot=$6::jsonb,quoted_at=$7,quote_expires_at=$8,
                        logistics_metadata=logistics_metadata-'invoice_baseline',
                        carrier_code=$9,service_code=$10,upstream_shipment_id=$11,upstream_rate_id=$12 WHERE tenant_id=$1 AND id=$2""",
                        context.tenant_id,shipment_id,rate.account_id,wholesale,markup,snapshot,quote_result.quoted_at,quote_result.expires_at,rate.carrier_code,rate.service_code,rate.upstream_shipment_id,rate.upstream_rate_id)
                    if rate.fee_breakdown.get('source')=='provider':
                        charge=calculate_cargo_charge(order.cargo,
                            kg_per_m3=getattr(self.settings,'freight_kg_per_m3',Decimal('333')),
                            kg_per_loading_metre=getattr(self.settings,'freight_kg_per_loading_metre',Decimal('1750')),
                            deck_width_m=getattr(self.settings,'freight_deck_width_m',Decimal('2.4')))
                        await record_invoice_baseline(lock,context.tenant_id,shipment_id,
                            {key:rate.fee_breakdown[key] for key in ('base_cost','fuel_surcharge','residential_fee','remote_area_fee')}|
                            {'currency':rate.currency,'billable_weight_kg':charge['billable_weight_kg']})
                    if mode=='QUOTE_ONLY':
                        await lock.executemany('''INSERT INTO public.partner_shipping_offers
                            (tenant_id,offer_id,shipment_id,rate_snapshot,expires_at)
                            VALUES($1,$2,$3,$4::jsonb,$5) ON CONFLICT DO NOTHING''',
                            [(context.tenant_id, option.offer_id, shipment_id, option.model_dump_json(), quote_result.expires_at)
                             for option in quote_result.rates])
                        public_rates=[r.model_dump(mode='json') for r in quote_result.rates]
                        if context.role=='DISPATCHER':
                            for public_rate in public_rates:public_rate['fee_breakdown']={'source':'financial_role_required'}
                        selected=next(r for r in public_rates if r['account_id']==str(rate.account_id) and r['upstream_rate_id']==rate.upstream_rate_id)
                        return {'order_reference':reference,'shipment_id':str(shipment_id),'status':'QUOTED','rate':selected,'all_rates':public_rates,'customs':declaration,'labels':[],
                                'partial':getattr(quote_result,'partial',False),'provider_issues':[issue.model_dump(mode='json') for issue in getattr(quote_result,'issues',[])]}
                    adapter=self.adapters.get(rate.provider)
                    if adapter is None: raise HTTPException(503,'CHEAPEST_PROVIDER_HAS_NO_PURCHASE_ADAPTER')
                    account=next((a for a in accounts if a.id==rate.account_id),None)
                    if account is None: raise HTTPException(503,'CARRIER_ACCOUNT_CHANGED')
                    if getattr(self,"native_orders",None) is not None:
                        await self.native_orders.ensure_order(context.tenant_id,shipment_id,rate.account_id)
                    permit=await self.finance.reserve(context,shipment_id)
                    await self.finance.mark_submitted(permit);submitted=True
                    try: label=await adapter.buy(account,rate)
                    except PurchaseRejected:
                        await self.finance.finish_booking(permit,'DEFINITIVE_FAILURE');submitted=False;permit=None
                        raise HTTPException(502,'PROVIDER_REJECTED_PURCHASE') from None
                    await self.finance.finish_booking(permit,'SUCCESS',tracking_number=label['tracking_number'],label_storage_path=label['label_url'],carrier_name=rate.carrier_code,label_documents=label)
                    return {'order_reference':reference,'shipment_id':str(shipment_id),'status':'BOOKED','label':label,'customs':declaration,
                            'print_bundle':{'shipping_label':label['label_url'],'carrier_documents':label.get('carrier_forms',[]),'customs_metadata':declaration,'printer_broadcast':False}}
                finally:
                    await lock.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))',lock_key)
        except Exception as exc:
            import traceback
            frames=traceback.extract_tb(exc.__traceback__)
            frame=frames[-1] if frames else None
            logger.warning('Automation operation deferred type=%s location=%s:%s constraint=%s',
                type(exc).__name__, frame.name if frame else 'unknown', frame.lineno if frame else 0,
                getattr(exc,'constraint_name',None) or 'none')
            if permit and not submitted:
                try: await self.finance.finish_booking(permit,'NOT_SUBMITTED')
                except Exception: pass
            code='INSUFFICIENT_WALLET_CREDIT' if isinstance(exc,HTTPException) and exc.status_code==402 else str(exc.detail) if isinstance(exc,HTTPException) and isinstance(exc.detail,str) else 'PURCHASE_RECONCILIATION_REQUIRED' if submitted else 'ORDER_VALIDATION_FAILED' if isinstance(exc,ValueError) else 'ORDER_SERVICE_FAILED'
            # Do not store raw payload/exception text, which may contain PII or keys.
            safe_code=code if re_safe(code) else 'ORDER_SERVICE_FAILED'
            ticket_recorded=False
            try:
                if shipment_id:
                    async with self.pool.acquire() as connection:
                        if not await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.shipments WHERE tenant_id=$1 AND id=$2)',context.tenant_id,shipment_id):
                            shipment_id=None
                await self.fail_ticket(context.tenant_id,failure_key,reference,shipment_id,safe_code)
                ticket_recorded=True
            except Exception:
                logger.warning('Automation failure ticket persistence deferred: %s',safe_code)
            return {'order_reference':reference,'shipment_id':str(shipment_id) if shipment_id else None,'status':'RECONCILIATION_REQUIRED' if submitted or safe_code=='BOOKING_RECONCILIATION_REQUIRED' else 'FAILED','error':safe_code,'support_ticket_recorded':ticket_recorded}


def re_safe(value):
    return len(value)<=100 and all(c.isupper() or c.isdigit() or c=='_' for c in value)


def build_router(authenticate):
    router=APIRouter(prefix='/api/v1/automation',tags=['Automation and freight'])
    @router.post('/cargo-weight')
    async def cargo_weight(cargo:Cargo,request:Request,context:Any=Depends(authenticate)):
        settings=request.app.state.settings
        return calculate_cargo_charge(cargo,kg_per_m3=settings.freight_kg_per_m3,kg_per_loading_metre=settings.freight_kg_per_loading_metre,deck_width_m=settings.freight_deck_width_m)
    @router.get('/customs/{shipment_id}')
    async def customs(shipment_id:UUID,request:Request,context:Any=Depends(authenticate)):
        with customs_scope(request.app.state.automation_freight,context.tenant_id):
            return await generate_customs_declaration(shipment_id)
    @router.post('/orders/{shipment_id}/reconcile')
    async def reconcile(shipment_id:UUID,request:Request,context:Any=Depends(authenticate)):
        return await request.app.state.automation_freight.reconcile(context,shipment_id)
    @router.post('/bulk-fulfill')
    async def bulk(request:Request,background_tasks:BackgroundTasks,context:Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','DISPATCHER'}: raise HTTPException(403,'Dispatch permission required')
        if request.headers.get('content-type','').split(';',1)[0]!='application/json': raise HTTPException(415,'Use application/json')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>5000000: raise HTTPException(413,'Batch exceeds 5 MB')
        try: data=json.loads(raw,parse_float=Decimal)
        except (ValueError,UnicodeError): raise HTTPException(422,'Invalid JSON') from None
        mode=request.query_params.get('mode','QUOTE_ONLY')
        if mode not in {'QUOTE_ONLY','FULFILL'} or not isinstance(data,list) or not 1<=len(data)<=100:
            raise HTTPException(422,'Supply 1–100 normalized orders and mode QUOTE_ONLY or FULFILL')
        service=request.app.state.automation_freight
        limiter=getattr(service,'order_limiter',None) or asyncio.Semaphore(min(4,max(1,service.settings.db_pool_max_size//2-1)))
        async def run(order):
            async with limiter: return await service.process(context,order,mode)
        results=await asyncio.gather(*(run(order) for order in data))
        if any(r['status']=='BOOKED' for r in results) and getattr(request.app.state,'hubspot',None) is not None:
            from backend.hubspot_crm import sync_tenant_metrics_to_crm
            background_tasks.add_task(sync_tenant_metrics_to_crm,context.tenant_id)
        return {'mode':mode,'total':len(results),'booked':sum(r['status']=='BOOKED' for r in results),'quoted':sum(r['status']=='QUOTED' for r in results),
                'failed':sum(r['status'] in {'FAILED','RECONCILIATION_REQUIRED'} for r in results),'results':results,
                'labels':[r['label'] for r in results if r.get('label')]}
    return router
