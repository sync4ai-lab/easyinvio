"""Offline boundary tests: no configured services, credentials or DB are used."""
import ast
import hashlib
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI,HTTPException
from pydantic import SecretStr
from backend.ecommerce_connectors import StoreConnector
from backend.ecommerce_sync import EcommerceService
from backend.custom_stores import build_router,signature
from backend.platform_registry import PLATFORMS
from backend.store_returns_portal import build_router as portal_router
from backend.store_transport import https_url,store_json

@asynccontextmanager
async def apatch(*args,**kwargs):
    with patch(*args,**kwargs) as value:
        yield value

class Pool:
    def __init__(self):
        self.tenant,self.store,self.actor=uuid4(),uuid4(),uuid4()
        self.commands=[];self.config=None;self.event=None;self.portal=None;self.shipment=None;self.session=None
    @asynccontextmanager
    async def acquire(self): yield self
    @asynccontextmanager
    async def transaction(self): yield self
    async def fetchrow(self,sql,*args):
        self.commands.append((sql,args))
        if 'workspace_store_connections' in sql: return self.config if args[-1]==self.store else None
        if 'token_sha256=$3' in sql:
            if self.session and args[:2]==(self.store,self.tenant) and args[2]==self.session['token_sha256']: return self.session
            return None
        if 'store_slug=$1' in sql: return self.portal if args[0]=='sample-shop' else None
        if 'SELECT u.role' in sql: return {'role':'OWNER'}
        if 'billing_address' in sql: return {'legal_company_name':'Fixture warehouse','billing_address':{'name':'Warehouse','line1':'1 Fixture Street','city':'Leeds','postal_code':'LS12 6EJ','country_code':'GB'}}
        if 'FROM public.shipments' in sql: return self.shipment
    async def fetch(self,sql,*args):
        self.commands.append((sql,args))
        if 'tracking_outbox' in sql:
            return [self.event] if self.event and args==(self.tenant,'1042') else []
        if 'FROM public.shipments' in sql:
            return [self.shipment] if args[:2]==(self.tenant,self.store) and args[2]=='#1042' else []
        return []
    async def fetchval(self,sql,*args):
        self.commands.append((sql,args))
        if 'UPDATE public.ecommerce_tracking_outbox' in sql:
            self.event['status']='RECONCILIATION_REQUIRED';self.event['attempts']+=1;return self.event['id']
        if "state='PROCESSING'" in sql:
            if self.session['state']!='VERIFIED': return None
            self.session['state']='PROCESSING';return self.session['id']
        return None
    async def execute(self,sql,*args):
        self.commands.append((sql,args))
        if 'INSERT INTO public.store_checkout_cache' in sql: assert isinstance(args[4],datetime)
        if 'INSERT INTO public.store_return_sessions' in sql:
            self.session=dict(zip(['id','tenant_id','store_id','shipment_id','request_id','token_sha256','policy_sha256'],args),state='VERIFIED')
        if 'UPDATE public.store_return_sessions' in sql:
            if "state='SUBMITTED'" in sql:self.session['state']='SUBMITTED'
            if "state='REVIEW_REQUIRED'" in sql:self.session['state']='REVIEW_REQUIRED'
        if 'UPDATE public.ecommerce_tracking_outbox' in sql:
            if "status='DELIVERED'" in sql:self.event['status']='DELIVERED'
            elif "status='SIMULATED_DELIVERED'" in sql:self.event['status']='SIMULATED_DELIVERED'
            elif 'LIVE_DELIVERY_DISABLED' in sql:self.event['store_sync_error_code']='LIVE_DELIVERY_DISABLED'

def encrypted_config(pool,platform='CUSTOM_WEBSITE',**kwargs):
    key=Fernet.generate_key()
    defaults={'tenant_id':pool.tenant,'auth_user_id':pool.actor,'platform':platform,'webhook_secret':'fixture-signing-secret-32-characters-long','api_key_id':'fixture-key',**kwargs}
    if platform=='CUSTOM_WEBSITE':defaults['store_url']='https://retailer.example.com'
    config=StoreConnector(**defaults)
    values=config.model_dump(mode='json')
    for name in ('webhook_secret','access_token','client_secret','amazon_client_secret','amazon_refresh_token'):
        value=getattr(config,name);values[name]=value.get_secret_value() if value else None
    values['store_id']=str(pool.store)
    pool.config={'tenant_id':pool.tenant,'credential_key_id':'k','credentials_ciphertext':Fernet(key).encrypt(json.dumps(values).encode())}
    return config,{'k':SecretStr(key.decode())}

