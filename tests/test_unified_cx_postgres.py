"""Actual 056 migration and service SQL on disposable PostgreSQL WASM only."""
import asyncio
import json
import os
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

from tests.test_tracking_workspace_postgres import Database,UUID_FIELDS,decode
from backend.cx_policies import PolicyService
from backend.cx_claims import ClaimIntake,ClaimScope,ClaimTriageService
from backend.cx_delay import DelaySentinel

ROOT=Path(__file__).resolve().parents[1]
UUID_FIELDS.update({'actor_id','ticket_id','authorized_by','platform_connection_id'})


class PrivateDatabase(Database):
    async def command(self,sql,args=(),mode='query'):
        def encode(value):
            if isinstance(value,(bytes,bytearray)):return {'__bytea_hex__':bytes(value).hex()}
            if isinstance(value,datetime):return value.isoformat()
            return str(value)
        command=json.dumps({'sql':sql,'args':args,'mode':mode},default=encode)+'\n'
        self.process.stdin.write(command.encode());await self.process.stdin.drain()
        raw=await asyncio.wait_for(self.process.stdout.readline(),30)
        result=json.loads(raw)
        if not result['ok']:raise asyncpg.PostgresError.new({'C':result.get('code','XX000'),'M':result['message']})
        rows=[decode(row) for row in result['rows']]
        for row in rows:
            for key,value in row.items():
                if isinstance(value,dict) and '__bytea_hex__' in value:row[key]=bytes.fromhex(value['__bytea_hex__'])
        return rows


