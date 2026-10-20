"""Signed endpoint contracts using controlled carrier replies, not paid messages."""
import unittest
from decimal import Decimal
from types import SimpleNamespace
from xml.etree import ElementTree

import main
from backend.whatsapp_bot import WEBHOOK_PATH, format_quotes, initialize_whatsapp, xml_message
from test_sandbox_hooks import WhatsAppTests


class ConversationalWebhookTests(WhatsAppTests):
    def setUp(self):
        super().setUp()
        self.settings.twilio_webhook_url = "https://sandbox.example.com" + WEBHOOK_PATH
        self.settings.whatsapp_brand_name = "EasyInvio.com"

    def post(self, fields, *, signature=None):
        from urllib.parse import urlencode
        from starlette.datastructures import FormData
        pairs = list(fields.items()) if isinstance(fields, dict) else fields
        signature = signature or main.app.state.twilio_validator.compute_signature(
            self.settings.twilio_webhook_url, FormData(pairs))
        response = self.client.post(WEBHOOK_PATH, content=urlencode(pairs),
            headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": signature})
        return self.complete_response(response, dict(pairs))

    def test_signed_query_exact_decimal_pricing_and_duplicate_receipt(self):
        response = self.post(self.fields(Body="Quote 4.5kg from GB to US route TEST"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers['content-type'].startswith('application/xml'))
        text = ElementTree.fromstring(response.text).find('Message').text
        self.assertIn('23.45 GBP', text)
        self.assertIn('4.5kg', text)
        self.assertIn('GB \u2192 US', text)
        self.assertIn('wallet balance is too low', text)
        self.assertIn('https://sandbox.example.com/book?', text)
        self.assertEqual(self.post(self.fields(Body="Quote 4.5kg from GB to US route TEST")).text, response.text)
        self.assertEqual(len(self.observed), 1)
        self.assertEqual(self.observed[0][0].tenant_id, self.tenant)

    def test_funded_and_postpaid_accounts_do_not_get_zero_wallet_warning(self):
        self.connection.state['wallet']['balance'] = Decimal('100')
        self.assertNotIn('wallet balance is too low', self.post(self.fields()).text)
        self.connection.state['tenant']['billing_plan'] = 'POSTPAID_30_DAY'
        self.connection.state['wallet']['balance'] = Decimal('0')
        self.assertNotIn('wallet balance is too low', self.post(self.fields(MessageSid='SM'+'c'*32)).text)

    def test_reserved_credit_cannot_be_promised_for_booking(self):
        self.connection.state['wallet'].update(balance=Decimal('100'), reserved_balance=Decimal('90'))
        self.assertIn('wallet balance is too low', self.post(self.fields()).text)

    def test_unconfigured_booking_page_has_no_placeholder_link(self):
        self.settings.booking_page_url = ''
        response = self.post(self.fields())
        self.assertEqual(response.status_code, 200)
        self.assertIn('Book option N', response.text)
        self.assertNotIn('_Book:_ https', response.text)

    def test_wrong_canonical_url_and_disabled_integration(self):
        self.settings.twilio_webhook_url = 'https://sandbox.example.com/other'
        self.assertEqual(self.post(self.fields()).status_code, 400)
        self.settings.twilio_enabled = False
        self.assertEqual(self.post(self.fields()).status_code, 503)


class FormatterTests(unittest.TestCase):
    def test_long_replies_are_split_without_breaking_booking_links(self):
        link = 'https://example.com/?quote=' + 'a'*700
        root = ElementTree.fromstring(xml_message('\n'.join([link]*3)))
        messages = [message.text for message in root.findall('Message')]
        self.assertTrue(all(len(message) < 1600 for message in messages))
        self.assertEqual('\n'.join(messages), '\n'.join([link]*3))

    def test_xml_escaping_three_offers_decimal_format(self):
        rate = SimpleNamespace(carrier_code='DHL & UPS', service_code='<Express>',
                               currency='GBP', client_price_ex_tax=Decimal('46.00'))
        xml = format_quotes('EasyInvio.com', Decimal('4.5'), 'GB', 'US',
            [(rate, 'https://example.com/?a=1&b=2')]*4, sandbox=False, partial=True, wallet_blocked=False)
        text = ElementTree.fromstring(xml).find('Message').text
        self.assertEqual(text.count('Price:'), 3)
        self.assertIn('DHL & UPS <Express>', text)
        self.assertIn('£46.00 GBP', text)
        self.assertIn('Some providers', text)

    def test_unconfigured_initialization_warns_without_secret(self):
        from pydantic import SecretStr
        config=SimpleNamespace(twilio_account_sid='',twilio_auth_token=SecretStr(''),twilio_whatsapp_number='')
        with self.assertLogs('easyinvio.whatsapp',level='WARNING') as captured:
            self.assertFalse(initialize_whatsapp(config))
        self.assertIn('environment configuration keys are unmapped',captured.output[0])


if __name__ == '__main__':
    unittest.main()
