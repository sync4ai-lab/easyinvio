import unittest
import ssl

from pydantic import ValidationError

from main import Settings
from backend.database_tls import database_tls_context


class OptionalIntegrationTests(unittest.TestCase):
    def values(self):
        return {"supabase_url": "https://example.supabase.co", "supabase_publishable_key": "fixture-public",
                "supabase_service_role_key": "fixture-server", "database_url": "postgresql://fixture:fixture@localhost/postgres",
                "credential_keys": {}, "regional_allowed_origins": ["https://regional.example.com"],
                "stripe_enabled": False, "twilio_enabled": False,
                "stripe_secret_key": "", "stripe_webhook_secret": "", "twilio_account_sid": "",
                "twilio_auth_token": "", "twilio_whatsapp_number": "", "twilio_webhook_url": "",
                "checkout_success_url": "", "checkout_cancel_url": "", "booking_page_url": "", "quote_link_secret": ""}

    def test_database_only_configuration(self):
        settings = Settings(_env_file=None, **self.values())
        self.assertFalse(settings.stripe_enabled)
        self.assertFalse(settings.twilio_enabled)
        self.assertEqual(settings.credential_keys, {})

    def test_enabled_provider_requires_valid_credentials(self):
        for field in ["stripe_enabled", "twilio_enabled"]:
            values = self.values()
            values[field] = True
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, **values)

    def test_legacy_ca_mode_keeps_verified_tls(self):
        context = database_tls_context(strict=False)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertFalse(context.verify_flags & ssl.VERIFY_X509_STRICT)
        strict_context = database_tls_context(strict=True)
        self.assertTrue(strict_context.verify_flags & ssl.VERIFY_X509_STRICT)


if __name__ == "__main__":
    unittest.main()
