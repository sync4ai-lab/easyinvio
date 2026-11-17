"""Immutable account activity statements, distinct from VAT invoices and wallet funding.

Ledger captures are the wallet source of truth. A booked shipment without a
wallet capture is shown as external/postpaid activity, never as a wallet debit.
Dispute estimates and projected overages are not posted charges or refunds.
"""
from __future__ import annotations
import csv,hashlib,io,json
import asyncpg
from collections import defaultdict
from datetime import datetime,timezone
from decimal import Decimal
from uuid import UUID,uuid4
from xml.sax.saxutils import escape
from fastapi import HTTPException
from backend.subscription_math import money,utc
from backend.subscription_lifecycle import document,decoded

LIMIT=10000
FINANCE_ROLES={'OWNER','ADMIN','ACCOUNTANT'}

def period_bounds(start=None,end=None,*,now=None):
    now=utc(now or datetime.now(timezone.utc))
    first=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    if start is None and end is None:
        end=first;start=(first.replace(year=first.year-1,month=12) if first.month==1 else first.replace(month=first.month-1))
    elif start is None or end is None:raise HTTPException(422,'Supply both period start and exclusive end')
    start,end=utc(start),utc(end)
    if start>=end or (end-start).total_seconds()>32*86400 or end>now:
        raise HTTPException(422,'Choose a completed period of at most 32 days; use Preview for the current month')
    return start,end

