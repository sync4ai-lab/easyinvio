"""Real SQL on disposable PGlite only. Never reads .env or contacts a provider."""
import hashlib,json
from datetime import datetime,timezone
from types import SimpleNamespace
from uuid import UUID,uuid4
from unittest.mock import patch
import asyncpg,pytest
from fastapi import HTTPException
from backend.post_purchase import PostPurchaseService,RecipientVerification,RecipientPermission,contact_digest,save_permission
from backend.recipient_notifications import stage_recipient_notifications
from backend.tracking_workspace import ShareRequest,CustomerRequest
from backend.tracking_input import parse_tracking_input
from test_tracking_workspace_postgres import world,ROOT
from test_universal_stores_postgres import setup as store_setup
from test_sender_notifications import migrate as sender_setup

async def setup(w):
    stores=await store_setup(w);await sender_setup(w)
    await w.db.command('ALTER TABLE public.tenants ADD COLUMN public_status_lookup_enabled boolean DEFAULT true;',mode='exec')
    await w.db.command((ROOT/'migrations/058_branded_recipient_tracking.sql').read_text(encoding='utf-8'),mode='exec')
    address={'name':'Private Recipient','line1':'42 Private Street','city':'Leeds','postal_code':'LS12 6EJ','country_code':'GB','email':'recipient@example.test','phone':'+447700900222'}
    order={'origin':{'country_code':'GB'},'destination':{'country_code':'GB'},'items':[{'description':'Fixture shirt','quantity':1}],'packages':[{'weight_kg':'1'}]}
    await w.db.execute("UPDATE public.shipments SET status='DELIVERED',delivered_at=now(),tracking_number='PARCEL-000000',recipient_address=$2::jsonb,proof_of_delivery_url='https://carrier.example.test/pod',logistics_metadata=$3::jsonb WHERE id=$1",w.shipments[0],json.dumps(address),json.dumps({'automation_order':order}))
    await w.db.execute("UPDATE public.ecommerce_stores SET brand_display_name='Fixture Brand',brand_logo_url='https://shop.example.test/logo.svg',brand_accent_hex='#123456',buyer_notification_policy=$2::jsonb WHERE id=$1",stores[0],json.dumps({'email':True,'whatsapp':True,'categories':['IN_TRANSIT','DELIVERED']}))
    return PostPurchaseService(w.engine),stores

def test_shared_parser_formats_and_host_boundary():
    origins={'https://uat.easyinvio.com'};token='A'*43
    for value in [token,'https://uat.easyinvio.com/track#'+token,'https://uat.easyinvio.com/track?token='+token,'/track#'+token]:assert parse_tracking_input(value,origins).value==token
    assert parse_tracking_input('JVGL062948102948',origins).kind=='REFERENCE'
    with pytest.raises(ValueError):parse_tracking_input('https://attacker.example/track#'+token,origins)
    with pytest.raises(ValueError):parse_tracking_input('/track?token='+token+'#'+token,origins)

@pytest.mark.asyncio
async def test_plain_and_piece_lookup_redaction_branding_collision(world):
    w=world;service,stores=await setup(w)
    result=await service.lookup('PARCEL-000000','fixture-ip')
    assert result['branding']['display_name']=='Fixture Brand'
    assert result['branding']['accent_hex']=='#123456'
    long_reference='CARRIER'+('1'*40)
    await w.db.execute('UPDATE public.shipments SET tracking_number=$2 WHERE id=$1',w.shipments[0],long_reference)
    assert (await service.lookup(long_reference,'fixture-ip'))['access']=='PUBLIC'
    await w.db.execute("UPDATE public.shipments SET tracking_number='PARCEL-000000' WHERE id=$1",w.shipments[0])
    encoded=json.dumps(result)
    for secret in ['Private Recipient','Private Street','recipient@example.test','carrier.example.test/pod',str(w.tenants[0])]:assert secret not in encoded
    await w.db.execute("UPDATE public.shipments SET logistics_metadata=logistics_metadata||$2::jsonb WHERE id=$1",w.shipments[0],json.dumps({'automation_label':{'package_labels':[{'tracking_number':'PIECE-000001'},{'tracking_number':'PIECE-000002'}]}}))
    assert (await service.lookup('PIECE-000002','fixture-ip'))['shipments'][0]['tracking_number']=='PIECE-000002'
    await w.db.execute("UPDATE public.shipments SET tracking_number='PIECE-000002' WHERE id=$1",w.shipments[1])
    await w.db.execute('UPDATE public.tenants SET public_status_lookup_enabled=false WHERE tenant_id=$1',w.tenants[1])
    with pytest.raises(HTTPException) as error:await service.lookup('PIECE-000002','fixture-ip')
    assert error.value.status_code==404

