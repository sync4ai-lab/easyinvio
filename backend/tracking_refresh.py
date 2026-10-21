"""Bounded read-only reconciliation. Never create a tracker or retry a purchase."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

import asyncpg
import httpx
from fastapi import HTTPException

from backend.automation_freight_engine import PurchaseRejected, PurchaseUncertain
from backend.integration_policy import integration_enabled
from backend.tracking_and_support import InternalTrackingSource
from backend.tracking_workspace import TrackingScope, obj

logger=logging.getLogger(__name__)


@dataclass(frozen=True)
class TrackingCapabilities:
    signed_webhooks: bool
    polling: bool
    creates_chargeable_resources: bool = False


class TrackingRateLimited(Exception):
    def __init__(self,retry_after=None):self.retry_after=retry_after


CAPABILITIES={
    'https://api.easypost.com/v2':TrackingCapabilities(True,True),
    'https://panel.sendcloud.sc/api/v3':TrackingCapabilities(True,False),
    'https://api.goshippo.com':TrackingCapabilities(True,False),
}


class EasyPostTrackingAdapter:
    """Retrieve an existing purchased shipment's tracker, preserving source binding."""
    async def lookup(self, client, account, shipment, environment):
        from backend.automation_three_partners import EasyPostAdapter, parse_easypost_tracking
        adapter=EasyPostAdapter(client,account.api_key,environment=environment)
        async def read(path):
            try:return await adapter.request('GET',path)
            except PurchaseUncertain:
                if adapter.last_http_status==429:raise TrackingRateLimited(adapter.last_retry_after_seconds) from None
                raise
        metadata=obj(shipment['logistics_metadata'])
        pieces=obj(metadata.get('automation_label')).get('package_labels') or []
        ids=[piece.get('upstream_id') for piece in pieces] or [shipment.get('upstream_shipment_id')]
        if not ids or len(ids)>100 or any(not isinstance(value,str) or not re.fullmatch(r'shp_[A-Za-z0-9]+',value) for value in ids):
            raise PurchaseRejected('TRACKING_REMOTE_SHIPMENT_REFERENCE_REQUIRED')
        expected={piece.get('tracking_number') for piece in pieces} or {shipment.get('tracking_number')}
        events=[]
        for remote_id in ids:
            remote=await read('/shipments/'+remote_id)
            if remote.get('id')!=remote_id or remote.get('mode')!=('test' if environment=='TEST' else 'production'):
                raise PurchaseRejected('TRACKING_REMOTE_IDENTITY_MISMATCH')
            tracker=remote.get('tracker') or {}
            tracker_id=tracker.get('id') if isinstance(tracker,dict) else tracker
            if not isinstance(tracker_id,str) or not re.fullmatch(r'trk_[A-Za-z0-9]+',tracker_id):
                continue
            tracker=await read('/trackers/'+tracker_id)
            if tracker.get('id')!=tracker_id or tracker.get('tracking_code') not in expected:
                raise PurchaseRejected('TRACKING_NUMBER_BINDING_MISMATCH')
            scans=tracker.get('tracking_details') or []
            if len(scans)>1000:raise PurchaseRejected('TRACKING_HISTORY_LIMIT')
            snapshots=[]
            for scan in scans:
                if scan.get('status') not in {'in_transit','out_for_delivery','available_for_pickup','delivered','failure','error','return_to_sender'}:
                    continue
                snapshots.append({**tracker,'status':scan['status'],'updated_at':scan['datetime'],'tracking_details':[scan]})
            if not snapshots:snapshots=[tracker]
            for snapshot in snapshots:
                digest=hashlib.sha256(json.dumps([tracker_id,snapshot.get('status'),snapshot.get('updated_at')],separators=(',',':')).encode()).hexdigest()
                parsed=parse_easypost_tracking({'description':'tracker.updated','id':'poll:'+digest,'result':snapshot},environment,preserve_unknown=True)
                if parsed:
                    # POD retrieval has its own existing approved-host boundary.
                    event=parsed[0].model_copy(update={'proof_of_delivery_url':None})
                    facts=json.dumps(event.model_dump(mode='json',exclude={'event_id'}),sort_keys=True,separators=(',',':'))
                    events.append(event.model_copy(update={'event_id':'poll:'+hashlib.sha256(facts.encode()).hexdigest()}))
        # A valid existing tracker can still be pre-transit. Preserve that absence
        # and check again on schedule; do not manufacture a scan or mark it failed.
        return events


