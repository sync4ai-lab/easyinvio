"""Offline browser regression for required fields and delayed address lookups."""
import asyncio
import json
from uuid import uuid4
from urllib.parse import urlsplit

from playwright.async_api import async_playwright, expect
from tests import vercel_hosting_browser as hosting


async def check(origin):
    import os
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(hosting.ROOT / '.playwright')
    tenant = str(uuid4())
    errors, writes = [], []
    gate = asyncio.Event()
    delayed = False
    sender = {'name': 'Sender fixture', 'line1': '1 Warehouse Road', 'city': 'Leeds',
              'postal_code': 'LS1 1AA', 'country_code': 'GB', 'company': 'Sender Company',
              'line2': 'Unit 1', 'state': None, 'phone': '+447700900123', 'email': 'sender@example.invalid'}
    recipient = {**sender, 'name': 'Recipient fixture', 'line1': '20 Delivery Street',
                 'city': 'Manchester', 'postal_code': 'M1 1AA', 'company': 'Recipient Company',
                 'line2': 'Unit 2', 'email': 'recipient@example.invalid'}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 1366, 'height': 950})
        page.on('pageerror', lambda error: errors.append(str(error)))

        async def handler(route):
            path = urlsplit(route.request.url).path
            method = route.request.method
            if method != 'GET': writes.append((path, route.request.post_data_json))
            if path.startswith('/api/v1/catalog/'):
                if delayed:
                    await asyncio.wait_for(gate.wait(), 15)
                contacts = '/contacts' in path
                row = {'id': str(uuid4()), 'label': 'Saved recipient' if contacts else 'Saved sender',
                       'address': recipient if contacts else sender, 'version': 1}
                if not contacts: row.update(address_role='SENDER', is_default=True)
                await route.fulfill(json={'items': [row], 'has_more': False})
            elif path.endswith('/package-check'):
                await route.fulfill(json={'blocking': False, 'messages': []})
            elif path == '/v1/rates':
                await route.fulfill(json={'rates': [], 'issues': [], 'partial': False, 'currency': 'GBP',
                    'quoted_at': '2026-10-23T12:00:00Z', 'expires_at': '2026-10-23T12:05:00Z'})
            elif path == '/api/v1/config':
                await route.fulfill(json={'mode': 'local-preview', 'supabase_url': None,
                                         'publishable_key': None, 'dispatch_updates_mode': 'POLLING'})
            else:
                await route.fulfill(json={'items': [], 'shipments': [], 'orders': [], 'members': [], 'invitations': []})

        await page.route('**/api/v1/**', handler)
        await page.route('**/v1/rates', handler)
        await page.goto(origin, wait_until='domcontentloaded')
        await page.wait_for_function("state.mode === 'local-preview' && window.easyinvioFormFeedback")
        await page.evaluate("""tenant => {
          document.body.classList.remove('auth-locked');
          document.querySelector('#loginContainer').hidden = true;
          portal.role = 'CLIENT';
          portal.profile = {tenant_id:tenant, workspace_role:'OWNER', portal_role:'CLIENT'};
          state.session = {access_token:'synthetic', expires_at:Math.floor(Date.now()/1000)+3600};
          state.mode = 'configured';
          refreshEnterpriseNavigation(); setView('dispatch');
        }""", tenant)
        await page.locator('#quote-btn').click()
        await expect(page.locator('#quote-form .form-validation-summary')).to_contain_text('Pickup name')
        await expect(page.locator('#quote-form .form-validation-summary')).to_contain_text('Delivery street')
        await expect(page.locator('#origin-name')).to_have_attribute('aria-invalid', 'true')
        await expect(page.locator('#toast')).to_be_visible()
        assert not writes, writes

        await page.locator('[data-catalog-directory=origin]').click()
        await page.locator('#catalog-directory-list button', has_text='Saved sender').click()
        await expect(page.locator('#origin-name')).to_have_value(sender['name'])
        original = await page.evaluate("Object.fromEntries(['name','company','line1','line2','city','state','postal_code','country_code','phone','email'].map(f=>[f,document.getElementById('origin-'+f).value]))")
        await page.locator('[data-catalog-directory=origin]').click()
        old = await page.locator('#catalog-directory-list button', has_text='Saved sender').element_handle()
        await page.locator('#catalog-directory-dialog [data-catalog-close]').click()
        delayed = True
        await page.locator('[data-catalog-directory=destination]').click()
        await expect(page.locator('#catalog-directory-list button')).to_have_count(0)
        # Even a retained stale DOM handle must not write to the pickup side.
        await old.evaluate('(button)=>button.click()')
        assert original == await page.evaluate("Object.fromEntries(Object.keys("+json.dumps(original)+").map(f=>[f,document.getElementById('origin-'+f).value]))")
        gate.set()
        await page.locator('#catalog-directory-list button', has_text='Saved recipient').click()
        await expect(page.locator('#destination-name')).to_have_value(recipient['name'])
        await expect(page.locator('#destination-line1')).to_have_value(recipient['line1'])
        await expect(page.locator('#destination-email')).to_have_value(recipient['email'])
        assert original == await page.evaluate("Object.fromEntries(Object.keys("+json.dumps(original)+").map(f=>[f,document.getElementById('origin-'+f).value]))")
        await expect(page.locator('#destination-name')).not_to_have_attribute('aria-invalid', 'true')

        for key, value in {'length_cm': '20', 'width_cm': '15', 'height_cm': '10', 'weight_kg': '1'}.items():
            await page.locator('#'+key).fill(value)
        await page.locator('#destination-line1').fill('   ')
        await page.locator('#quote-btn').click()
        await expect(page.locator('#quote-form .form-validation-summary')).to_contain_text('spaces alone')
        assert not any(path == '/v1/rates' for path, _ in writes)
        await page.locator('#destination-line1').fill(recipient['line1'])
        await page.locator('#quote-btn').click()
        await page.wait_for_function("document.querySelector('#rates-badge').textContent !== 'COMPARING RATES'")
        requests = [body for path, body in writes if path == '/v1/rates']
        assert len(requests) == 1, writes
        assert requests[0]['origin']['name'] == sender['name']
        assert requests[0]['destination']['name'] == recipient['name']

        # Every existing form with required controls must reject programmatic
        # submit events too, including hidden modals and dynamic admin forms.
        before = len(writes)
        coverage = await page.evaluate("""() => {
          const tested=[];
          for(const form of document.forms){
            const field=[...form.elements].find(n=>n.willValidate && n.required && !['hidden','submit'].includes(n.type));
            if(!field || form.noValidate)continue;
            if(['checkbox','radio'].includes(field.type))field.checked=false;else field.value='';
            const submitted=form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
            if(submitted || !form.querySelector('.form-validation-summary'))throw Error('Missing validation: '+form.id);
            tested.push(form.id);
          }
          return tested;
        }""")
        assert len(coverage) >= 15, coverage
        assert len(writes) == before
        formatted = await page.evaluate("easyinvioFormFeedback.formatErrors([{loc:['body','destination','line1'],type:'missing',msg:'Field required'}])")
        assert formatted == 'Enter Delivery street.'
        await page.evaluate("""() => {
          const dialog=document.createElement('dialog');dialog.id='dynamic-validation-test';
          dialog.innerHTML='<form id="dynamic-validation-form"><label>Return reason<input name="reason" required></label><details><summary>Contact</summary><label>Customer email<input name="email" type="email" required></label></details><label>Evidence file<input name="evidence" type="file" required></label><button type="submit">Continue</button></form>';
          document.body.append(dialog);dialog.showModal();window.dynamicSubmits=0;
          dialog.querySelector('form').addEventListener('submit',event=>{event.preventDefault();dynamicSubmits++;});
        }""")
        await page.locator('#dynamic-validation-test button[type=submit]').click()
        await expect(page.locator('#dynamic-validation-test details')).to_have_attribute('open', '')
        await expect(page.locator('#dynamic-validation-form .form-validation-summary')).to_contain_text('Evidence file')
        assert await page.evaluate('dynamicSubmits') == 0
        await page.locator('#dynamic-validation-form [name=reason]').fill('Damaged parcel')
        await page.locator('#dynamic-validation-form [name=email]').fill('invalid-email')
        await page.locator('#dynamic-validation-test button[type=submit]').click()
        await expect(page.locator('#dynamic-validation-form .form-validation-summary')).to_contain_text('valid email')
        await page.locator('#dynamic-validation-form [name=email]').fill('customer@example.invalid')
        await page.locator('#dynamic-validation-form [name=evidence]').set_input_files({'name':'synthetic.txt','mimeType':'text/plain','buffer':b'Synthetic validation fixture only'})
        await page.locator('#dynamic-validation-test button[type=submit]').click()
        assert await page.evaluate('dynamicSubmits') == 1
        await page.evaluate("document.getElementById('dynamic-validation-test').close();document.getElementById('dynamic-validation-test').remove();")
        personas = [('ADMIN','BUSINESS'), ('DISPATCHER','BUSINESS'), ('ACCOUNTANT','BUSINESS'), ('OWNER','INDIVIDUAL')]
        for role, workspace_type in personas:
            await page.evaluate("""([role, type])=>{
              portal.profile.workspace_role=role;portal.profile.workspace_type=type;
              setView('dispatch');
            }""", [role, workspace_type])
            await page.locator('[data-catalog-directory=origin]').click()
            try:
                await page.locator('#catalog-directory-list button', has_text='Saved sender').click(timeout=5000)
            except Exception:
                print(json.dumps({'role':role,'diagnostic':await page.evaluate("({open:document.querySelector('#catalog-directory-dialog').open,status:document.querySelector('#catalog-directory-status').textContent,session:!!state.session,role:portal.profile?.workspace_role})")}))
                raise
            await page.locator('[data-catalog-directory=destination]').click()
            await page.locator('#catalog-directory-list button', has_text='Saved recipient').click()
            await expect(page.locator('#origin-name')).to_have_value(sender['name'])
            await expect(page.locator('#destination-name')).to_have_value(recipient['name'])
        assert not errors, errors
        await browser.close()
        print(json.dumps({'status': 'PASS', 'forms_checked': coverage, 'delayed_recipient_lookup': 'PASS',
                          'pickup_preserved': True, 'invalid_submissions_sent': 0,
                          'personas': ['business owner']+[role+':'+kind for role,kind in personas],
                          'valid_quote_requests': 1, 'provider_calls': 0, 'database_calls': 0}))


if __name__ == '__main__':
    hosting.check = check
    hosting.main()
