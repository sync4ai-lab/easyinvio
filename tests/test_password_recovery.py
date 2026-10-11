import unittest,json
from contextlib import asynccontextmanager
import main
from unittest.mock import patch
import httpx
from tests.test_identity import IdentityTests

class RecoveryTests(IdentityTests):
    def setUp(self):
        super().setUp()
        self.settings.auth_recovery_redirect_url='http://127.0.0.1:8000/'
        self.calls=[];self.verify_status=200;self.recover_status=200;self.database_calls=[]
        original_acquire=main.app.state.finance.pool.acquire
        @asynccontextmanager
        async def acquire():
            async with original_acquire() as connection:
                original_execute=connection.execute
                async def execute(sql,*args):
                    self.database_calls.append((sql,args))
                    return await original_execute(sql,*args)
                connection.execute=execute
                yield connection
        main.app.state.finance.pool.acquire=acquire
        test=self
        def provider(req):
            test.calls.append((req.method,req.url.path,json.loads(req.content or b'{}')))
            if req.url.path.endswith('/recover'):return httpx.Response(test.recover_status,json={})
            if req.url.path.endswith('/verify'):return httpx.Response(test.verify_status,json={'access_token':'recovery-provider-session','user':{'id':str(test.user)}})
            if req.url.path.endswith('/logout'):return httpx.Response(204)
            return httpx.Response(200,json={'id':str(test.user)})
        self.transport=httpx.MockTransport(provider)
    def request(self,path,data):
        with patch('backend.identity.httpx.AsyncClient',side_effect=lambda **kw:self.real_async(transport=self.transport,**kw)):
            return self.client.post('/api/v1/auth/'+path,json=data)
    def test_recovery_generic(self):
        good=self.request('forgot-password',{'email':'registered@example.com'})
        self.recover_status=400
        unknown=self.request('forgot-password',{'email':'unknown@example.com'})
        self.assertEqual(good.status_code,200);self.assertEqual(good.json(),unknown.json())
    def test_verified_reset_updates_only_after_recovery(self):
        r=self.request('reset-password',{'token_hash':'x'*40,'password':'A long unique passphrase 29'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.calls[0][2]['type'],'recovery')
        self.assertTrue(any('DELETE FROM public.app_auth_sessions WHERE auth_user_id=$1' in sql and args==(self.user,) for sql,args in self.database_calls))
        self.assertEqual([method for method,path,data in self.calls],['POST','PUT','POST'])
    def test_expired_link_cannot_update(self):
        self.verify_status=403
        r=self.request('reset-password',{'token_hash':'x'*40,'password':'A long unique passphrase 29'})
        self.assertEqual(r.status_code,400);self.assertEqual(len(self.calls),1)
    def test_short_password_and_injected_role_are_rejected(self):
        secret='sensitive'
        r=self.request('reset-password',{'token_hash':'x'*40,'password':secret,'role':'SUPER_ADMIN'})
        self.assertEqual(r.status_code,422);self.assertNotIn(secret,r.text);self.assertFalse(self.calls)
    def test_provider_outage_and_throttling(self):
        self.recover_status=500
        self.assertEqual(self.request('forgot-password',{'email':'a@example.com'}).status_code,503)
        self.recover_status=429
        self.assertEqual(self.request('forgot-password',{'email':'a@example.com'}).status_code,429)
    def test_untrusted_redirect_rejected(self):
        self.settings.auth_recovery_redirect_url='http://attacker.example/'
        self.assertEqual(self.request('forgot-password',{'email':'a@example.com'}).status_code,503)

# Inherited login tests use their original provider fixture, so only collect new recovery cases.
for name in list(vars(IdentityTests)):
    if name.startswith('test_'):setattr(RecoveryTests,name,None)
if __name__=='__main__':unittest.main()
