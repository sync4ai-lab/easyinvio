"""Durable outbound delivery. Native uncertain sends require reconciliation;
bridge callbacks retry with a stable event ID that the receiver must deduplicate.
"""
from __future__ import annotations
import json
from typing import Any
from uuid import UUID
import httpx
from fastapi import HTTPException
from backend.platform_registry import NATIVE, REST_PLATFORMS
from backend.store_connections import resolve_connector

def adapter_for(service: Any, config: Any) -> Any:
    if config.platform=='SHOPIFY':
        from backend.ecommerce_connectors import ShopifyFulfillment
        return ShopifyFulfillment(service.client,config)
    if config.platform in REST_PLATFORMS:
        from backend.store_rest import RestStoreAdapter
        return RestStoreAdapter(service.client,config)
    raise HTTPException(409,'This platform requires signed bridge callback delivery')

async def deliver_tracking(service: Any, tenant_id: UUID, store_order_id: str,
                           tracking_number: str, carrier_name: str) -> None:
    async with service.pool.acquire() as c:
        rows=await c.fetch('''SELECT o.*,s.platform FROM public.ecommerce_tracking_outbox o
            JOIN public.ecommerce_stores s ON s.tenant_id=o.tenant_id AND s.id=o.store_id
            WHERE o.tenant_id=$1 AND o.store_order_id=$2 AND s.is_active
              ORDER BY o.id''',tenant_id,store_order_id)
    matched=False
    for row in rows:
        body=json.loads(row['payload']) if isinstance(row['payload'],str) else dict(row['payload'])
        if body['tracking_number']!=tracking_number or body['carrier_name']!=carrier_name: continue
        matched=True
        if row['status'] not in {'PENDING','RECONCILIATION_REQUIRED'}: continue
        config=await resolve_connector(service,row['store_id'])
        if config and (config.tenant_id!=tenant_id or config.platform!=row['platform']):
            raise HTTPException(409,'Store configuration identity mismatch')
        bridge=bool(config and config.platform not in NATIVE)
        if row.get('tracking_lifecycle_type','FORWARD_SHIPMENT')!='FORWARD_SHIPMENT' and not bridge: continue
        if row['status']=='RECONCILIATION_REQUIRED' and not bridge: continue
        enabled=bool(config and config.live_delivery)
        # Missing settings is fail-closed, never an implicit TEST environment.
        environment=getattr(service.settings,'provider_environment',None)
        if not enabled:
            async with service.pool.acquire() as c:
                if environment=='TEST' and row['status']=='PENDING':
                    await c.execute("UPDATE public.ecommerce_tracking_outbox SET status='SIMULATED_DELIVERED',attempts=attempts+1,response=$3::jsonb WHERE tenant_id=$1 AND id=$2 AND status='PENDING'",tenant_id,row['id'],json.dumps({'simulated':True}))
                elif row['status']=='PENDING':
                    await c.execute("UPDATE public.ecommerce_tracking_outbox SET store_sync_error_code='LIVE_DELIVERY_DISABLED',next_attempt_at=now()+interval '10 minutes' WHERE tenant_id=$1 AND id=$2",tenant_id,row['id'])
            continue
        if service.client is None: raise HTTPException(503,'Store delivery client unavailable')
        if row.get('attempts',0)>=30: continue
        # Claim BEFORE network I/O. A callback's lease permits safe retry by event ID.
        async with service.pool.acquire() as c:
            claimed=await c.fetchval("""UPDATE public.ecommerce_tracking_outbox SET status='RECONCILIATION_REQUIRED',
                attempts=attempts+1,store_sync_error_code=$3,next_attempt_at=now()+interval '5 minutes'
                WHERE tenant_id=$1 AND id=$2 AND attempts<30 AND next_attempt_at<=now()
                  AND (status='PENDING' OR ($4 AND status='RECONCILIATION_REQUIRED'
                    AND store_sync_error_code IN ('CALLBACK_RETRY','RETURN_ADAPTER_UPGRADE_REQUIRED'))) RETURNING id""",tenant_id,row['id'],
                    'CALLBACK_RETRY' if bridge else 'NATIVE_SUBMITTED',bridge)
        if not claimed: continue
        body['event_id']=str(row['id'])
        try:
            if bridge:
                from backend.custom_stores import callback
                result=await callback(service.client,config,row['store_id'],body)
            else: result=await adapter_for(service,config).deliver(body)
        except (httpx.HTTPError,HTTPException,ValueError,KeyError,TypeError):
            continue
        async with service.pool.acquire() as c:
            async with c.transaction():
                await c.execute("""UPDATE public.ecommerce_tracking_outbox SET status='DELIVERED',
                    delivered_at=now(),response=$3::jsonb,store_sync_error_code=NULL
                    WHERE tenant_id=$1 AND id=$2 AND status='RECONCILIATION_REQUIRED'""",tenant_id,row['id'],json.dumps(result))
                if row.get('tracking_lifecycle_type','FORWARD_SHIPMENT')=='FORWARD_SHIPMENT':
                    await c.execute("UPDATE public.shipments SET store_fulfillment_status='FULFILLED' WHERE tenant_id=$1 AND id=$2 AND tracking_lifecycle_type='FORWARD_SHIPMENT'",tenant_id,row['shipment_id'])
    if not matched: raise HTTPException(404,'Confirmed tracking event not found')

