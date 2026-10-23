"""Application services run on disposable PostgreSQL, never the configured database.

Set PGLITE_TEST_MODULE and optionally PGLITE_TEST_NODE to execute this suite.
Ordinary pytest runs skip it when the explicit test dependency is not installed.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import SecretStr

from backend.tracking_workspace import TrackingWorkspace, TrackingScope, ShareRequest, Preferences, CustomerRequest, NO_REFUND
from backend.tracking_and_support import TrackingSupportService, TrackingSettings, TrackingKey, TrackingEvent
from backend.tracking_refresh import TrackingRefreshWorker

ROOT=Path(__file__).resolve().parents[1]
UUID_FIELDS={'id','tenant_id','shipment_id','carrier_account_id','auth_user_id','ecommerce_store_id','return_of_shipment_id',
             'actor_auth_user_id','created_by','anchor_shipment_id','tracking_event_id','requested_by','lease_token','assigned_to','updated_by'}


def decode(row):
    for key,value in list(row.items()):
        if isinstance(value, str) and key in UUID_FIELDS:row[key]=UUID(value)
        elif isinstance(value,str) and (key.endswith('_at') or key=='lease_until'):
            row[key]=datetime.fromisoformat(value.replace('Z','+00:00'))
        elif key=='shipment_ids':row[key]=[UUID(item) for item in value]
    return row


class Database:
    def __init__(self,process):self.process=process;self.lock=asyncio.Lock()
    async def command(self,sql,args=(),mode='query'):
        command=json.dumps({'sql':sql,'args':args,'mode':mode},default=lambda item:item.isoformat() if isinstance(item,datetime) else str(item))+'\n'
        self.process.stdin.write(command.encode());await self.process.stdin.drain()
        raw=await asyncio.wait_for(self.process.stdout.readline(),30)
        if not raw:raise RuntimeError('Disposable PostgreSQL bridge stopped')
        result=json.loads(raw)
        if not result['ok']:raise asyncpg.PostgresError.new({'C':result.get('code','XX000'),'M':result['message']})
        return [decode(row) for row in result['rows']]
    async def fetch(self,sql,*args):return await self.command(sql,args)
    async def fetchrow(self,sql,*args):
        rows=await self.fetch(sql,*args);return rows[0] if rows else None
    async def fetchval(self,sql,*args):
        row=await self.fetchrow(sql,*args);return next(iter(row.values())) if row else None
    async def execute(self,sql,*args):return await self.command(sql,args)
    @asynccontextmanager
    async def acquire(self):
        async with self.lock:yield self
    @asynccontextmanager
    async def transaction(self,**kwargs):
        await self.command('BEGIN',mode='exec')
        try:
            yield self
        except BaseException:
            await self.command('ROLLBACK',mode='exec');raise
        else:await self.command('COMMIT',mode='exec')


@pytest_asyncio.fixture
async def world():
    if not os.getenv('PGLITE_TEST_MODULE'):pytest.skip('Explicit disposable PostgreSQL test dependency not configured')
    node=os.getenv('PGLITE_TEST_NODE',str(ROOT/'.venv/Lib/site-packages/playwright/driver/node.exe'))
    process=await asyncio.create_subprocess_exec(node,str(ROOT/'tests/pglite_tracking_bridge.cjs'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,limit=4_000_000)
    database=Database(process)
    try:
        await database.command((ROOT/'tests/fixtures/tracking_baseline.sql').read_text(),mode='exec')
        for filename in ('043_whatsapp_async_ingress.sql','044_carrier_manifests_and_media.sql','045_unified_tracking.sql'):
            await database.command((ROOT/'migrations'/filename).read_text(),mode='exec')
        actors=[uuid4(),uuid4()];tenants=[uuid4(),uuid4()];accounts=[uuid4(),uuid4()];shipments=[uuid4(),uuid4()]
        for index in range(2):
            await database.execute('INSERT INTO auth.users(id) VALUES($1)',actors[index])
            await database.execute('INSERT INTO public.tenants(tenant_id,company_name) VALUES($1,$2)',tenants[index],f'Synthetic tenant {index}')
            await database.execute("INSERT INTO public.users(id,tenant_id,auth_user_id,role) VALUES($1,$2,$3,'OWNER')",uuid4(),tenants[index],actors[index])
            await database.execute('INSERT INTO public.carrier_accounts(id,tenant_id) VALUES($1,$2)',accounts[index],tenants[index])
            await database.execute("INSERT INTO public.shipments(id,tenant_id,carrier_account_id,customer_reference,tracking_number,carrier_code,upstream_shipment_id) VALUES($1,$2,$3,$4,$5,'ROYALMAIL','shp_offline')",shipments[index],tenants[index],accounts[index],f'ORDER-{index}',f'TRACK-{index}')
        settings=SimpleNamespace(booking_page_url='https://app.example.test',auth_recovery_redirect_url='',tracking_polling_enabled=False,provider_environment='TEST')
        engine=TrackingWorkspace(database,settings);await engine.initialise()
        support=TrackingSupportService(database,TrackingSettings(_env_file=None));support.workspace=engine
        yield SimpleNamespace(db=database,engine=engine,support=support,actors=actors,tenants=tenants,accounts=accounts,shipments=shipments,
                              scope=TrackingScope(tenants[0],actors[0]),settings=settings)
    finally:
        process.stdin.close();await process.wait()


@pytest.mark.asyncio
async def test_real_search_scopes_exact_references_and_admin_audits(world):
    w=world
    result=await w.engine.search(w.scope,q='ORDER-')
    assert len(result['shipments'])==1 and result['shipments'][0]['order_reference']=='ORDER-0'
    assert (await w.engine.search(w.scope,q='ORDER-1'))['shipments']==[]
    with pytest.raises(HTTPException) as error:await w.engine.detail(w.scope,w.shipments[1])
    assert error.value.status_code==404
    admin=TrackingScope(None,w.actors[0],True)
    result=await w.engine.search(admin,q='ORDER-')
    assert len(result['shipments'])==2 and {item['tenant_id'] for item in result['shipments']}=={str(value) for value in w.tenants}
    assert await w.db.fetchval("SELECT count(*) FROM public.tracking_operations_audit WHERE tenant_id IS NULL AND action='SEARCH'")==1


@pytest.mark.asyncio
async def test_public_capability_scope_redaction_and_revocation(world):
    w=world
    metadata={'automation_order':{'destination':{'name':'Private name','line1':'Private street','phone':'+447700900000'}},'secret':'not-public'}
    await w.db.execute('UPDATE public.shipments SET logistics_metadata=$2::jsonb WHERE id=$1',w.shipments[0],json.dumps(metadata))
    link=await w.engine.share(w.scope,w.shipments[0],ShareRequest())
    token=link['url'].split('#')[1]
    result=await w.engine.resolve(token)
    assert len(result['shipments'])==1 and result['shipments'][0]['order_reference']=='ORDER-0'
    encoded=json.dumps(result)
    for private in ('Private name','Private street','not-public',str(w.tenants[0]),str(w.shipments[0]),'account_id','raw_error'):
        assert private not in encoded
    stored=await w.db.fetchrow('SELECT token_sha256,shipment_ids FROM public.tracking_share_links WHERE id=$1',UUID(link['id']))
    assert stored['token_sha256']==hashlib.sha256(token.encode()).hexdigest()
    with pytest.raises(asyncpg.CheckViolationError):
        await w.db.execute('INSERT INTO public.tracking_share_links(tenant_id,anchor_shipment_id,shipment_ids,token_sha256,created_by,expires_at) VALUES($1,$2,$3,$4,$5,now()+interval \'1 day\')',w.tenants[0],w.shipments[0],[w.shipments[0],w.shipments[1]],'f'*64,w.actors[0])
    await w.db.execute('UPDATE public.tracking_share_links SET revoked_at=now() WHERE id=$1',UUID(link['id']))
    with pytest.raises(HTTPException) as error:await w.engine.resolve(token)
    assert error.value.status_code==404
    with pytest.raises(asyncpg.InsufficientPrivilegeError):await w.db.execute('UPDATE public.tracking_share_links SET revoked_at=NULL WHERE id=$1',UUID(link['id']))


@pytest.mark.asyncio
async def test_multi_parcel_split_order_and_independent_return_refund(world):
    w=world;store=uuid4();split=uuid4();returned=uuid4()
    await w.db.execute("UPDATE public.shipments SET ecommerce_store_id=$2,store_order_id='WEB-77',parcel_count=2,logistics_metadata=$3::jsonb WHERE id=$1",w.shipments[0],store,
                       json.dumps({'automation_label':{'package_labels':[{'tracking_number':'PIECE-1'},{'tracking_number':'PIECE-2'}]}}))
    await w.db.execute("INSERT INTO public.shipments(id,tenant_id,carrier_account_id,ecommerce_store_id,store_order_id,customer_reference) VALUES($1,$2,$3,$4,'WEB-77','SPLIT-77')",split,w.tenants[0],w.accounts[0],store)
    await w.db.execute("INSERT INTO public.shipments(id,tenant_id,carrier_account_id,customer_reference,tracking_lifecycle_type,return_of_shipment_id,store_return_status) VALUES($1,$2,$3,'RETURN-77','RETURN_SHIPMENT',$4,'RECEIVED')",returned,w.tenants[0],w.accounts[0],w.shipments[0])
    result=await w.engine.detail(w.scope,w.shipments[0])
    assert len(result['shipments'])==2 and len(result['shipments'][0]['parcels'])==2
    assert len(result['returns'])==1 and result['returns'][0]['return_status']=='RECEIVED'
    assert result['refund']==NO_REFUND
    assert 'SPLIT-77' in await w.engine.chat(SimpleNamespace(tenant_id=w.tenants[0],user_id=w.actors[0]),'WEB-77')
    link=await w.engine.share(w.scope,w.shipments[0],ShareRequest(include_order=True,include_returns=False))
    public=await w.engine.resolve(link['url'].split('#')[1]);assert len(public['shipments'])==2


@pytest.mark.asyncio
async def test_ingestion_replay_late_scans_immutable_facts_and_notification_dedup(world):
    w=world;key=TrackingKey(tenant_id=w.tenants[0],carrier_account_id=w.accounts[0],secret=SecretStr('x'*40))
    now=datetime.now(timezone.utc)-timedelta(minutes=10)
    event=TrackingEvent(event_id='evt-1',tracking_number='TRACK-0',status='IN_TRANSIT',milestone='OUT_FOR_DELIVERY',occurred_at=now)
    await w.support.ingest('test',key,event,'a'*64)
    assert (await w.support.ingest('test',key,event,'a'*64))['replayed']
    same=event.model_copy(update={'event_id':'evt-2'})
    await w.support.ingest('test',key,same,'b'*64)
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_notifications')==1
    late=TrackingEvent(event_id='evt-late',tracking_number='TRACK-0',status='IN_TRANSIT',occurred_at=now-timedelta(hours=1))
    assert not (await w.support.ingest('test',key,late,'c'*64))['applied']
    detail=await w.engine.detail(w.scope,w.shipments[0])
    item=detail['shipments'][0]
    assert item['status']=='OUT_FOR_DELIVERY' and len(item['timeline'])==2
    with pytest.raises(asyncpg.InsufficientPrivilegeError):await w.db.execute("UPDATE public.tracking_events SET raw_error='tampered'")
    await w.db.execute('UPDATE public.tracking_events SET support_pending=false')
    assert (await w.engine.search(w.scope,view='OUT_FOR_DELIVERY'))['counts']['out_for_delivery']==1
    unknown=TrackingEvent(event_id='unmapped',tracking_number='TRACK-0',status='UNKNOWN',milestone='UNKNOWN',
        source_status='future_provider_status',occurred_at=now+timedelta(minutes=1))
    assert not (await w.support.ingest('test',key,unknown,'d'*64))['applied']
    assert await w.db.fetchval("SELECT status FROM public.tracking_events WHERE event_id='unmapped'")=='UNKNOWN'
    assert await w.db.fetchval('SELECT status FROM public.shipments WHERE id=$1',w.shipments[0])=='IN_TRANSIT'
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_notifications')==1


@pytest.mark.asyncio
async def test_refresh_dedup_cooldown_lease_and_disabled_polling(world):
    w=world;worker=TrackingRefreshWorker(w.engine,w.support)
    with pytest.raises(HTTPException):await worker.enqueue(w.scope,w.shipments[0])
    w.settings.tracking_polling_enabled=True
    await worker.enqueue(w.scope,w.shipments[0]);await worker.enqueue(w.scope,w.shipments[0])
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_refresh_jobs')==1
    job=await worker.claim()
    assert job['tenant_id']==w.tenants[0] and job['attempts']==1 and job['lease_token']
    assert await worker.claim() is None
    await w.db.execute("UPDATE public.tracking_refresh_jobs SET lease_until=now()-interval '1 minute'")
    assert await worker.claim() is None  # account-wide 30-second cooldown is retained
    assert await w.db.fetchval('SELECT error_code FROM public.tracking_refresh_jobs')=='WORKER_INTERRUPTED'


@pytest.mark.asyncio
async def test_verified_customer_help_is_idempotent_bounded_and_tenant_owned(world):
    w=world
    link=await w.engine.share(w.scope,w.shipments[0],ShareRequest())
    token=link['url'].split('#')[1]
    body=CustomerRequest(token=token,request_id=uuid4(),note='Please check the delivery with the carrier.')
    assert (await w.engine.customer_request(body))['status']=='RECEIVED'
    assert (await w.engine.customer_request(body))['replayed']
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_customer_requests')==1
    detail=await w.engine.detail(w.scope,w.shipments[0])
    assert detail['customer_requests'][0]['note']==body.note
    assert 'Please check' not in json.dumps(await w.engine.resolve(token))
    assert (await w.engine.search(w.scope,view='CUSTOMER_REQUESTS'))['counts']['customer_requests']==1
    with pytest.raises(HTTPException) as error:
        await w.engine.customer_request(body.model_copy(update={'note':'A different request with the same identifier.'}))
    assert error.value.status_code==409
    for _ in range(2):await w.engine.customer_request(body.model_copy(update={'request_id':uuid4()}))
    with pytest.raises(HTTPException) as error:
        await w.engine.customer_request(body.model_copy(update={'request_id':uuid4()}))
    assert error.value.status_code==429
    assert not (await w.engine.search(TrackingScope(w.tenants[1],w.actors[1]),view='CUSTOMER_REQUESTS'))['shipments']


@pytest.mark.asyncio
async def test_expired_tokens_are_not_accepted(world):
    w=world;token='c'*43
    await w.db.execute("""INSERT INTO public.tracking_share_links(tenant_id,anchor_shipment_id,shipment_ids,token_sha256,created_by,created_at,expires_at)
        VALUES($1,$2,$3,$4,$5,now()-interval '2 days',now()-interval '1 day')""",w.tenants[0],w.shipments[0],[w.shipments[0]],hashlib.sha256(token.encode()).hexdigest(),w.actors[0])
    with pytest.raises(HTTPException) as error:await w.engine.resolve(token)
    assert error.value.status_code==404


@pytest.mark.asyncio
async def test_read_only_provider_reconciliation_and_transient_failure_fence(world):
    from unittest.mock import AsyncMock
    from main import CarrierAccount
    import httpx
    w=world;w.settings.tracking_polling_enabled=True
    member_id=await w.db.fetchval('SELECT id FROM public.users WHERE tenant_id=$1',w.tenants[0])
    await w.db.execute('UPDATE public.shipments SET created_by_user_id=$2 WHERE id=$1',w.shipments[0],member_id)
    worker=TrackingRefreshWorker(w.engine,w.support)
    await worker.seed()
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_refresh_jobs')==1
    owner=CarrierAccount(w.accounts[0],w.tenants[0],'EASYPOST','https://api.easypost.com/v2',None,5,'offline-test')
    w.engine.repository=SimpleNamespace(accounts=AsyncMock(return_value=[owner]))
    calls=[];failure=False
    now=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    def handler(request):
        calls.append(request.method)
        if failure:return httpx.Response(503,json={'error':'offline failure'})
        if '/shipments/' in request.url.path:return httpx.Response(200,json={'id':'shp_offline','mode':'test','tracker':{'id':'trk_offline'}})
        return httpx.Response(200,json={'id':'trk_offline','object':'Tracker','mode':'test','tracking_code':'TRACK-0',
            'status':'out_for_delivery','updated_at':now,'tracking_details':[{'status':'out_for_delivery','datetime':now,'message':'Out for delivery'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        w.engine.client=http
        await worker.process(await worker.claim())
        result=await w.engine.detail(w.scope,w.shipments[0]);assert result['shipments'][0]['status']=='OUT_FOR_DELIVERY'
        assert calls==['GET','GET']
        job=await w.db.fetchrow('SELECT * FROM public.tracking_refresh_jobs')
        assert job['last_success_at'] and job['attempts']==0 and job['state']=='DUE'
        failure=True
        await w.db.execute("UPDATE public.tracking_refresh_jobs SET next_attempt_at=now();")
        await w.db.execute("UPDATE public.tracking_provider_limits SET next_allowed_at=now()-interval '1 minute'")
        job=await worker.claim()
        await w.db.execute('UPDATE public.tracking_refresh_jobs SET attempts=5')
        job['attempts']=5
        await worker.process(job)
        dead=await w.db.fetchrow('SELECT * FROM public.tracking_refresh_jobs')
        assert dead['state']=='DEAD' and dead['lease_token'] is None and dead['error_code']=='PROVIDER_TEMPORARILY_UNAVAILABLE'
        assert all(method=='GET' for method in calls)


@pytest.mark.asyncio
async def test_platform_refresh_and_retry_after_are_account_bound(world):
    from unittest.mock import AsyncMock
    from main import CarrierAccount
    import httpx
    w=world;w.settings.tracking_polling_enabled=True;w.settings.platform_admin_user_ids=[w.actors[1]]
    worker=TrackingRefreshWorker(w.engine,w.support)
    await worker.enqueue(TrackingScope(None,w.actors[1],True),w.shipments[0])
    account=CarrierAccount(w.accounts[0],w.tenants[0],'EASYPOST','https://api.easypost.com/v2',None,5,'offline-test')
    w.engine.repository=SimpleNamespace(accounts=AsyncMock(return_value=[account]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(429,headers={'Retry-After':'600'},json={'error':'synthetic quota'}))) as client:
        w.engine.client=client
        await worker.process(await worker.claim())
    row=await w.db.fetchrow('SELECT * FROM public.tracking_refresh_jobs')
    assert row['error_code']=='PROVIDER_RATE_LIMITED' and row['state']=='DUE'
    assert row['next_attempt_at']>datetime.now(timezone.utc)+timedelta(seconds=590)
    account_hold=await w.db.fetchval('SELECT next_allowed_at FROM public.tracking_provider_limits')
    assert account_hold>datetime.now(timezone.utc)+timedelta(seconds=590)


@pytest.mark.asyncio
async def test_pickup_preferences_apply_only_to_future_carrier_events(world):
    w = world
    key = TrackingKey(tenant_id=w.tenants[0], carrier_account_id=w.accounts[0], secret=SecretStr('x'*40))
    start = datetime.now(timezone.utc) - timedelta(minutes=10)
    async def scan(index):
        event = TrackingEvent(event_id=f'pickup-{index}', tracking_number='TRACK-0',
            status='IN_TRANSIT', milestone='AVAILABLE_FOR_PICKUP', occurred_at=start+timedelta(minutes=index))
        return await w.support.ingest('test', key, event, str(index)*64)
    await scan(1)
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_notifications') == 0
    await w.db.execute("INSERT INTO public.tracking_preferences(tenant_id,categories) VALUES($1,ARRAY['AVAILABLE_FOR_PICKUP'])", w.tenants[0])
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_notifications') == 0
    await scan(2)
    assert await w.db.fetchval('SELECT category FROM public.tracking_notifications') == 'AVAILABLE_FOR_PICKUP'
    await w.db.execute('UPDATE public.tracking_preferences SET in_app_enabled=false WHERE tenant_id=$1', w.tenants[0])
    await scan(3)
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_notifications') == 1
    detail = await w.engine.detail(w.scope, w.shipments[0])
    assert detail['shipments'][0]['status'] == 'AVAILABLE_FOR_PICKUP'
    assert len(detail['shipments'][0]['timeline']) == 3
