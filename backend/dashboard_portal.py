"""Server-verified portal roles, owner analytics and support dashboard actions."""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from backend.admin_portal import authenticate_platform_owner


class Intervention(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    note: str = Field(min_length=3, max_length=2000)

class WorkspaceMember(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    auth_user_id: UUID
    full_name: str=Field(min_length=1,max_length=200)
    role: Literal['ADMIN','DISPATCHER','ACCOUNTANT']='DISPATCHER'

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
            rows=await c.fetch('SELECT id,platform,display_name,is_active FROM public.ecommerce_stores WHERE tenant_id=$1 ORDER BY display_name LIMIT 200',context.tenant_id)
        return {'stores':[{'id':str(r['id']),'platform':r['platform'],'display_name':r['display_name'],'is_active':r['is_active']} for r in rows], 'mode':'SIMULATED_IMPORT_AND_TRACKING'}

    @router.post('/workspace/stores',status_code=201)
    async def create_store(body: StoreConfiguration, request: Request, context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:raise HTTPException(403,'Workspace configuration permission required')
        async with request.app.state.finance.pool.acquire() as c:
            row=await c.fetchrow('INSERT INTO public.ecommerce_stores(tenant_id,platform,display_name) VALUES($1,$2,$3) RETURNING id',context.tenant_id,body.platform,body.display_name)
        return {'id':str(row['id']),'platform':body.platform,'display_name':body.display_name,'is_active':True}

    @router.patch('/workspace/stores/{store_id}')
    async def store_state(store_id: UUID, body: StoreState, request: Request, context: Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:raise HTTPException(403,'Workspace configuration permission required')
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
                              owner: Any = Depends(authenticate_platform_owner)):
        if end_date < start_date or end_date == date.max or (end_date-start_date).days > 366:
            raise HTTPException(422, "Use an ordered date range of at most 367 days")
        start = datetime.combine(start_date, datetime.min.time(), timezone.utc)
        end = datetime.combine(end_date+timedelta(days=1), datetime.min.time(), timezone.utc)
        async with request.app.state.finance.pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                totals = await connection.fetch("""SELECT currency,sum(final_client_price)::numeric AS revenue,
                    sum(profit_markup)::numeric AS margin,sum(parcel_count)::bigint AS package_count
                    FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
                    WHERE NOT t.is_sandbox AND booked_at >= $1 AND booked_at < $2
                    AND status::text IN ('BOOKED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED') GROUP BY currency""", start, end)
                tenants = await connection.fetchval("SELECT count(*) FROM public.tenants WHERE workspace_status='ACTIVE' AND NOT is_sandbox")
                carriers = await connection.fetch("""SELECT coalesce(carrier_code,'Unassigned') AS carrier,sum(parcel_count)::bigint AS volume
                    FROM public.shipments s JOIN public.tenants t ON t.tenant_id=s.tenant_id
                    WHERE NOT t.is_sandbox AND booked_at >= $1 AND booked_at < $2
                    AND status::text IN ('BOOKED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED')
                    GROUP BY carrier_code ORDER BY volume DESC LIMIT 20""", start, end)
        return {"active_tenants": tenants, "totals_by_currency": [{"currency": row["currency"], "revenue": format(row["revenue"],'.2f'), "margin": format(row["margin"],'.2f'), "package_count": row["package_count"]} for row in totals],
                "carriers": [dict(row) for row in carriers], "margin_basis": "stored gross markup; net profit is unavailable"}

    async def tickets_query(request, tenant_id=None):
        async with request.app.state.finance.pool.acquire() as connection:
            rows = await connection.fetch("""SELECT t.id,t.tenant_id,t.shipment_id,t.status,t.ai_summary,t.ai_method,
                t.manual_note,t.archived_at,t.created_at,coalesce(s.tracking_number,a.order_reference) AS tracking_number,s.destination_country,s.proof_of_delivery_url
                FROM public.support_tickets t LEFT JOIN public.shipments s ON s.id=t.shipment_id AND s.tenant_id=t.tenant_id
                LEFT JOIN public.automation_failures a ON a.id=t.automation_failure_id AND a.tenant_id=t.tenant_id
                WHERE ($1::uuid IS NULL OR t.tenant_id=$1) ORDER BY t.created_at DESC LIMIT 100""", tenant_id)
        return {"tickets": [{**dict(row), "id": str(row["id"]), "tenant_id": str(row["tenant_id"]), "shipment_id": str(row["shipment_id"]), "created_at": row["created_at"].isoformat()} for row in rows]}

    @router.get("/support/tickets")
    async def client_tickets(request: Request, context: Any = Depends(authenticate)):
        return await tickets_query(request, context.tenant_id)

    @router.get("/admin/support/tickets")
    async def all_tickets(request: Request, owner: Any = Depends(authenticate_platform_owner)):
        return await tickets_query(request)

    @router.post("/support/tickets/{ticket_id}/intervene")
    async def intervene(ticket_id: UUID, body: Intervention, request: Request, context: Any = Depends(authenticate)):
        if context.role not in {"OWNER","ADMIN","DISPATCHER"}:
            raise HTTPException(403,"Dispatch permission required")
        async with request.app.state.finance.pool.acquire() as connection:
            result = await connection.execute("UPDATE public.support_tickets SET manual_note=$3,status='IN_REVIEW' WHERE tenant_id=$1 AND id=$2 AND status IN ('OPEN','IN_REVIEW')", context.tenant_id,ticket_id,body.note)
        if result == 'UPDATE 0':
            raise HTTPException(404,"Ticket not found")
        return {"status":"IN_REVIEW","ticket_id":str(ticket_id)}

    @router.post("/admin/support/tickets/{ticket_id}/intervene")
    async def admin_intervene(ticket_id: UUID, body: Intervention, request: Request, owner: Any = Depends(authenticate_platform_owner)):
        async with request.app.state.finance.pool.acquire() as connection:
            result = await connection.execute("UPDATE public.support_tickets SET manual_note=$2,status='IN_REVIEW' WHERE id=$1 AND status IN ('OPEN','IN_REVIEW')", ticket_id,body.note)
        if result == 'UPDATE 0':
            raise HTTPException(404,"Ticket not found")
        return {"status":"IN_REVIEW","ticket_id":str(ticket_id)}

    @router.post('/support/tickets/{ticket_id}/resolve')
    async def resolve(ticket_id: UUID, request: Request, context: Any = Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','DISPATCHER'}:
            raise HTTPException(403,'Dispatch permission required')
        async with request.app.state.finance.pool.acquire() as connection:
            result=await connection.execute("UPDATE public.support_tickets SET status='CLOSED',archived_at=coalesce(archived_at,now()) WHERE tenant_id=$1 AND id=$2",context.tenant_id,ticket_id)
        if result=='UPDATE 0':raise HTTPException(404,'Ticket not found')
        return {'status':'CLOSED','ticket_id':str(ticket_id)}

    return router
