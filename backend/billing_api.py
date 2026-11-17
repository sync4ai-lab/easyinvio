"""Finance-scoped statements; commercial mutations require the actual customer Owner."""
import asyncio
import asyncpg
from datetime import datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,ConfigDict,AwareDatetime
from backend.subscription_lifecycle import ChangeRequest
from backend.statements import StatementService,statement_pdf,statement_csv,FINANCE_ROLES

class StatementPeriod(BaseModel):
    model_config=ConfigDict(extra='forbid')
    start:AwareDatetime|None=None
    end:AwareDatetime|None=None
    currency:Literal['GBP','EUR','USD']='GBP'

def services(request,context):
    if context.role not in FINANCE_ROLES:raise HTTPException(403,'Financial permission required')
    if not getattr(request.app.state.settings,'billing_lifecycle_enabled',False):raise HTTPException(503,'Billing lifecycle is not enabled on this deployment')
    lifecycle=request.app.state.subscription_lifecycle
    return lifecycle,StatementService(lifecycle.pool,request.app.state.settings)

def build_router(authenticate):
    async def private_response(response:Response):response.headers['Cache-Control']='private, no-store'
    router=APIRouter(prefix='/api/v1/billing',tags=['Billing and statements'],dependencies=[Depends(private_response)])
    async def change(request,context,action,body):
        lifecycle,_=services(request,context)
        try:return await lifecycle.command(context,action,body)
        except ValueError:raise HTTPException(409,'The agreement dates or plan choice require a fresh, reconciled preview') from None
        except asyncpg.UniqueViolationError:raise HTTPException(409,'A subscription operation is already in progress. Refresh billing before retrying.') from None
    @router.get('/subscription')
    async def subscription(request:Request,context=Depends(authenticate)):
        lifecycle,_=services(request,context);return await lifecycle.status(context)
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
    async def preview(request:Request,currency:Literal['GBP','EUR','USD']='GBP',context=Depends(authenticate)):
        _,service=services(request,context);return await service.generate(context,currency=currency,preview=True)
    @router.post('/statements')
    async def generate(body:StatementPeriod,request:Request,context=Depends(authenticate)):
        _,service=services(request,context);return await service.generate(context,body.start,body.end,body.currency)
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
    return router
