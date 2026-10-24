"""Native partner lifecycle contracts behind EasyInvio's private account boundary.

Mutating HTTP requests are never retried automatically. A timeout is an unknown
outcome, not a rejected purchase. Return snapshots must contain a newly quoted
return service; a forward price is never reused as a return authorization.
"""
from __future__ import annotations

import copy
import asyncio
import json
import hashlib
import hmac
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Literal
import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from pydantic import Field, SecretStr, field_validator
from backend.tracking_and_support import TrackingEvent, TrackingKey
from decimal import Decimal
from uuid import UUID, uuid5, NAMESPACE_URL
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from backend.automation_freight_engine import PurchaseRejected, PurchaseUncertain, Order


class NativeProviderSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    order_sync_enabled: bool = False
    sendcloud_integration_id: int | None = Field(default=None, gt=0, strict=True)
    webhook_enabled: bool = False
    webhook_auth: Literal['HMAC', 'URL_TOKEN'] = 'HMAC'
    webhook_secret: SecretStr | None = None
    pod_allowed_hosts: list[str] = Field(default_factory=list, max_length=30)
    sendcloud_status_map: dict[str, Literal['IN_TRANSIT', 'DELIVERED', 'EXCEPTION']] = Field(default_factory=dict)

    @field_validator('pod_allowed_hosts')
    @classmethod
    def hostnames(cls, values):
        import ipaddress
        for host in values:
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '.' not in host or host.endswith('.local'):
                raise ValueError('Use exact public carrier/storage hostnames')
            try:
                ipaddress.ip_address(host)
            except ValueError:
                continue
            raise ValueError('IP addresses are not allowed')
        return values

    @field_validator('sendcloud_status_map')
    @classmethod
    def numeric_statuses(cls, values):
        if len(values)>200 or any(not re.fullmatch(r'[0-9]{1,6}', key) for key in values):
            raise ValueError('Sendcloud status identifiers must be numeric strings')
        return values

    @field_validator('webhook_secret')
    @classmethod
    def secret_length(cls, value):
        if value and not 32 <= len(value.get_secret_value().encode()) <= 4096:
            raise ValueError('Use a webhook secret of 32â€“4096 bytes')
        return value


class NativeOrderSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tenant_id: UUID
    shipment_ids: list[UUID] = Field(min_length=1, max_length=100)


class NativeOrderReconciliation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tenant_id:UUID
    shipment_id:UUID
    remote_object_id:str=Field(min_length=1,max_length=200,pattern=r'^[A-Za-z0-9_-]+$')


def decode_json(value):
    return json.loads(value, parse_float=Decimal) if isinstance(value, str) else ({} if value is None else value)


def native_timestamp(value):
    from datetime import timedelta
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        integer = int(value)
        return datetime.fromtimestamp(integer, timezone.utc) + timedelta(microseconds=int((Decimal(value)-integer)*1000000))
    if not isinstance(value, str):
        raise ValueError('Tracking timestamp missing')
    result = datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('Tracking timestamp requires timezone')
    return result


def native_pod(body):
    # Only supplied URLs are mapped. A signer name is not a POD image.
    value = body.get('proof_of_delivery_url') or body.get('signature_url')
    if value is None and isinstance(body.get('proof_of_delivery'), dict):
        value = body['proof_of_delivery'].get('url')
    return value


def enrich_easypost_event(event, tracker, latest):
    detailed={'out_for_delivery':'OUT_FOR_DELIVERY','available_for_pickup':'AVAILABLE_FOR_PICKUP','return_to_sender':'RETURNED_TO_SENDER'}
    values={'milestone':detailed.get(tracker['status'],event.status),'source_status':tracker['status'],
            'scan_occurred_at':native_timestamp(latest['datetime']) if latest.get('datetime') else None}
    location=latest.get('tracking_location') or {}
    city=location.get('city') if isinstance(location,dict) else None
    if isinstance(city,str) and re.fullmatch(r"[\w .'-]{1,80}",city):values['location']=city
    estimate=tracker.get('est_delivery_date')
    if isinstance(estimate,str):
        try:
            candidate=datetime.fromisoformat(estimate.replace('Z','+00:00'))
            if candidate.tzinfo is not None:values['estimated_delivery_at']=candidate
        except ValueError:pass
    return TrackingEvent.model_validate({**event.model_dump(),**values})


def parse_easypost_tracking(body, environment, *, preserve_unknown=False):
    if body.get('description') != 'tracker.updated':
        return None
    tracker = body['result']
    if tracker.get('object')!='Tracker' or tracker.get('mode')!=('test' if environment=='TEST' else 'production'):
        raise ValueError('Tracking mode mismatch')
    status = {'in_transit':'IN_TRANSIT','out_for_delivery':'IN_TRANSIT','available_for_pickup':'IN_TRANSIT',
              'delivered':'DELIVERED','failure':'EXCEPTION','error':'EXCEPTION','return_to_sender':'EXCEPTION'}.get(tracker['status'])
    if status is None:
        if not preserve_unknown:return None
        status='UNKNOWN'
    details = tracker.get('tracking_details') or []
    latest = max(details, key=lambda value:native_timestamp(value['datetime'])) if details else {}
    event = TrackingEvent(event_id=body['id'], tracking_number=tracker['tracking_code'], status=status,
        occurred_at=native_timestamp(tracker['updated_at']),
        raw_error=str(latest.get('message') or tracker.get('status_detail') or '')[:4000],
        proof_of_delivery_url=native_pod(tracker) if status=='DELIVERED' else None)
    event=enrich_easypost_event(event,tracker,latest)
    return event, tracker.get('shipment_id'), 'EASYPOST'


def parse_sendcloud_tracking(body, status_map, *, preserve_unknown=False):
    if body.get('action') != 'parcel_status_changed':
        return None
    parcel = body['parcel']
    identifier_value = parcel['status']['id']
    if type(identifier_value) is not int:
        raise ValueError('Invalid parcel status identifier')
    status = status_map.get(str(identifier_value))
    if status is None:
        if not preserve_unknown:return None
        status='UNKNOWN'
    timestamp = native_timestamp(body.get('carrier_status_change_timestamp') or body['timestamp'])
    facts = {'tracking_number':parcel['tracking_number'],'status':status,'occurred_at':timestamp.isoformat(),
             'raw_error':str(parcel['status'].get('message',''))[:4000],
             'proof_of_delivery_url':native_pod(parcel) if status=='DELIVERED' else None}
    event_id = 'sc:' + hashlib.sha256(decimal_json(facts).encode()).hexdigest()
    return TrackingEvent(event_id=event_id,milestone=status,source_status='status:'+str(identifier_value), **facts), None, 'SENDCLOUD'


def parse_shippo_tracking(body, environment, *, preserve_unknown=False):
    if body.get('event')!='track_updated':
        return None
    if body.get('test') is not (environment=='TEST'):
        raise ValueError('Tracking mode mismatch')
    data = body['data']
    milestone = data['tracking_status']
    status = {'TRANSIT':'IN_TRANSIT','DELIVERED':'DELIVERED','FAILURE':'EXCEPTION','RETURNED':'EXCEPTION'}.get(milestone['status'])
    if status is None:
        if not preserve_unknown:return None
        status='UNKNOWN'
    facts = {'tracking_number':data['tracking_number'],'status':status,
        'occurred_at':native_timestamp(milestone['status_date']).isoformat(),
        'raw_error':str(milestone.get('status_details') or milestone.get('substatus',{}).get('text') or '')[:4000],
        'proof_of_delivery_url':(native_pod(milestone) or native_pod(data)) if status=='DELIVERED' else None}
    event_id = 'sp:' + hashlib.sha256(decimal_json(facts).encode()).hexdigest()
    transaction = data.get('transaction')
    if isinstance(transaction, dict):
        transaction = transaction.get('object_id')
    return TrackingEvent(event_id=event_id,milestone='RETURNED_TO_SENDER' if milestone['status']=='RETURNED' else status,source_status=milestone['status'], **facts), transaction, 'SHIPPO'


def verify_native_signature(request, raw, provider, auth_method, secret, now=None):
    """Validate native signatures, or Shippo's documented fallback URL token."""
    if provider=='EASYPOST':
        name='x-hmac-signature'
        expected='hmac-sha256-hex=' + hmac.new(unicodedata.normalize('NFKD',secret).encode(),raw,hashlib.sha256).hexdigest()
    elif provider=='SENDCLOUD':
        name='sendcloud-signature'
        expected=hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
    elif provider=='SHIPPO' and auth_method=='URL_TOKEN':
        from backend.webhook_security import enforce_shippo_source_ip
        enforce_shippo_source_ip(request)
        tokens=request.query_params.getlist('token')
        if len(tokens)!=1 or not hmac.compare_digest(secret.encode(),tokens[0].encode()):
            raise HTTPException(401,'Invalid tracking authentication')
        return
    elif provider=='SHIPPO':
        from backend.webhook_security import enforce_shippo_source_ip
        enforce_shippo_source_ip(request)
        name='shippo-auth-signature'
        values=request.headers.getlist(name)
        if len(values)!=1:
            raise HTTPException(401,'Invalid tracking authentication')
        try:
            fields=values[0].split(',')
            if len(fields)!=2:
                raise ValueError()
            timestamp,signature=(field.split('=',1) for field in fields)
            if timestamp[0]!='t' or signature[0]!='v1' or not re.fullmatch(r'[0-9]{1,12}',timestamp[1]):
                raise ValueError()
            if abs((time.time() if now is None else now)-int(timestamp[1]))>300:
                raise ValueError()
            expected=hmac.new(secret.encode(),timestamp[1].encode()+b'.'+raw,hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected.encode(),signature[1].encode()):
                raise ValueError()
        except (ValueError,TypeError):
            raise HTTPException(401,'Invalid tracking authentication') from None
        return
    else:
        raise HTTPException(401,'Tracking provider is not configured')
    values=request.headers.getlist(name)
    if len(values)!=1 or not hmac.compare_digest(expected.encode(),values[0].encode()):
        raise HTTPException(401,'Invalid tracking authentication')


