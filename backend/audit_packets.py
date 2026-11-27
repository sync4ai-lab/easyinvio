"""Evidence packets and explicitly requested support intake; never sends a dispute."""
import asyncio,csv,io,json
from uuid import UUID,uuid5,NAMESPACE_URL
from html import escape
from fastapi import Depends,HTTPException,Request,Response

def csv_cell(value):
    text=str(value if value is not None else '')
    return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text

def packet(row,kind):
    details={k:json.loads(row[k]) if isinstance(row[k],str) else row[k] for k in ('findings','baseline','invoice_line')}
    values=[('Invoice',row['invoice_reference']),('Dispute',row['id']),('Shipment',row['shipment_id']),
            ('Currency',row['currency']),('Potential overcharge',row['estimated_overcharge']),
            ('Review status',row['status']),('Findings',json.dumps(details['findings'])),
            ('Booking evidence',json.dumps(details['baseline'])),('Invoice evidence',json.dumps(details['invoice_line'])),
            ('Review request',row['email_draft'])]
    if kind=='csv':
        out=io.StringIO();writer=csv.writer(out);writer.writerow(['Field','Recorded evidence'])
        writer.writerows([[csv_cell(k),csv_cell(v)] for k,v in values]);return out.getvalue().encode('utf-8-sig')
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    out=io.BytesIO();styles=getSampleStyleSheet();story=[Paragraph('Carrier invoice review packet',styles['Title'])]
    for key,value in values:story.extend([Paragraph(escape(key),styles['Heading3']),Paragraph(escape(str(value)).replace('\n','<br/>'),styles['BodyText']),Spacer(1,8)])
    story.append(Paragraph('Evidence for carrier review. Liability and refunds require confirmation. No submission or payment is made by exporting this packet.',styles['BodyText']))
    SimpleDocTemplate(out).build(story);return out.getvalue()

def add_routes(router,authenticate):
    async def get(request,context,identifier):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:raise HTTPException(403,'Financial permission required')
        async with request.app.state.finance.pool.acquire() as c:
            row=await c.fetchrow('SELECT * FROM public.billing_disputes WHERE tenant_id=$1 AND id=$2',context.tenant_id,identifier)
        if not row:raise HTTPException(404,'Dispute not found in this workspace')
        return row
    @router.get('/billing-disputes/{identifier}/export/{kind}')
    async def export(identifier:UUID,kind:str,request:Request,context=Depends(authenticate)):
        if kind not in {'pdf','csv'}:raise HTTPException(404,'Export format not supported')
        row=await get(request,context,identifier);content=await asyncio.to_thread(packet,row,kind)
        return Response(content,media_type='application/pdf' if kind=='pdf' else 'text/csv',headers={
            'Cache-Control':'private, no-store','Content-Disposition':f'attachment; filename="dispute-{identifier}.{kind}"'})
    @router.post('/billing-disputes/{identifier}/support-case')
    async def support(identifier:UUID,request:Request,context=Depends(authenticate)):
        if getattr(context,'assistance_session_id',None):raise HTTPException(403,'Use your own financial workspace to log a dispute case')
        row=await get(request,context,identifier)
        ticket=uuid5(NAMESPACE_URL,'easyinvio:billing-dispute:'+str(identifier))
        summary=f"Carrier invoice {row['invoice_reference']}: review {row['estimated_overcharge']} {row['currency']} potential discrepancy. Evidence packet {identifier}."
        async with request.app.state.finance.pool.acquire() as c:
            await c.execute('''INSERT INTO public.support_tickets
                (id,tenant_id,shipment_id,status,ai_summary,ai_method,prompt_version,cx_request_id,cx_kind,issue_category)
                VALUES($1,$2,$3,'OPEN',$4,'DETERMINISTIC_BILLING','billing-review-v1',$1,'COMPLAINT','BILLING_OTHER')
                ON CONFLICT(cx_request_id) DO NOTHING''',ticket,context.tenant_id,row['shipment_id'],summary)
        return {'ticket_id':str(ticket),'status':'OPEN','message':'Support case logged. No carrier submission or refund has been made.'}