async def queue_status_callback(connection: Any, tenant_id: UUID, shipment_id: UUID,
                                source_event: str, payload: dict[str,Any]) -> None:
    """Called within accepted tracking-event transaction; no network or secrets."""
    if not await connection.fetchval("SELECT to_regclass('public.store_callback_events') IS NOT NULL"): return
    await connection.execute('''INSERT INTO public.store_callback_events(tenant_id,store_id,shipment_id,source_event,payload)
        SELECT s.tenant_id,st.id,s.id,$3,$4::jsonb||jsonb_build_object('store_order_id',COALESCE(s.store_order_id,p.store_order_id),
          'tracking_lifecycle_type',s.tracking_lifecycle_type)
        FROM public.shipments s LEFT JOIN public.shipments p ON p.tenant_id=s.tenant_id AND p.id=s.return_of_shipment_id
        JOIN public.ecommerce_stores st ON st.tenant_id=s.tenant_id AND st.id=COALESCE(s.ecommerce_store_id,p.ecommerce_store_id)
        WHERE s.tenant_id=$1 AND s.id=$2 AND st.is_active AND NOT (st.platform=ANY($5::text[]))
        ON CONFLICT(tenant_id,shipment_id,source_event) DO NOTHING''',tenant_id,shipment_id,source_event,json.dumps(payload),list(NATIVE))

async def retry_status_callbacks(service: Any) -> None:
    async with service.pool.acquire() as c:
        if not await c.fetchval("SELECT to_regclass('public.store_callback_events') IS NOT NULL"): return
        rows=await c.fetch("SELECT * FROM public.store_callback_events WHERE state IN ('PENDING','RETRY') AND attempts<30 AND next_attempt_at<=now() ORDER BY next_attempt_at LIMIT 50")
    for row in rows:
        config=await resolve_connector(service,row['store_id'])
        if not config or config.tenant_id!=row['tenant_id'] or config.platform in NATIVE or not config.live_delivery: continue
        async with service.pool.acquire() as c:
            active=await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.ecommerce_stores WHERE tenant_id=$1 AND id=$2 AND is_active)',row['tenant_id'],row['store_id'])
            if not active: continue
            claim=await c.fetchval("""UPDATE public.store_callback_events SET state='RETRY',attempts=attempts+1,
                next_attempt_at=now()+interval '5 minutes' WHERE id=$1 AND state IN ('PENDING','RETRY')
                AND next_attempt_at<=now() AND attempts<30 RETURNING id""",row['id'])
        if not claim: continue
        body=json.loads(row['payload']) if isinstance(row['payload'],str) else dict(row['payload'])
        body['event_id']=str(row['id'])
        try:
            from backend.custom_stores import callback
            await callback(service.client,config,row['store_id'],body)
        except (HTTPException,httpx.HTTPError,ValueError,KeyError,TypeError): continue
        async with service.pool.acquire() as c: await c.execute("UPDATE public.store_callback_events SET state='DELIVERED' WHERE id=$1",row['id'])