@pytest.mark.asyncio
async def test_postcode_unlocks_pod_return_help_and_expiry(world):
    w=world;service,_=await setup(w)
    with pytest.raises(HTTPException) as error:await service.verify(RecipientVerification(tracking_number='PARCEL-000000',delivery_postcode='B69 3EB'),'wrong-ip')
    assert error.value.status_code==404
    result=await service.verify(RecipientVerification(tracking_number='PARCEL-000000',delivery_postcode='ls126ej'),'fixture-ip')
    assert result['access']=='VERIFIED_RECIPIENT'
    shipment=result['shipments'][0]
    assert shipment['delivery_address']['line1']=='42 Private Street'
    assert shipment['proof_of_delivery_url']=='https://carrier.example.test/pod'
    assert shipment['return_url']=='/returns/fixture-shop-0'
    token=result['tracking_access_token']
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_recipient_access WHERE token_sha256=$1',hashlib.sha256(token.encode()).hexdigest())==1
    assert token not in str(await w.db.fetch('SELECT * FROM public.tracking_recipient_access'))
    help_result=await w.engine.customer_request(CustomerRequest(token=token,request_id=uuid4(),note='Please help with this delivery.'))
    assert help_result['status']=='RECEIVED'
    await service.permission(token,RecipientPermission(email=True,email_permission_confirmed=True))
    assert await w.db.fetchval('SELECT email FROM public.shipment_recipient_preferences WHERE tenant_id=$1 AND shipment_id=$2',w.tenants[0],w.shipments[0])
    await w.db.execute("UPDATE public.tracking_recipient_access SET expires_at=now()-interval '1 second'")
    with pytest.raises(HTTPException):await service.resolve(token)
    with pytest.raises(HTTPException):await w.engine.customer_request(CustomerRequest(token=token,request_id=uuid4(),note='Expired session must not submit.'))

@pytest.mark.asyncio
async def test_capability_alternative_verification_and_source_revocation(world):
    w=world;service,_=await setup(w)
    link=await w.engine.share(w.scope,w.shipments[0],ShareRequest());token=link['url'].split('#')[1]
    for text in [link['url'],link['url'].split('#')[0]+'?token='+token]:assert (await service.lookup(text,'fixture-ip'))['access']=='CAPABILITY'
    result=await service.verify(RecipientVerification(token=token),'fixture-ip');access=result['tracking_access_token']
    await w.db.execute('UPDATE public.tracking_share_links SET revoked_at=now() WHERE id=$1',UUID(link['id']))
    with pytest.raises(HTTPException):await service.resolve(access)
    with pytest.raises(HTTPException):await w.engine.resolve(access)

@pytest.mark.asyncio
async def test_rate_limits_are_durable_and_wrong_postcodes_do_not_issue_tokens(world):
    w=world;service,_=await setup(w)
    for _ in range(5):
        with pytest.raises(HTTPException) as error:await service.verify(RecipientVerification(tracking_number='PARCEL-000000',delivery_postcode='B69 3EB'),'same-ip')
        assert error.value.status_code==404
    with pytest.raises(HTTPException) as error:await service.verify(RecipientVerification(tracking_number='PARCEL-000000',delivery_postcode='LS12 6EJ'),'same-ip')
    assert error.value.status_code==429
    assert await w.db.fetchval('SELECT count(*) FROM public.tracking_recipient_access')==0

