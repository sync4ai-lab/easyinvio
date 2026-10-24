"""Staff access must be revocable and independent of customer/token roles."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from fastapi import HTTPException, Request
from backend.admin_portal import authenticate_platform_operator, authenticate_platform_owner
from backend.platform_staff import platform_role

class Acquire:
    def __init__(self,c):self.c=c
    async def __aenter__(self):return self.c
    async def __aexit__(self,*args):return False

class StaffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.uid=uuid4();self.settings=SimpleNamespace(platform_admin_user_ids=[])
        self.c=SimpleNamespace(fetchval=AsyncMock(side_effect=[True,True]))
        self.app=SimpleNamespace(state=SimpleNamespace(settings=self.settings,finance=SimpleNamespace(pool=SimpleNamespace(acquire=lambda:Acquire(self.c)))))
        self.request=Request({'type':'http','app':self.app,'headers':[]})

    async def test_registry_agent_cannot_use_owner_dependency(self):
        with patch('backend.admin_portal.verified_platform_identity',AsyncMock(return_value=self.uid)):
            actor=await authenticate_platform_operator(self.request,None)
            self.assertEqual((actor.user_id,actor.role),(self.uid,'AGENT'))
            with self.assertRaises(HTTPException) as error:
                await authenticate_platform_owner(self.request,None)
            self.assertEqual(error.exception.status_code,403)

    async def test_disabled_or_absent_agent_denied_even_with_metadata(self):
        self.request.state.platform_auth_claims={'app_metadata':{'role':'AGENT','platform_admin':True}}
        for values in ([True,False],[False]):
            self.c.fetchval=AsyncMock(side_effect=values)
            with patch('backend.admin_portal.verified_platform_identity',AsyncMock(return_value=self.uid)):
                with self.assertRaises(HTTPException) as error:
                    await authenticate_platform_operator(self.request,None)
                self.assertEqual(error.exception.status_code,403)

    async def test_revocation_rechecked_on_next_request(self):
        self.c.fetchval=AsyncMock(side_effect=[True,True,True,False])
        with patch('backend.admin_portal.verified_platform_identity',AsyncMock(return_value=self.uid)):
            self.assertEqual((await authenticate_platform_operator(self.request,None)).role,'AGENT')
            with self.assertRaises(HTTPException):await authenticate_platform_operator(self.request,None)

    async def test_root_allowlist_still_works_without_registry(self):
        self.settings.platform_admin_user_ids=[self.uid]
        self.assertEqual(await platform_role(self.c,self.settings,self.uid),'SUPER_ADMIN')
        self.c.fetchval.assert_not_awaited()
        with patch('backend.admin_portal.verified_platform_identity',AsyncMock(return_value=self.uid)):
            self.assertEqual((await authenticate_platform_owner(self.request,None)).role,'SUPER_ADMIN')
            self.assertEqual((await authenticate_platform_operator(self.request,None)).role,'SUPER_ADMIN')

    async def test_identity_failure_never_queries_staff_registry(self):
        with patch('backend.admin_portal.verified_platform_identity',AsyncMock(side_effect=HTTPException(401,'Invalid token'))):
            with self.assertRaises(HTTPException):await authenticate_platform_operator(self.request,None)
        self.c.fetchval.assert_not_awaited()

    async def test_read_only_client_routes_allow_staff_but_configuration_stays_owner_only(self):
        from backend.admin_management import router
        from fastapi.routing import APIRoute
        expected={'/api/v1/admin/tenants','/api/v1/admin/transactions','/api/v1/admin/marketplaces'}
        for route in router.routes:
            if not isinstance(route,APIRoute):continue
            dependency=route.dependant.dependencies[0].call
            self.assertIs(dependency,authenticate_platform_operator if route.path in expected else authenticate_platform_owner)

    async def test_tracking_and_manifest_staff_routes_keep_separate_from_root_controls(self):
        import main
        for route in main.app.routes:
            path=getattr(route,'path','')
            if path.startswith('/api/v1/admin/tracking/') or path=='/api/v1/admin/shipments/manifest':
                self.assertIn(authenticate_platform_operator,[d.call for d in route.dependant.dependencies],path)

    async def test_agent_onboarding_cannot_enroll_a_staff_identity(self):
        from backend.admin_portal import create_tenant, TenantCreate, PlatformOwner
        from tests.test_admin_portal import company
        body=TenantCreate(company_profile=company(),billing_plan='PREPAID_WALLET',owner_auth_user_id=uuid4())
        self.c.fetchval=AsyncMock(side_effect=[True,True,False])
        with self.assertRaises(HTTPException) as error:
            await create_tenant(body,self.request,PlatformOwner(self.uid,'AGENT'))
        self.assertEqual(error.exception.status_code,409)

    async def test_finance_revalidates_staff_and_client_assistance_before_granting_owner_context(self):
        import main
        tenant=uuid4();aid=uuid4()
        context=main.TenantContext(tenant,self.uid,'OWNER','',aid)
        engine=main.FinanceEngine(None,self.settings,None)
        self.c.fetchrow=AsyncMock(side_effect=[{'tenant_id':tenant,'workspace_status':'ACTIVE'},{'id':aid}])
        with patch('backend.platform_staff.platform_role',AsyncMock(return_value='AGENT')):
            await engine.lock_tenant(self.c,tenant,context,main.FINANCE_ROLES)
        self.assertIn('actor_auth_user_id=$3',self.c.fetchrow.await_args_list[-1].args[0])
        for staff,session in [(None,{'id':aid}),('AGENT',None)]:
            self.c.fetchrow=AsyncMock(side_effect=[{'tenant_id':tenant,'workspace_status':'ACTIVE'},session])
            with patch('backend.platform_staff.platform_role',AsyncMock(return_value=staff)):
                with self.assertRaises(HTTPException):await engine.lock_tenant(self.c,tenant,context,main.FINANCE_ROLES)

    async def test_dispatcher_cannot_turn_a_shipping_permission_into_a_wallet_topup(self):
        from decimal import Decimal
        from backend.platform_staff import checkout_roles
        from backend.card_checkout import permitted
        dispatcher=SimpleNamespace(role='DISPATCHER',tenant_id=uuid4(),user_id=self.uid)
        permitted(dispatcher)
        self.assertNotIn('DISPATCHER',await checkout_roles(self.c,dispatcher))
        self.c.fetchrow=AsyncMock(return_value={'id':uuid4(),'amount':Decimal('12.50')})
        self.assertIn('DISPATCHER',await checkout_roles(self.c,dispatcher,uuid4(),Decimal('12.50')))
        with self.assertRaises(HTTPException):await checkout_roles(self.c,dispatcher,uuid4(),Decimal('500.00'))
        self.c.fetchrow=AsyncMock(return_value=None)
        with self.assertRaises(HTTPException):await checkout_roles(self.c,dispatcher,uuid4(),Decimal('12.50'))
        with self.assertRaises(HTTPException):permitted(SimpleNamespace(role='ACCOUNTANT'))


import tests.test_admin_portal as fixtures
class RootWorkspaceTests(unittest.TestCase):
    setUp=fixtures.AdminHTTPTests.setUp
    tearDown=fixtures.AdminHTTPTests.tearDown
    token=fixtures.AdminHTTPTests.token
    headers=fixtures.AdminHTTPTests.headers
    def test_root_cannot_operate_customer_wallet_without_assistance(self):
        response=self.client.get('/api/v1/wallet',headers=self.headers())
        self.assertEqual(response.status_code,403)
        self.assertIn('client assistance',response.json()['detail'])
