"""Card-funded label baskets over the atomic wallet booking ledger."""
import asyncio,json,logging,os
from datetime import datetime,timezone,timedelta
from uuid import UUID
from decimal import Decimal
from types import SimpleNamespace
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import Field
from backend.bulk_checkout import CheckoutSelection,validate_checkout,checkout_orders
from backend.payment_gateway import ensure_customer,reconcile_topup,checkout_redirect,checkout_return_base,safe_checkout_url,require_payment_gateway
from backend.dispatch_workspace import decoded
from backend.carrier_consolidation import public_payload

class CardCart(CheckoutSelection):
    request_id:UUID
    return_origin:str|None=Field(default=None,max_length=200)

def permitted(context):
    if context.role not in {'OWNER','ADMIN','DISPATCHER'}:raise HTTPException(403,'Dispatch permission required for card-funded bookings')

async def create_cart(service,context,body):
    permitted(context)
    rows,total,currencies=await validate_checkout(service,context,body,check_wallet=False)
    if len(currencies)!=1 or not Decimal(1)<=total<=Decimal(10000):raise HTTPException(422,'Card baskets require one currency and a total between 1 and 10000. Split a larger basket or pay from wallet.')
    finance=service.finance
    require_payment_gateway(finance.settings)
    # Web checkout creation acquires connections sequentially. Only the booking
    # worker needs capacity for the basket, shipment and financial locks together.
    from backend.runtime_hosting import resolve_role
    role=resolve_role(getattr(finance.settings,'runtime_role','AUTO'),os.environ)
    capacity=service.pool.get_max_size() if hasattr(service.pool,'get_max_size') else finance.settings.db_pool_max_size
    if role!='WEB' and capacity<4:
        raise HTTPException(503,'The booking worker needs at least four database connections; checkout was not started')
    from backend.automation_three_partners import create_adapter,EasyPostAdapter,ShippoAdapter,verify_quote_connection
    from main import ClientRate
    environment='LIVE' if finance.settings.stripe_livemode else 'TEST'
    if finance.settings.provider_environment!=environment:raise HTTPException(403,'Carrier and card payment environments must match')
    accounts=await service.automation.repository.accounts(context)
    async with service.pool.acquire() as c:
        snapshots=await c.fetch('SELECT rate_snapshot FROM public.partner_shipping_offers WHERE tenant_id=$1 AND offer_id=ANY($2::uuid[])',context.tenant_id,[r.offer_id for r in body.offers])
    for row in snapshots:
        rate=ClientRate.model_validate(decoded(row['rate_snapshot']));account=next((a for a in accounts if a.id==rate.account_id),None)
        if not account:raise HTTPException(409,'Selected carrier connection is no longer enabled; request fresh rates')
        try:verify_quote_connection(account,rate)
        except Exception:raise HTTPException(409,'Carrier configuration changed; request fresh rates before paying') from None
        adapter=create_adapter(service.client,account,environment=environment)
        if environment=='TEST' and not isinstance(adapter,(EasyPostAdapter,ShippoAdapter)):raise HTTPException(403,'This connection has no verified non-billable label test contract. Choose another service before paying.')

    origin=checkout_return_base(finance.settings,body.return_origin,'success')
    cancel=checkout_return_base(finance.settings,body.return_origin,'cancel')
    selection=CheckoutSelection(offers=body.offers).model_dump(mode='json')['offers'];currency=next(iter(currencies))
    async with service.pool.acquire() as c:
        async with c.transaction():
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','cart-create:'+str(body.request_id))
            existing=await c.fetchrow('SELECT * FROM public.payment_carts WHERE id=$1 FOR UPDATE',body.request_id)
            if existing:
                if (existing['tenant_id']!=context.tenant_id or existing['requested_by']!=context.user_id or decoded(existing['offers'])!=selection or existing['amount']!=total):
                    raise HTTPException(409,'This basket request already belongs to another selection')
                if existing['status'] not in {'CREATING','AWAITING_PAYMENT'}:raise HTTPException(409,'This basket has already been paid or processed. Open its existing result.')
            else:
                await c.execute('''INSERT INTO public.payment_carts(id,tenant_id,requested_by,offers,amount,currency)
                    VALUES($1,$2,$3,$4::jsonb,$5,$6)''',body.request_id,context.tenant_id,context.user_id,json.dumps(selection),total,currency)
    await ensure_customer(finance,context,shipping_cart_id=body.request_id)
    from main import TopupRequest
    from urllib.parse import urlsplit,parse_qsl,urlencode,urlunsplit
    def returning(base,outcome):
        parts=urlsplit(checkout_redirect(base,outcome,body.request_id));q=dict(parse_qsl(parts.query));q['cart_id']=str(body.request_id)
        return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(q),''))
    checkout=await finance.create_checkout(context,TopupRequest(request_id=body.request_id,amount=total),return_urls=(returning(origin,'success'),returning(cancel,'cancel')),payment_label='EasyInvio.com shipping labels - '+str(len(selection))+' selected orders',shipping_cart_id=body.request_id)
    async with service.pool.acquire() as c:
        await c.execute("UPDATE public.payment_carts SET status='AWAITING_PAYMENT',updated_at=now() WHERE tenant_id=$1 AND id=$2 AND status='CREATING'",context.tenant_id,body.request_id)
    return {'cart_id':str(body.request_id),'topup_id':str(checkout.topup_id),'url':safe_checkout_url(checkout.checkout_url),'amount':format(total,'.2f'),'currency':currency,
        'mode':environment,'notice':'Card payment funds exactly this basket. Credit is consumed only for confirmed labels. Any unused amount remains in your wallet.'}

