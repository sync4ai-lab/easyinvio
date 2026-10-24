"""Hostinger SMTP behavior with real MIME messages and controlled transport IO."""
import asyncio
import smtplib
import ssl
import time
from unittest.mock import patch
import httpx
import pytest
from pydantic import SecretStr, ValidationError
from backend.email_delivery import EmailDeliverySettings, EmailReceipt, email_configured, send_notification_email


def settings(**changes):
    values=dict(smtp_username='support@easyinvio.com',smtp_password='synthetic-password')
    values.update(changes)
    return EmailDeliverySettings(_env_file=None,**values)


class SMTP:
    events=[]
    send_error=None
    starttls_error=None
    quit_error=None
    rejected={}

    def __init__(self,host,port,**kwargs):
        type(self).events.append(('connect',host,port,kwargs))
        self.sent=[]
    def ehlo(self):self.events.append(('ehlo',))
    def starttls(self,**kwargs):
        self.events.append(('starttls',kwargs))
        if self.starttls_error:raise self.starttls_error
    def login(self,username,password):self.events.append(('login',username))
    def send_message(self,message,**kwargs):
        self.events.append(('send',message,kwargs))
        if self.send_error:raise self.send_error
        return self.rejected
    def quit(self):
        self.events.append(('quit',))
        if self.quit_error:raise self.quit_error
    def close(self):self.events.append(('close',))


@pytest.fixture(autouse=True)
def smtp():
    SMTP.events=[];SMTP.send_error=None;SMTP.starttls_error=None;SMTP.quit_error=None;SMTP.rejected={}
    with patch('backend.email_delivery.smtplib.SMTP_SSL',SMTP),patch('backend.email_delivery.smtplib.SMTP',SMTP):
        yield SMTP


async def send(config=None,**changes):
    values=dict(sender='support@easyinvio.com',recipient='tester@example.test',subject='Booking confirmed',
                text='TEST booking reference EINVIO-SYNTHETIC',html_body='<p>TEST booking reference EINVIO-SYNTHETIC</p>',
                message_key='synthetic:1',api_key=SecretStr('a-legacy-key-must-not-trigger-sendgrid'))
    values.update(changes)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:pytest.fail('Hostinger must not call SendGrid'))) as client:
        return await send_notification_email(client,config or settings(),**values)


@pytest.mark.asyncio
@pytest.mark.parametrize('port',[465,587])
async def test_tls_auth_mime_and_sender_identity(port,smtp):
    receipt=await send(settings(smtp_port=port))
    assert receipt.state=='ACCEPTED'
    events=smtp.events;connect=events[0]
    assert connect[1:3]==('smtp.hostinger.com',port)
    context=connect[3].get('context') if port==465 else next(row[1]['context'] for row in events if row[0]=='starttls')
    assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
    if port==587:
        assert [row[0] for row in events].index('starttls') < [row[0] for row in events].index('login')
    message=next(row[1] for row in events if row[0]=='send')
    assert message['From']=='EasyInvio <support@easyinvio.com>'
    assert message['Reply-To']=='support@easyinvio.com'
    assert message['To']=='tester@example.test' and receipt.reference==message['Message-ID']
    assert message.get_body(preferencelist=('plain',)).get_content().startswith('TEST booking')
    assert message.get_body(preferencelist=('html',)) is not None


@pytest.mark.asyncio
async def test_quit_failure_does_not_change_accepted_message(smtp):
    smtp.quit_error=smtplib.SMTPServerDisconnected('after acceptance')
    assert (await send()).state=='ACCEPTED'
    assert len([row for row in smtp.events if row[0]=='send'])==1


@pytest.mark.asyncio
async def test_missing_starttls_never_authenticates_or_sends(smtp):
    smtp.starttls_error=smtplib.SMTPNotSupportedError('no STARTTLS')
    receipt=await send(settings(smtp_port=587))
    assert receipt.state=='FAILED'
    assert not any(row[0] in {'login','send'} for row in smtp.events)


@pytest.mark.asyncio
@pytest.mark.parametrize('error,state',[(smtplib.SMTPDataError(451,b'temporary'),'RETRYABLE'),
    (smtplib.SMTPDataError(550,b'rejected'),'FAILED'),(smtplib.SMTPServerDisconnected('during DATA'),'REVIEW_REQUIRED'),
    (TimeoutError('during DATA'),'REVIEW_REQUIRED')])
