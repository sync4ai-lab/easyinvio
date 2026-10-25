"""Signed HubSpot deal events and durable, idempotent workspace provisioning.

CRM payloads identify deals only. Canonical company/contact data is fetched
using the account-scoped service key, never trusted from webhook body fields.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from uuid import uuid4

import asyncpg
from fastapi import BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.admin_portal import CompanyProfile


class DealEvent(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)
    portalId: int = Field(gt=0)
    appId: int = Field(gt=0)
    eventId: int = Field(ge=0)
    objectId: int = Field(gt=0)
    occurredAt: int = Field(gt=0)
    subscriptionType: str = Field(max_length=100)
    propertyName: str = Field(default='', max_length=100)
    propertyValue: str = Field(default='', max_length=100)


def verify_signature(secret: str, url: str, body: bytes, timestamp: str, signature: str, now_ms: int | None = None):
    if not re.fullmatch(r'\d{13}', timestamp) or abs((now_ms or int(time.time()*1000))-int(timestamp)) > 300000:
        raise HTTPException(401, 'Invalid HubSpot signature or timestamp')
    # Decode only HubSpot's documented reserved characters in the query.
    head, separator, query = url.partition('?')
    mapping = {'3A': ':', '2F': '/', '3F': '?', '40': '@', '21': '!', '24': '$',
               '27': "'", '28': '(', '29': ')', '2A': '*', '2C': ',', '3B': ';'}
    query = re.sub(r'%('+'|'.join(mapping)+r')', lambda m: mapping[m[1].upper()], query, flags=re.I)
    message = ('POST'+head+separator+query).encode()+body+timestamp.encode()
    expected = base64.b64encode(hmac.digest(secret.encode(), message, 'sha256')).decode()
    if not signature.isascii() or not hmac.compare_digest(expected, signature):
        raise HTTPException(401, 'Invalid HubSpot signature or timestamp')


async def webhook(request: Request, background_tasks: BackgroundTasks):
    service = getattr(request.app.state, 'hubspot', None)
    if service is None or not service.client.settings.hubspot_provisioning_enabled:
        raise HTTPException(503, 'HubSpot provisioning is disabled')
    settings = service.client.settings
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1048576:
            raise HTTPException(413, 'Webhook body too large')
    if request.url.query:
        raise HTTPException(400, 'Webhook query parameters are not supported')
    verify_signature(settings.hubspot_webhook_client_secret.get_secret_value(), settings.hubspot_webhook_url,
                     bytes(body), request.headers.get('x-hubspot-request-timestamp',''), request.headers.get('x-hubspot-signature-v3',''))
    try:
        data = json.loads(body)
        if not isinstance(data, list) or not 1 <= len(data) <= 100:
            raise ValueError()
        events = [DealEvent.model_validate(item) for item in data]
    except (ValueError, ValidationError, TypeError):
        raise HTTPException(422, 'Invalid HubSpot event batch') from None
    if any(e.portalId != settings.hubspot_expected_portal_id or e.appId != settings.hubspot_webhook_app_id for e in events):
        raise HTTPException(403, 'HubSpot account or app mismatch')
    selected = [e for e in events if e.subscriptionType == 'deal.propertyChange' and e.propertyName == 'dealstage'
                and e.propertyValue in settings.hubspot_closed_won_stage_ids]
    try:
        async with service.pool.acquire() as c:
            async with c.transaction():
                for e in selected:
                    await c.execute('''INSERT INTO public.hubspot_activation_jobs(portal_id,deal_id)
                        VALUES($1,$2) ON CONFLICT(portal_id,deal_id) DO NOTHING''', e.portalId, str(e.objectId))
    except asyncpg.PostgresError:
        raise HTTPException(503, 'CRM activation queue unavailable') from None
    background_tasks.add_task(safe_pending, service)
    return {'status': 'QUEUED', 'accepted_events': len(selected)}


async def safe_pending(service):
    try:
        await process_pending(service)
    except Exception:
        from backend.hubspot_crm import logger
        logger.warning('Optional CRM activation task deferred; durable job retained')


def association_id(record, kind):
    from backend.hubspot_crm import CRMError
    block = (record.get('associations') or {}).get(kind) or {}
    results = block.get('results', [])
    ids = {str(r.get('id')) for r in results if isinstance(r, dict)}
    if block.get('paging') or len(ids) != 1 or not next(iter(ids), '').isdigit():
        raise CRMError('crm_activation_requires_single_'+kind, retryable=False)
    return ids.pop()


async def provision(service, c, portal_id, deal_id):
    from backend.hubspot_crm import CRMError
    client = service.client
    await client.verify_account()
    deal = await client.request('GET', f'/crm/v3/objects/deals/{deal_id}?properties=dealstage,hs_is_closed_won&associations=companies,contacts')
    props = deal.get('properties') or {}
    if props.get('dealstage') not in client.settings.hubspot_closed_won_stage_ids or str(props.get('hs_is_closed_won')).lower() != 'true':
        raise CRMError('crm_activation_deal_not_closed_won', retryable=False)
    company_id = association_id(deal, 'companies')
    contact_id = association_id(deal, 'contacts')
    company = await client.request('GET', f'/crm/v3/objects/companies/{company_id}?properties=name,address,city,zip,country,veloce_vat_number,veloce_tenant_id&associations=contacts')
    # Require this deal contact to be associated to the company too.
    contacts = (company.get('associations') or {}).get('contacts') or {}
    if contacts.get('paging') or contact_id not in {str(r.get('id')) for r in contacts.get('results', [])}:
        raise CRMError('crm_activation_contact_company_mismatch', retryable=False)
    contact = await client.request('GET', f'/crm/v3/objects/contacts/{contact_id}?properties=email,firstname,lastname')
    p, person = company.get('properties') or {}, contact.get('properties') or {}
    try:
        profile = CompanyProfile(company_name=p.get('name'), billing_email=person.get('email'),
            contact_name=' '.join(v for v in [person.get('firstname'), person.get('lastname')] if v),
            address_line1=p.get('address'), city=p.get('city'), postal_code=p.get('zip'), country_code=p.get('country'),
            tax_id=p.get('veloce_vat_number') or None)
    except (ValueError, TypeError):
        raise CRMError('crm_activation_incomplete_company_profile', retryable=False) from None
    # Company identity, rather than deal identity, prevents multiple won deals
    # from creating duplicate workspaces. No network call inside this transaction.
    async with c.transaction():
        await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'crm-company:{portal_id}:{company_id}')
        existing = await c.fetchrow('SELECT tenant_id FROM public.hubspot_tenant_links WHERE portal_id=$1 AND company_id=$2', portal_id, company_id)
        if existing:
            tenant_id = existing['tenant_id']
            tenant = await c.fetchrow('SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1',tenant_id)
            if not tenant or bool(tenant['is_sandbox']) != (client.settings.hubspot_environment == 'SANDBOX'):
                raise CRMError('crm_activation_tenant_environment_mismatch',retryable=False)
        else:
            # Refuse to replace any Supabase-owned identity from HubSpot.
            if p.get('veloce_tenant_id'):
                raise CRMError('crm_activation_existing_identity_requires_reconciliation', retryable=False)
            tenant_id = uuid4()
            meta = profile.model_dump(mode='json')
            meta['hubspot'] = {'portal_id':str(portal_id), 'company_id':company_id, 'contact_id':contact_id}
            address = {'line1':profile.address_line1,'city':profile.city,'postal_code':profile.postal_code,'country_code':profile.country_code}
            sandbox = client.settings.hubspot_environment == 'SANDBOX'
            await c.execute('''INSERT INTO public.tenants(tenant_id,company_name,company_profile,billing_plan,default_currency,
                workspace_status,billing_status,is_sandbox,workspace_slug,workspace_name,legal_company_name,billing_email,
                billing_address,country_code,vat_registration_number)
                VALUES($1,$2,$3::jsonb,'PREPAID_WALLET','GBP','ACTIVE','ACTIVE',$4,$5,$2,$2,$6,$7::jsonb,$8,$9)''',
                tenant_id,profile.company_name,json.dumps(meta),sandbox,'tenant-'+tenant_id.hex,profile.billing_email,
                json.dumps(address),profile.country_code,profile.tax_id)
            await c.execute('''INSERT INTO public.wallets(tenant_id,currency,balance,reserved_balance)
                VALUES($1,'GBP',0,0) ON CONFLICT(tenant_id) DO NOTHING''',tenant_id)
            wallet = await c.fetchrow('SELECT currency,balance,reserved_balance FROM public.wallets WHERE tenant_id=$1 FOR UPDATE',tenant_id)
            if not wallet or wallet['currency'] != 'GBP' or wallet['balance'] != 0 or wallet['reserved_balance'] != 0:
                raise CRMError('crm_activation_invalid_opening_wallet', retryable=False)
            await c.execute('''INSERT INTO public.hubspot_tenant_links(tenant_id,company_id,contact_id,portal_id)
                VALUES($1,$2,$3,$4)''',tenant_id,company_id,contact_id,portal_id)
        await c.execute('''UPDATE public.hubspot_activation_jobs SET tenant_id=$3,completed_at=now(),last_error=NULL
            WHERE portal_id=$1 AND deal_id=$2''',portal_id,deal_id,tenant_id)


async def process_pending(service):
    from backend.hubspot_crm import CRMError, logger
    if not service.client.settings.hubspot_provisioning_enabled:
        return
    async with service.pool.acquire() as c:
        jobs = await c.fetch('''SELECT portal_id,deal_id FROM public.hubspot_activation_jobs
            WHERE portal_id=$1 AND completed_at IS NULL AND NOT blocked AND next_attempt_at<=now()
            ORDER BY next_attempt_at LIMIT 20''',service.client.settings.hubspot_expected_portal_id)
    for job in jobs:
        async with service.pool.acquire() as c:
            key = f"crm-activation:{job['portal_id']}:{job['deal_id']}"
            if not await c.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))',key):
                continue
            try:
                current = await c.fetchrow('''SELECT attempts FROM public.hubspot_activation_jobs WHERE portal_id=$1 AND deal_id=$2
                    AND completed_at IS NULL AND NOT blocked AND next_attempt_at<=now()''',job['portal_id'],job['deal_id'])
                if current is None:
                    continue
                try:
                    await provision(service,c,job['portal_id'],job['deal_id'])
                except Exception as exc:
                    code = exc.code if isinstance(exc, CRMError) else 'crm_activation_internal_failure'
                    attempts = current['attempts']+1
                    delay = max(getattr(exc,'retry_after',0),min(3600,2**min(attempts,12)))
                    await c.execute('''UPDATE public.hubspot_activation_jobs SET attempts=$3,last_error=$4,blocked=$5,
                        next_attempt_at=now()+$6*interval '1 second' WHERE portal_id=$1 AND deal_id=$2''',
                        job['portal_id'],job['deal_id'],attempts,code,not getattr(exc,'retryable',True) or attempts>=12,float(delay))
                    logger.warning('CRM activation deferred: %s',code)
            finally:
                await c.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))',key)
