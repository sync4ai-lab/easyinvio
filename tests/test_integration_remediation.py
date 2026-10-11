"""Tenant-parameter rejection and non-blocking HubSpot scope remediation."""
import unittest
from unittest.mock import patch
from uuid import uuid4
from starlette.requests import Request
from fastapi import HTTPException
import httpx
import main
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.hubspot_crm import build_router
from backend.admin_portal import authenticate_platform_owner
from backend.hubspot_crm import CRMError,HubSpotClient,safe_process
from tests.test_hubspot_crm import settings

class TenantQueryTests(unittest.TestCase):
 def request(self,query):return Request({'type':'http','method':'GET','path':'/api/v1/shipments/manifest','query_string':query.encode(),'headers':[]})
 def test_absent_and_matching_query(self):
  tenant=uuid4()
  for query in ['',f'tenant_id={tenant}',f'tenant_id={str(tenant).upper()}']:
   main.validate_tenant_query(self.request(query),tenant)
 def test_foreign_empty_malformed_and_duplicate_are_denied(self):
  tenant=uuid4()
  for query in [f'tenant_id={uuid4()}','tenant_id=','tenant_id=not-a-uuid',f'tenant_id={tenant}&tenant_id={uuid4()}',f'tenant_id={tenant}&tenant_id={tenant}']:
   with self.subTest(query=query),self.assertRaises(HTTPException) as caught:
    main.validate_tenant_query(self.request(query),tenant)
   self.assertEqual(caught.exception.status_code,403)
 def test_attacker_input_not_echoed_in_security_log(self):
  with self.assertLogs('veloce',level='WARNING') as logs,self.assertRaises(HTTPException):
   main.validate_tenant_query(self.request('tenant_id=attacker-text'),uuid4())
  self.assertNotIn('attacker-text',' '.join(logs.output))

class CRMRemediationTests(unittest.IsolatedAsyncioTestCase):
 async def test_scope_denied_is_permanent_warned_and_not_retried(self):
  calls=[]
  def rejected(request):calls.append(request);return httpx.Response(403,json={'message':'Do not log raw secrets'})
  async with httpx.AsyncClient(transport=httpx.MockTransport(rejected)) as http:
   client=HubSpotClient(http,settings())
   with self.assertLogs('veloce.crm',level='WARNING') as logs,self.assertRaises(CRMError) as error:
    await client.request('GET','/crm/v3/objects/companies')
   self.assertEqual(error.exception.code,'hubspot_http_403');self.assertFalse(error.exception.retryable)
   self.assertEqual(len(calls),1);self.assertNotIn('raw secrets',' '.join(logs.output))
 async def test_optional_task_failure_does_not_escape(self):
  class Broken:
   async def process(self,tenant):raise RuntimeError('CRM failure')
  with self.assertLogs('veloce.crm',level='WARNING'):
   await safe_process(Broken(),uuid4())

if __name__=='__main__':unittest.main()

class IntegrationAlertTests(unittest.TestCase):
 def test_owner_only_alerts_have_remedy_and_no_credentials(self):
  app=FastAPI();app.include_router(build_router(lambda:None))
  class Connection:
   async def fetch(self,sql):return [{'tenant_id':uuid4(),'last_error':'hubspot_http_403','attempts':1,'blocked':True,'next_attempt_at':datetime.now(timezone.utc)}]
  class Pool:
   @asynccontextmanager
   async def acquire(self):yield Connection()
  app.state.finance=SimpleNamespace(pool=Pool());app.state.settings=SimpleNamespace()
  client=TestClient(app)
  self.assertEqual(client.get('/api/v1/admin/integrations/alerts').status_code,401)
  app.dependency_overrides[authenticate_platform_owner]=lambda:SimpleNamespace(user_id=uuid4())
  response=client.get('/api/v1/admin/integrations/alerts');self.assertEqual(response.status_code,200)
  alert=response.json()['alerts'][0];self.assertEqual(alert['status'],'BLOCKED');self.assertIn('Companies',alert['ai_summary'])
  self.assertEqual(alert['ai_method'],'DETERMINISTIC_REMEDIATION')
