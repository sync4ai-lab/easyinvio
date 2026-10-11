import unittest
from types import SimpleNamespace
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
from backend.whatsapp_ingress import app


class IngressTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        async def post(url, **kwargs):
            self.calls.append((url, kwargs))
            return httpx.Response(403, content=b'{"detail":"Invalid Twilio signature"}',
                                  headers={'content-type':'application/json'})
        self.client = TestClient(app)
        self.client.__enter__()
        app.state.client = SimpleNamespace(post=post)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_only_two_callbacks_are_routed(self):
        for path in ['/', '/docs', '/openapi.json', '/health', '/api/v1/admin/tenants',
                     '/api/v1/billing/create-checkout', '/webhooks/stripe',
                     '/api/v1/support/whatsapp/status/not-a-uuid']:
            response = self.client.post(path, content='x=1')
            self.assertIn(response.status_code, (404, 422))
        self.assertEqual(self.calls, [])

    def test_forwarding_preserves_raw_body_and_signature_only(self):
        path = '/api/v1/integrations/whatsapp/webhook'
        response = self.client.post(path, content='Body=Quote+4.5kg&From=whatsapp%3A%2B1',
            headers={'content-type':'application/x-www-form-urlencoded', 'X-Twilio-Signature':'signed',
                     'Authorization':'Bearer must-not-forward', 'X-Forwarded-Host':'attacker.example'})
        self.assertEqual(response.status_code, 403)
        url, options = self.calls[0]
        self.assertEqual(url, 'http://127.0.0.1:8000'+path)
        self.assertEqual(options['content'], b'Body=Quote+4.5kg&From=whatsapp%3A%2B1')
        self.assertEqual(set(options['headers']), {'Content-Type', 'X-Twilio-Signature'})

    def test_status_callback_uuid_route(self):
        path = '/api/v1/support/whatsapp/status/' + str(uuid4())
        self.assertEqual(self.client.post(path, content='MessageStatus=delivered',
            headers={'content-type':'application/x-www-form-urlencoded', 'X-Twilio-Signature':'signed'}).status_code, 403)
        self.assertEqual(self.calls[0][0], 'http://127.0.0.1:8000'+path)

    def test_unsigned_oversized_and_query_payloads_never_forward(self):
        path = '/api/v1/integrations/whatsapp/webhook'
        headers = {'content-type':'application/x-www-form-urlencoded', 'X-Twilio-Signature':'signed'}
        self.assertEqual(self.client.post(path, content='x=1', headers={'content-type':headers['content-type']}).status_code,403)
        self.assertEqual(self.client.post(path+'?target=http://other', content='x=1',headers=headers).status_code,400)
        self.assertEqual(self.client.post(path, content='x'*32769, headers=headers).status_code,413)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