async def test_refusal_vs_ambiguous_data_never_auto_resends(error,state,smtp):
    smtp.send_error=error
    assert (await send()).state==state
    assert len([row for row in smtp.events if row[0]=='send'])==1


@pytest.mark.asyncio
async def test_smtp_recipient_refusals_and_header_injection(smtp):
    smtp.rejected={'tester@example.test':(450,b'temporary')}
    assert (await send()).state=='RETRYABLE'
    smtp.events=[]
    assert (await send(recipient='tester@example.test\r\nBcc: other@example.test')).state=='FAILED'
    assert not smtp.events


@pytest.mark.asyncio
async def test_hostinger_missing_credentials_does_not_use_legacy_key(smtp):
    receipt=await send(settings(smtp_password=''))
    assert receipt.state=='FAILED' and receipt.error_code=='EMAIL_NOT_CONFIGURED'
    assert not smtp.events


def test_plaintext_ports_and_unrelated_from_addresses_are_rejected():
    with pytest.raises(ValidationError):settings(smtp_port=25)
    assert not email_configured(settings(),'other@example.test',SecretStr('legacy'))


@pytest.mark.asyncio
async def test_network_runs_off_the_async_event_loop(smtp):
    original=smtp.send_message
    def slow(self,*args,**kwargs):time.sleep(.08);return original(self,*args,**kwargs)
    with patch.object(smtp,'send_message',slow):
        task=asyncio.create_task(send())
        await asyncio.sleep(.02)
        assert not task.done()
        assert (await task).state=='ACCEPTED'


@pytest.mark.asyncio
async def test_message_identity_is_stable_and_subject_is_sanitized(smtp):
    first=await send(subject='Hello\r\nBcc: other@example.test')
    second=await send()
    assert first.reference==second.reference
    message=next(row[1] for row in smtp.events if row[0]=='send')
    assert message['Bcc'] is None and '\n' not in message['Subject']

@pytest.mark.asyncio
@pytest.mark.parametrize('error,state',[(smtplib.SMTPAuthenticationError(535,b'synthetic invalid password'),'FAILED'),
    (ConnectionRefusedError('synthetic unavailable'),'RETRYABLE'),
    (ssl.SSLCertVerificationError('synthetic invalid certificate'),'FAILED')])
async def test_connection_and_authentication_failures_never_submit_message(error,state,smtp):
    with patch('backend.email_delivery.smtplib.SMTP_SSL',side_effect=error):
        receipt=await send()
    assert receipt.state==state
    assert not any(row[0]=='send' for row in smtp.events)


@pytest.mark.parametrize('port',['465','587'])
def test_real_environment_port_and_shared_notification_settings(monkeypatch,port):
    from backend.shipment_notifications import ShipmentNotificationSettings
    from backend.return_delivery import ReturnDeliverySettings
    monkeypatch.setenv('SMTP_PORT',port)
    monkeypatch.setenv('SMTP_USERNAME','support@easyinvio.com')
    monkeypatch.setenv('SMTP_PASSWORD','synthetic-password')
    monkeypatch.setenv('SHIPMENT_NOTIFICATION_TEST_RECIPIENTS','["tester@example.test"]')
    shipment=ShipmentNotificationSettings(_env_file=None,shipment_email_notifications_enabled=True)
    returns=ReturnDeliverySettings(_env_file=None,return_email_enabled=True)
    assert shipment.smtp_port==returns.smtp_port==int(port)
    assert shipment.shipment_notification_test_recipients==['tester@example.test']
    assert email_configured(shipment,shipment.shipment_email_from,shipment.shipment_sendgrid_api_key)
    assert email_configured(returns,returns.return_email_from,returns.return_sendgrid_api_key)


@pytest.mark.parametrize('port',['25','2525','smtp://465'])
def test_environment_does_not_bypass_secure_port_allowlist(monkeypatch,port):
    monkeypatch.setenv('SMTP_PORT',port)
    with pytest.raises(ValidationError):EmailDeliverySettings(_env_file=None)
