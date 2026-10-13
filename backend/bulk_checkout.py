"""Review persisted rates and explicitly buy selected offers for CSV or store orders."""
import asyncio
from datetime import datetime,timezone
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field,model_validator
from typing import Literal
from backend.dispatch_workspace import permitted,decoded
from backend.carrier_consolidation import public_payload
from backend.automation_three_partners import BookingRequest

class OrderSelection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    shipment_ids:list[UUID]=Field(min_length=1,max_length=100)
    @model_validator(mode='after')
    def unique(self):
        if len(set(self.shipment_ids))!=len(self.shipment_ids):raise ValueError('Select each order once')
        return self

class SelectedOffer(BaseModel):
    model_config=ConfigDict(extra='forbid')
    shipment_id:UUID
    offer_id:UUID
    expected_price:Decimal=Field(gt=0,max_digits=14,decimal_places=2)
    currency:Literal['GBP','EUR','USD']

class CheckoutSelection(BaseModel):
    model_config=ConfigDict(extra='forbid')
    offers:list[SelectedOffer]=Field(min_length=1,max_length=100)
    @model_validator(mode='after')
    def unique(self):
        if len({x.shipment_id for x in self.offers})!=len(self.offers):raise ValueError('Only one service may be selected per order')
        return self

async def order_rows(service,context,ids):
    async with service.pool.acquire() as c:
        rows=await c.fetch('SELECT * FROM public.shipments WHERE tenant_id=$1 AND id=ANY($2::uuid[])',context.tenant_id,ids)
    if len(rows)!=len(ids):raise HTTPException(404,'One or more orders were not found in this workspace')
    mapping={r['id']:r for r in rows}
    return [mapping[id_] for id_ in ids]

async def review_orders(service,context,ids):
    rows=await order_rows(service,context,ids)
    async with service.pool.acquire() as c:
        offers=await c.fetch('''SELECT o.shipment_id,o.rate_snapshot,o.expires_at FROM public.partner_shipping_offers o
            JOIN public.shipments s ON s.tenant_id=o.tenant_id AND s.id=o.shipment_id
            WHERE o.tenant_id=$1 AND o.shipment_id=ANY($2::uuid[]) AND s.status='QUOTED'
            AND o.expires_at=s.quote_expires_at AND o.expires_at>now()''',context.tenant_id,ids)
    result=[]
    for row in rows:
        rates=[decoded(o['rate_snapshot'])|{'expires_at':o['expires_at'].isoformat()} for o in offers if o['shipment_id']==row['id']]
        rates.sort(key=lambda r:(Decimal(r['client_price_ex_tax']),r['carrier_code'],r['service_code']))
        customs=decoded(row['logistics_metadata']).get('automation_customs',{})
        result.append({'shipment_id':str(row['id']),'reference':row['customer_reference'],'status':row['status'],
            'rates':rates,'customs_ready':not row['customs_required'] or customs.get('ready_for_provider',False),
            'batch_import':'batch_csv' in decoded(row['logistics_metadata']),
            'notice':'Choose a shipping service and confirm the total before buying.' if rates else
                'Complete packing/customs and fetch fresh rates. Uploading an order does not purchase a label.'})
    return public_payload({'orders':result},financial=context.role!='DISPATCHER')