async def complete_cart(service,context,cart_id):
    permitted(context)
    from backend.runtime_hosting import resolve_role
    if resolve_role(getattr(service.finance.settings,'runtime_role','AUTO'),os.environ)=='WEB':
        return await web_cart_status(service,context,cart_id)
    async with service.card_limiter:
        return await _complete_cart(service,context,cart_id)

async def web_cart_status(service,context,cart_id):
    """Verify payment without holding a basket connection or purchasing a label.

    The existing durable cart and dedicated worker own native booking. Keeping
    this request free of the worker's nested session locks fits the web pool.
    """
    async with service.pool.acquire() as c:
        row=await c.fetchrow('SELECT * FROM public.payment_carts WHERE tenant_id=$1 AND id=$2',context.tenant_id,cart_id)
    if not row:raise HTTPException(404,'Basket not found')
    if row['status'] in {'COMPLETED','REVIEW_REQUIRED'}:
        return public_payload({'cart_id':str(cart_id),'status':row['status'],'amount':format(row['amount'],'.2f'),
                               'currency':row['currency'],'outcome':decoded(row['results']),'replayed':True})
    if row['status']=='BOOKING':return {'cart_id':str(cart_id),'status':'BOOKING'}
    # Financial reconciliation uses its existing tenant-bound, idempotent credit
    # ledger. No cart connection is held while it acquires a financial connection.
    payment=await reconcile_topup(service.finance,context,cart_id)
    return {'cart_id':str(cart_id),'status':'BOOKING' if payment['status']=='CREDITED' else 'AWAITING_PAYMENT',
            'payment_status':payment.get('payment_status',payment['status']),
            'notice':'Payment verified. Your shipping label is being prepared.' if payment['status']=='CREDITED'
                     else 'Waiting for verified card payment. Do not pay again if your card was charged.'}

async def _complete_cart(service,context,cart_id):
    permitted(context)
    async with service.pool.acquire() as c:
        key='cart-book:'+str(cart_id)
        if not await c.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))',key):return {'cart_id':str(cart_id),'status':'BOOKING'}
        try:
            row=await c.fetchrow('SELECT * FROM public.payment_carts WHERE tenant_id=$1 AND id=$2',context.tenant_id,cart_id)
            if not row:raise HTTPException(404,'Basket not found')
            if row['status'] in {'COMPLETED','REVIEW_REQUIRED'}:
                return public_payload({'cart_id':str(cart_id),'status':row['status'],'amount':format(row['amount'],'.2f'),'currency':row['currency'],'outcome':decoded(row['results']),'replayed':True})
            if row['status'] in {'CREATING','AWAITING_PAYMENT'} and datetime.now(timezone.utc)-row['updated_at']<timedelta(seconds=10):
                paid=await c.fetchval("SELECT status='CREDITED' FROM public.wallet_topups WHERE tenant_id=$1 AND id=$2",context.tenant_id,cart_id)
                if not paid:return {'cart_id':str(cart_id),'status':'AWAITING_PAYMENT'}
            payment=await reconcile_topup(service.finance,context,cart_id)
            if payment['status']=='EXPIRED':
                result={'results':[],'notice':'Card checkout expired without payment. No credit or labels were created. Request fresh rates and start another checkout.'}
                await c.execute("UPDATE public.payment_carts SET status='REVIEW_REQUIRED',results=$2::jsonb,updated_at=now() WHERE id=$1",cart_id,json.dumps(result))
                return {'cart_id':str(cart_id),'status':'REVIEW_REQUIRED','outcome':result}
            if payment['status']!='CREDITED':
                await c.execute('UPDATE public.payment_carts SET updated_at=now() WHERE id=$1',cart_id)
                return {'cart_id':str(cart_id),'status':'AWAITING_PAYMENT','payment_status':payment.get('payment_status','pending')}
            await c.execute("UPDATE public.payment_carts SET status='BOOKING',updated_at=now() WHERE id=$1",cart_id)
            selection=CheckoutSelection(offers=decoded(row['offers']))
            try:
                result=await checkout_orders(service,context,selection)
                statuses=[r['status'] for r in result['results']]
                status='COMPLETED' if all(s in {'BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED'} for s in statuses) else 'BOOKING' if any(s=='SYNC_PENDING' for s in statuses) else 'REVIEW_REQUIRED'
                in_progress=await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.shipments WHERE tenant_id=$1 AND id=ANY($2::uuid[]) AND status='BOOKING')",context.tenant_id,[x.shipment_id for x in selection.offers])
                if in_progress:status='BOOKING'
            except HTTPException as exc:
                message=exc.detail.get('message',exc.detail.get('code','Booking needs review')) if isinstance(exc.detail,dict) else str(exc.detail)
                result={'results':[],'notice':message+'. Payment is already verified; unused credit remains in your wallet. Request fresh rates and use wallet payment. Do not pay again.'}
                status='REVIEW_REQUIRED'
            except Exception:
                result={'results':[],'notice':'Payment is verified. Refresh the manifest and reconcile any submitted bookings before retrying; unused credit remains in the wallet.'};status='REVIEW_REQUIRED'
            if status=='BOOKING':
                for selected in selection.offers:
                    await c.execute("UPDATE public.shipments SET logistics_metadata=logistics_metadata||jsonb_build_object('payment_cart_id',$3::text) WHERE tenant_id=$1 AND id=$2 AND status='BOOKING' AND pricing_snapshot->'selected_rate'->>'offer_id'=$4",context.tenant_id,selected.shipment_id,str(cart_id),str(selected.offer_id))
            for outcome in result.get('results',[]):
                if outcome['status'] in {'BOOKED','SYNC_PENDING'}:
                    selected=next(x for x in selection.offers if str(x.shipment_id)==outcome['shipment_id'])
                    await c.execute("UPDATE public.shipments SET logistics_metadata=logistics_metadata||jsonb_build_object('payment_cart_id',$3::text) WHERE tenant_id=$1 AND id=$2 AND pricing_snapshot->'selected_rate'->>'offer_id'=$4",context.tenant_id,selected.shipment_id,str(cart_id),str(selected.offer_id))
            await c.execute('UPDATE public.payment_carts SET status=$2,results=$3::jsonb,updated_at=now() WHERE id=$1',cart_id,status,json.dumps(result))
            return public_payload({'cart_id':str(cart_id),'status':status,'amount':format(row['amount'],'.2f'),'currency':row['currency'],'outcome':result})
        finally:await c.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))',key)

