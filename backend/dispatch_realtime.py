"""Commit-time Postgres notifications fan out to authenticated tenant sockets."""
import asyncio
import json
import logging

import asyncpg
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials


class DispatchUpdates:
    def __init__(self, settings, ssl):
        self.settings = settings
        self.ssl = ssl
        self.connections = {}

    def notified(self, connection, process_id, channel, payload):
        try:
            event = json.loads(payload)
            tenant_id = event.pop('tenant_id')
        except (ValueError, KeyError, TypeError):
            return
        self.publish(tenant_id, {'type': 'shipment_changed', **event})

    def publish(self, tenant_id, event):
        for queue in tuple(self.connections.get(tenant_id, ())):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({'type': 'refresh_required'})
            else:
                queue.put_nowait(event)

    async def worker(self):
        while True:
            connection = None
            try:
                connection = await asyncpg.connect(self.settings.database_url.get_secret_value(), ssl=self.ssl, timeout=15, command_timeout=15)
                await connection.add_listener('easyinvio_dispatch', self.notified)
                for tenant_id in tuple(self.connections):
                    self.publish(tenant_id, {'type': 'refresh_required'})
                while not connection.is_closed():
                    await asyncio.sleep(15)
                    await connection.fetchval('SELECT 1')
            except (asyncpg.PostgresError, OSError, TimeoutError):
                logging.getLogger(__name__).warning('Dispatch listener reconnecting; browser refresh fallback remains available')
            finally:
                if connection is not None:
                    await connection.close()
            await asyncio.sleep(3)


def build_router(authenticate, origins):
    router = APIRouter()

    @router.websocket('/api/v1/dispatch-workspace/live')
    async def updates(socket: WebSocket):
        origin = socket.headers.get('origin')
        from urllib.parse import urlsplit
        parsed = urlsplit(origin or '')
        allowed = origin in origins()
        if socket.app.state.settings.provider_environment == 'TEST' and parsed.scheme in {'http', 'https'}:
            allowed = allowed or (parsed.hostname in {'127.0.0.1', 'localhost'} and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment)
        if socket.scope.get('query_string') or not allowed:
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = asyncio.Queue(maxsize=50)
        tenant_id = None
        broker = socket.app.state.dispatch_updates
        try:
            message = await asyncio.wait_for(socket.receive_json(), timeout=10)
            if not isinstance(message,dict):
                raise HTTPException(401, 'Authenticate this connection')
            token = message.get('access_token')
            if not isinstance(token, str) or not token or len(token) > 16000:
                raise HTTPException(401, 'Authenticate this connection')
            scope = {'type': 'http', 'method': 'GET', 'path': '/api/v1/dispatch-workspace/live',
                'headers': [], 'query_string': b'', 'app': socket.app, 'scheme': 'https',
                'client': socket.scope.get('client'), 'server': socket.scope.get('server')}
            request = Request(scope)
            credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
            context = await authenticate(request, credentials)
            if context.role not in {'OWNER', 'ADMIN', 'DISPATCHER', 'ACCOUNTANT'}:
                raise HTTPException(403, 'Workspace access required')
            tenant_id = str(context.tenant_id)
            if sum(len(group) for group in broker.connections.values()) >= 100:
                await socket.close(code=1013)
                return
            broker.connections.setdefault(tenant_id, set()).add(queue)
            await socket.send_json({'type': 'refresh_required'})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    event = {'type': 'heartbeat'}
                refreshed = await authenticate(request, credentials)
                if str(refreshed.tenant_id) != tenant_id or refreshed.role != context.role:
                    raise HTTPException(403, 'Workspace membership changed')
                await socket.send_json(event)
        except (HTTPException, ValueError, TypeError, WebSocketDisconnect, TimeoutError):
            try:
                await socket.close(code=1008)
            except RuntimeError:
                pass
        finally:
            if tenant_id is not None:
                broker.connections.get(tenant_id, set()).discard(queue)
                if not broker.connections.get(tenant_id):
                    broker.connections.pop(tenant_id, None)

    return router
