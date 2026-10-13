"""Fresh-admin replacement of sealed, tenant-bound credentials; never unlock."""
import json
import time
from uuid import UUID

import asyncpg
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, SecretStr
from backend.admin_portal import InputModel, authenticate_platform_owner, database_error


class CredentialReplacement(InputModel):
    request_id: UUID
    new_api_key: SecretStr
    reason: str = Field(min_length=10, max_length=500)


def require_recent_admin_auth(request):
    claims = getattr(request.state, 'platform_auth_claims', {})
    now = time.time()
    methods = claims.get('amr') or []
    if not any(isinstance(method, dict) and method.get('method') in {'password', 'totp', 'otp', 'webauthn'}
               and type(method.get('timestamp')) in {int, float} and 0 <= now - method['timestamp'] <= 300
               for method in methods):
        raise HTTPException(403, 'Sign in again as a platform administrator within five minutes before replacing credentials. Refreshing a token does not count as reauthentication.')


router = APIRouter(prefix='/api/v1/admin/carriers', tags=['Credential protection'])


@router.post('/{account_id}/replace-credentials', status_code=201)
async def replace_credentials(account_id: UUID, body: CredentialReplacement, request: Request,
                              owner=Depends(authenticate_platform_owner)):
    require_recent_admin_auth(request)
    secret = body.new_api_key.get_secret_value().strip()
    if not secret or len(secret)>4096 or body.request_id == account_id:
        raise HTTPException(422, 'A new connection ID and nonempty API credential are required')
    from backend.admin_management import audit, validate_endpoint
    settings = request.app.state.settings
    try:
        async with request.app.state.finance.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('platform-carriers',0))")
                original = await connection.fetchrow('SELECT * FROM public.carrier_accounts WHERE id=$1 FOR UPDATE', account_id)
                if not original:
                    raise HTTPException(404, 'Connection not found')
                if original['platform_connection_id'] is not None:
                    raise HTTPException(403, 'Shared connection credentials must be managed in the platform catalog')
                validate_endpoint(original['aggregator'], original['api_base_url'], settings)
                if await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.carrier_accounts WHERE id=$1)', body.request_id):
                    raise HTTPException(409, 'Replacement ID already exists. Review the saved replacement; no second rotation was performed.')
                if not settings.credential_keys:
                    raise HTTPException(503, 'Configure server credential encryption keys first')
                key_id = sorted(settings.credential_keys)[0]
                envelope = json.dumps({'tenant_id': str(original['tenant_id']), 'account_id': str(body.request_id), 'api_key': secret}).encode()
                ciphertext = Fernet(settings.credential_keys[key_id].get_secret_value().encode()).encrypt(envelope)
                await connection.execute('''INSERT INTO public.carrier_accounts
                    (id,tenant_id,account_name,aggregator,regional_provider_code,api_base_url,environment,
                     upstream_account_id,credentials_ciphertext,credential_key_id,credential_version,
                     priority,timeout_seconds,is_active,credential_write_locked,credentials_rotated_at,last_security_audit_at)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,false,true,now(),now())''', body.request_id,
                    original['tenant_id'], original['account_name'][:60]+' (replacement '+str(body.request_id)[:8]+')', original['aggregator'], original['regional_provider_code'],
                    original['api_base_url'], original['environment'], original['upstream_account_id'], ciphertext, key_id,
                    original['credential_version'] + 1, original['priority'], original['timeout_seconds'])
                await connection.execute('UPDATE public.carrier_accounts SET is_active=false,last_security_audit_at=now() WHERE id=$1', account_id)
                await audit(connection, owner, original['tenant_id'], 'CREATE_CARRIER', body.request_id,
                            {'replaces_account_id': str(account_id), 'reason': body.reason, 'is_active': False})
                await audit(connection, owner, original['tenant_id'], 'RETIRE_CARRIER', account_id,
                            {'replacement_account_id': str(body.request_id), 'reason': body.reason})
        return {'id': str(body.request_id), 'replaces_account_id': str(account_id), 'credential_write_locked': True,
                'is_active': False, 'notice': 'Credentials sealed in a new connection. Verify and activate the replacement before requesting fresh quotes. Historical shipments retain the original account.'}
    except asyncpg.PostgresError as error:
        raise database_error(error) from None
