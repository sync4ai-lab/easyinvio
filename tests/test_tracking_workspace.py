"""Offline authorization, data projection and channel compatibility tests."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient

from backend.tracking_workspace import TrackingWorkspace,TrackingScope,build_router,shipment_projection,timeline_projection
from backend.tracking_and_support import TrackingEvent
from backend.automation_three_partners import parse_easypost_tracking


def client(role='OWNER',platform=False):
    identity=SimpleNamespace(tenant_id=uuid4(),user_id=uuid4(),role=role)
    async def member():return identity
    async def owner():
        if not platform:raise HTTPException(403,'Platform-owner permission required')
        return identity
    app=FastAPI();app.include_router(build_router(member,owner))
    engine=SimpleNamespace(ready=True,require_ready=lambda:None,search=AsyncMock(return_value={'shipments':[]}),
                           detail=AsyncMock(return_value={'shipments':[]}),share=AsyncMock(),resolve=AsyncMock(return_value={'shipments':[]}),
                           public_rate_limit=lambda _:None)
    app.state.tracking_workspace=engine
    return TestClient(app),engine,identity


def test_retailer_scope_cannot_be_overridden_by_query_and_admin_endpoint_denies_access():
    ac,engine,identity=client()
    assert ac.get('/api/v1/tracking/shipments?tenant_id='+str(uuid4())).status_code==200
    assert engine.search.call_args.args[0].tenant_id==identity.tenant_id
    assert ac.get('/api/v1/admin/tracking/shipments').status_code==403
    assert engine.search.await_count==1


def test_platform_search_uses_separate_dependency_and_explicit_scope():
    ac,engine,identity=client(platform=True)
    assert ac.get('/api/v1/admin/tracking/shipments').status_code==200
    assert engine.search.call_args.args[0]==TrackingScope(None,identity.user_id,True)


def test_read_only_persona_cannot_create_shares_and_invalid_identifiers_are_rejected():
    ac,engine,_=client(role='ACCOUNTANT')
    assert ac.get('/api/v1/tracking/shipments/'+str(uuid4())).status_code==200
    assert ac.post('/api/v1/tracking/shipments/'+str(uuid4())+'/share',json={}).status_code==403
    assert ac.get('/api/v1/tracking/shipments/not-a-uuid').status_code==422
    engine.share.assert_not_awaited()


def test_public_capability_endpoint_is_bounded_and_never_uses_reference_lookup():
    ac,engine,_=client()
    token='a'*43
    response=ac.post('/api/v1/public/tracking/resolve',json={'token':token})
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    engine.resolve.assert_awaited_once_with(token)
    assert ac.post('/api/v1/public/tracking/resolve',json={'tracking_number':'guessed'}).status_code==422
    assert ac.post('/api/v1/public/tracking/resolve',content='x'*4097).status_code==413
    engine.search.assert_not_awaited()


def test_empty_and_stale_are_not_fabricated_delivery_failures():
    now=datetime.now(timezone.utc)
    row=dict(id=uuid4(),status='BOOKED',logistics_metadata={},parcel_count=1,last_tracking_event_at=None)
    empty=shipment_projection(row,now=now)
    assert empty['status']=='BOOKED' and empty['data_state']=='AWAITING_CARRIER_UPDATE'
    assert empty['estimated_delivery_at'] is None and empty['refund']['status']=='UNAVAILABLE'
    row.update(status='IN_TRANSIT',last_tracking_event_at=now-timedelta(hours=60))
    stale=shipment_projection(row,now=now)
    assert stale['status']=='IN_TRANSIT' and stale['data_state']=='STALE'


def test_actual_scan_time_and_detailed_milestone_do_not_change_legacy_receipt_digest():
    now=datetime.now(timezone.utc)-timedelta(minutes=10);scan=now-timedelta(hours=1)
    body={'description':'tracker.updated','id':'evt_test','result':{'id':'trk_test','object':'Tracker','mode':'test',
        'tracking_code':'TEST','status':'out_for_delivery','updated_at':now.isoformat(),
        'tracking_details':[{'datetime':scan.isoformat(),'message':'Out for delivery','tracking_location':{'city':'Leeds'}}]}}
    event,_,_=parse_easypost_tracking(body,'TEST')
    assert event.scan_occurred_at==scan and event.milestone=='OUT_FOR_DELIVERY' and event.location=='Leeds'
    legacy={'event_id':'evt_test','tracking_number':'TEST','status':'IN_TRANSIT','occurred_at':now.isoformat().replace('+00:00','Z'),
            'raw_error':'Out for delivery','proof_of_delivery_url':None}
    actual=event.model_dump(mode='json',include=set(legacy))
    assert hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest()==hashlib.sha256(json.dumps(legacy,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['TWILIO','GUPSHUP'])
async def test_existing_whatsapp_queue_accepts_capability_without_inferred_phone_ownership(monkeypatch,provider):
    from backend.whatsapp_queue import process_inbound
    from starlette.datastructures import FormData
    from starlette.requests import Request
    token='b'*43;app=FastAPI()
    app.state.settings=SimpleNamespace(whatsapp_provider=provider,twilio_enabled=True,gupshup_enabled=True,
        whatsapp_outbound_paused=False,whatsapp_uat_mode=True,whatsapp_test_recipients=['+447700900001'])
    app.state.tracking_workspace=SimpleNamespace(ready=True,public_rate_limit=lambda _:None,
        resolve=AsyncMock(return_value={'shipments':[{'order_reference':'ORDER-TEST','status':'IN_TRANSIT'}],'support_message':'Contact the retailer for help.'}))
    # A capability branch must not invoke registration, model parsing or a carrier.
    monkeypatch.setattr('backend.whatsapp_onboarding.onboarding_manager',AsyncMock(side_effect=AssertionError('Unexpected signup')))
    request=Request({'type':'http','method':'POST','path':'/','headers':[],'app':app})
    result=await process_inbound(request,FormData({'From':'whatsapp:+447700900001','To':'whatsapp:+447700900002','Body':'Track link '+token,'NumMedia':'0'}))
    assert 'ORDER-TEST' in result[0].body and 'in transit' in result[0].body
    app.state.tracking_workspace.resolve.assert_awaited_once_with(token)
    app.state.settings.whatsapp_test_recipients=[]
    with pytest.raises(HTTPException):
        await process_inbound(request,FormData({'From':'whatsapp:+447700900001','To':'whatsapp:+447700900002','Body':'Track link '+token,'NumMedia':'0'}))
    app.state.tracking_workspace.resolve.assert_awaited_once_with(token)
