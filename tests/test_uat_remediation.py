import unittest
from uuid import uuid4
from pydantic import ValidationError
from backend.admin_portal import MarginCreate
from backend.ai_engine import predict_hs_code,analyze_tracking_history

class RemediationTests(unittest.TestCase):
 def test_extreme_markup_requires_review(self):
  with self.assertRaises(ValidationError):MarginCreate(tenant_id=uuid4(),markup_type='PERCENTAGE',markup_value='500')
  self.assertEqual(str(MarginCreate(tenant_id=uuid4(),markup_type='PERCENTAGE',markup_value='499').markup_value),'499')
 def test_supported_description_synonyms_and_safe_abstention(self):
  self.assertEqual(predict_hs_code('leather footwear for jogging')['hs_code'],'640399')
  self.assertEqual(predict_hs_code('knitted cotton garment')['hs_code'],'610910')
  self.assertIsNone(predict_hs_code('qzxv zzz qqq')['hs_code'])
 def test_active_exception_risk_without_invented_delay(self):
  result=analyze_tracking_history('GB','US',[{'provider':'EASYPOST','active_exception':True}])
  carrier=next(p for p in result['providers'] if p['provider']=='EASYPOST')
  self.assertEqual(carrier['risk'],'high');self.assertIsNone(carrier['mean_delay_days'])
  cleared=analyze_tracking_history('GB','US',[{'provider':'EASYPOST','active_exception':False}])
  self.assertEqual(cleared['providers'][0]['risk'],'unknown')
