"""Server-owned commercial strategy and accountable admin updates."""
import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.admin_management import router
from backend.admin_portal import authenticate_platform_owner, PlatformOwner


class Database:
    def __init__(self):
        self.classification = 'STANDARD'
        self.events = []

    @asynccontextmanager
    async def acquire(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        before = copy.deepcopy((self.classification,self.events))
        try:
            yield
        except BaseException:
            self.classification,self.events = before
            raise

    async def fetchrow(self, sql, *args):
        assert 'FOR UPDATE' in sql
        return {'seller_classification':self.classification}

    async def execute(self, sql, *args):
        if 'UPDATE public.tenants' in sql:
            self.classification = args[1]
        elif 'INSERT INTO public.admin_management_events' in sql:
            self.events.append(args)
        else:
            raise AssertionError(sql)


def test_only_platform_owner_can_set_explicit_classification_and_changes_are_audited():
    app,db = FastAPI(),Database()
    actor = PlatformOwner(uuid4())
    tenant = uuid4()
    app.state.finance = SimpleNamespace(pool=db)
    app.include_router(router)
    path = f'/api/v1/admin/tenants/{tenant}/seller-classification'
    body = {'seller_classification':'HIGH_VOLUME_COST_SENSITIVE_SELLER'}
    with TestClient(app) as client:
        assert client.patch(path,json=body).status_code in (401,403)
        assert db.classification == 'STANDARD' and not db.events
        app.dependency_overrides[authenticate_platform_owner] = lambda:actor
        assert client.patch(path,json=body).status_code == 200
        assert db.classification == 'HIGH_VOLUME_COST_SENSITIVE_SELLER'
        event = db.events[0]
        assert event[0] == actor.user_id and event[1] == tenant
        assert event[2] == 'UPDATE_SELLER_CLASSIFICATION'
        assert 'STANDARD' in event[4] and 'HIGH_VOLUME_COST_SENSITIVE_SELLER' in event[4]
        assert client.patch(path,json=body).status_code == 200 and len(db.events) == 1
        assert client.patch(path,json={'seller_classification':'INFERRED_FROM_NAME'}).status_code == 422
        assert len(db.events) == 1
