"""Plan or create only EasyInvio's required CRM property definitions."""
import argparse,asyncio,json
from pathlib import Path
import httpx
from backend.hubspot_crm import HubSpotClient,HubSpotSettings,CRMError
async def setup(http,settings,apply=False):
 client=HubSpotClient(http,settings);await client.verify_account()
 definitions=json.loads((Path(__file__).resolve().parents[1]/'config/hubspot_properties.json').read_text(encoding='utf-8'))
 objects=[('companies',p) for p in definitions['companies']]
 if settings.hubspot_upsell_enabled:objects.extend(('deals',p) for p in definitions['optional_upsell_deals'])
 missing=[]
 for kind,definition in objects:
  try:existing=await client.request('GET','/crm/v3/properties/'+kind+'/'+definition['name'])
  except CRMError as error:
   if error.code!='hubspot_http_404':raise
   missing.append((kind,definition));continue
  if any(existing.get(key)!=definition[key] for key in ['type','fieldType']) or (definition.get('hasUniqueValue') and not existing.get('hasUniqueValue')) or existing.get('archived') or (existing.get('modificationMetadata') or {}).get('readOnlyValue'):
   raise CRMError('hubspot_existing_property_requires_review',retryable=False)
 if apply:
  for kind,definition in missing:await client.request('POST','/crm/v3/properties/'+kind,definition)
  await client.verify_schema()
 return {'status':'READY' if apply else 'PLAN','missing_properties':[{'object':kind,'name':definition['name']} for kind,definition in missing],
  'created_properties':len(missing) if apply else 0,'company_or_contact_records_created':0}
async def run(apply):
 try:
  async with httpx.AsyncClient(trust_env=False) as http:return await setup(http,HubSpotSettings(),apply)
 except CRMError as error:return {'status':'BLOCKED','code':error.code,'instruction':'Correct account/scopes/property definitions, then rerun. Existing matching properties are reused; mismatched properties are never overwritten.'}
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');result=asyncio.run(run(parser.parse_args().apply));print(json.dumps(result,indent=2));raise SystemExit(2 if result['status']=='BLOCKED' else 0)
