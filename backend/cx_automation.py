"""Portal endpoints for the same guarded services used by WhatsApp."""
from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.cx_claims import ClaimIntake, ClaimScope, ClaimTriageService
from backend.cx_connectors import connector_checks
from backend.cx_policies import PolicyService, merchant_owner


class PolicyDescription(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str=Field(min_length=5,max_length=1000)
    request_id: UUID=Field(default_factory=uuid4)


class PublicTrackingChoice(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled: bool=Field(strict=True)


class ClaimUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    description: str | None=Field(default=None,min_length=10,max_length=1800)
    item_value_gbp: Decimal | None=Field(default=None,gt=0,le=50000,decimal_places=2)


class FixtureRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    owner_auth_user_ids: list[UUID]=Field(min_length=3,max_length=3)
    reset: bool=False

    @model_validator(mode='after')
    def distinct(self) -> FixtureRequest:
        if len(set(self.owner_auth_user_ids))!=3:
            raise ValueError('Supply three distinct existing test Auth users')
        return self


async def require_schema(request: Request) -> None:
    pool=getattr(getattr(request.app.state,'finance',None),'pool',None)
    if pool is None:
        raise HTTPException(503,'Configured database required')
    async with pool.acquire() as c:
        ready=await c.fetchval("SELECT to_regclass('public.cx_policy_proposals') IS NOT NULL AND to_regclass('public.cx_claim_dossiers') IS NOT NULL")
    if not ready:
        raise HTTPException(503,'Apply migration 056 before enabling unified CX automation')


def policies(request: Request) -> PolicyService:
    runtime=getattr(getattr(request.app.state,'logistics_supervisor',None),'runtime',None)
    return PolicyService(request.app.state.finance.pool,runtime)


async def dossier_scope(request: Request,context: Any,identifier: UUID) -> ClaimScope:
    async with request.app.state.finance.pool.acquire() as c:
        row=await c.fetchrow('SELECT shipment_id FROM public.cx_claim_dossiers WHERE id=$1 AND tenant_id=$2 AND actor_id=$3',identifier,context.tenant_id,context.user_id)
    if row is None:
        raise HTTPException(404,'Claim dossier unavailable')
    return ClaimScope(context.tenant_id,row['shipment_id'],actor_id=context.user_id)


def build_router(authenticate: Any,authenticate_platform_owner: Any) -> APIRouter:
    router=APIRouter(tags=['Unified CX automation'],dependencies=[Depends(require_schema)])

    @router.post('/api/v1/public/tracking/status')
    async def public_status(body: PolicyDescription,request: Request,response: Response) -> dict[str,str]:
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',body.text):
            raise HTTPException(422,'Enter the complete carrier tracking reference')
        workspace=request.app.state.tracking_workspace
        workspace.public_rate_limit(request.client.host if request.client else 'unknown')
        from backend.whatsapp_progressive import GuestShippingAssistant
        assistant=object.__new__(GuestShippingAssistant)
        assistant.pool=request.app.state.finance.pool
        assistant.settings=request.app.state.settings
        response.headers['Cache-Control']='no-store'
        return {'message':await assistant.public_status(body.text)}

    @router.post('/api/v1/settings/return-policy/proposals')
    async def propose(body: PolicyDescription,request: Request,context=Depends(authenticate)) -> dict[str,Any]:
        return await policies(request).propose(context,body.text,body.request_id)

    @router.post('/api/v1/settings/return-policy/proposals/{proposal_id}/confirm')
    async def confirm(proposal_id: UUID,request: Request,context=Depends(authenticate)) -> dict[str,Any]:
        return await policies(request).confirm(context,proposal_id)

    @router.get('/api/v1/settings/public-tracking')
    async def get_public(request: Request,context=Depends(authenticate)) -> dict[str,bool]:
        async with request.app.state.finance.pool.acquire() as c:
            await merchant_owner(c,context)
            enabled=await c.fetchval('SELECT public_status_lookup_enabled FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
        return {'enabled':enabled}

    @router.put('/api/v1/settings/public-tracking')
    async def set_public(body: PublicTrackingChoice,request: Request,context=Depends(authenticate)) -> dict[str,bool]:
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                await merchant_owner(c,context)
                await c.execute('UPDATE public.tenants SET public_status_lookup_enabled=$2 WHERE tenant_id=$1',context.tenant_id,body.enabled)
        return {'enabled':body.enabled}

    @router.post('/api/v1/agents/claims/intake')
    async def intake(body: ClaimIntake,request: Request,context=Depends(authenticate)) -> dict[str,Any]:
        service=ClaimTriageService(request.app.state)
        scope=await service.merchant_scope(context,body.reference)
        engine=getattr(request.app.state,'logistics_supervisor',None)
        if engine is not None:
            return await engine.support.intake(request.app.state,context,body)
        return await service.create(scope,body)

    @router.patch('/api/v1/agents/claims/{dossier_id}')
    async def update(dossier_id: UUID,body: ClaimUpdate,request: Request,context=Depends(authenticate)) -> dict[str,Any]:
        scope=await dossier_scope(request,context,dossier_id)
        return await ClaimTriageService(request.app.state).update(scope,dossier_id,description=body.description,value=body.item_value_gbp)

    @router.post('/api/v1/agents/claims/{dossier_id}/evidence')
    async def evidence(dossier_id: UUID,request: Request,context=Depends(authenticate)) -> dict[str,Any]:
        scope=await dossier_scope(request,context,dossier_id)
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>5_000_000:
                raise HTTPException(413,'Photograph exceeds 5 MB')
        return await ClaimTriageService(request.app.state).update(scope,dossier_id,image=bytes(raw),mime=request.headers.get('content-type','').split(';')[0])

    async def review_authority(request: Request,context: Any,identifier: UUID) -> tuple[Any,ClaimScope]:
        async with request.app.state.finance.pool.acquire() as c:
            row=await c.fetchrow('SELECT * FROM public.cx_claim_dossiers WHERE id=$1 AND tenant_id=$2',identifier,context.tenant_id)
        if row is None:raise HTTPException(404,'Claim dossier unavailable')
        scope=await ClaimTriageService(request.app.state).merchant_scope(context,str(row['shipment_id']))
        return row,scope

    @router.get('/api/v1/agents/claims/{dossier_id}')
    async def review(dossier_id: UUID,request: Request,response: Response,context=Depends(authenticate)) -> dict[str,Any]:
        row,scope=await review_authority(request,context,dossier_id)
        async with request.app.state.finance.pool.acquire() as c:
            await ClaimTriageService(request.app.state).validate_scope(c,scope)
            evidence=await c.fetch('SELECT id,mime_type,created_at FROM public.cx_claim_evidence WHERE dossier_id=$1 AND tenant_id=$2 ORDER BY created_at',dossier_id,context.tenant_id)
        response.headers['Cache-Control']='no-store'
        return {**ClaimTriageService.result(dossier_id,ClaimTriageService.decode(row['dossier'])),
            'evidence':[dict(item) for item in evidence]}

    @router.get('/api/v1/agents/claims/{dossier_id}/evidence/{evidence_id}')
    async def download(dossier_id: UUID,evidence_id: UUID,request: Request,context=Depends(authenticate)) -> Response:
        _,scope=await review_authority(request,context,dossier_id)
        async with request.app.state.finance.pool.acquire() as c:
            await ClaimTriageService(request.app.state).validate_scope(c,scope)
            row=await c.fetchrow('SELECT content,mime_type FROM public.cx_claim_evidence WHERE dossier_id=$1 AND id=$2 AND tenant_id=$3',dossier_id,evidence_id,scope.tenant_id)
        if row is None:
            raise HTTPException(404,'Evidence unavailable')
        return Response(bytes(row['content']),media_type=row['mime_type'],headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="claim-photo"','X-Content-Type-Options':'nosniff'})

    @router.get('/api/v1/admin/connectors/health')
    async def health(request: Request,actor=Depends(authenticate_platform_owner)) -> dict[str,Any]:
        async with request.app.state.finance.pool.acquire() as c:
            rows=await c.fetch('''SELECT p.id,p.api_base_url,p.environment,o.sendcloud_integration_id,
                coalesce(o.webhook_enabled,false) AS webhook_enabled,o.webhook_secret IS NOT NULL AS webhook_secret_configured,
                j.state AS setup_state,j.error_code AS setup_error,j.callback_url,j.verified_at AS registration_verified_at
                FROM public.platform_carrier_connections p LEFT JOIN public.partner_provider_options o ON o.platform_connection_id=p.id
                LEFT JOIN public.connector_tracking_setup j ON j.platform_connection_id=p.id
                WHERE p.is_active AND p.retired_at IS NULL AND p.environment=$1''',request.app.state.settings.provider_environment)
        async with request.app.state.finance.pool.acquire() as c:
            running=bool(await c.fetchval("SELECT EXISTS(SELECT 1 FROM public.cx_worker_heartbeats WHERE worker_name='tracking-refresh' AND environment=$1 AND last_seen>now()-interval '90 seconds')",request.app.state.settings.provider_environment))
        return connector_checks(request.app.state.settings,[dict(row) for row in rows],worker_running=running)

    @router.post('/api/v1/admin/uat/plan-fixtures')
    async def fixtures(body: FixtureRequest,request: Request,actor=Depends(authenticate_platform_owner)) -> dict[str,Any]:
        settings=request.app.state.settings
        if settings.provider_environment!='TEST' or settings.database_environment!='SANDBOX':
            raise HTTPException(403,'UAT fixtures require TEST providers and SANDBOX database mode')
        from backend.entitlements import capabilities
        result=[]
        async with request.app.state.finance.pool.acquire() as c:
            async with c.transaction():
                await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('cx-uat-fixtures',0))")
                for plan,owner_id in zip(('STARTER','VELOCITY','COMMAND'),body.owner_auth_user_ids,strict=True):
                    slug='sandbox-'+plan.lower()
                    identifier=uuid5(NAMESPACE_URL,'easyinvio:uat-fixture:'+slug)
                    if not await c.fetchval('SELECT EXISTS(SELECT 1 FROM auth.users WHERE id=$1)',owner_id):
                        raise HTTPException(422,'Each fixture owner must already exist in Supabase Auth')
                    previous=await c.fetchrow('SELECT tenant_id,is_sandbox FROM public.tenants WHERE workspace_slug=$1 FOR UPDATE',slug)
                    if previous and (previous['tenant_id']!=identifier or not previous['is_sandbox']):
                        raise HTTPException(409,'Reserved fixture slug belongs to a different workspace')
                    if body.reset and previous and await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.shipments WHERE tenant_id=$1)',identifier):
                        raise HTTPException(409,'Fixture has shipment history; reset will not erase financial/shipping records')
                    await c.execute('''INSERT INTO public.tenants(tenant_id,company_name,company_profile,billing_plan,default_currency,
                        workspace_status,billing_status,is_sandbox,workspace_slug,workspace_name,subscription_plan,plan_enforcement_enabled,subscription_complimentary)
                        VALUES($1,$2,'{}','PREPAID_WALLET','GBP','ACTIVE','ACTIVE',true,$2,$2,$3,true,true) ON CONFLICT(tenant_id) DO NOTHING''',identifier,slug,plan)
                    existing_owner=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER' AND is_active LIMIT 1",identifier)
                    if existing_owner and existing_owner!=owner_id:raise HTTPException(409,'Fixture owner cannot be silently replaced')
                    other=await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1 AND tenant_id<>$2)',owner_id,identifier)
                    if other:
                        raise HTTPException(409,'Use a clean dedicated Auth user for each fixture')
                    await c.execute('''INSERT INTO public.users(id,tenant_id,auth_user_id,role,is_active)
                        VALUES($1,$2,$3,'OWNER',true) ON CONFLICT DO NOTHING''',uuid5(identifier,'owner'),identifier,owner_id)
                    await c.execute("INSERT INTO public.wallets(tenant_id,currency,balance,reserved_balance) VALUES($1,'GBP',0,0) ON CONFLICT(tenant_id) DO NOTHING",identifier)
                    if previous and not body.reset:
                        result.append({'tenant_id':str(identifier),'slug':slug,'plan':plan,'enforced':True})
                        continue
                    await c.execute('''UPDATE public.tenants SET subscription_plan=$2,plan_status='ACTIVE',plan_period_start=now(),
                        plan_period_end=NULL,plan_enforcement_enabled=true,subscription_complimentary=true,plan_version=plan_version+1
                        WHERE tenant_id=$1 AND is_sandbox''',identifier,plan)
                    policy=capabilities(plan)
                    await c.execute('''INSERT INTO public.margin_rules(id,tenant_id,currency,markup_type,markup_value,priority,is_active,valid_from,subscription_baseline)
                        VALUES($1,$2,'GBP','PERCENTAGE',$3,900000,true,now(),true)
                        ON CONFLICT(tenant_id,currency) WHERE subscription_baseline DO UPDATE SET markup_value=excluded.markup_value,is_active=true''',uuid4(),identifier,policy.default_markup_percent)
                    result.append({'tenant_id':str(identifier),'slug':slug,'plan':plan,'enforced':True})
        return {'fixtures':result,'auth_users_created':False,'wallet_credit_added':False,'history_deleted':False}

    return router
