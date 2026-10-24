"""Admin-bound client assistance, fail-closed auditing and tenant context tests."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import asyncpg
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

import main
from backend import client_assistance as support


class Acquire:
    def __init__(self, connection): self.connection = connection
    async def __aenter__(self): return self.connection
    async def __aexit__(self, *args): return False


class AssistanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor, self.tenant, self.identifier = uuid4(), uuid4(), uuid4()
        self.session = {'id': self.identifier, 'actor_auth_user_id': self.actor,
            'tenant_id': self.tenant, 'company_name': 'Client Alpha', 'is_sandbox': True,
            'workspace_status': 'ACTIVE', 'expires_at': datetime.now(timezone.utc)+timedelta(minutes=10)}
        self.connection = SimpleNamespace(fetchrow=AsyncMock(return_value=self.session), execute=AsyncMock())
        self.app = FastAPI()
        self.app.state.finance = SimpleNamespace(pool=SimpleNamespace(acquire=lambda: Acquire(self.connection)))
        self.app.add_middleware(support.ClientAssistanceMiddleware)
        self.executions = 0

        @self.app.post('/api/v1/catalog/test')
        async def update(request: Request):
            context = await main.authenticate(request, HTTPAuthorizationCredentials(scheme='Bearer', credentials='admin-token'))
            self.executions += 1
            payload = await request.json()
            return {'tenant_id': str(context.tenant_id), 'actor': str(context.user_id),
                'role': context.role, 'assistance': str(context.assistance_session_id), 'payload': payload}

        self.owner = patch.object(support, 'authenticate_platform_operator', AsyncMock(return_value=SimpleNamespace(user_id=self.actor)))
        self.owner.start()
        self.addCleanup(self.owner.stop)

    async def request(self, headers=None, payload=None):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test') as client:
            return await client.post('/api/v1/catalog/test', headers=headers or {
                'Authorization': 'Bearer admin-token', support.HEADER: str(self.identifier)}, json=payload or {'description': 'A reviewed product'})

    async def test_client_context_retains_actual_admin_and_audits_before_execution(self):
        response = await self.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['tenant_id'], str(self.tenant))
        self.assertEqual(response.json()['actor'], str(self.actor))
        self.assertEqual(response.json()['role'], 'OWNER')
        self.assertEqual(response.json()['assistance'], str(self.identifier))
        self.assertEqual(self.connection.fetchrow.call_args.args[1:3], (self.identifier, self.actor))
        events = [call.args[4] for call in self.connection.execute.await_args_list]
        self.assertEqual(events, ['REQUEST_STARTED', 'REQUEST_FINISHED'])
        self.assertIn('x-easyinvio-audit-id', response.headers)
        detail = json.loads(self.connection.execute.await_args_list[-1].args[-1])
        self.assertEqual(len(detail['body_sha256']), 64)

    async def test_revoked_expired_wrong_actor_or_token_session_does_not_execute(self):
        self.connection.fetchrow.return_value = None
        response = await self.request()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.executions, 0)
        self.connection.execute.assert_not_awaited()

    async def test_non_platform_admin_cannot_use_a_session_identifier(self):
        with patch.object(support, 'authenticate_platform_operator', AsyncMock(side_effect=HTTPException(403, 'Platform-owner permission required'))):
            self.assertEqual((await self.request()).status_code, 403)
        self.assertEqual(self.executions, 0)

    async def test_audit_write_failure_prevents_mutation(self):
        self.connection.execute.side_effect = asyncpg.PostgresError('Audit unavailable')
        self.assertEqual((await self.request()).status_code, 503)
        self.assertEqual(self.executions, 0)

    async def test_completion_failure_keeps_start_record_and_success_response(self):
        self.connection.execute.side_effect = [None, asyncpg.PostgresError('Outcome unavailable')]
        self.assertEqual((await self.request()).status_code, 200)
        self.assertEqual(self.executions, 1)
        self.assertEqual(self.connection.execute.await_count, 2)

    async def test_invalid_identifier_is_rejected(self):
        self.assertEqual((await self.request(headers={'Authorization':'Bearer admin-token',support.HEADER:'invalid'})).status_code, 401)
        self.assertEqual(self.executions, 0)

    async def test_client_tenant_query_tampering_remains_blocked(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test') as client:
            result = await client.post('/api/v1/catalog/test?tenant_id='+str(uuid4()),
                headers={'Authorization':'Bearer admin-token',support.HEADER:str(self.identifier)},json={})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.executions, 0)

    async def test_platform_routes_are_not_client_operations(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test') as client:
            result = await client.get('/api/v1/admin/tenants',headers={'Authorization':'Bearer admin-token',support.HEADER:str(self.identifier)})
        self.assertEqual(result.status_code, 403)

    async def test_audit_redacts_credentials_but_keeps_changed_values(self):
        result = await self.request(payload={'description':'Updated product','unit_value':'12.30',
            'credentials':{'api_key':'private-key'},'password':'private-password','nested':{'access_token':'private-token'}})
        self.assertEqual(result.status_code,200)
        detail=json.loads(self.connection.execute.await_args_list[-1].args[-1])
        change=detail['requested_change']
        self.assertEqual(change['unit_value'],'12.30')
        self.assertEqual(change['description'],'Updated product')
        self.assertEqual(change['credentials'],'[redacted]')
        self.assertEqual(change['password'],'[redacted]')
        self.assertEqual(change['nested']['access_token'],'[redacted]')

    async def test_websocket_revalidation_does_not_trust_cached_session(self):
        request=Request({'type':'http','method':'GET','path':'/api/v1/dispatch-workspace/live',
            'headers':[(b'x-easyinvio-assistance',str(self.identifier).encode())],
            'query_string':b'','app':self.app,'easyinvio_assistance_revalidate':True})
        request.state.client_assistance=self.session
        with patch.object(support,'resolve_assistance',AsyncMock(side_effect=HTTPException(401,'Expired'))):
            with self.assertRaises(HTTPException) as caught:
                await main.authenticate(request,HTTPAuthorizationCredentials(scheme='Bearer',credentials='admin-token'))
        self.assertEqual(caught.exception.status_code,401)

    def test_parent_binding_survives_token_renewal_but_not_a_new_sign_in(self):
        def request(token,parent):
            result=Request({'type':'http','method':'GET','path':'/','headers':[(b'authorization',token.encode())],'query_string':b''})
            result.state.app_session_claims={'jti':parent}
            return result
        parent=str(uuid4())
        self.assertEqual(support.token_fingerprint(request('Bearer old',parent)),support.token_fingerprint(request('Bearer renewed',parent)))
        self.assertNotEqual(support.token_fingerprint(request('Bearer renewed',parent)),support.token_fingerprint(request('Bearer renewed',str(uuid4()))))


if __name__ == '__main__':
    unittest.main()
