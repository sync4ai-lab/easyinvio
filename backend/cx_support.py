"""Tenant-scoped support intake. Never voids postage or mutates money."""
from typing import Literal
from uuid import UUID
from asyncpg import Connection
from pydantic import BaseModel, ConfigDict, Field


class SupportCase(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    tenant_id: UUID
    shipment_id: UUID
    kind: Literal['SERVICE_REQUEST','COMPLAINT','RETURN_REQUEST','REFUND_INQUIRY']
    category: Literal['DAMAGED','MISSING_DELAYED','ADDRESS_CHANGE','BILLING_OTHER']
    summary: str = Field(min_length=10,max_length=1000)
    customer_request_id: UUID | None = None


async def record_case(connection: Connection, case: SupportCase) -> UUID:
    """Caller owns the transaction; idempotent ticket and notification staging."""
    ticket = await connection.fetchval('''INSERT INTO public.support_tickets
      (id,tenant_id,shipment_id,status,ai_summary,ai_method,prompt_version,cx_request_id,cx_kind,issue_category,tracking_customer_request_id)
      VALUES($1,$2,$3,'OPEN',$4,'DETERMINISTIC_CX','whatsapp-cx-v1',$1,$5,$6,$7)
      ON CONFLICT(cx_request_id) DO UPDATE SET cx_request_id=excluded.cx_request_id
      WHERE support_tickets.tenant_id=excluded.tenant_id AND support_tickets.shipment_id=excluded.shipment_id
        AND support_tickets.ai_summary=excluded.ai_summary AND support_tickets.cx_kind=excluded.cx_kind
        AND support_tickets.issue_category=excluded.issue_category
        AND support_tickets.tracking_customer_request_id IS NOT DISTINCT FROM excluded.tracking_customer_request_id
      RETURNING id''',case.request_id,case.tenant_id,case.shipment_id,case.summary,
      case.kind,case.category,case.customer_request_id)
    if ticket is None:
        from fastapi import HTTPException
        raise HTTPException(409,'Support request identity conflict')
    await connection.execute('''INSERT INTO public.support_message_outbox
      (tenant_id,ticket_id,recipient_e164,body,status,message_kind)
      SELECT DISTINCT $1::uuid,$2::uuid,b.sender_e164,$3::text,'STAGED','CUSTOMER_CX'
      FROM public.whatsapp_bindings b JOIN public.users u ON u.tenant_id=b.tenant_id AND u.id=b.user_id
      WHERE b.tenant_id=$1 AND b.is_active AND b.verified_at IS NOT NULL AND b.notification_opt_in
        AND NOT coalesce((to_jsonb(b)->>'alerts_paused')::boolean,false)
        AND u.is_active AND u.role IN ('OWNER','ADMIN')
      ON CONFLICT(tenant_id,ticket_id,recipient_e164) DO NOTHING''',case.tenant_id,ticket,
      f'EasyInvio case {ticket}: {case.kind.replace("_"," ")} / {case.category.replace("_"," ")}. Open Support to review.')
    return ticket
