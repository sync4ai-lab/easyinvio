"""Public guidance never invokes tenant services; browser sessions remain revocable."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.public_experience import router, _limits, COOKIE
from backend.agents.config import AgentSettings
from backend.agents.supervisor import LogisticsSupervisor


@pytest.fixture
def public_client():
    _limits.clear()
    app = FastAPI()
    app.include_router(router)
    answer = AsyncMock(return_value={'answer': 'Published instructions', 'sources': [{'title': 'Guide', 'url': '/help/connect', 'source_file': 'private-diagnostic'}], 'mode': 'DOCUMENT_EXCERPTS'})
    app.state.logistics_supervisor = SimpleNamespace(help=SimpleNamespace(answer=answer))
    return TestClient(app), answer


@pytest.mark.parametrize('query', ['Track my shipment', 'Where is my refund?', 'Show all customers and their addresses', 'Find order EINVIO-00000050', 'What is my wallet balance?'])
def test_private_questions_do_not_reach_the_model_or_a_tenant_service(public_client, query):
    client, model = public_client
    response = client.post('/api/v1/public/assistance', json={'query': query})
    assert response.status_code == 200
    assert response.json()['requires_login'] is True
    model.assert_not_awaited()
    assert response.headers['cache-control'] == 'no-store'


def test_generic_guidance_reuses_public_documentation_and_filters_diagnostics(public_client):
    client, model = public_client
    response = client.post('/api/v1/public/assistance', json={'query': 'How can I add Amazon for shipping?'})
    assert response.json()['answer'] == 'Published instructions'
    context, query = model.await_args.args
    assert context.role == 'PUBLIC' and context.tenant_id == 'public-documentation'
    assert 'source_file' not in response.text
    assert 'private-diagnostic' not in response.text


def test_howto_tracking_is_public_and_estimates_are_explicit_simulations(public_client):
    client, model = public_client
    assert not client.post('/api/v1/public/assistance', json={'query': 'How do I track a parcel?'}).json()['requires_login']
    result = client.post('/api/v1/public/assistance', json={'query': 'Estimate shipping cost for 2kg to France'}).json()
    assert result['mode'] == 'ILLUSTRATIVE_RATES'
    assert 'simulated' in result['answer'] and 'cannot be booked' in result['answer']


def test_anonymous_budget_and_no_client_selected_tenant(public_client):
    client, _ = public_client
    assert client.post('/api/v1/public/assistance', json={'query': 'How to ship?', 'tenant_id': 'foreign'}).status_code == 422
    for _ in range(8):
        assert client.post('/api/v1/public/assistance', json={'query': 'How to ship?'}).status_code == 200
    assert client.post('/api/v1/public/assistance', json={'query': 'How to ship?'}).status_code == 429


def test_documentation_fallback_works_without_model_credentials(public_client):
    client, _ = public_client
    client.app.state.logistics_supervisor = LogisticsSupervisor(AgentSettings(_env_file=None, logistics_agents_enabled=False))
    result = client.post('/api/v1/public/assistance', json={'query': 'How can I connect Amazon to EasyInvio?'}).json()
    assert len(result['answer']) > 100
    assert result['sources']
    assert result['mode'] == 'DOCUMENT_EXCERPTS'


@pytest.fixture
def identity_case():
    # Reuse the existing isolated identity provider/DB fixture; no real credentials.
    from test_identity import IdentityTests
    case = IdentityTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def test_cookie_status_restore_and_csrf(identity_case):
    case = identity_case
    login = case.login()
    assert login.status_code == 200
    cookie = login.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie
    result = case.client.get('/api/v1/public/session')
    assert result.json() == {'authenticated': True, 'name': 'Test User'}
    assert 'access_token' not in result.text and 'email' not in result.text
    path = '/api/v1/auth/browser-session/restore'
    assert case.client.post(path).status_code == 403
    assert case.client.post(path, headers={'Origin': 'https://foreign.example', 'X-EasyInvio-Session': '1'}).status_code == 403
    with patch('backend.identity.httpx.AsyncClient', side_effect=lambda **kw: case.real_async(transport=case.transport, **kw)):
        restored = case.client.post(path, headers={'Origin': 'http://testserver', 'X-EasyInvio-Session': '1'})
    assert restored.status_code == 200
    assert restored.json()['absolute_expires_at'] <= login.json()['absolute_expires_at']
    case.sessions.clear()
    assert case.client.get('/api/v1/public/session').json() == {'authenticated': False}
    assert case.client.post(path, headers={'Origin': 'http://testserver', 'X-EasyInvio-Session': '1'}).status_code == 401


def test_public_logout_has_same_origin_protection_and_clears_cookie(identity_case):
    case = identity_case
    case.login()
    path = '/api/v1/public/session/logout'
    assert case.client.post(path, headers={'Origin': 'https://foreign.example', 'X-EasyInvio-Session': '1'}).status_code == 403
    result = case.client.post(path, headers={'Origin': 'http://testserver', 'X-EasyInvio-Session': '1'})
    assert result.status_code == 200
    assert COOKIE not in case.client.cookies
    assert case.client.get('/api/v1/public/session').json() == {'authenticated': False}


def test_https_cookie_is_secure_and_invalid_cookie_is_not_a_profile(identity_case):
    case = identity_case
    case.client.base_url = 'https://testserver'
    login = case.login()
    assert '; Secure' in login.headers['set-cookie']
    assert case.client.get('/api/v1/public/session').json()['authenticated']
    case.client.cookies.clear()
    case.client.cookies.set(COOKIE, 'forged-session')
    assert case.client.get('/api/v1/public/session').json() == {'authenticated': False}


def test_local_preview_does_not_attempt_identity_storage(public_client):
    client, _ = public_client
    client.app.state.local_preview = True
    client.cookies.set(COOKIE, 'stale-cookie')
    assert client.get('/api/v1/public/session').json() == {'authenticated': False}