def build_snapshot(tenant,currency,start,end,opening,ledger,external,invoices,events,disputes,*,reference='PREVIEW',refunds=()):
    opening=money(opening);running=opening;lines=[];carriers={};tax_complete=True
    totals={key:Decimal(0) for key in ('total_topups','subscription_net','shipping_net','refunds_net','tax_total','gross_total','other_wallet_credits','other_wallet_debits','unclassified_gross')}
    def line(identifier,at,kind,gross,net,tax,wallet_delta=0,**extra):
        nonlocal running,tax_complete
        gross=money(gross);delta=money(wallet_delta)
        item={'id':str(identifier),'occurred_at':utc(at).isoformat(),'type':kind,'gross_amount':str(gross),
            'net_amount':str(money(net)) if net is not None else None,'tax_amount':str(money(tax)) if tax is not None else None,
            'wallet_delta':str(delta),**document(extra)}
        lines.append(item)
        if kind not in {'TOPUP','TOPUP_REVERSAL','OTHER_CREDIT'}:
            totals['gross_total']+=gross
            if tax is not None:totals['tax_total']+=money(tax)
            elif gross:tax_complete=False;totals['unclassified_gross']+=gross
        return item
    for order,r in enumerate(ledger):
        delta=money(r['balance_delta']);kind=r['entry_type'];net=tax=None;gross=-delta
        shipment_id=r.get('shipment_id');original=money(r['shipment_gross']) if r.get('shipment_gross') is not None else None
        recorded_tax=money(r['shipment_tax']) if r.get('shipment_tax') is not None else None
        payload=decoded(r.get('operation_payload')) if r.get('operation_payload') else {}
        if kind=='TOPUP':totals['total_topups']+=delta;gross=Decimal(0);net=tax=Decimal(0)
        elif kind=='REFUND_DEBIT':kind='TOPUP_REVERSAL';totals['total_topups']+=delta;gross=Decimal(0);net=tax=Decimal(0)
        elif kind=='CAPTURE' and shipment_id:
            kind='SHIPPING';tax=recorded_tax if original==gross else None;net=gross-tax if tax is not None else None
            if net is not None:totals['shipping_net']+=net
        elif kind=='SHIPMENT_REFUND':
            kind='SHIPPING_REFUND';tax=-recorded_tax if original==delta and recorded_tax is not None else None
            net=gross-tax if tax is not None else None
            if net is not None:totals['refunds_net']-=net
        elif kind=='SUBSCRIPTION_DEBIT':
            kind='SUBSCRIPTION';tax=money(payload.get('wallet_tax_amount',0));net=gross-tax;totals['subscription_net']+=net
        elif delta>0:kind='OTHER_CREDIT';gross=Decimal(0);totals['other_wallet_credits']+=delta
        else:kind='OTHER_CHARGE';totals['other_wallet_debits']-=delta
        item=line('wallet:'+str(r['id']),r['created_at'],kind,gross,net,tax,delta,shipment_id=shipment_id,
            tracking_number=r.get('tracking_number'),carrier=r.get('carrier_code'),route=r.get('route'),
            parcel_count=r.get('parcel_count') or 0,reference=r.get('reference'),funding='WALLET',
            recorded_wallet_after=str(money(r['balance_after'])),_ledger_order=order)
    for r in external:
        gross=money(r['final_client_price']);tax=money(r['tax_amount']) if r.get('tax_amount') is not None else None
        net=gross-tax if tax is not None else None
        if net is not None:totals['shipping_net']+=net
        line('shipment:'+str(r['id']),r['booked_at'],'SHIPPING',gross,net,tax,shipment_id=r['id'],
            tracking_number=r.get('tracking_number'),carrier=r.get('carrier_code'),route=r.get('route'),
            parcel_count=r.get('parcel_count') or 1,funding='EXTERNAL_OR_POSTPAID',reference=r.get('customer_reference'))
    for r in invoices:
        gross=money(r['invoice_gross_gbp'] if r.get('invoice_gross_gbp') is not None else r['amount_paid_gbp'])
        net=money(r['invoice_net_gbp']) if r.get('invoice_net_gbp') is not None else None
        tax=money(r['invoice_tax_gbp']) if r.get('invoice_tax_gbp') is not None else None
        if net is not None:totals['subscription_net']+=net
        line('invoice:'+r['stripe_invoice_id'],r['created_at'],'SUBSCRIPTION',gross,net,tax,funding='STRIPE',
            reference=r['stripe_invoice_id'],paid_amount=str(money(r['amount_paid_gbp'])),effective_at=r['paid_at'])
    for r in refunds:
        net=money(r['net_amount']);tax=money(r['tax_amount']);gross=money(r['gross_amount'])
        totals['subscription_net']-=net
        line('refund:'+str(r['id']),r['settled_at'],'SUBSCRIPTION_REFUND',-gross,-net,-tax,
            funding='STRIPE',reference=r['provider_refund_id'],original_invoice=r['stripe_invoice_id'])
    lines.sort(key=lambda r:(r['occurred_at'],0 if r['id'].startswith('wallet:') else 1,r.get('_ledger_order',0),r['id']))
    # Balance order uses the ledger's immutable monotonic ID for identical timestamps.
    # SQL supplies chronological ledger rows; external invoices never move the wallet.
    ledger_balances={}
    for r in ledger:
        running+=money(r['balance_delta'])
        if running!=money(r['balance_after']):raise HTTPException(409,'Wallet history does not reconcile; request support review before issuing a statement')
        ledger_balances['wallet:'+str(r['id'])]=running
    cursor=opening
    for r in lines:
        r.pop('_ledger_order',None)
        if r['id'] in ledger_balances:cursor=ledger_balances[r['id']]
        r['running_wallet_balance']=str(cursor)
        if r['type'] in {'SHIPPING','SHIPPING_REFUND'}:
            carrier=r.get('carrier') or 'Not recorded'
            c=carriers.setdefault(carrier,{'carrier':carrier,'parcels':0,'refunded_count':0,'net':Decimal(0),'tax':Decimal(0),'gross':Decimal(0),'tax_complete':True})
            c['parcels']+=int(r.get('parcel_count') or 1) if r['type']=='SHIPPING' else 0
            c['refunded_count']+=1 if r['type']=='SHIPPING_REFUND' else 0
            c['gross']+=Decimal(r['gross_amount'])
            if r['net_amount'] is not None:c['net']+=Decimal(r['net_amount'])
            if r['tax_amount'] is not None:c['tax']+=Decimal(r['tax_amount'])
            else:c['tax_complete']=False
    return document({'schema_version':1,'statement_number':reference,'tenant_id':tenant['tenant_id'],
        'workspace_name':tenant['company_name'],'is_sandbox':tenant['is_sandbox'],'currency':currency,
        'period_start':start,'period_end':end,'opening_balance':opening,'closing_balance':running,
        **{key:money(value) for key,value in totals.items()},'tax_complete':tax_complete,
        'carrier_summary':[{**r,**{key:money(r[key]) for key in ('net','tax','gross')}} for r in carriers.values()],'transactions':lines,
        'plan_and_proration':[{**{k:row[k] for k in ('event_type','amount','effective_at','created_at')},'breakdown':decoded(row['breakdown'])} for row in events],
        'disputes':disputes,'notice':'Account activity statement, not a VAT invoice. Recorded tax only; missing tax is not treated as zero. Top-ups fund your wallet and are not purchases. Stripe subscription charges do not debit your wallet. Dispute estimates and projected overages are not refunds or charges. Late postings appear in the period they are recorded.'})

