"""Offline mobile portal controls; all HTTP and authentication are synthetic."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def run():
    with sync_playwright() as driver:
        browser=driver.chromium.launch(channel=os.getenv('BROWSER_CHANNEL') or None)
        context=browser.new_context(viewport={'width':390,'height':844})
        network=[];errors=[]
        def route_handler(route):
            path=urlsplit(route.request.url).path
            network.append((route.request.method,path))
            if path in {'/workspace','/login'}:return route.fulfill(content_type='text/html',body=(ROOT/'index.html').read_text(encoding='utf-8'))
            if path=='/api/v1/config':return route.fulfill(json={'mode':'configured'})
            if path.startswith('/api/'):return route.fulfill(status=401,json={})
            asset=ROOT/path.lstrip('/')
            if asset.parent==ROOT and asset.is_file() and asset.suffix in {'.js','.css','.svg'}:return route.fulfill(path=str(asset))
            return route.abort()
        context.route('**/*',route_handler)
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('https://cx.test/login',wait_until='domcontentloaded',timeout=90000)
        page.wait_for_selector('#cx-policy-form',state='attached')
        page.wait_for_function('!window.easyinvioIdentityPending')
        page.evaluate('''() => {
            window.cxCalls=[];
            state.session={access_token:'synthetic-token'};
            portal.profile={tenant_id:'synthetic-tenant',workspace_role:'OWNER'};portal.session=state.session;
            identityProfile={email:'test@example.test',role:'CLIENT',full_name:'Test Owner'};
            document.body.classList.remove('auth-locked','auth-checking');document.body.classList.add('auth-ready');
            document.querySelector('#loginContainer').hidden=true;
            document.querySelectorAll('[role=tabpanel]').forEach(panel=>panel.hidden=panel.id!=='settings');
            document.querySelector('#settings').hidden=false;
            api=async(path,options)=>{
                cxCalls.push({path,body:options?.body,method:options?.method||'GET'});
                if(path==='/api/v1/settings/public-tracking')return {enabled:true};
                if(path.endsWith('/confirm'))return {confirmed:true,message:'Policy saved'};
                if(path.includes('return-policy/proposals'))return {proposal_id:'synthetic-proposal',message:'30 days; merchant pays; GBP10 cap. Confirm to apply.'};
                if(path==='/api/v1/agents/claims/intake')return {dossier_id:'synthetic-case',message:'Please attach damage photos. No payout approved.'};
                if(path==='/api/v1/agents/claims/synthetic-case')return {dossier_id:'synthetic-case',message:'Evidence retained for review.'};
                return {};
            };
        }''')
        assert page.locator('#cx-public-save').is_disabled()
        page.locator('#cx-public-load').click()
        page.wait_for_function("!document.querySelector('#cx-public-save').disabled")
        assert page.locator('#cx-public-optin').is_checked()
        page.locator('#cx-policy-form textarea').fill('Set a 30-day free return policy for UK orders, maximum GBP 10')
        page.locator('#cx-policy-form [type=submit]').click()
        page.wait_for_selector('#cx-policy-confirm',state='visible')
        assert not [call for call in page.evaluate('cxCalls') if call['path'].endswith('/confirm')]
        page.locator('#cx-policy-confirm').click()
        page.wait_for_function("document.querySelector('#cx-policy-status').textContent==='Policy saved'")
        assert page.locator('#cx-policy-confirm').is_hidden()
        page.evaluate("document.querySelector('#settings').hidden=true;document.querySelector('#manifest').hidden=false")
        page.get_by_role('button',name='Report lost or damaged parcel',exact=True).click()
        form=page.locator('#cx-claim-form')
        form.locator('[name=reference]').fill('TEST-TRACKING-123')
        form.locator('[name=description]').fill('The parcel arrived with a crushed box and broken item')
        form.locator('[name=value]').fill('25')
        form.locator('[type=submit]').click()
        page.wait_for_function("document.querySelector('#cx-claim-status').textContent.includes('attach damage photos')")
        assert form.locator('[name=reference]').is_disabled()
        form.locator('[type=submit]').click()
        page.wait_for_function("document.querySelector('#cx-claim-status').textContent.includes('retained')")
        calls=page.evaluate('cxCalls')
        assert len([call for call in calls if call['path']=='/api/v1/agents/claims/intake'])==1
        assert len([call for call in calls if call['path']=='/api/v1/agents/claims/synthetic-case'])==1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.evaluate("document.body.classList.remove('auth-ready');document.body.classList.add('auth-locked')")
        page.wait_for_function("!document.querySelector('#cx-claim-dialog').open")
        assert not errors,errors
        assert not [path for method,path in network if 'purchase' in path or 'webhooks' in path or '/rates' in path]
        browser.close()
    print('PASS: mobile policy preview/confirmation, publication choice, claim retry identity, session cleanup; no external calls.')


if __name__=='__main__':run()
