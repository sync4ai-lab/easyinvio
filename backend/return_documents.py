"""Optional carrier drop-off documents; never a second label purchase."""
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit, urljoin
from uuid import UUID

import jwt
from fastapi import HTTPException

from backend.carrier_consolidation import carrier_identity


async def request_easypost_qr(pool, adapter, account, rate, snapshot, label):
    """USPS Label Broker forms require an enabled USPS Returns account.

    EasyPost documents this forms POST after the successful buy. The committed
    submission marker prevents a timed-out optional request from being repeated.
    GET shipment retrieval can subsequently recover the appended form.
    """
    if label.get('return_dropoff_qr_code_url') or carrier_identity(rate.carrier_code) != 'USPS':
        return label
    from backend.automation_three_partners import identifier, secure_link
    try:
        async with pool.acquire() as connection:
            permitted = await connection.fetchval('''UPDATE public.shipments SET logistics_metadata=
                logistics_metadata||jsonb_build_object('return_qr_request_state','SUBMITTED')
                WHERE tenant_id=$1 AND carrier_account_id=$2
                AND pricing_snapshot->'selected_rate'->>'offer_id'=$3
                AND NOT (logistics_metadata ? 'return_qr_request_state') RETURNING true''',
                account.tenant_id, account.id, str(rate.offer_id))
        if not permitted:
            return label
        data = await adapter.request('POST', '/shipments/'+identifier(label['upstream_id'])+'/forms',
            {'form':{'type':'label_qr_code'}})
        # The forms endpoint returns the updated shipment, not a new shipment.
        if data.get('id') != label['upstream_id'] or data.get('mode') != ('test' if adapter.environment=='TEST' else 'production'):
            raise ValueError('QR shipment identity mismatch')
        qr = next((form.get('form_url') for form in data.get('forms', []) if form.get('form_type')=='label_qr_code'), None)
        if qr:
            from backend.automation_three_partners import carrier_qr_fields
            label = dict(label, **carrier_qr_fields(qr))
    except Exception:
        logging.getLogger(__name__).warning('Optional return QR unavailable; confirmed label retained')
    return label


def public_return_links(settings, context, result):
    """A share link grants only one QR document, never workspace access."""
    if not result.get('paperless_available'):
        return result
    result = dict(result, qr_requires_workspace_login=True)
    key = getattr(settings, 'quote_link_secret', None)
    key = key.get_secret_value() if key else ''
    base = getattr(settings, 'booking_page_url', '') or getattr(settings, 'auth_recovery_redirect_url', '')
    parsed = urlsplit(base)
    if (len(key) < 32 or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme != 'https' and not (parsed.scheme=='http' and parsed.hostname in {'localhost','127.0.0.1'}))):
        return result
    now = datetime.now(timezone.utc)
    token = jwt.encode({'iss':'easyinvio-returns','aud':'return-dropoff-document',
        't':str(context.tenant_id),'s':str(result['shipment_id']),
        'iat':int(now.timestamp()),'exp':int((now+timedelta(hours=24)).timestamp())}, key, algorithm='HS256')
    result.update(return_dropoff_qr_code_url=urljoin(base,'/api/v1/shipping/return-dropoff')+'?'+urlencode({'token':token}),
        qr_requires_workspace_login=False, qr_link_expires_at=(now+timedelta(hours=24)).isoformat())
    return result


def verify_dropoff_token(settings, token):
    key = getattr(settings,'quote_link_secret',None)
    key = key.get_secret_value() if key else ''
    if len(key) < 32 or len(token) > 2000:
        raise HTTPException(401, 'Invalid or expired return document link')
    try:
        claims = jwt.decode(token,key,algorithms=['HS256'],issuer='easyinvio-returns',audience='return-dropoff-document',
            options={'require':['iss','aud','t','s','iat','exp']})
        if claims['exp']-claims['iat']>86400:
            raise ValueError('Invalid lifetime')
        return UUID(claims['t']), UUID(claims['s'])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(401, 'Invalid or expired return document link') from None


async def recover_easypost_qr(connection, lifecycle, context, shipment, metadata):
    """Read an appended form after an interrupted request; never repeat POST."""
    label = metadata.get('automation_label') or {}
    if metadata.get('return_qr_request_state')!='SUBMITTED' or label.get('return_dropoff_qr_code_url'):
        return label
    try:
        from backend.automation_three_partners import EasyPostAdapter, create_adapter, verify_quote_connection
        from backend.dispatch_workspace import decoded
        from main import ClientRate
        rate = ClientRate.model_validate(decoded(shipment['pricing_snapshot'])['selected_rate'])
        accounts = await lifecycle.automation.repository.accounts(context,historical_account_id=shipment['carrier_account_id'])
        account = next(item for item in accounts if item.id==rate.account_id)
        if account.base_url != EasyPostAdapter.endpoint:
            return label
        verify_quote_connection(account,rate)
        adapter = create_adapter(lifecycle.client,account,environment=lifecycle.automation.settings.provider_environment)
        recovered = await adapter.retrieve_label(label['upstream_id'],rate.model_dump(mode='json')|{'is_return':True})
        qr = recovered.get('return_dropoff_qr_code_url')
        if qr:
            await connection.execute('''UPDATE public.shipments SET logistics_metadata=
                jsonb_set(logistics_metadata,'{automation_label,return_dropoff_qr_code_url}',to_jsonb($3::text))
                ||jsonb_build_object('return_dropoff_qr_code_url',$3::text,'return_qr_request_state','READY')
                WHERE tenant_id=$1 AND id=$2''',context.tenant_id,shipment['id'],qr)
            return label|{'return_dropoff_qr_code_url':qr}
    except Exception:
        logging.getLogger(__name__).warning('Optional return QR recovery deferred; no mutation retried')
    return label
