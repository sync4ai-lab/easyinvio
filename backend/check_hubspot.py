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
            'upsell_enabled':settings.hubspot_upsell_enabled,'uat_allowlisted_workspaces':len(settings.hubspot_uat_tenant_ids),'writes':0}
    if not result['token_present'] or not result['expected_account_configured']:
        return {**result,'code':'set_token_and_expected_account_locally'}
    checks=[]
    async with httpx.AsyncClient(trust_env=False) as http:
        client=HubSpotClient(http,settings)
        try:
            details=await client.request('GET','/account-info/v3/details')
        except CRMError as exc:
            return {**result,'code':exc.code,'checks':[{'check':'account','code':exc.code}]}
        result['account_type']=details.get('accountType')
        result['account_matches_expected']=str(details.get('portalId'))==str(settings.hubspot_expected_portal_id)
        if not result['account_matches_expected']:
            return {**result,'code':'hubspot_account_mismatch','checks':[{'check':'account','code':'hubspot_account_mismatch'}]}
        # Metadata reads are safe after identity match, even when the configured
        # environment is wrong. Do not hide permission errors behind that mismatch.
        try:await client.verify_account()
        except CRMError as exc:checks.append({'check':'environment','code':exc.code})
        checks_to_run=[('companies','/crm/v3/objects/companies?limit=1&properties=name'),
            ('contacts','/crm/v3/objects/contacts?limit=1&properties=email')]
        if settings.hubspot_upsell_enabled:checks_to_run.append(('deal_pipeline','/crm/v3/pipelines/deals/'+settings.hubspot_upsell_pipeline_id))
        for name,path in checks_to_run:
            try:await client.request('GET',path);checks.append({'check':name,'code':'ok'})
            except CRMError as exc:checks.append({'check':name,'code':exc.code})
        # Stop repeated schema requests if the underlying object read is forbidden.
        if not any(item['code']=='hubspot_http_403' for item in checks):
            try:await client.verify_schema();checks.append({'check':'required_properties','code':'ok'})
            except CRMError as exc:checks.append({'check':'required_properties','code':exc.code})
        else:checks.append({'check':'required_properties','code':'grant_object_and_schema_read_permissions'})
    failures=[item for item in checks if item['code']!='ok']
    return {**result,'ready':not failures,'code':failures[0]['code'] if failures else 'account_schema_and_read_access_verified',
        'checks':checks,'required_scopes':['crm.objects.companies.read','crm.objects.companies.write',
            'crm.objects.contacts.read','crm.objects.contacts.write','crm.schemas.companies.read','crm.schemas.contacts.read'],
        'setup_scope':'crm.schemas.companies.write is needed only to create the required custom properties',
        'write_scopes':'Read-only checks cannot prove write access. Confirm write scopes before the isolated live test.'}



if __name__=='__main__':
    result=asyncio.run(check())
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['ready'] else 2)
