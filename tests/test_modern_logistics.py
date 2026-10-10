import unittest
from decimal import Decimal
from types import SimpleNamespace
from backend.advanced_logistics import preview_rates, generate_commercial_invoice
from backend.automation_freight_engine import Cargo, calculate_cargo_charge
from backend.ai_engine import InvoiceLine
from pydantic import ValidationError
from main import RatingRequest
from tests.test_logistics import payload

class ModernLogisticsTests(unittest.TestCase):
 def test_letter_boundary(self):
  self.assertEqual(calculate_cargo_charge(Cargo(cargo_type='LETTER',actual_weight_kg='0.499'))['billable_weight_kg'],'0.499')
  with self.assertRaises(ValidationError):Cargo(cargo_type='LETTER',actual_weight_kg='0.500')
 def test_sample_freight_matches_configured_floor(self):
  body=payload();body.update(cargo_type='PALLET',stackable=False,dimensions=[{'length_cm':'120','width_cm':'80','height_cm':'100'}],weights_kg=['100.000'])
  settings=SimpleNamespace(freight_kg_per_m3=Decimal('333'),freight_kg_per_loading_metre=Decimal('2000'),freight_deck_width_m=Decimal('2.4'))
  result=preview_rates(RatingRequest.model_validate(body),settings)
  self.assertEqual(Decimal(result['weight']['billable_weight_kg']),Decimal('800'))
  self.assertTrue(result['simulated']);self.assertEqual(result['rates'][0]['provider'],'REGIONAL')
 def test_heavy_freight_invoice_weight_is_accepted(self):
  line=InvoiceLine(shipment_id='00000000-0000-4000-8000-000000001043',currency='GBP',billed_weight_kg='1750.000',base_cost='100.00',fuel_surcharge='12.00',remote_area_fee='0.00')
  self.assertEqual(line.billed_weight_kg,Decimal('1750'))
