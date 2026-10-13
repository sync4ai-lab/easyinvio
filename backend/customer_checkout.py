"""Tenant-authorized checkout of private offers and confirmed invoice PDFs."""
import asyncio
import json
from decimal import Decimal
from uuid import UUID, NAMESPACE_URL, uuid5
import html
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field

from backend.automation_freight_engine import EU_CUSTOMS_AREA, Goods, Order, StrictInput
from backend.automation_three_partners import decode_json
from backend.carrier_consolidation import carrier_identity, service_identity, public_payload


class CheckoutCustoms(StrictInput):
    items: list[Goods] = Field(min_length=1,max_length=100)
    signer: str = Field(min_length=1,max_length=200)
    reviewed: bool
    currency: str = Field(pattern='^(GBP|EUR|USD)$')
    category: str = Field(pattern='^(SALE|GIFT|RETURN|SAMPLE|OTHER)$')
    category_other: str | None = Field(default=None,min_length=3,max_length=200)
    incoterm: str = Field(default='DAP',pattern='^DAP$')
    sender_eori: str | None = Field(default=None,max_length=40)
    recipient_eori: str | None = Field(default=None,max_length=40)


class CheckoutPrepare(StrictInput):
    offer_id: UUID
    customs: CheckoutCustoms | None = None


class TariffQuery(StrictInput):
    description: str = Field(min_length=3,max_length=500)


async def search_tariff(client,description):
    if description.strip().lower() in {'iron box','iron','box'}:
        return {'candidates':[],'question':'Do you mean an electric clothes iron, or a storage box made from iron? Describe its function and material.'}
    url='https://www.trade-tariff.service.gov.uk/api/v2/search'
    try:
        async with client.stream('GET',url,params={'q':description},timeout=12,follow_redirects=False) as response:
            if response.status_code!=200:
                raise ValueError('Tariff unavailable')
            raw=bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw)>2_000_000:
                    raise ValueError('Tariff response limit')
        data=json.loads(raw)
        attributes=data['data']['attributes'];candidates=[];seen=set()
        for group in ('goods_nomenclature_match','reference_match'):
            for entry in attributes.get(group,{}).get('commodities',[]):
                source=entry.get('_source',entry)
                code=source.get('goods_nomenclature_item_id','')
                if not re.fullmatch(r'\d{10}',code) or source.get('declarable') is False or code in seen:
                    continue
                seen.add(code)
                descriptions=source.get('ancestor_descriptions',[])+[source.get('description','')]
                title=html.unescape(re.sub('<[^>]+>','', ' / '.join(str(value) for value in descriptions)))
                candidates.append({'hs_code':code[:6],'national_code':code,'title':title,
                    'source':'UK Integrated Online Tariff','source_url':'https://www.trade-tariff.service.gov.uk/commodities/'+code})
        return {'candidates':candidates[:12],'question':None,
            'notice':'Official UK tariff search results, not an automatic classification. Review the description and destination requirements; the first six digits are the common HS code.'}
    except Exception:
        raise HTTPException(503,'Official tariff lookup is unavailable. Try again or check the UK Trade Tariff directly; no code was guessed.') from None


async def booking_reference(pool,tenant,request_id):
    async with pool.acquire() as c:
        async with c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','invoice:'+str(tenant)+':'+str(request_id))
            reference=await c.fetchval('SELECT invoice_reference FROM public.booking_references WHERE tenant_id=$1 AND request_id=$2',tenant,request_id)
            if reference:return reference
            key=uuid5(NAMESPACE_URL,'checkout:'+str(tenant)+':'+str(request_id))
            reference=await c.fetchval('SELECT customer_reference FROM public.shipments WHERE tenant_id=$1 AND idempotency_key=$2',tenant,key)
            if not reference:
                number=await c.fetchval("SELECT nextval('public.easyinvio_booking_reference_sequence')")
                reference='EINVIO-'+str(number).zfill(8)
            await c.execute('INSERT INTO public.booking_references(tenant_id,request_id,invoice_reference) VALUES($1,$2,$3)',tenant,request_id,reference)
            return reference


def quoted_goods(quote):
    source=quote.shipment_items or (quote.customs_document or {}).get('items',[])
    return [{k:item[k] for k in ['description','quantity','unit_value','unit_weight_kg','origin_country','hs_code'] if k in item} for item in source]