def signed_headers(config,store_id,path,raw,stamp=None):
    stamp=stamp or str(int(time.time()))
    return {'Content-Type':'application/json','X-EasyInvio-Store-Id':str(store_id),'X-EasyInvio-Key-Id':config.api_key_id,
        'X-EasyInvio-Timestamp':stamp,'X-EasyInvio-Signature':signature(config.webhook_secret.get_secret_value(),stamp,'POST',path,store_id,raw)}

@pytest.mark.asyncio
async def test_signed_custom_orders_binding_and_tampering():
    pool=Pool();config,keys=encrypted_config(pool)
    service=EcommerceService(pool,credential_keys=keys)
    service.import_order=AsyncMock(return_value={'shipment_id':str(uuid4()),'status':'PENDING_IMPORT','replayed':False})
    app=FastAPI();app.state.ecommerce=service;app.include_router(build_router())
    path='/api/v1/integration/custom-store/orders'
    raw=json.dumps({'id':'1042','name':'#1042','currency':'GBP','shipping_address':{'name':'Customer','address1':'1 Test Street','city':'Leeds','zip':'LS12 6EJ','country_code':'GB'},'line_items':[{'title':'Shirt','quantity':1,'grams':'200'}]}).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://local.test') as client,apatch('backend.custom_stores.throttle',new=AsyncMock()):
        headers=signed_headers(config,pool.store,path,raw)
        assert (await client.post(path,content=raw,headers=headers)).status_code==201
        context,payload=service.import_order.call_args.args
        assert context.tenant_id==pool.tenant and payload.store_id==pool.store and payload.platform=='CUSTOM_WEBSITE'
        assert (await client.post(path,content=raw+b' ',headers=headers)).status_code==401
        headers=signed_headers(config,pool.store,path,raw,str(int(time.time())-301))
        assert (await client.post(path,content=raw,headers=headers)).status_code==401
        headers=signed_headers(config,pool.store,path,raw);headers['X-EasyInvio-Store-Id']=str(uuid4())
        assert (await client.post(path,content=raw,headers=headers)).status_code==401
        assert service.import_order.await_count==1

@pytest.mark.asyncio
async def test_live_checkout_invokes_workspace_rating_without_wholesale_leakage():
    pool=Pool();config,keys=encrypted_config(pool);service=EcommerceService(pool,credential_keys=keys)
    app=FastAPI();app.state.ecommerce=service
    app.state.rating=SimpleNamespace(quote=AsyncMock(return_value=SimpleNamespace(partial=False,expires_at=datetime.now(timezone.utc),
        rates=[SimpleNamespace(carrier_code='EVRI',service_code='Standard',client_price_ex_tax=Decimal('3.49'),currency='GBP',delivery_days=3,wholesale_cost=Decimal('2.10'))])))
    app.include_router(build_router());path='/api/v1/integration/custom-store/checkout-rates'
    raw=json.dumps({'weight_kg':'2','length_cm':'25','width_cm':'20','height_cm':'15','destination':{'name':'Customer','line1':'1 Test Street','city':'Leeds','postal_code':'LS12 6EJ','country_code':'GB'}}).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://local.test') as client,apatch('backend.custom_stores.throttle',new=AsyncMock()),apatch('backend.entitlements.guard_feature',new=AsyncMock()):
        response=await client.post(path,content=raw,headers=signed_headers(config,pool.store,path,raw))
        assert response.status_code==200,response.text
        assert response.json()['rates'][0]['price_ex_tax']=='3.49'
        assert 'wholesale' not in response.text and '2.10' not in response.text
        context,body=app.state.rating.quote.call_args.args
        assert context.tenant_id==pool.tenant and body.weights_kg==[Decimal('2')]

