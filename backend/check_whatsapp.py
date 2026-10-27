"""Read-only WhatsApp setup check. Never sends messages or changes provider settings."""
import argparse
import asyncio
import json
import re
from urllib.parse import urlsplit
import httpx


def public_https(value, path=None):
    parsed=urlsplit(value or '')
    return bool(parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment and (path is None or parsed.path==path))


def configuration_report(settings, delivery, notifications, returns=None):
    from backend.whatsapp_provider import provider,enabled,paused,template
    if provider(settings)=='GUPSHUP':
        issues=[]
        if not enabled(settings):issues.append('GUPSHUP_DISABLED')
        if paused(settings):issues.append('WHATSAPP_OUTBOUND_PAUSED')
        if settings.whatsapp_uat_mode and not settings.whatsapp_test_recipients:issues.append('UAT_ALLOWLIST_EMPTY')
        mode=settings.gupshup_webhook_auth_mode
        if mode=='DISABLED':issues.append('CALLBACK_ORIGIN_UNCONFIRMED')
        if mode in {'HEADER','HEADER_AND_SOURCE_IP'} and len(settings.gupshup_webhook_token.get_secret_value().encode())<32:issues.append('WEBHOOK_HEADER_TOKEN_REQUIRED')
        if mode in {'SOURCE_IP','HEADER_AND_SOURCE_IP'} and (not settings.gupshup_callback_ips_confirmed or not settings.gupshup_callback_ips):issues.append('CALLBACK_IPS_UNCONFIRMED')
        for logical,active in [('SUPPORT',delivery.support_whatsapp_enabled),('SHIPMENT',notifications.shipment_whatsapp_notifications_enabled),('RETURN',bool(returns and returns.return_whatsapp_enabled))]:
            if active and not template(settings,logical):issues.append(logical+'_APPROVED_TEMPLATE_REQUIRED')
        return {'provider':'GUPSHUP','product':'SELF_SERVICE','enabled':enabled(settings),'paused':paused(settings),
            'local_config_valid':not issues,'issues':issues,'messages_sent':0,'templates':sorted(settings.gupshup_templates),
            'runtime_and_handset_delivery':'NOT_PROVEN_BY_CONFIGURATION_CHECK'}
    incoming=settings.twilio_webhook_url
    callback=delivery.support_whatsapp_status_url
    issues=[]
    if not public_https(incoming) or urlsplit(incoming).path not in {'/api/v1/integrations/whatsapp/webhook','/webhooks/twilio/whatsapp'}:
        issues.append('INVALID_INCOMING_WEBHOOK_URL')
    if delivery.support_whatsapp_enabled:
        if not public_https(callback,'/api/v1/support/whatsapp/status'):
            issues.append('INVALID_SUPPORT_STATUS_URL')
        elif urlsplit(callback).netloc!=urlsplit(incoming).netloc:
            issues.append('SUPPORT_STATUS_HOST_DIFFERS_FROM_INCOMING_HOST')
    if settings.booking_page_url and (not public_https(settings.booking_page_url) or urlsplit(settings.booking_page_url).netloc!=urlsplit(incoming).netloc):
        issues.append('BOOKING_HOST_DIFFERS_FROM_INCOMING_HOST')
    sandbox=settings.twilio_whatsapp_sandbox_enabled
    if sandbox and (settings.twilio_whatsapp_number!='+14155238886' or settings.database_environment!='SANDBOX' or settings.provider_environment!='TEST'):
        issues.append('SANDBOX_MODE_MISMATCH')
    template=notifications.shipment_whatsapp_content_sid
    shipment_state=('DISABLED' if not notifications.shipment_whatsapp_notifications_enabled else
                    'BLOCKED_CUSTOM_TEMPLATE_NOT_SUPPORTED_BY_SANDBOX' if sandbox else
                    'BLOCKED_APPROVED_TEMPLATE_REQUIRED' if not re.fullmatch(r'HX[0-9a-fA-F]{32}',template) else
                    'CONFIGURED_REQUIRES_PROVIDER_APPROVAL_AND_CONSENT')
    return {'enabled':settings.twilio_enabled,'mode':'SANDBOX' if sandbox else 'REGISTERED_SENDER_REQUIRED',
            'local_config_valid':not issues,'issues':issues,
            'incoming_webhook':incoming if public_https(incoming) else 'INVALID',
            'support_status_base':callback if public_https(callback) else 'INVALID_OR_UNSET',
            'shipment_whatsapp':shipment_state,'messages_sent':0,
            'runtime_and_handset_delivery':'NOT_PROVEN_BY_CONFIGURATION_CHECK'}


async def check(live=False, domain='easyinvio.com'):
    try:
        from main import Settings
        from backend.support_delivery import DeliverySettings
        from backend.shipment_notifications import ShipmentNotificationSettings
        from backend.return_delivery import ReturnDeliverySettings
        settings=Settings();result=configuration_report(settings,DeliverySettings(),ShipmentNotificationSettings(),ReturnDeliverySettings())
    except ValueError:
        return {'local_config_valid':False,'code':'INVALID_LOCAL_CONFIGURATION','messages_sent':0}
    if not live or result.get('provider')=='GUPSHUP':return result
    if not re.fullmatch(r'[A-Za-z0-9.-]{1,253}',domain):raise ValueError('Expected a DNS domain name')
    async with httpx.AsyncClient(trust_env=False,timeout=20,follow_redirects=False) as http:
        try:
            response=await http.get('https://api.twilio.com/2010-04-01/Accounts/'+settings.twilio_account_sid+'.json',
                auth=(settings.twilio_account_sid,settings.twilio_auth_token.get_secret_value()))
            data=response.json()
            result['twilio_account']={'http':response.status_code,'matches_configured_account':data.get('sid')==settings.twilio_account_sid,
                'status':data.get('status'),'type':data.get('type'),'error_code':data.get('code')}
        except (httpx.HTTPError,ValueError):result['twilio_account']={'code':'ACCOUNT_READ_FAILED'}
        try:
            response=await http.get('https://dns.google/resolve',params={'name':'_twilio.'+domain,'type':'TXT'})
            data=response.json()
            result['domain_verification']={'domain':domain,'twilio_txt_published':any('twilio-domain-verification=' in r.get('data','') for r in data.get('Answer',[])),
                'twilio_console_verification':'CHECK_SEPARATELY_NOT_PROVEN_BY_DNS'}
        except (httpx.HTTPError,ValueError):result['domain_verification']={'code':'DNS_READ_FAILED'}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--domain',default='easyinvio.com')
    args=parser.parse_args();result=asyncio.run(check(args.live,args.domain));print(json.dumps(result,indent=2))
    raise SystemExit(0 if result.get('local_config_valid') else 2)
