"""Public documentation assistance and a cookie bridge for existing revocable sessions.

Public answers have no tenant service, database tool, or conversational action gateway.
Cookie mutations require an exact same-origin request and a custom CSRF header.
"""
import asyncio
import hashlib
import re
import time
from collections import OrderedDict
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

COOKIE = 'easyinvio_browser_session'
router = APIRouter()
_limits = OrderedDict()


def same_origin(request):
    origin = request.headers.get('origin', '')
    expected = f'{request.url.scheme}://{request.url.netloc}'
    if origin != expected or request.headers.get('x-easyinvio-session') != '1':
        raise HTTPException(403, 'Open EasyInvio in the same browser to continue')


def remember_browser(request, response, token, expires):
    # The bearer remains in memory in the workspace. Navigation uses this
    # HttpOnly, same-site cookie; no access or refresh token enters web storage.
    if request.headers.get('origin') not in {None, f'{request.url.scheme}://{request.url.netloc}'}:
        return
    response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == 'https',
                        samesite='strict', path='/', max_age=max(0, int(expires-time.time())))
    response.headers['Cache-Control'] = 'no-store'


def bearer_request(request):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, 'Sign in to your workspace')
    headers = [(key, value) for key, value in request.scope['headers'] if key.lower() != b'authorization']
    try:
        encoded = ('Bearer ' + token).encode('ascii')
    except UnicodeError:
        raise HTTPException(401, 'Invalid browser session') from None
    headers.append((b'authorization', encoded))
    return Request({**request.scope, 'headers': headers})


@router.get('/api/v1/public/session')
async def browser_status(request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Cookie'
    if getattr(request.app.state, 'local_preview', False) or not request.cookies.get(COOKIE):
        return {'authenticated': False}
    from backend.identity import me
    try:
        identity = await me(bearer_request(request))
    except HTTPException as error:
        if error.status_code not in {401, 403}:
            raise
        response.delete_cookie(COOKIE, path='/')
        return {'authenticated': False}
    return {'authenticated': True, 'name': identity.get('full_name') or 'Your workspace'}


@router.post('/api/v1/auth/browser-session/restore')
async def restore_browser(request: Request, response: Response):
    same_origin(request)
    # Reuse renewal's live role checks, provider validation, revocation and
    # eight-hour absolute limit. Visiting the page never bypasses these checks.
    from backend.identity import renew
    return await renew(bearer_request(request), response)


@router.post('/api/v1/public/session/logout')
async def browser_logout(request: Request, response: Response):
    same_origin(request)
    from backend.identity import logout
    try:
        await logout(bearer_request(request), response)
    except HTTPException as error:
        if error.status_code not in {401, 403}:
            raise
    response.delete_cookie(COOKIE, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return {'logged_out': True}


class PublicQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=3, max_length=1000)


def needs_workspace(query):
    # This gate improves UX. Privacy does not depend on classification: even an
    # adversarial prompt reaches only the public-document retriever below.
    generic_howto = bool(re.match(r'\s*how\s+(?:do|can|to)\b', query, re.I))
    if generic_howto and not re.search(r'\b(?:EINVIO[-_]?\d+|\d{8,}|customers|password|secret|balance|wallet)\b|@', query, re.I):
        return False
    return bool(re.search(
        r'\b(?:track|locate|find|cancel|refund|return|book)\s+(?:(?:my|our|the|a|this|that)\s+)?(?:order|shipment|parcel|package|booking|payment)\b|'
        r'\b(?:my|our|customer[’\x27]?s?)\s+(?:balance|wallet|refund|payment|order|shipment|package|address|email|invoice)\b|'
        r'\b(?:show|list|reveal|export)\b.{0,35}\b(?:customers|addresses|orders|shipments|refunds|balances)\b|'
        r'\b(?:EINVIO[-_]?\d+|[A-Z]{2}\d{9}[A-Z]{2}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\b|'
        r'@[\w.-]+|\b(?:password|api.?key|access.?token|secret)\s*[:=]|\b\d{8,}\b', query, re.I))


def admit(request):
    # Bounded per-process controls plus a shared anonymous runtime budget.
    # Edge rate limits should additionally be configured for multi-instance traffic.
    now = time.monotonic()
    peer = request.client.host if request.client else 'unknown'
    identity = hashlib.sha256(peer.encode()).hexdigest()
    for key, limit in ((identity, 8), ('global', 30)):
        start, count = _limits.pop(key, (now, 0))
        if now-start >= 60:
            start, count = now, 0
        _limits[key] = (start, count+1)
        if count >= limit:
            raise HTTPException(429, 'Please wait a minute before asking another question', headers={'Retry-After': '60'})
    while len(_limits) > 2048:
        _limits.popitem(last=False)


@router.post('/api/v1/public/assistance')
async def public_assistance(body: PublicQuestion, request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    admit(request)
    query = body.query.strip()
    if needs_workspace(query):
        return {'answer': 'Open your signed-in workspace to check a shipment, payment, return or refund. I can explain the process here without accessing account records.',
                'sources': [], 'requires_login': True, 'action_url': '/login', 'mode': 'WORKSPACE_REQUIRED'}
    weight = re.search(r'\b(\d+(?:\.\d{1,3})?)\s*(?:kg|kilograms?)\b', query, re.I)
    if weight and re.search(r'\b(?:cost|rate|quote|price|estimate|send|ship)\b', query, re.I):
        from main import Address, Dimensions, RatingRequest
        from backend.advanced_logistics import preview_rates
        try:
            address = Address(name='Sample', line1='Sample', city='Sample', postal_code='SW1A 1AA', country_code='GB')
            value = preview_rates(RatingRequest(origin=address, destination=address, weights_kg=[weight[1]],
                dimensions=[Dimensions(length_cm=30, width_cm=20, height_cm=10)]))
        except ValueError:
            raise HTTPException(422, 'Enter a parcel weight between 0.001 and 1000 kg') from None
        rates = '; '.join(f"{item['service_code']}: GBP {item['client_price_ex_tax']}" for item in value['rates'])
        return {'answer': f'Illustrative sample for {weight[1]} kg in a 30 × 20 × 10 cm parcel: {rates}. These simulated prices do not price your actual countries or route and cannot be booked. Use Quick Rate Preview to explore the sample, or your workspace for a carrier quote with complete addresses and dimensions.',
                'sources': [], 'requires_login': False, 'mode': 'ILLUSTRATIVE_RATES'}
    from backend.agents.supervisor import supervisor
    engine = supervisor(request)
    try:
        async with asyncio.timeout(35):
            result = await engine.help.answer(SimpleNamespace(tenant_id='public-documentation', role='PUBLIC'), query)
    except (TimeoutError, HTTPException):
        return {'answer': 'Guidance is taking longer than expected. You can browse the Help Centre or try again shortly.',
                'sources': [{'title': 'Help Centre', 'url': '/help'}], 'requires_login': False, 'mode': 'TEMPORARILY_UNAVAILABLE'}
    # No prompts, keys, provider diagnostics or internal source filenames leave here.
    return {'answer': result['answer'], 'sources': [{'title': item['title'], 'url': item['url']} for item in result.get('sources', [])],
            'requires_login': False, 'mode': result.get('mode', 'DOCUMENT_EXCERPTS')}
