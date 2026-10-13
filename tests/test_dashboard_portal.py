import unittest
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from backend.admin_portal import authenticate_platform_owner
from backend.dashboard_portal import build_router


class DB:
    def __init__(self):
        self.calls=[]
    @asynccontextmanager
    async def acquire(self):
        yield self
    @asynccontextmanager
    async def transaction(self,**kw):
        yield
    async def fetch(self,sql,*args):
        self.calls.append((sql,args))
        if 'AS revenue' in sql:
            return [{'currency':'GBP','revenue':Decimal('1234.50'),'margin':Decimal('246.90'),'package_count':12}]
        if 'AS volume' in sql:
            return [{'carrier':'DHL','volume':12}]
        return []
    async def fetchrow(self,sql,*args):
        self.calls.append((sql,args))
        return {"id":args[0],"tenant_id":args[1],"status":"OPEN"}
    async def fetchval(self,sql,*args):
        self.calls.append((sql,args))
        return 42
    async def execute(self,sql,*args):
        self.calls.append((sql,args))
        return 'UPDATE 1'


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.context=SimpleNamespace(tenant_id=uuid4(),user_id=uuid4(),role='OWNER')
        self.db=DB()
        async def authenticate(request: Request, credentials=None):
            return self.context
        self.auth=authenticate
        self.app=FastAPI()
        self.app.state.finance=SimpleNamespace(pool=self.db)
        self.app.include_router(build_router(authenticate))
        self.client=TestClient(self.app)
    def tearDown(self):
        self.client.close()
    def test_client_profile_comes_from_verified_context(self):
        with patch('backend.dashboard_portal.authenticate_platform_owner',AsyncMock(side_effect=HTTPException(403,'Not an owner'))):
            response=self.client.get('/api/v1/profile',headers={'Authorization':'Bearer fixture'})
        self.assertEqual(response.json()['portal_role'],'CLIENT')
        self.assertEqual(response.json()['tenant_id'],str(self.context.tenant_id))
    def test_owner_profile_needs_no_tenant(self):
        with patch('backend.dashboard_portal.authenticate_platform_owner',AsyncMock(return_value=SimpleNamespace(user_id=self.context.user_id))):
            response=self.client.get('/api/v1/profile',headers={'Authorization':'Bearer fixture'})
        self.assertEqual(response.json()['portal_role'],'SUPER_ADMIN')
        self.assertIsNone(response.json()['tenant_id'])
    def test_macro_metrics_require_owner_and_use_decimal(self):
        async def owner():
            return SimpleNamespace(user_id=uuid4())
        self.app.dependency_overrides[authenticate_platform_owner]=owner
        response=self.client.get('/api/v1/admin/analytics/dashboard?start_date=2026-10-01&end_date=2026-10-31')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['totals_by_currency'][0]['revenue'],'1234.50')
        self.assertEqual(response.json()['totals_by_currency'][0]['margin'],'246.90')
        self.assertTrue(any('NOT t.is_sandbox' in sql for sql,_ in self.db.calls))
        self.assertEqual(self.client.get('/api/v1/admin/analytics/dashboard?start_date=2026-11-01&end_date=2026-10-01').status_code,422)
    def test_unauthorized_owner_request_does_not_query_database(self):
        async def denied():
            raise HTTPException(403,'Owner required')
        self.app.dependency_overrides[authenticate_platform_owner]=denied
        response=self.client.get('/api/v1/admin/analytics/dashboard?start_date=2026-10-01&end_date=2026-10-31')
        self.assertEqual(response.status_code,403)
        self.assertFalse(self.db.calls)
    def test_client_tickets_and_intervention_scope(self):
        self.assertEqual(self.client.get('/api/v1/support/tickets').status_code,200)
        self.assertEqual(self.db.calls[-1][1],(self.context.tenant_id,None,False))
        ticket_id=uuid4()
        response=self.client.post(f'/api/v1/support/tickets/{ticket_id}/intervene',json={'note':'Ask carrier to check customs paperwork'})
        self.assertEqual(response.status_code,200)
        sql,args=self.db.calls[-1]
        self.assertIn('tenant_id=$1',sql)
        self.assertEqual(args[:2],(self.context.tenant_id,ticket_id))
        self.context.role='ACCOUNTANT'
        self.assertEqual(self.client.post(f'/api/v1/support/tickets/{ticket_id}/intervene',json={'note':'Review issue'}).status_code,403)

    def test_note_does_not_assign_review_or_notify_and_history_is_scoped(self):
        ticket=uuid4()
        response=self.client.post(f'/api/v1/support/tickets/{ticket}/intervene',json={'note':'Internal finding','start_review':False})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['status'],'OPEN')
        self.assertFalse(response.json()['merchant_notified'])
        self.assertFalse(response.json()['carrier_contacted'])
        sql,args=self.db.calls[-1]
        self.assertIn('support_ticket_activity',sql)
        self.assertEqual(args[4],'INTERNAL_NOTE')
        self.assertEqual(args[:2],(self.context.tenant_id,ticket))

    def test_processing_issue_is_not_carrier_exception_or_missing_pod(self):
        from backend.support_workflow import present_ticket
        ticket=present_ticket({'automation_failure_id':uuid4(),'error_code':'ORDER_SERVICE_FAILED','notifications':[]})
        self.assertEqual(ticket['ticket_type'],'PROCESSING_ISSUE')
        self.assertEqual(ticket['pod_state'],'NOT_BOOKED')
        self.assertNotIn('Bulk order',ticket['ai_summary'])
        self.assertIn('internal',ticket['notification_explanation'])


if __name__=='__main__':
    unittest.main()
