"""One bounded tracking grammar for public web and WhatsApp consumers."""
from __future__ import annotations
import re
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from pydantic import BaseModel, ConfigDict, Field

class ParsedTrackingInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    kind: Literal['REFERENCE','CAPABILITY']
    value: str=Field(min_length=8,max_length=100)

def parse_tracking_input(text: str, trusted_origins: set[str]) -> ParsedTrackingInput:
    value=text.strip()
    if len(value)>2048:raise ValueError('Tracking input is too long')
    command=re.fullmatch(r'track\s+link\s+([A-Za-z0-9_-]{40,100})',value,re.I)
    if command:value=command[1]
    if value.startswith(('/','https://','http://')):
        url=urlsplit(value)
        if url.netloc and (url.username or url.password or f'{url.scheme}://{url.netloc}' not in trusted_origins):
            raise ValueError('Use a tracking link from your EasyInvio environment')
        if url.path not in {'/track','/tracking.html'}:raise ValueError('Use an EasyInvio tracking link')
        query=parse_qs(url.query)
        candidates=[item for item in [url.fragment,*query.get('token',[]),*query.get('q',[])] if item]
        if len(candidates)!=1:raise ValueError('Use one tracking number or secure link')
        if query.get('q') and re.fullmatch(r'[A-Za-z0-9_-]{8,100}',candidates[0]):return ParsedTrackingInput(kind='REFERENCE',value=candidates[0])
        return parse_tracking_input(candidates[0],trusted_origins)
    if re.fullmatch(r'[A-Za-z0-9_-]{40,100}',value):return ParsedTrackingInput(kind='CAPABILITY',value=value)
    if re.fullmatch(r'[A-Za-z0-9_-]{8,100}',value):return ParsedTrackingInput(kind='REFERENCE',value=value)
    raise ValueError('Enter a complete tracking number or EasyInvio tracking link')

def trusted_tracking_origins(settings: object) -> set[str]:
    result=set()
    for name in ('booking_page_url','auth_recovery_redirect_url'):
        url=urlsplit(str(getattr(settings,name,'') or ''))
        if url.scheme in {'https','http'} and url.netloc:result.add(f'{url.scheme}://{url.netloc}')
    return result
