"""Finance-scoped statements; commercial mutations require the actual customer Owner."""
import asyncio
import asyncpg
from datetime import datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,AwareDatetime,Field
from backend.subscription_lifecycle import ChangeRequest,statements_enabled,require_statements
from backend.statements import StatementService,statement_pdf,statement_csv,FINANCE_ROLES

class StatementPeriod(BaseModel):
    model_config=ConfigDict(extra='forbid')
    start:AwareDatetime|None=None
    end:AwareDatetime|None=None
    currency:Literal['GBP','EUR','USD']='GBP'

class StatementMonth(BaseModel):
    model_config=ConfigDict(extra='forbid')
    year:int=Field(ge=2000,le=2100)
    month:int=Field(ge=1,le=12)
    currency:Literal['GBP','EUR','USD']='GBP'

def services(request,context):
    if context.role not in FINANCE_ROLES:raise HTTPException(403,'Financial permission required')
    require_statements(request.app.state.settings)
    lifecycle=request.app.state.subscription_lifecycle
    return lifecycle,StatementService(lifecycle.pool,request.app.state.settings)

def build_router(authenticate):
    async def private_response(response:Response):response.headers['Cache-Control']='private, no-store'
    router=APIRouter(prefix='/api/v1/billing',tags=['Billing and statements'],dependencies=[Depends(private_response)])
    @router.get('/capabilities')
    async def capabilities(request:Request,context=Depends(authenticate)):
        if context.role not in FINANCE_ROLES:raise HTTPException(403,'Financial permission required')
        settings=request.app.state.settings;available=statements_enabled(settings)
        lifecycle=bool(getattr(settings,'billing_lifecycle_enabled',False))
        return {'statements_enabled':available,'subscription_changes_enabled':lifecycle,
            'message':('Statements are available. Subscription changes are disabled.' if not lifecycle else 'Billing is available.') if available
                else 'Billing statements are not enabled for this deployment. Contact the platform administrator to enable statement access.'}
    async def change(request,context,action,body):
        lifecycle,_=services(request,context)
        try:return await lifecycle.command(context,action,body)
        except ValueError:raise HTTPException(409,'The agreement dates or plan choice require a fresh, reconciled preview') from None
        except asyncpg.UniqueViolationError:raise HTTPException(409,'A subscription operation is already in progress. Refresh billing before retrying.') from None
    @router.get('/subscription')
    async def subscription(request:Request,context=Depends(authenticate)):
        if context.role not in FINANCE_ROLES:raise HTTPException(403,'Financial permission required')
        return await request.app.state.subscription_lifecycle.status(context)
    @router.post('/subscription/reconcile')
    async def reconcile(request:Request,context=Depends(authenticate)):
        from backend.subscription_billing import reconcile_checkout
        return await reconcile_checkout(request,context)
    @router.post('/subscription/{operation_id}/process')
    async def process_operation(operation_id:UUID,request:Request,context=Depends(authenticate)):
        from backend.subscription_lifecycle import owner
        owner(context);service=request.app.state.subscription_lifecycle;service.ready()
        async with service.pool.acquire() as c:
            found=await c.fetchval('SELECT id FROM public.subscription_operations WHERE id=$1 AND tenant_id=$2 AND actor_auth_user_id=$3',operation_id,context.tenant_id,context.user_id)
        if not found:raise HTTPException(404,'Plan change not found')
        await service.execute(found)
        return await service.status(context)
    @router.post('/subscription/upgrade')
    async def upgrade(body:ChangeRequest,request:Request,context=Depends(authenticate)):
        return await change(request,context,'UPGRADE',body)
    @router.post('/subscription/downgrade')
    async def downgrade(body:ChangeRequest,request:Request,context=Depends(authenticate)):
        return await change(request,context,'DOWNGRADE',body)
    @router.post('/subscription/cancel')
    async def cancel(body:ChangeRequest,request:Request,context=Depends(authenticate)):
        return await change(request,context,'CANCEL',body)
    @router.get('/statements')
    async def statements(request:Request,context=Depends(authenticate)):
        _,service=services(request,context);return await service.list(context)
    @router.get('/statements/preview')
    async def preview(request:Request,currency:Literal['GBP','EUR','USD']='GBP',start:AwareDatetime|None=None,end:AwareDatetime|None=None,context=Depends(authenticate)):
        _,service=services(request,context);return await service.generate(context,start=start,end=end,currency=currency,preview=True)
    @router.get('/statements/preview/{kind}')
    async def preview_export(kind:Literal['pdf','csv'],request:Request,currency:Literal['GBP','EUR','USD']='GBP',start:AwareDatetime|None=None,end:AwareDatetime|None=None,context=Depends(authenticate)):
        _,service=services(request,context);data=await service.generate(context,start=start,end=end,currency=currency,preview=True)
        content=await asyncio.to_thread(statement_pdf if kind=='pdf' else statement_csv,data)
        return Response(content,media_type='application/pdf' if kind=='pdf' else 'text/csv',headers={
            'Cache-Control':'private, no-store','Content-Disposition':f'attachment; filename="EasyInvio-current-preview.{kind}"'})
    @router.post('/statements')
    async def generate(body:StatementPeriod,request:Request,context=Depends(authenticate)):
        _,service=services(request,context);return await service.generate(context,body.start,body.end,body.currency)
    @router.post('/statements/monthly')
    async def monthly(body:StatementMonth,request:Request,context=Depends(authenticate)):
        from datetime import timezone
        start=datetime(body.year,body.month,1,tzinfo=timezone.utc)
        end=start.replace(year=start.year+1,month=1) if body.month==12 else start.replace(month=start.month+1)
        _,service=services(request,context)
        return await service.generate(context,start,end,body.currency)
    @router.get('/statements/{statement_id}')
    async def detail(statement_id:UUID,request:Request,context=Depends(authenticate)):
        _,service=services(request,context);return await service.detail(context,statement_id)
    @router.get('/statements/{statement_id}/pdf')
    async def pdf(statement_id:UUID,request:Request,context=Depends(authenticate)):
        _,service=services(request,context);data=await service.detail(context,statement_id)
        content=await asyncio.to_thread(statement_pdf,data)
        return Response(content,media_type='application/pdf',headers={'Cache-Control':'private, no-store','Content-Disposition':'attachment; filename="'+data['statement_number']+'.pdf"'})
    @router.get('/statements/{statement_id}/csv')
    async def csv(statement_id:UUID,request:Request,context=Depends(authenticate)):
        _,service=services(request,context);data=await service.detail(context,statement_id)
        return Response(statement_csv(data),media_type='text/csv',headers={'Cache-Control':'private, no-store','Content-Disposition':'attachment; filename="'+data['statement_number']+'.csv"'})
    from backend.billing_ledger import add_routes
    add_routes(router,authenticate)
    return router
