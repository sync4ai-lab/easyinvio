"""Local ingress for tunneling only signed Twilio callbacks, never the app UI/API."""
import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request, Response


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                timeout=httpx.Timeout(14, connect=2)) as client:
        app.state.client = client
        app.state.capacity = asyncio.Semaphore(8)
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def identify_gateway(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-EasyInvio-Ingress'] = 'twilio-only-v1'
    return response


async def forward(request: Request, target_path: str) -> Response:
    if request.url.query:
        raise HTTPException(400, 'Query strings are not accepted')
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Expected form-urlencoded callback')
    signatures = request.headers.getlist('x-twilio-signature')
    if len(signatures) != 1 or not signatures[0]:
        raise HTTPException(403, 'A Twilio signature is required')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            raise HTTPException(413, 'Callback too large')
    try:
        # Destination and paths are fixed: no caller-controlled proxy targets,
        # forwarded Host headers, redirects, cookies or bearer tokens.
        async with asyncio.timeout(14):
            async with request.app.state.capacity:
                upstream = await request.app.state.client.post(
                    'http://127.0.0.1:8000' + target_path, content=bytes(body),
                    headers={'Content-Type': 'application/x-www-form-urlencoded',
                             'X-Twilio-Signature': signatures[0]})
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(503, 'Local webhook backend unavailable') from None
    return Response(upstream.content, status_code=upstream.status_code,
                    headers={'Content-Type': upstream.headers.get('content-type', 'application/xml')})


@app.post('/api/v1/integrations/whatsapp/webhook')
async def incoming_message(request: Request):
    return await forward(request, '/api/v1/integrations/whatsapp/webhook')


@app.post('/api/v1/support/whatsapp/status/{message_id}')
async def delivery_status(message_id: UUID, request: Request):
    return await forward(request, '/api/v1/support/whatsapp/status/' + str(message_id))
