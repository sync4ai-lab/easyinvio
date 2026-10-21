"""Manifest effects use synthetic SQL state and mocked HTTP, never a live account."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from decimal import Decimal
from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI,HTTPException
from pydantic import SecretStr
from pypdf import PdfReader

import main
from backend.manifest_service import ManifestService,ManifestShipment,driver_sheet,build_router


class Store:
    def __init__(self):
        self.tenant,self.user,self.account=uuid4(),uuid4(),uuid4()
        self.rows={};self.manifests={};self.events=[];self.calls=[];self.role='OWNER';self.lock=asyncio.Lock()
        for index in range(3):
            ident=uuid4();self.rows[ident]=dict(id=ident,tenant_id=self.tenant,carrier_account_id=self.account,
                status='BOOKED',manifest_id=None,carrier_code='ROYAL_MAIL',tracking_number='TEST-'+str(index),
                parcel_weight_kg=Decimal('1.125'),upstream_shipment_id='shp_'+str(index),
                logistics_metadata=dict(automation_order=dict(origin=dict(line1='10 Real Road',city='Leeds',postal_code='LS1 1AA',country_code='GB'),
                    destination=dict(postal_code='SW1A 2AA')),automation_label=dict(upstream_id='shp_'+str(index))),manifest_endpoint='https://regional.example')
    @asynccontextmanager
    async def acquire(self):yield self
    @asynccontextmanager
    async def transaction(self):
        async with self.lock:yield self
    async def fetchrow(self,sql,*args):
        self.calls.append((sql,args))
        if 'FROM public.users' in sql:return dict(role=self.role,is_sandbox=True) if args[:2]==(self.tenant,self.user) else None
        if 'FROM public.admin_client_assistance_sessions' in sql:return None
        if 'FROM public.carrier_manifests' in sql:
            if args[0]!=self.tenant:return None
            return next((r for r in self.manifests.values() if r.get('request_id')==args[1]),None) if 'request_id=$2' in sql else self.manifests.get(args[1])
        if 'tenant_catalog_addresses' in sql:return None
        raise AssertionError(sql)
    async def fetchval(self,sql,*args):
        self.calls.append((sql,args))
        if 'partner_cancellations' in sql:return False
        if 'carrier_manifests' in sql:return next((r['id'] for r in self.manifests.values() if r['status']=='SUBMITTED'),None)
        raise AssertionError(sql)
    async def fetch(self,sql,*args):
        self.calls.append((sql,args))
        if 'pg_advisory_xact_lock' in sql:return []
        if 'GROUP BY' in sql:
            from backend.manifest_service import postal_origin
            rows=[r for r in self.rows.values() if r['tenant_id']==args[0] and r['status']=='BOOKED' and r['manifest_id'] is None]
            if not rows:return []
            return [dict(carrier_account_id=self.account,carrier_code='ROYAL_MAIL',manifest_endpoint=rows[0]['manifest_endpoint'],
                origin=postal_origin(rows[0]['logistics_metadata']['automation_order']['origin']),total_shipments=len(rows),
                total_weight_kg=sum((r['parcel_weight_kg'] for r in rows),Decimal(0)))]
        if 'FOR UPDATE' in sql:return [self.rows[i] for i in args[1] if self.rows[i]['tenant_id']==args[0]]
        if 'FROM public.shipments s' in sql:return [r for r in self.rows.values() if r['tenant_id']==args[0] and r['status']=='BOOKED' and r['manifest_id'] is None and (args[1] is None or args[1]==r['carrier_account_id'])]
        raise AssertionError(sql)
    async def execute(self,sql,*args):
        self.calls.append((sql,args))
        if 'pg_advisory_xact_lock' in sql:return 'SELECT 1'
        if 'INSERT INTO public.carrier_manifests' in sql:
            keys=['id','tenant_id','carrier_account_id','carrier_code','total_shipments','total_weight_kg','created_by','request_id','input_sha256','document_kind','snapshot','environment']
            row=dict(zip(keys,args));row.update(status='SUBMITTED',master_tracking_id=None,provider_reference=None,document_pdf=None)
            self.manifests[row['id']]=row
        elif 'INSERT INTO public.carrier_manifest_events' in sql:self.events.append((args[1],'COMPLETED' if 'COMPLETED' in sql else 'SUBMITTED'))
        elif 'UPDATE public.shipments SET manifest_id' in sql:
            for ident in args[1]:self.rows[ident]['manifest_id']=args[2]
        elif "UPDATE public.shipments SET status='MANIFESTED'" in sql:
            for row in self.rows.values():
                if row['tenant_id']==args[0] and row['manifest_id']==args[1] and row['status']=='BOOKED':row['status']='MANIFESTED'
        elif 'UPDATE public.carrier_manifests' in sql:
            row=self.manifests[args[1]]
            if "status='COMPLETED'" in sql:row.update(status='COMPLETED',document_pdf=args[2],master_tracking_id=args[3])
            elif "status='FAILED'" in sql:row['status']='FAILED'
            elif 'provider_reference=' in sql:row['provider_reference']=args[2]
        else:raise AssertionError(sql)
        return 'UPDATE 1'


@pytest.fixture
def setup():
    store=Store();settings=SimpleNamespace(provider_environment='TEST',database_environment='SANDBOX',automation_purchase_enabled=False,booking_page_url='https://app.example/',
        auth_recovery_redirect_url='',quote_link_secret=SecretStr('x'*40),partner_document_allowed_hosts=['documents.example'])
    account=SimpleNamespace(id=store.account,tenant_id=store.tenant,base_url='https://regional.example',api_key='synthetic')
    repo=SimpleNamespace(accounts=AsyncMock(return_value=[account]))
    return store,settings,account,repo


@pytest.mark.asyncio
async def test_close_is_durable_exact_idempotent_and_pdf_does_not_assert_carrier_acceptance(setup):
    store,settings,account,repo=setup
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:pytest.fail('Internal sheet must not call provider'))) as http:
        service=ManifestService(store,settings,http,repository=repo)
        summary=await service.get_manifestable_summary(store.tenant)
        assert summary[0].total_shipments==3 and summary[0].total_weight_kg==Decimal('3.375')
        key=uuid4()
        result=await service.close_manifest(store.tenant,store.account,store.user,request_id=key)
        again=await service.close_manifest(store.tenant,store.account,store.user,request_id=key)
        assert result.id==again.id and result.status=='COMPLETED' and not result.carrier_closed
        assert len(store.manifests)==1 and len(store.events)==2
        assert all(r['status']=='MANIFESTED' for r in store.rows.values())
        pdf=store.manifests[result.id]['document_pdf'];text=' '.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
        assert 'INTERNAL HANDOVER RECORD' in text and '3.375' in text and 'TEST-2' in text
        with pytest.raises(HTTPException):await service.close_manifest(uuid4(),store.account,store.user)


@pytest.mark.asyncio
async def test_uncertain_native_submission_holds_claim_and_replay_never_posts_again(setup):
    store,settings,account,repo=setup;account.base_url='https://api.easypost.com/v2'
    calls=[]
    async def server(request):
        calls.append(request)
        assert json.loads(request.content)=={'shipments':[{'id':r['upstream_shipment_id']} for r in store.rows.values()]}
        raise httpx.ReadTimeout('Uncertain carrier response')
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http:
        service=ManifestService(store,settings,http,repository=repo);key=uuid4()
        first=await service.close_manifest(store.tenant,store.account,store.user,request_id=key)
        again=await service.close_manifest(store.tenant,store.account,store.user,request_id=key)
        assert first.status==again.status=='SUBMITTED' and len(calls)==1
        assert all(r['manifest_id']==first.id and r['status']=='BOOKED' for r in store.rows.values())
        with pytest.raises(HTTPException) as error:await service.close_manifest(store.tenant,store.account,store.user)
        assert error.value.status_code==409


@pytest.mark.asyncio
async def test_native_manifest_membership_and_completed_pdf_are_verified(setup):
    store,settings,account,repo=setup;account.base_url='https://api.easypost.com/v2'
    pdf=driver_sheet(uuid4(),'TEST',[ManifestShipment(id=uuid4(),tracking_number='TEST',upstream_ids=['shp_test'],weight_kg='1',origin={'postal_code':'TEST'},destination_postcode='TEST',carrier_code='TEST')],datetime.now(timezone.utc))
    async def server(request):
        if request.method=='POST':return httpx.Response(200,json=dict(id='sf_test',status='created',tracking_codes=[r['tracking_number'] for r in store.rows.values()],form_url='https://documents.example/test.pdf'))
        return httpx.Response(200,content=pdf)
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http:
        service=ManifestService(store,settings,http,repository=repo)
        result=await service.close_manifest(store.tenant,store.account,store.user)
    assert result.status=='COMPLETED' and result.carrier_closed
    assert store.manifests[result.id]['document_pdf']==pdf


@pytest.mark.asyncio
async def test_roles_mixed_origins_and_exact_weight_prevent_any_closeout(setup):
    store,settings,account,repo=setup
    async with httpx.AsyncClient() as http:
        service=ManifestService(store,settings,http,repository=repo)
        store.role='ACCOUNTANT'
        with pytest.raises(HTTPException) as denied:await service.close_manifest(store.tenant,store.account,store.user)
        assert denied.value.status_code==403 and not store.manifests
        store.role='OWNER';next(iter(store.rows.values()))['logistics_metadata']['automation_order']['origin']['line1']='Different pickup'
        with pytest.raises(HTTPException) as ambiguous:await service.close_manifest(store.tenant,store.account,store.user)
        assert ambiguous.value.status_code==409 and not store.manifests


@pytest.mark.asyncio
async def test_rest_scope_and_signed_document_download_cannot_change_manifest_tenant(setup):
    store,settings,account,repo=setup
    app=FastAPI();context=main.TenantContext(store.tenant,store.user,'OWNER','synthetic')
    async def authenticate():return context
    async with httpx.AsyncClient() as upstream:
        service=ManifestService(store,settings,upstream,repository=repo)
        app.state.manifests=service;app.state.settings=settings;app.include_router(build_router(authenticate))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://app.example') as client:
            body={'request_id':str(uuid4()),'carrier_account_id':str(store.account)}
            assert (await client.post('/api/v1/dispatch/manifests/close?tenant_id='+str(uuid4()),json=body)).status_code==403
            assert not store.manifests
            response=await client.post('/api/v1/dispatch/manifests/close',json=body)
            assert response.status_code==200 and response.json()['status']=='COMPLETED'
            signed=response.json()['manifest_document_url']
            document=await client.get(signed)
            assert document.status_code==200 and document.content.startswith(b'%PDF-')
            altered=signed.replace(response.json()['id'],str(uuid4()),1)
            assert (await client.get(altered)).status_code==401
            context=main.TenantContext(store.tenant,store.user,'ACCOUNTANT','synthetic')
            assert (await client.post('/api/v1/dispatch/manifests/preview',json={})).status_code==403


@pytest.mark.asyncio
async def test_two_close_requests_do_not_share_or_double_manifest_shipments(setup):
    store,settings,account,repo=setup
    async with httpx.AsyncClient() as http:
        service=ManifestService(store,settings,http,repository=repo)
        results=await asyncio.gather(service.close_manifest(store.tenant,store.account,store.user),
            service.close_manifest(store.tenant,store.account,store.user),return_exceptions=True)
    assert len(store.manifests)==1
    assert sum(not isinstance(result,Exception) for result in results)==1
    assert all(r['manifest_id']==next(iter(store.manifests)) for r in store.rows.values())
    assert not any('wallet_ledger' in sql or 'UPDATE public.wallets' in sql for sql,_ in store.calls)


@pytest.mark.asyncio
async def test_large_day_closes_bounded_batches_without_losing_remaining_shipments(setup):
    store,settings,account,repo=setup
    template=next(iter(store.rows.values()))
    for index in range(1002):
        ident=uuid4();store.rows[ident]=template|{'id':ident,'tracking_number':f'LARGE-{index}','upstream_shipment_id':f'shp_large{index}'}
    async with httpx.AsyncClient() as http:
        service=ManifestService(store,settings,http,repository=repo)
        preview=await service.get_manifestable_summary(store.tenant)
        assert preview[0].total_shipments==1005
        first=await service.close_manifest(store.tenant,store.account,store.user)
        assert first.total_shipments==1000 and 'Batch limit' in first.message
        remaining=await service.get_manifestable_summary(store.tenant)
        assert remaining[0].total_shipments==5
        second=await service.close_manifest(store.tenant,store.account,store.user)
    assert second.total_shipments==5 and first.id!=second.id
    assert all(r['status']=='MANIFESTED' for r in store.rows.values())
