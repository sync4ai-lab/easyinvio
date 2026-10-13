"""Tenant-owned settings, verified email invitations and durable dispute drafts."""
from uuid import UUID,uuid4
from urllib.parse import urlsplit
import asyncpg,httpx,hashlib
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,SecretStr
from typing import Any,Literal
from backend.identity import IdentityRoute,recovery_limit

class Invite(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    first_name:str=Field(min_length=1,max_length=100)
    last_name:str=Field(min_length=1,max_length=100)
    email:str=Field(max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    role:Literal['DISPATCHER','ACCOUNTANT']
class Accept(BaseModel):
    model_config=ConfigDict(extra='forbid',hide_input_in_errors=True)
    access_token:SecretStr=Field(min_length=20,max_length=16000)
    password:SecretStr=Field(min_length=12,max_length=128)
class MemberUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    role:Literal['DISPATCHER','ACCOUNTANT']
    is_active:bool
class CompanyUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    company_name:str=Field(min_length=1,max_length=200)
    workspace_name:str=Field(min_length=1,max_length=200)
    billing_email:str=Field(max_length=254,pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
class Draft(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    content:str=Field(min_length=10,max_length=12000)

def owner(context):
    if context.role not in {'OWNER','ADMIN'}:raise HTTPException(403,'Workspace owner permission required')
async def invitation_limit(pool,tenant_id):
    bucket=hashlib.sha256(('workspace-invitations:'+str(tenant_id)).encode()).hexdigest()
    async with pool.acquire() as c:
        count=await c.fetchval("""INSERT INTO public.app_login_limits(bucket,attempts) VALUES($1,1)
            ON CONFLICT(bucket) DO UPDATE SET
            attempts=CASE WHEN app_login_limits.window_start<now()-interval '1 hour' THEN 1 ELSE app_login_limits.attempts+1 END,
            window_start=CASE WHEN app_login_limits.window_start<now()-interval '1 hour' THEN now() ELSE app_login_limits.window_start END
            RETURNING attempts""",bucket)
    if count>20:raise HTTPException(429,'Workspace invitation limit reached. Try again later.',headers={'Retry-After':'3600'})

def headers(settings,admin=False):
    key=(settings.supabase_service_role_key if admin else settings.supabase_publishable_key).get_secret_value()
    return {'apikey':key,'Authorization':'Bearer '+key}

async def deliver_invitation(pool,settings,identifier,email,full_name):
    redirect=settings.auth_recovery_redirect_url
    parsed=urlsplit(redirect)
    if parsed.username or parsed.password or parsed.fragment or not parsed.netloc or (parsed.scheme!='https' and not(parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1'))):raise HTTPException(503,'Configure the application authentication redirect URL')
    try:
        async with httpx.AsyncClient(trust_env=False,timeout=15) as client:
            response=await client.post(settings.supabase_url+'/auth/v1/invite',params={'redirect_to':redirect},headers=headers(settings,True),json={'email':email,'data':{'full_name':full_name}})
            if response.status_code==429:raise HTTPException(429,'Email provider limit reached. Wait before resending.',headers={'Retry-After':'60'})
            if response.status_code not in (200,201):raise HTTPException(503,'Invitation email was not confirmed. Check Supabase email delivery configuration and limits.')
            principal=response.json();uid=UUID(principal['id'])
            if principal.get('email','').casefold()!=email:raise ValueError('identity mismatch')
        async with pool.acquire() as c:
            await c.execute("UPDATE public.workspace_invitations SET auth_user_id=$2,status='PENDING' WHERE id=$1 AND status='SENDING'",identifier,uid)
    except (httpx.HTTPError,ValueError,KeyError,HTTPException) as exc:
        async with pool.acquire() as c:
            await c.execute("UPDATE public.workspace_invitations SET status='FAILED' WHERE id=$1 AND status='SENDING'",identifier)
        if isinstance(exc,HTTPException):raise
        raise HTTPException(503,'Invitation delivery needs reconciliation. No workspace access has been granted.') from None
    return {'status':'PENDING','message':'Invitation email accepted for delivery. The user must verify their email and choose a password before workspace access is activated.'}

def build_router(authenticate):
    router=APIRouter(prefix='',tags=['Workspace settings'],route_class=IdentityRoute)
    @router.get('/workspace/settings')
    async def settings(request:Request,context:Any=Depends(authenticate)):
        owner(context)
        async with request.app.state.finance.pool.acquire() as c:
            company=await c.fetchrow('SELECT company_name,workspace_name,billing_email FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
            members=await c.fetch("SELECT u.id,u.full_name,u.role,u.is_active,a.email FROM public.users u JOIN auth.users a ON a.id=u.auth_user_id WHERE u.tenant_id=$1 ORDER BY u.created_at",context.tenant_id)
            invites=await c.fetch("SELECT id,first_name,last_name,email,role,status,expires_at FROM public.workspace_invitations WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT 100",context.tenant_id)
        return {'company':dict(company),'members':[dict(m) for m in members],'invitations':[dict(i) for i in invites]}
    @router.patch('/workspace/settings')
    async def company(body:CompanyUpdate,request:Request,context:Any=Depends(authenticate)):
        owner(context)
        async with request.app.state.finance.pool.acquire() as c:
            await c.execute("UPDATE public.tenants SET company_name=$2,workspace_name=$3,billing_email=$4 WHERE tenant_id=$1",context.tenant_id,body.company_name,body.workspace_name,body.billing_email)
        return {'saved':True}
    @router.patch('/workspace/users/{member_id}')
    async def member(member_id:UUID,body:MemberUpdate,request:Request,context:Any=Depends(authenticate)):
        owner(context)
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                row=await c.fetchrow("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND id=$2 AND role IN ('DISPATCHER','ACCOUNTANT') FOR UPDATE",context.tenant_id,member_id)
                if not row:raise HTTPException(404,'Editable workspace user not found')
                await c.execute('UPDATE public.users SET role=$3,is_active=$4 WHERE tenant_id=$1 AND id=$2',context.tenant_id,member_id,body.role,body.is_active)
                await c.execute('DELETE FROM public.app_auth_sessions WHERE auth_user_id=$1',row['auth_user_id'])
        return {'saved':True,'sessions_revoked':True}
    @router.post('/workspace/invitations',status_code=201)
    async def invite(body:Invite,request:Request,context:Any=Depends(authenticate)):
        owner(context);await invitation_limit(request.app.state.finance.pool,context.tenant_id)
        settings=request.app.state.settings;email=body.email.casefold();identifier=uuid4()
        redirect=settings.auth_recovery_redirect_url;parsed=urlsplit(redirect)
        if parsed.username or parsed.password or parsed.fragment or not parsed.netloc or (parsed.scheme!='https' and not(parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1'))):
            raise HTTPException(503,'Configure the application authentication redirect URL')
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                await c.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))",'workspace-invite:'+email)
                if await c.fetchval('SELECT EXISTS(SELECT 1 FROM auth.users WHERE lower(email)=$1)',email):
                    raise HTTPException(409,'This email already has an identity. Contact platform support to avoid assigning an existing account to another workspace.')
                try:
                    await c.execute("UPDATE public.workspace_invitations SET status='CANCELLED' WHERE lower(email)=$1 AND status IN ('SENDING','PENDING') AND expires_at<now()",email)
                    await c.execute('INSERT INTO public.workspace_invitations(id,tenant_id,email,first_name,last_name,role,invited_by) VALUES($1,$2,$3,$4,$5,$6,$7)',identifier,context.tenant_id,email,body.first_name,body.last_name,body.role,context.user_id)
                except asyncpg.UniqueViolationError:raise HTTPException(409,'An invitation is already pending for this email') from None
        return await deliver_invitation(request.app.state.finance.pool,settings,identifier,email,body.first_name+' '+body.last_name)
    @router.post('/workspace/invitations/{invite_id}/resend')
    async def resend(invite_id:UUID,request:Request,context:Any=Depends(authenticate)):
        owner(context);await invitation_limit(request.app.state.finance.pool,context.tenant_id)
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                row=await c.fetchrow("SELECT i.* FROM public.workspace_invitations i WHERE tenant_id=$1 AND id=$2 AND status IN ('PENDING','FAILED','CANCELLED') FOR UPDATE",context.tenant_id,invite_id)
                if not row:raise HTTPException(404,'Resendable invitation not found')
                if row['auth_user_id'] and await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)',row['auth_user_id']):raise HTTPException(409,'This user already has workspace access')
                try:await c.execute("UPDATE public.workspace_invitations SET status='SENDING',expires_at=now()+interval '24 hours' WHERE id=$1",invite_id)
                except asyncpg.UniqueViolationError:raise HTTPException(409,'Another invitation is already pending for this email') from None
        return await deliver_invitation(request.app.state.finance.pool,request.app.state.settings,invite_id,row['email'],row['first_name']+' '+row['last_name'])
    @router.post('/workspace/invitations/{invite_id}/cancel')
    async def cancel(invite_id:UUID,request:Request,context:Any=Depends(authenticate)):
        owner(context)
        async with request.app.state.finance.pool.acquire() as c:
            result=await c.execute("UPDATE public.workspace_invitations SET status='CANCELLED' WHERE tenant_id=$1 AND id=$2 AND status IN ('SENDING','PENDING')",context.tenant_id,invite_id)
        if result=='UPDATE 0':raise HTTPException(404,'Pending invitation not found')
        return {'cancelled':True}
    @router.post('/auth/accept-invitation')
    async def accept(body:Accept,request:Request):
        await recovery_limit(request);settings=request.app.state.settings
        h=headers(settings);h['Authorization']='Bearer '+body.access_token.get_secret_value()
        try:
            async with httpx.AsyncClient(trust_env=False,timeout=15) as client:
                response=await client.get(settings.supabase_url+'/auth/v1/user',headers=h)
                if response.status_code!=200:raise HTTPException(400,'Invitation session is invalid or expired. Contact your workspace owner.')
                principal=response.json();uid=UUID(principal['id']);email=principal.get('email','').casefold()
                if not principal.get('email_confirmed_at'):raise HTTPException(403,'Verify your invitation email first')
                async with request.app.state.finance.pool.acquire() as c:
                    async with c.transaction():
                        invitation=await c.fetchrow("SELECT i.* FROM public.workspace_invitations i JOIN public.tenants t USING(tenant_id) WHERE i.auth_user_id=$1 AND lower(i.email)=$2 AND i.status='PENDING' AND i.expires_at>now() AND t.workspace_status='ACTIVE' FOR UPDATE OF i",uid,email)
                        if not invitation:raise HTTPException(403,'No active workspace invitation matches this verified identity')
                        if await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)',uid):raise HTTPException(409,'Identity is already enrolled')
                        updated=await client.put(settings.supabase_url+'/auth/v1/user',headers=h,json={'password':body.password.get_secret_value()})
                        if updated.status_code!=200:raise HTTPException(400,'Choose a stronger password and retry')
                        # Authorization derives only from the stored invitation, never editable email metadata.
                        await c.execute('INSERT INTO public.users(tenant_id,auth_user_id,role,full_name,is_active) VALUES($1,$2,$3,$4,true)',invitation['tenant_id'],uid,invitation['role'],invitation['first_name']+' '+invitation['last_name'])
                        await c.execute("UPDATE public.workspace_invitations SET status='ACCEPTED',accepted_at=now() WHERE id=$1",invitation['id'])
                        await c.execute('DELETE FROM public.app_auth_sessions WHERE auth_user_id=$1',uid)
                try:
                    signed_out=await client.post(settings.supabase_url+'/auth/v1/logout',params={'scope':'global'},headers=h)
                    if signed_out.status_code not in (200,204):
                        import logging
                        logging.getLogger(__name__).warning('Invitation accepted; provider sign-out could not be confirmed')
                except httpx.HTTPError:
                    import logging
                    logging.getLogger(__name__).warning('Invitation accepted; provider sign-out could not be confirmed')
        except (httpx.HTTPError,ValueError,KeyError):raise HTTPException(503,'Invitation activation is temporarily unavailable; retry the same verified session') from None
        return {'message':'Workspace access activated. Sign in with your email and new password.'}
    @router.get('/shipments/{shipment_id}/dispute-draft')
    async def get_draft(shipment_id:UUID,request:Request,context:Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:raise HTTPException(403,'Financial permission required')
        async with request.app.state.finance.pool.acquire() as c:
            row=await c.fetchrow('SELECT content,updated_at FROM public.shipment_dispute_drafts WHERE tenant_id=$1 AND shipment_id=$2',context.tenant_id,shipment_id)
        return {'draft':dict(row) if row else None}
    @router.put('/shipments/{shipment_id}/dispute-draft')
    async def save_draft(shipment_id:UUID,body:Draft,request:Request,context:Any=Depends(authenticate)):
        if context.role not in {'OWNER','ADMIN','ACCOUNTANT'}:raise HTTPException(403,'Financial permission required')
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                exists=await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.shipments WHERE tenant_id=$1 AND id=$2 AND booked_at IS NOT NULL AND tracking_number IS NOT NULL)",context.tenant_id,shipment_id)
                if not exists:raise HTTPException(409,'A confirmed shipment is required for a surcharge dispute')
                await c.execute('INSERT INTO public.shipment_dispute_drafts(tenant_id,shipment_id,content,updated_by) VALUES($1,$2,$3,$4) ON CONFLICT(tenant_id,shipment_id) DO UPDATE SET content=excluded.content,updated_by=excluded.updated_by,updated_at=now()',context.tenant_id,shipment_id,body.content,context.user_id)
        return {'saved':True,'sent_to_carrier':False}
    from backend.admin_portal import authenticate_platform_owner
    from types import SimpleNamespace
    @router.get('/admin/shipments/{shipment_id}/dispute-draft')
    async def admin_get_draft(shipment_id:UUID,tenant_id:UUID,request:Request,admin:Any=Depends(authenticate_platform_owner)):
        return await get_draft(shipment_id,request,SimpleNamespace(tenant_id=tenant_id,user_id=admin.user_id,role='OWNER'))
    @router.put('/admin/shipments/{shipment_id}/dispute-draft')
    async def admin_save_draft(shipment_id:UUID,tenant_id:UUID,body:Draft,request:Request,admin:Any=Depends(authenticate_platform_owner)):
        return await save_draft(shipment_id,body,request,SimpleNamespace(tenant_id=tenant_id,user_id=admin.user_id,role='OWNER'))
    return router
