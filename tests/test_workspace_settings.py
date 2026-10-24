import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch,AsyncMock
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from backend.dashboard_portal import build_router
class DB:
 def __init__(self):self.calls=[];self.pending=True;self.confirmed=True;self.booked=True;self.invited=uuid4();self.tenant=uuid4()
 @asynccontextmanager
 async def acquire(self):yield self
 @asynccontextmanager
 async def transaction(self,**kwargs):yield
 async def execute(self,sql,*args):self.calls.append((sql,args));return 'UPDATE 1'
 async def fetchval(self,sql,*args):
  if 'RETURNING attempts' in sql:return 1
  if 'booked_at IS NOT NULL' in sql:return self.booked
  return False
 async def fetchrow(self,sql,*args):
  if 'workspace_invitations i JOIN' in sql:return {'id':uuid4(),'tenant_id':self.tenant,'role':'DISPATCHER','first_name':'Test','last_name':'User'} if self.pending else None
  if 'FROM public.shipment_dispute_drafts' in sql:return {'content':'Saved draft content','updated_at':None}
  return None
 async def fetch(self,*args):return []
class SettingsTests(unittest.TestCase):
 def setUp(self):
  self.db=DB();self.ctx=SimpleNamespace(tenant_id=self.db.tenant,user_id=uuid4(),role='OWNER')
  async def auth():return self.ctx
  self.app=FastAPI();self.app.state.finance=SimpleNamespace(pool=self.db)
  self.app.state.settings=SimpleNamespace(supabase_url='https://auth.example.invalid',supabase_publishable_key=SecretStr('public-test'),supabase_service_role_key=SecretStr('service-test'),auth_recovery_redirect_url='http://127.0.0.1:8000/')
  self.app.include_router(build_router(auth));self.client=TestClient(self.app);self.http=[]
  original=httpx.AsyncClient
  def transport(req):
   self.http.append(req)
   if req.url.path.endswith('/invite'):return httpx.Response(200,json={'id':str(self.db.invited),'email':'new@example.invalid'})
   if req.method=='GET':return httpx.Response(200,json={'id':str(self.db.invited),'email':'new@example.invalid','email_confirmed_at':'2026-10-13' if self.db.confirmed else None,'user_metadata':{'role':'SUPER_ADMIN','tenant_id':str(uuid4())}})
   return httpx.Response(200,json={})
  self.network=patch('backend.workspace_settings.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(transport),**kw));self.network.start()
 def tearDown(self):self.network.stop();self.client.close()
 def test_admin_invitation_rejected(self):
  r=self.client.post('/api/v1/workspace/invitations',json={'first_name':'Test','last_name':'User','email':'new@example.invalid','role':'ADMIN'})
  self.assertEqual(r.status_code,422);self.assertFalse(self.http);self.assertFalse(self.db.calls)
 def test_dispatcher_cannot_manage_team(self):
  self.ctx.role='DISPATCHER'
  r=self.client.post('/api/v1/workspace/invitations',json={'first_name':'Test','last_name':'User','email':'new@example.invalid','role':'ACCOUNTANT'})
  self.assertEqual(r.status_code,403);self.assertFalse(self.http)
 def test_invitation_queues_email_but_not_membership(self):
  r=self.client.post('/api/v1/workspace/invitations',json={'first_name':'Test','last_name':'User','email':'new@example.invalid','role':'DISPATCHER'})
  self.assertEqual(r.status_code,201);self.assertEqual(r.json()['status'],'PENDING')
  self.assertFalse(any('INSERT INTO public.users' in sql for sql,_ in self.db.calls))
 def test_acceptance_uses_stored_role_not_user_metadata(self):
  r=self.client.post('/api/v1/auth/accept-invitation',json={'access_token':'synthetic-access-token-123','password':'A-long-synthetic-password'})
  self.assertEqual(r.status_code,200)
  args=next(args for sql,args in self.db.calls if 'INSERT INTO public.users' in sql)
  self.assertEqual(args[:3],(self.db.tenant,self.db.invited,'DISPATCHER'))
 def test_unverified_email_not_activated(self):
  self.db.confirmed=False
  self.assertEqual(self.client.post('/api/v1/auth/accept-invitation',json={'access_token':'synthetic-access-token-123','password':'A-long-synthetic-password'}).status_code,403)
  self.assertFalse(any('INSERT INTO public.users' in sql for sql,_ in self.db.calls))
 def test_cancelled_or_expired_invitation_rejected(self):
  self.db.pending=False
  self.assertEqual(self.client.post('/api/v1/auth/accept-invitation',json={'access_token':'synthetic-access-token-123','password':'A-long-synthetic-password'}).status_code,403)
  self.assertFalse(any(req.method=='PUT' for req in self.http))
 def test_draft_requires_booking_and_financial_role(self):
  path='/api/v1/shipments/'+str(uuid4())+'/dispute-draft'
  self.db.booked=False
  self.assertEqual(self.client.put(path,json={'content':'Draft with enough content'}).status_code,409)
  self.ctx.role='DISPATCHER'
  self.assertEqual(self.client.put(path,json={'content':'Draft with enough content'}).status_code,403)
 def test_saved_draft_scoped_and_not_sent(self):
  sid=uuid4();path=f'/api/v1/shipments/{sid}/dispute-draft'
  r=self.client.put(path,json={'content':'Draft with enough content'})
  self.assertEqual(r.status_code,200);self.assertFalse(r.json()['sent_to_carrier']);self.assertFalse(self.http)
  args=self.db.calls[-1][1];self.assertEqual(args[:2],(self.ctx.tenant_id,sid))
 def test_invitation_rate_limit_prevents_email_send(self):
  self.db.fetchval=AsyncMock(return_value=21)
  r=self.client.post('/api/v1/workspace/invitations',json={'first_name':'Test','last_name':'User','email':'new@example.invalid','role':'DISPATCHER'})
  self.assertEqual(r.status_code,429);self.assertFalse(self.http)
 def test_accountant_cannot_open_company_or_team_settings(self):
  self.ctx.role='ACCOUNTANT'
  self.assertEqual(self.client.get('/api/v1/workspace/settings').status_code,403)
  self.assertFalse(self.db.calls)
 def test_legacy_admin_and_agent_cannot_manage_customer_team_directly(self):
  for role in ('ADMIN','AGENT','DISPATCHER','ACCOUNTANT'):
   self.ctx.role=role
   self.assertEqual(self.client.get('/api/v1/workspace/settings').status_code,403)
   result=self.client.post('/api/v1/workspace/users',json={'auth_user_id':str(uuid4()),'full_name':'Test Person','role':'DISPATCHER'})
   self.assertEqual(result.status_code,403)
  self.assertFalse(self.db.calls)
if __name__=='__main__':unittest.main()
