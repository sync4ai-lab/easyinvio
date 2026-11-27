"""Tenant-scoped, cursor-paginated wallet presentation; no money mutations."""
from datetime import datetime,timezone
from decimal import Decimal
from typing import Literal
from fastapi import Depends,HTTPException,Query,Request
from backend.subscription_lifecycle import document

def add_routes(router,authenticate):
    @router.get('/wallet-ledger')
    async def ledger(request:Request,category:Literal['ALL','TOPUPS','LABELS','SUBSCRIPTION']='ALL',
                     holds:bool=False,cursor:str|None=Query(default=None,max_length=200),
                     limit:int=Query(default=25,ge=1,le=100),context=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:raise HTTPException(403,'Financial permission required')
        before=None;identifier=None
        if cursor:
            try:
                at,identifier=cursor.split('|',1);before=datetime.fromisoformat(at)
                if before.tzinfo is None or not identifier or len(identifier)>80:raise ValueError()
            except ValueError:raise HTTPException(422,'Invalid ledger cursor') from None
        kinds={'ALL':None,'TOPUPS':['TOPUP','REFUND_DEBIT'],'LABELS':['CAPTURE','SHIPMENT_REFUND'],
               'SUBSCRIPTION':['SUBSCRIPTION_DEBIT']}[category]
        async with request.app.state.finance.pool.acquire() as c:
            wallet=await c.fetchrow('SELECT currency,balance,reserved_balance FROM public.wallets WHERE tenant_id=$1',context.tenant_id)
            if not wallet:raise HTTPException(404,'Wallet not provisioned')
            rows=await c.fetch('''SELECT l.id,l.created_at,l.entry_type,l.balance_delta,l.reserved_delta,l.balance_after,l.currency,
                r.shipment_id,coalesce(s.customer_reference,to_jsonb(l)->>'stripe_checkout_session_id',to_jsonb(l)->>'stripe_payment_intent_id',l.topup_id::text,l.id::text) AS reference
                FROM public.wallet_ledger l LEFT JOIN public.wallet_reservations r ON r.tenant_id=l.tenant_id AND r.id=l.reservation_id
                LEFT JOIN public.shipments s ON s.tenant_id=r.tenant_id AND s.id=r.shipment_id
                WHERE l.tenant_id=$1 AND l.currency=$2 AND ($3::text[] IS NULL OR l.entry_type=ANY($3::text[]))
                AND ($4::boolean OR l.entry_type NOT IN ('RESERVE','RELEASE'))
                AND ($5::timestamptz IS NULL OR (l.created_at,l.id::text)<($5,$6::text))
                ORDER BY l.created_at DESC,l.id::text DESC LIMIT $7''',context.tenant_id,wallet['currency'],kinds,holds,before,identifier,limit+1)
            summary=await c.fetchrow('''SELECT
                coalesce(sum(-l.balance_delta) FILTER(WHERE l.entry_type='CAPTURE'),0) AS shipping_gross,
                coalesce(sum(l.balance_delta) FILTER(WHERE l.entry_type='SHIPMENT_REFUND'),0) AS refunds_gross,
                sum(s.tax_amount) FILTER(WHERE l.entry_type='CAPTURE' AND -l.balance_delta=s.final_client_price) AS recorded_shipping_vat,
                count(*) FILTER(WHERE l.entry_type='CAPTURE' AND (s.tax_amount IS NULL OR s.final_client_price IS DISTINCT FROM -l.balance_delta)) AS missing_tax
                FROM public.wallet_ledger l LEFT JOIN public.wallet_reservations r ON r.tenant_id=l.tenant_id AND r.id=l.reservation_id
                LEFT JOIN public.shipments s ON s.tenant_id=r.tenant_id AND s.id=r.shipment_id
                WHERE l.tenant_id=$1 AND l.currency=$2 AND l.created_at>=date_trunc('month',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' ''',context.tenant_id,wallet['currency'])
        selected=rows[:limit]
        next_cursor=selected[-1]['created_at'].isoformat()+'|'+str(selected[-1]['id']) if len(rows)>limit else None
        return document({'entries':[dict(r) for r in selected],'next_cursor':next_cursor,'wallet':{**dict(wallet),'available':str(Decimal(str(wallet['balance']))-Decimal(str(wallet['reserved_balance'])))},
                         'month_to_date':dict(summary),'basis':'Posted wallet movements in UTC; external/card-funded shipments are shown in statements.'})