@pytest_asyncio.fixture
async def db():
    if not os.getenv('PGLITE_TEST_MODULE'):
        pytest.skip('Set explicit disposable PGlite module; never uses DATABASE_URL')
    process=await asyncio.create_subprocess_exec(str(ROOT/'.venv/Lib/site-packages/playwright/driver/node.exe'),str(ROOT/'tests/pglite_tracking_bridge.cjs'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=4_000_000)
    c=PrivateDatabase(process)
    try:
        for file in ['tests/fixtures/subscription_baseline.sql','migrations/050_subscription_tiers_and_entitlements.sql','migrations/051_subscription_safety_followup.sql']:
            await c.command((ROOT/file).read_text(encoding='utf-8'),mode='exec')
        await c.command('''
        ALTER TABLE public.wallets ADD reserved_balance numeric NOT NULL DEFAULT 0;
        ALTER TABLE public.tenants ADD public_status_lookup_enabled boolean NOT NULL DEFAULT false,ADD company_profile jsonb DEFAULT '{}',ADD billing_status text DEFAULT 'ACTIVE',ADD workspace_slug text UNIQUE,ADD workspace_name text;
        ALTER TABLE public.shipments ADD last_tracking_event_at timestamptz,ADD logistics_metadata jsonb NOT NULL DEFAULT '{}',
          ADD created_at timestamptz NOT NULL DEFAULT now(),ADD carrier_account_id uuid,ADD customer_reference text,ADD tracking_number text;
        ALTER TABLE public.carrier_accounts ADD api_base_url text DEFAULT 'https://api.easypost.com/v2',ADD environment text DEFAULT 'TEST';
        CREATE TABLE public.platform_carrier_connections(id uuid PRIMARY KEY,is_active boolean NOT NULL DEFAULT true,retired_at timestamptz);
        CREATE TABLE public.whatsapp_consumer_return_policies(tenant_id uuid PRIMARY KEY REFERENCES public.tenants,
          enabled boolean NOT NULL DEFAULT false,authorized_by uuid NOT NULL REFERENCES auth.users,
          window_days integer NOT NULL CHECK(window_days BETWEEN 1 AND 90),charge_bearer text NOT NULL CHECK(charge_bearer IN ('RETAILER_PAY','CUSTOMER_PAY')),
          maximum_price_gbp numeric(12,2) NOT NULL CHECK(maximum_price_gbp>0 AND maximum_price_gbp<=100),version integer NOT NULL DEFAULT 1,updated_at timestamptz NOT NULL DEFAULT now());
        CREATE TABLE public.support_tickets(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,shipment_id uuid,status text,
          ai_summary text,ai_method text,prompt_version text,tracking_event_id uuid,cx_request_id uuid UNIQUE,cx_kind text,issue_category text,tracking_customer_request_id uuid);
        CREATE TABLE public.whatsapp_bindings(id uuid PRIMARY KEY,tenant_id uuid,user_id uuid,sender_e164 text,is_active boolean,
          verified_at timestamptz,notification_opt_in boolean,alerts_paused boolean DEFAULT false);
        CREATE TABLE public.support_message_outbox(tenant_id uuid,ticket_id uuid,recipient_e164 text,body text,status text,message_kind text,
          UNIQUE(tenant_id,ticket_id,recipient_e164));
        CREATE TABLE public.tracking_share_links(tenant_id uuid,token_sha256 text,shipment_ids uuid[],revoked_at timestamptz,expires_at timestamptz);
        CREATE TABLE public.tracking_events(tenant_id uuid,shipment_id uuid,status text,occurred_at timestamptz,response jsonb);
        CREATE TABLE public.insurance_purchases(tenant_id uuid,shipment_id uuid,state text);
        CREATE TABLE public.insurance_claim_cases(id uuid PRIMARY KEY,tenant_id uuid,shipment_id uuid,policy_id text,reason text,state text,submission_payload jsonb,notes text,created_by uuid,payload_sha256 text,UNIQUE(tenant_id,id));
        INSERT INTO public.tenants(tenant_id,company_name) VALUES('00000000-0000-4000-8000-000000000001','Existing opted-out merchant');
        ''',mode='exec')
        await c.command((ROOT/'migrations/056_unified_cx_automation.sql').read_text(encoding='utf-8'),mode='exec')
        yield c
    finally:
        process.stdin.close()
        await process.wait()


async def merchant(c):
    tenant,actor,user=uuid4(),uuid4(),uuid4()
    await c.execute('INSERT INTO auth.users VALUES($1)',actor)
    await c.execute('INSERT INTO public.tenants(tenant_id,is_sandbox) VALUES($1,true)',tenant)
    await c.execute("INSERT INTO public.users(id,tenant_id,auth_user_id,role) VALUES($1,$2,$3,'OWNER')",user,tenant,actor)
    return NS(tenant_id=tenant,user_id=actor,role='OWNER',assistance_session_id=None)


@pytest.mark.asyncio
async def test_actual_migration_defaults_optout_enforcement_and_private_tables(db):
    context=await merchant(db)
    row=await db.fetchrow('SELECT public_status_lookup_enabled,plan_enforcement_enabled FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
    assert row=={'public_status_lookup_enabled':True,'plan_enforcement_enabled':True}
    assert not await db.fetchval("SELECT public_status_lookup_enabled FROM public.tenants WHERE company_name='Existing opted-out merchant'")
    await db.execute('UPDATE public.tenants SET plan_enforcement_enabled=false WHERE tenant_id=$1',context.tenant_id)
    assert await db.fetchval('SELECT plan_enforcement_enabled FROM public.tenants WHERE tenant_id=$1',context.tenant_id)
    policy=await db.fetchrow('SELECT * FROM public.whatsapp_consumer_return_policies WHERE tenant_id=$1',context.tenant_id)
    assert policy['enabled'] and policy['window_days']==14 and policy['charge_bearer']=='CUSTOMER_PAY'
    assert policy['require_delivered_status'] and policy['authorized_by']==context.user_id
    assert not await db.fetchval("SELECT has_table_privilege('authenticated','public.cx_claim_evidence','SELECT')")


@pytest.mark.asyncio
async def test_policy_confirmed_once_fresh_actor_and_version_guard(db):
    context=await merchant(db)
    service=PolicyService(db)
    result=await service.propose(context,'Set a 30-day free return policy for UK orders, maximum GBP 10')
    before=await db.fetchrow('SELECT window_days,charge_bearer FROM public.whatsapp_consumer_return_policies WHERE tenant_id=$1',context.tenant_id)
    assert before['window_days']==14 and before['charge_bearer']=='CUSTOMER_PAY'
    from uuid import UUID
    identifier=UUID(result['proposal_id'])
    assert (await service.confirm(context,identifier))['confirmed']
    version=await db.fetchval('SELECT version FROM public.whatsapp_consumer_return_policies WHERE tenant_id=$1',context.tenant_id)
    assert (await service.confirm(context,identifier))['replayed']
    assert await db.fetchval('SELECT version FROM public.whatsapp_consumer_return_policies WHERE tenant_id=$1',context.tenant_id)==version
    other=await merchant(db)
    with pytest.raises(HTTPException):await service.confirm(other,identifier)
    pending=await service.propose(context,'Set a 20-day customer pay return policy for UK orders')
    await db.execute('UPDATE public.whatsapp_consumer_return_policies SET version=version+1 WHERE tenant_id=$1',context.tenant_id)
    with pytest.raises(HTTPException) as error:await service.confirm(context,UUID(pending['proposal_id']))
    assert error.value.status_code==409


@pytest.mark.asyncio
async def test_uninsured_claim_intake_and_value_update_no_finance_or_insurer_required(db):
    context=await merchant(db);shipment=uuid4()
    await db.execute("INSERT INTO public.shipments(id,tenant_id,status) VALUES($1,$2,'DELIVERED')",shipment,context.tenant_id)
    service=ClaimTriageService(NS(finance=NS(pool=db),claims=None))
    scope=ClaimScope(context.tenant_id,shipment,actor_id=context.user_id)
    intake=ClaimIntake(reference=str(shipment),reason='DAMAGED',description='The parcel and contents were crushed')
    result=await service.create(scope,intake)
    assert result['dossier']['route']=='MERCHANT_CARRIER_REVIEW'
    assert result['dossier']['financial_action']=='NONE'
    assert (await service.create(scope,intake))['dossier_id']==result['dossier_id']
    from decimal import Decimal
    updated=await service.update(scope,intake.request_id,value=Decimal('25'))
    assert updated['dossier']['evidence_status']=='INCOMPLETE'
    assert await db.fetchval('SELECT count(*) FROM public.support_tickets')==1
    assert await db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0
    other=await merchant(db)
    with pytest.raises(HTTPException):await service.update(ClaimScope(other.tenant_id,shipment,actor_id=other.user_id),intake.request_id,value=Decimal('99'))


@pytest.mark.asyncio
async def test_capability_rechecked_on_every_claim_update(db):
    context=await merchant(db);shipment=uuid4();token='a'*64
    await db.execute("INSERT INTO public.shipments(id,tenant_id,status) VALUES($1,$2,'IN_TRANSIT')",shipment,context.tenant_id)
    await db.execute("INSERT INTO public.tracking_share_links(tenant_id,token_sha256,shipment_ids,expires_at) VALUES($1,$2,$3,now()+interval '1 hour')",context.tenant_id,token,[shipment])
    service=ClaimTriageService(NS(finance=NS(pool=db),claims=None));scope=ClaimScope(context.tenant_id,shipment,capability_sha256=token)
    body=ClaimIntake(reference=str(shipment),reason='LOST',description='The parcel has not arrived and the carrier trace is pending',item_value_gbp='30')
    result=await service.create(scope,body)
    assert result['dossier']['evidence_status']=='READY_FOR_REVIEW'
    await db.execute('UPDATE public.tracking_share_links SET revoked_at=now() WHERE token_sha256=$1',token)
    with pytest.raises(HTTPException):await service.update(scope,body.request_id,description='This update must not be accepted')


@pytest.mark.asyncio
async def test_delay_incident_deduplicates_ticket_and_opted_in_alert(db):
    context=await merchant(db);shipment,account=uuid4(),uuid4()
    await db.execute('INSERT INTO public.carrier_accounts(id,tenant_id,platform_connection_id) VALUES($1,$2,$3)',account,context.tenant_id,uuid4())
    await db.execute("INSERT INTO public.shipments(id,tenant_id,carrier_account_id,status,booked_at) VALUES($1,$2,$3,'BOOKED',now()-interval '49 hours')",shipment,context.tenant_id,account)
    user=await db.fetchval('SELECT id FROM public.users WHERE tenant_id=$1',context.tenant_id)
    await db.execute("INSERT INTO public.whatsapp_bindings(id,tenant_id,user_id,sender_e164,is_active,verified_at,notification_opt_in) VALUES($1,$2,$3,'+447700900123',true,now(),true)",uuid4(),context.tenant_id,user)
    sentinel=DelaySentinel(db,'TEST')
    assert await sentinel.scan()==1
    assert await sentinel.scan()==0
    assert await db.fetchval('SELECT count(*) FROM public.support_tickets')==1
    assert await db.fetchval('SELECT count(*) FROM public.support_message_outbox')==1


@pytest.mark.asyncio
async def test_platform_link_transactionally_queues_setup_and_disable(db):
    identifier=uuid4()
    await db.execute('INSERT INTO public.platform_carrier_connections(id) VALUES($1)',identifier)
    assert await db.fetchval('SELECT state FROM public.connector_tracking_setup WHERE platform_connection_id=$1',identifier)=='DUE'
    await db.execute('UPDATE public.platform_carrier_connections SET is_active=false WHERE id=$1',identifier)
    assert await db.fetchval('SELECT state FROM public.connector_tracking_setup WHERE platform_connection_id=$1',identifier)=='DISABLED'


@pytest.mark.asyncio
async def test_uat_seed_provisions_three_plans_without_funds_or_replay_version_changes(db):
    from fastapi import FastAPI
    import httpx
    from backend.cx_automation import build_router
    actor=await merchant(db)
    async def owner():return actor
    app=FastAPI();app.state.finance=NS(pool=db);app.state.settings=NS(provider_environment='TEST',database_environment='SANDBOX')
    app.include_router(build_router(owner,owner))
    owners=[uuid4() for _ in range(3)]
    for identifier in owners:await db.execute('INSERT INTO auth.users VALUES($1)',identifier)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://uat.test') as client:
        body={'owner_auth_user_ids':[str(i) for i in owners]}
        response=await client.post('/api/v1/admin/uat/plan-fixtures',json=body)
        assert response.status_code==200,response.text
        assert [r['plan'] for r in response.json()['fixtures']]==['STARTER','VELOCITY','COMMAND']
        versions=await db.fetch("SELECT workspace_slug,plan_version FROM public.tenants WHERE workspace_slug LIKE 'sandbox-%' ORDER BY workspace_slug")
        assert (await client.post('/api/v1/admin/uat/plan-fixtures',json=body)).status_code==200
        assert await db.fetch("SELECT workspace_slug,plan_version FROM public.tenants WHERE workspace_slug LIKE 'sandbox-%' ORDER BY workspace_slug")==versions
        assert not response.json()['wallet_credit_added']


@pytest.mark.asyncio
async def test_ready_insured_dossier_mirrors_intake_without_submission_or_credit(db):
    context=await merchant(db);shipment=uuid4()
    await db.execute("INSERT INTO public.shipments(id,tenant_id,status,logistics_metadata) VALUES($1,$2,'IN_TRANSIT',$3::jsonb)",shipment,context.tenant_id,json.dumps({'insurance':{'provider':'XCOVER','status':'CONFIRMED','policy_id':'synthetic-policy'}}))
    await db.execute("INSERT INTO public.insurance_purchases VALUES($1,$2,'INSURED')",context.tenant_id,shipment)
    state=NS(finance=NS(pool=db),claims=NS(client=NS(unavailable_reason=lambda:None)))
    body=ClaimIntake(reference=str(shipment),reason='LOST',description='The carrier cannot locate the parcel',item_value_gbp='40')
    result=await ClaimTriageService(state).create(ClaimScope(context.tenant_id,shipment,actor_id=context.user_id),body)
    assert result['dossier']['route']=='INSURER_REVIEW'
    row=await db.fetchrow('SELECT state,submission_payload FROM public.insurance_claim_cases WHERE id=$1',body.request_id)
    assert row['state']=='CLAIM_INGESTED'
    payload=json.loads(row['submission_payload']) if isinstance(row['submission_payload'],str) else row['submission_payload']
    assert payload['human_review_required']
    await ClaimTriageService(state).update(ClaimScope(context.tenant_id,shipment,actor_id=context.user_id),body.request_id,description='The carrier completed a trace and cannot locate this parcel')
    assert await db.fetchval('SELECT notes FROM public.insurance_claim_cases WHERE id=$1',body.request_id)=='The carrier completed a trace and cannot locate this parcel'
    assert await db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0


@pytest.mark.asyncio
async def test_private_photo_is_verified_deduplicated_and_completes_dossier(db):
    from io import BytesIO
    from PIL import Image
    from decimal import Decimal
    context=await merchant(db);shipment=uuid4()
    await db.execute("INSERT INTO public.shipments(id,tenant_id,status) VALUES($1,$2,'DELIVERED')",shipment,context.tenant_id)
    service=ClaimTriageService(NS(finance=NS(pool=db),claims=None));scope=ClaimScope(context.tenant_id,shipment,actor_id=context.user_id)
    body=ClaimIntake(reference=str(shipment),reason='DAMAGED',description='The glass item arrived broken inside crushed packaging',item_value_gbp='25')
    await service.create(scope,body)
    with pytest.raises(HTTPException):await service.update(scope,body.request_id,image=b'<html>Not a photo</html>',mime='image/png')
    image=Image.new('RGB',(2,2),(10,20,30));buffer=BytesIO();image.save(buffer,format='PNG');photo=buffer.getvalue()
    result=await service.update(scope,body.request_id,image=photo,mime='image/png')
    assert result['dossier']['evidence_status']=='READY_FOR_REVIEW'
    assert result['dossier']['photo_verification']=='FORMAT_ONLY_NOT_PROOF_OF_INCIDENT'
    await service.update(scope,body.request_id,image=photo,mime='image/png')
    assert await db.fetchval('SELECT count(*) FROM public.cx_claim_evidence')==1
    assert await db.fetchval('SELECT octet_length(content) FROM public.cx_claim_evidence')==len(photo)
    assert await db.fetchval('SELECT count(*) FROM public.wallet_ledger')==0


@pytest.mark.asyncio
async def test_policy_out_of_bounds_and_claim_request_reuse_are_rejected(db):
    context=await merchant(db)
    with pytest.raises(HTTPException) as error:await PolicyService(db).propose(context,'Set a 91-day free return policy for UK orders, maximum GBP 60')
    assert error.value.status_code==422
    shipment=uuid4();await db.execute("INSERT INTO public.shipments(id,tenant_id,status) VALUES($1,$2,'IN_TRANSIT')",shipment,context.tenant_id)
    service=ClaimTriageService(NS(finance=NS(pool=db),claims=None));scope=ClaimScope(context.tenant_id,shipment,actor_id=context.user_id)
    body=ClaimIntake(reference=str(shipment),reason='LOST',description='The carrier trace cannot locate the parcel',item_value_gbp='25')
    await service.create(scope,body)
    with pytest.raises(HTTPException) as error:await service.create(scope,body.model_copy(update={'item_value_gbp':Decimal('99')}))
    assert error.value.status_code==409
