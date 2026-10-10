"""Versioned CSV orders, tenant-scoped persistence and customs review.

The standard layout contains exactly the requested columns. Optional columns
carry facts that cannot be inferred from a shipping address or gross weight.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import asyncpg
from fastapi import HTTPException
from pydantic import Field, ValidationError, field_validator
from backend.ai_engine import StrictModel, country_code, predict_hs_code, strict_decimal
from backend.automation_freight_engine import Cargo, Goods, Order, EU_CUSTOMS_AREA, calculate_cargo_charge, customs_matrix

CSV_FIELDS = ('order_reference','cargo_type','origin_name','origin_line1','origin_city','origin_postal_code',
    'origin_country_code','recipient_name','recipient_phone','destination_name','destination_line1',
    'destination_city','destination_postal_code','destination_country_code','length_cm','width_cm','height_cm',
    'weight_kg','currency','item_description','item_declared_value')
LEGACY_CSV_FIELDS = tuple(field for field in CSV_FIELDS if field not in
    {'cargo_type','recipient_name','recipient_phone','item_description','item_declared_value'})
OPTIONAL_CSV_FIELDS = ('stackable','origin_state','destination_state','item_quantity','item_origin_country',
    'item_net_weight_kg','hs_code','hs_codes_reviewed','customs_signer','postal_form','incoterm',
    'sender_eori','recipient_eori','sender_vat','recipient_vat','store_id','store_order_id','platform','idempotency_key')
MAX_BATCH_BYTES = 5_000_000
MAX_BATCH_ROWS = 1000
logger=logging.getLogger('veloce.csv')


def boolean(value: str, default=False):
    if not value: return default
    if value.lower() not in {'true','false'}: raise ValueError('Use true or false')
    return value.lower()=='true'


def template(extended=False):
    examples = [
        ['CSV-PARCEL-001','PARCEL','Example Warehouse','10 Example Street','London','SW1A 1AA','GB',
         'Alex Example','+447700900001','Example Customer','20 Example Road','Manchester','M1 1AA','GB',
         '40','30','20','2.500','GBP','Cotton T-shirt','25.00'],
        ['CSV-LETTER-001','LETTER','Example Warehouse','10 Example Street','London','SW1A 1AA','GB',
         'Alex Example','+447700900001','Example Customer','20 Example Road','Manchester','M1 1AA','GB',
         '','','','0.100','GBP','Business documents','0.00'],
        ['CSV-PALLET-001','PALLET','Example Warehouse','10 Example Street','London','SW1A 1AA','GB',
         'Alex Example','+447700900001','Example Factory','20 Example Road','Manchester','M1 1AA','GB',
         '120','80','100','150.000','GBP','Industrial machine components','500.00'],
        ['CSV-INTERNATIONAL-001','PARCEL','Example Warehouse','10 Example Street','London','SW1A 1AA','GB',
         'Alex Example','+12025550123','Example Customer','20 Example Avenue','New York','10001','US',
         '40','30','20','2.500','USD','Cotton T-shirt','25.00'],
    ]
    columns=list(CSV_FIELDS)
    if extended:
        columns.extend(OPTIONAL_CSV_FIELDS)
        for row in examples:
            values={'stackable':'false' if row[1]=='PALLET' else 'true','platform':'MANUAL'}
            if row[0]=='CSV-INTERNATIONAL-001':
                values.update(destination_state='NY',item_quantity='1',item_origin_country='GB',
                    item_net_weight_kg='2.000',hs_code='610910',hs_codes_reviewed='false',postal_form='CN23',incoterm='DAP')
            row.extend(values.get(field,'') for field in OPTIONAL_CSV_FIELDS)
    return {'version':'2','columns':columns,'examples':examples,'optional_columns':list(OPTIONAL_CSV_FIELDS),
        'notice':'Examples only: replace every sample row. Each row is one packed order and one goods description. Upload saves and quotes; no payment or label purchase. International goods require review.'}


def parse_batch_csv(raw: bytes, rating_model: Any, settings=None) -> list[dict]:
    if len(raw)>MAX_BATCH_BYTES: raise ValueError('CSV is limited to 5 MB')
    try:
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''),strict=True)
        fields=reader.fieldnames or []
        legacy=set(fields)==set(LEGACY_CSV_FIELDS)
        if len(fields)!=len(set(fields)) or not fields or (not legacy and
            (not set(CSV_FIELDS)<=set(fields) or not set(fields)<=set(CSV_FIELDS+OPTIONAL_CSV_FIELDS))):
            raise ValueError('CSV headers must include: '+','.join(CSV_FIELDS)+'; use the downloaded extended template for optional fields')
        rows=[];references=set()
        for position,data in enumerate(reader,2):
            if len(rows)>=MAX_BATCH_ROWS:raise ValueError('CSV is limited to 1000 orders')
            result={'row':position,'order_reference':''}
            if None in data or any(value is None for value in data.values()):
                rows.append(result|{'error':'Wrong number of columns'});continue
            data={key:value.strip() for key,value in data.items()}
            reference=data['order_reference'];result['order_reference']=reference
            if not re.fullmatch(r'[A-Za-z0-9 #_./-]{1,100}',reference) or reference in references:
                rows.append(result|{'error':'Invalid or duplicate order reference'});continue
            references.add(reference)
            try:
                kind=data.get('cargo_type','PARCEL').upper()
                contact=data.get('recipient_name') or data['destination_name']
                phone=data.get('recipient_phone','')
                # Undo only the safe Excel text prefix for a valid E.164 phone.
                if re.fullmatch(r"'\+[1-9][0-9]{7,14}",phone):phone=phone[1:]
                payload={prefix:{field: data[f'{prefix}_{field}'] for field in
                    ('name','line1','city','postal_code','country_code')} for prefix in ('origin','destination')}
                for prefix in ('origin','destination'):
                    payload[prefix]['country_code']=country_code(payload[prefix]['country_code'])
                    if data.get(prefix+'_state'):payload[prefix]['state']=data[prefix+'_state']
                payload['destination']['name']=contact
                if data['destination_name']!=contact:payload['destination']['company']=data['destination_name']
                if phone:payload['destination']['phone']=phone
                cargo=Cargo(cargo_type=kind,actual_weight_kg=data['weight_kg'],
                    length_cm=None if kind=='LETTER' else data['length_cm'],
                    width_cm=None if kind=='LETTER' else data['width_cm'],
                    height_cm=None if kind=='LETTER' else data['height_cm'],
                    stackable=boolean(data.get('stackable',''),kind not in {'PALLET','OVERLAND_FREIGHT'}))
                cargo=cargo.model_copy(update={'actual_weight_kg':cargo.actual_weight_kg.quantize(Decimal('.001')),
                    **{field:getattr(cargo,field).quantize(Decimal('.01')) for field in ('length_cm','width_cm','height_cm') if getattr(cargo,field) is not None}})
                payload.update(cargo_type=kind,stackable=cargo.stackable,currency=data['currency'].upper(),
                    dimensions=[] if kind=='LETTER' else [{key:str(getattr(cargo,key)) for key in ('length_cm','width_cm','height_cm')}],
                    weights_kg=[str(cargo.actual_weight_kg)])
                request=rating_model.model_validate(payload)
                weight=calculate_cargo_charge(cargo,kg_per_m3=getattr(settings,'freight_kg_per_m3',Decimal('333')),
                    kg_per_loading_metre=getattr(settings,'freight_kg_per_loading_metre',Decimal('1750')),
                    deck_width_m=getattr(settings,'freight_deck_width_m',Decimal('2.4')))
                if Decimal(weight['billable_weight_kg'])>(30000 if kind in {'PALLET','OVERLAND_FREIGHT'} else 1000):
                    raise ValueError('Billable weight exceeds service limit')
                description=data.get('item_description','')
                if not legacy and (len(description)<3 or len(description)>500 or any(ord(c)<32 for c in description)):
                    raise ValueError('Enter a printable item description of 3–500 characters')
                declared=strict_decimal(data['item_declared_value']) if data.get('item_declared_value') else Decimal('0')
                if declared<0 or declared>1000000 or declared!=declared.quantize(Decimal('.01')):
                    raise ValueError('Declared value requires a nonnegative amount with at most two decimal places')
                if not legacy and not data.get('item_declared_value'):
                    raise ValueError('Enter item_declared_value, including 0.00 for documents')
                declared=declared.quantize(Decimal('.01'))
                item_quantity=data.get('item_quantity') or '1'
                if not re.fullmatch(r'[1-9][0-9]{0,4}',item_quantity):raise ValueError('Invalid item quantity')
                quantity=int(item_quantity)
                if quantity>10000:raise ValueError('Item quantity must be at most 10000')
                if data.get('item_origin_country'):country_code(data['item_origin_country'])
                if data.get('item_net_weight_kg'):
                    net=strict_decimal(data['item_net_weight_kg'])
                    if not 0<net<=cargo.actual_weight_kg or net!=net.quantize(Decimal('.001')):
                        raise ValueError('Item net weight requires positive kg with at most three decimal places, not exceeding gross weight')
                reviewed=boolean(data.get('hs_codes_reviewed',''))
                items=[]
                if description and data.get('item_origin_country') and data.get('item_net_weight_kg') and declared>0:
                    unit=declared
                    items=[Goods(description=description,quantity=quantity,unit_value=unit,
                        unit_weight_kg=str(strict_decimal(data['item_net_weight_kg']).quantize(Decimal('.001'))),origin_country=data['item_origin_country'],
                        hs_code=data.get('hs_code') or None).model_dump(mode='json')]
                if data.get('hs_code') and not re.fullmatch(r'\d{6}(?:\d{2})?(?:\d{2})?',data['hs_code']):raise ValueError('Invalid HS code')
                if data.get('store_id') or data.get('store_order_id'):
                    if not (data.get('store_id') and data.get('store_order_id')):raise ValueError('Supply store_id and store_order_id together')
                if data.get('platform') not in {'','MANUAL',None} and not data.get('store_id'):
                    raise ValueError('Marketplace orders require store_id and store_order_id')
                key=UUID(data['idempotency_key']) if data.get('idempotency_key') else uuid4()
                order=Order(idempotency_key=key,order_reference=reference,
                    origin=request.origin.model_dump(mode='json',exclude_none=True),destination=request.destination.model_dump(mode='json',exclude_none=True),
                    cargo=cargo,currency=request.currency,items=items,
                    store_id=data.get('store_id') or None,store_order_id=data.get('store_order_id') or None,
                    platform=data.get('platform') or 'MANUAL',hs_codes_reviewed=reviewed,
                    customs_signer=data.get('customs_signer') or None,postal_form=data.get('postal_form') or None,
                    incoterm=data.get('incoterm') or 'DAP',
                    **{field:data[field] for field in ('sender_eori','recipient_eori','sender_vat','recipient_vat') if data.get(field)})
                required=request.origin.country_code!=request.destination.country_code and not {request.origin.country_code,request.destination.country_code}<=EU_CUSTOMS_AREA
                missing=[]
                if required:
                    for field,valid in [('recipient_phone',bool(phone)),('item_description',bool(description)),
                        ('item_declared_value',declared>0),('item_origin_country',bool(data.get('item_origin_country'))),
                        ('item_net_weight_kg',bool(data.get('item_net_weight_kg'))),('hs_code',bool(data.get('hs_code'))),
                        ('hs_codes_reviewed',reviewed),('customs_signer',bool(order.customs_signer))]:
                        if not valid:missing.append(field)
                    missing.extend(country_state_requirements(order))
                if items and sum((item.unit_weight_kg*item.quantity for item in order.items),Decimal(0))>cargo.actual_weight_kg:
                    raise ValueError('Goods net weight exceeds gross cargo weight')
                result.update(request=request,weight=weight,order=order,explicit_key=bool(data.get('idempotency_key')),
                    customs_required=required,missing_fields=missing,source={key:value for key,value in data.items() if key!='idempotency_key'},
                    declared_value=format(declared,'.2f'),item_description=description,
                    hs_suggestion=predict_hs_code(description) if description else None)
            except (ValidationError,ValueError,ArithmeticError) as exc:
                # Pydantic errors can include submitted values; never return them.
                result['error']=('Invalid order fields: '+', '.join('.'.join(str(part) for part in error['loc']) for error in exc.errors(include_input=False))) if isinstance(exc,ValidationError) else str(exc)
            rows.append(result)
        if not rows:raise ValueError('CSV contains no orders')
        return rows
    except (UnicodeError,csv.Error):raise ValueError('Upload valid UTF-8 CSV') from None


class CSVCustomsReview(StrictModel):
    items: list[Goods]=Field(min_length=1,max_length=100)
    customs_signer: str=Field(min_length=1,max_length=200)
    hs_codes_reviewed: Literal[True]
    recipient_phone: str=Field(pattern=r'^\+[1-9][0-9]{7,14}$')
    origin_state: str | None = Field(default=None,min_length=1,max_length=100)
    destination_state: str | None = Field(default=None,min_length=1,max_length=100)
    postal_form: Literal['CN22','CN23'] | None = None
    incoterm: Literal['DAP','DDP','FCA','EXW']='DAP'
    sender_eori: str | None = Field(default=None,max_length=40)
    recipient_eori: str | None = Field(default=None,max_length=40)
    sender_vat: str | None = Field(default=None,max_length=40)
    recipient_vat: str | None = Field(default=None,max_length=40)

    @field_validator('hs_codes_reviewed',mode='before')
    @classmethod
    def explicit_review(cls,value):
        if value is not True:raise ValueError('Explicit HS review confirmation required')
        return value

    @field_validator('customs_signer')
    @classmethod
    def signer_text(cls,value):
        value=value.strip()
        if not value or any(ord(c)<32 for c in value):raise ValueError('Provide a printable customs signer')
        return value

    @field_validator('items')
    @classmethod
    def reviewed_codes(cls,items):
        if any(not item.hs_code for item in items):raise ValueError('Provide the explicitly reviewed HS code for every item')
        return items


class CSVOrderService:
    def __init__(self,pool,automation):self.pool,self.automation=pool,automation

    async def save(self,context,row):
        order=row['order']
        key=order.idempotency_key if row['explicit_key'] else uuid5(NAMESPACE_URL,f'veloce-csv-v2:{context.tenant_id}:{order.order_reference}')
        order=order.model_copy(update={'idempotency_key':key})
        canonical=order.model_dump(mode='json');source=row['source']
        import_details={'description':row['item_description'],'unit_value':row['declared_value'],
            'quantity':int(source.get('item_quantity') or '1'),'hs_code':source.get('hs_code') or None,
            'origin_country':country_code(source['item_origin_country']) if source.get('item_origin_country') else None,
            'unit_net_weight_kg':format(strict_decimal(source['item_net_weight_kg']),'.3f') if source.get('item_net_weight_kg') else None}
        digest=hashlib.sha256(json.dumps({'order':canonical,'import_details':import_details},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                tenant=await connection.fetchrow('SELECT * FROM public.tenants WHERE tenant_id=$1 AND workspace_status=\'ACTIVE\' FOR SHARE',context.tenant_id)
                member=await connection.fetchval("SELECT id FROM public.users WHERE tenant_id=$1 AND auth_user_id=$2 AND is_active AND role IN ('OWNER','ADMIN','DISPATCHER')",context.tenant_id,context.user_id)
                if not tenant or not member:raise HTTPException(403,'Active dispatch membership required')
                if order.store_id:
                    store=await connection.fetchrow('SELECT platform FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2 AND is_active FOR SHARE',context.tenant_id,order.store_id)
                    if not store or store['platform']!=order.platform:raise HTTPException(404,'Matching tenant store not found')
                await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'csv:{context.tenant_id}:{key}')
                existing=await connection.fetchrow('SELECT id,status,logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND idempotency_key=$2 FOR UPDATE',context.tenant_id,key)
                if existing:
                    metadata=json.loads(existing['logistics_metadata']) if isinstance(existing['logistics_metadata'],str) else existing['logistics_metadata']
                    if metadata.get('batch_csv',{}).get('fingerprint')!=digest:raise HTTPException(409,'Order reference/key already exists with different details')
                    return existing['id'],order,metadata,True,existing['status']
                sid=uuid4();declaration=draft_declaration(row,order,sid,dict(tenant))
                metadata={'automation_order':canonical,'automation_customs':declaration,'cargo_type':order.cargo.cargo_type,
                    'stackable':order.cargo.stackable,'destination':order.destination['country_code'],
                    'batch_csv':{'version':'2','fingerprint':digest,'source':source,'declared_value':row['declared_value'],
                        'item_description':row['item_description'],'missing_fields':row['missing_fields'],'weight':row['weight'],
                        'hs_suggestion':row['hs_suggestion']}}
                suggestions=[row['hs_suggestion']] if row['hs_suggestion'] else []
                await connection.execute('''INSERT INTO public.shipments
                    (id,tenant_id,created_by_user_id,idempotency_key,customer_reference,status,origin_country,destination_country,
                     sender_address,recipient_address,parcel_weight_kg,parcel_length_cm,parcel_width_cm,parcel_height_cm,cargo_type,
                     currency,wholesale_cost,profit_markup,pricing_snapshot,quoted_at,quote_expires_at,logistics_metadata,
                     customs_required,ai_hs_status,ai_hs_suggestions,ecommerce_store_id,store_order_id,store_import_hash)
                    VALUES($1,$2,$3,$4,$5,'PENDING_IMPORT',$6,$7,$8::jsonb,$9::jsonb,$10,$11,$12,$13,$14,$15,0,0,
                     jsonb_build_object('markup_type','MANUAL','markup_value','0.00','currency',$15::text),now()-interval '1 second',now(),
                     $16::jsonb,$17,$18,$19::jsonb,$20,$21,$22)''',sid,context.tenant_id,member,key,order.order_reference,
                    order.origin['country_code'],order.destination['country_code'],json.dumps(order.origin),json.dumps(order.destination),
                    order.cargo.actual_weight_kg,order.cargo.length_cm,order.cargo.width_cm,order.cargo.height_cm,order.cargo.cargo_type,
                    order.currency,json.dumps(metadata),row['customs_required'],'SUGGESTED' if suggestions else 'NOT_REQUESTED',json.dumps(suggestions),
                    order.store_id,order.store_order_id,digest if order.store_id else None)
                return sid,order,metadata,False,'PENDING_IMPORT'

    async def process(self,context,row):
        base={'row':row['row'],'order_reference':row['order_reference'],'cargo_type':row['order'].cargo.cargo_type}
        try:
            sid,order,metadata,replayed,status=await self.save(context,row)
            base.update(shipment_id=str(sid),saved=True,replayed=replayed,weight=row['weight'],order=order.model_dump(mode='json'),
                customs=metadata.get('automation_customs'),review=metadata.get('batch_csv'))
            if replayed and status in {'BOOKED','IN_TRANSIT','DELIVERED','EXCEPTION','BOOKING'}:
                return base|{'status':'already_processed','shipment_status':status}
            if row['missing_fields'] and status=='PENDING_IMPORT':
                return base|{'status':'customs_review_required','missing_fields':row['missing_fields']}
            if replayed and status!='PENDING_IMPORT':
                # Use the reviewed persisted order, not the original CSV draft.
                order=Order.model_validate(metadata['automation_order'])
            result=await self.automation.process(context,order.model_dump(mode='json'),'QUOTE_ONLY')
            return public_result(base,result,context)
        except HTTPException as exc:return base|{'status':'failed','error':exc.detail,'http_status':exc.status_code}
        except Exception as exc:
            logger.warning('CSV order processing failed type=%s',type(exc).__name__)
            return base|{'status':'failed','error':'Order could not be saved or quoted; verify configuration and fields'}

    async def review_and_quote(self,context,sid,review):
        async with self.pool.acquire() as connection:
            row=await connection.fetchrow("SELECT logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2 AND logistics_metadata ? 'batch_csv'",context.tenant_id,sid)
        if not row:raise HTTPException(404,'Uploaded order not found')
        metadata=json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'],str) else row['logistics_metadata']
        updates=review.model_dump(mode='json',exclude_none=True)
        updates.pop('recipient_phone')
        origin_state=updates.pop('origin_state',None)
        destination_state=updates.pop('destination_state',None)
        data=dict(metadata['automation_order']);data.update(updates)
        data['destination']={**data['destination'],'phone':review.recipient_phone}
        if destination_state:data['destination']['state']=destination_state
        if origin_state:data['origin']={**data['origin'],'state':origin_state}
        order=Order.model_validate(data)
        missing=country_state_requirements(order)
        if missing:raise HTTPException(422,'Complete '+', '.join(missing)+' before carrier rating')
        result=await self.automation.process(context,order.model_dump(mode='json'),'QUOTE_ONLY')
        return public_result({'shipment_id':str(sid),'saved':True,'order_reference':order.order_reference,'cargo_type':order.cargo.cargo_type},result,context)


def public_result(base,result,context):
    status='quoted' if result['status']=='QUOTED' else 'failed'
    output=base|{'status':status,'shipment_id':result.get('shipment_id') or base.get('shipment_id'),
        'customs':result.get('customs') or base.get('customs')}
    if status=='quoted':
        rates=[dict(rate) for rate in result.get('all_rates',[result['rate']])]
        if context.role=='DISPATCHER':
            for rate in rates:rate['fee_breakdown']={'source':'financial_role_required'}
        output['quote']={'currency':result['rate']['currency'],'rates':rates,'partial':result.get('partial',False),
            'issues':result.get('provider_issues',[])}
    else:output.update(error=result.get('error','Order could not be quoted'),support_ticket_recorded=result.get('support_ticket_recorded',False))
    return output


def country_state_requirements(order):
    return [prefix+'_state' for prefix in ('origin','destination')
        if getattr(order,prefix)['country_code'] in {'US','CA','AU'} and not getattr(order,prefix).get('state')]


def draft_declaration(row,order,sid,tenant):
    if not row['customs_required']:return {'required':False,'print_documents':[]}
    if order.items:
        doc=customs_matrix(sid,order,tenant)
        if row['missing_fields']:doc.update(status='requires_customs_data',ready_for_provider=False)
        return doc
    quantity=int(row['source'].get('item_quantity') or '1')
    return {'required':True,'shipment_id':str(sid),'document_type':'COMMERCIAL_INVOICE','status':'requires_customs_data',
        'ready_for_provider':False,'currency':order.currency,'sender':order.origin|{'eori':tenant.get('eori_number'),'vat_registration':tenant.get('vat_registration_number')},
        'recipient':order.destination,'postal_form':order.postal_form,'incoterm':order.incoterm,
        'items':[{'description':row['item_description'],'quantity':quantity,'unit_value':row['declared_value'],
            'origin_country':country_code(row['source']['item_origin_country']) if row['source'].get('item_origin_country') else None,
            'unit_weight_kg':row['source'].get('item_net_weight_kg') or None,
            'hs_code':row['source'].get('hs_code') or (row['hs_suggestion'] or {}).get('hs_code')}],
        'totals':{'goods_value':format(Decimal(row['declared_value'])*quantity,'.2f'),'gross_weight_kg':str(order.cargo.actual_weight_kg)},
        'missing_fields':row['missing_fields'],'print_documents':['COMMERCIAL_INVOICE'],
        'hs_notice':'Draft suggestions only. Goods origin, net weight, HS review and signer must be supplied; never inferred from warehouse location.'}
