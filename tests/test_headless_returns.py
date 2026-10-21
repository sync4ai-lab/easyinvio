"""Synthetic return commands: no live database, labels, card charges or emails."""
import asyncio
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from backend.reverse_logistics import ReturnCommand, ReverseLogisticsService, cheapest_return, process_batch
from backend.return_documents import public_return_links, verify_dropoff_token, request_easypost_qr
from backend.automation_three_partners import (EasyPostAdapter, SendcloudAdapter, PartnerLifecycleService,
    ReturnRequest, prepare_return_quote, build_router)
from backend.automation_freight_engine import PurchaseUncertain
from backend.carrier_access import verified_return_parent, return_accounts


class Store:
    def __init__(self, context):
        self.context = context
        self.parent_id, self.store_id, self.child_id = uuid4(), uuid4(), uuid4()
        self.commands, self.shipments, self.calls = {}, {}, []
        self.mutex = asyncio.Lock()
        self.warehouse = {'id':uuid4(),'version':1,'address':{
            'name':'Returns','line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}}

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        async with self.mutex:
            yield self

    async def fetch(self, sql, *args):
        self.calls.append((sql,args))
        if 'FROM public.shipments' in sql:
            if args[0] != self.context.tenant_id or (args[3] and args[3] != self.store_id):
                return []
            if args[1] == self.parent_id or args[2] in {'ORDER-1','TRACK-1'}:
                return [{'id':self.parent_id,'ecommerce_store_id':self.store_id,'status':'DELIVERED'}]
            return []
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        self.calls.append((sql,args))
        if 'to_regclass' in sql:
            return True
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        self.calls.append((sql,args))
        if 'FROM public.reverse_logistics_requests' in sql:
            return next((row for row in self.commands.values() if row['tenant_id']==args[0]
                and (row['id']==args[1] or len(args)>2 and row['original_shipment_id']==args[2])),None)
        if 'tenant_catalog_addresses' in sql:
            return self.warehouse
        if 'FROM public.shipments' in sql:
            return self.shipments.get(args[1]) if args[0]==self.context.tenant_id else None
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        self.calls.append((sql,args))
        if 'pg_advisory_xact_lock' in sql:
            return 'SELECT 1'
        if 'INSERT INTO public.reverse_logistics_requests' in sql:
            tenant,key,parent,user,source,bearer,digest = args
            self.commands[key] = {'tenant_id':tenant,'id':key,'original_shipment_id':parent,
                'requested_by':user,'source':source,'charge_bearer':bearer,'input_sha256':digest,
                'state':'PROCESSING','return_shipment_id':None,'response':{}}
        elif 'UPDATE public.reverse_logistics_requests' in sql:
            row = self.commands[args[1]]
            if "state='REVIEW_REQUIRED'" in sql:
                row['state']='REVIEW_REQUIRED'
                row['response'].update(status='REVIEW_REQUIRED',message=args[2])
            elif "state='BOOKED'" in sql:
                row.update(state='BOOKED',response=json.loads(args[2]))
            else:
                row.update(state=args[2],return_shipment_id=args[3],response=json.loads(args[4]))
        else:
            raise AssertionError(sql)


def setup():
    context = SimpleNamespace(tenant_id=uuid4(),user_id=uuid4(),role='OWNER',bearer_token='',assistance_session_id=None)
    pool = Store(context)
    settings = SimpleNamespace(quote_link_secret=SecretStr('synthetic-key-for-returns-tests-only-123456'),booking_page_url='https://example.test/')
    lifecycle = PartnerLifecycleService(SimpleNamespace(pool=pool,finance=None,settings=settings),None)
    lifecycle.confirm = AsyncMock(return_value={'status':'BOOKED','shipment_id':str(pool.child_id),
        'label':{'tracking_number':'RETURN-1','label_url':'/private/label'},'paperless_available':False})
    prepared = {'status':'QUOTED','shipment_id':str(pool.child_id),'partial':False,'all_rates':[
        {'offer_id':str(uuid4()),'carrier_code':'EVRI','currency':'GBP','client_price_ex_tax':'4.25'},
        {'offer_id':str(uuid4()),'carrier_code':'UPS','currency':'GBP','client_price_ex_tax':'8.00'}]}
    command = ReturnCommand(shipment_id=pool.parent_id,idempotency_key=uuid4())
    return context,pool,lifecycle,prepared,command


@pytest.mark.asyncio
async def test_retailer_return_uses_native_confirmation_and_replay_never_purchases_again():
    context,pool,lifecycle,prepared,command = setup()
    with patch('backend.automation_three_partners.prepare_return_quote',AsyncMock(return_value=prepared)) as quote:
        service = ReverseLogisticsService(lifecycle)
        result = await service.process(context,command)
        replay = await service.process(context,command)
    assert result['status']=='BOOKED' and replay['replayed']
    assert result['amount']=='4.25'
    assert lifecycle.confirm.await_count==1 and quote.await_count==1
    assert str(lifecycle.confirm.call_args.args[1].offer_id)==prepared['all_rates'][0]['offer_id']
    assert pool.commands[command.idempotency_key]['requested_by']==context.user_id
    assert any('pg_advisory_xact_lock' in sql for sql,_ in pool.calls)


@pytest.mark.asyncio
async def test_same_parent_with_another_key_or_same_key_changed_price_is_rejected():
    context,pool,lifecycle,prepared,command = setup()
    with patch('backend.automation_three_partners.prepare_return_quote',AsyncMock(return_value=prepared)):
        service=ReverseLogisticsService(lifecycle)
        await service.process(context,command)
        for different in [command.model_copy(update={'idempotency_key':uuid4()}),command.model_copy(update={'maximum_price':Decimal('99.00')})]:
            with pytest.raises(HTTPException) as exc:
                await service.process(context,different)
            assert exc.value.status_code==409
    assert lifecycle.confirm.await_count==1


@pytest.mark.asyncio
async def test_concurrent_duplicate_commands_cannot_buy_twice():
    context,pool,lifecycle,prepared,command=setup()
    gate=asyncio.Event()
    async def quote(*args,**kwargs):
        await gate.wait()
        return prepared
    with patch('backend.automation_three_partners.prepare_return_quote',quote):
        service=ReverseLogisticsService(lifecycle)
        first=asyncio.create_task(service.process(context,command))
        await asyncio.sleep(0)
        second=await service.process(context,command)
        assert second['status']=='PROCESSING'
        gate.set()
        await first
    assert lifecycle.confirm.await_count==1


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['warehouse','partial','ceiling','uncertain'])
async def test_failed_or_uncertain_return_stays_fenced(case):
    context,pool,lifecycle,prepared,command=setup()
    if case=='warehouse':pool.warehouse=None
    if case=='partial':prepared['partial']=True
    if case=='ceiling':command=command.model_copy(update={'maximum_price':Decimal('1.00')})
    if case=='uncertain':lifecycle.confirm.side_effect=TimeoutError()
    with patch('backend.automation_three_partners.prepare_return_quote',AsyncMock(return_value=prepared)):
        service=ReverseLogisticsService(lifecycle)
        with pytest.raises(HTTPException):await service.process(context,command)
        replay=await service.process(context,command)
    assert replay['status']=='REVIEW_REQUIRED'
    assert lifecycle.confirm.await_count==(1 if case=='uncertain' else 0)


@pytest.mark.asyncio
async def test_customer_pay_creates_exact_card_basket_without_wallet_booking():
    context,pool,lifecycle,prepared,command=setup()
    command=command.model_copy(update={'charge_bearer':'CUSTOMER_PAY'})
    with patch('backend.automation_three_partners.prepare_return_quote',AsyncMock(return_value=prepared)),patch(
            'backend.card_checkout.create_cart',AsyncMock(return_value={'url':'https://checkout.stripe.com/test','cart_id':str(command.idempotency_key)})) as checkout:
        result=await ReverseLogisticsService(lifecycle).process(context,command)
    assert result['status']=='PAYMENT_REQUIRED'
    assert checkout.call_args.args[2].offers[0].expected_price==Decimal('4.25')
    lifecycle.confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_tenant_store_and_financial_role_denied_before_purchase():
    context,pool,lifecycle,prepared,command=setup()
    service=ReverseLogisticsService(lifecycle)
    with pytest.raises(HTTPException) as exc:
        await service.process(SimpleNamespace(**(vars(context)|{'tenant_id':uuid4()})),command)
    assert exc.value.status_code==404
    with pytest.raises(HTTPException) as exc:
        await service.process(context,command,store_id=uuid4())
    assert exc.value.status_code==404
    context.role='DISPATCHER'
    with pytest.raises(HTTPException) as exc:
        await service.process(context,command.model_copy(update={'charge_bearer':'CUSTOMER_PAY'}))
    assert exc.value.status_code==403
    assert not pool.commands


def test_cheapest_exact_price_and_budget_tie_without_overpaying():
    def rate(carrier,price):return {'offer_id':str(uuid4()),'carrier_code':carrier,'client_price_ex_tax':price,'currency':'GBP'}
    assert cheapest_return([rate('UPS','4.00'),rate('Evri','4.00')])['carrier_code']=='Evri'
    assert cheapest_return([rate('UPS','3.99'),rate('Evri','4.00')])['carrier_code']=='UPS'
    for rates in [[],[rate('Evri','NaN')],[rate('Evri','-1')]]:
        with pytest.raises(HTTPException):cheapest_return(rates)


@pytest.mark.asyncio
async def test_new_warehouse_is_scoped_versioned_and_original_customer_cannot_change():
    buyer={'name':'Buyer','line1':'2 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
    warehouse={**buyer,'name':'Warehouse','line1':'3 Test Road'}
    original={**buyer,'name':'Original','line1':'1 Test Road'}
    account,tenant,parent,wid=uuid4(),uuid4(),uuid4(),uuid4()
    connection=SimpleNamespace(fetchrow=AsyncMock(side_effect=[
        {'carrier_account_id':account,'logistics_metadata':{'automation_order':{'origin':original,'destination':buyer}}},
        {'version':2,'address':warehouse}]))
    assert await verified_return_parent(connection,tenant,parent,buyer,warehouse,warehouse_id=wid,warehouse_version=2)==account
    assert connection.fetchrow.call_args.args[1:]==(tenant,wid)
    connection.fetchrow.side_effect=[{'carrier_account_id':account,'logistics_metadata':{'automation_order':{'origin':original,'destination':buyer}}},{'version':3,'address':warehouse}]
    with pytest.raises(HTTPException) as exc:await verified_return_parent(connection,tenant,parent,buyer,warehouse,warehouse_id=wid,warehouse_version=2)
    assert exc.value.status_code==409


@pytest.mark.asyncio
async def test_headless_network_never_reenables_retired_accounts():
    repository=SimpleNamespace(accounts=AsyncMock(return_value=[]))
    context=SimpleNamespace(tenant_id=uuid4())
    await return_accounts(repository,context,uuid4(),all_active=True)
    assert repository.accounts.call_args.kwargs=={}


@pytest.mark.asyncio
async def test_return_quote_swaps_customer_to_catalog_warehouse_and_clears_old_consent():
    context,pool,lifecycle,_,command=setup()
    origin=pool.warehouse['address']|{'name':'Original sender'}
    destination=origin|{'name':'Customer'}
    pool.shipments[pool.parent_id]={'logistics_metadata':{'automation_order':{'origin':origin,'destination':destination,
        'order_reference':'ORDER-1','packages':[],'customs_signer':'Old signer','hs_codes_reviewed':True}},
        'tracking_number':'FORWARD-1','booked_at':datetime.now(timezone.utc),'carrier_code':'DPD'}
    lifecycle.automation.order_limiter=asyncio.Semaphore(1)
    pool.shipments[pool.parent_id]['logistics_metadata']['automation_order']['cargo'] = {
        'cargo_type':'PARCEL','actual_weight_kg':'1.000','length_cm':'20','width_cm':'15','height_cm':'10'}
    lifecycle.automation.process=AsyncMock(return_value={'status':'QUOTED'})
    body=ReturnRequest(tenant_id=context.tenant_id,shipment_id=pool.parent_id,idempotency_key=command.idempotency_key)
    await prepare_return_quote(lifecycle,context,body,warehouse=pool.warehouse,paperless_requested=True)
    order=lifecycle.automation.process.call_args.args[1]
    assert order['origin']==destination and order['destination']==pool.warehouse['address']
    assert order['return_network_selection'] and order['paperless_requested']
    assert order['customs_signer'] is None and not order['hs_codes_reviewed']
    assert order['customs_category']=='RETURN'


@pytest.mark.asyncio
@pytest.mark.parametrize('supported',[True,False])
async def test_sendcloud_labelless_flag_and_confirmed_dropoff_document(supported):
    calls=[]
    async def provider(request):
        calls.append(request)
        if request.method=='POST':
            body=json.loads(request.content)
            assert body['delivery_option']==('drop_off_labelless' if supported else 'drop_off_point')
            assert body['ship_with']['contract']==10
            assert 'generate_qr_code' not in body
            return httpx.Response(201,json={'return_id':123})
        return httpx.Response(200,json={'tracking_number':'RETURN-1','label':{'label_printer':'https://panel.sendcloud.sc/label.pdf'},
            'delivery_option':'drop_off_labelless' if supported else 'drop_off_point'})
    address={'name':'Buyer','line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
    snapshot={'origin':address,'destination':address,'cargo':{'actual_weight_kg':'1.5','length_cm':'20','width_cm':'15','height_cm':'10'},
        'return_quote_authorized':True,'return_rate_id':'evri:return','order_reference':'RETURN-1',
        'contract_id':10,'paperless_requested':True,'return_paperless_supported':supported}
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        adapter=SendcloudAdapter(client,'{"public_key":"synthetic","secret_key":"synthetic"}',environment='LIVE')
        label=await adapter.generate_return_label(snapshot)
    assert bool(label.get('return_dropoff_qr_code_url'))==supported
    assert len(calls)==2


@pytest.mark.asyncio
async def test_easypost_qr_failure_preserves_label_and_submitted_form_is_not_retried():
    pool=SimpleNamespace()
    pool.fetchval=AsyncMock(side_effect=[True,False])
    @asynccontextmanager
    async def acquire():yield pool
    pool.acquire=acquire
    adapter=EasyPostAdapter(None,'synthetic',environment='TEST')
    adapter.request=AsyncMock(side_effect=TimeoutError())
    account=SimpleNamespace(tenant_id=uuid4(),id=uuid4())
    rate=SimpleNamespace(offer_id=uuid4(),carrier_code='USPS')
    label={'upstream_id':'shp_test','tracking_number':'RETURN-1','label_url':'https://example.test/label.pdf'}
    for _ in range(2):assert await request_easypost_qr(pool,adapter,account,rate,{},label)==label
    assert adapter.request.await_count==1
    assert adapter.request.call_args.args==('POST','/shipments/shp_test/forms',{'form':{'type':'label_qr_code'}})


def test_qr_capability_token_is_tenant_document_scoped_and_rejects_other_audience_or_expiry():
    context,_,lifecycle,_,_=setup()
    shipment=uuid4()
    reply=public_return_links(lifecycle.automation.settings,context,{'shipment_id':str(shipment),'paperless_available':True})
    token=reply['return_dropoff_qr_code_url'].split('token=')[1]
    assert verify_dropoff_token(lifecycle.automation.settings,token)==(context.tenant_id,shipment)
    key=lifecycle.automation.settings.quote_link_secret.get_secret_value()
    claims=jwt.decode(token,key,algorithms=['HS256'],audience='return-dropoff-document')
    for changes in [{'aud':'veloce-booking'},{'exp':1},{'s':'bad'},{'iat':claims['iat']-90000}]:
        bad=jwt.encode(claims|changes,key,algorithm='HS256')
        with pytest.raises(HTTPException):verify_dropoff_token(lifecycle.automation.settings,bad)


@pytest.mark.asyncio
async def test_signed_store_return_requires_timestamp_signature_and_real_dispatch_membership():
    from backend.ecommerce_connectors import StoreConnector
    from backend.return_ingress import receive_return_webhook
    context,pool,lifecycle,_,command=setup()
    config=StoreConnector(tenant_id=context.tenant_id,auth_user_id=context.user_id,platform='AMAZON',
        webhook_secret='synthetic-returns-webhook-secret-123456',live_returns=True)
    pool.fetchrow=AsyncMock(return_value={'role':'DISPATCHER'})
    ecommerce=SimpleNamespace(pool=pool,prepare_returns=AsyncMock(return_value={'booked':1}))
    app=FastAPI();app.state.ecommerce=ecommerce;app.state.partner_lifecycle=lifecycle
    @app.post('/returns/{store_id}')
    async def endpoint(store_id:str,request:Request):return await receive_return_webhook(request,store_id)
    raw=json.dumps([command.model_dump(mode='json')]).encode();timestamp=str(int(time.time()))
    # Store identity is UUID-normalized in production; use the same wire token.
    signature=hmac.new(config.webhook_secret.get_secret_value().encode(),timestamp.encode()+b'.'+str(pool.store_id).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    headers={'content-type':'application/json','x-easyinvio-timestamp':timestamp,'x-easyinvio-return-signature':signature}
    with patch('backend.store_connections.resolve_connector',AsyncMock(return_value=config)):
        with TestClient(app) as client:
            assert client.post('/returns/'+str(pool.store_id),content=raw,headers=headers).status_code==200
            assert client.post('/returns/'+str(pool.store_id),content=raw+b' ',headers=headers).status_code==401
            assert client.post('/returns/'+str(pool.store_id),content=raw,headers=headers|{'x-easyinvio-timestamp':'1'}).status_code==401
            pool.fetchrow.return_value={'role':'ACCOUNTANT'}
            assert client.post('/returns/'+str(pool.store_id),content=raw,headers=headers).status_code==403
    assert ecommerce.prepare_returns.await_count==1
    assert ecommerce.prepare_returns.call_args.kwargs['source']=='MARKETPLACE'


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['return order EINVIO-1024','create a return for tracking DPD-7712'])
async def test_chat_return_is_deterministic_and_does_not_need_a_model(text):
    from backend.agents.conversational_gateway import ConversationalActionGateway
    gateway=ConversationalActionGateway(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))
    intent=await gateway.interpret(None,text)
    assert intent.intent=='TRIGGER_RETURN'
    assert intent.target_reference_id==text.split()[-1]


def test_return_reference_schema_and_route_authentication():
    for data in [{'idempotency_key':str(uuid4())},{'idempotency_key':str(uuid4()),'shipment_id':str(uuid4()),'order_reference':'ORDER-1'},
                 {'idempotency_key':str(uuid4()),'order_reference':'ORDER-1','charge_bearer':'OTHER'}]:
        with pytest.raises(ValidationError):ReturnCommand.model_validate(data)
    app=FastAPI()
    async def unauthorized():raise HTTPException(401,'Sign in')
    app.include_router(build_router(unauthorized))
    with TestClient(app) as client:
        assert client.post('/api/v1/shipping/prepare-return',json=[{'order_reference':'ORDER-1','idempotency_key':str(uuid4())}]).status_code==401


@pytest.mark.asyncio
async def test_accepted_sendcloud_announcement_with_rejected_document_lookup_is_uncertain():
    async def provider(request):
        return httpx.Response(201,json={'return_id':123}) if request.method=='POST' else httpx.Response(404,json={})
    address={'name':'Buyer','line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
    snapshot={'origin':address,'destination':address,'cargo':{'actual_weight_kg':'1','length_cm':'20','width_cm':'15','height_cm':'10'},
        'return_quote_authorized':True,'return_rate_id':'evri:return','order_reference':'RETURN-1'}
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        adapter=SendcloudAdapter(client,'{"public_key":"synthetic","secret_key":"synthetic"}',environment='LIVE')
        with pytest.raises(PurchaseUncertain):await adapter.generate_return_label(snapshot)
        assert adapter.last_remote_id=='123'


@pytest.mark.asyncio
async def test_qr_form_success_returns_real_url_and_unrelated_carrier_makes_no_call():
    pool=SimpleNamespace(fetchval=AsyncMock(return_value=True))
    @asynccontextmanager
    async def acquire():yield pool
    pool.acquire=acquire
    adapter=EasyPostAdapter(None,'synthetic',environment='TEST')
    adapter.request=AsyncMock(return_value={'id':'shp_test','mode':'test','forms':[
        {'form_type':'label_qr_code','form_url':'https://easypost-files.s3.amazonaws.com/dropoff.png'}]})
    account=SimpleNamespace(tenant_id=uuid4(),id=uuid4())
    rate=SimpleNamespace(offer_id=uuid4(),carrier_code='USPS')
    label={'upstream_id':'shp_test','tracking_number':'RETURN-1','label_url':'https://example.test/label.pdf'}
    result=await request_easypost_qr(pool,adapter,account,rate,{},label)
    assert result['return_dropoff_qr_code_url'].endswith('/dropoff.png')
    rate.carrier_code='Royal Mail'
    await request_easypost_qr(pool,adapter,account,rate,{},label)
    assert adapter.request.await_count==1


def test_batch_route_success_preserves_private_projection_and_per_item_results():
    context,pool,lifecycle,prepared,command=setup()
    app=FastAPI();app.state.partner_lifecycle=lifecycle
    app.include_router(build_router(lambda:context))
    with patch('backend.automation_three_partners.prepare_return_quote',AsyncMock(return_value=prepared)):
        with TestClient(app) as client:
            result=client.post('/api/v1/shipping/prepare-return',json=[command.model_dump(mode='json')])
            assert result.status_code==200
            assert result.json()['booked']==1 and result.json()['requested']==1
            assert client.get('/api/v1/shipping/return-requests/'+str(command.idempotency_key)).status_code==200
