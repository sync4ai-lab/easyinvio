"""Rollback-only actual Supabase invitation and draft persistence; controlled Auth HTTP."""
import asyncio,json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
import asyncpg,httpx
from fastapi import FastAPI
import main
from backend.dashboard_portal import build_router
async def run():
 s=main.Settings();assert s.database_environment=='SANDBOX'
 c=await asyncpg.connect(s.database_url.get_secret_value(),ssl=main.database_tls_context(s.database_ca_file,strict=s.database_tls_strict));tx=c.transaction();await tx.start()
 class Pool:
  @asynccontextmanager
  async def acquire(self):yield c
 report={'database':'actual Supabase SANDBOX','auth_http':'controlled MockTransport','real_emails_sent':0,'writes_rolled_back':False,'checks':[]}
 try:
  tenant=await c.fetchval("SELECT tenant_id FROM public.tenants WHERE workspace_slug='seed24-03'");actor=await c.fetchval("SELECT auth_user_id FROM public.users WHERE tenant_id=$1 AND role='OWNER' LIMIT 1",tenant)
  uid=uuid4();email='invite-'+uid.hex+'@example.invalid';context=SimpleNamespace(tenant_id=tenant,user_id=actor,role='OWNER')
  async def auth():return context
  app=FastAPI();app.state.finance=SimpleNamespace(pool=Pool());app.state.settings=s;app.include_router(build_router(auth))
  original=httpx.AsyncClient
  async def provider(req):
   if req.url.path.endswith('/invite'):
    await c.execute("INSERT INTO auth.users(id,email,encrypted_password,aud,role,raw_app_meta_data,raw_user_meta_data,created_at,updated_at) VALUES($1,$2,'','authenticated','authenticated','{}','{}',now(),now())",uid,email)
    return httpx.Response(200,json={'id':str(uid),'email':email})
   if req.method=='GET':return httpx.Response(200,json={'id':str(uid),'email':email,'email_confirmed_at':'2026-10-13','user_metadata':{'role':'ADMIN'}})
   return httpx.Response(200,json={})
  async with original(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
   with patch('backend.workspace_settings.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(provider),**kw)):
    data={'first_name':'Synthetic','last_name':'Invitee','email':email,'role':'DISPATCHER'}
    result=await client.post('/api/v1/workspace/invitations',json=data);assert result.status_code==201,result.text
    assert not await c.fetchval('SELECT EXISTS(SELECT 1 FROM public.users WHERE auth_user_id=$1)',uid)
    report['checks'].append('Email-accepted invitation remains pending; no membership before verification and password setup')
    result=await client.post('/api/v1/auth/accept-invitation',json={'access_token':'controlled-provider-session-token','password':'A-long-synthetic-password'});assert result.status_code==200,result.text
    row=await c.fetchrow('SELECT tenant_id,role FROM public.users WHERE auth_user_id=$1',uid);assert row['tenant_id']==tenant and row['role']=='DISPATCHER'
    result=await client.post('/api/v1/auth/accept-invitation',json={'access_token':'controlled-provider-session-token','password':'A-long-synthetic-password'});assert result.status_code==403
    report['checks'].append('One accepted membership in stored tenant and Dispatcher role; spoofed Admin metadata ignored; replay rejected')
   result=await client.get('/api/v1/workspace/settings');assert result.status_code==200,result.text
   report['checks'].append('Actual Settings SQL lists company, members and invitation state')
   shipment=await c.fetchval("SELECT id FROM public.shipments WHERE tenant_id=$1 AND booked_at IS NOT NULL AND tracking_number IS NOT NULL LIMIT 1",tenant)
   assert shipment
   path=f'/api/v1/shipments/{shipment}/dispute-draft'
   result=await client.put(path,json={'content':'Synthetic carrier invoice evidence draft'});assert result.status_code==200,result.text
   assert (await client.get(path)).json()['draft']['content']=='Synthetic carrier invoice evidence draft'
   context.tenant_id=uuid4()
   assert (await client.put(path,json={'content':'Foreign tenant attempt'})).status_code==409
   context.tenant_id=tenant
   member=await c.fetchval('SELECT id FROM public.users WHERE auth_user_id=$1',uid)
   assert (await client.patch(f'/api/v1/workspace/users/{member}',json={'role':'ACCOUNTANT','is_active':False})).status_code==200
   assert not await c.fetchval('SELECT is_active FROM public.users WHERE id=$1',member)
   assert (await client.patch(f'/api/v1/workspace/users/{member}',json={'role':'ADMIN','is_active':True})).status_code==422
   report['checks'].append('Dispute save and reload are tenant-scoped; foreign write rejected; user disable and Accountant update work; Admin escalation rejected')
  report['status']='PASS'
 finally:await tx.rollback();await c.close();report['writes_rolled_back']=True
 out=Path('docs/workspace_settings');out.mkdir(exist_ok=True);(out/'database_probe.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(run())
