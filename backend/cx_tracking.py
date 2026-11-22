"""Read-only recovery for existing purchased resources; never creates trackers."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from backend.automation_freight_engine import PurchaseRejected


class AggregatorTrackingAdapter:
    async def lookup(self,client: Any,account: Any,shipment: Any,environment: str,options: Any) -> list[Any]:
        from backend.automation_three_partners import ShippoAdapter, SendcloudAdapter, parse_shippo_tracking, parse_sendcloud_tracking
        metadata=shipment['logistics_metadata']
        metadata=json.loads(metadata) if isinstance(metadata,str) else metadata or {}
        pieces=(metadata.get('automation_label') or {}).get('package_labels') or []
        if not pieces:
            pieces=[{'upstream_id':shipment.get('upstream_shipment_id'),'tracking_number':shipment.get('tracking_number')}]
        if len(pieces)>20:
            raise PurchaseRejected('TRACKING_PIECE_LIMIT_REQUIRES_REVIEW')
        events=[]
        for piece in pieces:
            number=piece.get('tracking_number')
            remote=piece.get('upstream_id')
            if not isinstance(number,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',number):
                raise PurchaseRejected('TRACKING_REMOTE_IDENTITY_REQUIRED')
            if account.base_url=='https://api.goshippo.com':
                adapter=ShippoAdapter(client,account.api_key,environment=environment)
                if not isinstance(remote,str) or not re.fullmatch(r'[a-fA-F0-9]{32}',remote):
                    raise PurchaseRejected('TRACKING_PURCHASED_TRANSACTION_REQUIRED')
                transaction=await adapter.request('GET','/transactions/'+remote)
                if transaction.get('object_id')!=remote or transaction.get('tracking_number')!=number or transaction.get('test') is not (environment=='TEST'):
                    raise PurchaseRejected('TRACKING_TRANSACTION_IDENTITY_MISMATCH')
                rate=transaction.get('rate') or {}
                if isinstance(rate,str):
                    if not re.fullmatch(r'[a-fA-F0-9]{32}',rate):raise PurchaseRejected('TRACKING_RATE_IDENTITY_REQUIRED')
                    rate=await adapter.request('GET','/rates/'+rate)
                carrier=(rate.get('provider') or '').lower()
                if not re.fullmatch(r'[a-z0-9_]{1,60}',carrier):
                    raise PurchaseRejected('TRACKING_NATIVE_CARRIER_REQUIRED')
                body=await adapter.request('GET','/tracks/'+quote(carrier,safe='')+'/'+quote(number,safe=''))
                if body.get('tracking_number')!=number or body.get('carrier')!=carrier:
                    raise PurchaseRejected('TRACKING_REMOTE_IDENTITY_MISMATCH')
                parsed=parse_shippo_tracking({'event':'track_updated','test':environment=='TEST','data':body},environment,preserve_unknown=True)
            elif account.base_url=='https://panel.sendcloud.sc/api/v3':
                if not isinstance(remote,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',remote):
                    raise PurchaseRejected('TRACKING_PURCHASED_SHIPMENT_REQUIRED')
                adapter=SendcloudAdapter(client,account.api_key,environment=environment)
                body=await adapter.request('GET','/shipments/'+remote)
                data=body.get('data',body)
                if str(data.get('id'))!=remote:
                    raise PurchaseRejected('TRACKING_REMOTE_IDENTITY_MISMATCH')
                parcels=[p for p in data.get('parcels',[]) if p.get('tracking_number')==number]
                if len(parcels)!=1 or not isinstance(parcels[0].get('status'),dict) or not parcels[0].get('carrier_status_change_timestamp'):
                    # Label announcement status is not a carrier scan. Never use now()/created_at as one.
                    raise PurchaseRejected('TRACKING_CARRIER_SCAN_NOT_AVAILABLE_IN_RESOURCE')
                status_map=(options or {}).get('sendcloud_status_map') or {}
                status_map=json.loads(status_map) if isinstance(status_map,str) else status_map
                parsed=parse_sendcloud_tracking({'action':'parcel_status_changed','parcel':parcels[0],
                    'carrier_status_change_timestamp':parcels[0]['carrier_status_change_timestamp']},status_map,preserve_unknown=True)
            else:
                raise PurchaseRejected('TRACKING_POLLING_UNSUPPORTED')
            if parsed is not None:
                events.append(parsed[0])
        return events
