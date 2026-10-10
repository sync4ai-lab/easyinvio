"""Read-only deployment preflight. Never enables a worker or creates records.

Run from the project root: python -m backend.check_hubspot
Secrets are read through settings and never included in the output.
"""
import asyncio
import json
from backend.hubspot_crm import HubSpotSettings,HubSpotClient,CRMError
import httpx
from pydantic import ValidationError


async def check():
    try:settings=HubSpotSettings()
    except ValidationError:
        return {'ready':False,'code':'invalid_local_hubspot_configuration','writes':0}
    result={'ready':False,'enabled':settings.hubspot_enabled,'environment':settings.hubspot_environment,
            'token_present':bool(settings.hubspot_access_token),'expected_account_configured':bool(settings.hubspot_expected_portal_id),
            'upsell_enabled':settings.hubspot_upsell_enabled,'writes':0}
    if not result['token_present'] or not result['expected_account_configured']:
        return {**result,'code':'set_token_and_expected_account_locally'}
    try:
        async with httpx.AsyncClient(trust_env=False) as http:
            client=HubSpotClient(http,settings)
            await client.verify_schema()
            # Read scope checks: return no record identities, names or emails.
            await client.request('GET','/crm/v3/objects/companies?limit=1&properties=name')
            await client.request('GET','/crm/v3/objects/contacts?limit=1&properties=email')
    except CRMError as exc:
        return {**result,'code':exc.code,'retryable':exc.retryable}
    return {**result,'ready':True,'code':'account_schema_and_read_access_verified',
            'write_scopes':'Confirm company/contact write scopes in private-app configuration; this probe performs no writes'}


if __name__=='__main__':
    result=asyncio.run(check())
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['ready'] else 2)
