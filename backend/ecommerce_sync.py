"""Tenant-scoped imports and durable fulfillment delivery.

Normalized JWT intake and native signed intake share the database write path.
Delivery defaults to an explicit simulation; server-configured Shopify delivery
uses a durable send fence and remote reconciliation. Other outbound platforms
still require adapters. See ecommerce_connectors.py and the core pillar report.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from decimal import Decimal, localcontext, ROUND_CEILING
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from backend.ai_engine import strict_decimal, country_code

_service: EcommerceService | None = None


class Address(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    address1: str = Field(min_length=1, max_length=250)
    address2: str = Field(default="", max_length=250)
    city: str = Field(min_length=1, max_length=120)
    zip: str = Field(min_length=1, max_length=30)
    country_code: str
    province: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=40)

    @field_validator("country_code")
    @classmethod
    def country(cls, value):
        return country_code(value)


class LineItem(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=250)
    quantity: int = Field(strict=True, ge=1, le=10000)
    grams: Decimal = Field(ge=0, le=1000000)
    length_cm: Decimal | None = Field(default=None, gt=0, le=1000)
    width_cm: Decimal | None = Field(default=None, gt=0, le=1000)
    height_cm: Decimal | None = Field(default=None, gt=0, le=1000)
    unit_value: Decimal | None = Field(default=None, gt=0, le=1000000, decimal_places=2)
    origin_country: str | None = None
    hs_code: str | None = Field(default=None, pattern=r'^\d{6}(?:\d{2})?(?:\d{2})?$')

    @field_validator("grams", "length_cm", "width_cm", "height_cm", "unit_value", mode="before")
    @classmethod
    def decimal_values(cls, value):
        return None if value is None else strict_decimal(value)

    @field_validator('origin_country')
    @classmethod
    def goods_origin(cls, value):
        return country_code(value) if value else None

    @model_validator(mode="after")
    def dimensions(self):
        supplied = [self.length_cm, self.width_cm, self.height_cm]
        if any(v is not None for v in supplied) and not all(v is not None for v in supplied):
            raise ValueError("Supply all three dimensions or none")
        return self


class StoreOrder(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    id: str | int
    name: str = Field(min_length=1, max_length=100)
    currency: Literal["GBP", "EUR", "USD"]
    shipping_address: Address
    line_items: list[LineItem] = Field(min_length=1, max_length=500)

    @field_validator("id", mode="before")
    @classmethod
    def identifier(cls, value):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError("Order ID must be text or an integer")
        value = str(value).strip()
        if not value or len(value) > 150 or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid order ID")
        return value


class ImportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    store_id: UUID
    platform: Literal["SHOPIFY", "WOOCOMMERCE", "AMAZON"] = "SHOPIFY"
    topic: Literal["orders/create", "orders/paid"] = "orders/create"
    cargo_type: Literal["LETTER", "PARCEL", "PALLET", "OVERLAND_FREIGHT"] = "PARCEL"
    order: StoreOrder


def parsed_order(order: StoreOrder) -> dict:
    """Grams are unit weight; multiply once by quantity using exact arithmetic."""
    with localcontext() as ctx:
        ctx.prec = 50
        grams = Decimal(0)
        quantity = 0
        items = []
        for item in order.line_items:
            grams += item.grams * item.quantity
            quantity += item.quantity
            serialized = item.model_dump(mode="json")
            # Preserve historical import hashes when optional customs facts are absent.
            for key in ('unit_value', 'origin_country', 'hs_code'):
                if serialized[key] is None:
                    serialized.pop(key)
            items.append(serialized)
        kg = grams / Decimal(1000)
        if kg <= 0 or kg > 1000 or quantity > 10000:
            raise ValueError("Order must weigh more than zero and at most 1000 kg, with at most 10000 units")
    address = order.shipping_address.model_dump()
    if not address['phone']:
        address.pop('phone')
    return {"store_order_id": str(order.id), "order_reference": order.name,
            "shipping_address": address,
            "total_weight_kg": format(kg, "f"), "total_quantity": quantity,
            "line_items": items, "currency": order.currency}


def tracking_link(carrier: str, number: str) -> str | None:
    encoded = quote(number, safe="")
    roots = {"UPS": "https://www.ups.com/track?tracknum=",
             "FEDEX": "https://www.fedex.com/fedextrack/?trknbr=",
             "DHL": "https://www.dhl.com/global-en/home/tracking.html?tracking-id=",
             "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels="}
    root = roots.get(carrier.strip().upper())
    return root + encoded if root else None


class ReturnReference(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reference:str=Field(pattern=r'^gid://shopify/ReverseFulfillmentOrder/[1-9][0-9]{0,30}$')

class EcommerceService:
    def __init__(self, pool, *, connectors=None, client=None, credential_keys=None):
        self.pool = pool
        self.connectors = connectors or {}
        self.client = client
        self.credential_keys = credential_keys or {}

    async def push_live(self, tenant_id, store_order_id, tracking_number, carrier_name):
        """Commit a send fence before the remote mutation; crashes cannot resend."""
        async with self.pool.acquire() as connection:
            rows = await connection.fetch('''SELECT o.id,o.store_id,o.payload FROM public.ecommerce_tracking_outbox o
                JOIN public.ecommerce_stores s ON s.tenant_id=o.tenant_id AND s.id=o.store_id
                WHERE o.tenant_id=$1 AND o.store_order_id=$2 AND o.status='PENDING' AND o.tracking_lifecycle_type='FORWARD_SHIPMENT' AND s.is_active''', tenant_id,store_order_id)
        for row in rows:
            from backend.store_connections import resolve_connector
            config = await resolve_connector(self, row['store_id'])
            if not config or not config.live_delivery or config.tenant_id != tenant_id:
                continue
            body = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
            if body['tracking_number'] != tracking_number or body['carrier_name'] != carrier_name:
                continue
            if self.client is None:
                raise HTTPException(503, 'Store delivery client unavailable')
            async with self.pool.acquire() as connection:
                claimed = await connection.fetchval('''UPDATE public.ecommerce_tracking_outbox
                    SET status='RECONCILIATION_REQUIRED',attempts=attempts+1
                    WHERE tenant_id=$1 AND id=$2 AND status='PENDING' RETURNING id''',tenant_id,row['id'])
            if not claimed:
                continue
            from backend.ecommerce_connectors import ShopifyFulfillment
            try:
                response = await ShopifyFulfillment(self.client,config).deliver(body)
            except (httpx.HTTPError,HTTPException,ValueError,KeyError,TypeError):
                # No remote error payload or credentials enter the outbox/logs.
                continue
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute('''UPDATE public.ecommerce_tracking_outbox SET status='DELIVERED',
                        delivered_at=now(),response=$3::jsonb WHERE tenant_id=$1 AND id=$2 AND status='RECONCILIATION_REQUIRED' ''',
                        tenant_id,row['id'],json.dumps(response))
                    await connection.execute("UPDATE public.shipments SET store_fulfillment_status='FULFILLED' WHERE tenant_id=$1 AND id=(SELECT shipment_id FROM public.ecommerce_tracking_outbox WHERE tenant_id=$1 AND id=$2) AND tracking_lifecycle_type='FORWARD_SHIPMENT'",tenant_id,row['id'])

    async def import_order(self, context, payload: ImportPayload, *, initial_status="PENDING_IMPORT") -> dict:
        if initial_status not in {"PENDING_IMPORT", "UNFULFILLED"}:
            raise ValueError("Invalid internal import status")
        if context.role not in {"OWNER", "ADMIN", "DISPATCHER"}:
            raise HTTPException(403, "Dispatch permission required")
        try:
            metadata = parsed_order(payload.order)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if payload.cargo_type != "PARCEL":
            metadata["cargo_type"] = payload.cargo_type
        digest = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                store = await connection.fetchrow(
                    "SELECT platform FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2 AND is_active FOR SHARE",
                    context.tenant_id, payload.store_id)
                if store is None:
                    raise HTTPException(404, "Store not found")
                if store["platform"] != payload.platform:
                    raise HTTPException(409, "Store platform mismatch")
                await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                                         f"import:{context.tenant_id}:{payload.store_id}:{payload.order.id}")
                existing = await connection.fetchrow(
                    "SELECT id,status,store_import_hash FROM public.shipments WHERE tenant_id=$1 AND ecommerce_store_id=$2 AND store_order_id=$3 FOR UPDATE",
                    context.tenant_id, payload.store_id, str(payload.order.id))
                if existing:
                    if existing["store_import_hash"] != digest:
                        raise HTTPException(409, "Order already imported with different shipping data; reconcile before updating")
                    return {"shipment_id": str(existing["id"]), "status": existing["status"], "replayed": True, **metadata}
                shipment_id = uuid4()
                if getattr(context,'assistance_session_id',None):
                    from backend.client_assistance import operator_member_id
                    member_id=await operator_member_id(connection,context)
                    member={'id':member_id} if member_id else None
                else:
                    member = await connection.fetchrow(
                        "SELECT id FROM public.users WHERE tenant_id=$1 AND auth_user_id=$2 AND is_active AND role IN ('OWNER','ADMIN','DISPATCHER')",
                        context.tenant_id, context.user_id)
                tenant = await connection.fetchrow(
                    "SELECT billing_address,legal_company_name FROM public.tenants WHERE tenant_id=$1 AND workspace_status='ACTIVE'",
                    context.tenant_id)
                if not member or not tenant:
                    raise HTTPException(403, "Active importing workspace member required")
                sender = json.loads(tenant['billing_address']) if isinstance(tenant['billing_address'], str) else dict(tenant['billing_address'])
                sender.setdefault('name', tenant['legal_company_name'])
                if not all(sender.get(key) for key in ('name','line1','city','postal_code','country_code')):
                    raise HTTPException(422, "Configure a complete warehouse billing address before import")
                sender['country_code'] = country_code(sender['country_code'])
                address = payload.order.shipping_address
                recipient = {'name':address.name,'line1':address.address1,'line2':address.address2,
                             'city':address.city,'postal_code':address.zip,'country_code':address.country_code}
                if not address.address2: recipient.pop('line2')
                if address.province: recipient['state']=address.province
                if address.phone: recipient['phone']=address.phone
                await connection.execute(
                    """INSERT INTO public.shipments
                       (id,tenant_id,status,currency,quote_expires_at,ecommerce_store_id,store_order_id,store_import_hash,logistics_metadata,
                        created_by_user_id,idempotency_key,customer_reference,origin_country,destination_country,
                        sender_address,recipient_address,parcel_weight_kg,wholesale_cost,profit_markup,
                        pricing_snapshot,quoted_at,customs_required,cargo_type)
                       VALUES ($1,$2,$15,$3,now(),$4,$5,$6,$7::jsonb,$8,$1,$9,$10,$11,
                         $12::jsonb,$13::jsonb,$14,0,0,jsonb_build_object('markup_type','MANUAL','markup_value','0.00','currency',$3::text),
                         now()-interval '1 second',$10::text<>$11::text,$16)""",
                    shipment_id, context.tenant_id, payload.order.currency, payload.store_id,
                    str(payload.order.id), digest, json.dumps({"ecommerce": metadata, "import_topic": payload.topic}),
                    member['id'],payload.order.name,sender['country_code'],address.country_code,
                    json.dumps(sender),json.dumps(recipient),Decimal(metadata['total_weight_kg']).quantize(Decimal('.001'),rounding=ROUND_CEILING), initial_status, payload.cargo_type)
                return {"shipment_id": str(shipment_id), "status": initial_status, "replayed": False, **metadata}

    async def queue_confirmed_tracking(self, connection, tenant_id, shipment_id, tracking_number, carrier_name):
        """Called in the label settlement transaction; no network inside the lock."""
        shipment = await connection.fetchrow(
            "SELECT ecommerce_store_id,store_order_id,tracking_lifecycle_type,return_of_shipment_id,logistics_metadata FROM public.shipments WHERE tenant_id=$1 AND id=$2",
            tenant_id, shipment_id)
        if shipment is None:
            return None
        metadata=json.loads(shipment.get('logistics_metadata','{}')) if isinstance(shipment.get('logistics_metadata'),str) else shipment.get('logistics_metadata') or {}
        lifecycle=shipment.get('tracking_lifecycle_type','FORWARD_SHIPMENT')
        if metadata.get('automation_order',{}).get('is_return'):lifecycle='RETURN_SHIPMENT'
        if lifecycle=='RETURN_SHIPMENT' and shipment.get('return_of_shipment_id'):
            parent=await connection.fetchrow('SELECT ecommerce_store_id,store_order_id FROM public.shipments WHERE tenant_id=$1 AND id=$2',tenant_id,shipment['return_of_shipment_id'])
            if parent:shipment={**dict(shipment),'ecommerce_store_id':parent['ecommerce_store_id'],'store_order_id':parent['store_order_id']}
        if shipment['ecommerce_store_id'] is None:return None
        body = {"return_quantity":sum(item['quantity'] for item in metadata.get('automation_order',{}).get('items',[])),"tracking_lifecycle_type":lifecycle,"store_return_reference":metadata.get('automation_order',{}).get('store_return_reference'),
                "tracking_numbers":[piece['tracking_number'] for piece in metadata.get('automation_label',{}).get('package_labels',[])],
                "fulfillment_state": "RETURN_LABEL_CREATED" if lifecycle=='RETURN_SHIPMENT' else "SHIPPED", "store_order_id": shipment["store_order_id"],
                "tracking_number": tracking_number, "carrier_name": carrier_name,
                "tracking_url": tracking_link(carrier_name, tracking_number)}
        await connection.execute(
            """INSERT INTO public.ecommerce_tracking_outbox
               (tenant_id,shipment_id,store_id,store_order_id,payload,tracking_lifecycle_type,store_return_reference)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7) ON CONFLICT (tenant_id,shipment_id) DO NOTHING""",
            tenant_id, shipment_id, shipment["ecommerce_store_id"], shipment["store_order_id"], json.dumps(body),lifecycle,body['store_return_reference'])
        return shipment["store_order_id"]

    async def push(self, tenant_id: UUID, store_order_id: str, tracking_number: str, carrier_name: str):
        if not isinstance(tenant_id, UUID) or not tracking_number.strip() or len(tracking_number) > 200 or not carrier_name.strip() or len(carrier_name) > 100:
            raise ValueError("Tenant UUID, tracking number and carrier are required")
        if any(config.live_delivery for config in self.connectors.values()):
            await self.push_live(tenant_id,store_order_id,tracking_number,carrier_name)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                rows = await connection.fetch(
                    """SELECT o.id,o.payload,o.status,o.tracking_lifecycle_type FROM public.ecommerce_tracking_outbox o
                       JOIN public.ecommerce_stores s ON s.id=o.store_id AND s.tenant_id=o.tenant_id
                       WHERE o.tenant_id=$1 AND o.store_order_id=$2 AND s.is_active
                       ORDER BY o.id FOR UPDATE OF o""", tenant_id, store_order_id)
                matched = 0
                for row in rows:
                    body = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
                    if row.get('tracking_lifecycle_type','FORWARD_SHIPMENT')!='FORWARD_SHIPMENT':continue
                    if body["tracking_number"] != tracking_number or body["carrier_name"] != carrier_name:
                        continue
                    matched += 1
                    if row["status"] in {"SIMULATED_DELIVERED", "DELIVERED", "RECONCILIATION_REQUIRED"}:
                        continue
                    # A real HTTP request/response exchange through an in-process mock
                    # transport: no DNS, sockets, credentials or real fulfillment.
                    def merchant_host(request: httpx.Request):
                        received = json.loads(request.content)
                        if received != body or request.headers.get("idempotency-key") != str(row["id"]):
                            return httpx.Response(422, json={"accepted": False})
                        return httpx.Response(200, json={"accepted": True, "fulfillment_state": "SHIPPED", "simulated": True})
                    async with httpx.AsyncClient(transport=httpx.MockTransport(merchant_host), trust_env=False) as client:
                        response = await client.post("https://merchant.invalid/fulfillments", json=body,
                                                     headers={"Idempotency-Key": str(row["id"])})
                        response.raise_for_status()
                    await connection.execute(
                        """UPDATE public.ecommerce_tracking_outbox SET status='SIMULATED_DELIVERED',
                           attempts=attempts+1,delivered_at=now(),response=$3::jsonb WHERE tenant_id=$1 AND id=$2""",
                        tenant_id, row["id"], json.dumps(response.json()))
                if matched == 0:
                    raise HTTPException(404, "Confirmed tracking event not found")

    async def retry_pending(self):
        async with self.pool.acquire() as connection:
            rows = await connection.fetch("SELECT tenant_id,store_order_id,payload FROM public.ecommerce_tracking_outbox WHERE status='PENDING' AND tracking_lifecycle_type='FORWARD_SHIPMENT' ORDER BY created_at LIMIT 100")
        for row in rows:
            body = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            try:
                await self.push(row["tenant_id"], row["store_order_id"], body["tracking_number"], body["carrier_name"])
            except (asyncpg.PostgresError, httpx.HTTPError, HTTPException):
                # Retain the durable pending record; a later cycle retries it.
                continue
        from backend.store_returns import sync_return_jobs
        await sync_return_jobs(self)


def configure_ecommerce_service(service: EcommerceService | None):
    global _service
    _service = service


async def push_tracking_to_store(tenant_id: UUID, store_order_id: str, tracking_number: str, carrier_name: str):
    """Only sends a previously persisted, tenant-owned confirmed-label event."""
    if _service is None:
        raise HTTPException(503, "E-commerce integration is unavailable")
    await _service.push(tenant_id, store_order_id, tracking_number, carrier_name)


async def tracking_worker(service: EcommerceService):
    while True:
        try:
            await service.retry_pending()
        except asyncpg.PostgresError:
            pass
        await asyncio.sleep(10)


def build_router(authenticate):
    router = APIRouter(prefix="/api/v1/integration", tags=["E-commerce"])

    @router.post('/webhooks/{store_id}',status_code=201)
    async def native_webhook(store_id: UUID,request: Request):
        from backend.ecommerce_connectors import receive_store_webhook
        try:
            return await receive_store_webhook(request,store_id)
        except asyncpg.PostgresError:
            raise HTTPException(503,'Store import temporarily unavailable') from None

    @router.get('/tracking-events')
    async def tracking_events(request: Request,context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:
            raise HTTPException(403,'Integration management permission required')
        async with request.app.state.ecommerce.pool.acquire() as connection:
            rows=await connection.fetch('''SELECT id,store_id,shipment_id,status,attempts,created_at,delivered_at,
                tracking_lifecycle_type,store_sync_error_code,store_return_reference
                FROM public.ecommerce_tracking_outbox WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT 200''',context.tenant_id)
        return {'events':[dict(row) for row in rows],'limit':200}

    @router.post('/tracking-events/{event_id}/reconcile')
    async def reconcile_tracking(event_id: UUID,request: Request,context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN'}:
            raise HTTPException(403,'Integration management permission required')
        service=request.app.state.ecommerce
        async with service.pool.acquire() as connection:
            row=await connection.fetchrow('''SELECT o.store_id,o.payload,o.tracking_lifecycle_type FROM public.ecommerce_tracking_outbox o
                JOIN public.ecommerce_stores s ON s.tenant_id=o.tenant_id AND s.id=o.store_id
                WHERE o.tenant_id=$1 AND o.id=$2 AND o.status='RECONCILIATION_REQUIRED' AND s.is_active''',context.tenant_id,event_id)
        if not row: raise HTTPException(404,'Pending reconciliation not found')
        from backend.store_connections import resolve_connector
        config=await resolve_connector(service, row['store_id'])
        if not config or not config.live_delivery or config.tenant_id!=context.tenant_id or service.client is None:
            raise HTTPException(503,'Store delivery not configured')
        from backend.ecommerce_connectors import ShopifyFulfillment
        body=json.loads(row['payload']) if isinstance(row['payload'],str) else row['payload']
        try:
            if row['tracking_lifecycle_type']=='RETURN_SHIPMENT':
                from backend.store_returns import ShopifyReturnTracking
                response=await ShopifyReturnTracking(service.client,config).deliver(body,verify_only=True)
            elif row['tracking_lifecycle_type']=='FORWARD_SHIPMENT':response=await ShopifyFulfillment(service.client,config).deliver(body,verify_only=True)
            else:raise HTTPException(409,'Exchange tracking requires a verified replacement-order allocation')
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            raise HTTPException(503,'Store verification unavailable; hold retained') from None
        async with service.pool.acquire() as connection:
            await connection.execute('''UPDATE public.ecommerce_tracking_outbox SET status='DELIVERED',
                delivered_at=now(),response=$3::jsonb WHERE tenant_id=$1 AND id=$2 AND status='RECONCILIATION_REQUIRED' ''',
                context.tenant_id,event_id,json.dumps(response))
        return {'event_id':str(event_id),'status':'DELIVERED','purchase_retried':False}

    @router.post('/tracking-events/{event_id}/return-reference')
    async def link_return(event_id:UUID,body:ReturnReference,request:Request,context:Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN'}:raise HTTPException(403,'Store management permission required')
        service=request.app.state.ecommerce
        async with service.pool.acquire() as connection:
            row=await connection.fetchrow("SELECT store_id,payload,store_sync_error_code FROM public.ecommerce_tracking_outbox WHERE tenant_id=$1 AND id=$2 AND tracking_lifecycle_type='RETURN_SHIPMENT' AND status='RECONCILIATION_REQUIRED'",context.tenant_id,event_id)
        if not row:raise HTTPException(404,'Held return tracking job not found')
        if row['store_sync_error_code']=='RETURN_SUBMITTED':raise HTTPException(409,'The original return submission requires verification; its reference cannot be replaced')
        from backend.store_connections import resolve_connector
        from backend.store_returns import ShopifyReturnTracking
        config=await resolve_connector(service,row['store_id'])
        if not config or config.tenant_id!=context.tenant_id or config.platform!='SHOPIFY' or not config.live_delivery:raise HTTPException(409,'Enable the verified Shopify return connector before linking a return')
        payload=json.loads(row['payload']) if isinstance(row['payload'],str) else row['payload']
        payload={**payload,'store_return_reference':body.reference}
        await ShopifyReturnTracking(service.client,config).inspect(payload)
        async with service.pool.acquire() as connection:
            result=await connection.execute("UPDATE public.ecommerce_tracking_outbox SET store_return_reference=$3,payload=$4::jsonb,store_sync_error_code='RETURN_ADAPTER_UPGRADE_REQUIRED',attempts=0 WHERE tenant_id=$1 AND id=$2 AND status='RECONCILIATION_REQUIRED' AND store_sync_error_code IS DISTINCT FROM 'RETURN_SUBMITTED'",context.tenant_id,event_id,body.reference,json.dumps(payload))
        if result=='UPDATE 0':raise HTTPException(409,'Return submission started; reference retained')
        return {'event_id':str(event_id),'status':'RECONCILIATION_REQUIRED','return_reference_verified':True,'original_fulfillment_changed':False}

    @router.post("/pull-orders", status_code=201)
    async def pull_orders(request: Request, context: Any = Depends(authenticate)):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(415, "Use application/json")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1048576:
                raise HTTPException(413, "Order payload is limited to 1 MB")
        try:
            data = json.loads(raw, parse_float=Decimal)
            payload = ImportPayload.model_validate(data)
        except (ValidationError, ValueError, UnicodeError):
            raise HTTPException(422, "Invalid store order; check required address, items, weights and identifiers") from None
        try:
            return await request.app.state.ecommerce.import_order(context, payload)
        except asyncpg.PostgresError:
            raise HTTPException(503, "Order import unavailable; check the e-commerce migration") from None

    return router
