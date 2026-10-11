"""Opt-in real database/read-only webhook check. No messages, labels or DB writes."""
import os
from urllib.parse import urlencode

os.environ['TWILIO_WEBHOOK_URL'] = 'https://local-verification.example/api/v1/integrations/whatsapp/webhook'
# This probe is independent of financial/CRM workers and their migrations.
os.environ['STRIPE_ENABLED'] = 'false'
os.environ['HUBSPOT_ENABLED'] = 'false'
os.environ['SUPPORT_WHATSAPP_ENABLED'] = 'false'

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator
import main


def run():
    settings = main.Settings()
    fields = {'AccountSid': settings.twilio_account_sid, 'From': 'whatsapp:+447700900999',
              'To': 'whatsapp:' + settings.twilio_whatsapp_number, 'MessageSid': 'SM' + 'f'*32,
              'Body': 'Quote 4.5kg from GB to US', 'NumMedia': '0'}
    signature = RequestValidator(settings.twilio_auth_token.get_secret_value()).compute_signature(
        settings.twilio_webhook_url, fields)
    with TestClient(main.app) as client:
        assert client.get('/health').json()['mode'] == 'configured'
        response = client.post('/api/v1/integrations/whatsapp/webhook', content=urlencode(fields),
            headers={'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': signature})
        assert response.status_code == 200, response.status_code
        assert 'not registered to an active workspace' in response.text
        forged = client.post('/api/v1/integrations/whatsapp/webhook', content=urlencode(fields),
            headers={'Content-Type': 'application/x-www-form-urlencoded', 'X-Twilio-Signature': 'invalid'})
        assert forged.status_code == 403, forged.status_code
    print('PASS: configured backend startup, signed sender lookup in Supabase, unknown sender TwiML, forged signature rejection. No database writes or messages.')


if __name__ == '__main__':
    run()