@pytest.mark.asyncio
async def test_recipient_staging_consent_contacts_dedupe_and_tenant_fk(world):
    w=world;service,stores=await setup(w)
    row=await w.db.fetchrow('SELECT recipient_address FROM public.shipments WHERE tenant_id=$1 AND id=$2',w.tenants[0],w.shipments[0])
    await stage_recipient_notifications(w.db,w.tenants[0],w.shipments[0],'DELIVERED')
    assert await w.db.fetchval("SELECT count(*) FROM public.shipment_sender_notifications WHERE audience='RECIPIENT'")==0
    await save_permission(w.db,w.tenants[0],w.shipments[0],row,RecipientPermission(email=True,whatsapp=True,email_permission_confirmed=True,whatsapp_permission_confirmed=True),actor=w.actors[0])
    for _ in range(2):await stage_recipient_notifications(w.db,w.tenants[0],w.shipments[0],'DELIVERED')
    assert await w.db.fetchval("SELECT count(*) FROM public.shipment_sender_notifications WHERE audience='RECIPIENT'")==2
    assert await w.db.fetchval("SELECT count(*) FROM public.shipment_sender_notifications WHERE audience='RECIPIENT' AND state='READY'")==0
    await w.db.execute("UPDATE public.shipments SET recipient_address=jsonb_set(recipient_address,'{email}','\"changed@example.test\"') WHERE id=$1",w.shipments[0])
    await stage_recipient_notifications(w.db,w.tenants[0],w.shipments[0],'IN_TRANSIT')
    assert await w.db.fetchval("SELECT count(*) FROM public.shipment_sender_notifications WHERE audience='RECIPIENT'")==2
    with pytest.raises(asyncpg.ForeignKeyViolationError):await save_permission(w.db,w.tenants[0],w.shipments[1],row,RecipientPermission(),actor=w.actors[0])
    await w.db.command('SET ROLE anon',mode='exec')
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):await w.db.fetch('SELECT * FROM public.tracking_recipient_access')
    finally:await w.db.command('RESET ROLE',mode='exec')


@pytest.mark.asyncio
async def test_verified_ingest_stages_recipient_once_and_preserves_sender_routing(world):
    from backend.tracking_and_support import TrackingKey,TrackingEvent
    from pydantic import SecretStr
    w=world;service,_=await setup(w)
    await w.db.execute("UPDATE public.shipments SET status='BOOKED',last_tracking_event_at=NULL WHERE id=$1",w.shipments[0])
    row=await w.db.fetchrow('SELECT recipient_address FROM public.shipments WHERE id=$1',w.shipments[0])
    await save_permission(w.db,w.tenants[0],w.shipments[0],row,RecipientPermission(email=True,email_permission_confirmed=True),actor=w.actors[0])
    event=TrackingEvent(event_id='verified-recipient-scan',tracking_number='PARCEL-000000',status='IN_TRANSIT',occurred_at=datetime.now(timezone.utc),hub_city='Leeds')
    key=TrackingKey(tenant_id=w.tenants[0],carrier_account_id=w.accounts[0],secret=SecretStr('fixture-only-secret-32-characters'))
    first=await w.support.ingest('fixture-verified',key,event,'c'*64)
    second=await w.support.ingest('fixture-verified',key,event,'c'*64)
    assert first['applied'] and second['replayed']
    assert await w.db.fetchval("SELECT count(*) FROM public.shipment_sender_notifications WHERE audience='RECIPIENT' AND category='IN_TRANSIT'")==1
    result=await service.lookup('PARCEL-000000','fixture-ip')
    assert result['shipments'][0]['timeline'][-1]['location']=='Leeds'


