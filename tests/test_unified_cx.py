"""Offline policy, delay, claims and connector contracts; no provider credentials."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.cx_claims import ClaimDossier,ClaimIntake,ClaimScope,ClaimTriageService,fetch_claim_photo
from backend.cx_connectors import callback_origin,connector_checks,provision_remote
from backend.cx_delay import ProactiveDelaySentinelAgent
from backend.cx_policies import ReturnPolicy,ReturnPolicyCopilotAgent
from backend.entitlements import Subscription,allowed,enabled


@pytest.mark.parametrize('days',[0,91])
def test_return_bounds(days):
    with pytest.raises(ValidationError):ReturnPolicy(return_window_days=days)


@pytest.mark.parametrize('amount',['0','50.01','NaN','Infinity'])
def test_policy_cannot_authorize_unbounded_cost(amount):
    with pytest.raises(ValidationError):ReturnPolicy(max_return_cost_gbp=amount)


@pytest.mark.asyncio
async def test_policy_extraction_has_no_side_effects_or_model_cost_for_common_command():
    runtime=NS(available=True,run=AsyncMock())
    policy=await ReturnPolicyCopilotAgent(runtime).extract(uuid4(),'Set a 30-day free return policy for UK orders, maximum GBP 12.50')
    assert policy.payer=='MERCHANT_PAY' and policy.return_window_days==30
    assert policy.allowed_countries==['GB'] and policy.max_return_cost_gbp==Decimal('12.50')
    runtime.run.assert_not_awaited()
    default=ReturnPolicy()
    assert default.payer=='CUSTOMER_PAY' and default.require_delivered_status and default.return_window_days==14


def test_all_tiers_ignore_legacy_enforcement_bypass():
    now=datetime.now(timezone.utc)
    starter=Subscription(plan_period_start=now,plan_enforcement_enabled=False)
    assert not allowed(starter,'whatsapp_bot') and not allowed(starter,'customs_hs_builder')
    assert enabled(NS(subscription_tiers_enabled=False))


@pytest.mark.parametrize('status,age,scan_age,expected',[
    ('BOOKED',49,None,'NO_FIRST_SCAN_48H'),('BOOKED',48,None,None),
    ('BOOKED',80,2,None),('IN_TRANSIT',100,73,'IN_TRANSIT_STALLED_72H'),
    ('IN_TRANSIT',100,72,None),('EXCEPTION',1,1,'CARRIER_EXCEPTION'),
    ('DELIVERED',200,150,None),('CANCELLED',200,None,None)])
def test_stall_rules_are_deterministic_and_terminal_safe(status,age,scan_age,expected):
    now=datetime.now(timezone.utc)
    reason=ProactiveDelaySentinelAgent.detect(status,now-timedelta(hours=age),now-timedelta(hours=scan_age) if scan_age is not None else None,now)
    assert reason==expected
    if reason:assert not any(word in ProactiveDelaySentinelAgent.explain(reason).lower() for word in ['tomorrow','guaranteed','will arrive'])


def test_damage_dossier_demands_all_evidence_and_never_credits():
    dossier=ClaimDossier(reason='DAMAGED',scan_status='DELIVERED')
    assert len(dossier.missing())==3
    dossier.description='The outer box and glass item were broken'
    dossier.item_value_gbp=Decimal('20')
    assert len(dossier.missing())==1
    dossier.photo_count=1
    assert not dossier.missing() and dossier.financial_action=='NONE'
    with pytest.raises(ValidationError):ClaimDossier(reason='LOST',scan_status='IN_TRANSIT',financial_action='CREDIT')


def test_claim_identity_cannot_cross_tenant_actor_or_capability():
    scope=ClaimScope(uuid4(),uuid4(),actor_id=uuid4())
    row={'tenant_id':scope.tenant_id,'shipment_id':scope.shipment_id,'actor_id':scope.actor_id,'capability_sha256':None}
    ClaimTriageService.assert_owner(row,scope)
    for field in ['tenant_id','shipment_id','actor_id']:
        with pytest.raises(HTTPException):ClaimTriageService.assert_owner({**row,field:uuid4()},scope)
    with pytest.raises(HTTPException):ClaimTriageService.assert_owner(row,ClaimScope(scope.tenant_id,scope.shipment_id,capability_sha256='x'*64))


@pytest.mark.asyncio
async def test_photo_fetch_does_not_follow_untrusted_urls():
    client=NS(stream=AsyncMock())
    state=NS(settings=NS(whatsapp_evidence_allowed_hosts=['media.example.test']),rating=NS(client=client))
    for url in ['http://media.example.test/a','https://127.0.0.1/a','https://media.example.test@evil.test/a','https://media.example.test:444/a']:
        with pytest.raises(HTTPException):await fetch_claim_photo(state,url)
    client.stream.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint',['https://api.easypost.com/v2','https://api.goshippo.com'])
async def test_webhook_registration_is_native_list_before_create_and_duplicate_safe(endpoint):
    calls=[];stored=[]
    callback='https://uat.example.test/api/v1/tracking/webhook?source='+str(uuid4())
    def handler(request):
        calls.append(request.method)
        if request.method=='GET':return httpx.Response(200,json={'webhooks' if 'easypost' in endpoint else 'results':stored})
        import json
        data=json.loads(request.content)
        value=data.get('webhook',data)
        stored.append({'url':value['url'],'id':'hook_test','object_id':'hook_test','active':True})
        return httpx.Response(201,json=stored[0])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first=await provision_remote(client,endpoint,'synthetic-private-key',callback,'x'*43,'TEST')
        second=await provision_remote(client,endpoint,'synthetic-private-key',callback,'x'*43,'TEST')
    assert first==second=='hook_test' and calls==['GET','POST','GET']


def test_health_distinguishes_live_integration_and_worker_and_direct_contracts():
    settings=NS(provider_environment='LIVE',tracking_polling_enabled=True,integration_evri_enabled=True)
    row={'id':uuid4(),'api_base_url':'https://panel.sendcloud.sc/api/v3','sendcloud_integration_id':None,'webhook_enabled':False}
    result=connector_checks(settings,[row],worker_running=False)
    assert not result['ready']
    assert 'SENDCLOUD_LIVE_INTEGRATION_ID_REQUIRED' in result['issues']
    assert 'EVRI_DIRECT_CONTRACT_NOT_INJECTED' in result['issues']
    settings.provider_environment='TEST'
    result=connector_checks(settings,[],worker_running=True)
    assert 'SENDCLOUD_LIVE_INTEGRATION_ID_REQUIRED' not in result['issues']
    assert result['sendcloud_test_label_purchase'].startswith('BLOCKED')


def test_callback_never_uses_host_headers_or_internal_origin():
    assert callback_origin(NS(tracking_webhook_base_url='',booking_page_url='https://uat.example.test'))=='https://uat.example.test'
    for value in ['http://localhost:8000','https://x.test/path','https://user:pass@x.test','https://x.test?token=a']:
        with pytest.raises(ValueError):callback_origin(NS(tracking_webhook_base_url=value,booking_page_url='https://fallback.test'))


@pytest.mark.asyncio
async def test_bounded_delay_model_cannot_invent_a_delivery_or_payout():
    runtime=NS(available=True,run=AsyncMock(return_value=NS(value={'text':'Your parcel will arrive tomorrow and you will be paid.'})))
    result=await ProactiveDelaySentinelAgent.explain_bounded(runtime,uuid4(),'NO_FIRST_SCAN_48H')
    assert result==ProactiveDelaySentinelAgent.explain('NO_FIRST_SCAN_48H')
    assert runtime.run.await_args.kwargs['output_token_limit']==160


def test_invalid_chat_claim_value_is_a_bounded_refusal():
    from backend.cx_claims import value_from_text
    assert value_from_text('The item cost GBP 25.50')==Decimal('25.50')
    for text in ('value GBP 0','value GBP 50001'):
        with pytest.raises(HTTPException) as error:value_from_text(text)
        assert error.value.status_code==422


@pytest.mark.asyncio
async def test_shippo_refresh_only_reads_matching_purchased_test_resources(monkeypatch):
    from backend.cx_tracking import AggregatorTrackingAdapter
    from backend.automation_three_partners import ShippoAdapter
    from backend.automation_freight_engine import PurchaseRejected
    remote='a'*32
    request=AsyncMock(side_effect=[
        {'object_id':remote,'tracking_number':'TRACK123','test':True,'rate':{'provider':'evri'}},
        {'tracking_number':'TRACK123','carrier':'evri','tracking_status':{'status':'TRANSIT','status_date':'2026-11-20T12:00:00Z'}}])
    monkeypatch.setattr(ShippoAdapter,'request',request)
    shipment={'logistics_metadata':{},'upstream_shipment_id':remote,'tracking_number':'TRACK123'}
    account=NS(base_url='https://api.goshippo.com',api_key='synthetic')
    events=await AggregatorTrackingAdapter().lookup(None,account,shipment,'TEST',None)
    assert len(events)==1 and events[0].status=='IN_TRANSIT'
    assert [call.args[0] for call in request.await_args_list]==['GET','GET']
    request.side_effect=None
    request.return_value={'object_id':remote,'tracking_number':'TRACK123','test':False}
    with pytest.raises(PurchaseRejected):await AggregatorTrackingAdapter().lookup(None,account,shipment,'TEST',None)


@pytest.mark.asyncio
async def test_sendcloud_refresh_requires_real_carrier_scan_time(monkeypatch):
    from backend.cx_tracking import AggregatorTrackingAdapter
    from backend.automation_three_partners import SendcloudAdapter
    from backend.automation_freight_engine import PurchaseRejected
    data={'id':'123','parcels':[{'tracking_number':'TRACK123','status':{'id':11}}]}
    request=AsyncMock(return_value={'data':data})
    monkeypatch.setattr(SendcloudAdapter,'request',request)
    shipment={'logistics_metadata':{},'upstream_shipment_id':'123','tracking_number':'TRACK123'}
    account=NS(base_url='https://panel.sendcloud.sc/api/v3',api_key='synthetic')
    with pytest.raises(PurchaseRejected,match='CARRIER_SCAN_NOT_AVAILABLE'):
        await AggregatorTrackingAdapter().lookup(None,account,shipment,'TEST',None)
    data['parcels'][0]['carrier_status_change_timestamp']='2026-11-20T12:00:00Z'
    result=await AggregatorTrackingAdapter().lookup(None,account,shipment,'TEST',{'sendcloud_status_map':{'11':'IN_TRANSIT'}})
    assert result[0].status=='IN_TRANSIT'
    assert all(call.args[0]=='GET' for call in request.await_args_list)


def test_native_gupshup_photo_preserves_caption_for_private_claim_intake():
    from backend.gupshup_ingress import parse_event
    from tests.test_gupshup_provider import settings,event
    body=event()
    body['payload']['type']='image'
    body['payload']['payload']={'caption':'Broken packaging','url':'https://filemanager.gupshup.io/synthetic','contentType':'image/jpeg'}
    kind,form,_,_=parse_event(body,settings())
    assert kind=='message' and form['Body']=='Broken packaging' and form['NumMedia']=='1'
    assert form['MediaUrl0']=='https://filemanager.gupshup.io/synthetic'
