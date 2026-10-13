import unittest,json
from decimal import Decimal
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from uuid import uuid4
from contextlib import asynccontextmanager
from main import ClientRate
from backend.carrier_consolidation import consolidate_rates,summarize_history,public_payload,route_history

class ConsolidationTests(unittest.TestCase):
 def rate(self,base,price,provider='EASYPOST',service='ExpressWorldwide',currency='GBP',carrier='DHL'):
  return ClientRate(provider=provider,account_id=uuid4(),upstream_shipment_id='private',upstream_rate_id=str(uuid4()),carrier_code=carrier,service_code=service,currency=currency,client_price_ex_tax=price,delivery_days=2,fee_breakdown={'wholesale_total':base,'platform_markup':str(Decimal(price)-Decimal(base))})
 def test_largest_profit_not_cheapest_wholesale_wins(self):
  low=self.rate('10.00','12.00');high=self.rate('15.00','20.00','REGIONAL','DHL Express Worldwide')
  result=consolidate_rates([low,high]);self.assertEqual(result,[high]);self.assertEqual(result[0].provider,'REGIONAL')
 def test_currency_distinct_services_and_stable_ties(self):
  a=self.rate('10','12');b=self.rate('11','13');other=self.rate('10','12',service='Economy');usd=self.rate('10','12',currency='USD')
  result=consolidate_rates([b,usd,other,a]);self.assertEqual(len(result),3);self.assertIn(a,result);self.assertNotIn(b,result)
 def test_private_snapshots_unchanged_public_references_removed(self):
  rate=self.rate('10','12');raw=rate.model_dump(mode='json');public=public_payload({'rates':[raw],'issues':[{'provider':'EASYPOST','code':'SENDCLOUD_UNAVAILABLE'}]})
  self.assertEqual(public_payload({'order_reference':'SHIPPO-123'})['order_reference'],'SHIPPO-123')
  self.assertEqual(raw['provider'],'EASYPOST');self.assertNotIn('EASYPOST',json.dumps(public));self.assertNotIn('SENDCLOUD',json.dumps(public));self.assertNotIn('account_id',public['rates'][0]);self.assertIn('offer_id',public['rates'][0])
  hidden=public_payload({'rates':[raw]},False);self.assertEqual(hidden['rates'][0]['fee_breakdown'],{'source':'financial_role_required'})
 def test_history_precision_risk_and_missing_promises(self):
  start=datetime(2026,10,5,tzinfo=timezone.utc)
  rows=[{'carrier_code':'DHL','status':'DELIVERED','booked_at':start,'dispatched_at':start,'delivered_at':start+timedelta(days=1,hours=12),'delivery_days':'2'},
        {'carrier_code':'DHL','status':'DELIVERED','booked_at':start,'dispatched_at':start,'delivered_at':start+timedelta(days=3),'delivery_days':None}]
  data=summarize_history(rows)['DHL'];self.assertEqual(data['on_time_rate'],Decimal('100.0'));self.assertEqual(data['avg_transit_days'],Decimal('2.3'));self.assertEqual(data['on_time_samples'],1)
  for _ in range(3):rows.append({'carrier_code':'DHL','status':'EXCEPTION','booked_at':start,'dispatched_at':None,'delivered_at':None,'delivery_days':None})
  self.assertEqual(summarize_history(rows)['DHL']['route_risk_level'],'HIGH_DELAY_ALERT')
 def test_unknown_delivery_dates_never_generate_percentages(self):
  data=summarize_history([{'carrier_code':'UPS','status':'BOOKED','booked_at':None,'dispatched_at':None,'delivered_at':None,'delivery_days':'2'}])['UPS']
  self.assertIsNone(data['on_time_rate']);self.assertIsNone(data['avg_transit_days'])

class HistoryScopeTests(unittest.IsolatedAsyncioTestCase):
 async def test_query_is_tenant_bound_and_excludes_fixtures(self):
  tenant=uuid4();calls=[]
  class Connection:
   async def fetch(self,sql,*args):calls.append((sql,args));return []
  class Pool:
   @asynccontextmanager
   async def acquire(self):yield Connection()
  self.assertEqual(await route_history(Pool(),tenant,'US'),{})
  self.assertEqual(calls[0][1],(tenant,'US',None));self.assertIn('tenant_id=$1',calls[0][0]);self.assertIn('fixture_batch',calls[0][0]);self.assertIn("'90 days'",calls[0][0])
if __name__=='__main__':unittest.main()

class PublicQuoteTransportTests(unittest.TestCase):
 def test_customer_projection_retains_internal_rate_for_booking(self):
  from fastapi.testclient import TestClient
  import main
  rate=ClientRate(provider='EASYPOST',account_id=uuid4(),upstream_shipment_id='shp_private',upstream_rate_id='rate_private',carrier_code='DHL',service_code='Express',currency='GBP',client_price_ex_tax='24',delivery_days=2,fee_breakdown={'wholesale_total':'20','platform_markup':'4'})
  now=datetime.now(timezone.utc)
  quote=main.RatingResponse(request_id=uuid4(),currency='GBP',quoted_at=now,expires_at=now+timedelta(minutes=5),partial=False,rates=[rate],issues=[])
  async def rated(*args):return quote
  main.app.state.local_preview=False;main.app.state.rating=SimpleNamespace(quote=rated)
  context=main.TenantContext(uuid4(),uuid4(),'ACCOUNTANT','fixture')
  main.app.dependency_overrides[main.authenticate]=lambda:context
  try:
   from tests.test_logistics import payload
   response=TestClient(main.app).post('/v1/rates',json=payload())
   self.assertEqual(response.status_code,200,response.text)
   public=response.json()['rates'][0]
   self.assertNotIn('provider',public);self.assertNotIn('account_id',public);self.assertNotIn('upstream_rate_id',public)
   self.assertEqual(public['offer_id'],str(rate.offer_id));self.assertEqual(rate.upstream_rate_id,'rate_private');self.assertEqual(rate.provider,'EASYPOST')
  finally:main.app.dependency_overrides.clear()