@pytest.mark.asyncio
async def test_buyer_delivery_uses_original_contact_brand_and_stable_durable_receipt(world,monkeypatch):
    import httpx
    from backend.shipment_notifications import ShipmentNotificationWorker
    from backend.email_delivery import EmailReceipt
    from test_sender_notifications import config,settings
    w=world;_,_=await setup(w)
    row=await w.db.fetchrow('SELECT recipient_address FROM public.shipments WHERE id=$1',w.shipments[0])
    await save_permission(w.db,w.tenants[0],w.shipments[0],row,RecipientPermission(email=True,email_permission_confirmed=True),actor=w.actors[0])
    await stage_recipient_notifications(w.db,w.tenants[0],w.shipments[0],'DELIVERED')
    sender_ready=await w.db.fetchval("SELECT count(*) FROM public.shipment_sender_notifications WHERE audience='SENDER' AND state='READY'")
    assert sender_ready>0
    cfg=config();assert not cfg.shipment_recipient_notifications_enabled
    cfg.shipment_recipient_notifications_enabled=True;cfg.shipment_notification_test_recipients=['recipient@example.test']
    calls=[]
    async def send(client,delivery_config,**message):
        assert await w.db.fetchval("SELECT state FROM public.shipment_sender_notifications WHERE audience='RECIPIENT'")=='SENDING'
        calls.append(message)
        return EmailReceipt('ACCEPTED','fixture-email-receipt')
    monkeypatch.setattr('backend.shipment_notifications.send_notification_email',send)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:pytest.fail('No provider network calls'))) as client:
        delivery_settings=settings();delivery_settings.booking_page_url='https://uat.easyinvio.com/login'
        worker=ShipmentNotificationWorker(SimpleNamespace(pool=w.db,client=client,automation=SimpleNamespace(settings=delivery_settings)),cfg,audience='RECIPIENT')
        assert await worker.drain()
        assert not await worker.drain()
    assert len(calls)==1
    assert await w.db.fetchval("SELECT count(*) FROM public.shipment_sender_notifications WHERE audience='SENDER' AND state='READY'")==sender_ready
    assert calls[0]['recipient']=='recipient@example.test'
    assert 'Fixture Brand' in calls[0]['text'] and '/track?q=PARCEL-000000' in calls[0]['text']
    assert 'Private Street' not in calls[0]['text']


@pytest.mark.asyncio
async def test_merchant_branding_routes_reject_other_tenants_and_invalid_urls(world):
    import httpx
    from fastapi import FastAPI
    from backend.post_purchase import build_router
    w=world;_,stores=await setup(w)
    actor=SimpleNamespace(tenant_id=w.tenants[0],user_id=w.actors[0],role='OWNER')
    async def authenticate():return actor
    app=FastAPI();app.state.ecommerce=SimpleNamespace(pool=w.db);app.state.finance=SimpleNamespace(pool=w.db);app.state.tracking_workspace=w.engine
    app.include_router(build_router(authenticate))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://app.example.test') as client:
        own=await client.get(f'/api/v1/workspace/stores/{stores[0]}/post-purchase');assert own.status_code==200,own.text
        other=await client.get(f'/api/v1/workspace/stores/{stores[1]}/post-purchase');assert other.status_code==404
        invalid=await client.put(f'/api/v1/workspace/stores/{stores[0]}/post-purchase',json={'brand_logo_url':'http://127.0.0.1/private'});assert invalid.status_code==422
        valid=await client.put(f'/api/v1/workspace/stores/{stores[0]}/post-purchase',json={'brand_display_name':'New Merchant','brand_accent_hex':'#059669','brand_logo_url':'https://shop.example.test/logo.svg'});assert valid.status_code==200,valid.text
        logo=await client.get('/api/v1/public/tracking/brand-logo',params={'url':'https://shop.example.test/logo.svg'})
        assert logo.status_code==200
        assert "img-src https://shop.example.test;" in logo.headers['content-security-policy']
        assert "img-src https:;" not in logo.headers['content-security-policy']
        assert 'sandbox' in logo.headers['content-security-policy']
        missing=await client.get('/api/v1/public/tracking/brand-logo',params={'url':'https://other.example.test/logo.svg'});assert missing.status_code==404
        actor.role='DISPATCHER'
        forbidden=await client.put(f'/api/v1/workspace/stores/{stores[0]}/post-purchase',json={});assert forbidden.status_code==403
        wrong_consent=await client.put(f'/api/v1/shipping/{w.shipments[1]}/recipient-notifications',json={});assert wrong_consent.status_code==404


def test_public_logo_origin_validation_rejects_policy_injection():
    from backend.post_purchase import public_https
    for url in ['https://127.0.0.1/logo','https://localhost/logo','https://cdn.example;script-src*/logo','https://cdn.example/\nlogo','https://user:password@cdn.example/logo','https://cdn.example:8443/logo']:
        with pytest.raises(ValueError):public_https(url)
    assert public_https('HTTPS://CDN.EXAMPLE/logo.svg')=='https://cdn.example/logo.svg'