async def offer_context(service,context,offer_id):
    from main import RatingRequest,RatingResponse
    if context.role not in {'OWNER','ADMIN','DISPATCHER'}:
        raise HTTPException(403,'This role cannot book shipping labels')
    async with service.pool.acquire() as connection:
        row=await connection.fetchrow('''SELECT request_id,request_payload,quote_payload FROM public.partner_unbound_quotes
            WHERE tenant_id=$1 AND expires_at>now() AND quote_payload->'rates' @>
            jsonb_build_array(jsonb_build_object('offer_id',$2::text))''',context.tenant_id,str(offer_id))
    if row is None:
        raise HTTPException(404,'Quote not found in this workspace or expired; request fresh rates')
    request=RatingRequest.model_validate(decode_json(row['request_payload']))
    result=RatingResponse.model_validate(decode_json(row['quote_payload']))
    selected=next((rate for rate in result.rates if rate.offer_id==offer_id),None)
    if selected is None:
        raise HTTPException(404,'Service not found in this quote')
    if len(request.weights_kg)!=1 or len(request.dimensions)>1:
        raise HTTPException(422,'Use the packed-order workspace for multiple parcels')
    reference=await booking_reference(service.pool,context.tenant_id,row['request_id'])
    required=request.origin.country_code!=request.destination.country_code and not {
        request.origin.country_code,request.destination.country_code}<=EU_CUSTOMS_AREA
    return row,request,result,selected,reference,required