async def cart_worker(service):
    while True:
        try:
            async with service.pool.acquire() as c:
                rows=await c.fetch('''SELECT p.id,p.tenant_id,p.requested_by,coalesce(u.role,'OWNER') AS role,
                    a.id AS assistance_session_id FROM public.payment_carts p LEFT JOIN public.users u
                    ON u.tenant_id=p.tenant_id AND u.auth_user_id=p.requested_by AND u.is_active AND u.role IN ('OWNER','ADMIN','DISPATCHER')
                    LEFT JOIN LATERAL (SELECT s.id FROM public.admin_client_assistance_sessions s
                      WHERE s.tenant_id=p.tenant_id AND s.actor_auth_user_id=p.requested_by
                      AND s.created_at<=p.created_at AND s.revoked_at IS NULL AND s.expires_at>now()
                      ORDER BY s.created_at DESC LIMIT 1) a ON true
                    JOIN public.wallet_topups w ON w.tenant_id=p.tenant_id AND w.id=p.id
                    WHERE p.status IN ('CREATING','AWAITING_PAYMENT','BOOKING') AND p.created_at>now()-interval '24 hours'
                    AND p.updated_at<now()-interval '15 seconds'
                    AND (u.role IS NOT NULL OR (a.id IS NOT NULL AND (p.requested_by=ANY($1::uuid[])
                     OR EXISTS(SELECT 1 FROM public.platform_staff f WHERE f.auth_user_id=p.requested_by AND f.is_active))))
                    ORDER BY p.updated_at LIMIT 5''',list(getattr(service.finance.settings,'platform_admin_user_ids',[])))
            for r in rows:
                try:
                    from main import TenantContext
                    context=TenantContext(r['tenant_id'],r['requested_by'],r['role'],'',r['assistance_session_id'])
                    await complete_cart(service,context,r['id'])
                except Exception:logging.getLogger(__name__).warning('Card basket verification deferred; durable basket retained')
        except Exception:logging.getLogger(__name__).warning('Card basket worker deferred; check payment schema and settings')
        await asyncio.sleep(15)

def build_router(authenticate):
    router=APIRouter(prefix='/api/v1/billing/carts',tags=['Card-funded booking baskets'])
    @router.post('')
    async def create(body:CardCart,request:Request,context=Depends(authenticate)):
        return await create_cart(request.app.state.partner_lifecycle,context,body)
    @router.post('/{cart_id}/complete')
    async def complete(cart_id:UUID,request:Request,context=Depends(authenticate)):
        return await complete_cart(request.app.state.partner_lifecycle,context,cart_id)
    return router