async def validate_checkout(service,context,selection,*,check_wallet=True):
    rows=await order_rows(service,context,[x.shipment_id for x in selection.offers])
    async with service.pool.acquire() as c:
        offers=await c.fetch('SELECT * FROM public.partner_shipping_offers WHERE tenant_id=$1 AND offer_id=ANY($2::uuid[])',context.tenant_id,[x.offer_id for x in selection.offers])
    by_offer={r['offer_id']:r for r in offers};total=Decimal(0);currencies=set();now=datetime.now(timezone.utc)
    for selected,row in zip(selection.offers,rows,strict=True):
        stored=by_offer.get(selected.offer_id)
        if not stored or stored['shipment_id']!=selected.shipment_id:raise HTTPException(404,'Selected offer does not belong to this workspace order')
        rate=decoded(stored['rate_snapshot'])
        if Decimal(rate['client_price_ex_tax'])!=selected.expected_price or rate['currency']!=selected.currency:
            raise HTTPException(409,'A selected price changed. Review rates again; no labels were purchased.')
        snapshot=decoded(row['pricing_snapshot']).get('selected_rate',{})
        already_submitted=row['status'] in {'BOOKED','BOOKING','DISPATCHED','IN_TRANSIT','DELIVERED','EXCEPTION'}
        if already_submitted:
            if snapshot.get('offer_id')!=str(selected.offer_id):raise HTTPException(409,'This order already has another booking in progress or confirmed')
        else:
            if row['status']!='QUOTED' or stored['expires_at']<=now or stored['expires_at']!=row['quote_expires_at']:
                raise HTTPException(409,'An order needs fresh rates. No labels were purchased.')
            customs=decoded(row['logistics_metadata']).get('automation_customs',{})
            if row['customs_required'] and not customs.get('ready_for_provider'):
                raise HTTPException(409,'Review customs before checkout. No labels were purchased.')
            total+=selected.expected_price;currencies.add(selected.currency)
    async with service.pool.acquire() as c:
        tenant=await c.fetchrow('SELECT billing_plan,workspace_status,billing_status FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
        if not tenant or tenant['workspace_status']!='ACTIVE' or tenant['billing_status']!='ACTIVE':raise HTTPException(403,'Active workspace and billing required')
        if tenant['billing_plan']=='PREPAID_WALLET' and total:
            wallet=await c.fetchrow('SELECT balance,reserved_balance,currency FROM public.wallets WHERE tenant_id=$1',context.tenant_id)
            if not wallet or currencies!={wallet['currency']}:raise HTTPException(409,'Select rates in the wallet currency')
            if check_wallet and wallet['balance']-wallet['reserved_balance']<total:raise HTTPException(402,'Insufficient available wallet funds for the selected total; no labels were purchased')
    return rows,total,currencies

async def checkout_orders(service,context,selection):
    rows,_,_=await validate_checkout(service,context,selection)
    # Each native confirmation retains the existing transaction locks, reservation,
    # idempotency and uncertain-outcome protections. External purchases are not atomic.
    limiter=asyncio.Semaphore(3)
    async def buy(selected,row):
        async with limiter:
            try:
                if row.get('booked_at') and row['status'] in {'BOOKED','DISPATCHED','IN_TRANSIT','DELIVERED','EXCEPTION'}:
                    async with service.pool.acquire() as c:
                        captured=await c.fetchval("SELECT status='CAPTURED' FROM public.wallet_reservations WHERE tenant_id=$1 AND shipment_id=$2",context.tenant_id,selected.shipment_id)
                    metadata=decoded(row['logistics_metadata']);label=metadata.get('automation_label')
                    if captured and label:
                        return {'reference':row['customer_reference'],**service.public_result(row['id'],label,metadata.get('automation_customs'),replayed=True)}
                result=await service.confirm(context,BookingRequest(tenant_id=context.tenant_id,offer_id=selected.offer_id))
                return {'reference':row['customer_reference'],**result}
            except HTTPException as exc:
                return {'shipment_id':str(selected.shipment_id),'reference':row['customer_reference'],'status':'ACTION_REQUIRED','error':exc.detail,'http_status':exc.status_code}
            except Exception:
                return {'shipment_id':str(selected.shipment_id),'reference':row['customer_reference'],'status':'RECONCILIATION_REQUIRED','error':'Refresh this order before retrying; a carrier outcome may require reconciliation.'}
    results=await asyncio.gather(*(buy(x,r) for x,r in zip(selection.offers,rows,strict=True)))
    return public_payload({'results':results,'notice':'Each order is confirmed separately. Successful bookings remain booked if another order fails; uncertain purchases must not be duplicated.'},financial=context.role!='DISPATCHER')

def build_router(authenticate):
    router=APIRouter(prefix='/api/v1/shipments/bulk',tags=['Bulk review and checkout'])
    @router.post('/review')
    async def review(body:OrderSelection,request:Request,context=Depends(authenticate)):
        permitted(context)
        return await review_orders(request.app.state.partner_lifecycle,context,body.shipment_ids)
    @router.post('/quote')
    async def quote(body:OrderSelection,request:Request,context=Depends(authenticate)):
        permitted(context);service=request.app.state.partner_lifecycle
        rows=await order_rows(service,context,body.shipment_ids)
        async def run(row):
            order=decoded(row['logistics_metadata']).get('automation_order')
            if not order or row['status'] not in {'PENDING_IMPORT','DRAFT','QUOTED'}:
                return {'shipment_id':str(row['id']),'status':'REVIEW_REQUIRED','error':'Complete preparation or use the existing booking'}
            async with service.automation.order_limiter:
                return await service.automation.process(context,order,'QUOTE_ONLY')
        results=await asyncio.gather(*(run(r) for r in rows))
        return public_payload({'results':results},financial=context.role!='DISPATCHER')
    @router.post('/checkout')
    async def checkout(body:CheckoutSelection,request:Request,context=Depends(authenticate)):
        permitted(context)
        return await checkout_orders(request.app.state.partner_lifecycle,context,body)
    @router.post('/print-bundle')
    async def print_bundle(body:OrderSelection,request:Request,context=Depends(authenticate)):
        permitted(context)
        from backend.dispatch_pdf import bundle_shipments
        rows=await order_rows(request.app.state.partner_lifecycle,context,body.shipment_ids)
        from backend.automation_three_partners import carrier_document
        async def fetch_document(row,document):
            response=await carrier_document(row['id'],document,request.app.state.partner_lifecycle,context)
            return response.body
        data=await bundle_shipments(rows,client=request.app.state.partner_lifecycle.client,fetch_document=fetch_document)
        return Response(data,media_type='application/pdf',headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="easyinvio-bulk-labels.pdf"'})
    return router
