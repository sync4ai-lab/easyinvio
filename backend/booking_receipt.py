"""Printable booking receipt from confirmed, tenant-owned shipment records."""
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle

def receipt_pdf(row):
    stream=BytesIO();styles=getSampleStyleSheet();styles['BodyText'].fontSize=10
    document=SimpleDocTemplate(stream,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=42)
    def text(value):return Paragraph(escape(str(value)),styles['BodyText'])
    story=[Paragraph('EasyInvio.com',styles['Title']),Paragraph('Shipping booking receipt',styles['Heading2']),Spacer(1,16)]
    if row.get('is_sandbox'):story.extend([text('SANDBOX / TEST BOOKING'),Spacer(1,10)])
    row=dict(row)
    if hasattr(row['booked_at'],'strftime'):row['booked_at']=row['booked_at'].strftime('%d %b %Y, %H:%M UTC')
    if row.get('payment_cart_id'):row['billing_plan']='Card payment through Stripe'
    row['billing_plan']={'PREPAID_WALLET':'Prepaid wallet','POSTPAID_30_DAY':'Postpaid - 30 days'}.get(row['billing_plan'],row['billing_plan'])
    for label,key in [('Booking / invoice reference','customer_reference'),('Client','company_name'),('Tracking number','tracking_number'),('Booked at (UTC)','booked_at'),('Billing plan','billing_plan')]:
        story.append(text(label+': '+str(row[key])))
    story.extend([Spacer(1,20),text('Route: '+str(row['origin_country'])+' to '+str(row['destination_country']))])
    currency=row['currency'];subtotal=row['final_client_price']-row['tax_amount']
    table=Table([[text('Description'),text('Amount')],[text('Shipping service'),text(f'{currency} {subtotal:.2f}')],
        [text('Recorded tax'),text(f'{currency} {row["tax_amount"]:.2f}')],[text('Total recorded shipping charge'),text(f'{currency} {row["final_client_price"]:.2f}')]],colWidths=[330,180])
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e2e8f0')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#94a3b8')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
    story.extend([Spacer(1,16),table,Spacer(1,20),text('Charges are recorded against the billing plan shown above. This booking receipt is not a VAT tax invoice.')])
    document.build(story);return stream.getvalue()