class StatementService:
    def __init__(self,pool,settings):self.pool=pool;self.settings=settings
    def ready(self,context):
        if context.role not in FINANCE_ROLES:raise HTTPException(403,'Financial permission required')
        if not getattr(self.settings,'billing_lifecycle_enabled',False):raise HTTPException(503,'Billing statements are not enabled on this deployment')

    async def list(self,context):
        self.ready(context)
        async with self.pool.acquire() as c:
            rows=await c.fetch('''SELECT id,statement_number,period_start,period_end,currency,gross_total,closing_balance,created_at
             FROM public.billing_statements WHERE tenant_id=$1 ORDER BY period_start DESC,id DESC LIMIT 100''',context.tenant_id)
        return {'statements':document([dict(r) for r in rows])}

    async def detail(self,context,statement_id):
        self.ready(context)
        async with self.pool.acquire() as c:row=await c.fetchrow('SELECT statement_snapshot,snapshot_sha256 FROM public.billing_statements WHERE tenant_id=$1 AND id=$2',context.tenant_id,statement_id)
        if not row:raise HTTPException(404,'Statement not found in this workspace')
        snapshot=decoded(row['statement_snapshot'])
        if hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':')).encode()).hexdigest()!=row['snapshot_sha256']:
            raise HTTPException(409,'Statement integrity requires review')
        return snapshot

    async def generate(self,context,start=None,end=None,currency='GBP',*,preview=False):
        # A stable database snapshot keeps balances and transaction rows coherent.
        # Retry a concurrent finalization after acquiring the period lock.
        for attempt in range(3):
            try:return await self._generate(context,start,end,currency,preview=preview)
            except (asyncpg.SerializationError,asyncpg.UniqueViolationError):
                if attempt==2:raise HTTPException(503,'Statement activity changed concurrently. Please retry.') from None

    async def _generate(self,context,start=None,end=None,currency='GBP',*,preview=False):
        self.ready(context)
        if currency not in {'GBP','EUR','USD'}:raise HTTPException(422,'Unsupported statement currency')
        if preview and start is None and end is None:
            end=datetime.now(timezone.utc);start=end.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        else:start,end=period_bounds(start,end)
        async with self.pool.acquire() as c:
            async with c.transaction(isolation='repeatable_read'):
                if not preview:
                    await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,52))','statement:'+str(context.tenant_id)+start.isoformat()+end.isoformat()+currency)
                    existing=await c.fetchrow('SELECT statement_snapshot FROM public.billing_statements WHERE tenant_id=$1 AND period_start=$2 AND period_end=$3 AND currency=$4',context.tenant_id,start,end,currency)
                    if existing:return decoded(existing['statement_snapshot'])
                tenant=await c.fetchrow('SELECT tenant_id,company_name,is_sandbox FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
                if not tenant:raise HTTPException(404,'Workspace not found')
                wallet=await c.fetchrow('SELECT currency,balance FROM public.wallets WHERE tenant_id=$1',context.tenant_id)
                prior=await c.fetchval('SELECT balance_after FROM public.wallet_ledger WHERE tenant_id=$1 AND currency=$2 AND created_at<$3 ORDER BY created_at DESC,id DESC LIMIT 1',context.tenant_id,currency,start)
                first=await c.fetchrow('SELECT balance_after,balance_delta FROM public.wallet_ledger WHERE tenant_id=$1 AND currency=$2 AND created_at>=$3 ORDER BY created_at,id LIMIT 1',context.tenant_id,currency,start)
                if prior is not None:opening=money(prior)
                elif first:opening=money(first['balance_after'])-money(first['balance_delta'])
                else:opening=money(wallet['balance']) if wallet and wallet['currency']==currency else Decimal(0)
                ledger=await c.fetch('''SELECT l.id,l.created_at,l.entry_type,l.balance_delta,l.balance_after,l.reserved_after,
                 r.shipment_id,s.final_client_price AS shipment_gross,s.tax_amount AS shipment_tax,s.tracking_number,s.carrier_code,s.parcel_count,
                 concat(s.origin_country,' → ',s.destination_country) AS route,coalesce(s.customer_reference,l.topup_id::text) AS reference,
                 o.payload AS operation_payload FROM public.wallet_ledger l
                 LEFT JOIN public.wallet_reservations r ON r.tenant_id=l.tenant_id AND r.id=l.reservation_id
                 LEFT JOIN public.shipments s ON s.tenant_id=r.tenant_id AND s.id=r.shipment_id
                 LEFT JOIN public.subscription_operations o ON o.tenant_id=l.tenant_id AND o.id=l.subscription_operation_id
                 WHERE l.tenant_id=$1 AND l.currency=$2 AND l.created_at>=$3 AND l.created_at<$4 AND l.balance_delta<>0
                 ORDER BY l.created_at,l.id LIMIT 10001''',context.tenant_id,currency,start,end)
                external=await c.fetch('''SELECT s.id,s.booked_at,s.final_client_price,s.tax_amount,s.tracking_number,s.carrier_code,s.parcel_count,
                 s.customer_reference,concat(s.origin_country,' → ',s.destination_country) AS route
                 FROM public.shipments s WHERE s.tenant_id=$1 AND s.currency=$2 AND s.booked_at>=$3 AND s.booked_at<$4
                 AND NOT EXISTS(SELECT 1 FROM public.wallet_ledger l JOIN public.wallet_reservations r ON r.tenant_id=l.tenant_id AND r.id=l.reservation_id
                  WHERE r.tenant_id=s.tenant_id AND r.shipment_id=s.id AND l.entry_type='CAPTURE') ORDER BY s.booked_at,s.id LIMIT 10001''',context.tenant_id,currency,start,end)
                invoices=await c.fetch('''SELECT * FROM public.subscription_invoice_receipts WHERE tenant_id=$1 AND created_at>=$2 AND created_at<$3 ORDER BY created_at,stripe_invoice_id LIMIT 10001''',context.tenant_id,start,end) if currency=='GBP' else []
                refunds=await c.fetch("SELECT * FROM public.subscription_refunds WHERE tenant_id=$1 AND state='SUCCEEDED' AND settled_at>=$2 AND settled_at<$3 ORDER BY settled_at,id LIMIT 10001",context.tenant_id,start,end) if currency=='GBP' else []
                events=await c.fetch('''SELECT event_type,amount,effective_at,breakdown,created_at FROM public.subscription_change_events
                 WHERE tenant_id=$1 AND created_at>=$2 AND created_at<$3 ORDER BY created_at,id LIMIT 10001''',context.tenant_id,start,end) if currency=='GBP' else []
                disputes=await c.fetch('''SELECT status,count(*) AS count,sum(estimated_overcharge)::text AS estimated_overcharge
                 FROM public.billing_disputes WHERE tenant_id=$1 AND currency=$2 AND created_at>=$3 AND created_at<$4 GROUP BY status''',context.tenant_id,currency,start,end)
                if len(ledger)+len(external)+len(invoices)+len(refunds)>LIMIT or len(events)>LIMIT:raise HTTPException(422,'Choose a shorter statement period; maximum 10,000 financial lines')
                sid=uuid4();reference='PREVIEW' if preview else 'EI-'+start.strftime('%Y%m')+'-'+sid.hex[:20].upper()
                snapshot=build_snapshot(dict(tenant),currency,start,end,opening,[dict(r) for r in ledger],[dict(r) for r in external],
                    [dict(r) for r in invoices],[dict(r) for r in events],[dict(r) for r in disputes],reference=reference,refunds=[dict(r) for r in refunds])
                snapshot['id']=str(sid) if not preview else None;snapshot['preview']=preview
                snapshot['wallet_currency_applicable']=bool(wallet and wallet['currency']==currency)
                if not preview:
                    canonical=json.dumps(snapshot,sort_keys=True,separators=(',',':'));digest=hashlib.sha256(canonical.encode()).hexdigest()
                    await c.execute('''INSERT INTO public.billing_statements(id,tenant_id,statement_number,period_start,period_end,currency,
                     opening_balance,total_topups,subscription_net,shipping_net,refunds_net,tax_total,gross_total,closing_balance,statement_snapshot,snapshot_sha256)
                     VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16)''',sid,context.tenant_id,reference,start,end,currency,
                     *[Decimal(snapshot[k]) for k in ('opening_balance','total_topups','subscription_net','shipping_net','refunds_net','tax_total','gross_total','closing_balance')],canonical,digest)
                return snapshot

def statement_csv(snapshot):
    stream=io.StringIO(newline='');w=csv.writer(stream)
    w.writerow(['Statement',snapshot['statement_number']]);w.writerow(['Currency',snapshot['currency']])
    w.writerow(['Date UTC','Type','Reference','Shipment','Tracking','Carrier','Route','Net','Tax','Gross','Wallet change','Wallet balance','Funding'])
    def safe(value):
        value='' if value is None else str(value)
        return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
    for r in snapshot['transactions']:
        w.writerow([safe(r.get(k)) for k in ('occurred_at','type','reference','shipment_id','tracking_number','carrier','route')]+
            [r.get(k) if r.get(k) is not None else 'Not supplied' for k in ('net_amount','tax_amount','gross_amount','wallet_delta','running_wallet_balance')]+[safe(r.get('funding'))])
    return stream.getvalue().encode('utf-8-sig')

def statement_pdf(snapshot):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak
    from reportlab.lib.enums import TA_RIGHT
    output=io.BytesIO();styles=getSampleStyleSheet()
    styles.add(ParagraphStyle('SmallBilling',fontName='Helvetica',fontSize=8,leading=11,spaceAfter=3,wordWrap='CJK'))
    styles.add(ParagraphStyle('RightBilling',parent=styles['SmallBilling'],alignment=TA_RIGHT))
    styles.add(ParagraphStyle('HeaderBilling',parent=styles['SmallBilling'],fontSize=7.5,wordWrap=None))
    slate=colors.HexColor('#0F172A');indigo=colors.HexColor('#4F46E5');muted=colors.HexColor('#64748B')
    doc=SimpleDocTemplate(output,pagesize=A4,leftMargin=40,rightMargin=40,topMargin=100,bottomMargin=48)
    def p(value,style='SmallBilling'):return Paragraph(escape(str(value if value is not None else 'Not supplied')),styles[style])
    def table(rows,widths,left_columns=1):
        t=Table([[p(v,'HeaderBilling' if number==0 else 'SmallBilling' if i<left_columns else 'RightBilling') for i,v in enumerate(row)] for number,row in enumerate(rows)],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E2E8F0')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),1,indigo),('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#CBD5E1')),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]));return t
    def page(canvas,document):
        canvas.saveState();canvas.setFillColor(slate);canvas.rect(0,A4[1]-76,A4[0],76,fill=1,stroke=0)
        canvas.setFillColor(colors.white);canvas.setFont('Helvetica-Bold',20);canvas.drawString(40,A4[1]-35,'EasyInvio.com')
        canvas.setFont('Helvetica',9);canvas.drawString(40,A4[1]-54,'Account activity statement'+(' - SANDBOX' if snapshot['is_sandbox'] else ''))
        canvas.setFillColor(muted);canvas.setFont('Helvetica',8);canvas.drawString(40,27,snapshot['statement_number']);canvas.drawRightString(A4[0]-40,27,'Page '+str(document.page));canvas.restoreState()
    story=[p(snapshot['workspace_name'],'Heading2'),p(snapshot['statement_number']),p(snapshot['period_start'][:10]+' to '+snapshot['period_end'][:10]+' (exclusive), UTC'),Spacer(1,14),p('A. Account and balance summary','Heading2')]
    summary=[['Account summary',snapshot['currency']],['Opening wallet balance',snapshot['opening_balance']],['Wallet funding / top-up reversals',snapshot['total_topups']],
        ['Known subscription net charges',snapshot['subscription_net']],['Known shipping net charges',snapshot['shipping_net']],['Known label refund net credits',snapshot['refunds_net']],
        ['Recorded tax',snapshot['tax_total']],['Total recorded charges less settled credits',snapshot['gross_total']],['Closing wallet balance',snapshot['closing_balance']]]
    story+=[table(summary,[350,165]),Spacer(1,10),p(snapshot['notice'])]
    if not snapshot['tax_complete']:story.append(p('Tax information is incomplete. Unknown tax and net amounts are shown as Not supplied; consult the original provider invoices.'))
    story+=[Spacer(1,12),p('B. Plan changes and proration','Heading2')]
    for e in snapshot['plan_and_proration']:
        breakdown=decoded(e['breakdown']);facts=breakdown.get('breakdown',breakdown)
        story.append(p(e['event_type']+' | '+str(e['effective_at'])+' | '+snapshot['currency']+' '+str(e['amount'])))
        for key in ('source_plan','target_plan','total_days','remaining_days','daily_rate','prorated_amount','uncovered_days','final_notice_prorated_amount'):
            if key in facts:story.append(p(key.replace('_',' ').title()+': '+str(facts[key])))
        if facts.get('annual_clawback'):
            a=facts['annual_clawback'];story.append(p('Annual discount removed: elapsed service and 30-day notice repriced at standard monthly rates.'))
            for key in ('verified_annual_prepaid_net','usage_at_monthly_price','notice_at_monthly_price','net_refund','additional_balance_for_review'):
                story.append(p(key.replace('_',' ').title()+': '+str(a[key])))
    if not snapshot['plan_and_proration']:story.append(p('No recorded plan changes in this period. Base software charges appear in the itemized transactions below.'))
    story+=[Spacer(1,14),p('C. Carrier usage','Heading2'),table([['Carrier','Parcels','Refunds','Known net','Recorded tax','Gross']]+[[r['carrier'],r['parcels'],r['refunded_count'],r['net'],r['tax'] if r['tax_complete'] else 'Incomplete',r['gross']] for r in snapshot['carrier_summary']],[165,50,55,80,80,85]),PageBreak(),p('D. Itemized transactions','Heading2')]
    rows=[['Date / transaction','Reference / carrier / route','Net','Tax','Gross','Wallet change','Wallet balance']]
    for r in snapshot['transactions']:
        rows.append([r['occurred_at'][:16].replace('T',' ')+' '+r['type'].replace('_',' '),
            ' | '.join(str(r[k]) for k in ('reference','shipment_id','tracking_number','carrier','route') if r.get(k)),
            r['net_amount'],r['tax_amount'],r['gross_amount'],r['wallet_delta'],r['running_wallet_balance']])
    if len(rows)==1:rows.append(['No transactions','','','','','',''])
    story.append(table(rows,[85,155,55,45,55,55,65],left_columns=2));doc.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()