class TrackingRefreshWorker:
    def __init__(self, workspace, tracking):
        self.workspace,self.tracking=workspace,tracking

    async def seed(self):
        engine=self.workspace
        if not integration_enabled('https://api.easypost.com/v2',engine.settings):return
        async with engine.pool.acquire() as connection:
            await connection.execute('''INSERT INTO public.tracking_refresh_jobs(tenant_id,shipment_id,requested_by)
                SELECT s.tenant_id,s.id,u.auth_user_id FROM public.shipments s
                JOIN public.users u ON u.tenant_id=s.tenant_id AND u.id=s.created_by_user_id AND u.is_active
                JOIN public.tenants t ON t.tenant_id=s.tenant_id AND t.workspace_status='ACTIVE'
                JOIN public.carrier_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.carrier_account_id AND a.is_active
                WHERE a.api_base_url='https://api.easypost.com/v2' AND a.environment=$1 AND u.role IN ('OWNER','ADMIN','DISPATCHER')
                AND s.status::text IN ('BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION') AND s.created_at>now()-interval '90 days'
                AND NOT EXISTS(SELECT 1 FROM public.tracking_refresh_jobs j WHERE j.tenant_id=s.tenant_id AND j.shipment_id=s.id)
                ORDER BY s.created_at DESC LIMIT 100 ON CONFLICT(tenant_id,shipment_id) DO NOTHING''',engine.settings.provider_environment)

    async def enqueue(self,scope,shipment_id,*,retry=False):
        engine=self.workspace;engine.require_ready()
        if not getattr(engine.settings,'tracking_polling_enabled',False):
            raise HTTPException(409,'Carrier refresh is not enabled. Signed carrier webhooks and recorded tracking remain available.')
        async with engine.pool.acquire() as connection:
            async with connection.transaction():
                row=await engine.row(connection,scope,shipment_id)
                capability=CAPABILITIES.get(row['api_base_url'])
                if not capability or not capability.polling:
                    raise HTTPException(409,'This connection supports webhook tracking only; no verified polling adapter is installed.')
                if not integration_enabled(row['api_base_url'],engine.settings):raise HTTPException(409,'This carrier integration is disabled')
                if row['status'] not in {'BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION'}:
                    raise HTTPException(409,'Refresh is available only for active confirmed shipments')
                current=TrackingScope(row['tenant_id'],scope.actor_id,scope.platform)
                if retry:
                    updated=await connection.fetchrow('''UPDATE public.tracking_refresh_jobs SET state='DUE',attempts=0,
                        next_attempt_at=now(),error_code=NULL,lease_token=NULL,lease_until=NULL,requested_by=$3,updated_at=now()
                        WHERE tenant_id=$1 AND shipment_id=$2 AND state IN ('DEAD','UNSUPPORTED') RETURNING state''',current.tenant_id,shipment_id,current.actor_id)
                    if updated is None:raise HTTPException(409,'Only failed or unsupported jobs may be explicitly retried')
                else:
                    await connection.execute('''INSERT INTO public.tracking_refresh_jobs(tenant_id,shipment_id,requested_by)
                        VALUES($1,$2,$3) ON CONFLICT(tenant_id,shipment_id) DO NOTHING''',current.tenant_id,shipment_id,current.actor_id)
                job=await connection.fetchrow('SELECT state,next_attempt_at FROM public.tracking_refresh_jobs WHERE tenant_id=$1 AND shipment_id=$2',current.tenant_id,shipment_id)
                if job['state'] in {'DEAD','UNSUPPORTED','COMPLETE'}:
                    raise HTTPException(409,'This refresh is held or finished. A platform operator must review a failed job before an explicit retry.')
                await engine.audit(connection,current,'RETRY' if retry else 'REFRESH',shipment_id)
        return {'status':job['state'],'next_attempt_at':job['next_attempt_at'].isoformat(),
                'message':'Read-only carrier refresh is scheduled or already running. Existing cooldowns are preserved.'}

    async def claim(self):
        async with self.workspace.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("""UPDATE public.tracking_refresh_jobs SET state=CASE WHEN attempts>=5 THEN 'DEAD' ELSE 'DUE' END,
                    lease_token=NULL,lease_until=NULL,error_code='WORKER_INTERRUPTED',updated_at=now()
                    WHERE state='RUNNING' AND lease_until<now()""")
                job=await connection.fetchrow('''SELECT j.*,s.carrier_account_id FROM public.tracking_refresh_jobs j
                    JOIN public.shipments s ON s.tenant_id=j.tenant_id AND s.id=j.shipment_id
                    WHERE j.state='DUE' AND j.next_attempt_at<=now() AND j.attempts<5
                    ORDER BY j.next_attempt_at FOR UPDATE OF j SKIP LOCKED LIMIT 1''')
                if not job:return None
                admitted=await connection.fetchval('''INSERT INTO public.tracking_provider_limits(carrier_account_id,next_allowed_at)
                    VALUES($1,now()+interval '30 seconds') ON CONFLICT(carrier_account_id) DO UPDATE
                    SET next_allowed_at=now()+interval '30 seconds' WHERE tracking_provider_limits.next_allowed_at<=now()
                    RETURNING carrier_account_id''',job['carrier_account_id'])
                if not admitted:
                    await connection.execute('''UPDATE public.tracking_refresh_jobs SET next_attempt_at=(SELECT next_allowed_at FROM public.tracking_provider_limits WHERE carrier_account_id=$3)
                        WHERE tenant_id=$1 AND shipment_id=$2''',job['tenant_id'],job['shipment_id'],job['carrier_account_id'])
                    return None
                token=uuid4()
                await connection.execute("""UPDATE public.tracking_refresh_jobs SET state='RUNNING',lease_token=$3,
                    lease_until=now()+interval '45 seconds',attempts=attempts+1,last_attempt_at=now(),updated_at=now()
                    WHERE tenant_id=$1 AND shipment_id=$2""",job['tenant_id'],job['shipment_id'],token)
                return {**dict(job),'lease_token':token,'attempts':job['attempts']+1}

    async def process(self,job):
        engine=self.workspace
        from main import TenantContext
        error=None;unsupported=False;terminal=False;interval=360;retry_after=0
        try:
            async with engine.pool.acquire() as connection:
                shipment=await connection.fetchrow('SELECT * FROM public.shipments WHERE tenant_id=$1 AND id=$2',job['tenant_id'],job['shipment_id'])
                member=await connection.fetchrow('''SELECT u.role FROM public.users u JOIN public.tenants t ON t.tenant_id=u.tenant_id
                    WHERE u.tenant_id=$1 AND u.auth_user_id=$2 AND u.is_active AND t.workspace_status='ACTIVE' ''',job['tenant_id'],job['requested_by'])
                active=await connection.fetchval('SELECT is_active FROM public.carrier_accounts WHERE tenant_id=$1 AND id=$2',job['tenant_id'],job['carrier_account_id'])
                if member is None and job['requested_by'] in set(getattr(engine.settings,'platform_admin_user_ids',[])):
                    if await connection.fetchval("SELECT workspace_status='ACTIVE' FROM public.tenants WHERE tenant_id=$1",job['tenant_id']):
                        member={'role':'ADMIN'}  # Current server allowlist, not a fabricated tenant membership.
                pref=await engine.preferences(connection,job['tenant_id']);interval=pref.poll_interval_minutes
            if not shipment or not member or member['role'] not in {'OWNER','ADMIN','DISPATCHER'} or not active:
                raise PurchaseRejected('TRACKING_SCOPE_OR_CONNECTION_INACTIVE')
            terminal=shipment['status'] in {'DELIVERED','CANCELLED','FAILED'}
            if not terminal:
                context=TenantContext(job['tenant_id'],job['requested_by'],member['role'],'')
                accounts=await engine.repository.accounts(context,historical_account_id=shipment['carrier_account_id'])
                account=next((item for item in accounts if item.id==shipment['carrier_account_id']),None)
                if not account or account.base_url!='https://api.easypost.com/v2':raise PurchaseRejected('TRACKING_POLLING_UNSUPPORTED')
                if not integration_enabled(account.base_url,engine.settings):raise PurchaseRejected('TRACKING_PROVIDER_DISABLED')
                async with asyncio.timeout(12):
                    events=await EasyPostTrackingAdapter().lookup(engine.client,account,shipment,engine.settings.provider_environment)
                    for event in sorted(events,key=lambda item:item.scan_occurred_at or item.occurred_at):
                        canonical=event.model_dump(mode='json')
                        digest=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                        key=InternalTrackingSource(tenant_id=job['tenant_id'],carrier_account_id=account.id)
                        await self.tracking.ingest('poll:'+str(account.id),key,event,digest)
                    async with engine.pool.acquire() as connection:
                        status=await connection.fetchval('SELECT status::text FROM public.shipments WHERE tenant_id=$1 AND id=$2',job['tenant_id'],job['shipment_id'])
                    terminal=status in {'DELIVERED','CANCELLED','FAILED'}
        except TrackingRateLimited as exc:
            error='PROVIDER_RATE_LIMITED';retry_after=exc.retry_after if exc.retry_after is not None else 3600
        except PurchaseRejected as exc:
            error='AUTHENTICATION_REJECTED' if 'HTTP_401' in str(exc) or 'HTTP_403' in str(exc) else 'UNSUPPORTED_OR_REJECTED'
            unsupported=error!='AUTHENTICATION_REJECTED'
        except (TimeoutError,httpx.HTTPError,PurchaseUncertain):error='PROVIDER_TEMPORARILY_UNAVAILABLE'
        except (ValueError,KeyError,TypeError):error='INVALID_PROVIDER_RESPONSE'
        except (asyncpg.PostgresError,HTTPException):error='TRACKING_STORAGE_OR_SCOPE_UNAVAILABLE'
        async with engine.pool.acquire() as connection:
            if error:
                state='UNSUPPORTED' if unsupported else 'DEAD' if job['attempts']>=5 else 'DUE'
                delay=max(retry_after,min(3600,30*2**job['attempts']))+random.SystemRandom().randint(0,30)
                if error=='PROVIDER_RATE_LIMITED':
                    await connection.execute('''UPDATE public.tracking_provider_limits SET next_allowed_at=GREATEST(next_allowed_at,now()+make_interval(secs=>$2))
                        WHERE carrier_account_id=$1''',job['carrier_account_id'],delay)
                await connection.execute('''UPDATE public.tracking_refresh_jobs SET state=$4,error_code=$5,next_attempt_at=now()+make_interval(secs=>$6),
                    lease_token=NULL,lease_until=NULL,updated_at=now() WHERE tenant_id=$1 AND shipment_id=$2 AND lease_token=$3''',
                    job['tenant_id'],job['shipment_id'],job['lease_token'],state,error,delay)
            else:
                await connection.execute('''UPDATE public.tracking_refresh_jobs SET state=$4,attempts=0,error_code=NULL,last_success_at=now(),
                    next_attempt_at=now()+make_interval(mins=>$5),lease_token=NULL,lease_until=NULL,updated_at=now()
                    WHERE tenant_id=$1 AND shipment_id=$2 AND lease_token=$3''',job['tenant_id'],job['shipment_id'],job['lease_token'],'COMPLETE' if terminal else 'DUE',interval)

    async def worker(self):
        next_seed=0
        while True:
            try:
                if time.monotonic()>=next_seed:
                    await self.seed();next_seed=time.monotonic()+60
                job=await self.claim()
                if job:await self.process(job)
            except (asyncpg.PostgresError,ValueError,KeyError,TypeError):
                logger.warning('Tracking reconciliation deferred; durable job retained')
            await asyncio.sleep(2)