def build_router(authenticate):
    router=APIRouter(prefix='/api/v1/checkout',tags=['Customer booking checkout'])

    @router.post('/hs-search')
    async def hs_search(body:TariffQuery,request:Request,user=Depends(authenticate)):
        return await search_tariff(request.app.state.partner_lifecycle.client,body.description)

    @router.get('/context')
    async def context(offer_id:UUID,request:Request,user=Depends(authenticate)):
        service=request.app.state.partner_lifecycle
        row,quote,_,rate,reference,required=await offer_context(service,user,offer_id)
        from backend.automation_three_partners import EasyPostAdapter
        currency=quote.goods_currency or ('USD' if rate.execution_details.get('account_endpoint')==EasyPostAdapter.endpoint else quote.currency)
        return {'invoice_reference':reference,'customs_required':required,'goods_value_currency':currency,
                'shipping_currency':rate.currency,'shipping_cost':str(rate.client_price_ex_tax),
                'origin':quote.origin.model_dump(mode='json'),'destination':quote.destination.model_dump(mode='json'),
                'gross_weight_kg':str(quote.weights_kg[0]),'total_goods_net_weight_kg':str(sum((Decimal(str(i['unit_weight_kg']))*int(i['quantity']) for i in quoted_goods(quote)),Decimal(0))),'items':quoted_goods(quote),
                'goods_locked':bool(quoted_goods(quote)),'invoice_download_after_booking':True}

    @router.post('/prepare')
    async def prepare(body:CheckoutPrepare,request:Request,user=Depends(authenticate)):
        service=request.app.state.partner_lifecycle
        row,quote,quoted,selected,reference,required=await offer_context(service,user,body.offer_id)
        if required and body.customs is None:
            raise HTTPException(422,'International goods require customs details before a carrier can issue the label')
        if body.customs:
            original=quoted_goods(quote)
            if not original:raise HTTPException(409,'This quote has no goods snapshot. Enter the goods in Create shipment and request fresh rates.')
            if len(original)!=len(body.customs.items):raise HTTPException(409,'Goods changed; request a new quote')
            for saved,submitted in zip(original,body.customs.items,strict=True):
                for key in ('quantity','unit_value','unit_weight_kg','origin_country'):
                    expected=saved[key];actual=getattr(submitted,key)
                    equal=(str(expected).upper()==str(actual).upper()) if key=='origin_country' else Decimal(str(expected))==Decimal(str(actual))
                    if not equal:raise HTTPException(409,'Quoted goods values are immutable. Change the shipment and request fresh rates.')
            if body.customs.currency!=(quote.goods_currency or ('USD' if selected.execution_details.get('account_endpoint')=='https://api.easypost.com/v2' else quote.currency)):
                raise HTTPException(409,'Goods currency changed; request a new quote')
        if body.customs and (not body.customs.reviewed or any(not item.hs_code for item in body.customs.items)):
            raise HTTPException(422,'Select and review an HS code for each product')
        if body.customs and body.customs.category=='OTHER' and selected.execution_details.get('account_endpoint')=='https://panel.sendcloud.sc/api/v3':
            raise HTTPException(422,'This service does not accept an OTHER export reason. Select the accurate supported category or another service; no purchase was made.')
        dimensions=quote.dimensions[0].model_dump(mode='json') if quote.dimensions else {}
        order={'idempotency_key':str(uuid5(NAMESPACE_URL,'checkout:'+str(user.tenant_id)+':'+str(row['request_id']))),
            'order_reference':reference,'invoice_reference':reference,'currency':quote.currency,
            'origin':quote.origin.model_dump(mode='json'),'destination':quote.destination.model_dump(mode='json'),
            'cargo':{'cargo_type':quote.cargo_type,'actual_weight_kg':str(quote.weights_kg[0]),'stackable':quote.stackable,**dimensions}}
        if body.customs:
            data=body.customs
            order.update(items=[item.model_dump(mode='json') for item in data.items],customs_signer=data.signer,
                hs_codes_reviewed=data.reviewed,customs_currency=data.currency,customs_category=data.category,
                customs_category_other=data.category_other,incoterm=data.incoterm,
                sender_eori=data.sender_eori,recipient_eori=data.recipient_eori)
        # Customs must be sent when native quotes are created, not retrofitted into
        # an already quoted remote parcel. Domestic quotes can be reused exactly.
        async with service.automation.order_limiter:
            result=await service.automation.process(user,Order.model_validate(order).model_dump(mode='json'),
                'QUOTE_ONLY',private_quote=None if required else quoted)
        if result['status']!='QUOTED':
            raise HTTPException(422,{'message':'Shipment could not be prepared','reason':result.get('error','PACKING_REVIEW_REQUIRED')})
        offers=result.get('all_rates',[])
        match=next((rate for rate in offers if carrier_identity(rate['carrier_code'])==carrier_identity(selected.carrier_code)
            and service_identity(rate['carrier_code'],rate['service_code'])==service_identity(selected.carrier_code,selected.service_code)),None)
        if match is None:
            raise HTTPException(409,'The selected service is unavailable with these customs details. Request another quote; no label was purchased.')
        async with service.pool.acquire() as connection:
            # This cost is server-selected, never the browser's shipping field.
            await connection.execute('''UPDATE public.shipments SET logistics_metadata=jsonb_set(logistics_metadata,
                '{automation_customs}',(logistics_metadata->'automation_customs')||jsonb_build_object(
                    'shipping_cost',$3::text,'shipping_currency',$4::text),true)
                WHERE tenant_id=$1 AND id=$2 AND status='QUOTED' ''',user.tenant_id,UUID(result['shipment_id']),
                str(match['client_price_ex_tax']),match['currency'])
        return public_payload({'shipment_id':result['shipment_id'],'invoice_reference':reference,
            'offer':match,'price_changed':Decimal(match['client_price_ex_tax'])!=selected.client_price_ex_tax,
            'customs_required':required},financial=user.role!='DISPATCHER')

    @router.get('/{shipment_id}/receipt.pdf')
    async def receipt(shipment_id:UUID,request:Request,user=Depends(authenticate)):
        if user.role=='DISPATCHER':raise HTTPException(403,'Financial documents require an owner or accountant role')
        async with request.app.state.partner_lifecycle.pool.acquire() as c:
            row=await c.fetchrow("""SELECT s.customer_reference,s.currency,s.final_client_price,s.tax_amount,s.tracking_number,
                s.origin_country,s.destination_country,s.booked_at,s.status,t.company_name,t.is_sandbox,t.billing_plan,
                r.status AS reservation_status FROM public.shipments s JOIN public.tenants t USING(tenant_id)
                LEFT JOIN public.wallet_reservations r ON r.tenant_id=s.tenant_id AND r.shipment_id=s.id
                WHERE s.tenant_id=$1 AND s.id=$2""",user.tenant_id,shipment_id)
        if not row:raise HTTPException(404,'Shipment not found in this workspace')
        if not row['booked_at'] or not row['tracking_number'] or row['status'] not in {'BOOKED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED'}:
            raise HTTPException(409,'Receipt is available after confirmed booking')
        if row['billing_plan']=='PREPAID_WALLET' and row['reservation_status']!='CAPTURED':raise HTTPException(409,'Booking payment requires reconciliation')
        from backend.booking_receipt import receipt_pdf
        data=await asyncio.to_thread(receipt_pdf,dict(row))
        return Response(data,media_type='application/pdf',headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="easyinvio-booking-receipt.pdf"'})

    @router.get('/{shipment_id}/commercial-invoice.pdf')
    async def invoice(shipment_id:UUID,request:Request,user=Depends(authenticate)):
        service=request.app.state.partner_lifecycle
        async with service.pool.acquire() as connection:
            row=await connection.fetchrow('''SELECT s.customer_reference,s.logistics_metadata,s.status,s.booked_at,
                s.tracking_number,r.status AS reservation_status FROM public.shipments s
                LEFT JOIN public.wallet_reservations r ON r.tenant_id=s.tenant_id AND r.shipment_id=s.id
                WHERE s.tenant_id=$1 AND s.id=$2''',user.tenant_id,shipment_id)
        if row is None:
            raise HTTPException(404,'Shipment not found in this workspace')
        if (row['status'] not in {'BOOKED','DISPATCHED','IN_TRANSIT','DELIVERED','EXCEPTION'} or not row['booked_at']
            or not row['tracking_number'] or row['reservation_status']!='CAPTURED'):
            raise HTTPException(409,'The invoice download becomes available after the label and booking payment are confirmed')
        declaration=decode_json(row['logistics_metadata']).get('automation_customs')
        if not declaration or not declaration.get('required'):
            raise HTTPException(409,'This shipment has no customs declaration')
        from backend.dispatch_pdf import invoice_pdf
        data=await asyncio.to_thread(invoice_pdf,row['customer_reference'],declaration)
        return Response(data,media_type='application/pdf',headers={'Cache-Control':'no-store',
            'Content-Disposition':'attachment; filename="easyinvio-commercial-invoice-'+str(shipment_id)+'.pdf"'})

    return router
