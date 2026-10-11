import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from scripts import start_stripe_sandbox_listener as setup


class ListenerSetupTests(unittest.TestCase):
    def values(self):
        return {'STRIPE_SECRET_KEY':'sk_test_private_fixture','STRIPE_LIVEMODE':'false',
                'DATABASE_ENVIRONMENT':'SANDBOX','PROVIDER_ENVIRONMENT':'TEST'}

    def test_live_configuration_never_starts_listener(self):
        values = self.values()
        values['STRIPE_SECRET_KEY'] = 'sk_live_private_fixture'
        with patch.object(setup,'dotenv_values',return_value=values), patch.object(setup.subprocess,'Popen') as start:
            with self.assertRaises(SystemExit):
                setup.main()
            start.assert_not_called()

    def test_project_key_is_child_environment_only_and_secret_is_not_printed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'.env').write_text('STRIPE_WEBHOOK_SECRET=whsec_old\nOTHER_SETTING=preserved\n',encoding='utf-8')
            with patch.object(setup,'ROOT',root), patch.object(setup,'dotenv_values',return_value=self.values()), \
                 patch.object(setup.shutil,'which',return_value='stripe.cmd'), \
                 patch.object(setup.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='whsec_new',stderr='')) as check, \
                 patch.object(setup.subprocess,'Popen') as start, patch('builtins.print') as output:
                setup.main()
                self.assertEqual(start.call_args.kwargs['env']['STRIPE_API_KEY'],'sk_test_private_fixture')
                self.assertEqual(check.call_args.kwargs['env']['STRIPE_API_KEY'],'sk_test_private_fixture')
                self.assertNotIn('sk_test_private_fixture',str(start.call_args.args))
                self.assertNotIn('whsec_new',str(output.call_args_list))
                self.assertIn('charge.refunded,charge.failed',str(start.call_args.args))
                self.assertIn('OTHER_SETTING=preserved', (root/'.env').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
