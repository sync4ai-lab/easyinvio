import json,time,unittest
from datetime import datetime,timedelta,timezone
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch
import httpx,jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import SecretStr
import main


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.user,self.tenant=uuid4(),uuid4();self.sessions={};self.profile={'full_name':'Test User','phone_e164':None}
        self.no_membership=False;self.agent=False
        self.refresh_calls=0;self.identity_unavailable=False;self.refresh_wrong_user=False
        self.assisted=[];self.assistance_events=[]
        self.email='satyakishore.mavuri@gmail.com';self.invalid_password=False
        self.key=ec.generate_private_key(ec.SECP256R1())
        self.settings=SimpleNamespace(auth_jwt_secret=SecretStr('h'*48),credential_keys={'v1':SecretStr(Fernet.generate_key().decode())},
            supabase_url='https://identity.example',supabase_publishable_key=SecretStr('fixture'),
            platform_admin_user_ids=[],jwt_algorithm='ES256',jwt_audience='authenticated')
        test=self
        class C:
            @asynccontextmanager
            async def transaction(self):yield
            async def fetchval(self,sql,*args):
                if 'public.platform_staff' in sql:return test.agent
                return 1
            async def fetch(self,sql,*args):
                if 'UPDATE public.admin_client_assistance_sessions' in sql:
                    for row in test.assisted:
                        row.update(bearer_sha256=args[2],expires_at=min(row['created_at']+timedelta(minutes=30),args[3]))
                    return test.assisted
                return [] if test.no_membership else [{'tenant_id':test.tenant,'role':'OWNER'}]
            async def fetchrow(self,sql,*args):
                if 'app_auth_sessions' in sql:return test.sessions.get(args[0])
                return {'email':test.email,**test.profile}
            async def execute(self,sql,*args):
                if sql.startswith('INSERT INTO public.app_auth_sessions'):test.sessions[args[0]]={'id':args[0],'auth_user_id':args[1],'tenant_id':args[2],'provider_token':args[3],'key_id':args[4],'expires_at':args[5],'created_at':datetime.now(timezone.utc)}
                elif sql.startswith('UPDATE public.app_auth_sessions SET provider_token='):test.sessions[args[0]].update(provider_token=args[1],expires_at=args[2])
                elif 'DELETE FROM public.app_auth_sessions WHERE id=' in sql:test.sessions.pop(args[0],None)
                elif 'INSERT INTO public.app_user_profiles' in sql:test.profile.update(full_name=args[1],phone_e164=args[2])
                elif 'INSERT INTO public.admin_client_assistance_events' in sql:test.assistance_events.append(args)
        class Pool:
            @asynccontextmanager
            async def acquire(self):yield C()
        async def select(table,params,context,**kwargs):
            return [{'tenant_id':str(test.tenant),'auth_user_id':str(test.user),'role':'OWNER','is_active':True}] if table=='users' else [{'tenant_id':str(test.tenant),'workspace_status':'ACTIVE'}]
        main.app.state.local_preview=False;main.app.state.settings=self.settings
        main.app.state.finance=SimpleNamespace(pool=Pool())
        main.app.state.repository=SimpleNamespace(select=select)
        main.app.state.jwks=SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=test.key.public_key()))
        self.client=TestClient(main.app)
        self.real_async=httpx.AsyncClient
        def provider(req):
            if req.url.path.endswith('/token'):
                if req.url.params.get('grant_type')=='refresh_token':
                    test.refresh_calls+=1
                    assert json.loads(req.content)['refresh_token']=='synthetic-provider-refresh'
                if test.invalid_password:return httpx.Response(400,json={'error':'invalid_grant'})
                now=int(time.time());access=jwt.encode({'sub':str(test.user),'role':'authenticated','iss':'https://identity.example/auth/v1','aud':'authenticated','iat':now,'exp':now+3600},test.key,algorithm='ES256',headers={'kid':'test'})
                return httpx.Response(200,json={'access_token':access,'expires_at':now+3600,'refresh_token':'synthetic-provider-refresh','user':{'id':str(uuid4() if test.refresh_wrong_user else test.user)}})
            if test.identity_unavailable:return httpx.Response(503,json={'error':'unavailable'})
            return httpx.Response(200,json={'id':str(test.user),'email':test.email})
        self.transport=httpx.MockTransport(provider)
    def login(self):
        with patch('backend.identity.httpx.AsyncClient',side_effect=lambda **kw:self.real_async(transport=self.transport,**kw)):
            return self.client.post('/api/v1/auth/token',json={'email':self.email,'password':'fixture-password'})
    def test_email_does_not_grant_platform_admin_and_logout_revokes(self):
        response=self.login();self.assertEqual(response.status_code,200,response.text)
        token=response.json()['access_token'];claims=jwt.decode(token,'h'*48,algorithms=['HS256'],issuer='easyinvio-auth',audience='easyinvio-api')
        self.assertEqual(claims['role'],'OWNER');self.assertEqual(claims['tenant_id'],str(self.tenant))
        headers={'Authorization':'Bearer '+token}
        self.assertEqual(self.client.get('/api/v1/auth/me',headers=headers).status_code,200)
        self.assertEqual(self.client.patch('/api/v1/auth/me',headers=headers,json={'full_name':'Updated Name','phone_e164':'+447700900123'}).status_code,200)
        self.assertEqual(self.profile['full_name'],'Updated Name')
        self.assertEqual(self.client.post('/api/v1/auth/logout',headers=headers).status_code,200)
        self.assertEqual(self.client.get('/api/v1/auth/me',headers=headers).status_code,401)
    def test_allowlisted_identity_gets_admin(self):
        self.settings.platform_admin_user_ids=[self.user]
        response=self.login();self.assertEqual(response.status_code,200)
        headers={'Authorization':'Bearer '+response.json()['access_token']}
        self.assertEqual(self.client.get('/api/v1/auth/me',headers=headers).json()['role'],'SUPER_ADMIN')
    def test_invalid_password_creates_no_session(self):
        self.invalid_password=True
        self.assertEqual(self.login().status_code,401);self.assertEqual(self.sessions,{})
    def test_role_edits_and_unsigned_access_are_rejected(self):
        self.assertEqual(self.client.get('/api/v1/auth/me').status_code,401)
        token=self.login().json()['access_token'];headers={'Authorization':'Bearer '+token}
        self.assertEqual(self.client.patch('/api/v1/auth/me',headers=headers,json={'full_name':'Name','role':'SUPER_ADMIN'}).status_code,422)

    def test_admin_can_bootstrap_without_a_tenant_but_clients_cannot(self):
        self.no_membership=True
        self.assertEqual(self.login().status_code,403)
        self.settings.platform_admin_user_ids=[self.user]
        token=self.login().json()['access_token']
        response=self.client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+token})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['role'],'SUPER_ADMIN')

    def test_expired_and_wrong_signature_sessions_are_rejected(self):
        token=self.login().json()['access_token']
        claims=jwt.decode(token,'h'*48,algorithms=['HS256'],issuer='easyinvio-auth',audience='easyinvio-api')
        bad=jwt.encode(claims,'different-private-fixture-key-at-least-32',algorithm='HS256')
        self.assertEqual(self.client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+bad}).status_code,401)
        claims['exp']=int(time.time())-1
        expired=jwt.encode(claims,'h'*48,algorithm='HS256')
        self.assertEqual(self.client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+expired}).status_code,401)

    def renew(self,token):
        with patch('backend.identity.httpx.AsyncClient',side_effect=lambda **kw:self.real_async(transport=self.transport,**kw)):
            return self.client.post('/api/v1/auth/renew',headers={'Authorization':'Bearer '+token})

    def test_renewal_retains_session_and_stores_provider_secret_only_encrypted(self):
        token=self.login().json()['access_token']
        old=jwt.decode(token,'h'*48,algorithms=['HS256'],audience='easyinvio-api')
        result=self.renew(token)
        self.assertEqual(result.status_code,200,result.text)
        new=jwt.decode(result.json()['access_token'],'h'*48,algorithms=['HS256'],audience='easyinvio-api')
        self.assertEqual(new['jti'],old['jti']);self.assertEqual(new['sub'],old['sub'])
        self.assertNotIn('refresh_token',result.json())
        row=next(iter(self.sessions.values()))
        envelope=json.loads(Fernet(self.settings.credential_keys['v1'].get_secret_value().encode()).decrypt(row['provider_token']))
        self.assertEqual(envelope['refresh_token'],'synthetic-provider-refresh')
        self.assertEqual(self.refresh_calls,0)

    def test_renewal_refreshes_nearly_expired_upstream_credentials(self):
        token=self.login().json()['access_token'];row=next(iter(self.sessions.values()))
        cipher=Fernet(self.settings.credential_keys['v1'].get_secret_value().encode())
        envelope=json.loads(cipher.decrypt(row['provider_token']));envelope['provider_expires_at']=int(time.time())+60
        row['provider_token']=cipher.encrypt(json.dumps(envelope).encode())
        result=self.renew(token)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(self.refresh_calls,1)
        self.assertGreater(json.loads(cipher.decrypt(row['provider_token']))['provider_expires_at'],int(time.time())+120)

    def test_renewal_cannot_reopen_revoked_expired_or_absolute_limit_session(self):
        token=self.login().json()['access_token'];self.sessions.clear()
        self.assertEqual(self.renew(token).status_code,401)
        token=self.login().json()['access_token'];next(iter(self.sessions.values()))['created_at']=datetime.now(timezone.utc)-timedelta(hours=9)
        self.assertEqual(self.renew(token).status_code,401)
        claims=jwt.decode(token,'h'*48,algorithms=['HS256'],audience='easyinvio-api');claims['exp']=int(time.time())-1
        expired=jwt.encode(claims,'h'*48,algorithm='HS256')
        self.assertEqual(self.renew(expired).status_code,401)

    def test_renewal_rechecks_membership_and_provider_identity(self):
        token=self.login().json()['access_token'];self.no_membership=True
        self.assertEqual(self.renew(token).status_code,403)
        self.no_membership=False;self.identity_unavailable=True
        before=next(iter(self.sessions.values()))['provider_token']
        self.assertEqual(self.renew(token).status_code,503)
        self.assertEqual(next(iter(self.sessions.values()))['provider_token'],before)
        self.assertEqual(self.refresh_calls,0)

    def test_refresh_response_cannot_switch_the_authenticated_user(self):
        token=self.login().json()['access_token'];row=next(iter(self.sessions.values()))
        cipher=Fernet(self.settings.credential_keys['v1'].get_secret_value().encode())
        envelope=json.loads(cipher.decrypt(row['provider_token']));envelope['provider_expires_at']=int(time.time())+60
        row['provider_token']=cipher.encrypt(json.dumps(envelope).encode());self.refresh_wrong_user=True
        self.assertEqual(self.renew(token).status_code,401)

    def test_admin_renewal_preserves_and_audits_assistance_parent_binding(self):
        import hashlib
        self.settings.platform_admin_user_ids=[self.user]
        token=self.login().json()['access_token']
        claims=jwt.decode(token,'h'*48,algorithms=['HS256'],audience='easyinvio-api')
        self.assisted=[{'id':uuid4(),'actor_auth_user_id':self.user,'tenant_id':uuid4(),
            'created_at':datetime.now(timezone.utc)-timedelta(minutes=20),
            'expires_at':datetime.now(timezone.utc)+timedelta(minutes=1)}]
        result=self.renew(token)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.assisted[0]['bearer_sha256'],hashlib.sha256(('app-session:'+claims['jti']).encode()).hexdigest())
        self.assertLessEqual(self.assisted[0]['expires_at'],self.assisted[0]['created_at']+timedelta(minutes=30))
        self.assertEqual(result.json()['assistance_sessions'][0]['session_id'],str(self.assisted[0]['id']))
        self.assertEqual(len(self.assistance_events),2)


    def test_agent_login_has_no_customer_workspace_and_revocation_blocks_renewal(self):
        self.agent=True;self.no_membership=True
        response=self.login();self.assertEqual(response.status_code,200,response.text)
        claims=jwt.decode(response.json()['access_token'],'h'*48,algorithms=['HS256'],issuer='easyinvio-auth',audience='easyinvio-api')
        self.assertEqual(claims['role'],'AGENT');self.assertIsNone(claims['tenant_id'])
        headers={'Authorization':'Bearer '+response.json()['access_token']}
        self.assertEqual(self.client.get('/api/v1/auth/me',headers=headers).json()['role'],'AGENT')
        self.assertEqual(self.client.get('/api/v1/profile',headers=headers).json()['portal_role'],'AGENT')
        self.agent=False
        self.assertEqual(self.client.post('/api/v1/auth/renew',headers=headers).status_code,403)

if __name__=='__main__':unittest.main()
