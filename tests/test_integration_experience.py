"""Keep published executable examples aligned with the signed-store contract."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend.custom_stores import signature
from backend.integration_help import ORDER, RATE, callback_examples, integration_explorer, request_examples


class IntegrationExperienceTests(unittest.TestCase):
    def test_python_request_examples_sign_exact_transmitted_bytes(self):
        env={'EASYINVIO_ORIGIN':'https://uat.easyinvio.com','EASYINVIO_STORE_ID':'00000000-0000-4000-8000-000000000057','EASYINVIO_KEY_ID':'fixture-key','EASYINVIO_SIGNING_SECRET':'offline-fixture-only-secret-32-bytes'}
        class Response:
            status=201
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'{}'
        for endpoint,payload in [('orders',ORDER),('checkout-rates',RATE)]:
            path='/api/v1/integration/custom-store/'+endpoint
            with tempfile.TemporaryDirectory() as directory:
                request_file=Path(directory)/'payload.json';request_file.write_text(json.dumps(payload),encoding='utf-8')
                import builtins
                real_open=builtins.open
                def open_payload(name,*args,**kwargs):return real_open(request_file if name=='payload.json' else name,*args,**kwargs)
                with patch.dict(os.environ,env),patch('builtins.open',open_payload),patch('urllib.request.urlopen',return_value=Response()) as send,patch('builtins.print'):
                    exec(compile(request_examples(path)['Python'],'published-example','exec'),{})
                request=send.call_args.args[0]
                stamp=request.get_header('X-easyinvio-timestamp')
                expected=signature(env['EASYINVIO_SIGNING_SECRET'],stamp,'POST',path,env['EASYINVIO_STORE_ID'],request.data)
                self.assertEqual(request.get_header('X-easyinvio-signature'),expected)
                self.assertEqual(json.loads(request.data),payload)

    def test_callback_example_rejects_wrong_store_stale_and_modified_body(self):
        env={'EASYINVIO_STORE_ID':'00000000-0000-4000-8000-000000000057','EASYINVIO_KEY_ID':'fixture-key','EASYINVIO_SIGNING_SECRET':'fixture-only'}
        namespace={};exec(callback_examples()['Python'],namespace)
        raw=b'{"event_id":"fixture-event"}';path='/callbacks/tracking';stamp='1800000000'
        headers={'X-EasyInvio-Store-Id':env['EASYINVIO_STORE_ID'],'X-EasyInvio-Key-Id':'fixture-key','X-EasyInvio-Timestamp':stamp,'X-EasyInvio-Signature':signature(env['EASYINVIO_SIGNING_SECRET'],stamp,'POST',path,env['EASYINVIO_STORE_ID'],raw)}
        with patch.dict(os.environ,env),patch('time.time',return_value=int(stamp)):
            self.assertEqual(namespace['verify_callback'](raw,headers,path),{'event_id':'fixture-event'})
            with self.assertRaises(ValueError):namespace['verify_callback'](raw+b' ',headers,path)
            with self.assertRaises(ValueError):namespace['verify_callback'](raw,{**headers,'X-EasyInvio-Store-Id':'different'},path)
        with patch.dict(os.environ,env),patch('time.time',return_value=int(stamp)+301):
            with self.assertRaises(ValueError):namespace['verify_callback'](raw,headers,path)

    def test_node_examples_parse_and_curl_preserves_environment_variable_names(self):
        node=Path(__file__).resolve().parents[1].parent.parent/'.venv/Lib/site-packages/playwright/driver/node.exe'
        if not node.is_file():self.skipTest('Bundled Node is unavailable')
        for path in ['/api/v1/integration/custom-store/orders','/api/v1/integration/custom-store/checkout-rates']:
            examples=request_examples(path)
            self.assertIn('EASYINVIO_API_PATH',examples['cURL'])
            with tempfile.TemporaryDirectory() as directory:
                script=Path(directory)/'example.mjs';script.write_text(examples['Node.js'],encoding='utf-8')
                result=subprocess.run([str(node),'--check',str(script)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_guide_contains_real_contract_and_explicit_bridge_limits(self):
        html=integration_explorer()
        for word in ['201 Created','200 OK','X-EasyInvio-Signature','EASYINVIO_SIGNING_SECRET','no installed one-click','durably deduplicate','401','409']:
            self.assertIn(word,html)
        self.assertNotIn('YOUR_API_KEY',html)


if __name__=='__main__':unittest.main()
