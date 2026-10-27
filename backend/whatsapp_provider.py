"""Selected WhatsApp transport, common UAT fences and self-service Gupshup contract.
No account mutations, implicit opt-in, provider failover or automatic HTTP retries.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
import re
import secrets
from typing import Literal
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class TemplateBinding(BaseModel):
    provider_id: str = Field(min_length=1,max_length=200)
    language: str = Field(min_length=2,max_length=20)
    parameters: list[str] = Field(max_length=10)
    category: Literal['UTILITY','AUTHENTICATION','MARKETING'] = 'UTILITY'

class WhatsAppProviderSettings(BaseSettings):
    model_config=SettingsConfigDict(env_file='.env',extra='ignore',hide_input_in_errors=True)
    whatsapp_provider: Literal['TWILIO','GUPSHUP']='TWILIO'
    whatsapp_uat_mode: bool=True
    whatsapp_test_recipients: list[str]=Field(default_factory=list,max_length=100)
    whatsapp_outbound_paused: bool=True
    gupshup_enabled: bool=False
    gupshup_product: Literal['SELF_SERVICE']='SELF_SERVICE'
    gupshup_api_key: SecretStr=SecretStr('')
    gupshup_app_name: str=''
    gupshup_app_id: str=''
    gupshup_source_number: str=''
    gupshup_webhook_url: str=''
    gupshup_webhook_auth_mode: Literal['DISABLED','SOURCE_IP','HEADER','HEADER_AND_SOURCE_IP']='DISABLED'
    gupshup_webhook_token: SecretStr=SecretStr('')
    gupshup_callback_ips_confirmed: bool=False
    gupshup_callback_ips: list[str]=Field(default_factory=list,max_length=50)
    gupshup_templates: dict[str,TemplateBinding]=Field(default_factory=dict)

    @model_validator(mode='after')
    def safe_gupshup(self):
        allowed={'SUPPORT':{'body'},'SHIPMENT':{'reference','body','tracking'},'RETURN':{'heading','body','link'}}
        for name,binding in self.gupshup_templates.items():
            if name not in allowed or not set(binding.parameters)<=allowed[name] or binding.category!='UTILITY':
                raise ValueError('Use supported logical utility templates and parameters: SUPPORT, SHIPMENT, RETURN')
        for phone in self.whatsapp_test_recipients:
            if not re.fullmatch(r'\+[1-9][0-9]{7,14}',phone):raise ValueError('WhatsApp test recipients require E.164')
        for value in self.gupshup_callback_ips:
            ipaddress.ip_address(value)  # Exact addresses only; never a broad network.
        if self.gupshup_enabled:
            url=urlsplit(self.gupshup_webhook_url)
            if (not self.gupshup_api_key.get_secret_value() or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',self.gupshup_app_name)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',self.gupshup_app_id)
                or not re.fullmatch(r'\+[1-9][0-9]{7,14}',self.gupshup_source_number)
                or url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment
                or url.path!='/api/v1/integrations/whatsapp/gupshup/webhook'):
                raise ValueError('Enabled Gupshup requires self-service credentials, app, source and exact HTTPS webhook')
            mode=self.gupshup_webhook_auth_mode
            if mode=='DISABLED':raise ValueError('Gupshup callback authentication must be configured')
            if mode in {'HEADER','HEADER_AND_SOURCE_IP'} and len(self.gupshup_webhook_token.get_secret_value().encode())<32:
                raise ValueError('Gupshup configured webhook header token must be at least 32 bytes')
            if mode in {'SOURCE_IP','HEADER_AND_SOURCE_IP'} and (not self.gupshup_callback_ips_confirmed or not self.gupshup_callback_ips):
                raise ValueError('Gupshup activation requires confirmed self-service callback origin IPs')
        return self

def provider(settings):return getattr(settings,'whatsapp_provider','TWILIO')
def enabled(settings):
    return bool(getattr(settings,'gupshup_enabled',False)) if provider(settings)=='GUPSHUP' else bool(getattr(settings,'twilio_enabled',False))
def number(settings):
    return getattr(settings,'gupshup_source_number','') if provider(settings)=='GUPSHUP' else getattr(settings,'twilio_whatsapp_number','')
def account(settings):
    return getattr(settings,'gupshup_app_id','') if provider(settings)=='GUPSHUP' else getattr(settings,'twilio_account_sid','')
def paused(settings):return bool(getattr(settings,'whatsapp_outbound_paused',False))
def recipient_error(settings,recipient):
    if paused(settings):return 'WHATSAPP_OUTBOUND_PAUSED'
    if not enabled(settings):return 'WHATSAPP_DISABLED'
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}',recipient or ''):return 'INVALID_WHATSAPP_RECIPIENT'
    # Settings-less legacy test doubles keep the pre-migration policy. Real Settings default to UAT.
    if getattr(settings,'whatsapp_uat_mode',False) and recipient not in getattr(settings,'whatsapp_test_recipients',[]):return 'WHATSAPP_TEST_RECIPIENT_NOT_ALLOWED'
    return None

def template(settings,logical):
    value=getattr(settings,'gupshup_templates',{}).get(logical)
    if value is not None and not isinstance(value,TemplateBinding):value=TemplateBinding.model_validate(value)
    return value

def valid_message_id(settings,value):
    if not isinstance(value,str):return False
    return bool(re.fullmatch(r'[A-Za-z0-9_.:+/=-]{1,512}',value or '')) if provider(settings)=='GUPSHUP' else bool(re.fullmatch(r'SM[0-9a-fA-F]{32}',value or ''))

@dataclass(frozen=True)
class SendResult:
    outcome: Literal['ACCEPTED','REJECTED','RETRYABLE','UNCERTAIN']
    external_id: str|None=None
    code: str|None=None
    http_status: int|None=None

class TwilioAdapter:
    def __init__(self,settings,client):self.settings,self.client=settings,client
    async def send(self,payload):
        s=self.settings
        try:
            r=await self.client.post(f'https://api.twilio.com/2010-04-01/Accounts/{s.twilio_account_sid}/Messages.json',
                auth=httpx.BasicAuth(s.twilio_account_sid,s.twilio_auth_token.get_secret_value()),data=payload,timeout=15,follow_redirects=False)
        except httpx.HTTPError:return SendResult('UNCERTAIN',code='SEND_OUTCOME_UNCERTAIN')
        if r.status_code==201:
            try:ref=r.json().get('sid')
            except ValueError:ref=None
            return SendResult('ACCEPTED',ref,http_status=201) if valid_message_id(s,ref) else SendResult('UNCERTAIN',code='INVALID_PROVIDER_RECEIPT')
        return SendResult('RETRYABLE' if r.status_code==429 else 'REJECTED' if 400<=r.status_code<500 else 'UNCERTAIN',code='PROVIDER_REJECTED',http_status=r.status_code)

class TwilioChatAdapter:
    # Keep the established SDK compatibility path behind the transport boundary.
    def __init__(self,client):self.client=client
    async def send(self,**payload):
        return await asyncio.to_thread(self.client.messages.create,**payload)


class GupshupAdapter:
    """Self-service /wa API only. App-language is fixed by the approved template ID."""
    def __init__(self,settings,client):self.settings,self.client=settings,client
    async def send(self,recipient,body,*,binding=None,parameters=None,media_url=None,received_at=None):
        s=self.settings
        if binding is None and (received_at is None or received_at<datetime.now(timezone.utc)-timedelta(hours=23,minutes=59)):
            return SendResult('REJECTED',code='SESSION_WINDOW_REQUIRED')
        payload={'channel':'whatsapp','source':number(s).lstrip('+'),'destination':recipient.lstrip('+'),'src.name':s.gupshup_app_name}
        if binding:
            if any(name not in (parameters or {}) for name in binding.parameters):return SendResult('REJECTED',code='TEMPLATE_PARAMETERS_MISSING')
            payload['template']=json.dumps({'id':binding.provider_id,'params':[str(parameters[name]) for name in binding.parameters]})
            endpoint='template/msg'
        else:
            message={'type':'text','text':body}
            if media_url:
                parsed=urlsplit(media_url)
                if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:return SendResult('REJECTED',code='INVALID_MEDIA_URL')
                message=({'type':'image','originalUrl':media_url,'previewUrl':media_url,'caption':body}
                    if parsed.path.lower().endswith(('.png','.jpg','.jpeg')) else
                    {'type':'file','url':media_url,'filename':'EasyInvio-return-document.pdf'})
            payload['message']=json.dumps(message);endpoint='msg'
        try:
            r=await self.client.post('https://api.gupshup.io/wa/api/v1/'+endpoint,headers={'apikey':s.gupshup_api_key.get_secret_value()},
                data=payload,timeout=15,follow_redirects=False)
        except httpx.HTTPError:return SendResult('UNCERTAIN',code='SEND_OUTCOME_UNCERTAIN')
        try:data=r.json()
        except ValueError:data={}
        if not isinstance(data,dict):data={}
        if 200<=r.status_code<300 and data.get('status')=='submitted' and valid_message_id(s,data.get('messageId')):
            return SendResult('ACCEPTED',data['messageId'],http_status=r.status_code)
        # No documented request idempotency. Never automatically retry 429/timeouts/5xx.
        return SendResult('REJECTED' if 400<=r.status_code<500 else 'UNCERTAIN',code='PROVIDER_REJECTED' if 400<=r.status_code<500 else 'PROVIDER_OUTCOME_UNCERTAIN',http_status=r.status_code)

def authenticate_gupshup_origin(request,settings):
    if not getattr(settings,'gupshup_enabled',False):raise HTTPException(503,'Gupshup ingress is disabled')
    mode=settings.gupshup_webhook_auth_mode
    if mode not in {'SOURCE_IP','HEADER','HEADER_AND_SOURCE_IP'}:
        raise HTTPException(503,'Gupshup callback origin has not been configured')
    if mode in {'HEADER','HEADER_AND_SOURCE_IP'}:
        expected=settings.gupshup_webhook_token.get_secret_value()
        supplied=request.headers.getlist('x-easyinvio-webhook-token')
        if len(expected.encode())<32:raise HTTPException(503,'Gupshup configured header token is unavailable')
        if len(supplied)!=1 or not secrets.compare_digest(supplied[0].encode(),expected.encode()):
            raise HTTPException(403,'Gupshup configured webhook header rejected')
        if mode=='HEADER':return
    if not settings.gupshup_callback_ips_confirmed or not settings.gupshup_callback_ips:
        raise HTTPException(503,'Gupshup callback IPs have not been confirmed')
    try:
        if os.environ.get('VERCEL')=='1':
            # Only the actual Vercel runtime may trust its platform-overwritten header.
            values=request.headers.getlist('x-vercel-forwarded-for')
            if len(values)!=1 or ',' in values[0]:raise ValueError()
            address=ipaddress.ip_address(values[0].strip())
        else:address=ipaddress.ip_address(request.client.host)
        if str(address) not in settings.gupshup_callback_ips:raise ValueError()
    except (ValueError,AttributeError):raise HTTPException(403,'Gupshup callback origin rejected') from None
