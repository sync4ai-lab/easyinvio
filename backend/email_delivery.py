"""Selectable notification email delivery; Hostinger SMTP is the default.

SMTP runs off the event loop. No automatic provider failover is permitted:
connection loss during DATA is an uncertain send, not permission to send twice.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import formatdate
import re
import smtplib
import ssl
from typing import Literal

import httpx
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmailDeliverySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', hide_input_in_errors=True)
    email_delivery_provider: Literal['HOSTINGER_SMTP', 'SENDGRID'] = 'HOSTINGER_SMTP'
    smtp_host: str = 'smtp.hostinger.com'
    smtp_port: Literal[465, 587] = 465
    smtp_username: str = ''
    smtp_password: SecretStr = SecretStr('')
    smtp_timeout_seconds: int = Field(default=10, ge=1, le=15)

    @field_validator('smtp_port', mode='before')
    @classmethod
    def environment_port(cls, value: object) -> object:
        # Environment values are strings; Literal[int] does not coerce them.
        # Preserve the strict TLS-only port allowlist after normalisation.
        if isinstance(value, str) and value.strip() in {'465', '587'}:
            return int(value.strip())
        return value

    @field_validator('smtp_host')
    @classmethod
    def hostname(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value)>253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',value) or '..' in value:
            raise ValueError('SMTP_HOST must be the mail server hostname from your email hosting panel')
        return value


def mailbox(value: str) -> bool:
    return bool(isinstance(value,str) and len(value)<=254 and re.fullmatch(r'[^\s<>(),;:\x00-\x1f\x7f@]+@[^\s<>(),;:\x00-\x1f\x7f@]+\.[^\s<>(),;:\x00-\x1f\x7f@]+',value))


def email_configured(config: EmailDeliverySettings, from_address: str, api_key: SecretStr) -> bool:
    if not mailbox(from_address):
        return False
    if config.email_delivery_provider == 'SENDGRID':
        return bool(api_key.get_secret_value())
    return bool(mailbox(config.smtp_username) and config.smtp_password.get_secret_value()
                and config.smtp_username.casefold()==from_address.casefold())


@dataclass(frozen=True)
class EmailReceipt:
    state: Literal['ACCEPTED','FAILED','RETRYABLE','REVIEW_REQUIRED']
    reference: str | None = None
    error_code: str | None = None


def refusal(code: int) -> EmailReceipt:
    if 400<=code<500:
        return EmailReceipt('RETRYABLE',error_code='SMTP_TEMPORARY_REFUSAL')
    return EmailReceipt('FAILED',error_code='SMTP_REJECTED')


def smtp_send(config: EmailDeliverySettings, message: EmailMessage, sender: str, recipient: str) -> EmailReceipt:
    connection = None
    phase = 'CONNECT'
    try:
        context = ssl.create_default_context()
        if config.smtp_port == 465:
            connection = smtplib.SMTP_SSL(config.smtp_host,465,timeout=config.smtp_timeout_seconds,context=context)
        else:
            connection = smtplib.SMTP(config.smtp_host,587,timeout=config.smtp_timeout_seconds)
            connection.ehlo()
            phase='TLS'
            connection.starttls(context=context)
        connection.ehlo()
        phase='AUTH'
        connection.login(config.smtp_username,config.smtp_password.get_secret_value())
        phase='SEND'
        rejected = connection.send_message(message,from_addr=sender,to_addrs=[recipient])
        if rejected:
            code = next(iter(rejected.values()))[0]
            return refusal(code)
        # Message-ID identifies the submitted message; this is SMTP acceptance,
        # not a remote mailbox delivery receipt. Ignore a failed QUIT after DATA.
        return EmailReceipt('ACCEPTED',reference=str(message['Message-ID']))
    except smtplib.SMTPRecipientsRefused as error:
        return refusal(next(iter(error.recipients.values()))[0])
    except smtplib.SMTPResponseException as error:
        return refusal(error.smtp_code)
    except (smtplib.SMTPNotSupportedError, ssl.SSLCertVerificationError):
        return EmailReceipt('FAILED',error_code='SMTP_TLS_OR_AUTH_UNSUPPORTED')
    except (smtplib.SMTPException, OSError):
        return EmailReceipt('REVIEW_REQUIRED' if phase=='SEND' else 'RETRYABLE',
            error_code='SMTP_SEND_OUTCOME_UNCERTAIN' if phase=='SEND' else 'SMTP_CONNECTION_FAILED')
    finally:
        if connection is not None:
            try:
                connection.quit()
            except Exception:
                try: connection.close()
                except Exception: pass


async def send_notification_email(client: httpx.AsyncClient, config: EmailDeliverySettings, *,
                                  sender: str, recipient: str, subject: str, text: str,
                                  message_key: str, api_key: SecretStr,
                                  html_body: str | None = None) -> EmailReceipt:
    if not mailbox(recipient) or not mailbox(sender):
        return EmailReceipt('FAILED',error_code='EMAIL_ADDRESS_INVALID')
    if not email_configured(config,sender,api_key):
        return EmailReceipt('FAILED',error_code='EMAIL_NOT_CONFIGURED')
    # Headers must not accept a user-supplied newline or a second recipient.
    subject = re.sub(r'[\x00-\x1f\x7f]+',' ',subject).strip()[:250]
    if config.email_delivery_provider == 'SENDGRID':
        try:
            content=[{'type':'text/plain','value':text}]
            if html_body is not None:content.append({'type':'text/html','value':html_body})
            response=await client.post('https://api.sendgrid.com/v3/mail/send',
                headers={'Authorization':'Bearer '+api_key.get_secret_value()},
                json={'personalizations':[{'to':[{'email':recipient}]}],
                      'from':{'email':sender,'name':'EasyInvio'},'subject':subject,'content':content,
                      'tracking_settings':{'click_tracking':{'enable':False,'enable_text':False}}},
                timeout=15,follow_redirects=False)
            if response.status_code==202:
                return EmailReceipt('ACCEPTED',reference=response.headers.get('x-message-id','')[:200] or None)
            if response.status_code==429:return EmailReceipt('RETRYABLE',error_code='PROVIDER_RATE_LIMITED')
            if 400<=response.status_code<500:return EmailReceipt('FAILED',error_code='PROVIDER_REJECTED')
            return EmailReceipt('REVIEW_REQUIRED',error_code='PROVIDER_OUTCOME_UNCERTAIN')
        except httpx.HTTPError:
            return EmailReceipt('REVIEW_REQUIRED',error_code='SEND_OUTCOME_UNCERTAIN')
    message=EmailMessage(policy=SMTP_POLICY)
    message['From']='EasyInvio <'+sender+'>'
    message['To']=recipient
    message['Reply-To']=sender
    message['Subject']=subject
    message['Date']=formatdate(localtime=False, usegmt=True)
    # Stable across a definitive-refusal retry, with no contact address in it.
    import hashlib
    digest=hashlib.sha256(message_key.encode()).hexdigest()
    message['Message-ID']='<'+digest+'@'+sender.rsplit('@',1)[1]+'>'
    message.set_content(text)
    if html_body is not None:message.add_alternative(html_body,subtype='html')
    try:
        return await asyncio.wait_for(asyncio.to_thread(smtp_send,config,message,sender,recipient),timeout=45)
    except TimeoutError:
        # The thread may still be completing DATA. Never resend after this timer.
        return EmailReceipt('REVIEW_REQUIRED',error_code='SMTP_SEND_OUTCOME_UNCERTAIN')
