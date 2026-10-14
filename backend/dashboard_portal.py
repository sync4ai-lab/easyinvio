"""Server-verified portal roles, owner analytics and support dashboard actions."""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from backend.admin_portal import authenticate_platform_owner
from backend.tracking_and_support import money
from backend.support_workflow import add_internal_note,present_ticket


class Intervention(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(min_length=3, max_length=2000)
    start_review: bool = False

class WorkspaceMember(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    auth_user_id: UUID
    full_name: str=Field(min_length=1,max_length=200)
    role: Literal['DISPATCHER','ACCOUNTANT']='DISPATCHER'

class StoreConfiguration(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    platform: Literal['SHOPIFY','WOOCOMMERCE','AMAZON']
    display_name: str=Field(min_length=1,max_length=200)

class StoreState(BaseModel):
    model_config=ConfigDict(extra='forbid')
    is_active: bool


def build_router(authenticate):
    router = APIRouter(prefix="/api/v1", tags=["Dashboard"])

    @router.get('/workspace/stores')
    async def stores(request: Request, context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:raise HTTPException(403,'Workspace financial or administrator role required')
        async with request.app.state.finance.pool.acquire() as c:
            rows=await c.fetch('''SELECT s.id,s.platform,s.display_name,s.is_active,(c.store_id IS NOT NULL) AS connection_saved
                FROM public.ecommerce_stores s LEFT JOIN public.workspace_store_connections c
                ON c.tenant_id=s.tenant_id AND c.store_id=s.id WHERE s.tenant_id=$1 ORDER BY s.display_name LIMIT 200''',context.tenant_id)
        return {'stores':[{'id':str(r['id']),'platform':r['platform'],'display_name':r['display_name'],'is_active':r['is_active'],'connection_saved':bool(r.get('connection_saved',False))} for r in rows], 'mode':'WORKSPACE_STORE_REGISTRY'}

    @router.post('/workspace/stores',status_code=201)
    async def create_store(body: StoreConfiguration, request: Request, context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN'}:raise HTTPException(403,'Workspace administrator permission required')
        async with request.app.state.finance.pool.acquire() as c:
            row=await c.fetchrow('INSERT INTO public.ecommerce_stores(tenant_id,platform,display_name) VALUES($1,$2,$3) RETURNING id',context.tenant_id,body.platform,body.display_name)
        return {'id':str(row['id']),'platform':body.platform,'display_name':body.display_name,'is_active':True}

    @router.patch('/workspace/stores/{store_id}')
    async def store_state(store_id: UUID, body: StoreState, request: Request, context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN'}:raise HTTPException(403,'Workspace administrator permission required')
        async with request.app.state.finance.pool.acquire() as c:
            row=await c.fetchrow('UPDATE public.ecommerce_stores SET is_active=$3 WHERE tenant_id=$1 AND id=$2 RETURNING id',context.tenant_id,store_id,body.is_active)
        if not row:raise HTTPException(404,'Workspace store not found')
        return {'id':str(store_id),'is_active':body.is_active}

    @router.get('/dispatch/summary')
    async def dispatch_summary(request: Request, context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','DISPATCHER'}:raise HTTPException(403,'Dispatch permission required')
        async with request.app.state.finance.pool.acquire() as connection:
            row=await connection.fetchrow("SELECT coalesce(sum(parcel_count),0) AS package_count FROM public.shipments WHERE tenant_id=$1 AND status IN ('BOOKED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED')",context.tenant_id)
        return {'package_count':row['package_count']}

    @router.post('/workspace/users',status_code=201)
    async def add_member(body: WorkspaceMember, request: Request, context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN'}:raise HTTPException(403,'Workspace administrator required')
        async with request.app.state.finance.pool.acquire() as connection:
            async with connection.transaction():
                # Auth provisioning is separate. Server-owned app metadata must
                # bind the existing principal to this tenant before enrollment.
                principal=await connection.fetchrow("SELECT raw_app_meta_data->>'tenant_id' AS tenant_id FROM auth.users WHERE id=$1",body.auth_user_id)
                if not principal or principal['tenant_id']!=str(context.tenant_id):
                    raise HTTPException(422,'Auth user must already be provisioned for this workspace')
                try:
                    member=await connection.fetchrow("INSERT INTO public.users(tenant_id,auth_user_id,role,full_name,is_active) VALUES($1,$2,$3,$4,true) RETURNING id",context.tenant_id,body.auth_user_id,body.role,body.full_name)
                except asyncpg.UniqueViolationError:
                    raise HTTPException(409,'Auth user is already enrolled') from None
        return {'id':str(member['id']),'tenant_id':str(context.tenant_id),'role':body.role,'full_name':body.full_name}

    @router.get("/profile")
    async def profile(request: Request):
        from fastapi.security import HTTPBearer
        credentials = await HTTPBearer(auto_error=False)(request)
        if request.headers.get('X-EasyInvio-Assistance'):
            context = await authenticate(request, credentials)
            assistance = request.state.client_assistance
            return {'portal_role': 'CLIENT', 'user_id': str(context.user_id), 'tenant_id': str(context.tenant_id),
                'workspace_role': 'OWNER', 'company_name': assistance['company_name'],
                'assistance': {'session_id': str(assistance['id']), 'actor_user_id': str(context.user_id),
                    'expires_at': assistance['expires_at'].isoformat()}}
        try:
            owner = await authenticate_platform_owner(request, credentials)
            return {"portal_role": "SUPER_ADMIN", "user_id": str(owner.user_id), "tenant_id": None}
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
        context = await authenticate(request, credentials)
        async with request.app.state.finance.pool.acquire() as connection:
            company=await connection.fetchval('SELECT company_name FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
        return {"portal_role": "CLIENT", "user_id": str(context.user_id), "tenant_id": str(context.tenant_id), "workspace_role": context.role,'company_name':str(company) if company else ''}

    @router.get("/admin/analytics/dashboard")
    async def platform_report(request: Request, start_date: date, end_date: date,
                              environment: Literal['PRODUCTION','SANDBOX']='PRODUCTION',
                              owner: Any = Depends(authenticate_platform_owner)):
        if end_date > datetime.now(timezone.utc).date():raise HTTPException(422,'Reporting dates cannot be in the future (UTC)')
        if end_date < start_date or end_date == date.max or (end_date-start_date).days > 366:
            raise HTTPException(422, "Use an ordered date range of at most 367 days")
        start = datetime.combine(start_date, datetime.min.time(), timezone.utc)
        end = datetime.combine(end_date+timedelta(days=1), datetime.min.time(), timezone.utc)
        sandbox = environment=='SANDBOX'
        async with request.app.state.finance.pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                totals = await connection.fetch("""SELECT currency,sum(final_client_price)::numeric AS revenue,
                    sum(profit_markup)::numeric AS margin,sum(parcel_count)::bigint AS package_count
                    FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
                    WHERE ((NOT t.is_sandbox AND NOT $3::boolean) OR (t.is_sandbox AND $3::boolean)) AND booked_at >= $1 AND booked_at < $2
                    AND status::text IN ('BOOKED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED') GROUP BY currency""", start, end,sandbox)
                tenants = await connection.fetchval("SELECT count(*) FROM public.tenants WHERE workspace_status='ACTIVE' AND is_sandbox=$1",sandbox)
                carriers = await connection.fetch("""SELECT coalesce(carrier_code,'Unassigned') AS carrier,sum(parcel_count)::bigint AS volume
                    FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
                    WHERE t.is_sandbox=$3 AND booked_at >= $1 AND booked_at < $2
                    AND status::text IN ('BOOKED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED')
                    GROUP BY carrier_code ORDER BY volume DESC""", start, end,sandbox)
                billing = await connection.fetch('''SELECT billing_plan,billing_status,count(*)::bigint AS company_count
                    FROM public.tenants WHERE is_sandbox=$1 GROUP BY billing_plan,billing_status ORDER BY billing_plan,billing_status''',sandbox)
                payments = await connection.fetch('''SELECT p.currency,p.status,count(*)::bigint AS payment_count,coalesce(sum(p.amount),0)::numeric AS amount
                    FROM public.wallet_topups p JOIN public.tenants t ON t.tenant_id=p.tenant_id
                    WHERE t.is_sandbox=$3 AND p.created_at>=$1 AND p.created_at<$2
                    GROUP BY p.currency,p.status ORDER BY p.currency,p.status''',start,end,sandbox)
                threads = await connection.fetch('''SELECT q.status,count(*)::bigint AS ticket_count FROM public.support_tickets q
                    JOIN public.tenants t ON t.tenant_id=q.tenant_id WHERE t.is_sandbox=$1 AND q.status IN ('OPEN','IN_REVIEW')
                    GROUP BY q.status ORDER BY q.status''',sandbox)
        return {"active_tenants": tenants, "totals_by_currency": [{"currency": row["currency"], "revenue": money(row["revenue"]), "margin": money(row["margin"]), "package_count": row["package_count"]} for row in totals],
                "carriers": [dict(row) for row in carriers], "margin_basis": "stored gross markup; net profit is unavailable",
                'environment':environment,'start_date':start_date.isoformat(),'end_date':end_date.isoformat(),
                'billing_pipeline':[dict(row) for row in billing],
                'payment_pipeline':[{'currency':r['currency'],'status':r['status'],'payment_count':r['payment_count'],'amount':money(r['amount'])} for r in payments],
                'active_support':[dict(row) for row in threads]}

    async def tickets_query(request, tenant_id=None, sandbox=None, active_only=False):
        async with request.app.state.finance.pool.acquire() as connection:
            activity_ready=await connection.fetchval("SELECT to_regclass('public.support_ticket_activity') IS NOT NULL")
            history="""coalesce((SELECT jsonb_agg(jsonb_build_object('actor',h.actor_name,'type',h.activity_type,'note',h.note,'created_at',h.created_at)
                ORDER BY h.created_at,h.id) FROM public.support_ticket_activity h WHERE h.tenant_id=t.tenant_id AND h.ticket_id=t.id),'[]'::jsonb)""" if activity_ready else "'[]'::jsonb"
            rows = await connection.fetch("""SELECT t.id,t.tenant_id,t.shipment_id,t.status,t.ai_summary,t.ai_method,
                t.automation_failure_id,to_jsonb(t)->>'insurance_claim_id' AS insurance_claim_id,a.error_code,s.status AS shipment_status,s.booked_at,s.tracking_number AS shipment_tracking_number,
                CASE WHEN $1::uuid IS NULL THEN s.logistics_metadata->'purchase_failure' END AS purchase_failure,
                to_jsonb(t)->>'reviewed_by_auth_user_id' AS reviewer_id,to_jsonb(t)->>'review_started_at' AS review_started_at,
                coalesce((SELECT nullif(p.full_name,'') FROM public.app_user_profiles p
                    WHERE p.auth_user_id::text=to_jsonb(t)->>'reviewed_by_auth_user_id'),
                    (SELECT nullif(u.full_name,'') FROM public.users u WHERE u.tenant_id=t.tenant_id
                     AND u.auth_user_id::text=to_jsonb(t)->>'reviewed_by_auth_user_id' LIMIT 1)) AS reviewer_name,
                """+history+""" AS activity,
                t.manual_note,t.archived_at,t.created_at,coalesce(s.tracking_number,a.order_reference) AS tracking_number,s.destination_country,s.proof_of_delivery_url,
                company.company_name,
                coalesce((SELECT jsonb_agg(jsonb_build_object('status',m.status,'updated_at',m.delivery_updated_at,'error_code',m.last_error_code))
                    FROM public.support_message_outbox m WHERE m.tenant_id=t.tenant_id AND m.ticket_id=t.id),'[]'::jsonb) AS notifications
                FROM public.support_tickets t LEFT JOIN public.shipments s ON s.id=t.shipment_id AND s.tenant_id=t.tenant_id
                JOIN public.tenants company ON company.tenant_id=t.tenant_id
                LEFT JOIN public.automation_failures a ON a.id=t.automation_failure_id AND a.tenant_id=t.tenant_id
                WHERE ($1::uuid IS NULL OR t.tenant_id=$1) AND ($2::boolean IS NULL OR company.is_sandbox=$2)
                AND (NOT $3::boolean OR t.status IN ('OPEN','IN_REVIEW'))
                AND ($1::uuid IS NULL OR t.automation_failure_id IS NULL)
                ORDER BY t.created_at DESC LIMIT 100""", tenant_id,sandbox,active_only)
        import json
        return {"tickets": [{**present_ticket(row), "id": str(row["id"]), "tenant_id": str(row["tenant_id"]), "shipment_id": str(row["shipment_id"]) if row['shipment_id'] else None,
                'activity':json.loads(row['activity']) if isinstance(row.get('activity'),str) else row.get('activity',[]),
                'notifications':json.loads(row['notifications']) if isinstance(row.get('notifications'),str) else row.get('notifications',[]),
                "created_at": row["created_at"].isoformat()} for row in rows]}

    @router.get("/support/tickets")
    async def client_tickets(request: Request, context: Any = Depends(authenticate)):
        return await tickets_query(request, context.tenant_id)

    @router.get("/admin/support/tickets")
    async def all_tickets(request: Request, environment: Literal['PRODUCTION','SANDBOX']='PRODUCTION',active_only:bool=False,owner: Any = Depends(authenticate_platform_owner)):
        return await tickets_query(request,sandbox=environment=='SANDBOX',active_only=active_only)

    @router.post("/support/tickets/{ticket_id}/intervene")
    async def intervene(ticket_id: UUID, body: Intervention, request: Request, context: Any = Depends(authenticate)):
        if context.role not in {"OWNER","ADMIN","DISPATCHER"}:
            raise HTTPException(403,"Dispatch permission required")
        return await add_internal_note(request.app.state.finance.pool,ticket_id,context.user_id,body.note,
            tenant_id=context.tenant_id,start_review=body.start_review)

    @router.post("/admin/support/tickets/{ticket_id}/intervene")
    async def admin_intervene(ticket_id: UUID, body: Intervention, request: Request, owner: Any = Depends(authenticate_platform_owner)):
        return await add_internal_note(request.app.state.finance.pool,ticket_id,owner.user_id,body.note,start_review=body.start_review)

    @router.post('/support/tickets/{ticket_id}/resolve')
    async def resolve(ticket_id: UUID, request: Request, context: Any = Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','DISPATCHER'}:
            raise HTTPException(403,'Dispatch permission required')
        return await add_internal_note(request.app.state.finance.pool,ticket_id,context.user_id,
            'Internal support review closed. No carrier or merchant notification was sent.',
            tenant_id=context.tenant_id,start_review=True,resolve=True)

    @router.post('/admin/support/tickets/{ticket_id}/resolve')
    async def admin_resolve(ticket_id: UUID, request: Request, owner: Any = Depends(authenticate_platform_owner)):
        return await add_internal_note(request.app.state.finance.pool,ticket_id,owner.user_id,
            'Internal support review closed. No carrier or merchant notification was sent.',start_review=True,resolve=True)

    from backend.workspace_settings import build_router as settings_router
    router.include_router(settings_router(authenticate))
    return router
