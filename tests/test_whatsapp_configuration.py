import json,unittest
from types import SimpleNamespace
from backend.check_whatsapp import configuration_report

class WhatsAppConfigurationTests(unittest.TestCase):
 def setup_values(self):
  return (SimpleNamespace(twilio_webhook_url='https://uat.example.com/api/v1/integrations/whatsapp/webhook',booking_page_url='https://uat.example.com/',twilio_whatsapp_sandbox_enabled=True,twilio_whatsapp_number='+14155238886',database_environment='SANDBOX',provider_environment='TEST',twilio_enabled=True,twilio_auth_token='do-not-print-this'),
   SimpleNamespace(support_whatsapp_status_url='https://uat.example.com/api/v1/support/whatsapp/status',support_whatsapp_enabled=True),
   SimpleNamespace(shipment_whatsapp_content_sid='',shipment_whatsapp_notifications_enabled=True))
 def test_sandbox_interactive_readiness_does_not_claim_template_or_delivery_readiness(self):
  result=configuration_report(*self.setup_values())
  self.assertTrue(result['local_config_valid']);self.assertEqual(result['messages_sent'],0)
  self.assertEqual(result['shipment_whatsapp'],'BLOCKED_CUSTOM_TEMPLATE_NOT_SUPPORTED_BY_SANDBOX')
  self.assertNotIn('do-not-print-this',json.dumps(result))
 def test_stale_tunnel_callback_and_mixed_booking_host_are_detected(self):
  s,d,n=self.setup_values();d.support_whatsapp_status_url='https://old.ngrok-free.dev/api/v1/support/whatsapp/status';s.booking_page_url='https://old.example.com/'
  result=configuration_report(s,d,n)
  self.assertFalse(result['local_config_valid']);self.assertIn('SUPPORT_STATUS_HOST_DIFFERS_FROM_INCOMING_HOST',result['issues']);self.assertIn('BOOKING_HOST_DIFFERS_FROM_INCOMING_HOST',result['issues'])
 def test_credentials_in_webhook_url_are_not_printed(self):
  s,d,n=self.setup_values();s.twilio_webhook_url='https://user:private-password@uat.example.com/api/v1/integrations/whatsapp/webhook'
  result=configuration_report(s,d,n);self.assertFalse(result['local_config_valid']);self.assertEqual(result['incoming_webhook'],'INVALID');self.assertNotIn('private-password',json.dumps(result))
 def test_registered_sender_still_requires_an_approved_template(self):
  s,d,n=self.setup_values();s.twilio_whatsapp_sandbox_enabled=False
  self.assertEqual(configuration_report(s,d,n)['shipment_whatsapp'],'BLOCKED_APPROVED_TEMPLATE_REQUIRED')
  n.shipment_whatsapp_content_sid='HX'+'a'*32
  self.assertEqual(configuration_report(s,d,n)['shipment_whatsapp'],'CONFIGURED_REQUIRES_PROVIDER_APPROVAL_AND_CONSENT')