class NativePartnerService:
    """Selected-provider order synchronization and authenticated native tracking."""
    def __init__(self, automation, client, tracking):
        self.automation, self.client, self.tracking = automation, client, tracking
        self.pool, self.settings = automation.pool, automation.settings

    def decrypt_secret(self, row, name='credentials_ciphertext'):
        try:
            key=self.settings.credential_keys[row['credential_key_id']].get_secret_value()
            return Fernet(key.encode()).decrypt(bytes(row[name])).decode()
        except (KeyError,ValueError,InvalidToken,UnicodeError):
            raise HTTPException(503,'Private provider configuration unavailable') from None

    async def ensure_order(self, tenant_id, shipment_id, account_id):
        """Selected-provider native order confirmation precedes label purchase."""
        async with self.pool.acquire() as connection:
            row=await connection.fetchrow('''SELECT s.logistics_metadata,s.created_at,s.upstream_shipment_id
                FROM public.shipments s JOIN public.carrier_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.carrier_account_id
                JOIN public.partner_provider_options o ON o.platform_connection_id=a.platform_connection_id
                WHERE s.tenant_id=$1 AND s.id=$2 AND a.id=$3 AND o.order_sync_enabled''',tenant_id,shipment_id,account_id)
            if row is None:
                return
            metadata=decode_json(row['logistics_metadata'])
            if metadata.get('automation_order',{}).get('is_return'):
                return
            payload={'order':metadata['automation_order'],'customs':metadata.get('automation_customs'),
                     'placed_at':row['created_at'].isoformat(),'upstream_shipment_id':row['upstream_shipment_id']}
            await connection.execute('''INSERT INTO public.partner_order_jobs(tenant_id,shipment_id,carrier_account_id,payload)
                VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(tenant_id,shipment_id,carrier_account_id) DO UPDATE SET
                state='PENDING',payload=excluded.payload,last_error=NULL,updated_at=now()
                WHERE public.partner_order_jobs.state='FAILED' AND public.partner_order_jobs.remote_object_id IS NULL''',tenant_id,shipment_id,account_id,json.dumps(payload))
            previous=await connection.fetchval('SELECT payload FROM public.partner_order_jobs WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3',tenant_id,shipment_id,account_id)
            saved=decode_json(previous)
            if saved.get('order')!=payload['order'] or saved.get('customs')!=payload['customs']:
                raise HTTPException(409,'Native order packing/customs changed; reconcile or prepare a new order before purchase')
        result=await self.sync_one(tenant_id,shipment_id,account_id)
        if result['state']!='SYNCED':
            raise HTTPException(409,'Native order is not confirmed; wait or reconcile before buying a label')

    async def sync_one(self, tenant_id, shipment_id, account_id, candidate_remote_id=None):
        key='native-order:'+str(tenant_id)+':'+str(shipment_id)+':'+str(account_id)
        async with self.pool.acquire() as connection:
            if not await connection.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))',key):
                return {'state':'BUSY'}
            try:
                row=await connection.fetchrow('SELECT * FROM public.partner_order_jobs WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3',tenant_id,shipment_id,account_id)
                if row is None:
                    raise HTTPException(404,'Native order job not found')
                if candidate_remote_id and row['state'] not in {'SENDING','RECONCILIATION_REQUIRED','FAILED'}:
                    raise HTTPException(409,'This native order is not awaiting reconciliation')
                reconciling = bool(candidate_remote_id) or (row['state']=='RECONCILIATION_REQUIRED' and row['remote_object_id'] is not None)
                if row['state']!='PENDING' and not reconciling:
                    return {'state':row['state']}
                account=await connection.fetchrow('''SELECT a.*,o.order_sync_enabled,o.sendcloud_integration_id,
                    s.carrier_account_id AS selected_account,t.is_sandbox,t.workspace_status
                    FROM public.carrier_accounts a JOIN public.partner_provider_options o ON o.platform_connection_id=a.platform_connection_id
                    JOIN public.shipments s ON s.tenant_id=a.tenant_id AND s.id=$3
                    JOIN public.tenants t ON t.tenant_id=a.tenant_id WHERE a.tenant_id=$1 AND a.id=$2''',tenant_id,account_id,shipment_id)
                if not account or not account['is_active'] or not account['order_sync_enabled'] or account['workspace_status']!='ACTIVE' or account['selected_account']!=account_id:
                    await connection.execute("UPDATE public.partner_order_jobs SET state='SUPERSEDED',updated_at=now() WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3",tenant_id,shipment_id,account_id)
                    return {'state':'SUPERSEDED'}
                if account['environment']!=self.settings.provider_environment or account['is_sandbox']!=(account['environment']=='TEST') or self.settings.database_environment!=('SANDBOX' if account['environment']=='TEST' else 'LIVE'):
                    raise HTTPException(403,'Provider environment mismatch')
                try:
                    payload=decode_json(row['payload'])
                    order=Order.model_validate(payload['order'])
                    snapshot=order.model_dump(mode='json')
                    snapshot.update(tenant_id=str(tenant_id),shipment_id=str(shipment_id),placed_at=payload['placed_at'],
                        upstream_shipment_id=payload.get('upstream_shipment_id'),customs_document=payload.get('customs'),
                        sendcloud_integration_id=account['sendcloud_integration_id'])
                    envelope=json.loads(self.decrypt_secret(account))
                    if envelope.get('platform_id')!=str(account['platform_connection_id']):
                        raise HTTPException(503,'Private provider identity mismatch')
                    from types import SimpleNamespace
                    adapter=create_adapter(self.client,SimpleNamespace(base_url=account['api_base_url'],api_key=envelope['api_key']),environment=account['environment'])
                except (HTTPException,ValueError,KeyError,TypeError) as exc:
                    state='RECONCILIATION_REQUIRED' if reconciling else 'FAILED'
                    await connection.execute('''UPDATE public.partner_order_jobs SET state=$4,last_error=$5,updated_at=now()
                        WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3''',tenant_id,shipment_id,account_id,state,'PRE_SUBMISSION:'+type(exc).__name__)
                    try:
                        await self.automation.fail_ticket(tenant_id,uuid5(NAMESPACE_URL,key),str(shipment_id),shipment_id,'NATIVE_ORDER_CONFIGURATION_OR_PACKING_INVALID')
                    except Exception:
                        logger.warning('Native order preflight ticket deferred')
                    raise HTTPException(502,'Native order packing or private connection configuration needs correction; no order was submitted') from None
                # Commit the send fence before remote mutation. A process crash
                # leaves SENDING for reconciliation, never another POST.
                if not reconciling:
                    await connection.execute("UPDATE public.partner_order_jobs SET state='SENDING',attempts=attempts+1,updated_at=now() WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3",tenant_id,shipment_id,account_id)
                else:
                    await connection.execute('UPDATE public.partner_order_jobs SET attempts=attempts+1,updated_at=now() WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3',tenant_id,shipment_id,account_id)
                try:
                    result=await adapter.retrieve_order(candidate_remote_id or row['remote_object_id'],snapshot) if reconciling else await adapter.sync_order(snapshot)
                    await connection.execute('''UPDATE public.partner_order_jobs SET state='SYNCED',remote_object_id=$4,
                        remote_object_type=$5,last_error=NULL,updated_at=now() WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3''',tenant_id,shipment_id,account_id,str(result['remote_id']),result['object_type'])
                except Exception as exc:
                    state='FAILED' if isinstance(exc,PurchaseRejected) and not reconciling else 'RECONCILIATION_REQUIRED'
                    code=type(exc).__name__+':'+type(adapter).__name__+(':'+str(exc)[:200] if isinstance(exc,(PurchaseRejected,PurchaseUncertain)) else '')
                    logger.warning('Native order deferred provider=%s shipment=%s type=%s',type(adapter).__name__,shipment_id,type(exc).__name__)
                    await connection.execute('''UPDATE public.partner_order_jobs SET state=$4,last_error=$5,remote_object_id=coalesce($6,remote_object_id),remote_object_type=coalesce($7,remote_object_type),updated_at=now()
                        WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3''',tenant_id,shipment_id,account_id,state,code,adapter.last_order_id,adapter.last_order_kind)
                    try:
                        await self.automation.fail_ticket(tenant_id,uuid5(NAMESPACE_URL,key),str(shipment_id),shipment_id,'NATIVE_ORDER_'+state)
                    except Exception:
                        logger.warning('Native order support ticket deferred; durable failure retained')
                    raise HTTPException(502,{'operation':'native_order_sync','shipment_id':str(shipment_id),'state':state,
                        'reason':'Provider rejected the order' if state=='FAILED' else 'Provider outcome requires reconciliation; no automatic resend'}) from None
                return {'state':'SYNCED'}
            finally:
                await connection.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))',key)

    async def worker(self):
        while True:
            try:
                async with self.pool.acquire() as connection:
                    rows=await connection.fetch("SELECT tenant_id,shipment_id,carrier_account_id FROM public.partner_order_jobs WHERE state='PENDING' OR (state='RECONCILIATION_REQUIRED' AND remote_object_id IS NOT NULL AND attempts<30 AND updated_at<now()-interval '30 seconds') ORDER BY updated_at LIMIT 20")
                for row in rows:
                    try:
                        await self.sync_one(row['tenant_id'],row['shipment_id'],row['carrier_account_id'])
                    except (HTTPException,asyncpg.PostgresError,ValueError,KeyError,TypeError):
                        logger.warning('Native order processing deferred; durable state retained')
                await self.fulfillment_cycle()
            except asyncpg.PostgresError:
                logger.warning('Native order queue unavailable')
            await asyncio.sleep(10)

    async def fulfillment_cycle(self):
        async with self.pool.acquire() as connection:
            rows=await connection.fetch('''SELECT j.*,s.logistics_metadata,a.api_base_url,a.environment,
                a.platform_connection_id,a.credentials_ciphertext,a.credential_key_id FROM public.partner_order_jobs j
                JOIN public.shipments s ON s.tenant_id=j.tenant_id AND s.id=j.shipment_id AND s.carrier_account_id=j.carrier_account_id
                JOIN public.carrier_accounts a ON a.tenant_id=j.tenant_id AND a.id=j.carrier_account_id
                WHERE j.state='SYNCED' AND j.fulfillment_state<>'CONFIRMED' AND j.fulfillment_attempts<30
                AND s.status IN ('BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED')
                AND (j.fulfillment_attempts=0 OR j.updated_at<now()-interval '30 seconds') LIMIT 20''')
        for row in rows:
            key='native-fulfillment:'+str(row['tenant_id'])+':'+str(row['shipment_id'])
            async with self.pool.acquire() as connection:
                if not await connection.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))',key):
                    continue
                try:
                    current=await connection.fetchval('''SELECT fulfillment_state FROM public.partner_order_jobs
                        WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3''',row['tenant_id'],row['shipment_id'],row['carrier_account_id'])
                    if current=='CONFIRMED':
                        continue
                    await connection.execute('''UPDATE public.partner_order_jobs SET fulfillment_attempts=fulfillment_attempts+1,updated_at=now()
                        WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3''',row['tenant_id'],row['shipment_id'],row['carrier_account_id'])
                    try:
                        metadata=decode_json(row['logistics_metadata'])
                        label=metadata['automation_label']
                        snapshot=decode_json(row['payload'])['order']
                        snapshot.update(tenant_id=str(row['tenant_id']),shipment_id=str(row['shipment_id']))
                        envelope=json.loads(self.decrypt_secret(row))
                        if envelope.get('platform_id')!=str(row['platform_connection_id']):
                            raise ValueError('Private account identity mismatch')
                        from types import SimpleNamespace
                        adapter=create_adapter(self.client,SimpleNamespace(base_url=row['api_base_url'],api_key=envelope['api_key']),environment=row['environment'])
                        await adapter.confirm_order_fulfillment(row['remote_object_id'],snapshot,label)
                        await connection.execute('''UPDATE public.partner_order_jobs SET fulfillment_state='CONFIRMED',updated_at=now()
                            WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3''',row['tenant_id'],row['shipment_id'],row['carrier_account_id'])
                    except Exception as exc:
                        logger.warning('Native fulfillment deferred shipment=%s type=%s',row['shipment_id'],type(exc).__name__)
                        await connection.execute('''UPDATE public.partner_order_jobs SET fulfillment_state='FAILED',last_error=$4,updated_at=now()
                            WHERE tenant_id=$1 AND shipment_id=$2 AND carrier_account_id=$3''',row['tenant_id'],row['shipment_id'],row['carrier_account_id'],type(exc).__name__)
                        try:
                            await self.automation.fail_ticket(row['tenant_id'],uuid5(NAMESPACE_URL,key),str(row['shipment_id']),row['shipment_id'],'NATIVE_ORDER_FULFILLMENT_DEFERRED')
                        except Exception:
                            logger.warning('Native fulfillment support ticket deferred')
                finally:
                    await connection.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))',key)

    async def receive_tracking(self, request):
        sources=request.query_params.getlist('source')
        try:
            if len(sources)!=1:
                raise ValueError()
            source_id=UUID(sources[0])
        except ValueError:
            raise HTTPException(401,'Tracking source is not configured') from None
        async with self.pool.acquire() as connection:
            source=await connection.fetchrow('''SELECT o.*,p.api_base_url,p.environment FROM public.partner_provider_options o
                JOIN public.platform_carrier_connections p ON p.id=o.platform_connection_id
                WHERE o.platform_connection_id=$1 AND o.webhook_enabled''',source_id)
        if source is None:
            raise HTTPException(401,'Tracking source is not configured')
        provider={EasyPostAdapter.endpoint:'EASYPOST',SendcloudAdapter.endpoint:'SENDCLOUD',ShippoAdapter.endpoint:'SHIPPO'}.get(source['api_base_url'])
        if request.headers.get('content-type','').split(';')[0].strip().lower()!='application/json':
            raise HTTPException(415,'Use application/json')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>262144:
                raise HTTPException(413,'Tracking webhook exceeds 256 KB')
        secret=self.decrypt_secret(source,'webhook_secret')
        verify_native_signature(request,raw,provider,source['webhook_auth'],secret)
        try:
            body=json.loads(raw,parse_float=Decimal)
            if not isinstance(body,dict):
                raise ValueError()
            if provider=='EASYPOST':
                parsed=parse_easypost_tracking(body,source['environment'],preserve_unknown=getattr(self.tracking,'workspace',None) is not None)
            elif provider=='SENDCLOUD':
                parsed=parse_sendcloud_tracking(body,decode_json(source['sendcloud_status_map']),preserve_unknown=getattr(self.tracking,'workspace',None) is not None)
            elif provider=='SHIPPO':
                parsed=parse_shippo_tracking(body,source['environment'],preserve_unknown=getattr(self.tracking,'workspace',None) is not None)
            else:
                raise ValueError()
        except (ValueError,KeyError,TypeError,AttributeError,OverflowError):
            raise HTTPException(422,'Invalid native tracking event') from None
        if parsed is None:
            return {'accepted':True,'ignored':True,'reason':'Non-dispatch or unmapped milestone'}
        event, remote_id, provider=parsed
        async with self.pool.acquire() as connection:
            rows=await connection.fetch('''SELECT s.tenant_id,s.carrier_account_id,s.upstream_shipment_id,
                s.logistics_metadata FROM public.shipments s JOIN public.carrier_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.carrier_account_id
                WHERE a.platform_connection_id=$1 AND (s.tracking_number=$2 OR s.logistics_metadata->'automation_label'->'package_labels' @> jsonb_build_array(jsonb_build_object('tracking_number',$2::text))) AND a.environment=$3 LIMIT 2''',source_id,event.tracking_number,source['environment'])
        if not rows:
            raise HTTPException(404,'Tracked shipment not found for this connection')
        if len(rows)!=1:
            raise HTTPException(409,'Tracking reference requires reconciliation')
        row=rows[0]
        if remote_id:
            expected=row['upstream_shipment_id'] if provider=='EASYPOST' else decode_json(row['logistics_metadata']).get('automation_label',{}).get('upstream_id')
            labels=decode_json(row['logistics_metadata']).get('automation_label',{}).get('package_labels',[])
            if any(piece.get('upstream_id')==str(remote_id) and piece.get('tracking_number')==event.tracking_number for piece in labels):expected=remote_id
            if str(remote_id)!=str(expected):
                raise HTTPException(409,'Native shipment reference does not match')
        key=TrackingKey(tenant_id=row['tenant_id'],carrier_account_id=row['carrier_account_id'],
            secret=SecretStr(secret),pod_allowed_hosts=decode_json(source['pod_allowed_hosts']))
        # Retain the pre-045 receipt digest contract for delayed native retries.
        canonical=json.dumps(event.model_dump(mode='json',include={'event_id','tracking_number','status','occurred_at','raw_error','proof_of_delivery_url'}),sort_keys=True,separators=(',',':')).encode()
        return await self.tracking.ingest('native:'+str(source_id),key,event,hashlib.sha256(canonical).hexdigest())


async def wake_exception_delivery(application):
    try:
        await application.state.tracking_support.stage_tickets()
        for attempt in range(10):
            if not await application.state.support_delivery.drain():
                break
    except (asyncpg.PostgresError, httpx.HTTPError, ValueError, TypeError):
        logging.getLogger(__name__).warning('Exception alert deferred; durable ticket and notification jobs retained')


def build_native_router(authenticate):
    from backend.admin_portal import authenticate_platform_owner
    router=APIRouter(tags=['Native partner orders and tracking'])

    @router.post('/api/v1/admin/platform-carriers/{connection_id}/native-orders/reconcile')
    async def reconcile_order(connection_id:UUID,body:NativeOrderReconciliation,request:Request,actor=Depends(authenticate_platform_owner)):
        service=request.app.state.native_partners
        async with service.pool.acquire() as connection:
            account_id=await connection.fetchval('''SELECT j.carrier_account_id FROM public.partner_order_jobs j
                JOIN public.carrier_accounts a ON a.tenant_id=j.tenant_id AND a.id=j.carrier_account_id
                WHERE j.tenant_id=$1 AND j.shipment_id=$2 AND a.platform_connection_id=$3''',body.tenant_id,body.shipment_id,connection_id)
        if account_id is None:
            raise HTTPException(404,'Native order job not found for this connection')
        return await service.sync_one(body.tenant_id,body.shipment_id,account_id,body.remote_object_id)

    @router.post('/api/v1/shipping/tracking-webhooks')
    async def tracking_webhooks(request:Request, background_tasks:BackgroundTasks):
        service=getattr(request.app.state,'native_partners',None)
        if service is None:
            raise HTTPException(503,'Tracking engine unavailable')
        try:
            engine = getattr(request.app.state, 'logistics_supervisor', None)
            result = (await engine.support.receive_tracking(request, service) if engine is not None
                      else await service.receive_tracking(request))
            if result.get('support_queued') and result.get('applied'):
                background_tasks.add_task(engine.support.stage if engine is not None else wake_exception_delivery, request.app)
            return result
        except asyncpg.PostgresError:
            raise HTTPException(503,'Tracking database unavailable; event not acknowledged') from None

    @router.put('/api/v1/admin/platform-carriers/{connection_id}/native-settings')
    async def configure(connection_id:UUID,body:NativeProviderSettings,request:Request,actor=Depends(authenticate_platform_owner)):
        settings=request.app.state.settings
        service=request.app.state.native_partners
        async with service.pool.acquire() as connection:
            async with connection.transaction():
                row=await connection.fetchrow('SELECT * FROM public.platform_carrier_connections WHERE id=$1 FOR UPDATE',connection_id)
                if row is None or row['api_base_url'] not in ADAPTERS:
                    raise HTTPException(404,'Native provider connection not found')
                if body.webhook_auth=='URL_TOKEN' and row['api_base_url']!=ShippoAdapter.endpoint:
                    raise HTTPException(422,'URL token authentication is supported only for Shippo')
                if body.order_sync_enabled and row['api_base_url']==SendcloudAdapter.endpoint and not body.sendcloud_integration_id:
                    raise HTTPException(422,'Sendcloud native orders require its integration ID')
                if body.webhook_enabled and row['api_base_url']==SendcloudAdapter.endpoint and not body.sendcloud_status_map:
                    raise HTTPException(422,'Configure verified Sendcloud numeric status mappings')
                previous=await connection.fetchrow('SELECT * FROM public.partner_provider_options WHERE platform_connection_id=$1 FOR UPDATE',connection_id)
                if body.webhook_secret:
                    key_id=sorted(settings.credential_keys)[0] if settings.credential_keys else None
                    if key_id is None:
                        raise HTTPException(503,'Server encryption unavailable')
                    cipher=Fernet(settings.credential_keys[key_id].get_secret_value().encode()).encrypt(body.webhook_secret.get_secret_value().encode())
                else:
                    key_id=previous['credential_key_id'] if previous else None
                    cipher=previous['webhook_secret'] if previous else None
                if body.webhook_enabled and cipher is None:
                    raise HTTPException(422,'Supply the native webhook secret')
                await connection.execute('''INSERT INTO public.partner_provider_options
                    (platform_connection_id,order_sync_enabled,sendcloud_integration_id,webhook_enabled,webhook_auth,
                     webhook_secret,credential_key_id,pod_allowed_hosts,sendcloud_status_map)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb) ON CONFLICT(platform_connection_id) DO UPDATE SET
                    order_sync_enabled=excluded.order_sync_enabled,sendcloud_integration_id=excluded.sendcloud_integration_id,
                    webhook_enabled=excluded.webhook_enabled,webhook_auth=excluded.webhook_auth,webhook_secret=excluded.webhook_secret,
                    credential_key_id=excluded.credential_key_id,pod_allowed_hosts=excluded.pod_allowed_hosts,
                    sendcloud_status_map=excluded.sendcloud_status_map,updated_at=now()''',connection_id,body.order_sync_enabled,
                    body.sendcloud_integration_id,body.webhook_enabled,body.webhook_auth,cipher,key_id,json.dumps(body.pod_allowed_hosts),json.dumps(body.sendcloud_status_map))
                audit=body.model_dump(mode='json',exclude={'webhook_secret'})
                await connection.execute("INSERT INTO public.platform_carrier_events(actor_auth_user_id,connection_id,action,snapshot) VALUES($1,$2,'SAVE',$3::jsonb)",actor.user_id,connection_id,json.dumps(audit))
        return {'configured':True,'webhook_path':'/api/v1/shipping/tracking-webhooks?source='+str(connection_id),
                'webhook_secret_configured':cipher is not None,'order_sync_enabled':body.order_sync_enabled}

    @router.get('/api/v1/admin/platform-carriers/{connection_id}/native-settings')
    async def read_configuration(connection_id:UUID,request:Request,actor=Depends(authenticate_platform_owner)):
        async with request.app.state.native_partners.pool.acquire() as connection:
            endpoint=await connection.fetchval('SELECT api_base_url FROM public.platform_carrier_connections WHERE id=$1',connection_id)
            if endpoint not in ADAPTERS:
                raise HTTPException(404,'Native provider connection not found')
            row=await connection.fetchrow('''SELECT order_sync_enabled,sendcloud_integration_id,webhook_enabled,webhook_auth,
                webhook_secret IS NOT NULL AS webhook_secret_configured,pod_allowed_hosts,sendcloud_status_map
                FROM public.partner_provider_options WHERE platform_connection_id=$1''',connection_id)
        result=dict(row) if row else NativeProviderSettings().model_dump(exclude={'webhook_secret'})
        for field in ('pod_allowed_hosts','sendcloud_status_map'):
            result[field]=decode_json(result[field])
        result['webhook_path']='/api/v1/shipping/tracking-webhooks?source='+str(connection_id)
        return result

    @router.post('/api/v1/shipping/native-orders/sync')
    async def synchronize(body:NativeOrderSelection,request:Request,context=Depends(authenticate)):
        authorize(context,body.tenant_id)
        service=request.app.state.native_partners
        async with service.pool.acquire() as connection:
            rows=await connection.fetch('''SELECT s.id,s.carrier_account_id,s.logistics_metadata,s.created_at,s.upstream_shipment_id
                FROM public.shipments s JOIN public.carrier_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.carrier_account_id
                JOIN public.partner_provider_options o ON o.platform_connection_id=a.platform_connection_id
                WHERE s.tenant_id=$1 AND s.id=ANY($2::uuid[]) AND o.order_sync_enabled AND a.is_active
                AND s.logistics_metadata ? 'automation_order' ''',context.tenant_id,body.shipment_ids)
            if len(rows)!=len(set(body.shipment_ids)):
                raise HTTPException(422,'Selection includes unavailable, unprepared or disabled native orders')
            for row in rows:
                metadata=decode_json(row['logistics_metadata'])
                payload={'order':metadata['automation_order'],'customs':metadata.get('automation_customs'),
                    'upstream_shipment_id':row['upstream_shipment_id'],'placed_at':row['created_at'].isoformat()}
                await connection.execute('''INSERT INTO public.partner_order_jobs(tenant_id,shipment_id,carrier_account_id,payload)
                    VALUES($1,$2,$3,$4::jsonb) ON CONFLICT(tenant_id,shipment_id,carrier_account_id) DO UPDATE SET
                    state='PENDING',payload=excluded.payload,last_error=NULL,updated_at=now()
                    WHERE public.partner_order_jobs.state='FAILED' AND public.partner_order_jobs.remote_object_id IS NULL''',context.tenant_id,row['id'],row['carrier_account_id'],json.dumps(payload))
        results=[]
        for row in rows:
            try:
                result=await service.sync_one(context.tenant_id,row['id'],row['carrier_account_id'])
            except HTTPException as exc:
                result={'state':'FAILED','http_status':exc.status_code,'detail':exc.detail}
            results.append({'shipment_id':str(row['id']),**result})
        return {'orders':results}

    @router.get('/api/v1/shipping/native-orders')
    async def native_order_statuses(request:Request,context=Depends(authenticate)):
        authorize(context,context.tenant_id)
        async with request.app.state.native_partners.pool.acquire() as connection:
            rows=await connection.fetch('''SELECT shipment_id,state,attempts,fulfillment_state,fulfillment_attempts,updated_at FROM public.partner_order_jobs
                WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT 200''',context.tenant_id)
        return {'orders':[dict(row) for row in rows]}

    return router


