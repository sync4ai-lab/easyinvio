"""Shared, tenant-bound tracking projections and revocable customer capabilities.

Existing tracking receipts and shipment/return states stay authoritative. This
module never buys labels, changes a carrier scan or infers a merchandise refund.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

MILESTONES = {'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED', 'EXCEPTION', 'AVAILABLE_FOR_PICKUP',
              'RETURNED_TO_SENDER', 'CUSTOMS_PROCESSING', 'DELIVERY_ATTEMPTED', 'UNKNOWN'}
READ_ROLES = {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}
WRITE_ROLES = {'OWNER', 'ADMIN', 'DISPATCHER'}
NO_REFUND = {'status': 'UNAVAILABLE', 'message': 'A purchase refund has not been confirmed by an authorized order/payment source.'}
OFFICIAL_PORTALS={'ROYALMAIL':'https://www.royalmail.com/track-your-item','EVRI':'https://www.evri.com/track-a-parcel'}


def obj(value: Any) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def iso(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def event_detail(event) -> dict:
    return obj(obj(event.get('response')).get('tracking_detail'))


def scan_fingerprint(number: str, status: str, occurred_at: datetime) -> str:
    return hashlib.sha256(json.dumps([number, status, occurred_at.astimezone(timezone.utc).isoformat()], separators=(',', ':')).encode()).hexdigest()


def timeline_projection(events, *, platform=False):
    result, seen = [], set()
    for event in sorted(events, key=lambda row: (row['occurred_at'], str(row['id']))):
        detail = event_detail(event)
        milestone = detail.get('milestone') if detail.get('milestone') in MILESTONES else event['status']
        number = detail.get('tracking_number')
        fingerprint = scan_fingerprint(number or '', milestone, event['occurred_at'])
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append({'id': str(event['id']), 'status': milestone, 'tracking_number': number,
                       'occurred_at': iso(event['occurred_at']), 'received_at': iso(event['received_at']),
                       'applied': obj(event.get('response')).get('applied', False),
                       'source': event['integration_key_id'] if platform else 'Carrier integration',
                       'source_status': detail.get('source_status'),
                       'location': detail.get('location'), 'estimated_delivery_at': detail.get('estimated_delivery_at')})
    return result


def shipment_projection(row, events=(), *, platform=False, stale_hours=48, now=None):
    now = now or datetime.now(timezone.utc)
    metadata = obj(row.get('logistics_metadata'))
    label = obj(metadata.get('automation_label'))
    labels = label.get('package_labels') or []
    labels = labels if isinstance(labels, list) else []
    timeline = timeline_projection(events, platform=platform)
    applied = [event for event in timeline if event['applied']]
    latest = applied[-1] if applied else None
    status = row['status']
    # The persisted aggregate controls delivery, including partial multi-piece delivery.
    if latest and status not in {'DELIVERED', 'CANCELLED', 'FAILED'} and status in {'IN_TRANSIT', 'EXCEPTION'}:
        if latest['status'] != 'DELIVERED':
            status = latest['status']
    pieces = []
    numbers = [piece.get('tracking_number') for piece in labels if isinstance(piece, dict)]
    if not numbers:
        numbers = [row.get('tracking_number')] + [None] * (max(1, min(row.get('parcel_count') or 1, 100)) - 1)
    for index, number in enumerate(numbers[:100]):
        scans = [event for event in applied if number and event['tracking_number'] == number]
        recorded = obj(obj(metadata.get('package_tracking')).get(number)) if number else {}
        piece_status = scans[-1]['status'] if scans else recorded.get('status') or (row['status'] if len(numbers) == 1 else 'AWAITING_TRACKING')
        pieces.append({'index': index + 1, 'tracking_number': number, 'status': piece_status,
                       'last_event_at': scans[-1]['occurred_at'] if scans else recorded.get('occurred_at')})
    last = row.get('last_tracking_event_at')
    stale = bool(last and row['status'] in {'IN_TRANSIT', 'EXCEPTION'} and now - last > timedelta(hours=stale_hours))
    result = {'id': str(row['id']), 'order_reference': row.get('customer_reference') or row.get('store_order_id') or str(row['id']),
              'store_order_reference': row.get('store_order_id'), 'carrier': row.get('carrier_code') or 'Not recorded',
              'tracking_number': row.get('tracking_number'), 'status': status, 'shipment_status': row['status'],
              'created_at': iso(row.get('created_at')), 'last_event_at': iso(last),
              'data_state': 'STALE' if stale else 'RECORDED' if last else 'AWAITING_CARRIER_UPDATE',
              'latest_event': latest, 'parcels': pieces, 'timeline': timeline,
              'lifecycle': row.get('tracking_lifecycle_type', 'FORWARD_SHIPMENT'),
              'return_status': row.get('store_return_status', 'NONE'), 'refund': dict(NO_REFUND),
              'return_of_shipment_id': str(row['return_of_shipment_id']) if row.get('return_of_shipment_id') else None,
              'estimated_delivery_at': latest.get('estimated_delivery_at') if latest else None,
              'origin_country': row.get('origin_country'), 'destination_country': row.get('destination_country'),
              'refresh': {'state': row.get('refresh_state'), 'last_success_at': iso(row.get('last_success_at')),
                          'error_code': row.get('refresh_error')},
              'review': {'state': row.get('review_state'), 'assigned_to': str(row['assigned_to']) if row.get('assigned_to') else None}}
    result['review'].update(note=row.get('review_note'),updated_at=iso(row.get('review_updated_at')))
    from backend.carrier_consolidation import carrier_identity
    result['carrier_portal']=OFFICIAL_PORTALS.get(carrier_identity(row.get('carrier_code') or ''))
    if platform:
        result.update(tenant_id=str(row['tenant_id']), tenant_name=row.get('tenant_name'),
                      provider=row.get('aggregator'), account_id=str(row['carrier_account_id']))
    return result


@dataclass(frozen=True)
class TrackingScope:
    tenant_id: UUID | None
    actor_id: UUID
    platform: bool = False


class ShareRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    include_order: bool = False
    include_returns: bool = False
    expires_in_days: int = Field(default=7, ge=1, le=30)


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{40,100}$')


class CustomerRequest(ResolveRequest):
    request_id: UUID
    note: str = Field(min_length=10,max_length=1000)

    @field_validator('note')
    @classmethod
    def readable(cls,value):
        if any(ord(char)<32 and char not in '\n\t' for char in value) or len(value.strip())<10:
            raise ValueError('Enter a message of at least 10 readable characters')
        return value.strip()


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    in_app_enabled: bool = True
    categories: list[Literal['IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','RETURNED_TO_SENDER','AVAILABLE_FOR_PICKUP']] = Field(
        default_factory=lambda: ['IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','RETURNED_TO_SENDER'], max_length=6)
    stale_hours: int = Field(default=48, ge=12, le=720)
    poll_interval_minutes: int = Field(default=360, ge=60, le=1440)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    state: Literal['ACKNOWLEDGED','IN_REVIEW','ESCALATED','RESOLVED']
    assigned_to: UUID | None = None
    note: str = Field(min_length=1, max_length=1000)


SELECT_SHIPMENT = '''SELECT s.id,s.tenant_id,s.customer_reference,s.store_order_id,s.ecommerce_store_id,
 s.tracking_number,s.status::text AS status,s.last_tracking_event_at,s.booked_at,s.created_at,
 s.origin_country,s.destination_country,s.parcel_count,s.tracking_lifecycle_type,s.store_return_status,
 s.return_of_shipment_id,s.carrier_account_id,s.carrier_code,s.logistics_metadata,
 a.api_base_url,a.aggregator,a.is_active AS account_active,t.company_name AS tenant_name,
 j.state AS refresh_state,j.last_success_at,j.error_code AS refresh_error,
 r.state AS review_state,r.assigned_to,r.note AS review_note,r.updated_at AS review_updated_at
 FROM public.shipments s JOIN public.carrier_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.carrier_account_id
 JOIN public.tenants t ON t.tenant_id=s.tenant_id
 LEFT JOIN public.tracking_refresh_jobs j ON j.tenant_id=s.tenant_id AND j.shipment_id=s.id
 LEFT JOIN public.tracking_case_reviews r ON r.tenant_id=s.tenant_id AND r.shipment_id=s.id '''


class TrackingWorkspace:
    def __init__(self, pool, settings, *, repository=None, client=None):
        self.pool, self.settings, self.repository, self.client = pool, settings, repository, client
        self.ready = False
        self.public_limits: OrderedDict[str, tuple[float, int]] = OrderedDict()

    async def initialise(self):
        async with self.pool.acquire() as connection:
            self.ready = bool(await connection.fetchval("""SELECT bool_and(to_regclass('public.'||name) IS NOT NULL)
                FROM unnest(ARRAY['tracking_share_links','tracking_preferences','tracking_notifications','tracking_refresh_jobs',
                'tracking_provider_limits','tracking_case_reviews','tracking_customer_requests','tracking_operations_audit']) name"""))

    def require_ready(self):
        if not self.ready:
            raise HTTPException(503, 'Tracking workspace requires migration 045. Existing booking and carrier webhooks remain available.')

    async def audit(self, connection, scope, action, shipment_id=None, detail=None):
        await connection.execute('''INSERT INTO public.tracking_operations_audit(tenant_id,actor_auth_user_id,shipment_id,action,detail)
            VALUES($1,$2,$3,$4,$5::jsonb)''', scope.tenant_id, scope.actor_id, shipment_id, action, json.dumps(detail or {}))

    async def preferences(self, connection, tenant_id):
        row = await connection.fetchrow('SELECT in_app_enabled,categories,stale_hours,poll_interval_minutes FROM public.tracking_preferences WHERE tenant_id=$1', tenant_id)
        return Preferences.model_validate(dict(row)) if row else Preferences()

    async def row(self, connection, scope, shipment_id):
        if scope.tenant_id is None and not scope.platform:
            raise HTTPException(403, 'A workspace scope is required')
        row = await connection.fetchrow(SELECT_SHIPMENT + ' WHERE s.id=$1 AND ($2::uuid IS NULL OR s.tenant_id=$2)', shipment_id, scope.tenant_id)
        if row is None:
            raise HTTPException(404, 'Shipment not found')
        return row

    async def detail(self, scope, shipment_id, *, audit=True):
        self.require_ready()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                anchor = await self.row(connection, scope, shipment_id)
                tenant_id = anchor['tenant_id']
                siblings = await connection.fetch(SELECT_SHIPMENT + ''' WHERE s.tenant_id=$1 AND
                    (s.id=$2 OR ($3::uuid IS NOT NULL AND $4::text IS NOT NULL AND s.ecommerce_store_id=$3 AND s.store_order_id=$4 AND s.tracking_lifecycle_type=$5))
                    ORDER BY s.created_at,s.id LIMIT 101''', tenant_id, shipment_id, anchor.get('ecommerce_store_id'), anchor.get('store_order_id'),anchor['tracking_lifecycle_type'])
                if len(siblings) > 100:
                    raise HTTPException(409, 'This order requires a paginated operational review')
                ids = [item['id'] for item in siblings]
                returns = await connection.fetch(SELECT_SHIPMENT + ' WHERE s.tenant_id=$1 AND s.return_of_shipment_id=ANY($2::uuid[]) ORDER BY s.created_at,s.id LIMIT 101', tenant_id, ids)
                if len(returns) > 100:
                    raise HTTPException(409, 'This return group requires a paginated operational review')
                all_rows = {item['id']: item for item in [*siblings, *returns]}
                events = await connection.fetch('''SELECT * FROM public.tracking_events WHERE tenant_id=$1 AND shipment_id=ANY($2::uuid[])
                    ORDER BY occurred_at,id LIMIT 5001''', tenant_id, list(all_rows))
                if len(events) > 5000:
                    raise HTTPException(409, 'This timeline exceeds the interactive limit; request an operational export')
                pref = await self.preferences(connection, tenant_id)
                projected = {key: shipment_projection(value, [e for e in events if e['shipment_id'] == key], platform=scope.platform,
                                                     stale_hours=pref.stale_hours) for key, value in all_rows.items()}
                from backend.integration_policy import integration_enabled
                for key,item in projected.items():
                    row=all_rows[key]
                    item['refresh']['available']=bool(getattr(self.settings,'tracking_polling_enabled',False) and row['account_active']
                        and row['api_base_url']=='https://api.easypost.com/v2' and integration_enabled(row['api_base_url'],self.settings)
                        and row['status'] in {'BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION'})
                if audit:
                    await self.audit(connection, TrackingScope(tenant_id, scope.actor_id, scope.platform), 'DETAIL', shipment_id)
                customer_requests=await connection.fetch('''SELECT id,shipment_id,note,state,created_at FROM public.tracking_customer_requests
                    WHERE tenant_id=$1 AND shipment_id=ANY($2::uuid[]) ORDER BY created_at DESC LIMIT 100''',tenant_id,list(all_rows))
                return {'anchor_id': str(shipment_id), 'order_reference': projected[shipment_id]['order_reference'],
                        'group_basis': 'VERIFIED_STORE_ORDER' if anchor.get('ecommerce_store_id') and anchor.get('store_order_id') else 'SHIPMENT',
                        'shipments': [projected[item['id']] for item in siblings],
                        'returns': [projected[item['id']] for item in returns if item['id'] not in ids],
                        'refund': dict(NO_REFUND), 'customer_requests':[dict(row) for row in customer_requests], 'tracking_included': True}

    async def search(self, scope, *, q='', view='all', carrier='', country='', start=None, end=None, page=1):
        self.require_ready()
        if scope.tenant_id is None and not scope.platform:
            raise HTTPException(403, 'A workspace scope is required')
        q = q.strip()
        if len(q) > 120 or any(ord(char) < 32 for char in q):
            raise HTTPException(422, 'Search must contain at most 120 printable characters')
        end = end or datetime.now(timezone.utc).date()
        start = start or end - timedelta(days=89)
        if end < start or (end-start).days > 365:
            raise HTTPException(422, 'Choose a reporting range of at most 366 days')
        if view not in {'all','IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','STALE','RETURNS','CUSTOMER_REQUESTS'}:
            raise HTTPException(422, 'Unsupported tracking filter')
        prefix = q.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        where = ''' WHERE ($1::uuid IS NULL OR s.tenant_id=$1) AND s.created_at>=$2 AND s.created_at<$3
          AND ($4='' OR lower(coalesce(s.customer_reference,'')) LIKE $5 OR lower(coalesce(s.tracking_number,'')) LIKE $5
            OR lower(coalesce(s.store_order_id,'')) LIKE $5 OR s.id::text=$4
            OR EXISTS(SELECT 1 FROM public.ecommerce_tracking_outbox x WHERE x.tenant_id=s.tenant_id AND x.shipment_id=s.id AND x.store_return_reference=$4)
            OR s.logistics_metadata->'automation_label'->'package_labels' @> jsonb_build_array(jsonb_build_object('tracking_number',$4::text)))
          AND ($6='' OR upper(s.carrier_code)=$6) AND ($7='' OR s.destination_country=$7)'''
        args = (scope.tenant_id, datetime.combine(start, datetime.min.time(), timezone.utc),
                datetime.combine(end+timedelta(days=1), datetime.min.time(), timezone.utc), q, prefix, carrier.upper(), country.upper())
        lateral = ''' LEFT JOIN LATERAL (SELECT e.occurred_at,coalesce(e.response->'tracking_detail'->>'milestone',e.status) AS milestone
          FROM public.tracking_events e WHERE e.tenant_id=s.tenant_id AND e.shipment_id=s.id AND e.response->>'applied'='true'
          ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1) latest ON true
          LEFT JOIN public.tracking_preferences p ON p.tenant_id=s.tenant_id '''
        stale = "(s.status::text IN ('IN_TRANSIT','EXCEPTION') AND s.last_tracking_event_at<now()-make_interval(hours=>coalesce(p.stale_hours,48)))"
        conditions = {'all': 'true', 'STALE': stale, 'RETURNS': "s.tracking_lifecycle_type='RETURN_SHIPMENT' AND s.store_return_status NOT IN ('RECEIVED','RESOLVED')",
                      'CUSTOMER_REQUESTS':"EXISTS(SELECT 1 FROM public.tracking_customer_requests c WHERE c.tenant_id=s.tenant_id AND c.shipment_id=s.id AND c.state='OPEN')",
                      'OUT_FOR_DELIVERY': "s.status::text<>'DELIVERED' AND latest.milestone='OUT_FOR_DELIVERY'"}
        condition = conditions.get(view, "s.status::text='" + view + "'")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                counts = await connection.fetchrow('''SELECT count(*)::int AS total,
                  count(*) FILTER(WHERE s.status::text='IN_TRANSIT')::int AS in_transit,
                  count(*) FILTER(WHERE s.status::text<>'DELIVERED' AND latest.milestone='OUT_FOR_DELIVERY')::int AS out_for_delivery,
                  count(*) FILTER(WHERE s.status::text='DELIVERED')::int AS delivered,
                  count(*) FILTER(WHERE s.status::text='EXCEPTION')::int AS exceptions,
                  count(*) FILTER(WHERE EXISTS(SELECT 1 FROM public.tracking_customer_requests c WHERE c.tenant_id=s.tenant_id AND c.shipment_id=s.id AND c.state='OPEN'))::int AS customer_requests,
                  count(*) FILTER(WHERE '''+stale+''')::int AS stale,
                  count(*) FILTER(WHERE s.tracking_lifecycle_type='RETURN_SHIPMENT' AND s.store_return_status NOT IN ('RECEIVED','RESOLVED'))::int AS returns
                  FROM public.shipments s '''+lateral+where, *args)
                rows = await connection.fetch(SELECT_SHIPMENT+lateral+where+' AND ('+condition+''')
                  ORDER BY CASE WHEN s.customer_reference=$4 OR s.tracking_number=$4 OR s.store_order_id=$4 OR s.id::text=$4 THEN 0 ELSE 1 END,
                    s.created_at DESC,s.id LIMIT 51 OFFSET $8''', *args, (page-1)*50)
                await self.audit(connection, scope, 'SEARCH', detail={'query_sha256': hashlib.sha256(q.encode()).hexdigest(), 'view': view, 'start': start.isoformat(), 'end': end.isoformat(), 'page': page})
                row_ids=[row['id'] for row in rows[:50]]
                latest_events=await connection.fetch('''SELECT DISTINCT ON(tenant_id,shipment_id) * FROM public.tracking_events
                    WHERE ($1::uuid IS NULL OR tenant_id=$1) AND shipment_id=ANY($2::uuid[]) AND response->>'applied'='true'
                    ORDER BY tenant_id,shipment_id,occurred_at DESC,id DESC''',scope.tenant_id,row_ids)
                preference_rows=await connection.fetch('SELECT tenant_id,stale_hours FROM public.tracking_preferences WHERE tenant_id=ANY($1::uuid[])',list({row['tenant_id'] for row in rows[:50]}))
                thresholds={row['tenant_id']:row['stale_hours'] for row in preference_rows}
                projected = []
                for row in rows[:50]:
                    latest=[event for event in latest_events if event['shipment_id']==row['id'] and event['tenant_id']==row['tenant_id']]
                    projected.append(shipment_projection(row, latest, platform=scope.platform, stale_hours=thresholds.get(row['tenant_id'],48)))
                return {'shipments': projected, 'counts': dict(counts), 'has_more': len(rows)>50, 'page': page,
                        'period': {'start': start.isoformat(), 'end': end.isoformat()}, 'refund_status': 'UNAVAILABLE', 'tracking_included': True}

    async def record_event(self, connection, key_id, key, event, result):
        """Called within the existing ingest transaction, after its receipt INSERT."""
        if not result['applied']:
            return
        pref = await self.preferences(connection, key.tenant_id)
        category = event.milestone or event.status
        if not pref.in_app_enabled or category not in pref.categories:
            return
        await connection.execute('''INSERT INTO public.tracking_notifications(tenant_id,shipment_id,tracking_event_id,event_sha256,category)
          SELECT tenant_id,shipment_id,id,$4,$5 FROM public.tracking_events
          WHERE tenant_id=$1 AND integration_key_id=$2 AND event_id=$3
          ON CONFLICT(tenant_id,event_sha256) DO NOTHING''', key.tenant_id, key_id, event.event_id,
          scan_fingerprint(event.tracking_number, category, event.scan_occurred_at or event.occurred_at), category)

    async def share(self, scope, shipment_id, body):
        from urllib.parse import urlsplit
        parsed=urlsplit(self.settings.booking_page_url or self.settings.auth_recovery_redirect_url)
        if parsed.scheme not in {'https','http'} or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(503,'Configure the public application origin before sharing tracking')
        if parsed.scheme!='https' and parsed.hostname not in {'localhost','127.0.0.1'}:
            raise HTTPException(503,'Public tracking requires HTTPS')
        origin=f'{parsed.scheme}://{parsed.netloc}'
        detail = await self.detail(scope, shipment_id)
        candidates = detail['shipments'] if body.include_order else [item for item in detail['shipments'] if item['id']==str(shipment_id)]
        if not any(item['id']==str(shipment_id) and item['shipment_status'] in {'BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','DELIVERED','EXCEPTION','CANCELLED'} for item in candidates):
            raise HTTPException(409,'A customer tracking link requires a confirmed shipment')
        candidates=[item for item in candidates if item['shipment_status'] in {'BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','DELIVERED','EXCEPTION','CANCELLED'}]
        ids = [UUID(item['id']) for item in candidates]
        if body.include_returns:
            ids += [UUID(item['id']) for item in detail['returns'] if item['return_of_shipment_id'] in {str(value) for value in ids}]
        ids = list(dict.fromkeys(ids))
        if not 1 <= len(ids) <= 100:
            raise HTTPException(409, 'Share at most 100 shipment records')
        token = secrets.token_urlsafe(32)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                anchor = await self.row(connection, scope, shipment_id)
                count = await connection.fetchval('SELECT count(*) FROM public.shipments WHERE tenant_id=$1 AND id=ANY($2::uuid[])', anchor['tenant_id'], ids)
                if count != len(ids):
                    raise HTTPException(409, 'Share membership changed; refresh the order')
                await connection.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'tracking-share:{anchor["tenant_id"]}:{shipment_id}')
                active_count=await connection.fetchval('SELECT count(*) FROM public.tracking_share_links WHERE tenant_id=$1 AND anchor_shipment_id=$2 AND revoked_at IS NULL AND expires_at>now()',anchor['tenant_id'],shipment_id)
                if active_count>=20:raise HTTPException(429,'This shipment already has 20 active tracking links. Revoke unused links before issuing another.')
                row = await connection.fetchrow('''INSERT INTO public.tracking_share_links(tenant_id,anchor_shipment_id,shipment_ids,token_sha256,created_by,expires_at)
                   VALUES($1,$2,$3,$4,$5,now()+make_interval(days=>$6)) RETURNING id,expires_at''', anchor['tenant_id'], shipment_id, ids, hashlib.sha256(token.encode()).hexdigest(), scope.actor_id, body.expires_in_days)
                await self.audit(connection, TrackingScope(anchor['tenant_id'],scope.actor_id,scope.platform), 'SHARE', shipment_id, {'share_id': str(row['id']), 'records': len(ids)})
        return {'id': str(row['id']), 'url': f'{origin}/track#{token}', 'expires_at': row['expires_at'].isoformat()}

    def public_rate_limit(self, client: str):
        now = time.monotonic()
        key = hashlib.sha256(client.encode()).hexdigest()
        started, count = self.public_limits.pop(key, (now, 0))
        if now-started >= 60:
            started, count = now, 0
        self.public_limits[key] = (started, count+1)
        while len(self.public_limits)>2048:
            self.public_limits.popitem(last=False)
        if count>=30:
            raise HTTPException(429, 'Too many tracking requests; please wait a minute', headers={'Retry-After':'60'})

    async def resolve(self, token):
        self.require_ready()
        async with self.pool.acquire() as connection:
            link = await connection.fetchrow('''SELECT tenant_id,anchor_shipment_id,shipment_ids FROM public.tracking_share_links
                WHERE token_sha256=$1 AND revoked_at IS NULL AND expires_at>now()''', hashlib.sha256(token.encode()).hexdigest())
            if link is None:
                raise HTTPException(404, 'This tracking link is unavailable or has expired. Request a new link from the retailer.')
            rows = await connection.fetch(SELECT_SHIPMENT+' WHERE s.tenant_id=$1 AND s.id=ANY($2::uuid[]) ORDER BY s.created_at,s.id', link['tenant_id'],link['shipment_ids'])
            if len(rows)!=len(link['shipment_ids']):
                raise HTTPException(404, 'This tracking link is unavailable. Contact the retailer.')
            events = await connection.fetch('''SELECT * FROM public.tracking_events WHERE tenant_id=$1 AND shipment_id=ANY($2::uuid[])
                ORDER BY occurred_at,id LIMIT 5001''',link['tenant_id'],link['shipment_ids'])
            if len(events)>5000:
                raise HTTPException(503, 'This tracking history requires retailer assistance')
            visible = []
            for row in rows:
                item = shipment_projection(row,[event for event in events if event['shipment_id']==row['id']])
                allowed_event={'status','tracking_number','occurred_at','received_at','applied','location'}
                item['timeline']=[{key:value for key,value in event.items() if key in allowed_event} for event in item['timeline']]
                if item['latest_event']:item['latest_event']={key:value for key,value in item['latest_event'].items() if key in allowed_event}
                # Explicit allowlist: no internal IDs, country/address/contact, financial,
                # review, sync, provider URL or account fields cross the public boundary.
                visible.append({key:item[key] for key in ('order_reference','carrier','carrier_portal','tracking_number','status','data_state','latest_event','parcels','timeline','lifecycle','return_status','estimated_delivery_at')})
            whatsapp_number=getattr(self.settings,'twilio_whatsapp_number','')
            whatsapp={'number':whatsapp_number,'sandbox':bool(getattr(self.settings,'twilio_whatsapp_sandbox_enabled',False))} if getattr(self.settings,'twilio_enabled',False) and re.fullmatch(r'\+[1-9][0-9]{7,14}',whatsapp_number) else None
            return {'shipments':visible,'tracking_included':True,'whatsapp':whatsapp,
                    'support_message':'For delivery changes, returns or refund help, contact the retailer using your order confirmation.'}

    async def chat(self, context, reference):
        scope=TrackingScope(context.tenant_id,context.user_id)
        async with self.pool.acquire() as connection:
            exact=await connection.fetch('''SELECT id,ecommerce_store_id,store_order_id FROM public.shipments s WHERE tenant_id=$1
                AND (s.id::text=$2 OR s.customer_reference=$2 OR s.tracking_number=$2 OR s.store_order_id=$2
                OR s.logistics_metadata->'automation_label'->'package_labels' @> jsonb_build_array(jsonb_build_object('tracking_number',$2::text)))
                ORDER BY created_at,id LIMIT 101''',scope.tenant_id,reference)
        same_store_order=bool(exact and exact[0]['ecommerce_store_id'] and exact[0]['store_order_id'] and
            all((item['ecommerce_store_id'],item['store_order_id'])==(exact[0]['ecommerce_store_id'],exact[0]['store_order_id']) for item in exact))
        if not exact or len(exact)>100 or (len(exact)>1 and not same_store_order):
            raise HTTPException(404,'Please provide a unique shipment, tracking or storefront order reference from your workspace')
        detail=await self.detail(scope,exact[0]['id'])
        lines=[]
        for item in detail['shipments']:
            line=f"{item['order_reference']}: {item['status'].replace('_',' ').lower()}."
            if item['last_event_at']:line+=' Last carrier update: '+item['last_event_at']+'.'
            else:line+=' No carrier scan has been recorded yet.'
            if item['data_state']=='STALE':line+=' Tracking needs a fresh carrier update; a delay is not confirmed.'
            if item['lifecycle']=='RETURN_SHIPMENT':line+=' Return status: '+item['return_status'].replace('_',' ').lower()+'.'
            lines.append(line)
        if detail['returns']:lines.append('Returns: '+', '.join(item['return_status'] for item in detail['returns'])+'.')
        lines.append(NO_REFUND['message'])
        return '\n'.join(lines)

    async def customer_request(self,body):
        self.require_ready()
        digest=hashlib.sha256(body.note.encode()).hexdigest()
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                link=await connection.fetchrow('''SELECT id,tenant_id,anchor_shipment_id FROM public.tracking_share_links
                    WHERE token_sha256=$1 AND revoked_at IS NULL AND expires_at>now() FOR UPDATE''',hashlib.sha256(body.token.encode()).hexdigest())
                if link is None:raise HTTPException(404,'This tracking link is unavailable or expired')
                previous=await connection.fetchrow('SELECT id,input_sha256 FROM public.tracking_customer_requests WHERE share_link_id=$1 AND request_id=$2',link['id'],body.request_id)
                if previous:
                    if previous['input_sha256']!=digest:raise HTTPException(409,'Request reference was already used for different content')
                    return {'status':'RECEIVED','request_id':str(previous['id']),'replayed':True}
                count=await connection.fetchval("SELECT count(*) FROM public.tracking_customer_requests WHERE share_link_id=$1 AND created_at>now()-interval '1 day'",link['id'])
                if count>=3:raise HTTPException(429,'Three requests have already been recorded on this link today. Contact the retailer directly.')
                request_id=await connection.fetchval('''INSERT INTO public.tracking_customer_requests(tenant_id,shipment_id,share_link_id,request_id,input_sha256,note)
                    VALUES($1,$2,$3,$4,$5,$6) RETURNING id''',link['tenant_id'],link['anchor_shipment_id'],link['id'],body.request_id,digest,body.note)
        return {'status':'RECEIVED','request_id':str(request_id),'replayed':False,
                'message':'Your request is available to the retailer team. No delivery change or purchase refund has been made.'}


def build_router(authenticate, authenticate_platform_owner):
    class TrackingRoute(APIRoute):
        def get_route_handler(self):
            original=super().get_route_handler()
            async def handler(request):
                try:return await original(request)
                except asyncpg.PostgresError:
                    raise HTTPException(503,'Tracking data is temporarily unavailable; existing shipment and payment states are unchanged') from None
            return handler
    router=APIRouter(tags=['Unified tracking'],route_class=TrackingRoute)

    def service(request):
        instance=getattr(request.app.state,'tracking_workspace',None)
        if instance is None:raise HTTPException(503,'Tracking workspace is not configured')
        instance.require_ready()
        return instance

    def scope(context, write=False):
        if context.role not in (WRITE_ROLES if write else READ_ROLES):raise HTTPException(403,'Tracking permission required')
        return TrackingScope(context.tenant_id,context.user_id)

    @router.get('/api/v1/tracking/shipments')
    async def shipments(request:Request,q:str='',view:str='all',carrier:str=Query('',max_length=50),country:str=Query('',max_length=2),
                        start:date|None=None,end:date|None=None,page:int=Query(1,ge=1,le=10000),context=Depends(authenticate)):
        return await service(request).search(scope(context),q=q,view=view,carrier=carrier,country=country,start=start,end=end,page=page)

    @router.get('/api/v1/admin/tracking/shipments')
    async def global_shipments(request:Request,tenant_id:UUID|None=None,q:str='',view:str='all',carrier:str=Query('',max_length=50),
                              country:str=Query('',max_length=2),start:date|None=None,end:date|None=None,
                              page:int=Query(1,ge=1,le=10000),actor=Depends(authenticate_platform_owner)):
        return await service(request).search(TrackingScope(tenant_id,actor.user_id,True),q=q,view=view,carrier=carrier,country=country,start=start,end=end,page=page)

    @router.get('/api/v1/tracking/shipments/{shipment_id}')
    async def detail(shipment_id:UUID,request:Request,context=Depends(authenticate)):
        return await service(request).detail(scope(context),shipment_id)

    @router.get('/api/v1/admin/tracking/shipments/{shipment_id}')
    async def admin_detail(shipment_id:UUID,request:Request,actor=Depends(authenticate_platform_owner)):
        return await service(request).detail(TrackingScope(None,actor.user_id,True),shipment_id)

    @router.post('/api/v1/tracking/shipments/{shipment_id}/share')
    async def share(shipment_id:UUID,body:ShareRequest,request:Request,context=Depends(authenticate)):
        return await service(request).share(scope(context,True),shipment_id,body)

    @router.delete('/api/v1/tracking/share-links/{share_id}')
    async def revoke(share_id:UUID,request:Request,context=Depends(authenticate)):
        current=scope(context,True);engine=service(request)
        async with engine.pool.acquire() as connection:
            async with connection.transaction():
                row=await connection.fetchrow('''UPDATE public.tracking_share_links SET revoked_at=coalesce(revoked_at,now())
                   WHERE tenant_id=$1 AND id=$2 RETURNING anchor_shipment_id''',current.tenant_id,share_id)
                if row is None:raise HTTPException(404,'Tracking link not found')
                await engine.audit(connection,current,'REVOKE',row['anchor_shipment_id'],{'share_id':str(share_id)})
        return {'revoked':True}

    @router.get('/api/v1/tracking/shipments/{shipment_id}/share-links')
    async def shares(shipment_id:UUID,request:Request,context=Depends(authenticate)):
        engine=service(request);current=scope(context,True)
        async with engine.pool.acquire() as connection:
            await engine.row(connection,current,shipment_id)
            rows=await connection.fetch('SELECT id,created_at,expires_at,revoked_at FROM public.tracking_share_links WHERE tenant_id=$1 AND anchor_shipment_id=$2 ORDER BY created_at DESC LIMIT 100',current.tenant_id,shipment_id)
        return {'links':[dict(row) for row in rows]}

    @router.post('/api/v1/public/tracking/resolve',openapi_extra={'requestBody':{'required':True,'content':{'application/json':{'schema':ResolveRequest.model_json_schema()}}}})
    async def public_tracking(request:Request,response:Response):
        engine=service(request)
        engine.public_rate_limit(request.client.host if request.client else 'unknown')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>4096:raise HTTPException(413,'Tracking request exceeds 4 KB')
        try:body=ResolveRequest.model_validate_json(raw)
        except ValueError:raise HTTPException(422,'Use the complete tracking capability from your retailer') from None
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})
        return await engine.resolve(body.token)

    @router.post('/api/v1/public/tracking/help',status_code=202,openapi_extra={'requestBody':{'required':True,'content':{'application/json':{'schema':CustomerRequest.model_json_schema()}}}})
    async def public_help(request:Request,response:Response):
        engine=service(request);engine.public_rate_limit(request.client.host if request.client else 'unknown')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>4096:raise HTTPException(413,'Tracking request exceeds 4 KB')
        try:body=CustomerRequest.model_validate_json(raw)
        except ValueError:raise HTTPException(422,'Provide a valid tracking link, request reference and message') from None
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
        return await engine.customer_request(body)

    @router.get('/api/v1/tracking/preferences')
    async def get_preferences(request:Request,context=Depends(authenticate)):
        current=scope(context);engine=service(request)
        async with engine.pool.acquire() as connection:pref=await engine.preferences(connection,current.tenant_id)
        return {'preferences':pref.model_dump(),'channels':{'IN_APP':'AVAILABLE','WHATSAPP':'EXISTING_OPT_IN_SUPPORT_ALERTS_ONLY','SMS':'NOT_CONFIGURED','EMAIL':'NOT_CONFIGURED'},
                'refresh_enabled':bool(getattr(engine.settings,'tracking_polling_enabled',False)),
                'commercial_policy':'Tracking visibility is included. No new paid messages are sent by this workspace.'}

    @router.put('/api/v1/tracking/preferences')
    async def put_preferences(body:Preferences,request:Request,context=Depends(authenticate)):
        current=scope(context,True);engine=service(request)
        if context.role not in {'OWNER','ADMIN'}:raise HTTPException(403,'Owner or admin permission required')
        async with engine.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute('''INSERT INTO public.tracking_preferences(tenant_id,in_app_enabled,categories,stale_hours,poll_interval_minutes,updated_by)
                  VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(tenant_id) DO UPDATE SET in_app_enabled=$2,categories=$3,stale_hours=$4,poll_interval_minutes=$5,updated_by=$6,updated_at=now()''',
                  current.tenant_id,body.in_app_enabled,body.categories,body.stale_hours,body.poll_interval_minutes,current.actor_id)
                await engine.audit(connection,current,'PREFERENCES',detail=body.model_dump())
        return body

    @router.get('/api/v1/tracking/notifications')
    async def notifications(request:Request,context=Depends(authenticate)):
        engine=service(request);current=scope(context)
        async with engine.pool.acquire() as connection:
            rows=await connection.fetch('''SELECT n.id,n.shipment_id,n.category,n.created_at,s.customer_reference FROM public.tracking_notifications n
               JOIN public.shipments s ON s.tenant_id=n.tenant_id AND s.id=n.shipment_id WHERE n.tenant_id=$1 ORDER BY n.created_at DESC LIMIT 50''',current.tenant_id)
        return {'notifications':[dict(row) for row in rows]}

    async def review_action(engine,current,shipment_id,body):
        async with engine.pool.acquire() as connection:
            async with connection.transaction():
                row=await engine.row(connection,current,shipment_id)
                current=TrackingScope(row['tenant_id'],current.actor_id,current.platform)
                if body.assigned_to and not await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.users WHERE tenant_id=$1 AND auth_user_id=$2 AND is_active)',current.tenant_id,body.assigned_to):
                    raise HTTPException(422,'Assign a current member of this workspace')
                await connection.execute('''INSERT INTO public.tracking_case_reviews(tenant_id,shipment_id,state,assigned_to,note,updated_by)
                 VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(tenant_id,shipment_id) DO UPDATE SET state=$3,assigned_to=$4,note=$5,updated_by=$6,updated_at=now()''',
                 current.tenant_id,shipment_id,body.state,body.assigned_to,body.note,current.actor_id)
                await engine.audit(connection,current,'REVIEW',shipment_id,body.model_dump(mode='json'))
                await connection.execute("UPDATE public.tracking_customer_requests SET state='ACKNOWLEDGED',acknowledged_at=now() WHERE tenant_id=$1 AND shipment_id=$2 AND state='OPEN'",current.tenant_id,shipment_id)
        return {'review_state':body.state,'carrier_status_changed':False}

    @router.post('/api/v1/tracking/shipments/{shipment_id}/review')
    async def review(shipment_id:UUID,body:ReviewRequest,request:Request,context=Depends(authenticate)):
        return await review_action(service(request),scope(context,True),shipment_id,body)

    @router.post('/api/v1/admin/tracking/shipments/{shipment_id}/review')
    async def global_review(shipment_id:UUID,body:ReviewRequest,request:Request,actor=Depends(authenticate_platform_owner)):
        return await review_action(service(request),TrackingScope(None,actor.user_id,True),shipment_id,body)

    @router.post('/api/v1/tracking/shipments/{shipment_id}/refresh',status_code=202)
    async def refresh(shipment_id:UUID,request:Request,context=Depends(authenticate)):
        from backend.tracking_refresh import TrackingRefreshWorker
        return await TrackingRefreshWorker(service(request),request.app.state.tracking_support).enqueue(scope(context,True),shipment_id)

    @router.post('/api/v1/admin/tracking/shipments/{shipment_id}/refresh',status_code=202)
    async def global_refresh(shipment_id:UUID,request:Request,actor=Depends(authenticate_platform_owner)):
        from backend.tracking_refresh import TrackingRefreshWorker
        return await TrackingRefreshWorker(service(request),request.app.state.tracking_support).enqueue(TrackingScope(None,actor.user_id,True),shipment_id)

    @router.post('/api/v1/admin/tracking/shipments/{shipment_id}/retry',status_code=202)
    async def global_retry(shipment_id:UUID,request:Request,actor=Depends(authenticate_platform_owner)):
        from backend.tracking_refresh import TrackingRefreshWorker
        return await TrackingRefreshWorker(service(request),request.app.state.tracking_support).enqueue(TrackingScope(None,actor.user_id,True),shipment_id,retry=True)

    @router.get('/api/v1/admin/tracking/health')
    async def health(request:Request,actor=Depends(authenticate_platform_owner)):
        engine=service(request)
        async with engine.pool.acquire() as connection:
            async with connection.transaction():
                counts=await connection.fetch('SELECT state,count(*)::int AS count FROM public.tracking_refresh_jobs GROUP BY state')
                jobs=await connection.fetch('''SELECT j.tenant_id,j.shipment_id,j.state,j.attempts,j.error_code,j.last_success_at,j.next_attempt_at,t.company_name
                    FROM public.tracking_refresh_jobs j JOIN public.tenants t ON t.tenant_id=j.tenant_id
                    WHERE j.error_code IS NOT NULL ORDER BY j.updated_at DESC LIMIT 50''')
                await engine.audit(connection,TrackingScope(None,actor.user_id,True),'SEARCH',detail={'health':True})
        return {'jobs':[dict(row) for row in jobs],'counts':{row['state']:row['count'] for row in counts},
                'polling_enabled':bool(getattr(engine.settings,'tracking_polling_enabled',False)),
                'webhook_failure_history':'Signature rejections are not persisted as shipment events. Existing provider and support queues remain separate.'}

    @router.get('/api/v1/tracking/capabilities')
    async def capabilities(request:Request,context=Depends(authenticate)):
        from backend.tracking_refresh import CAPABILITIES
        from backend.integration_policy import integration_enabled
        current=scope(context);engine=service(request)
        async with engine.pool.acquire() as connection:
            rows=await connection.fetch('SELECT id,aggregator,api_base_url,is_active,environment FROM public.carrier_accounts WHERE tenant_id=$1 ORDER BY id',current.tenant_id)
        return {'connections':[{'id':str(row['id']),'provider':row['aggregator'],'environment':row['environment'],
            'enabled':bool(row['is_active'] and integration_enabled(row['api_base_url'],engine.settings)),
            'signed_webhook_adapter':bool(CAPABILITIES.get(row['api_base_url'])),
            'polling_adapter':bool(CAPABILITIES.get(row['api_base_url']) and CAPABILITIES[row['api_base_url']].polling),
            'tracking_api_cost':None,'cost_verification':'VERIFY_ACCOUNT_CONTRACT','call_quota':None} for row in rows],
            'tracking_included':True,'refund_feed':'NOT_CONNECTED','paid_notifications':'NO_NEW_DISPATCH_ENABLED'}

    return router
