import asyncio
import unittest
from types import SimpleNamespace
from uuid import uuid4
from fastapi import HTTPException
from fastapi.testclient import TestClient
import main
from backend.platform_carriers import PlatformConnection, save


class PlatformCarrierTests(unittest.TestCase):
    def body(self):
        return {'account_name':'EasyInvio Test','aggregator':'EASYPOST',
                'api_base_url':'https://api.easypost.com/v2','environment':'TEST',
                'api_key':'synthetic-key-no-provider-call','is_active':True}

    def test_all_platform_routes_require_authentication(self):
        main.app.state.local_preview=False
        client = TestClient(main.app)
        root='/api/v1/admin/platform-carriers'
        self.assertEqual(client.get(root).status_code,401)
        self.assertEqual(client.post(root,json=self.body()).status_code,401)
        self.assertEqual(client.put(root+'/'+str(uuid4()),json=self.body()).status_code,401)
        self.assertEqual(client.delete(root+'/'+str(uuid4())).status_code,401)

    def test_client_assignment_is_rejected_before_database_access(self):
        body=PlatformConnection(**self.body(),tenant_id=uuid4())
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace())))
        with self.assertRaises(HTTPException) as error:
            asyncio.run(save(body,request,None))
        self.assertEqual(error.exception.status_code,422)

    def test_keys_are_secret_values_and_update_can_omit_them(self):
        body=PlatformConnection(**self.body())
        self.assertNotIn('synthetic-key-no-provider-call',str(body))
        values=self.body();del values['api_key']
        self.assertIsNone(PlatformConnection(**values).api_key)

if __name__=='__main__':unittest.main()
