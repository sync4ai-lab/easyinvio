"""Durable webhook setup. No purchases, speculative endpoints or blind POST retries."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import asyncpg
import httpx
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger('easyinvio.connector_setup')


def callback_origin(settings: Any) -> str:
    value = getattr(settings, 'tracking_webhook_base_url', '') or settings.booking_page_url
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:
        raise ValueError('Configure an explicit HTTPS tracking callback origin')
    return value.rstrip('/')


async def provision_remote(client: httpx.AsyncClient, endpoint: str, credential: str,
                           callback: str, secret: str, environment: str) -> str:
    """List before create; caller persists ambiguous outcomes for manual reconciliation."""
    if endpoint == 'https://api.easypost.com/v2':
        auth = {'auth': httpx.BasicAuth(credential, '')}
        path = endpoint + '/webhooks'
        payload = {'webhook': {'url': callback, 'webhook_secret': secret}}
        collection, identity = 'webhooks', 'id'
    elif endpoint == 'https://api.goshippo.com':
        auth = {'headers': {'Authorization': 'ShippoToken ' + credential}}
        path = endpoint + '/webhooks'
        callback += '&' + urlencode({'token': secret})
        if len(callback) >= 200:
            raise ValueError('Shippo callback exceeds its URL length limit')
        payload = {'url': callback, 'event': 'track_updated', 'is_test': environment == 'TEST'}
        collection, identity = 'results', 'object_id'
    else:
        raise ValueError('Provider requires dashboard webhook setup')
    response = await client.get(path, **auth, timeout=8, follow_redirects=False)
    if response.status_code != 200 or len(response.content) > 1_000_000:
        raise ValueError('Webhook list could not be verified')
    data = response.json()
    if not isinstance(data,dict):
        raise ValueError('Webhook catalog response is invalid')
    entries = data.get(collection, [])
    if not isinstance(entries,list) or len(entries)>1000 or data.get('next') or data.get('has_more'):
        raise ValueError('Webhook catalog needs operator reconciliation')
    if any(not isinstance(item,dict) for item in entries):
        raise ValueError('Webhook catalog entry is invalid')
    matches = [item for item in entries if item.get('url') == callback]
    if matches:
        if len(matches)!=1 or matches[0].get('disabled_at') or matches[0].get('active') is False:
            raise ValueError('Existing webhook needs review')
        return str(matches[0][identity])
    response = await client.post(path, json=payload, **auth, timeout=8, follow_redirects=False)
    if response.status_code not in {200,201} or len(response.content)>1_000_000:
        raise ValueError('Webhook creation requires reconciliation')
    created = response.json()
    if not isinstance(created,dict) or created.get('url') != callback or not isinstance(created.get(identity),str):
        raise ValueError('Webhook creation identity unconfirmed')
    return created[identity]


class ConnectorSetupWorker:
    def __init__(self, state: Any) -> None:
        self.state, self.pool = state, state.finance.pool

    async def tick(self) -> bool:
        async with self.pool.acquire() as c:
            async with c.transaction():
                await c.execute("UPDATE public.connector_tracking_setup SET state='REVIEW_REQUIRED',error_code='SETUP_INTERRUPTED' WHERE state='RUNNING' AND lease_until<now()")
                row = await c.fetchrow('''SELECT j.*,p.api_base_url,p.environment,p.is_active,p.retired_at,p.credentials_ciphertext,p.credential_key_id
                    FROM public.connector_tracking_setup j JOIN public.platform_carrier_connections p ON p.id=j.platform_connection_id
                    WHERE j.state='DUE' AND j.next_attempt_at<=now() AND p.environment=$1
                    ORDER BY j.updated_at FOR UPDATE OF j SKIP LOCKED LIMIT 1''', self.state.settings.provider_environment)
                if row is None:
                    return False
                await c.execute("UPDATE public.connector_tracking_setup SET state='RUNNING',attempts=attempts+1,lease_until=now()+interval '45 seconds',updated_at=now() WHERE platform_connection_id=$1",row['platform_connection_id'])
        identifier = row['platform_connection_id']
        status, code, remote = 'REVIEW_REQUIRED', 'SETUP_UNCONFIRMED', None
        try:
            if not row['is_active'] or row['retired_at'] is not None:
                status, code = 'DISABLED', 'CONNECTION_DISABLED'
            else:
                from backend.integration_policy import integration_enabled
                if not integration_enabled(row['api_base_url'],self.state.settings):
                    raise ValueError('Integration disabled')
                cipher = Fernet(self.state.settings.credential_keys[row['credential_key_id']].get_secret_value().encode())
                envelope = json.loads(cipher.decrypt(bytes(row['credentials_ciphertext'])))
                if envelope.get('platform_id') != str(identifier):
                    raise ValueError('Credential identity mismatch')
                credential = envelope['api_key']
                secret = secrets.token_urlsafe(32)
                if row['api_base_url']=='https://panel.sendcloud.sc/api/v3':
                    secret=json.loads(credential)['secret_key']
                callback=callback_origin(self.state.settings)+'/api/v1/tracking/webhook?'+urlencode({'source':str(identifier)})
                async with self.pool.acquire() as c:
                    async with c.transaction():
                        current = await c.fetchrow('SELECT * FROM public.partner_provider_options WHERE platform_connection_id=$1 FOR UPDATE',identifier)
                        if current and current['webhook_enabled']:
                            status,code='MANUAL_REQUIRED','EXISTING_WEBHOOK_PRESERVED'
                        else:
                            # A prior uncertain POST must retain its original secret for reconciliation.
                            if row['secret_ciphertext']:
                                saved=Fernet(self.state.settings.credential_keys[row['key_id']].get_secret_value().encode())
                                secret=saved.decrypt(bytes(row['secret_ciphertext'])).decode()
                            encrypted=cipher.encrypt(secret.encode())
                            await c.execute('''INSERT INTO public.partner_provider_options(platform_connection_id,webhook_enabled,webhook_auth,webhook_secret,credential_key_id)
                                VALUES($1,true,$2,$3,$4) ON CONFLICT(platform_connection_id) DO UPDATE SET webhook_enabled=true,
                                webhook_auth=excluded.webhook_auth,webhook_secret=excluded.webhook_secret,credential_key_id=excluded.credential_key_id''',
                                identifier,'URL_TOKEN' if 'goshippo' in row['api_base_url'] else 'HMAC',encrypted,row['credential_key_id'])
                            await c.execute('''UPDATE public.connector_tracking_setup SET callback_url=$2,secret_ciphertext=$3,key_id=$4 WHERE platform_connection_id=$1''',identifier,callback,encrypted,row['credential_key_id'])
                if code!='EXISTING_WEBHOOK_PRESERVED':
                    if row['api_base_url']=='https://panel.sendcloud.sc/api/v3':
                        status,code='MANUAL_REQUIRED','SENDCLOUD_DASHBOARD_CALLBACK_REQUIRED'
                    elif row['api_base_url'] in {'https://api.easypost.com/v2','https://api.goshippo.com'}:
                        remote=await provision_remote(self.state.rating.client,row['api_base_url'],credential,callback,secret,row['environment'])
                        status,code='READY',None
                    else:
                        status,code='MANUAL_REQUIRED','NO_VERIFIED_WEBHOOK_REGISTRATION_CONTRACT'
        except (ValueError,KeyError,TypeError,InvalidToken,UnicodeError,httpx.HTTPError):
            logger.warning('connector_tracking_setup_needs_review connection=%s',identifier)
        async with self.pool.acquire() as c:
            await c.execute('''UPDATE public.connector_tracking_setup SET state=$2,error_code=$3,provider_reference=$4,
                verified_at=CASE WHEN $2='READY' THEN now() ELSE verified_at END,lease_until=NULL,updated_at=now()
                WHERE platform_connection_id=$1 AND state='RUNNING' ''',identifier,status,code,remote)
        return True

    async def worker(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncpg.PostgresError:
                logger.warning('connector_tracking_setup_storage_unavailable')
            await asyncio.sleep(10)


def connector_checks(settings: Any, rows: list[dict[str, Any]], *, worker_running: bool) -> dict[str, Any]:
    issues: list[str] = []
    if not rows:
        issues.append('NO_ACTIVE_AGGREGATOR_CONNECTIONS')
    if not getattr(settings,'tracking_polling_enabled',False):
        issues.append('TRACKING_POLLING_DISABLED')
    if not worker_running:
        issues.append('TRACKING_WORKER_NOT_RUNNING_IN_THIS_PROCESS')
    for row in rows:
        if row['api_base_url']=='https://panel.sendcloud.sc/api/v3' and settings.provider_environment=='LIVE' and not row.get('sendcloud_integration_id'):
            issues.append('SENDCLOUD_LIVE_INTEGRATION_ID_REQUIRED')
        if row.get('setup_state')!='READY':
            issues.append('WEBHOOK_REGISTRATION_NOT_VERIFIED:'+str(row['id']))
        if not row.get('webhook_enabled') or not row.get('webhook_secret_configured'):
            issues.append('TRACKING_WEBHOOK_NOT_CONFIGURED:'+str(row['id']))
    for provider in ('royal_mail','evri'):
        if getattr(settings,'integration_'+provider+'_enabled',False):
            issues.append(provider.upper()+'_DIRECT_CONTRACT_NOT_INJECTED')
    return {'ready':not issues,'issues':issues,'connections':rows,
            'test_label_contracts':['EASYPOST','SHIPPO'],
            'sendcloud_test_label_purchase':'BLOCKED_NO_VERIFIED_NON_BILLABLE_CONTRACT',
            'worker_scope':'shared environment worker heartbeat (90-second freshness)' }