logger = logging.getLogger(__name__)


def decimal_json(value):
    """JSON numbers retain Decimal precision; never convert money to float."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('Nonfinite JSON number')
        return format(value, 'f')
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(str(key)) + ':' + decimal_json(item) for key, item in value.items()) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(decimal_json(item) for item in value) + ']'
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def order_total(snapshot):
    return sum((Decimal(str(item['unit_value'])) * item['quantity'] for item in snapshot.get('items', [])), Decimal('0'))


def native_order_key(snapshot):
    return 'easyinvio:' + str(snapshot['tenant_id']) + ':' + str(snapshot['shipment_id'])


def easypost_parcel(cargo):
    validate_native_cargo(cargo, 'EASYPOST')
    parcel = {'weight': str(Decimal(str(cargo['actual_weight_kg'])) * Decimal('35.27396195'))}
    if cargo.get('cargo_type') == 'LETTER':
        parcel['predefined_package'] = 'Letter'
    else:
        for source, target in [('length_cm','length'),('width_cm','width'),('height_cm','height')]:
            parcel[target] = str(Decimal(str(cargo[source])) / Decimal('2.54'))
    return parcel


def validate_native_cargo(cargo, provider):
    """Fail closed before network mutations; parcel schemas are not LTL schemas."""
    kind = cargo.get('cargo_type', 'PARCEL')
    if kind in {'PALLET', 'OVERLAND_FREIGHT'}:
        raise PurchaseRejected(provider + '_NATIVE_FREIGHT_CONTRACT_REQUIRED')
    if kind not in {'LETTER', 'PARCEL'}:
        raise PurchaseRejected('INVALID_CARGO_TYPE')
    weight = Decimal(str(cargo['actual_weight_kg']))
    if not weight.is_finite() or weight <= 0:
        raise PurchaseRejected('INVALID_CARGO_WEIGHT')
    if kind == 'LETTER':
        if weight >= Decimal('0.5'):
            raise PurchaseRejected('LETTER_WEIGHT_MUST_BE_BELOW_0_5_KG')
        if provider != 'EASYPOST':
            raise PurchaseRejected(provider + '_VERIFIED_LETTER_SERVICE_REQUIRED')
    else:
        for key in ('length_cm', 'width_cm', 'height_cm'):
            value = Decimal(str(cargo.get(key, '0')))
            if not value.is_finite() or value <= 0:
                raise PurchaseRejected('INVALID_CARGO_DIMENSIONS')


def easypost_tax_identifiers(document):
    result=[]
    for field,entity in [('sender','SENDER'),('recipient','RECEIVER')]:
        party=document.get(field,{})
        for name,kind in [('eori','EORI'),('vat_registration','VAT')]:
            if party.get(name):
                result.append({'entity':entity,'tax_id':party[name],'tax_id_type':kind,'issuing_country':party['country_code']})
    return result


def easypost_address(address):
    return {'name': address['name'], 'street1': address['line1'], 'street2': address.get('line2',''),
            'city': address['city'], 'state': address.get('state',''), 'zip': address['postal_code'],
            'country': address['country_code'], 'phone': address.get('phone',''), 'email': address.get('email','')}


def shippo_address(address):
    return easypost_address(address)


def identifier(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise PurchaseRejected('INVALID_REMOTE_ID')
    value = str(value)
    if not value or len(value) > 200:
        raise PurchaseRejected('INVALID_REMOTE_ID')
    return quote(value, safe='')


def secure_link(value):
    if not isinstance(value, str):
        raise PurchaseUncertain('DOCUMENT_NOT_READY')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise PurchaseUncertain('INVALID_DOCUMENT_LINK')
    return value


def carrier_qr_fields(value):
    """Optional carrier media never invalidates an otherwise confirmed label."""
    if isinstance(value,bytes):
        if len(value)>5_000_000:return {}
        import base64
        return {'return_dropoff_qr_code_base64':base64.b64encode(value).decode('ascii')}
    if not isinstance(value,str) or len(value)>7_000_000:return {}
    if value.lstrip().startswith(('<svg','<?xml')):return {'return_dropoff_qr_code_svg':value}
    if value.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/svg+xml;base64,')):
        return {'return_dropoff_qr_code_base64':value}
    if value.startswith(('iVBORw0KGgo','/9j/','PHN2Zy','PD94bWwg')):
        return {'return_dropoff_qr_code_base64':value}
    try:return {'return_dropoff_qr_code_url':secure_link(value)}
    except PurchaseUncertain:return {}


def declaration(data):
    document = data.get('customs_document') or data.get('customs') or {}
    if not document.get('required'):
        return None
    if not document.get('ready_for_provider') or not document.get('signer') or not document.get('items'):
        raise PurchaseRejected('CUSTOMS_REVIEW_REQUIRED')
    for item in document['items']:
        code = item.get('hs_code', '')
        if not isinstance(code, str) or not code.isdigit() or len(code) not in {6, 8, 10}:
            raise PurchaseRejected('CUSTOMS_CLASSIFICATION_REQUIRED')
        for key in ('unit_value', 'unit_weight_kg'):
            amount = Decimal(str(item[key]))
            if not amount.is_finite() or amount <= 0:
                raise PurchaseRejected('INVALID_CUSTOMS_VALUE')
        if type(item['quantity']) is not int or item['quantity'] < 1:
            raise PurchaseRejected('INVALID_CUSTOMS_QUANTITY')
    return document


def return_snapshot(original):
    """Only a fresh, server-authorized return quote may purchase a return label."""
    if not original.get('return_quote_authorized') or not original.get('return_rate_id'):
        raise PurchaseRejected('FRESH_RETURN_QUOTE_REQUIRED')
    result = copy.deepcopy(original)
    result['upstream_rate_id'] = result.pop('return_rate_id')
    result['origin'], result['destination'] = original['destination'], original['origin']
    result['is_return'] = True
    return result


class BaseAggregatorAdapter:
    endpoint: str

    def __init__(self, client: httpx.AsyncClient, credentials: str, *, environment: str):
        if environment not in {'TEST', 'LIVE'}:
            raise ValueError('Explicit TEST or LIVE environment required')
        self.client, self.credentials, self.environment = client, credentials, environment
        self.last_remote_id = None
        self.pending_void_id = None
        self.last_order_id = None
        self.last_order_kind = None
        self.last_http_status = None
        self.last_retry_after_seconds = None

    def authentication(self):
        return {}

    async def request(self, method, path, body=None):
        if method.upper() not in {'GET', 'HEAD'}:
            from backend.integration_policy import require_integration
            require_integration(self.endpoint)
        # Bound reads before parsing, never follow redirects with credentials.
        try:
            authentication = self.authentication()
            headers = {**authentication.pop('headers', {}), 'Content-Type': 'application/json'}
            async with self.client.stream(method, self.endpoint + path,
                                          content=decimal_json(body) if body is not None else None, headers=headers,
                                          timeout=30, follow_redirects=False,
                                          **authentication) as response:
                self.last_http_status = response.status_code
                self.last_retry_after_seconds = None
                if response.status_code == 429:
                    retry = response.headers.get('retry-after','')
                    if retry.isdigit():self.last_retry_after_seconds = min(int(retry),86400)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise PurchaseUncertain('RESPONSE_LIMIT')
                if response.status_code in {400, 401, 403, 404, 422}:
                    raise PurchaseRejected(type(self).__name__ + ':HTTP_' + str(response.status_code))
                if not 200 <= response.status_code < 300:
                    raise PurchaseUncertain('REMOTE_OUTCOME_UNKNOWN')
                if response.status_code == 204:
                    return {}
                try:
                    result = json.loads(raw, parse_float=Decimal)
                except ValueError:
                    raise PurchaseUncertain('INVALID_REMOTE_RESPONSE') from None
                if not isinstance(result, dict):
                    raise PurchaseUncertain('INVALID_REMOTE_RESPONSE')
                return result
        except httpx.HTTPError:
            raise PurchaseUncertain('REMOTE_OUTCOME_UNKNOWN') from None



class EasyPostAdapter(BaseAggregatorAdapter):
    endpoint = 'https://api.easypost.com/v2'

    def authentication(self):
        return {'auth': httpx.BasicAuth(self.credentials, '')}

    async def quote(self, request, account, rate_model):
        import sys
        core = sys.modules[rate_model.__module__]
        return await core.EasyPostStrategy(self.client, account).rates(request)

    async def sync_order(self, snapshot):
        packages = snapshot.get('packages') or [snapshot['cargo']]
        for cargo in packages:
            validate_native_cargo(cargo, 'EASYPOST')
        prepared = await self.inject_customs(snapshot)
        if len(packages) == 1 and snapshot.get('upstream_shipment_id'):
            # EasyPost Orders are multi-package shipping objects, not sales orders.
            self.last_order_id = snapshot['upstream_shipment_id']
            self.last_order_kind = 'Shipment'
            body = await self.request('GET', '/shipments/' + identifier(snapshot['upstream_shipment_id']))
            if body.get('id')!=snapshot['upstream_shipment_id']:
                raise PurchaseUncertain('EASYPOST_ORDER_SHIPMENT_IDENTITY_MISMATCH')
            kind = 'Shipment'
        elif len(packages)>1 and str(snapshot.get('upstream_shipment_id','')).startswith('order_'):
            body=await self.request('GET','/orders/'+identifier(snapshot['upstream_shipment_id']))
            kind='Order'
        elif len(packages) == 1:
            shipment = {'reference': native_order_key(snapshot), 'from_address': easypost_address(snapshot['origin']),
                        'to_address': easypost_address(snapshot['destination']), 'parcel': easypost_parcel(packages[0]),
                        'options': {'label_format': 'PDF'}}
            if prepared.get('customs_info'):
                shipment['customs_info'] = prepared['customs_info']
                shipment['tax_identifiers'] = prepared.get('tax_identifiers', [])
            body = await self.request('POST', '/shipments', {'shipment': shipment})
            kind = 'Shipment'
        else:
            if len(packages) > 100:
                raise PurchaseRejected('EASYPOST_ORDER_PACKAGE_LIMIT')
            shipments = []
            for cargo in packages:
                shipment = {'parcel': easypost_parcel(cargo), 'options': {'label_format': 'PDF'}}
                if prepared.get('customs_info'):
                    shipment['customs_info'] = prepared['customs_info']
                    shipment['tax_identifiers'] = prepared.get('tax_identifiers', [])
                shipments.append(shipment)
            body = await self.request('POST', '/orders', {'order': {
                'reference': native_order_key(snapshot), 'from_address': easypost_address(snapshot['origin']),
                'to_address': easypost_address(snapshot['destination']), 'shipments': shipments}})
            kind = 'Order'
        if body.get('mode') != ('test' if self.environment == 'TEST' else 'production') or not body.get('id'):
            raise PurchaseUncertain('EASYPOST_ORDER_CONFIRMATION_INVALID')
        self.last_order_id, self.last_order_kind = body['id'], kind
        return {'remote_id': body['id'], 'object_type': kind}

    async def confirm_order_fulfillment(self, remote_id, snapshot, label):
        if label.get('package_labels'):
            body=await self.request('GET','/orders/'+identifier(label['upstream_id']))
            if body.get('mode')!=('test' if self.environment=='TEST' else 'production') or {piece.get('tracking_code') for piece in body.get('shipments',[])}!={piece['tracking_number'] for piece in label['package_labels']}:
                raise PurchaseUncertain('EASYPOST_FULFILLMENT_NOT_CONFIRMED')
            return True
        body = await self.request('GET', '/shipments/' + identifier(label['upstream_id']))
        if body.get('mode')!=('test' if self.environment=='TEST' else 'production') or body.get('tracking_code')!=label['tracking_number'] or not body.get('postage_label'):
            raise PurchaseUncertain('EASYPOST_FULFILLMENT_NOT_CONFIRMED')
        return True

    async def retrieve_order(self, remote_id, snapshot):
        kind = 'Shipment' if str(remote_id).startswith('shp_') else 'Order'
        path = '/shipments/' if kind=='Shipment' else '/orders/'
        body = await self.request('GET', path + identifier(remote_id))
        reference_matches = body.get('reference')==native_order_key(snapshot) or str(remote_id)==str(snapshot.get('upstream_shipment_id'))
        if not reference_matches or body.get('id')!=remote_id or body.get('mode')!=('test' if self.environment=='TEST' else 'production'):
            raise PurchaseRejected('EASYPOST_ORDER_IDENTITY_MISMATCH')
        return {'remote_id':body['id'],'object_type':kind}

    def normalize(self, body, snapshot):
        if body.get('mode') != ('test' if self.environment == 'TEST' else 'production'):
            raise PurchaseUncertain('REMOTE_MODE_MISMATCH')
        if (body.get('id') != snapshot['upstream_shipment_id'] or
                body.get('selected_rate', {}).get('id') != snapshot['upstream_rate_id']):
            raise PurchaseUncertain('REMOTE_RATE_MISMATCH')
        label = body.get('postage_label') or {}
        tracking = body.get('tracking_code')
        if not isinstance(tracking, str) or not tracking.strip():
            raise PurchaseUncertain('TRACKING_NOT_READY')
        qr = next((f.get('form_url') for f in body.get('forms', [])
                   if f.get('form_type') == 'label_qr_code'), None)
        return {'upstream_id': body['id'], 'tracking_number': tracking,
                'tracking_url': (body.get('tracker') or {}).get('public_url'),
                'label_url': secure_link(label.get('label_pdf_url') or label.get('label_url')),
                **(carrier_qr_fields(qr) if qr else {}),
                'carrier_forms': [{'document_type': f.get('form_type', 'CUSTOMS_FORM'),
                                   'url': secure_link(f['form_url'])} for f in body.get('forms', []) if f.get('form_type') != 'label_qr_code']}

    def normalize_order(self,body,snapshot):
        from backend.multi_label import bundle_labels
        pieces=body.get('shipments') or []
        expected=snapshot.get('package_shipment_ids',[])
        if body.get('mode')!=('test' if self.environment=='TEST' else 'production') or body.get('id')!=snapshot['upstream_shipment_id']:
            raise PurchaseUncertain('REMOTE_ORDER_IDENTITY_MISMATCH')
        if len(pieces)!=len(snapshot.get('packages') or expected) or len(pieces)<2 or set(expected)!={piece.get('id') for piece in pieces}:
            raise PurchaseUncertain('PACKAGE_LABELS_INCOMPLETE')
        labels=[]
        for remote_id in expected:
            piece=next(value for value in pieces if value.get('id')==remote_id)
            selected=piece.get('selected_rate') or {}
            if str(selected.get('carrier','')).upper()!=snapshot['carrier_code'].upper() or str(selected.get('service','')).upper()!=snapshot['service_code'].upper():
                raise PurchaseUncertain('REMOTE_ORDER_SERVICE_MISMATCH')
            labels.append(self.normalize(piece,{**snapshot,'upstream_shipment_id':remote_id,'upstream_rate_id':selected['id']}))
        return bundle_labels(labels,body['id'])

    async def purchase_label(self, rate_snapshot):
        if rate_snapshot.get('cargo'):
            validate_native_cargo(rate_snapshot['cargo'], 'EASYPOST')
        shipment_id = identifier(rate_snapshot['upstream_shipment_id'])
        if rate_snapshot.get('easypost_order'):
            remote=await self.request('GET','/orders/'+shipment_id)
            if remote.get('mode')!=('test' if self.environment=='TEST' else 'production'):raise PurchaseRejected('REMOTE_MODE_MISMATCH')
            pieces=remote.get('shipments') or []
            if any(piece.get('postage_label') for piece in pieces):return self.normalize_order(remote,rate_snapshot)
            selected=next((rate for rate in remote.get('rates',[]) if rate.get('id')==rate_snapshot['upstream_rate_id']),None)
            if not selected:raise PurchaseRejected('RATE_NO_LONGER_AVAILABLE')
            self.last_remote_id=shipment_id
            body=await self.request('POST','/orders/'+shipment_id+'/buy',{'carrier':selected['carrier'],'service':selected['service']})
            return self.normalize_order(body,rate_snapshot)
        # Confirm the key's actual remote mode before any charge-producing call.
        remote = await self.request('GET', '/shipments/' + shipment_id)
        if remote.get('mode') != ('test' if self.environment == 'TEST' else 'production'):
            raise PurchaseRejected('REMOTE_MODE_MISMATCH')
        if remote.get('postage_label'):
            return self.normalize(remote, rate_snapshot)
        if not any(r.get('id') == rate_snapshot['upstream_rate_id'] for r in remote.get('rates', [])):
            raise PurchaseRejected('RATE_NO_LONGER_AVAILABLE')
        body = await self.request('POST', '/shipments/' + shipment_id + '/buy',
                                  {'rate': {'id': rate_snapshot['upstream_rate_id']}})
        self.last_remote_id = body.get('id')
        return self.normalize(body, rate_snapshot)

    async def inject_customs(self, parcel_data):
        result = copy.deepcopy(parcel_data)
        document = declaration(result)
        if document:
            result['tax_identifiers'] = easypost_tax_identifiers(document)
            if document['currency'] != 'USD':
                raise PurchaseRejected('CUSTOMS_USD_VALUES_REQUIRED')
            result['customs_info'] = {'customs_certify': True, 'customs_signer': document['signer'],
                'contents_type': {'SALE':'merchandise','GIFT':'gift','SAMPLE':'sample','RETURN':'returned_goods','OTHER':'other'}.get(document.get('category'),'merchandise'),
                'contents_explanation':document.get('category_other') or '', 'restriction_type': 'none',
                'customs_items': [{'description': i['description'], 'quantity': i['quantity'],
                    'value': str(Decimal(str(i['unit_value'])) * i['quantity']),
                    'weight': str(Decimal(str(i['unit_weight_kg'])) * i['quantity'] * Decimal('35.27396195')),
                    'hs_tariff_number': i['hs_code'], 'origin_country': i['origin_country']}
                    for i in document['items']]}
        return result

    async def retrieve_label(self, upstream_shipment_id, rate_snapshot):
        rate_snapshot={**rate_snapshot,**rate_snapshot.get('execution_details',{})}
        if rate_snapshot.get('easypost_order'):
            return self.normalize_order(await self.request('GET','/orders/'+identifier(upstream_shipment_id)),rate_snapshot)
        return self.normalize(await self.request('GET', '/shipments/' + identifier(upstream_shipment_id)), rate_snapshot)

    async def void_label(self, upstream_shipment_id):
        body = await self.request('POST', '/shipments/' + identifier(upstream_shipment_id) + '/refund', {})
        return body.get('refund_status') == 'refunded'

    async def void_confirmed(self, upstream_shipment_id):
        body = await self.request('GET', '/shipments/' + identifier(upstream_shipment_id))
        return body.get('refund_status') == 'refunded'

    async def generate_return_label(self, original_shipment_snapshot):
        snapshot = return_snapshot(original_shipment_snapshot)
        # Return shipment and rate IDs must already have been quoted natively.
        snapshot['upstream_shipment_id'] = snapshot['return_shipment_id']
        return await self.purchase_label(snapshot)


class ShippoAdapter(BaseAggregatorAdapter):
    endpoint = 'https://api.goshippo.com'

    def authentication(self):
        if self.environment == 'TEST' and not self.credentials.startswith('shippo_test_'):
            raise PurchaseRejected('TEST_TOKEN_REQUIRED')
        if self.environment == 'LIVE' and not self.credentials.startswith('shippo_live_'):
            raise PurchaseRejected('LIVE_TOKEN_REQUIRED')
        return {'headers': {'Authorization': 'ShippoToken ' + self.credentials,
                            'SHIPPO-API-VERSION': '2018-02-08'}}

    async def quote(self, request, account, rate_model):
        return await ShippoRateStrategy(self.client, account, rate_model, self.environment).rates(request)

    async def sync_order(self, snapshot):
        validate_native_cargo(snapshot['cargo'], 'SHIPPO')
        line_items = []
        for item in snapshot.get('items', []):
            line_items.append({'title': item['description'], 'quantity': item['quantity'],
                'total_price': format(Decimal(str(item['unit_value'])) * item['quantity'], '.2f'),
                'currency': snapshot['currency'], 'weight': str(item['unit_weight_kg']), 'weight_unit': 'kg',
                'sku': item.get('sku',''), 'manufacture_country': item['origin_country']})
        payload = {'to_address': shippo_address(snapshot['destination']),
            'from_address': shippo_address(snapshot['origin']), 'placed_at': snapshot['placed_at'],
            'order_number': native_order_key(snapshot), 'order_status': 'UNKNOWN', 'line_items': line_items,
            'notes': 'EasyInvio local reference: ' + snapshot['order_reference'],
            'currency': snapshot['currency'], 'total_price': format(order_total(snapshot), '.2f'),
            'weight': str(snapshot['cargo']['actual_weight_kg']), 'weight_unit': 'kg'}
        body = await self.request('POST', '/orders/', payload)
        if not body.get('object_id') or body.get('order_number') != payload['order_number']:
            raise PurchaseUncertain('SHIPPO_ORDER_CONFIRMATION_INVALID')
        self.last_order_id, self.last_order_kind = body['object_id'], 'Order'
        return {'remote_id': body['object_id'], 'object_type': 'Order'}

    async def confirm_order_fulfillment(self, remote_id, snapshot, label):
        body = await self.request('GET', '/orders/' + identifier(remote_id) + '/')
        transactions = [value.get('object_id') if isinstance(value,dict) else value for value in body.get('transactions',[])]
        if body.get('order_number')!=native_order_key(snapshot) or body.get('order_status')!='SHIPPED' or label['upstream_id'] not in transactions:
            raise PurchaseUncertain('SHIPPO_ORDER_FULFILLMENT_NOT_CONFIRMED')
        return True

    async def retrieve_order(self, remote_id, snapshot):
        body = await self.request('GET', '/orders/' + identifier(remote_id) + '/')
        if body.get('object_id')!=remote_id or body.get('order_number')!=native_order_key(snapshot):
            raise PurchaseRejected('SHIPPO_ORDER_IDENTITY_MISMATCH')
        return {'remote_id':body['object_id'],'object_type':'Order'}

    def normalize(self, body, snapshot):
        if body.get('status') != 'SUCCESS' or body.get('test') is not (self.environment == 'TEST'):
            raise PurchaseUncertain('TRANSACTION_NOT_CONFIRMED')
        rate = body.get('rate')
        rate_id = rate.get('object_id') if isinstance(rate, dict) else rate
        if rate_id != snapshot['upstream_rate_id']:
            raise PurchaseUncertain('REMOTE_RATE_MISMATCH')
        if not body.get('tracking_number'):
            raise PurchaseUncertain('TRACKING_NOT_READY')
        forms = []
        if body.get('commercial_invoice_url'):
            forms.append({'document_type': 'COMMERCIAL_INVOICE', 'url': secure_link(body['commercial_invoice_url'])})
        return {'upstream_id': body['object_id'], 'tracking_number': body['tracking_number'],
                'tracking_url': body.get('tracking_url_provider'), 'label_url': secure_link(body.get('label_url')),
                'carrier_forms': forms}

    async def purchase_label(self, rate_snapshot):
        if rate_snapshot.get('cargo'):
            validate_native_cargo(rate_snapshot['cargo'], 'SHIPPO')
        if rate_snapshot.get('package_count',1)>1:
            self.last_remote_id=rate_snapshot.get('upstream_shipment_id')
        body = await self.request('POST', '/transactions/',
            {'rate': rate_snapshot['upstream_rate_id'], 'label_file_type': 'PDF', 'async': False,
             **({'order': rate_snapshot['native_order_id']} if rate_snapshot.get('native_order_id') else {})})
        self.last_remote_id = body.get('object_id') or (rate_snapshot['upstream_shipment_id'] if rate_snapshot.get('package_count',1)>1 else None)
        if body.get('status') == 'ERROR':
            if rate_snapshot.get('package_count',1)>1:
                raise PurchaseUncertain('MULTIPIECE_PURCHASE_RECONCILIATION_REQUIRED')
            messages = body.get('messages') or []
            if any(isinstance(message, dict)
                   and message.get('code') == 'carrier_request_failed'
                   and 'carrier is unavailable' in str(message.get('text', '')).lower()
                   for message in messages):
                raise PurchaseRejected('SHIPPO_CARRIER_UNAVAILABLE')
            raise PurchaseRejected('LABEL_REJECTED')
        if rate_snapshot.get('package_count',1)>1:return await self.retrieve_package_labels(rate_snapshot)
        return self.normalize(body, rate_snapshot)

    async def retrieve_package_labels(self,snapshot):
        from backend.multi_label import bundle_labels
        body=await self.request('GET','/transactions/?results=100&rate='+identifier(snapshot['upstream_rate_id']))
        pieces=body.get('results') or []
        if body.get('next') or len(pieces)!=snapshot['package_count']:raise PurchaseUncertain('PACKAGE_LABELS_INCOMPLETE')
        labels=[self.normalize(piece,snapshot) for piece in pieces]
        return bundle_labels(labels,self.last_remote_id or labels[0]['upstream_id'])

    async def retrieve_label(self, upstream_shipment_id, rate_snapshot):
        rate_snapshot={**rate_snapshot,**rate_snapshot.get('execution_details',{})}
        if rate_snapshot.get('package_count',1)>1:
            self.last_remote_id=upstream_shipment_id
            return await self.retrieve_package_labels(rate_snapshot)
        return self.normalize(await self.request('GET', '/transactions/' + identifier(upstream_shipment_id) + '/'), rate_snapshot)

    async def inject_customs(self, parcel_data):
        result = copy.deepcopy(parcel_data)
        document = declaration(result)
        if document:
            items = []
            for i in document['items']:
                item = await self.request('POST', '/customs/items/', {'description': i['description'],
                    'quantity': i['quantity'], 'net_weight': str(Decimal(str(i['unit_weight_kg'])) * i['quantity']),
                    'mass_unit': 'kg', 'value_amount': str(Decimal(str(i['unit_value'])) * i['quantity']),
                    'value_currency': document['currency'], 'origin_country': i['origin_country'],
                    'tariff_number': i['hs_code']})
                items.append(item['object_id'])
            customs_payload = {'contents_type': 'RETURN_MERCHANDISE' if result.get('is_return') else {'SALE':'MERCHANDISE','GIFT':'GIFT','SAMPLE':'SAMPLE','RETURN':'RETURN_MERCHANDISE','OTHER':'OTHER'}.get(document.get('category'),'MERCHANDISE'),
                'contents_explanation':document.get('category_other') or '',
                'non_delivery_option': 'RETURN', 'certify': True, 'certify_signer': document['signer'], 'items': items,
                'invoice': document.get('invoice_number',document.get('shipment_id'))}
            if document.get('incoterm')=='EXW':
                raise PurchaseRejected('SHIPPO_CUSTOMS_INCOTERM_NOT_SUPPORTED')
            customs_payload['incoterm'] = 'DDU' if document.get('incoterm','DAP')=='DAP' else document['incoterm']
            if document.get('sender',{}).get('eori'):
                customs_payload['exporter_identification'] = {'eori_number':document['sender']['eori']}
            customs = await self.request('POST', '/customs/declarations/', customs_payload)
            result['customs_declaration'] = customs['object_id']
        return result

    async def void_label(self, upstream_shipment_id):
        body = await self.request('POST', '/refunds/', {'transaction': upstream_shipment_id, 'async': False})
        self.pending_void_id = body.get('object_id')
        return body.get('status') == 'SUCCESS'

    async def void_confirmed(self, upstream_shipment_id):
        body = await self.request('GET', '/transactions/' + identifier(upstream_shipment_id) + '/')
        return body.get('status') == 'REFUNDED'

    async def generate_return_label(self, original_shipment_snapshot):
        snapshot = return_snapshot(original_shipment_snapshot)
        # Shippo's USPS/UPS/FedEx return shipment creation automatically reverses
        # addresses. The newly authorized native rate encodes that direction;
        # do not create another shipment or reverse it a second time here.
        return await self.purchase_label(snapshot)


class ShippoRateStrategy:
    """Native Shippo shipment/rate discovery, feeding existing consolidation."""
    def __init__(self, client, account, rate_model, environment):
        self.account, self.rate_model = account, rate_model
        self.adapter = ShippoAdapter(client, account.api_key, environment=environment)

    async def rates(self, request):
        if request.cargo_type != 'PARCEL':
            raise ValueError('A verified freight or document service contract is required')
        mapping = {'name': 'name', 'company': 'company', 'line1': 'street1', 'line2': 'street2',
                   'city': 'city', 'state': 'state', 'postal_code': 'zip', 'country_code': 'country',
                   'phone': 'phone', 'email': 'email'}
        def address(value):
            data = value.model_dump(mode='json')
            return {target: data[source] for source, target in mapping.items() if data.get(source)}
        payload = {'address_from':address(request.origin),'address_to':address(request.destination),
            'parcels':[{'length':str(box.length_cm),'width':str(box.width_cm),'height':str(box.height_cm),
                'distance_unit':'cm','weight':str(weight),'mass_unit':'kg'} for box,weight in zip(request.dimensions,request.weights_kg,strict=True)],'async':False}
        if len(request.weights_kg)>40:raise PurchaseRejected('SHIPPO_MULTIPIECE_LIMIT_40')
        if request.customs_document:
            mapped = await self.adapter.inject_customs({'customs_document': request.customs_document})
            if mapped.get('customs_declaration'):
                payload['customs_declaration'] = mapped['customs_declaration']
        if self.account.upstream_account_id:
            payload['carrier_accounts'] = [self.account.upstream_account_id]
        if request.is_return:
            payload['address_from'] = address(request.destination)
            payload['address_to'] = address(request.origin)
            payload['extra'] = {'is_return': True}
        body = await self.adapter.request('POST', '/shipments/', payload)
        if body.get('test') is not (self.adapter.environment == 'TEST'):
            raise ValueError('Native quote environment does not match the connection')
        results = []
        if not body.get('rates'):raise PurchaseRejected('NO_SERVICES_FOR_ROUTE_OR_ACCOUNT')
        available_currencies = set()
        for rate in body.get('rates', []):
            if request.is_return and str(rate.get('provider', '')).upper() not in {'USPS', 'UPS', 'FEDEX'}:
                continue
            if rate.get('currency') != request.currency:
                available_currencies.add(rate.get('currency'))
                continue
            if len(request.weights_kg)>1 and (str(rate.get('provider','')).upper() not in {'UPS','FEDEX'} or (str(rate.get('provider','')).upper()=='FEDEX' and len(request.weights_kg)>12)):continue
            service = rate.get('servicelevel') or {}
            results.append(self.rate_model(provider='REGIONAL', account_id=self.account.id,
                upstream_shipment_id=body['object_id'], upstream_rate_id=rate['object_id'],
                carrier_code=rate['provider'], service_code=service['token'], currency=rate['currency'],
                wholesale_cost=str(rate['amount']), delivery_days=rate.get('estimated_days'),
                execution_details={'package_count':len(request.weights_kg)}))
        if not results and available_currencies:
            from backend.rate_diagnostics import RateCurrencyUnavailable
            raise RateCurrencyUnavailable(available_currencies)
        return results


def sendcloud_address(address):
    mapping = {'name': 'name', 'company': 'company_name', 'line1': 'address_line_1',
               'line2': 'address_line_2', 'city': 'city', 'postal_code': 'postal_code',
               'country_code': 'country_code', 'phone': 'phone_number', 'email': 'email'}
    result = {target: address[source] for source, target in mapping.items() if address.get(source)}
    if address.get('state'):
        state = address['state']
        result['state_province_code'] = state if '-' in state else address['country_code'] + '-' + state
    return result


class SendcloudAdapter(BaseAggregatorAdapter):
    endpoint = 'https://panel.sendcloud.sc/api/v3'

    def authentication(self):
        credentials = json.loads(self.credentials)
        return {'auth': httpx.BasicAuth(credentials['public_key'], credentials['secret_key'])}

    async def quote(self, request, account, rate_model):
        from backend.sendcloud_adapter import quote_sendcloud_v3
        return [rate_model.model_validate(row) for row in await quote_sendcloud_v3(self.client, account, request)]

    def purchase_allowed(self):
        # Ordinary Sendcloud accounts do not have EasyPost-style test keys.
        if self.environment != 'LIVE':
            raise PurchaseRejected('NO_VERIFIED_TEST_LABEL_CONTRACT')

    async def inject_customs(self, parcel_data):
        result = copy.deepcopy(parcel_data)
        document = declaration(result)
        if document:
            category=document.get('category','SALE')
            if category=='OTHER':
                raise PurchaseRejected('SENDCLOUD_EXPORT_CATEGORY_NOT_SUPPORTED')
            result['customs_information'] = {'invoice_number': document.get('invoice_number') or document['shipment_id'],
                'export_reason': 'returned_goods' if result.get('is_return') else {'SALE':'commercial_goods','GIFT':'gift','SAMPLE':'commercial_sample','RETURN':'returned_goods'}.get(category,'commercial_goods'),
                'incoterm': document['incoterm']}
            taxes = {}
            for source, target in (('sender', 'sender'), ('recipient', 'receiver')):
                party = document[source]
                taxes[target] = [{'name': name, 'country_code': party['country_code'], 'value': party[field]}
                    for field, name in (('eori', 'EORI'), ('vat_registration', 'VAT')) if party.get(field)]
            taxes['importer_of_record'] = []
            result['customs_information']['tax_numbers'] = taxes
            if result.get('is_return') and document.get('return_data'):
                result['customs_information']['return_data'] = document['return_data']
            result['parcel_items'] = [{'description': i['description'], 'quantity': i['quantity'],
                'hs_code': i['hs_code'], 'origin_country': i['origin_country'], 'package_index':i.get('package_index'),
                'weight': {'value': str(i['unit_weight_kg']), 'unit': 'kg'},
                'price': {'value': str(i['unit_value']), 'currency': document['currency']}}
                for i in document['items']]
        return result

    def payload(self, snapshot):
        parcels=[]
        for index,cargo in enumerate(snapshot.get('packages') or [snapshot['cargo']],1):
            validate_native_cargo(cargo,'SENDCLOUD')
            parcel={'weight':{'value':str(cargo['actual_weight_kg']),'unit':'kg'},
                'dimensions':{**{key:str(cargo[key+'_cm']) for key in ('length','width','height')},'unit':'cm'}}
            if snapshot.get('parcel_items'):
                parcel['parcel_items']=[{key:value for key,value in item.items() if key!='package_index'} for item in snapshot['parcel_items'] if len(snapshot.get('packages') or [])<2 or item.get('package_index')==index]
                if not parcel['parcel_items']:raise PurchaseRejected('MULTIPIECE_CUSTOMS_ALLOCATION_REQUIRED')
            parcels.append(parcel)
        properties = {'shipping_option_code': snapshot['upstream_rate_id']}
        if snapshot.get('contract_id'):
            properties['contract_id'] = snapshot['contract_id']
        result = {'from_address': sendcloud_address(snapshot['origin']),
            'to_address': sendcloud_address(snapshot['destination']), 'order_number': snapshot['order_reference'],
            'ship_with': {'type': 'shipping_option_code', 'properties': properties}, 'parcels': parcels,
            'label_details': {'mime_type': 'application/pdf', 'dpi': 72}}
        if snapshot.get('customs_information'):
            result['customs_information'] = snapshot['customs_information']
            result['total_order_price'] = {'value': snapshot['customs_document']['totals']['goods_value'],
                                           'currency': snapshot['customs_document']['currency']}
        return result

    def normalize(self,body,expected_count=1):
        from backend.multi_label import bundle_labels
        data=body.get('data',body);parcels=data.get('parcels') or []
        self.last_remote_id=str(data['id']) if data.get('id') is not None else None
        if len(parcels)!=expected_count:raise PurchaseUncertain('PACKAGE_LABELS_INCOMPLETE')
        if expected_count==1:return self.normalize_single(body)
        labels=[]
        for parcel in parcels:
            label=self.normalize_single({'data':{**data,'parcels':[parcel]}})
            label['upstream_id']=str(parcel.get('id') or '')
            labels.append(label)
        return bundle_labels(labels,self.last_remote_id)

    def normalize_single(self, body):
        data = body.get('data', body)
        self.last_remote_id = str(data['id']) if data.get('id') is not None else None
        parcels = data.get('parcels') or []
        if data.get('errors') or len(parcels) != 1:
            raise PurchaseUncertain('ANNOUNCEMENT_NOT_CONFIRMED')
        parcel = parcels[0]
        state = (parcel.get('status') or {}).get('code')
        if state in {'ANNOUNCING', 'ANNOUNCEMENT_FAILED', 'CANCELLED', 'CANCELLATION_REQUEST'}:
            raise PurchaseUncertain('ANNOUNCEMENT_NOT_CONFIRMED')
        documents = parcel.get('documents') or []
        labels = [d for d in documents if d.get('document_type', d.get('type')) == 'label']
        if not labels or not parcel.get('tracking_number'):
            raise PurchaseUncertain('DOCUMENT_NOT_READY')
        return {'upstream_id': self.last_remote_id, 'tracking_number': parcel['tracking_number'],
            'tracking_url': parcel.get('tracking_url'), 'label_url': secure_link(labels[0].get('link')),
            'carrier_forms': [{'document_type': d.get('document_type', d.get('type', 'CUSTOMS_FORM')),
                              'url': secure_link(d.get('link'))}
                              for d in documents if d.get('document_type', d.get('type')) != 'label']}

    async def sync_order(self, snapshot):
        validate_native_cargo(snapshot['cargo'], 'SENDCLOUD')
        integration_id = snapshot.get('sendcloud_integration_id')
        if type(integration_id) is not int or integration_id < 1:
            raise PurchaseRejected('SENDCLOUD_INTEGRATION_ID_REQUIRED')
        prepared = await self.inject_customs(snapshot)
        items = []
        for position, item in enumerate(snapshot.get('items', []), 1):
            items.append({'item_id': str(position), 'name': item['description'], 'quantity': item['quantity'],
                'hs_code': item.get('hs_code'), 'country_of_origin': item['origin_country'],
                'unit_price': {'value': Decimal(str(item['unit_value'])), 'currency': snapshot['currency']},
                'total_price': {'value': Decimal(str(item['unit_value'])) * item['quantity'], 'currency': snapshot['currency']},
                'measurement': {'weight': {'value': Decimal(str(item['unit_weight_kg'])), 'unit': 'kg'}}})
        address = snapshot['destination']
        payload = {'order_id': native_order_key(snapshot), 'order_number': snapshot['order_reference'],
            'order_details': {'integration': {'id': integration_id}, 'status': {'code': 'open'},
                'order_created_at': snapshot['placed_at'], 'order_items': items},
            'payment_details': {'status': {'code': 'unknown'},
                'total_price': {'value': order_total(snapshot), 'currency': snapshot['currency']}},
            'shipping_address': {'name': address['name'], 'address_line_1': address['line1'],
                'address_line_2': address.get('line2',''), 'city': address['city'],
                'postal_code': address['postal_code'], 'country_code': address['country_code'],
                'phone_number': address.get('phone',''), 'email': address.get('email','')},
            'shipping_details': {'is_local_pickup': False, 'measurement': {'weight': {
                'value': Decimal(str(snapshot['cargo']['actual_weight_kg'])), 'unit': 'kg'}}}}
        if prepared.get('customs_information'):
            customs = prepared['customs_information']
            payload['customs_details'] = {'commercial_invoice_number': customs['invoice_number'],
                'shipment_type': customs['export_reason'], 'tax_numbers': customs['tax_numbers']}
        # Single-element batches isolate invalid orders; the API itself is all-or-nothing.
        body = await self.request('POST', '/orders', [payload])
        rows = body.get('data', [])
        if len(rows)!=1 or rows[0].get('order_id')!=payload['order_id'] or not rows[0].get('id'):
            raise PurchaseUncertain('SENDCLOUD_ORDER_CONFIRMATION_INVALID')
        self.last_order_id, self.last_order_kind = str(rows[0]['id']), 'Order'
        try:
            return await self.retrieve_order(self.last_order_id, snapshot)
        except PurchaseRejected as exc:
            if str(exc).endswith('HTTP_404'):
                raise PurchaseUncertain('SENDCLOUD_ORDER_ASYNC_PENDING') from None
            raise

    async def confirm_order_fulfillment(self, remote_id, snapshot, label):
        await self.retrieve_order(remote_id, snapshot)
        await self.request('PATCH', '/orders/' + identifier(remote_id), {'id': str(remote_id),
            'order_id': native_order_key(snapshot), 'order_details': {'status': {'code': 'fulfilled',
            'message': 'Shipping label confirmed; tracking ' + label['tracking_number']}}})
        return True

    async def retrieve_order(self, remote_id, snapshot):
        body = await self.request('GET', '/orders/' + identifier(remote_id))
        order = body.get('data',{})
        if str(order.get('id'))!=str(remote_id) or order.get('order_id')!=native_order_key(snapshot):
            raise PurchaseRejected('SENDCLOUD_ORDER_IDENTITY_MISMATCH')
        return {'remote_id':str(order['id']),'object_type':'Order'}

    async def purchase_label(self, rate_snapshot):
        self.purchase_allowed()
        snapshot = await self.inject_customs(rate_snapshot)
        body = await self.request('POST', '/shipments', self.payload(snapshot))
        data = body.get('data', body)
        self.last_remote_id = str(data['id']) if data.get('id') is not None else None
        # Both the documented 201 ANNOUNCING and 202 are pending purchases.
        # An accepted announcement never authorizes financial capture.
        if self.last_http_status == 202:
            raise PurchaseUncertain('SENDCLOUD_LABEL_SYNC_PENDING')
        return self.normalize(body,len(rate_snapshot.get('packages') or [rate_snapshot.get('cargo')]))

    def normalize_return(self, data):
        label = (data.get('label') or {}).get('label_printer') or data.get('label_url')
        if not label or not data.get('tracking_number'):
            raise PurchaseUncertain('RETURN_DOCUMENT_NOT_READY')
        return {'upstream_id': self.last_remote_id, 'tracking_number': data['tracking_number'],
                'tracking_url': data.get('tracking_url'), 'label_url': secure_link(label), 'carrier_forms': [],
                **({'return_dropoff_qr_code_url':secure_link(label)} if data.get('delivery_option')=='drop_off_labelless' else {})}

    async def retrieve_label(self, upstream_shipment_id, rate_snapshot):
        rate_snapshot={**rate_snapshot,**rate_snapshot.get('execution_details',{})}
        if rate_snapshot.get('is_return') or getattr(self, 'is_return', False):
            self.last_remote_id = str(upstream_shipment_id)
            return self.normalize_return(await self.request('GET', '/returns/' + identifier(upstream_shipment_id)))
        body = await self.request('GET', '/shipments/' + identifier(upstream_shipment_id))
        if str(body.get('data', body).get('id')) != str(upstream_shipment_id):
            raise PurchaseUncertain('SENDCLOUD_SHIPMENT_IDENTITY_MISMATCH')
        return self.normalize(body,rate_snapshot.get('package_count',len(rate_snapshot.get('packages') or [None])))

    async def void_label(self, upstream_shipment_id):
        self.purchase_allowed()
        if getattr(self, 'is_return', False):
            await self.request('PATCH', '/returns/' + identifier(upstream_shipment_id) + '/cancel')
            # A 202 confirms a request, never the actual cancellation or refund.
            return False
        body = await self.request('POST', '/shipments/' + identifier(upstream_shipment_id) + '/cancel', {})
        return body.get('data', body).get('status') == 'cancelled'

    async def void_confirmed(self, upstream_shipment_id):
        if getattr(self, 'is_return', False):
            body = await self.request('GET', '/returns/' + identifier(upstream_shipment_id))
            return str(body.get('status', {}).get('parent_status', '')).strip().lower() == 'cancelled'
        body = await self.request('GET', '/shipments/' + identifier(upstream_shipment_id))
        return body.get('data', body).get('status') == 'cancelled'

    async def generate_return_label(self, original_shipment_snapshot):
        self.purchase_allowed()
        snapshot = await self.inject_customs(return_snapshot(original_shipment_snapshot))
        forward = self.payload(snapshot)
        parcel = forward['parcels'][0]
        payload = {'from_address': forward['from_address'], 'to_address': forward['to_address'],
            'ship_with': {'type': 'shipping_option_code', 'shipping_option_code': snapshot['upstream_rate_id']},
            'dimensions': parcel['dimensions'], 'weight': parcel['weight'], 'collo_count': 1,
            'order_number': snapshot['order_reference'], 'parcel_items': snapshot.get('parcel_items', [])}
        if snapshot.get('contract_id'):
            payload['ship_with']['contract'] = snapshot['contract_id']
        if snapshot.get('paperless_requested') and snapshot.get('return_paperless_supported') is True:
            payload['delivery_option'] = 'drop_off_labelless'
        else:
            payload['delivery_option'] = 'drop_off_point'
        if snapshot.get('customs_document', {}).get('required'):
            payload['total_order_value'] = {'value': snapshot['customs_document']['totals']['goods_value'],
                                            'currency': snapshot['customs_document']['currency']}
        if snapshot.get('customs_information'):
            payload['customs_information'] = snapshot['customs_information']
        body = await self.request('POST', '/returns/announce-synchronously', payload)
        self.last_remote_id = str(body['return_id'])
        try:
            data = await self.request('GET', '/returns/' + identifier(self.last_remote_id))
        except PurchaseRejected:
            # Announcement succeeded. A later document lookup rejection cannot
            # prove that the carrier purchase failed or authorize a release.
            raise PurchaseUncertain('SENDCLOUD_RETURN_DOCUMENT_PENDING') from None
        return self.normalize_return(data)



ADAPTERS = {adapter.endpoint: adapter for adapter in
            (EasyPostAdapter, SendcloudAdapter, ShippoAdapter)}


def create_adapter(client, account, *, environment):
    adapter = ADAPTERS.get(account.base_url)
    if adapter is None:
        raise PurchaseRejected('NATIVE_LIFECYCLE_NOT_SUPPORTED')
    return adapter(client, account.api_key, environment=environment)


class NativeRateStrategy:
    def __init__(self, client, account, rate_model, environment):
        self.account, self.rate_model = account, rate_model
        self.adapter = create_adapter(client, account, environment=environment)

    async def rates(self, request):
        return await self.adapter.quote(request, self.account, self.rate_model)


def verify_quote_connection(account, rate):
    identity = rate.execution_details
    if (identity.get('account_endpoint') != account.base_url or
            identity.get('account_credential_sha256') != hashlib.sha256(account.api_key.encode()).hexdigest() or
            identity.get('account_upstream_id') != account.upstream_account_id):
        raise PurchaseRejected('CARRIER_CONFIGURATION_CHANGED_REQUOTE_REQUIRED')


class FactoryPurchaseBridge:
    """Integrate the native factory with the existing bulk settlement engine."""
    def __init__(self, client, pool, environment):
        self.client, self.pool, self.environment = client, pool, environment

    async def snapshot(self, account, rate):
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow('''SELECT logistics_metadata FROM public.shipments
                WHERE tenant_id=$1 AND carrier_account_id=$2 AND upstream_rate_id=$3
                AND pricing_snapshot->'selected_rate'->>'offer_id'=$4 LIMIT 2''',
                account.tenant_id, account.id, rate.upstream_rate_id, str(rate.offer_id))
        if row is None:
            raise PurchaseRejected('PREPARED_SHIPMENT_REQUIRED')
        metadata = json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'], str) else row['logistics_metadata']
        snapshot = dict(metadata['automation_order'])
        snapshot.update(rate.model_dump(mode='json'))
        snapshot.update(rate.execution_details)
        snapshot['customs_document'] = metadata.get('automation_customs')
        async with self.pool.acquire() as connection:
            native_order = await connection.fetchval('''SELECT j.remote_object_id FROM public.partner_order_jobs j
                JOIN public.shipments s ON s.tenant_id=j.tenant_id AND s.id=j.shipment_id
                WHERE j.tenant_id=$1 AND j.carrier_account_id=$2 AND j.state='SYNCED' AND j.remote_object_type='Order'
                AND s.pricing_snapshot->'selected_rate'->>'offer_id'=$3''',account.tenant_id,account.id,str(rate.offer_id))
        if native_order:
            snapshot['native_order_id'] = native_order
        return snapshot

    async def buy(self, account, rate):
        verify_quote_connection(account, rate)
        adapter = create_adapter(self.client, account, environment=self.environment)
        snapshot = await self.snapshot(account, rate)
        if snapshot.get('is_return') and len(snapshot.get('packages') or []) > 1:
            raise PurchaseRejected('MULTIPIECE_RETURN_REQUIRES_SEPARATE_PARCELS')
        try:
            if snapshot.get('is_return'):
                # Adapter methods consume the original forward orientation;
                # the stored return order already has operational addresses reversed.
                original = {**snapshot, 'origin': snapshot['destination'], 'destination': snapshot['origin'],
                    'return_quote_authorized': True, 'return_rate_id': rate.upstream_rate_id,
                    'return_shipment_id': rate.upstream_shipment_id}
                label = await adapter.generate_return_label(original)
            else:
                label = await adapter.purchase_label(snapshot)
        except PurchaseRejected as exc:
            # Preserve bounded diagnostics without storing arbitrary provider bodies.
            code = str(exc) if str(exc) in {'SHIPPO_CARRIER_UNAVAILABLE', 'LABEL_REJECTED',
                'RATE_NO_LONGER_AVAILABLE', 'REMOTE_MODE_MISMATCH'} else 'NATIVE_PURCHASE_REJECTED'
            try:
                async with self.pool.acquire() as connection:
                    await connection.execute('''UPDATE public.shipments SET logistics_metadata=
                        logistics_metadata||jsonb_build_object('purchase_failure',$4::jsonb)
                        WHERE tenant_id=$1 AND carrier_account_id=$2
                        AND pricing_snapshot->'selected_rate'->>'offer_id'=$3 AND status='BOOKING' ''',
                        account.tenant_id, account.id, str(rate.offer_id), json.dumps({
                            'code': code, 'provider': type(adapter).__name__,
                            'transaction_id': adapter.last_remote_id if isinstance(adapter.last_remote_id, str) and len(adapter.last_remote_id) <= 150 else None, 'http_status': adapter.last_http_status}))
            except Exception:
                import logging
                logging.getLogger(__name__).warning('Definitive rejection diagnostic deferred')
            raise
        except PurchaseUncertain:
            if adapter.last_remote_id:
                try:
                    async with self.pool.acquire() as connection:
                        await connection.execute('''UPDATE public.shipments SET logistics_metadata=
                            logistics_metadata||jsonb_build_object('partner_pending_remote_id',$4::text,
                                'label_lifecycle_status',$5::text,'label_poll_attempts',0,'label_poll_after',now()::text)
                            WHERE tenant_id=$1 AND carrier_account_id=$2
                            AND pricing_snapshot->'selected_rate'->>'offer_id'=$3 AND status='BOOKING' ''',
                            account.tenant_id, account.id, str(rate.offer_id), str(adapter.last_remote_id),
                            'SYNC_PENDING' if isinstance(adapter, SendcloudAdapter) else 'RECONCILIATION_REQUIRED')
                except Exception:
                    pass
            raise
        # Optional QR creation must never turn a confirmed label into a failed
        # purchase or release its reservation. Fence the forms POST durably.
        if snapshot.get('is_return') and snapshot.get('paperless_requested') and isinstance(adapter, EasyPostAdapter):
            from backend.return_documents import request_easypost_qr
            label = await request_easypost_qr(self.pool, adapter, account, rate, snapshot, label)
        try:
            async with self.pool.acquire() as connection:
                await connection.execute('''UPDATE public.shipments
                    SET logistics_metadata=logistics_metadata||jsonb_build_object('automation_label',$4::jsonb)
                    WHERE tenant_id=$1 AND carrier_account_id=$2
                    AND pricing_snapshot->'selected_rate'->>'offer_id'=$3 AND status='BOOKING' ''',
                    account.tenant_id, account.id, str(rate.offer_id), json.dumps(label))
        except Exception:
            raise PurchaseUncertain('LABEL_PERSISTENCE_RECONCILIATION_REQUIRED') from None
        return label

    async def reconcile(self, account, rate):
        snapshot = await self.snapshot(account, rate)
        # Native IDs of successful announcements differ from quote IDs.
        # Until a durable confirmation exists, never issue another purchase.
        async with self.pool.acquire() as connection:
            label = await connection.fetchval('''SELECT logistics_metadata->'automation_label'
                FROM public.shipments WHERE tenant_id=$1 AND carrier_account_id=$2
                AND pricing_snapshot->'selected_rate'->>'offer_id'=$3''',
                account.tenant_id, account.id, str(rate.offer_id))
        label = json.loads(label) if isinstance(label, str) else label
        if not label or not label.get('upstream_id'):
            raise PurchaseUncertain('REMOTE_ID_RECONCILIATION_REQUIRED')
        adapter = create_adapter(self.client, account, environment=self.environment)
        return await adapter.retrieve_label(label['upstream_id'], snapshot)


class BookingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tenant_id: UUID
    offer_id: UUID
    insurance_requested: bool = False
    insurance_quote_id: UUID | None = None
    insurance_terms_accepted: bool = Field(default=False, strict=True)


class VoidRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tenant_id: UUID
    shipment_id: UUID


from backend.reverse_logistics import ReturnCommand


class ReturnRequest(VoidRequest):
    idempotency_key: UUID
    customs_signer: str | None = None
    hs_codes_reviewed: bool = False
    store_return_reference: str | None = Field(default=None,max_length=200)
    preparation_edits: dict | None = None


def authorize(context, tenant_id):
    if context.tenant_id != tenant_id:
        raise HTTPException(403, 'Requested workspace does not match the authenticated session')
    if context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}:
        raise HTTPException(403, 'Dispatch permission required')


class PartnerLifecycleService:
    def __init__(self, automation, client):
        self.automation, self.client = automation, client
        self.pool, self.finance = automation.pool, automation.finance
        self.card_limiter=asyncio.Semaphore(1)

    def environment(self, tenant):
        settings = self.automation.settings
        test = (settings.provider_environment == 'TEST' and
                settings.database_environment == 'SANDBOX' and tenant['is_sandbox'])
        live = (settings.provider_environment == 'LIVE' and
                settings.database_environment == 'LIVE' and not tenant['is_sandbox'] and
                settings.automation_purchase_enabled)
        if not test and not live:
            raise HTTPException(403, 'Carrier purchase is disabled for this workspace environment')
        return 'TEST' if test else 'LIVE'

    async def ticket(self, context, shipment_id, code):
        try:
            await self.automation.fail_ticket(context.tenant_id,
                uuid5(NAMESPACE_URL, 'lifecycle:' + str(shipment_id)), str(shipment_id), shipment_id, code)
        except Exception:
            # The held reservation remains authoritative if optional support fails.
            import logging
            logging.getLogger(__name__).warning('Lifecycle support persistence deferred; shipment=%s', shipment_id)

    def public_result(self, shipment_id, label, customs=None, replayed=False):
        has_qr=any(label.get(key) for key in ('return_dropoff_qr_code_url','return_dropoff_qr_code_svg','return_dropoff_qr_code_base64'))
        root = '/api/v1/shipping/' + str(shipment_id) + '/documents/'
        return {'shipment_id': str(shipment_id), 'status': 'BOOKED', 'label_status': 'LABEL_CREATED', 'replayed': replayed,
                'environment': self.automation.settings.provider_environment,
                'label': {'tracking_number': label['tracking_number'], 'tracking_url': '/?view=manifest&shipment_id=' + str(shipment_id), 'label_url': root + 'label',
                          'package_labels':[{'tracking_number':piece['tracking_number'],'label_url':root+('label' if index==0 else str(next(i for i,form in enumerate(label.get('carrier_forms',[])) if form['url']==piece['label_url'])))} for index,piece in enumerate(label.get('package_labels',[]))],
                          'carrier_forms': [{'document_type': f['document_type'], 'url': root + str(i)}
                                            for i, f in enumerate(label.get('carrier_forms', []))]},
                'customs': customs,
                'paperless_available':has_qr,
                'return_dropoff_qr_code_url':root+'return-qr' if has_qr else None,
                'dropoff_instructions':('Use a participating drop-off location for the selected carrier. Check its parcel and location restrictions.'
                    if has_qr else 'Print the shipping label and use an eligible location for the selected carrier.')}

    async def bind_direct_quote(self, context, offer_id):
        from main import RatingRequest, RatingResponse
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow('''SELECT request_id,request_payload,quote_payload FROM public.partner_unbound_quotes
                WHERE tenant_id=$1 AND expires_at>now() AND quote_payload->'rates' @>
                jsonb_build_array(jsonb_build_object('offer_id',$2::text))''', context.tenant_id, str(offer_id))
        if row is None:
            raise HTTPException(404, 'Offer not found in this workspace or expired')
        request = RatingRequest.model_validate_json(row['request_payload']) if isinstance(row['request_payload'],str) else RatingRequest.model_validate(row['request_payload'])
        quoted = RatingResponse.model_validate_json(row['quote_payload']) if isinstance(row['quote_payload'],str) else RatingResponse.model_validate(row['quote_payload'])

        dimensions = request.dimensions[0].model_dump(mode='json') if request.dimensions else {}
        document = request.customs_document or {}
        order = {'idempotency_key':str(row['request_id']), 'order_reference':'QUOTE-'+str(row['request_id']),
            'origin':request.origin.model_dump(mode='json'),'destination':request.destination.model_dump(mode='json'),
            'sender_notifications':request.sender_notifications.model_dump(),
            'currency':request.currency,'cargo':{'cargo_type':request.cargo_type,'actual_weight_kg':str(request.weights_kg[0]),
                                             'stackable':request.stackable,**dimensions},
            'items':[{field:item[field] for field in ('description','quantity','unit_value','unit_weight_kg','origin_country','hs_code','sku','package_index') if field in item}
                     for item in document.get('items',[])],
            'customs_signer':document.get('signer'), 'hs_codes_reviewed':bool(document.get('ready_for_provider'))}
        if len(request.weights_kg)>1:
            order['packages']=[{'cargo_type':'PARCEL','actual_weight_kg':str(weight),'stackable':request.stackable,**box.model_dump(mode='json')} for box,weight in zip(request.dimensions,request.weights_kg,strict=True)]
        if request.is_return:
            raise HTTPException(422, 'Prepare returns through the authenticated original shipment workflow')
        async with self.automation.order_limiter:
            result = await self.automation.process(context,order,'QUOTE_ONLY',private_quote=quoted)
        if result['status']!='QUOTED':
            raise HTTPException(422,result.get('error','Packing or customs review required'))

    async def confirm(self, context, body):
        result=await self._prepare_confirm(context,body)
        if result.get('paperless_available'):
            from backend.return_documents import public_return_links
            from backend.logistics_media import publish_return_media
            return await publish_return_media(self,context,public_return_links(self.automation.settings,context,result))
        return result

    async def _prepare_confirm(self, context, body):
        authorize(context, body.tenant_id)
        if body.insurance_requested:
            protection = getattr(self, 'protection', None)
            if protection is None:
                from backend.shipment_protection import PROTECTION_NOTICE
                raise HTTPException(409, PROTECTION_NOTICE)
            return await protection.confirm(context, body, self)
        if body.insurance_quote_id is not None:
            raise HTTPException(422, 'A protection quote requires insurance_requested=true')
        async with self.pool.acquire() as connection:
            prepared = await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.partner_shipping_offers WHERE tenant_id=$1 AND offer_id=$2)', context.tenant_id, body.offer_id)
        if not prepared:
            try:
                await self.bind_direct_quote(context, body.offer_id)
            except (ValueError, KeyError, TypeError):
                raise HTTPException(422, 'This quote needs complete packing and customs review before booking') from None
        limiter=getattr(self.automation,'order_limiter',None) or asyncio.Semaphore(1)
        async with limiter:
            return await self._confirm(context,body)

    async def _confirm(self,context,body):
        from main import ClientRate, BookingPermit
        async with self.pool.acquire() as lock:
            offer = await lock.fetchrow('''SELECT o.shipment_id,o.rate_snapshot,o.expires_at,s.idempotency_key
                FROM public.partner_shipping_offers o JOIN public.shipments s
                  ON s.tenant_id=o.tenant_id AND s.id=o.shipment_id
                WHERE o.tenant_id=$1 AND o.offer_id=$2''', context.tenant_id, body.offer_id)
            if offer is None:
                raise HTTPException(404, 'Prepared offer not found; pack and review the workspace order first')
            # Share the preparation/bulk lock: concurrent repricing must never
            # replace a submitted purchase's immutable financial snapshot.
            key = 'automation:' + str(context.tenant_id) + ':' + str(offer['idempotency_key'])
            if not await lock.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key):
                raise HTTPException(409, 'This offer is already being processed')
            try:
                row = await lock.fetchrow('''SELECT * FROM public.shipments WHERE tenant_id=$1
                    AND id=$2''', context.tenant_id, offer['shipment_id'])
                if row is None:
                    raise HTTPException(404, 'Prepared offer not found; pack and review the workspace order first')
                stored_rate = json.loads(offer['rate_snapshot']) if isinstance(offer['rate_snapshot'], str) else offer['rate_snapshot']
                rate = ClientRate.model_validate(stored_rate)
                metadata = json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'], str) else row['logistics_metadata']
                if metadata.get('return_review_id'):
                    from backend.return_review import assert_review_purchase
                    await assert_review_purchase(lock, context.tenant_id, row['id'],
                        UUID(metadata['return_review_id']), body.offer_id)
                if row['status'] in {'BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','DELIVERED','EXCEPTION'}:
                    selected = json.loads(row['pricing_snapshot']) if isinstance(row['pricing_snapshot'], str) else row['pricing_snapshot']
                    if selected.get('selected_rate', {}).get('offer_id') != str(body.offer_id):
                        raise HTTPException(409, 'Another offer was already booked for this order')
                    if not metadata.get('automation_label'):
                        raise HTTPException(409, 'Original label requires reconciliation')
                    return self.public_result(row['id'], metadata['automation_label'], metadata.get('automation_customs'), True)
                historical_access = row['status']=='BOOKING'
                return_order=metadata.get('automation_order') or {}
                if return_order.get('is_return'):
                    from backend.carrier_access import verified_return_parent
                    parent_account=await verified_return_parent(lock,context.tenant_id,UUID(return_order['return_of_shipment_id']),return_order['origin'],return_order['destination'],
                        warehouse_id=UUID(return_order['return_warehouse_id']) if return_order.get('return_warehouse_id') else None,
                        warehouse_version=return_order.get('return_warehouse_version'))
                    if parent_account!=rate.account_id and not return_order.get('return_network_selection'):
                        raise HTTPException(403,'Return offer must use the original shipment connection')
                    historical_access=row['status']=='BOOKING' or (parent_account==rate.account_id and not return_order.get('return_network_selection'))
                accounts = await self.automation.repository.accounts(context)
                if historical_access and not any(a.id==rate.account_id for a in accounts):
                    accounts=await self.automation.repository.accounts(context,historical_account_id=rate.account_id)
                account = next((a for a in accounts if a.id == rate.account_id), None)
                if account is None:
                    raise HTTPException(409, 'The carrier connection is no longer available')
                try:
                    verify_quote_connection(account, rate)
                except PurchaseRejected:
                    raise HTTPException(409, 'Carrier configuration changed; request a fresh quote before booking') from None
                tenant = await lock.fetchrow('SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1', context.tenant_id)
                environment = self.environment(tenant)
                from backend.integration_policy import integration_enabled
                if row['status'] != 'BOOKING' and not integration_enabled(account.base_url, self.automation.settings):
                    raise HTTPException(409, 'Shipping integration disabled; request fresh quotes before booking')
                adapter = create_adapter(self.client, account, environment=environment)
                if environment == 'TEST' and not isinstance(adapter, (EasyPostAdapter, ShippoAdapter)):
                    raise HTTPException(403, 'This connection has no verified non-billable label test contract')
                if row['status'] == 'BOOKING':
                    selected = json.loads(row['pricing_snapshot']) if isinstance(row['pricing_snapshot'], str) else row['pricing_snapshot']
                    if selected.get('selected_rate', {}).get('offer_id') != str(body.offer_id):
                        raise HTTPException(409, 'Another offer is being processed for this order')
                    reservation = await lock.fetchrow('''SELECT * FROM public.wallet_reservations
                        WHERE tenant_id=$1 AND shipment_id=$2''', context.tenant_id, row['id'])
                    if not reservation or reservation['status'] != 'SUBMITTED':
                        raise HTTPException(409, 'Outcome requires reconciliation; no second purchase was attempted')
                    permit = BookingPermit(context.tenant_id, row['id'], reservation['id'], reservation['amount'],
                                           reservation['currency'], reservation['billing_plan'])
                    label = metadata.get('automation_label')
                    if not label:
                        remote_id = (rate.upstream_shipment_id if isinstance(adapter, EasyPostAdapter)
                                     else metadata.get('partner_pending_remote_id'))
                        if not remote_id:
                            raise HTTPException(409, 'Native transaction reference requires reconciliation; reserved credit retained')
                        try:
                            label = await adapter.retrieve_label(remote_id, dict(stored_rate, is_return=bool(metadata.get('automation_order', {}).get('is_return'))))
                            await lock.execute('''UPDATE public.shipments SET logistics_metadata=
                                logistics_metadata||jsonb_build_object('automation_label',$3::jsonb)
                                WHERE tenant_id=$1 AND id=$2 AND status='BOOKING' ''', context.tenant_id, row['id'], json.dumps(label))
                        except Exception:
                            raise HTTPException(409, 'Native outcome remains unconfirmed; no purchase was retried') from None
                else:
                    if row['status'] != 'QUOTED':
                        raise HTTPException(409, 'Offer is no longer bookable')
                    from datetime import datetime, timezone
                    if offer['expires_at'] <= datetime.now(timezone.utc) or offer['expires_at'] != row['quote_expires_at']:
                        raise HTTPException(409, 'Offer expired or superseded; request a new quote')
                    wholesale = Decimal(rate.fee_breakdown['wholesale_total'])
                    markup = rate.client_price_ex_tax - wholesale
                    selected = {'markup_type': 'MANUAL', 'markup_value': str(markup), 'currency': rate.currency,
                                'selected_rate': stored_rate}
                    await lock.execute('''UPDATE public.shipments SET carrier_account_id=$3,wholesale_cost=$4,
                        profit_markup=$5,tax_amount=0,currency=$6,pricing_snapshot=$7::jsonb,
                        carrier_code=$8,service_code=$9,upstream_shipment_id=$10,upstream_rate_id=$11,quote_expires_at=$12,
                        logistics_metadata=logistics_metadata-'invoice_baseline'
                        WHERE tenant_id=$1 AND id=$2 AND status='QUOTED' ''', context.tenant_id, row['id'], rate.account_id,
                        wholesale, markup, rate.currency, json.dumps(selected), rate.carrier_code, rate.service_code,
                        rate.upstream_shipment_id, rate.upstream_rate_id, offer['expires_at'])
                    from main import Address
                    from backend.address_validation import verify_shipping_addresses
                    order_addresses = metadata.get('automation_order') or {}
                    from pydantic import ValidationError
                    try:
                        addresses = [('Pickup', Address.model_validate(order_addresses.get('origin'))),
                                     ('Delivery', Address.model_validate(order_addresses.get('destination')))]
                    except ValidationError:
                        raise HTTPException(422, 'Stored pickup or delivery address is incomplete. Requote the shipment with complete addresses before booking.') from None
                    await verify_shipping_addresses(self.client, self.automation.settings, addresses)
                    native_orders=getattr(self.automation,'native_orders',None)
                    if native_orders is not None:
                        await native_orders.ensure_order(context.tenant_id,row['id'],account.id)
                    permit = await self.finance.reserve(context, row['id'])
                    try:
                        await self.finance.mark_submitted(permit, verified_test_environment=environment == 'TEST')
                    except Exception:
                        await self.finance.finish_booking(permit, 'NOT_SUBMITTED')
                        raise
                    bridge = FactoryPurchaseBridge(self.client, self.pool, environment)
                    try:
                        label = await bridge.buy(account, rate)
                    except PurchaseRejected as exc:
                        await self.finance.finish_booking(permit, 'DEFINITIVE_FAILURE')
                        unavailable = str(exc) == 'SHIPPO_CARRIER_UNAVAILABLE'
                        await self.ticket(context, row['id'], 'SHIPPO_CARRIER_UNAVAILABLE' if unavailable else 'NATIVE_PURCHASE_REJECTED')
                        message = ('This carrier is temporarily unavailable. Request fresh quotes and choose another carrier, '
                                   'or try again later. Reserved wallet credit has been released.' if unavailable else
                                   'The carrier could not create this label. Reserved wallet credit has been released. '
                                   'Request fresh quotes or contact EasyInvio support; the failure is recorded for our team.')
                        raise HTTPException(502, {
                            'code': 'CARRIER_UNAVAILABLE' if unavailable else 'CARRIER_PURCHASE_REJECTED',
                            'message': message, 'retry_requires_fresh_quote': True,
                            'reserved_credit_released': True,
                        }) from None
                    except Exception:
                        pending = await lock.fetchval('''SELECT logistics_metadata->>'label_lifecycle_status'
                            FROM public.shipments WHERE tenant_id=$1 AND id=$2''', context.tenant_id, row['id'])
                        if pending == 'SYNC_PENDING':
                            return {'shipment_id': str(row['id']), 'status': 'SYNC_PENDING',
                                    'shipment_status': 'BOOKING', 'label_status': 'SYNC_PENDING',
                                    'message': 'Announcement accepted; credit remains reserved until the label is confirmed.'}
                        await self.ticket(context, row['id'], 'PURCHASE_RECONCILIATION_REQUIRED')
                        raise HTTPException(502, 'Shipping outcome is uncertain; credit remains reserved pending reconciliation') from None
                try:
                    await self.finance.finish_booking(permit, 'SUCCESS', tracking_number=label['tracking_number'],
                        label_storage_path=label['label_url'], carrier_name=rate.carrier_code, label_documents=label,
                        verified_test_environment=environment == 'TEST')
                except Exception:
                    await self.ticket(context, row['id'], 'LABEL_SETTLEMENT_RECONCILIATION_REQUIRED')
                    raise HTTPException(503, 'Label confirmation is stored; financial settlement needs reconciliation') from None
                return self.public_result(row['id'], label, metadata.get('automation_customs'))
            finally:
                await lock.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)

    async def void(self, context, body):
        authorize(context, body.tenant_id)
        async with self.pool.acquire() as lock:
            key = 'partner-void:' + str(context.tenant_id) + ':' + str(body.shipment_id)
            if not await lock.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key):
                raise HTTPException(409, 'Cancellation already processing')
            try:
                shipment = await lock.fetchrow('SELECT * FROM public.shipments WHERE tenant_id=$1 AND id=$2', context.tenant_id, body.shipment_id)
                if shipment is None:
                    raise HTTPException(404, 'Shipment not found')
                if shipment['status'] == 'CANCELLED':
                    return {'status': 'CANCELLED', 'replayed': True}
                if shipment['status'] != 'BOOKED':
                    raise HTTPException(409, 'Only an undispatched booked shipment can be cancelled')
                if shipment.get('manifest_id') is not None:
                    raise HTTPException(409,'A manifest has claimed this shipment; reconcile carrier close-out before cancellation')
                accounts = await self.automation.repository.accounts(context)
                if not any(a.id == shipment['carrier_account_id'] for a in accounts):
                    accounts = await self.automation.repository.accounts(context, historical_account_id=shipment['carrier_account_id'])
                account = next((a for a in accounts if a.id == shipment['carrier_account_id']), None)
                if account is None:
                    raise HTTPException(409, 'Original carrier connection unavailable')
                tenant = await lock.fetchrow('SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1', context.tenant_id)
                adapter = create_adapter(self.client, account, environment=self.environment(tenant))
                metadata = json.loads(shipment['logistics_metadata']) if isinstance(shipment['logistics_metadata'], str) else shipment['logistics_metadata']
                if len((metadata.get('automation_label') or {}).get('package_labels',[]))>1:
                    raise HTTPException(409,'Multi-piece cancellation requires all-package refund reconciliation. Contact support; no cancellation or wallet refund was submitted.')
                adapter.is_return = bool(metadata.get('automation_order', {}).get('is_return'))
                label = metadata.get('automation_label') or {}
                remote_id = label.get('upstream_id', shipment['upstream_shipment_id'])
                if not remote_id:
                    raise HTTPException(409, 'Original transaction reference requires reconciliation')
                prior = await lock.fetchrow('SELECT state FROM public.partner_cancellations WHERE tenant_id=$1 AND shipment_id=$2', context.tenant_id, body.shipment_id)
                await lock.execute('''INSERT INTO public.partner_cancellations(tenant_id,shipment_id)
                    VALUES($1,$2) ON CONFLICT DO NOTHING''', context.tenant_id, body.shipment_id)
                try:
                    confirmed = await (adapter.void_confirmed(remote_id) if prior else adapter.void_label(remote_id))
                except Exception:
                    await self.ticket(context, body.shipment_id, 'CANCELLATION_RECONCILIATION_REQUIRED')
                    raise HTTPException(502, 'Cancellation requires reconciliation; no wallet refund applied') from None
                if not confirmed:
                    return {'status': 'CANCELLATION_PENDING', 'wallet_credited': False}
                async with lock.transaction():
                    await self.finance.lock_tenant(lock, context.tenant_id, context, {'OWNER', 'ADMIN', 'DISPATCHER'})
                    current_status = await lock.fetchval('SELECT status FROM public.shipments WHERE tenant_id=$1 AND id=$2 FOR UPDATE', context.tenant_id, body.shipment_id)
                    if current_status != 'BOOKED':
                        raise HTTPException(409, 'Shipment changed during cancellation; reconcile before crediting')
                    reservation = await lock.fetchrow('''SELECT * FROM public.wallet_reservations
                        WHERE tenant_id=$1 AND shipment_id=$2 FOR UPDATE''', context.tenant_id, body.shipment_id)
                    if not reservation or reservation['status'] != 'CAPTURED':
                        raise HTTPException(409, 'Original charge requires reconciliation')
                    if reservation['billing_plan'] == 'PREPAID_WALLET':
                        wallet = await self.finance.lock_wallet(lock, context.tenant_id)
                        if wallet['currency'] != reservation['currency']:
                            raise HTTPException(409, 'Wallet currency requires reconciliation')
                        balance = wallet['balance'] + reservation['amount']
                        await lock.execute('UPDATE public.wallets SET balance=$2,updated_at=now() WHERE tenant_id=$1', context.tenant_id, balance)
                        await self.finance.append_ledger(lock, tenant_id=context.tenant_id, currency=reservation['currency'],
                            entry_type='SHIPMENT_REFUND', balance_delta=reservation['amount'], reserved_delta=Decimal(0),
                            balance_after=balance, reserved_after=wallet['reserved_balance'], reservation_id=reservation['id'])
                    await lock.execute("UPDATE public.shipments SET status='CANCELLED' WHERE tenant_id=$1 AND id=$2", context.tenant_id, body.shipment_id)
                    await lock.execute("UPDATE public.partner_cancellations SET state='CREDITED',updated_at=now() WHERE tenant_id=$1 AND shipment_id=$2", context.tenant_id, body.shipment_id)
                return {'status': 'CANCELLED', 'wallet_credited': reservation['billing_plan'] == 'PREPAID_WALLET'}
            finally:
                await lock.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)

    async def poll_and_finalize_sendcloud_label(self, shipment_id: UUID):
        """Poll one durable announcement under the same lock as booking/replay.

        No POST, no re-rating, and no reservation release before atomic capture.
        Credentials and the financial snapshot must still match the accepted offer.
        """
        from main import BookingPermit, ClientRate, TenantContext
        async with self.pool.acquire() as lock:
            row = await lock.fetchrow('SELECT * FROM public.shipments WHERE id=$1', shipment_id)
            if row is None:
                return False
            key = 'automation:' + str(row['tenant_id']) + ':' + str(row['idempotency_key'])
            if not await lock.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key):
                return False
            attempts = 0
            context = TenantContext(row['tenant_id'], UUID(int=0), 'OWNER', '')
            try:
                row = await lock.fetchrow('SELECT * FROM public.shipments WHERE tenant_id=$1 AND id=$2', row['tenant_id'], shipment_id)
                metadata = decode_json(row['logistics_metadata'])
                if row['status'] != 'BOOKING' or metadata.get('label_lifecycle_status') != 'SYNC_PENDING':
                    return False
                attempts = int(metadata.get('label_poll_attempts', 0))
                if attempts >= 30:
                    return False
                await lock.execute('''UPDATE public.shipments SET logistics_metadata=logistics_metadata||
                    jsonb_build_object('label_poll_attempts',$3::int,'label_poll_after',
                        (now()+make_interval(secs=>$4))::text) WHERE tenant_id=$1 AND id=$2''',
                    row['tenant_id'], shipment_id, attempts + 1, min(3600, 20 * 2 ** min(attempts, 7)))
                selected = decode_json(row['pricing_snapshot'])['selected_rate']
                rate = ClientRate.model_validate(selected)
                accounts = await self.automation.repository.accounts(context, historical_account_id=row['carrier_account_id'])
                account = next((item for item in accounts if item.id == rate.account_id), None)
                if account is None or account.base_url != SendcloudAdapter.endpoint:
                    raise PurchaseUncertain('PENDING_CONNECTION_UNAVAILABLE')
                verify_quote_connection(account, rate)
                tenant = await lock.fetchrow('SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1', row['tenant_id'])
                environment = self.environment(tenant)
                reservation = await lock.fetchrow('''SELECT * FROM public.wallet_reservations
                    WHERE tenant_id=$1 AND shipment_id=$2''', row['tenant_id'], shipment_id)
                if not reservation or reservation['status'] != 'SUBMITTED':
                    raise PurchaseUncertain('PENDING_RESERVATION_RECONCILIATION_REQUIRED')
                adapter = SendcloudAdapter(self.client, account.api_key, environment=environment)
                label = metadata.get('automation_label')
                if not label:
                    remote_id = metadata.get('partner_pending_remote_id')
                    if not remote_id:
                        raise PurchaseUncertain('PENDING_NATIVE_REFERENCE_MISSING')
                    label = await adapter.retrieve_label(remote_id, {'is_return':bool(metadata.get('automation_order',{}).get('is_return'))})
                    await lock.execute('''UPDATE public.shipments SET logistics_metadata=logistics_metadata||
                        jsonb_build_object('automation_label',$3::jsonb) WHERE tenant_id=$1 AND id=$2
                        AND status='BOOKING' ''', row['tenant_id'], shipment_id, json.dumps(label))
                permit = BookingPermit(row['tenant_id'], shipment_id, reservation['id'], reservation['amount'],
                                       reservation['currency'], reservation['billing_plan'])
                await self.finance.finish_booking(permit, 'SUCCESS', tracking_number=label['tracking_number'],
                    label_storage_path=label['label_url'], carrier_name=rate.carrier_code,
                    label_documents=label, verified_test_environment=environment == 'TEST')
                return True
            except Exception:
                logging.getLogger(__name__).warning('Label poll deferred; held credit retained; shipment=%s', shipment_id)
                if attempts == 29:
                    await self.ticket(context, shipment_id, 'LABEL_POLL_RECONCILIATION_REQUIRED')
                return False
            finally:
                await lock.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)

    async def worker(self):
        """Poll pending labels and cancellations without repeating mutations."""
        import logging
        from main import TenantContext
        while True:
            try:
                async with self.pool.acquire() as connection:
                    labels = await connection.fetch('''SELECT id FROM public.shipments WHERE status='BOOKING'
                        AND logistics_metadata->>'label_lifecycle_status'='SYNC_PENDING'
                        AND coalesce((logistics_metadata->>'label_poll_attempts')::int,0)<30
                        AND (logistics_metadata->>'label_poll_after')::timestamptz<=now()
                        ORDER BY updated_at,id LIMIT 10''')
                for label_job in labels:
                    await self.poll_and_finalize_sendcloud_label(label_job['id'])
                async with self.pool.acquire() as connection:
                    jobs = await connection.fetch('''SELECT p.tenant_id,p.shipment_id,p.attempts,
                        member.auth_user_id,member.role FROM public.partner_cancellations p
                        JOIN LATERAL (SELECT auth_user_id,role FROM public.users
                          WHERE tenant_id=p.tenant_id AND is_active AND role IN ('OWNER','ADMIN')
                          ORDER BY role DESC,id LIMIT 1) member ON true
                        WHERE p.state='PENDING' AND p.next_attempt_at<=now() AND p.attempts<30
                        ORDER BY p.next_attempt_at LIMIT 10''')
                for job in jobs:
                    async with self.pool.acquire() as connection:
                        await connection.execute('''UPDATE public.partner_cancellations SET attempts=attempts+1,
                            next_attempt_at=now()+make_interval(secs=>$3) WHERE tenant_id=$1 AND shipment_id=$2
                            AND state='PENDING' ''', job['tenant_id'], job['shipment_id'], min(3600, 30 * 2 ** min(job['attempts'], 7)))
                    context = TenantContext(job['tenant_id'], job['auth_user_id'], job['role'], '')
                    try:
                        await self.void(context, VoidRequest(tenant_id=job['tenant_id'], shipment_id=job['shipment_id']))
                    except Exception:
                        logging.getLogger(__name__).warning('Pending cancellation retained for reconciliation; shipment=%s', job['shipment_id'])
            except Exception:
                logging.getLogger(__name__).warning('Cancellation poll deferred; durable requests retained')
            await asyncio.sleep(20)


async def carrier_document(shipment_id: UUID, document: str, service, context):
    from fastapi.responses import Response
    authorize(context, context.tenant_id)
    async with service.pool.acquire() as connection:
        row = await connection.fetchrow('''SELECT carrier_account_id,logistics_metadata FROM public.shipments
            WHERE tenant_id=$1 AND id=$2 AND status IN ('BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED')''', context.tenant_id, shipment_id)
    if row is None:
        raise HTTPException(404, 'Document not found')
    metadata = json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'], str) else row['logistics_metadata']
    label = metadata.get('automation_label') or {}
    if document == 'return-qr':
        from backend.logistics_media import inline_asset, normalize_image
        inline = inline_asset(label)
        if inline is not None:
            try:
                raw, mime = await asyncio.to_thread(normalize_image, inline)
            except ValueError:
                raise HTTPException(502, 'Carrier QR image is invalid') from None
            return Response(raw, media_type=mime, headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    try:
        link = (metadata.get('return_dropoff_qr_code_url') or label['return_dropoff_qr_code_url']) if document == 'return-qr' else label['label_url'] if document == 'label' else label['carrier_forms'][int(document)]['url']
        if document not in {'label','return-qr'} and (not document.isdigit() or int(document) < 0):
            raise ValueError()
        parsed = urlsplit(secure_link(link))
    except (ValueError, KeyError, IndexError, PurchaseUncertain):
        raise HTTPException(404, 'Document not found') from None
    approved = set(service.automation.settings.partner_document_allowed_hosts)
    if parsed.hostname not in approved:
        raise HTTPException(503, 'Document host requires platform-owner approval')
    accounts = await service.automation.repository.accounts(context, historical_account_id=row['carrier_account_id'])
    account = next((a for a in accounts if a.id == row['carrier_account_id']), None)
    authentication = {}
    if account and parsed.hostname == urlsplit(account.base_url).hostname:
        adapter = create_adapter(service.client, account, environment=service.automation.settings.provider_environment)
        authentication = adapter.authentication()
    try:
        async with service.client.stream('GET', link, follow_redirects=False, timeout=30, **authentication) as response:
            if response.status_code != 200:
                raise HTTPException(502, 'Shipping document unavailable')
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 15_000_000:
                    raise HTTPException(502, 'Shipping document exceeds download limit')
        if document == 'return-qr':
            from backend.logistics_media import normalize_image
            try:
                normalized, mime = await asyncio.to_thread(normalize_image, bytes(raw))
            except ValueError:
                raise HTTPException(502, 'Carrier QR image is invalid') from None
            return Response(normalized, media_type=mime, headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
        media = ('image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else
                 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else
                 'application/pdf' if raw.startswith(b'%PDF-') else None)
        if media is None or (document != 'return-qr' and media != 'application/pdf'):
            raise HTTPException(502, 'Provider did not return the requested PDF document')
        extension = {'image/png':'png','image/jpeg':'jpg','application/pdf':'pdf'}[media]
        return Response(bytes(raw), media_type=media, headers={'Cache-Control': 'no-store',
            'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
            'Content-Disposition': ('inline' if document=='return-qr' else 'attachment') + '; filename="easyinvio-' + str(shipment_id) + '.' + extension + '"'})
    except httpx.HTTPError:
        raise HTTPException(502, 'Shipping document temporarily unavailable') from None

async def prepare_return_quote(service, context, body, *, warehouse=None, paperless_requested=False):
    authorize(context, body.tenant_id)
    async with service.pool.acquire() as connection:
        row = await connection.fetchrow('''SELECT logistics_metadata,tracking_number,booked_at,carrier_code FROM public.shipments
            WHERE tenant_id=$1 AND id=$2 AND status='DELIVERED' ''',
            context.tenant_id, body.shipment_id)
    if row is None:
        raise HTTPException(409, 'Returns require an original outbound shipment with recorded delivery in this workspace')
    metadata = json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'], str) else row['logistics_metadata']
    original = metadata.get('automation_order')
    if not original or original.get('is_return'):
        raise HTTPException(422, 'An original prepared outbound shipment is required')
    if len(original.get('packages') or [])>1:
        raise HTTPException(409,'Create separately measured return parcels; grouped return purchase is not enabled')
    order = copy.deepcopy(original)
    customs = metadata.get('automation_customs') or {}
    order.update(idempotency_key=str(body.idempotency_key), order_reference=('RETURN-' + original['order_reference'])[:100],
        origin=original['destination'], destination=original['origin'], is_return=True,
        return_of_shipment_id=str(body.shipment_id), platform='MANUAL', store_id=None, store_order_id=None,
        store_return_reference=body.store_return_reference,
        customs_signer=body.customs_signer, hs_codes_reviewed=body.hs_codes_reviewed, postal_form=None,
        sender_eori=customs.get('recipient', {}).get('eori'), recipient_eori=customs.get('sender', {}).get('eori'),
        sender_vat=customs.get('recipient', {}).get('vat_registration'), recipient_vat=customs.get('sender', {}).get('vat_registration'),
        original_invoice_number=customs.get('invoice_number') or str(body.shipment_id),
        return_data={'return_postal_code':original['destination']['postal_code'],
                     'outbound_tracking_number':row['tracking_number'],
                     'outbound_shipment_date':row['booked_at'].date().isoformat() if row['booked_at'] else None,
                     'outbound_carrier_name':row['carrier_code']})
    if warehouse is not None:
        order.update(destination=json.loads(warehouse['address']) if isinstance(warehouse['address'],str) else warehouse['address'],
            return_warehouse_id=str(warehouse['id']),return_warehouse_version=warehouse['version'],
            return_network_selection=True,paperless_requested=paperless_requested,customs_category='RETURN')
    if body.preparation_edits is not None:
        from backend.return_review import ReturnEdits
        edits = ReturnEdits.model_validate(body.preparation_edits)
        order.update(edits.model_dump(mode='json'))
        order['packages'] = [order['cargo']]
        order['multi_parcel_dimensions'] = []
    # Validate the complete edited return before any provider request. The original
    # party reversal and versioned warehouse remain server-owned.
    from backend.automation_freight_engine import Order
    try:
        order = Order.model_validate(order).model_dump(mode='json')
    except ValueError:
        raise HTTPException(422, 'Review return packing, item weights, values and customs details before comparing services') from None
    async with service.automation.order_limiter:
        result = await service.automation.process(context, order, 'QUOTE_ONLY')
    if result['status'] != 'QUOTED':
        raise HTTPException(422, result.get('error', 'Return preparation requires review'))
    if result.get('shipment_id'):
        async with service.pool.acquire() as connection:
            await connection.execute('''UPDATE public.shipments SET tracking_lifecycle_type='RETURN_SHIPMENT',
                return_of_shipment_id=$3 WHERE tenant_id=$1 AND id=$2''',
                context.tenant_id, UUID(result['shipment_id']), body.shipment_id)
    return result



def build_router(authenticate):
    router = APIRouter(prefix='/api/v1/shipping', tags=['Private partner lifecycle'])
    from backend.return_review import build_router as return_review_router
    router.include_router(return_review_router(authenticate))

    @router.post('/confirm-booking')
    async def confirm(body: BookingRequest, request: Request, context=Depends(authenticate)):
        engine = getattr(request.app.state, 'logistics_supervisor', None)
        service = request.app.state.partner_lifecycle
        result = (await engine.confirm(context, body, service) if engine is not None
                  else await service.confirm(context, body))
        if result.get('status') == 'SYNC_PENDING':
            from fastapi.responses import JSONResponse
            return JSONResponse(result, status_code=202)
        if request.headers.get('accept', '').split(';')[0].strip() == 'application/pdf':
            return await carrier_document(UUID(result['shipment_id']), 'label', request.app.state.partner_lifecycle, context)
        return result

    @router.post('/request-void')
    async def void(body: VoidRequest, request: Request, context=Depends(authenticate)):
        return await request.app.state.partner_lifecycle.void(context, body)

    @router.post('/prepare-return')
    async def prepare_return(body: ReturnRequest | list[ReturnCommand], request: Request, context=Depends(authenticate)):
        from main import validate_tenant_query
        validate_tenant_query(request, context.tenant_id)
        if isinstance(body, list):
            from backend.reverse_logistics import process_batch
            return await process_batch(request.app.state.partner_lifecycle, context, body)
        return await prepare_return_quote(request.app.state.partner_lifecycle, context, body)

    @router.get('/return-requests/{request_id}')
    async def return_status(request_id: UUID, request: Request, context=Depends(authenticate)):
        from main import validate_tenant_query
        validate_tenant_query(request, context.tenant_id)
        from backend.reverse_logistics import ReverseLogisticsService
        return await ReverseLogisticsService(request.app.state.partner_lifecycle).status(context, request_id)

    @router.get('/return-dropoff')
    async def return_dropoff(token: str, request: Request):
        from types import SimpleNamespace
        from backend.return_documents import verify_dropoff_token
        service = request.app.state.partner_lifecycle
        tenant_id, shipment_id = verify_dropoff_token(service.automation.settings, token)
        return await carrier_document(shipment_id, 'return-qr', service,
            SimpleNamespace(tenant_id=tenant_id,role='DISPATCHER'))

    @router.get('/{shipment_id}/documents/{document}')
    async def document(shipment_id: UUID, document: str, request: Request, context=Depends(authenticate)):
        return await carrier_document(shipment_id,document,request.app.state.partner_lifecycle,context)

    return router