@pytest.mark.asyncio
@pytest.mark.parametrize('platform',['SHOPIFY','WOOCOMMERCE'])
async def test_live_delivery_uses_encrypted_database_connection(platform):
    pool=Pool();options={'shop_domain':'fixture.myshopify.com','access_token':'fixture-token'} if platform=='SHOPIFY' else {'store_url':'https://retailer.example.com','client_id':'fixture-key','client_secret':'fixture-secret'}
    _,keys=encrypted_config(pool,platform,live_delivery=True,**options)
    calls=[]
    def remote(request):
        calls.append(request)
        if platform=='SHOPIFY':
            if 'fulfillmentCreate' in request.content.decode():return httpx.Response(200,json={'data':{'fulfillmentCreate':{'fulfillment':{'id':'remote-1','status':'SUCCESS'},'userErrors':[]}}})
            return httpx.Response(200,json={'data':{'order':{'fulfillments':[],'fulfillmentOrders':{'pageInfo':{'hasNextPage':False},'nodes':[{'id':'fo-1','status':'OPEN','assignedLocation':{'location':{'id':'loc-1'}}}]}}}})
        if request.method=='GET':return httpx.Response(200,json=[] if request.url.path.endswith('/notes') else {'id':1042,'status':'processing','meta_data':[]})
        if request.method=='PUT':assert json.loads(request.content)['status']=='completed'
        return httpx.Response(200,json={'id':1})
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        service=EcommerceService(pool,connectors={},credential_keys=keys,client=client,settings=SimpleNamespace(provider_environment='LIVE'))
        pool.event={'id':uuid4(),'shipment_id':uuid4(),'store_id':pool.store,'platform':platform,'status':'PENDING','attempts':0,
            'payload':{'store_order_id':'1042','tracking_number':'TRACK-1','carrier_name':'UPS','tracking_lifecycle_type':'FORWARD_SHIPMENT'}}
        await service.push(pool.tenant,'1042','TRACK-1','UPS')
        assert pool.event['status']=='DELIVERED' and calls
        previous=len(calls);await service.push(pool.tenant,'1042','TRACK-1','UPS');assert len(calls)==previous
        assert any('workspace_store_connections' in sql for sql,_ in pool.commands)

@pytest.mark.asyncio
async def test_live_disabled_never_simulates_or_sends():
    pool=Pool();_,keys=encrypted_config(pool)
    pool.event={'id':uuid4(),'shipment_id':uuid4(),'store_id':pool.store,'platform':'CUSTOM_WEBSITE','status':'PENDING','attempts':0,
        'payload':{'store_order_id':'1042','tracking_number':'TRACK-1','carrier_name':'UPS'}}
    service=EcommerceService(pool,credential_keys=keys,settings=SimpleNamespace(provider_environment='LIVE'))
    await service.push(pool.tenant,'1042','TRACK-1','UPS')
    assert pool.event['status']=='PENDING' and pool.event['store_sync_error_code']=='LIVE_DELIVERY_DISABLED'

@pytest.fixture
def shopper_app():
    pool=Pool()
    pool.portal={'id':pool.store,'tenant_id':pool.tenant,'display_name':'Fixture retailer','role':'OWNER',
        'return_policy_authorized_by':pool.actor,'return_policy':{'enabled':True,'return_window_days':30,'maximum_price':'10.00'}}
    pool.shipment={'id':uuid4(),'tenant_id':pool.tenant,'status':'DELIVERED','currency':'GBP','delivered_at':datetime.now(timezone.utc),
        'recipient_address':{'postal_code':'LS12 6EJ','email':'shopper@example.test'},'logistics_metadata':{'automation_order':{
        'origin':{'country_code':'GB'},'destination':{'country_code':'GB'},'items':[{'description':'Shirt','quantity':1}]}}}
    app=FastAPI();app.state.ecommerce=SimpleNamespace(pool=pool);app.state.partner_lifecycle=SimpleNamespace(pool=pool)
    async def auth():return SimpleNamespace(tenant_id=pool.tenant,user_id=pool.actor,role='OWNER')
    app.include_router(portal_router(auth));return app,pool

@pytest.mark.asyncio
@pytest.mark.parametrize('verification',['ls126ej','SHOPPER@example.test'])
async def test_shopper_verification_rejects_wrong_value_before_disclosing_items(shopper_app,verification):
    app,pool=shopper_app;path='/api/v1/public/store-returns/sample-shop/verify'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://local.test') as client,apatch('backend.store_returns_portal.throttle',new=AsyncMock()):
        bad=await client.post(path,json={'order_reference':'#1042','verification_value':'wrong@example.test'})
        assert bad.status_code==404 and 'Shirt' not in bad.text
        good=await client.post(path,json={'order_reference':'#1042','verification_value':verification})
        assert good.status_code==200 and good.json()['items'][0]['description']=='Shirt'
        assert hashlib.sha256(good.json()['token'].encode()).hexdigest()==pool.session['token_sha256']
        assert good.json()['token']!=pool.session['token_sha256']

