"""Decimal dimensional pricing, declaration metadata and bounded CSV order imports."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, localcontext
from typing import Annotated, Any, Callable, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, ValidationError, field_validator, model_validator

from backend.ai_engine import StrictModel, amount, country_code, strict_decimal
from backend.automation_freight_engine import Cargo, Order, calculate_cargo_charge, customs_matrix
from backend.order_csv import (CSV_FIELDS, OPTIONAL_CSV_FIELDS, MAX_BATCH_BYTES, MAX_BATCH_ROWS,
    parse_batch_csv, template as csv_template, CSVCustomsReview, draft_declaration, country_state_requirements)


def calculate_billable_weight(length_cm: Any, width_cm: Any, height_cm: Any, actual_weight_kg: Any) -> dict:
    values = [strict_decimal(value) for value in (length_cm, width_cm, height_cm, actual_weight_kg)]
    if any(value <= 0 or value > 1000 for value in values):
        raise ValueError("Dimensions and weight must be greater than zero and at most 1000")
    with localcontext() as context:
        context.prec = 50
        volumetric = (values[0] * values[1] * values[2] / Decimal("5000")).quantize(Decimal("0.001"), rounding=ROUND_CEILING)
        billable = max(values[3], volumetric).quantize(Decimal("0.001"), rounding=ROUND_CEILING)
    return {"actual_weight_kg": str(values[3]), "volumetric_weight_kg": str(volumetric), "billable_weight_kg": str(billable),
            "divisor_cm3_per_kg": "5000", "basis": "volumetric" if volumetric > values[3] else "actual"}


class ParcelInput(StrictModel):
    length_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)
    width_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)
    height_cm: Decimal = Field(gt=0, le=1000, decimal_places=2)
    actual_weight_kg: Decimal = Field(gt=0, le=1000, decimal_places=3)

    @field_validator("length_cm", "width_cm", "height_cm", "actual_weight_kg", mode="before")
    @classmethod
    def decimals(cls, value):
        return strict_decimal(value)


class DeclarationParty(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    line1: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=1, max_length=30)
    country_code: str
    eori: str | None = Field(default=None, max_length=40)

    @field_validator("country_code")
    @classmethod
    def country(cls, value):
        return country_code(value)

    @field_validator("name", "line1", "city", "postal_code")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("Enter a nonblank printable address field")
        return value


class CustomsItem(StrictModel):
    description: str = Field(min_length=3, max_length=500)
    hs_code: str = Field(pattern=r"^\d{6}(?:\d{2})?(?:\d{2})?$", max_length=10)
    origin_country: str
    quantity: int = Field(gt=0, le=100000)
    unit_value: Decimal = Field(ge=0, le=1000000, decimal_places=2)
    unit_net_weight_kg: Decimal = Field(gt=0, le=30000, decimal_places=3)

    @field_validator("quantity", mode="before")
    @classmethod
    def integer_quantity(cls, value):
        if type(value) is not int:
            raise ValueError("Quantity must be an integer")
        return value

    @field_validator("unit_value", "unit_net_weight_kg", mode="before")
    @classmethod
    def decimals(cls, value):
        return strict_decimal(value)

    @field_validator("origin_country")
    @classmethod
    def country(cls, value):
        return country_code(value)


class DeclarationInput(StrictModel):
    invoice_reference: str = Field(min_length=1, max_length=100)
    form: Literal["CN22", "CN23", "COMMERCIAL_INVOICE"] = "CN23"
    sender: DeclarationParty
    recipient: DeclarationParty
    currency: Literal["GBP", "EUR", "USD"] = "GBP"
    category: Literal["SALE", "GIFT", "RETURN", "SAMPLE", "OTHER"] = "SALE"
    incoterm: Literal["DAP", "DDP", "FCA", "EXW"] = "DAP"
    items: list[CustomsItem] = Field(min_length=1, max_length=100)
    gross_weight_kg: Decimal = Field(gt=0, le=30000, decimal_places=3)
    shipping_cost: Decimal = Field(default=Decimal("0"), ge=0, le=1000000, decimal_places=2)
    hs_codes_reviewed: Literal[True]

    @field_validator("gross_weight_kg", "shipping_cost", mode="before")
    @classmethod
    def decimals(cls, value):
        return strict_decimal(value)

    @model_validator(mode="after")
    def validate_weight(self):
        net = sum((item.unit_net_weight_kg * item.quantity for item in self.items), Decimal("0"))
        if net > self.gross_weight_kg:
            raise ValueError("Gross parcel weight cannot be below total goods net weight")
        if self.sender.country_code == self.recipient.country_code:
            raise ValueError("Cross-border declaration requires different countries")
        return self


def generate_commercial_invoice(data: DeclarationInput | dict) -> dict:
    declaration = data if isinstance(data, DeclarationInput) else DeclarationInput.model_validate(data)
    goods_total = Decimal("0")
    net_total = Decimal("0")
    items = []
    for item in declaration.items:
        line_value = item.unit_value * item.quantity
        line_weight = item.unit_net_weight_kg * item.quantity
        goods_total += line_value
        net_total += line_weight
        items.append({**item.model_dump(mode="json"), "line_value": amount(line_value), "line_net_weight_kg": str(line_weight)})
    return {"schema_version": "1.0", "document_type": "COMMERCIAL_INVOICE", "postal_declaration_form": None if declaration.form == 'COMMERCIAL_INVOICE' else declaration.form,
            "invoice_reference": declaration.invoice_reference, "created_at": datetime.now(timezone.utc).isoformat(),
            "sender": declaration.sender.model_dump(mode="json"), "recipient": declaration.recipient.model_dump(mode="json"),
            "currency": declaration.currency, "category": declaration.category, "incoterm": declaration.incoterm, "items": items,
            "totals": {"goods_value": amount(goods_total), "shipping_cost": amount(declaration.shipping_cost),
                       "invoice_value": amount(goods_total + declaration.shipping_cost), "net_weight_kg": str(net_total), "gross_weight_kg": str(declaration.gross_weight_kg)},
            "print_metadata": {"format": "JSON", "templates": ["COMMERCIAL_INVOICE"] if declaration.form=='COMMERCIAL_INVOICE' else ["COMMERCIAL_INVOICE", declaration.form], "copies": 3},
            "status": "draft", "signature_required": True, "notice": "Structured print metadata only. Postal operator eligibility, national tariff codes, tax IDs and signature require verification before submission."}




def preview_rates(rating_request: Any, settings: Any = None) -> dict:
    dimensions = rating_request.dimensions[0] if rating_request.dimensions else None
    kind=getattr(rating_request,'cargo_type','PARCEL')
    weight = calculate_cargo_charge(Cargo(cargo_type=kind,actual_weight_kg=rating_request.weights_kg[0],
        length_cm=dimensions.length_cm if dimensions else None,width_cm=dimensions.width_cm if dimensions else None,
        height_cm=dimensions.height_cm if dimensions else None,stackable=getattr(rating_request,'stackable',True)),
        kg_per_m3=getattr(settings,'freight_kg_per_m3',Decimal('333')),
        kg_per_loading_metre=getattr(settings,'freight_kg_per_loading_metre',Decimal('1750')),
        deck_width_m=getattr(settings,'freight_deck_width_m',Decimal('2.4'))) if kind!='PARCEL' else calculate_billable_weight(dimensions.length_cm, dimensions.width_cm, dimensions.height_cm, rating_request.weights_kg[0])
    billable = Decimal(weight["billable_weight_kg"])
    if billable > (30000 if kind in {'PALLET','OVERLAND_FREIGHT'} else 1000):
        raise ValueError("Billable weight exceeds the cargo service limit")
    rates = []
    carriers=(("REGIONAL","Regional Freight","Road freight sample","30.00",6),) if kind in {'PALLET','OVERLAND_FREIGHT'} else (("EASYPOST", "DHL", "Express preview", "12.00", 2), ("EASYPOST", "UPS", "Standard preview", "9.50", 4), ("REGIONAL", "Regional", "Economy preview", "7.20", 6))
    for provider, carrier, service, base, days in carriers:
        base_cost = (Decimal(base) + billable * (Decimal('.08') if kind in {'PALLET','OVERLAND_FREIGHT'} else Decimal("1.25"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fuel = (base_cost * Decimal("0.12")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        residential = Decimal("0.00") if kind in {'PALLET','OVERLAND_FREIGHT'} else Decimal("1.50")
        wholesale = base_cost + fuel + residential
        markup = (wholesale * Decimal("0.20")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rates.append({"provider": provider, "account_id": str(uuid4()), "upstream_shipment_id": "PREVIEW", "upstream_rate_id": str(uuid4()),
                      "carrier_code": carrier, "service_code": service, "currency": rating_request.currency, "delivery_days": days,
                      "client_price_ex_tax": amount(wholesale + markup), "simulated": True,
                      "fee_breakdown": {"base_cost": amount(base_cost), "fuel_surcharge": amount(fuel), "residential_fee": amount(residential), "remote_area_fee": "0.00", "wholesale_total": amount(wholesale), "platform_markup": amount(markup), "source": "simulation"}})
    return {"request_id": str(uuid4()), "currency": rating_request.currency, "rates": sorted(rates, key=lambda row: Decimal(row["client_price_ex_tax"])), "issues": [], "partial": False, "weight": weight, "simulated": True}


def build_router(authenticate: Callable, rating_model: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Advanced logistics"])

    @router.post("/logistics/weight")
    async def weight(body: ParcelInput):
        return calculate_billable_weight(body.length_cm, body.width_cm, body.height_cm, body.actual_weight_kg)

    @router.post('/logistics/cargo-weight')
    async def cargo_weight(body: Cargo, request: Request):
        settings=getattr(request.app.state,'settings',None)
        return calculate_cargo_charge(body,
            kg_per_m3=getattr(settings,'freight_kg_per_m3',Decimal('333')),
            kg_per_loading_metre=getattr(settings,'freight_kg_per_loading_metre',Decimal('1750')),
            deck_width_m=getattr(settings,'freight_deck_width_m',Decimal('2.4')))

    @router.post("/customs/declaration")
    async def declaration(body: DeclarationInput):
        return generate_commercial_invoice(body)

    @router.post("/rates/preview")
    async def rates_preview(body: dict, request: Request):
        if not request.app.state.local_preview:
            raise HTTPException(404, "Preview endpoint is disabled in configured mode")
        try:
            return preview_rates(rating_model.model_validate(body),getattr(request.app.state,'settings',None))
        except (ValidationError, ValueError, ArithmeticError):
            raise HTTPException(422, "Invalid rating request") from None

    @router.post('/rates/sample')
    async def sample_rates(body: dict, request: Request):
        # Public calculator only; no tenant lookup, purchase or stored quote.
        try:return preview_rates(rating_model.model_validate(body),getattr(request.app.state,'settings',None))
        except (ValidationError,ValueError,ArithmeticError):raise HTTPException(422,'Invalid sample cargo request') from None

    @router.get('/routing/sample')
    async def sample_routing(origin: str,destination: str):
        from backend.ai_engine import evaluate_carrier_disruptions
        try:return evaluate_carrier_disruptions(origin,destination)
        except ValueError as exc:raise HTTPException(422,str(exc)) from None

    @router.get("/routing/preview")
    async def routing_preview(origin: str, destination: str, request: Request):
        if not request.app.state.local_preview:
            raise HTTPException(404, "Preview endpoint is disabled in configured mode")
        from backend.ai_engine import evaluate_carrier_disruptions
        try:
            return evaluate_carrier_disruptions(origin, destination)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post("/shipments/batch")
    async def batch(request: Request, context: Any = Depends(authenticate)):
        if context.role not in {"OWNER", "ADMIN", "DISPATCHER"}:
            raise HTTPException(403, "Dispatch permission required")
        if request.headers.get("content-type", "").split(";", 1)[0] not in {"text/csv", "application/csv"}:
            raise HTTPException(415, "Upload UTF-8 CSV with Content-Type: text/csv")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BATCH_BYTES:
                raise HTTPException(413, "CSV is limited to 5 MB")
        try:
            engine = getattr(request.app.state, 'logistics_supervisor', None)
            prepared = (await engine.ingestion.csv_headers(context, bytes(raw))
                        if engine is not None and engine.runtime.available else bytes(raw))
            rows = parse_batch_csv(prepared, rating_model, getattr(request.app.state,'settings',None))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        service = getattr(request.app.state, 'csv_orders', None)
        if service is None: raise HTTPException(503, 'CSV order persistence is not configured')
        limiter = service.automation.order_limiter
        async def process(row):
            if row.get('error'):
                return {'row':row['row'],'order_reference':row['order_reference'],'status':'invalid','error':row['error']}
            async with limiter:
                return await service.process(context,row)
        results = await asyncio.gather(*(process(row) for row in rows))
        return {'batch_id':str(uuid4()),'total':len(results),'quoted':sum(row['status']=='quoted' for row in results),
            'saved':sum(row.get('saved',False) for row in results),'review_required':sum(row['status']=='customs_review_required' for row in results),
            'results':results,'bookings_created':0}

    @router.post("/shipments/batch-preview")
    async def batch_preview(request: Request):
        if not request.app.state.local_preview:
            raise HTTPException(404, "Preview endpoint is disabled in configured mode")
        if request.headers.get("content-type", "").split(";", 1)[0] not in {"text/csv", "application/csv"}:
            raise HTTPException(415, "Upload CSV with Content-Type: text/csv")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BATCH_BYTES:
                raise HTTPException(413, "CSV is limited to 5 MB")
        try:
            rows = parse_batch_csv(bytes(raw), rating_model, getattr(request.app.state,'settings',None))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        results = []
        for row in rows:
            result = {'row':row['row'],'order_reference':row['order_reference'],'saved':False,'simulated':True}
            if row.get('error'):
                results.append(result|{'status':'invalid','error':row['error']})
                continue
            order=row['order'];doc=draft_declaration(row,order,uuid4(),{})
            result.update(cargo_type=order.cargo.cargo_type,weight=row['weight'],order=order.model_dump(mode='json'),
                customs=doc,review={'source':row['source'],'item_description':row['item_description'],
                    'declared_value':row['declared_value'],'hs_suggestion':row['hs_suggestion']})
            if row['missing_fields']:
                results.append(result|{'status':'customs_review_required','missing_fields':row['missing_fields']})
            else:
                results.append(result|{'status':'quoted','quote':preview_rates(row['request'],getattr(request.app.state,'settings',None))})
        return {'batch_id':str(uuid4()),'total':len(results),'quoted':sum(row['status']=='quoted' for row in results),
            'saved':0,'review_required':sum(row['status']=='customs_review_required' for row in results),
            'results':results,'bookings_created':0,'simulated':True}

    @router.get('/shipments/batch-template')
    async def batch_template(extended: bool=False):
        return csv_template(extended)

    @router.post('/shipments/batch-review-preview')
    async def review_preview(body: Order,request: Request):
        if not request.app.state.local_preview: raise HTTPException(404,'Preview endpoint is disabled in configured mode')
        doc=customs_matrix(uuid4(),body,{})
        if not doc.get('ready_for_provider'):raise HTTPException(422,'Complete the reviewed customs data first')
        if country_state_requirements(body):raise HTTPException(422,'Complete origin/destination state before carrier rating')
        rating=rating_model.model_validate({'origin':body.origin,'destination':body.destination,'currency':body.currency,
            'cargo_type':body.cargo.cargo_type,'stackable':body.cargo.stackable,'weights_kg':[str(body.cargo.actual_weight_kg)],
            'dimensions':[] if body.cargo.cargo_type=='LETTER' else [{k:str(getattr(body.cargo,k)) for k in ('length_cm','width_cm','height_cm')}],
            'customs_document':doc})
        return {'status':'quoted','order_reference':body.order_reference,'cargo_type':body.cargo.cargo_type,
            'quote':preview_rates(rating,getattr(request.app.state,'settings',None)),'customs':doc,'saved':False,'simulated':True}

    @router.get('/shipments/batch/{shipment_id}')
    async def uploaded_order(shipment_id: UUID,request: Request,context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','DISPATCHER'}:raise HTTPException(403,'Dispatch permission required')
        async with request.app.state.finance.pool.acquire() as connection:
            row=await connection.fetchrow("SELECT customer_reference,logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2 AND logistics_metadata ? 'batch_csv'",context.tenant_id,shipment_id)
        if not row:raise HTTPException(404,'Uploaded order not found')
        metadata=json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'],str) else row['logistics_metadata']
        return {'shipment_id':str(shipment_id),'order_reference':row['customer_reference'],'order':metadata['automation_order'],
            'review':metadata['batch_csv'],'customs':metadata.get('automation_customs')}

    @router.post('/shipments/batch/{shipment_id}/quote')
    async def review_order(shipment_id: UUID,body: CSVCustomsReview,request: Request,context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','DISPATCHER'}:raise HTTPException(403,'Dispatch permission required')
        service=getattr(request.app.state,'csv_orders',None)
        if service is None:raise HTTPException(503,'CSV order persistence is not configured')
        async with service.automation.order_limiter:
            return await service.review_and_quote(context,shipment_id,body)

    async def read_manifest(request: Request, tenant_id, financial_details=True):
        try:
            async with request.app.state.finance.pool.acquire() as connection:
                rows = await connection.fetch("""SELECT id,tenant_id,customer_reference,status,currency,final_client_price,tracking_number,logistics_metadata,
                                                  origin_country,destination_country,cargo_type,proof_of_delivery_url,tracking_url,
                                                  customs_required,customs_items,sender_address,recipient_address,parcel_weight_kg,
                                                  customs_reviewed_at,booked_at,dispatched_at,delivered_at,last_tracking_event_at
                                                  FROM public.shipments WHERE ($1::uuid IS NULL OR tenant_id=$1) ORDER BY created_at DESC,id DESC LIMIT 200""", tenant_id)
        except asyncpg.PostgresError:
            raise HTTPException(503, "Manifest unavailable; check logistics migration") from None
        result = []
        for row in rows:
            metadata = json.loads(row["logistics_metadata"]) if isinstance(row["logistics_metadata"], str) else row["logistics_metadata"]
            label_status = metadata.get('label_lifecycle_status') if isinstance(metadata,dict) else None
            insurance = metadata.get('insurance') if isinstance(metadata,dict) else None
            insurance = {key:insurance[key] for key in ('provider','status','policy_id','premium','tax_amount','total_charge') if key in insurance} if isinstance(insurance,dict) else None
            if isinstance(metadata,dict) and 'insurance' in metadata:
                metadata=dict(metadata,insurance=insurance)
            if not financial_details and isinstance(metadata,dict):
                metadata={k:v for k,v in metadata.items() if k in {'carrier','destination','cargo_type','tracking','ecommerce','synthetic','fixture_batch','stackable','batch_csv','automation_customs'}}
            entry={"id": str(row["id"]), "status": row["status"], "currency": row["currency"], "price": str(row["final_client_price"]), "tracking_number": row["tracking_number"], "metadata": metadata}
            entry['label_status']=label_status
            entry['insurance']=insurance
            entry['tenant_id']=str(row['tenant_id']) if row.get('tenant_id') else None
            entry['reference']=row.get('customer_reference') or str(row['id'])[:12]
            entry['batch_import']=isinstance(metadata,dict) and 'batch_csv' in metadata
            for field in ['origin_country','destination_country','cargo_type','proof_of_delivery_url','tracking_url','customs_required']:
                entry[field]=row.get(field)
            for field in ['booked_at','dispatched_at','delivered_at','last_tracking_event_at']:
                value=row.get(field);entry[field]=value.isoformat() if value else None
            entry['customs_declaration']=metadata.get('automation_customs') if isinstance(metadata,dict) else None
            if not entry['customs_declaration'] and row.get('customs_required') and row.get('customs_reviewed_at'):
                try:
                    def decode(v):return json.loads(v) if isinstance(v,str) else v
                    party_fields={'name','line1','city','postal_code','country_code','eori'}
                    items=decode(row['customs_items'])
                    entry['customs_declaration']=generate_commercial_invoice({'invoice_reference':str(row['id']),
                        'form':'COMMERCIAL_INVOICE','sender':{k:v for k,v in decode(row['sender_address']).items() if k in party_fields},
                        'recipient':{k:v for k,v in decode(row['recipient_address']).items() if k in party_fields},'currency':row['currency'],
                        'items':[{'description':i['description'],'quantity':i['quantity'],'unit_value':i['unit_value'],'unit_net_weight_kg':i.get('unit_net_weight_kg',i.get('unit_weight_kg')),'origin_country':i['origin_country'],'hs_code':i['hs_code']} for i in items],
                        'gross_weight_kg':str(row['parcel_weight_kg']),'hs_codes_reviewed':True})
                    entry['customs_declaration']['created_at']=row['customs_reviewed_at'].isoformat()
                    entry['customs_declaration']['source']='RECONSTRUCTED_FROM_REVIEWED_SHIPMENT'
                except (ValueError,TypeError,KeyError):
                    entry['customs_declaration']=None
            result.append(entry)
        return {"shipments": result, "limit": 200}

    @router.get('/shipments/manifest')
    async def manifest(request: Request,context: Any=Depends(authenticate)):
        from main import validate_tenant_query
        validate_tenant_query(request, context.tenant_id)
        return await read_manifest(request,context.tenant_id,financial_details=context.role!='DISPATCHER')

    from backend.admin_portal import authenticate_platform_owner
    @router.get('/admin/shipments/manifest')
    async def owner_manifest(request: Request,owner: Any=Depends(authenticate_platform_owner)):
        return await read_manifest(request,None)

    @router.get('/countries')
    async def countries():
        import pycountry
        return {'countries':sorted([{'code':c.alpha_2,'name':c.name} for c in pycountry.countries],key=lambda c:c['name'])}

    @router.get("/wallet")
    async def wallet(request: Request, context: Any = Depends(authenticate)):
        if context.role not in {"OWNER", "ADMIN", "ACCOUNTANT"}:
            raise HTTPException(403, "Financial permission required")
        try:
            async with request.app.state.finance.pool.acquire() as connection:
                row = await connection.fetchrow("SELECT currency,balance,reserved_balance FROM public.wallets WHERE tenant_id=$1", context.tenant_id)
        except asyncpg.PostgresError:
            raise HTTPException(503, "Wallet unavailable") from None
        if row is None:
            raise HTTPException(404, "Wallet is not provisioned")
        return {"currency": row["currency"], "balance": amount(row["balance"]), "reserved_balance": amount(row["reserved_balance"]), "available": amount(row["balance"] - row["reserved_balance"])}

    return router
