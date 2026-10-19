"""One-time completion of an authenticated, unsubmitted chat claim draft."""
import hashlib

from fastapi import HTTPException


async def complete_conversational_claim(connection, context, *, case_id, shipment_id, policy_id,
        reason, notes, old_digest, digest, state, submission_payload, photos):
    from backend.shipment_protection import insured_shipment, decimal_json
    await insured_shipment(connection, context.tenant_id, shipment_id)
    actor = await connection.fetchval('''SELECT auth_user_id FROM public.users
        WHERE tenant_id=$1 AND auth_user_id=$2 AND is_active''', context.tenant_id, context.user_id)
    if actor is None:
        raise HTTPException(403, 'Verified active workspace membership required')
    updated = await connection.fetchval('''UPDATE public.insurance_claim_cases c
        SET notes=$7,payload_sha256=$8,state=$9,submission_payload=$10::jsonb,updated_at=now()
        WHERE c.tenant_id=$1 AND c.id=$2 AND c.shipment_id=$3 AND c.policy_id=$4
        AND c.created_by=$5 AND c.reason=$6 AND c.payload_sha256=$11
        AND c.state='CLAIM_INGESTED' AND c.upstream_claim_id IS NULL AND c.submission_payload='{}'::jsonb
        AND NOT EXISTS(SELECT 1 FROM public.insurance_claim_evidence e WHERE e.tenant_id=c.tenant_id AND e.case_id=c.id)
        AND EXISTS(SELECT 1 FROM public.support_tickets t WHERE t.tenant_id=c.tenant_id
            AND t.insurance_claim_id=c.id AND t.prompt_version='conversation-intake-v1') RETURNING c.id''',
        context.tenant_id, case_id, shipment_id, policy_id, actor, reason, notes,
        digest, state, decimal_json(submission_payload), old_digest)
    if updated is None:
        return False
    await connection.execute('''INSERT INTO public.support_ticket_activity
        (tenant_id,ticket_id,actor_auth_user_id,actor_name,activity_type,note)
        SELECT tenant_id,id,$3,'Workspace claimant','INTERNAL_NOTE',$4 FROM public.support_tickets
        WHERE tenant_id=$1 AND insurance_claim_id=$2 AND prompt_version='conversation-intake-v1' ''',
        context.tenant_id, case_id, actor, 'Chat claim draft completed with reviewed evidence. ' + notes)
    await connection.execute('''UPDATE public.support_tickets SET prompt_version='conversation-completed-v1'
        WHERE tenant_id=$1 AND insurance_claim_id=$2 AND prompt_version='conversation-intake-v1' ''', context.tenant_id, case_id)
    for data, kind in photos:
        await connection.execute('''INSERT INTO public.insurance_claim_evidence
            (tenant_id,case_id,content_type,content_sha256,content) VALUES($1,$2,$3,$4,$5)''',
            context.tenant_id, case_id, kind, hashlib.sha256(data).hexdigest(), data)
    return True