@pytest.mark.asyncio
@pytest.mark.parametrize('paid,status',[('RETAILER_PAY','BOOKED'),('CUSTOMER_PAY','PAYMENT_REQUIRED')])
async def test_portal_selects_cheapest_and_payment_gates_documents(shopper_app,paid,status):
    app,pool=shopper_app;pool.portal['return_policy']['charge_bearer']=paid
    offer1,offer2=uuid4(),uuid4()
    result={'status':status,'label_path':'internal/label','qr_path':'internal/qr'}
    if status=='PAYMENT_REQUIRED':result['checkout_url']='https://checkout.stripe.com/c/pay/cs_test_fixture'
    review=SimpleNamespace(context=AsyncMock(return_value={'destination':{'country_code':'GB'},'edits':{'cargo':{'actual_weight_kg':'1','cargo_type':'PARCEL','length_cm':'20','width_cm':'15','height_cm':'10'},'items':[]}}),
        prepare=AsyncMock(return_value={'partial':False,'rates':[{'offer_id':str(offer2),'client_price_ex_tax':'5.00','currency':'GBP','carrier_code':'UPS'},
            {'offer_id':str(offer1),'client_price_ex_tax':'3.49','currency':'GBP','carrier_code':'EVRI'}]}),select=AsyncMock(),status=AsyncMock(return_value=result))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://local.test') as client,apatch('backend.store_returns_portal.throttle',new=AsyncMock()),apatch('backend.entitlements.guard_feature',new=AsyncMock()),apatch('backend.return_review.ReturnReviewService',return_value=review),apatch('backend.return_delivery.signed_document',return_value='https://uat.easyinvio.com/document/fixture'):
        token=(await client.post('/api/v1/public/store-returns/sample-shop/verify',json={'order_reference':'#1042','verification_value':'LS12 6EJ'})).json()['token']
        response=await client.post('/api/v1/public/store-returns/sample-shop/confirm',json={'token':token,'original_packaging_confirmed':True})
        assert response.status_code==200,response.text
        assert review.select.call_args.args[2].offer_id==offer1
        assert review.select.call_args.kwargs['expected_store_policy'][0]==pool.store
        if status=='BOOKED':assert response.json()['label_url'] and response.json()['qr_url']
        else:assert response.json()['checkout_url'] and 'label_url' not in response.json() and 'qr_url' not in response.json()

@pytest.mark.asyncio
async def test_custom_website_help_uses_authored_guide_without_paid_ai():
    from backend.agents.runtime import AgentRuntime
    from backend.agents.config import AgentSettings
    from backend.agents.rag_support import HelpRetriever
    retriever=HelpRetriever(AgentRuntime(AgentSettings(_env_file=None,logistics_agents_enabled=False,openai_api_key=SecretStr(''))))
    result=await retriever.answer(SimpleNamespace(tenant_id='public-documentation',role='PUBLIC'),'How do I integrate my own custom website with EasyInvio?',allow_web=False)
    assert result['sources'] and all('/help/connect-custom-website' in s['url'] for s in result['sources'])
    assert 'signed' in result['answer'].lower() and 'secret' in result['answer'].lower()

