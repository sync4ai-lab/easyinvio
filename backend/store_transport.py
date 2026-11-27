"""Bounded credential-safe HTTP to configured public store origins."""
from __future__ import annotations
import asyncio
import ipaddress
import json
import socket
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException

def https_url(value: str, *, origin: bool = False) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.query or parsed.port not in {None,443}
            or (origin and parsed.path not in {'','/'})):
        raise ValueError('Use a public HTTPS origin without credentials, port, query or fragment')
    host=parsed.hostname.lower()
    if '.' not in host or host.endswith(('.localhost','.local','.internal')):
        raise ValueError('Private store hosts are not permitted')
    try:
        if not ipaddress.ip_address(host).is_global: raise ValueError('Private host')
    except ValueError:
        # A hostname is permitted, but every connection is DNS checked below.
        if all(c in '0123456789abcdef:.' for c in host): raise
    return value.rstrip('/') if origin else value

async def public_host(url: str) -> str:
    host=urlsplit(https_url(url)).hostname
    try:
        async with asyncio.timeout(5):
            results=await asyncio.get_running_loop().getaddrinfo(host,443,type=socket.SOCK_STREAM)
        if not results or any(not ipaddress.ip_address(result[4][0]).is_global for result in results):
            raise ValueError()
        return results[0][4][0]
    except (OSError,ValueError,TimeoutError):
        raise HTTPException(422,'Store endpoint must resolve only to public IP addresses') from None

async def store_json(client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> Any:
    # MockTransport is explicitly an offline fixture; production always checks DNS.
    if not isinstance(client._transport,httpx.MockTransport):
        host=urlsplit(url).hostname
        address=await public_host(url)
        # Pin the validated public address for this request, retaining TLS SNI
        # and HTTP Host. A second DNS lookup cannot rebind to an internal host.
        parsed=httpx.URL(url)
        kwargs['headers']={**kwargs.get('headers',{}),'Host':parsed.netloc.decode()}
        kwargs['extensions']={**kwargs.get('extensions',{}),'sni_hostname':host}
        url=str(parsed.copy_with(host=address))
    kwargs['headers']={**kwargs.get('headers',{}),'Accept-Encoding':'identity'}
    try:
        async with client.stream(method,url,timeout=20,follow_redirects=False,**kwargs) as response:
            if response.headers.get('content-encoding','identity').lower() not in {'','identity'}:
                raise HTTPException(502,'Compressed store responses are not accepted')
            if response.status_code not in {200,201,202,204}:
                raise HTTPException(502,f'Store API returned HTTP {response.status_code}; check credentials, scopes and connection settings')
            raw=bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw)>2_097_152: raise HTTPException(502,'Store API response exceeds 2 MB')
            return json.loads(raw,parse_float=Decimal) if raw else {}
    except (httpx.HTTPError,ValueError,TypeError):
        raise HTTPException(502,'Store API unavailable or returned invalid JSON; credentials and response body are hidden') from None
