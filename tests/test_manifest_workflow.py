"""Offline state/action matrix and scoped manifest/requote API checks."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.advanced_logistics import build_router
from backend.manifest_workflow import workflow, requote_context


def record(status='QUOTED', **values):
    now = datetime.now(timezone.utc)
    return dict(id=uuid4(),tenant_id=uuid4(),status=status,currency='GBP',final_client_price='19.94',
                customer_reference='SYNTHETIC-51',quote_expires_at=now+timedelta(minutes=5),
                logistics_metadata={},booked_at=None,tracking_number=None,carrier_code='DPD',
                customs_required=False,**values)


@pytest.mark.parametrize('status', ['PENDING_IMPORT','UNFULFILLED','DRAFT','QUOTED','FAILED','BOOKING','CANCELLED'])
def test_unbooked_states_never_offer_label_qr_or_proof(status):
    row=record(status)
    row['logistics_metadata']={'automation_label':{'label_url':'https://carrier.example/old.pdf','return_dropoff_qr_code_base64':'old'}}
    row['proof_of_delivery_url']='https://carrier.example/old-pod'
    actions=workflow(row)
    assert not actions['has_label'] and not actions['has_qr'] and not actions['has_pod']
    assert not actions['can_return'] and not actions['has_receipt']


@pytest.mark.parametrize('status',['BOOKED','MANIFESTED','DISPATCHED','IN_TRANSIT','EXCEPTION','DELIVERED'])
def test_confirmed_states_need_real_assets_and_preserve_carrier_outcomes(status):
    row=record(status)
    row.update(booked_at=datetime.now(timezone.utc),tracking_number='SYNTHETIC-TRACK',reservation_status='CAPTURED')
    assert not workflow(row)['has_label'] and not workflow(row)['has_pod']
    row['logistics_metadata']={'automation_label':{'label_url':'https://carrier.example/real.pdf','return_dropoff_qr_code_svg':'<svg/>'},'automation_customs':{'required':True}}
    row['proof_of_delivery_url']='https://carrier.example/proof'
    result=workflow(row)
    assert result['has_label'] and result['has_qr'] and result['has_invoice'] and result['has_receipt']
    assert result['has_pod'] == (status=='DELIVERED')
    assert not result['can_requote'] and not result['can_select']


def test_expiry_boundary_and_missing_expiry_are_not_bookable():
    now=datetime.now(timezone.utc);row=record()
    row['quote_expires_at']=now
    assert workflow(row,now=now)['status']=='QUOTE_EXPIRED'
    assert not workflow(row,now=now)['can_select']
    row['quote_expires_at']=None
    assert workflow(row)['status']=='QUOTE_UNAVAILABLE'
    assert not workflow(row)['can_select']
    row['quote_expires_at']=now+timedelta(minutes=5)
    assert workflow(row,now=now)['can_select']


@pytest.mark.parametrize('field,value',[('reservation_status','RESERVED'),('reservation_status','SUBMITTED'),('order_job_state','SENDING'),('order_job_state','RECONCILIATION_REQUIRED')])
def test_uncertain_failed_mutations_cannot_be_copied_to_duplicate_purchase(field,value):
    row=record('FAILED');row[field]=value
    assert not workflow(row)['can_requote']
    with pytest.raises(HTTPException) as error:requote_context(row)
    assert error.value.status_code==409


def test_import_review_is_preparation_not_a_quote_or_customs_import_charge():
    row=record('PENDING_IMPORT');row['customs_required']=True
    row['logistics_metadata']={'batch_csv':{},'automation_customs':{'required':True,'ready_for_provider':False}}
    result=workflow(row)
    assert result['can_prepare'] and result['can_review_import'] and not result['quote_current']
    row['status']='BOOKED';row['booked_at']=datetime.now(timezone.utc)
    assert not workflow(row)['can_review_import']


def test_return_parent_fence_and_unsafe_assets_are_preserved():
    row=record('FAILED');row['tracking_lifecycle_type']='RETURN_SHIPMENT'
    assert not workflow(row)['can_requote']
    row=record('DELIVERED');row.update(booked_at=datetime.now(timezone.utc),tracking_number='SYNTHETIC',proof_of_delivery_url='javascript:alert(1)')
    row['logistics_metadata']={'automation_label':{'label_url':'https://name:password@carrier.example/file'}}
    assert not workflow(row)['has_label'] and not workflow(row)['has_pod']


def test_requote_restores_all_packages_and_goods_without_prices_or_execution_secrets():
    row=record('FAILED')
    boxes=[{'actual_weight_kg':'2.000','length_cm':'24','width_cm':'16','height_cm':'8'}, {'actual_weight_kg':'3.500','length_cm':'30','width_cm':'20','height_cm':'10'}]
    row['logistics_metadata']={'automation_order':{'origin':{'name':'Sender','country_code':'GB','phone':'+447700900000'},'destination':{'country_code':'FR'},
        'cargo':{'cargo_type':'PARCEL','stackable':False},'packages':boxes,'customs_currency':'EUR',
        'items':[{'description':'Books','quantity':2,'unit_value':'12.00','unit_weight_kg':'1.000','package_index':1,'hs_code':'490199','sku':'BOOKS'}]},'secret':'not-exported'}
    result=requote_context(row)
    assert result['packages']==boxes and result['shipment_items'][0]['package_index']==1
    assert result['shipment_items'][0]['sku']=='BOOKS' and result['goods_currency']=='EUR'
    assert result['origin']['phone']=='+447700900000' and not result['stackable']
    assert 'secret' not in str(result) and 'final_client_price' not in result and 'offer_id' not in result


def api_client(role='OWNER', found=True):
    row=record();row['service_code']='AIR_EXPRESS'
    row['logistics_metadata']={'automation_customs':{'required':False},'automation_order':{'cargo':{'cargo_type':'PARCEL'}}}
    calls=[]
    class Pool:
        @asynccontextmanager
        async def acquire(self):yield self
        async def fetch(self,sql,*args):calls.append((sql,args));return [row]
        async def fetchrow(self,sql,*args):calls.append((sql,args));return row if found else None
    async def auth():return SimpleNamespace(tenant_id=row['tenant_id'],user_id=uuid4(),role=role)
    app=FastAPI();app.state.finance=SimpleNamespace(pool=Pool());app.include_router(build_router(auth,None))
    return TestClient(app),row,calls


def test_manifest_transmits_carrier_expiry_and_evidence_flags():
    client,row,_=api_client()
    response=client.get('/api/v1/shipments/manifest')
    assert response.status_code==200
    saved=response.json()['shipments'][0]
    assert saved['carrier_code']=='DPD' and saved['service_code']=='AIR_EXPRESS'
    assert saved['quote_expires_at']==row['quote_expires_at'].isoformat()
    assert saved['workflow']['can_select'] and not saved['workflow']['has_pod']


def test_requote_lookup_is_tenant_bound_and_has_no_mutation():
    client,row,calls=api_client()
    assert client.get('/api/v1/shipments/'+str(row['id'])+'/requote-context').status_code==200
    assert calls[-1][1]==(row['tenant_id'],row['id'])
    assert all(sql.strip().startswith('SELECT') for sql,_ in calls)
    assert client.get('/api/v1/shipments/'+str(row['id'])+'/requote-context?tenant_id='+str(uuid4())).status_code==403


def test_requote_denies_read_only_and_foreign_records():
    client,row,calls=api_client('ACCOUNTANT')
    assert client.get('/api/v1/shipments/'+str(row['id'])+'/requote-context').status_code==403
    assert not calls
    client,row,_=api_client(found=False)
    assert client.get('/api/v1/shipments/'+str(row['id'])+'/requote-context').status_code==404