def test_registry_and_router_order():
    assert len(PLATFORMS)==24 and PLATFORMS['AMAZON'].tracking_writeback is False
    assert PLATFORMS['ETSY'].setup_mode=='API_BRIDGE'
    tree=ast.parse((Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8'))
    cli=[n.lineno for n in tree.body if isinstance(n,ast.If) and '__name__' in ast.unparse(n.test) and any(isinstance(x,ast.Call) and ast.unparse(x.func)=='uvicorn.run' for x in ast.walk(n))]
    calls=[n.lineno for n in ast.walk(tree) if isinstance(n,ast.Call) and ast.unparse(n.func)=='app.include_router']
    assert len(cli)==1 and max(calls)<cli[0]

@pytest.mark.parametrize('url',['http://retailer.example.com','https://127.0.0.1','https://localhost','https://user:secret@retailer.example.com','https://retailer.example.com?secret=x'])
def test_store_url_rejects_unsafe_origins(url):
    with pytest.raises(ValueError):https_url(url,origin=True)

@pytest.mark.asyncio
async def test_bridge_callback_is_signed_and_keeps_event_id_on_retry():
    pool=Pool();config,keys=encrypted_config(pool,live_delivery=True,tracking_callback_url='https://retailer.example.com/hooks/tracking')
    pool.event={'id':uuid4(),'shipment_id':uuid4(),'store_id':pool.store,'platform':'CUSTOM_WEBSITE','status':'PENDING','attempts':0,
        'payload':{'store_order_id':'1042','tracking_number':'TRACK-1','carrier_name':'UPS'}}
    calls=[]
    def remote(request):
        body=json.loads(request.content);calls.append(body)
        assert request.headers['x-easyinvio-store-id']==str(pool.store)
        assert request.headers['idempotency-key']==body['event_id']
        assert request.headers['x-easyinvio-signature']==signature(config.webhook_secret.get_secret_value(),request.headers['x-easyinvio-timestamp'],'POST','/hooks/tracking',pool.store,request.content)
        return httpx.Response(503 if len(calls)==1 else 202,json={'accepted':len(calls)>1})
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        service=EcommerceService(pool,credential_keys=keys,client=client,settings=SimpleNamespace(provider_environment='LIVE'))
        await service.push(pool.tenant,'1042','TRACK-1','UPS')
        assert pool.event['status']=='RECONCILIATION_REQUIRED'
        await service.push(pool.tenant,'1042','TRACK-1','UPS')
        assert pool.event['status']=='DELIVERED' and calls[0]['event_id']==calls[1]['event_id']

@pytest.mark.asyncio
@pytest.mark.parametrize('platform',['EBAY','BIGCOMMERCE','WIX','MAGENTO'])
async def test_native_rest_connection_checks_use_expected_authorized_api(platform):
    from backend.store_rest import RestStoreAdapter
    pool=Pool();config,_=encrypted_config(pool,platform,access_token='fixture-token',store_url='https://retailer.example.com',external_store_id='fixture-site')
    calls=[]
    def remote(request):
        calls.append(request)
        assert 'fixture-token' in (request.headers.get('Authorization') or request.headers.get('X-Auth-Token'))
        return httpx.Response(200,json={'orders':[]} if platform=='WIX' else {})
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
        assert (await RestStoreAdapter(client,config).test())['verified'] is True
    assert len(calls)==1
    assert calls[0].url.host=={'EBAY':'api.ebay.com','BIGCOMMERCE':'api.bigcommerce.com','WIX':'www.wixapis.com','MAGENTO':'retailer.example.com'}[platform]

@pytest.mark.asyncio
async def test_outbound_dns_is_pinned_while_retaining_tls_identity():
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            assert request.url.host=='1.1.1.1'
            assert request.headers['host']=='retailer.example.com'
            assert request.extensions['sni_hostname']=='retailer.example.com'
            return httpx.Response(200,json={'ok':True})
    async with httpx.AsyncClient(transport=Transport()) as client:
        with patch('backend.store_transport.public_host',new=AsyncMock(return_value='1.1.1.1')):
            assert (await store_json(client,'GET','https://retailer.example.com/orders'))['ok']

@pytest.mark.asyncio
@pytest.mark.parametrize('change',[{'status':'IN_TRANSIT'},{'delivered_at':None}])
async def test_portal_rejects_orders_without_recorded_delivery(shopper_app,change):
    app,pool=shopper_app;pool.shipment.update(change)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://local.test') as client,apatch('backend.store_returns_portal.throttle',new=AsyncMock()):
        result=await client.post('/api/v1/public/store-returns/sample-shop/verify',json={'order_reference':'#1042','verification_value':'LS12 6EJ'})
        assert result.status_code==409 and pool.session is None



def test_signed_api_openapi_contracts_have_no_broken_local_refs():
    app=FastAPI();app.include_router(build_router())
    paths=app.openapi()['paths']
    for path in ('/api/v1/integration/custom-store/orders','/api/v1/integration/custom-store/checkout-rates'):
        schema=paths[path]['post']['requestBody']['content']['application/json']['schema']
        assert '$ref' not in json.dumps(schema)
        assert 'required' in schema
