"""Explicit, repeatable CRM test fixtures. Creates no shipments, payments or messages.

Run with --run (and --allow-standard-account for a standard HubSpot account).
Requires the configured account identity, required property definitions and CRM
permissions. Never starts the worker or drains real tenant synchronization jobs.
"""
import argparse,asyncio,json
from decimal import Decimal
from uuid import NAMESPACE_URL,uuid5
import httpx
from backend.hubspot_crm import HubSpotClient,HubSpotSettings,CRMError

async def exercise(http,settings):
 client=HubSpotClient(http,settings)
 await client.verify_schema()  # No object writes until all account/schema checks pass.
 records=[]
 for index in [1,2]:
  tenant=uuid5(NAMESPACE_URL,f'easyinvio:isolated-crm-qa:v1:{settings.hubspot_expected_portal_id}:{index}')
  name=f'[EASYINVIO TEST] CRM integration fixture {index}'
  email=f'easyinvio-crm-qa-{tenant.hex[:16]}@example.com'
  company=await client.onboard(tenant,name,email,'',contact_name=f'EasyInvio Test {index}')
  await client.milestone(tenant,company,name,3,Decimal('12.34'),'GBP',wallet_balance=Decimal('50.00'),shipment_count=2)
  again=await client.onboard(tenant,name,email,'',contact_name=f'EasyInvio Test {index}')
  if company!=again:raise CRMError('qa_duplicate_company',retryable=False)
  records.append({'company_id':company,'contact_id':client.contact_ids[str(tenant)],'repeated_upsert_same_company':True})
 return {'status':'PASS','portal_id':str(settings.hubspot_expected_portal_id),'fixtures':records,'synthetic_metrics':True,'real_shipments':0,'payments':0,'emails_sent_by_test':0}

async def run(args):
 settings=HubSpotSettings()
 if not args.run:return {'status':'NOT_RUN','instruction':'Use --run for the two explicitly labelled CRM fixtures. Read-only readiness: python -m backend.check_hubspot.'}
 if settings.hubspot_upsell_enabled:return {'status':'BLOCKED','code':'disable_upsells_for_isolated_test'}
 if settings.hubspot_environment=='PRODUCTION' and not args.allow_standard_account:
  return {'status':'BLOCKED','code':'explicit_standard_account_test_flag_required'}
 try:
  async with httpx.AsyncClient(trust_env=False) as http:return await exercise(http,settings)
 except CRMError as error:return {'status':'BLOCKED','code':error.code,'reason':'Readiness or CRM operation failed; no automatic worker activation. If object creation had started, rerunning reuses deterministic fixture identities.'}

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true');parser.add_argument('--allow-standard-account',action='store_true')
 result=asyncio.run(run(parser.parse_args()));print(json.dumps(result,indent=2));raise SystemExit(0 if result['status'] in {'PASS','NOT_RUN'} else 2)
