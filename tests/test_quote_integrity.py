import unittest
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
from decimal import Decimal
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from io import BytesIO
from fastapi import HTTPException
from pypdf import PdfReader
import main
import httpx
from backend.customer_checkout import CheckoutPrepare,build_router
from backend.automation_freight_engine import PurchaseRejected
from backend.carrier_consolidation import summarize_history
from backend.booking_receipt import receipt_pdf
class IntegrityTests(unittest.IsolatedAsyncioTestCase):
 def goods(self):return {'description':'Electric steam iron','quantity':1,'unit_value':'25.00','unit_weight_kg':'1.000','origin_country':'GB'}
 def quote(self):
  a={'name':'Synthetic','line1':'1 Test Road','city':'London','postal_code':'SW1A 1AA','country_code':'GB'}
  return main.RatingRequest(origin=a,destination={**a,'country_code':'US'},weights_kg=['2'],dimensions=[{'length_cm':'20','width_cm':'20','height_cm':'20'}],goods_currency='USD',shipment_items=[self.goods()])
 async def test_goods_changes_cannot_reach_booking_process(self):
  quote=self.quote();service=SimpleNamespace(automation=SimpleNamespace(process=AsyncMock()));req=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(partner_lifecycle=service)))
  endpoint=next(r.endpoint for r in build_router(lambda:None).routes if r.path.endswith('/prepare'))
  for field,value in [('quantity',2),('unit_value','1.00'),('unit_weight_kg','0.001'),('origin_country','US')]:
   changed={**self.goods(),field:value,'hs_code':'851640'}
   body=CheckoutPrepare(offer_id=uuid4(),customs={'items':[changed],'signer':'Synthetic signer','reviewed':True,'currency':'USD','category':'SALE'})
   with patch('backend.customer_checkout.offer_context',AsyncMock(return_value=({},quote,None,SimpleNamespace(execution_details={}), 'EINVIO-00000001',True))):
    with self.assertRaises(HTTPException) as exc:await endpoint(body,req,SimpleNamespace(tenant_id=uuid4()))
    self.assertEqual(exc.exception.status_code,409)
  service.automation.process.assert_not_awaited()
 async def test_freight_failure_is_capability_not_carrier_rejection(self):
  service=main.RatingService(None,None,SimpleNamespace(max_parallel_provider_requests=3))
  for endpoint in ['https://api.easypost.com/v2','https://api.goshippo.com','https://panel.sendcloud.sc/api/v3']:
   strategy=SimpleNamespace(account=SimpleNamespace(id=uuid4(),provider='REGIONAL',base_url=endpoint),rates=AsyncMock())
   rates,issue=await service.run_provider(strategy,self.quote().model_copy(update={'cargo_type':'PALLET'}),10)
   self.assertEqual(issue.code,'FREIGHT_ADAPTER_CONTRACT_NOT_CONFIGURED');self.assertFalse(rates);strategy.rates.assert_not_awaited()
 async def test_authentication_error_not_disguised_as_empty_rates(self):
  service=main.RatingService(None,None,SimpleNamespace(max_parallel_provider_requests=3));strategy=SimpleNamespace(account=SimpleNamespace(id=uuid4(),provider='REGIONAL',base_url='https://api.goshippo.com'),rates=AsyncMock(side_effect=PurchaseRejected('ShippoAdapter:HTTP_403')))
  _,issue=await service.run_provider(strategy,self.quote(),10);self.assertEqual(issue.code,'UPSTREAM_AUTHENTICATION_REJECTED')
 async def test_letter_verification_error_is_actionable(self):
  account=SimpleNamespace(provider='EASYPOST',base_url='https://api.easypost.com/v2',api_key='synthetic',timeout_seconds=10,upstream_account_id=None)
  async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(422,json={'error':{'code':'ADDRESS.VERIFY.FAILURE','message':'private address details'}}))) as client:
   with self.assertRaises(main.ProviderFailure) as exc:await main.EasyPostStrategy(client,account).rates(self.quote().model_copy(update={'cargo_type':'LETTER','weights_kg':[Decimal('.1')],'dimensions':[]}))
   self.assertEqual(exc.exception.code,'LETTER_ADDRESS_VERIFICATION_REQUIRED')
 async def test_dispatcher_cannot_download_financial_receipt(self):
  endpoint=next(r.endpoint for r in build_router(lambda:None).routes if r.path.endswith('/receipt.pdf'))
  with self.assertRaises(HTTPException) as exc:await endpoint(uuid4(),None,SimpleNamespace(role='DISPATCHER'))
  self.assertEqual(exc.exception.status_code,403)
 def test_net_goods_weight_cannot_exceed_package(self):
  q=self.quote().model_dump(mode='json');q['shipment_items'][0]['quantity']=3
  with self.assertRaises(ValueError):main.RatingRequest.model_validate(q)
 def test_booking_time_not_used_as_transit_start(self):
  now=datetime.now(timezone.utc);r=summarize_history([{'carrier_code':'DHL','status':'DELIVERED','booked_at':now-timedelta(days=10),'dispatched_at':None,'delivered_at':now,'delivery_days':'2'}])['DHL']
  self.assertIsNone(r['avg_transit_days']);self.assertIsNone(r['on_time_rate'])
 def test_receipt_has_consistent_reference_without_customs(self):
  row={'customer_reference':'EINVIO-00000001','company_name':'Synthetic Company','currency':'GBP','final_client_price':Decimal('62.70'),'tax_amount':Decimal(0),'tracking_number':'SYNTHETIC','booked_at':datetime.now(timezone.utc),'origin_country':'GB','destination_country':'GB','billing_plan':'PREPAID_WALLET','is_sandbox':True}
  pdf=receipt_pdf(row);text=''.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
  self.assertIn(row['customer_reference'],text);self.assertIn('GBP 62.70',text);self.assertIn('SANDBOX',text)
if __name__=='__main__':unittest.main()
