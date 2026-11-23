"""No network, provider, real wallet or shared database is used in these tests."""
import asyncio
import hashlib
import hmac
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from io import BytesIO
from uuid import UUID,uuid4

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from backend.provider_simulation import ProviderSimulation, QuoteInput, BookInput, ClaimInput, ManifestInput, InsurerEvent
from backend.provider_lab import build_lab


def quote(**changes):
    return QuoteInput(weight_kg='2',length_cm='25',width_cm='20',height_cm='15',
        origin_postcode='ls126ej',destination_postcode='B69 3EB',**changes)


async def booked(service,*,workspace='merchant-a',insured=False,scenario='NORMAL'):
    rates=await service.quote(workspace,quote())
    body=BookInput(offer_id=rates['offers'][0]['id'],confirm=True,protection_consent=insured,terms_accepted=insured,scenario=scenario)
    return body,await service.book(workspace,body)


@pytest.mark.parametrize('options',[{'environment':'LIVE'},{'environment':'TEST'},
    {'dummy_account':'REAL-ACCOUNT'},{'event_secret':'real-looking-key'}])
def test_real_configuration_cannot_enable_lab(options):
    with pytest.raises(ValueError):ProviderSimulation(**options)


@pytest.mark.asyncio
async def test_quote_uses_existing_direct_strategies_without_network_or_database(monkeypatch):
    import asyncpg
    async def forbidden(*args,**kwargs):pytest.fail('Unexpected network/database operation')
    monkeypatch.setattr(asyncpg,'connect',forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',forbidden)
    service=ProviderSimulation();body=quote()
    result=await service.quote('merchant-a',body)
    assert body.origin_postcode=='LS12 6EJ'
    assert [r['carrier'] for r in result['offers']]==['EVRI','ROYALMAIL']
    assert [r['price_gbp'] for r in result['offers']]==['3.20','3.80']
    assert result['simulated'] and 'NOT VALID' in result['notice']
    assert (await service.quote('merchant-a',body))['replayed']
    assert len(service.state('merchant-a')['offers'])==2


@pytest.mark.asyncio
async def test_tenant_account_identity_is_scoped_and_offers_cannot_cross_workspaces():
    service=ProviderSimulation()
    a=await service.quote('merchant-a',quote(account_mode='TENANT'))
    b=await service.quote('merchant-b',quote(account_mode='TENANT'))
    assert a['offers'][0]['account_id']!=b['offers'][0]['account_id']
    with pytest.raises(HTTPException) as error:await service.book('merchant-b',BookInput(offer_id=a['offers'][0]['id'],confirm=True))
    assert error.value.status_code==404 and service.state('merchant-b')['balance']==100


@pytest.mark.asyncio
async def test_concurrent_booking_replay_debits_dummy_balance_once():
    service=ProviderSimulation();rates=await service.quote('merchant-a',quote())
    body=BookInput(offer_id=rates['offers'][0]['id'],confirm=True,protection_consent=True,terms_accepted=True)
    results=await asyncio.gather(*(service.book('merchant-a',body) for _ in range(5)))
    assert len({r['shipment']['id'] for r in results})==1
    assert service.state('merchant-a')['balance']==Decimal('95.60')
    assert len(service.state('merchant-a')['ledger'])==1
    with pytest.raises(HTTPException) as error:await service.book('merchant-a',body.model_copy(update={'protection_consent':False}))
    assert error.value.status_code==409


@pytest.mark.asyncio
async def test_rejected_or_expired_offer_never_debits():
    service=ProviderSimulation();rates=await service.quote('merchant-a',quote());identifier=rates['offers'][0]['id']
    with pytest.raises(HTTPException):await service.book('merchant-a',BookInput(offer_id=identifier,confirm=True,scenario='REJECT'))
    service.state('merchant-a')['offers'][identifier]['expires_at']=datetime.now(timezone.utc)-timedelta(seconds=1)
    with pytest.raises(HTTPException) as error:await service.book('merchant-a',BookInput(offer_id=identifier,confirm=True))
    assert error.value.status_code==410 and service.state('merchant-a')['balance']==100


@pytest.mark.asyncio
async def test_protection_requires_separate_consent_and_demo_terms():
    service=ProviderSimulation();rates=await service.quote('merchant-a',quote())
    with pytest.raises(HTTPException):await service.book('merchant-a',BookInput(offer_id=rates['offers'][0]['id'],confirm=True,protection_consent=True))
    assert service.state('merchant-a')['balance']==100
    _,result=await booked(service)
    assert result['shipment']['policy_id'] is None and result['shipment']['premium_gbp']=='0'


@pytest.mark.asyncio
async def test_timeout_after_acceptance_reconciles_without_second_label_or_debit():
    service=ProviderSimulation();rates=await service.quote('merchant-a',quote())
    body=BookInput(offer_id=rates['offers'][0]['id'],confirm=True,scenario='TIMEOUT_AFTER_ACCEPTANCE')
    with pytest.raises(HTTPException) as error:await service.book('merchant-a',body)
    assert error.value.status_code==503 and 'reconcile_url' in error.value.detail
    result=await service.book('merchant-a',body)
    assert result['replayed'] and len(service.state('merchant-a')['shipments'])==1
    assert len(service.state('merchant-a')['ledger'])==1


@pytest.mark.asyncio
async def test_manifest_tracks_exact_membership_and_blocks_late_cancellation():
    service=ProviderSimulation();_,booking=await booked(service);identifier=UUID(booking['shipment']['id'])
    body=ManifestInput(carrier='EVRI',shipment_ids=[identifier])
    result=await service.manifest('merchant-a',body)
    assert not result['carrier_closed'] and result['shipment_ids']==[str(identifier)]
    assert (await service.manifest('merchant-a',body))['replayed']
    with pytest.raises(HTTPException):await service.cancel('merchant-a',str(identifier))
    with pytest.raises(HTTPException):await service.return_label('merchant-a',str(identifier))
    await service.scan('merchant-a',str(identifier),'IN_TRANSIT')
    await service.scan('merchant-a',str(identifier),'DELIVERED')
    returning=await service.return_label('merchant-a',str(identifier))
    assert not returning['postage_purchased']
    assert b'EASYINVIO-DEMO' not in service.documents[('merchant-a','return-'+str(identifier))][0] # PDF is a document, not a carrier barcode.
    qr=service.documents[('merchant-a','qr-'+str(identifier))][0]
    assert b'<svg' in qr and b'SIMULATED' in qr
    assert (await service.return_label('merchant-a',str(identifier)))['qr_url']==returning['qr_url']


@pytest.mark.asyncio
async def test_cancellation_refunds_dummy_balance_exactly_once():
    service=ProviderSimulation();_,result=await booked(service,insured=True);identifier=result['shipment']['id']
    await service.cancel('merchant-a',identifier)
    assert (await service.cancel('merchant-a',identifier))['replayed']
    assert service.state('merchant-a')['balance']==100
    assert len(service.state('merchant-a')['ledger'])==2


def photo():
    buffer=BytesIO();Image.new('RGB',(3,3),(10,20,30)).save(buffer,format='PNG');return buffer.getvalue()


def signed(service,event):
    raw=event.model_dump_json().encode()
    return raw,hmac.new(service.event_secret,raw,hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_damage_evidence_insurer_approval_and_receipt_are_separate_steps():
    service=ProviderSimulation();_,booking=await booked(service,insured=True)
    body=ClaimInput(shipment_id=booking['shipment']['id'],reason='DAMAGED',description='Fictional glass broke in transit',item_value_gbp='25')
    result=await service.claim('merchant-a',body);identifier=result['claim']['id']
    assert result['claim']['status']=='NEEDS_EVIDENCE'
    with pytest.raises(HTTPException):await service.submit_claim('merchant-a',identifier)
    with pytest.raises(HTTPException):await service.evidence('merchant-a',identifier,b'not-an-image','image/png')
    await service.evidence('merchant-a',identifier,photo(),'image/png')
    await service.evidence('merchant-a',identifier,photo(),'image/png')
    assert len(service.claim_row('merchant-a',identifier)['photos'])==1
    await service.submit_claim('merchant-a',identifier)
    event=InsurerEvent(claim_id=identifier,status='APPROVED')
    raw,signature=signed(service,event)
    with pytest.raises(HTTPException):await service.insurer_event('merchant-a',raw,'forged')
    result=await service.insurer_event('merchant-a',raw,signature)
    assert not result['wallet_credit'] and service.state('merchant-a')['balance']==Decimal('95.60')
    paid=InsurerEvent(claim_id=identifier,status='PAID',amount_gbp='25',funds_received=True,payee='DEMO-EASYINVIO')
    raw,signature=signed(service,paid);result=await service.insurer_event('merchant-a',raw,signature)
    assert result['dummy_ledger_credit'] and not result['wallet_credit']
    assert (await service.insurer_event('merchant-a',raw,signature))['replayed']
    assert service.state('merchant-a')['balance']==Decimal('120.60')
    assert len([e for e in service.state('merchant-a')['ledger'] if e['kind']=='DEMO_SETTLEMENT'])==1


@pytest.mark.asyncio
async def test_uninsured_claim_stays_manual_and_foreign_claim_is_unavailable():
    service=ProviderSimulation();_,booking=await booked(service)
    result=await service.claim('merchant-a',ClaimInput(shipment_id=booking['shipment']['id'],reason='LOST',description='Fictional carrier trace failed',item_value_gbp='25'))
    identifier=result['claim']['id']
    assert (await service.submit_claim('merchant-a',identifier))['claim']['route']=='MERCHANT_CARRIER_REVIEW'
    with pytest.raises(HTTPException):await service.submit_claim('merchant-b',identifier)
    event=InsurerEvent(claim_id=identifier,status='APPROVED');raw,signature=signed(service,event)
    with pytest.raises(HTTPException):await service.insurer_event('merchant-a',raw,signature)


@pytest.mark.asyncio
async def test_api_chat_document_isolation_and_cross_origin_mutation_guard():
    app=build_lab()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://lab.test') as client:
        assert 'SIMULATED' in (await client.get('/')).text
        r=await client.post('/api/chat',json={'text':'Quote 2kg from LS12 6EJ to B69 3EB 25x20x15'})
        assert r.status_code==200,r.text
        r=await client.post('/api/chat',json={'text':'Book 1 insured'})
        assert r.status_code==200,r.text
        shipment=r.json()['shipment'];path=shipment['label_url']
        document=await client.get(path)
        assert document.content.startswith(b'%PDF-') and document.headers['cache-control']=='no-store'
        assert (await client.get(path,headers={'X-Demo-Workspace':'merchant-b'})).status_code==404
        assert (await client.post('/api/quotes',headers={'Origin':'https://evil.invalid'},json=quote().model_dump(mode='json'))).status_code==403
        assert (await client.get('/api/state',headers={'X-Demo-Workspace':'real-tenant'})).status_code==422
        assert (await client.post('/api/quotes',json={**quote().model_dump(mode='json'),'api_key':'REAL'})).status_code==422


@pytest.mark.asyncio
async def test_settlement_cannot_skip_approval_or_credit_a_wrong_payee():
    service=ProviderSimulation();_,booking=await booked(service,insured=True)
    claim=await service.claim('merchant-a',ClaimInput(shipment_id=booking['shipment']['id'],reason='LOST',description='The fictional trace could not locate this parcel',item_value_gbp='25'))
    identifier=claim['claim']['id'];await service.submit_claim('merchant-a',identifier)
    paid=InsurerEvent(claim_id=identifier,status='PAID',amount_gbp='25',funds_received=True,payee='DEMO-EASYINVIO')
    raw,signature=signed(service,paid)
    with pytest.raises(HTTPException):await service.insurer_event('merchant-a',raw,signature)
    approval=InsurerEvent(claim_id=identifier,status='APPROVED');raw,signature=signed(service,approval)
    await service.insurer_event('merchant-a',raw,signature)
    wrong=paid.model_copy(update={'payee':'DEMO-OTHER-PAYEE'});raw,signature=signed(service,wrong)
    with pytest.raises(HTTPException):await service.insurer_event('merchant-a',raw,signature)
    conflicting=approval.model_copy(update={'status':'DECLINED'});raw,signature=signed(service,conflicting)
    with pytest.raises(HTTPException):await service.insurer_event('merchant-a',raw,signature)
    with pytest.raises(HTTPException):await service.cancel('merchant-a',booking['shipment']['id'])
    assert service.state('merchant-a')['balance']==Decimal('95.60')


@pytest.mark.asyncio
async def test_royal_mail_simulator_has_real_pdf_documents_and_read_only_config():
    service=ProviderSimulation();rates=await service.quote('merchant-a',quote())
    offer=next(row for row in rates['offers'] if row['carrier']=='ROYALMAIL')
    result=await service.book('merchant-a',BookInput(offer_id=offer['id'],confirm=True))
    identifier=result['shipment']['id']
    assert result['shipment']['tracking_number'].startswith('DEMO-ROYALMAIL-')
    assert service.documents[('merchant-a','label-'+identifier)][0].startswith(b'%PDF-')
    manifest=await service.manifest('merchant-a',ManifestInput(carrier='ROYALMAIL',shipment_ids=[identifier]))
    assert manifest['carrier_closed'] is False
    from backend.adapters import DIRECT_REGISTRATIONS
    assert DIRECT_REGISTRATIONS==() # The simulator never registers itself in the real app.
