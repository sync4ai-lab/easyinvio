"""Explicit internal review ownership and tenant-scoped append-only activity."""
import json

from fastapi import HTTPException

from backend.automation_freight_engine import processing_remedy


def present_ticket(row):
    result=dict(row)
    internal=bool(row.get('automation_failure_id'))
    insurance=bool(row.get('insurance_claim_id'))
    booked=bool(row.get('booked_at') and row.get('shipment_tracking_number'))
    result['ticket_type']='PROCESSING_ISSUE' if internal else 'CARRIER_EXCEPTION'
    result['responsibility']='EasyInvio internal support' if internal else 'Carrier tracking; shipper action may be required'
    if insurance:
        result['ticket_type']='INSURANCE_SUPPORT'
        result['responsibility']='EasyInvio support case; XCover assesses the insurer claim'
    if internal:
        result['ai_summary']=processing_remedy(row.get('error_code') or 'ORDER_SERVICE_FAILED')
        if str(row.get('error_code') or '').startswith('AI_RECOMMENDATION_'):
            result['ticket_title']='Quote recommendation assistance'
            result['ai_summary']=row.get('ai_summary') or 'Optional recommendation unavailable. Priced offers were returned without a badge; no booking or wallet change occurred.'
        if row.get('error_code') in {'RATE_QUOTES_UNAVAILABLE', 'FREIGHT_QUOTE_REQUESTED'}:
            result['ticket_title'] = 'Freight quote request' if row['error_code'] == 'FREIGHT_QUOTE_REQUESTED' else 'Rate availability investigation'
            result['ai_summary'] = row.get('ai_summary') or 'Review the quote reference and connected carrier services. No booking or payment occurred.'
    result['pod_state']=('NOT_BOOKED' if not booked else 'AWAITING_DELIVERY' if row.get('shipment_status')!='DELIVERED'
                         else 'AVAILABLE' if row.get('proof_of_delivery_url') else 'NOT_PROVIDED')
    notifications=row.get('notifications') or []
    if isinstance(notifications,str):notifications=json.loads(notifications)
    result['notifications']=notifications
    if internal or insurance:
        result['notification_explanation']='No merchant alert is queued for an internal preparation issue. Notes stay inside EasyInvio.'
        if insurance:
            result['notification_explanation']='Support notes do not submit a claim to XCover or confirm insurer review or payment.'
        elif result.get('ticket_title'):
            result['pod_state']='NOT_APPLICABLE'
            result['notification_explanation']='This is optional quote advice, not a shipment failure. No merchant alert is queued.'
    elif notifications:
        result['notification_explanation']='Delivery states below are receipts for queued WhatsApp alerts; accepted does not mean delivered.'
    else:
        result['notification_explanation']='No WhatsApp alert has been queued. A verified, opted-in merchant binding is required.'
    result['note_visibility']='Internal only; saving a note does not contact the carrier or notify the merchant.'
    return result


async def add_internal_note(pool,ticket_id,actor_id,note,*,tenant_id=None,start_review=True,resolve=False):
    async with pool.acquire() as connection:
        async with connection.transaction():
            if not await connection.fetchval("SELECT to_regclass('public.support_ticket_activity') IS NOT NULL"):
                raise HTTPException(503,'Apply migration 026 to record reviewer identity and note history')
            row=await connection.fetchrow('''SELECT id,tenant_id,status,manual_note FROM public.support_tickets
                WHERE id=$1 AND ($2::uuid IS NULL OR (tenant_id=$2 AND automation_failure_id IS NULL)) FOR UPDATE''',ticket_id,tenant_id)
            if row is None:raise HTTPException(404,'Ticket not found')
            if row['status'] not in {'OPEN','IN_REVIEW'}:
                raise HTTPException(409,'This ticket is archived; its review history is read-only')
            tenant=row['tenant_id']
            # Preserve notes written before activity auditing existed, without inventing an author.
            if row.get('manual_note') and not await connection.fetchval(
                    'SELECT EXISTS(SELECT 1 FROM public.support_ticket_activity WHERE tenant_id=$1 AND ticket_id=$2)',tenant,ticket_id):
                await connection.execute("""INSERT INTO public.support_ticket_activity
                    (tenant_id,ticket_id,actor_name,activity_type,note)
                    VALUES($1,$2,'Earlier note (reviewer not recorded)','INTERNAL_NOTE',$3)""",
                    tenant,ticket_id,row['manual_note'])
            name=await connection.fetchval('''SELECT coalesce(
                (SELECT nullif(full_name,'') FROM public.app_user_profiles WHERE auth_user_id=$1),
                (SELECT nullif(full_name,'') FROM public.users WHERE auth_user_id=$1 AND tenant_id=$2 LIMIT 1),
                'Workspace reviewer')''',actor_id,tenant)
            state='CLOSED' if resolve else 'IN_REVIEW' if start_review else row['status']
            await connection.execute('''UPDATE public.support_tickets SET manual_note=$3,status=$4,
                archived_at=CASE WHEN $4='CLOSED' THEN coalesce(archived_at,now()) ELSE archived_at END,
                reviewed_by_auth_user_id=CASE WHEN $5 THEN $6 ELSE reviewed_by_auth_user_id END,
                review_started_at=CASE WHEN $5 THEN coalesce(review_started_at,now()) ELSE review_started_at END
                WHERE tenant_id=$1 AND id=$2''',tenant,ticket_id,note,state,start_review,actor_id)
            await connection.execute('''INSERT INTO public.support_ticket_activity
                (tenant_id,ticket_id,actor_auth_user_id,actor_name,activity_type,note)
                SELECT $1,$2,$3,$4,$5,$6 FROM public.support_tickets WHERE tenant_id=$1 AND id=$2''',
                tenant,ticket_id,actor_id,str(name), 'RESOLVED' if resolve else 'INTERNAL_REVIEW' if start_review else 'INTERNAL_NOTE',note)
            return {'status':state,'ticket_id':str(ticket_id),'note_saved':True,'reviewer':str(name) if start_review else None,
                    'merchant_notified':False,'carrier_contacted':False,'visibility':'INTERNAL'}
