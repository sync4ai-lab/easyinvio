"""Offline mobile WhatsApp draft -> existing-account login regression.

Run from the repository: BROWSER_CHANNEL=msedge python tests/quick_quote_signin_browser.py.
Every request is intercepted; no database, provider, rate or purchase calls.
"""
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def run():
    root = Path(__file__).resolve().parents[1]
    html = (root / 'index.html').read_text(encoding='utf-8')
    facts = {'weight_kg': '2', 'dimensions_cm': ['25', '20', '15'],
             'origin_country': 'GB', 'destination_country': 'GB',
             'origin_city': 'Leeds', 'destination_city': 'Oldbury',
             'origin_postal_code': 'LS12 6EJ', 'destination_postal_code': 'B69 3EB'}
    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel=os.getenv('BROWSER_CHANNEL') or None)
        for already_signed_in in (False, True):
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            requests, errors = [], []

            def route_handler(route):
                request = route.request
                path = urlsplit(request.url).path
                requests.append((request.method, path))
                if path == '/login':
                    return route.fulfill(content_type='text/html', body=html)
                if path == '/api/v1/public/quick-quote':
                    return route.fulfill(json={'facts': facts, 'authorizes_booking': False})
                if path == '/api/v1/config':
                    return route.fulfill(json={'mode': 'configured'})
                if path.startswith('/api/'):
                    return route.fulfill(status=401, json={})
                asset = root / path.lstrip('/')
                if asset.is_file() and asset.parent == root and asset.suffix in {'.js', '.css', '.svg'}:
                    return route.fulfill(path=str(asset))
                return route.abort()

            context.route('**/*', route_handler)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto('https://quote.test/login?mode=signup&quick_quote=synthetic-token', wait_until='domcontentloaded')
            page.wait_for_function("document.querySelector('#qq-weight')?.value==='2' && !window.easyinvioIdentityPending")
            assert 'quick_quote' not in page.url
            assert page.locator('#identity-signin-top').is_visible()
            position = page.locator('#identity-signin-top').bounding_box()
            assert position and position['y'] < 110
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#qq-weight').fill('3')
            page.locator('#identity-signin-top').click()
            assert page.locator('#identity-login-form').is_visible()
            assert page.locator('#identity-signup-form').is_hidden()
            assert page.locator('#qq-weight').input_value() == '3'
            page.locator('#identity-signup-open').click()
            assert page.locator('#identity-signin-top').is_visible()
            assert page.locator('#qq-weight').input_value() == '3'
            page.locator('#identity-signin-top').click()
            # Exercise the real login flow with an entirely synthetic account bootstrap.
            # Portal dashboard data is outside this UI regression and is stubbed.
            page.evaluate('''() => {
                window.loginCalls=[];
                const session={access_token:'synthetic-token',expires_at:Math.floor(Date.now()/1000)+600};
                const identity={role:'CLIENT',email:'sender@example.test',full_name:'Test Sender',phone_e164:'+447700900123'};
                const profile={tenant_id:'synthetic-tenant',workspace_role:'OWNER',portal_role:'CLIENT'};
                api=async(path)=>{
                    loginCalls.push(path);
                    if(path==='/api/v1/auth/token')return {...session,bootstrap:{profile,identity}};
                    return {};
                };
                renderAccount=()=>{};renderPortal=()=>{};refreshPortal=async()=>{};
                window.syntheticLogin=()=>process_user_login('sender@example.test','synthetic-password');
                window.syntheticRestore=()=>{
                    state.session=session;portal.profile=profile;
                    renderIdentityProfile(identity);
                    window.dispatchEvent(new Event('easyinvio-session-ready'));
                };
            }''')
            if already_signed_in:
                page.evaluate('syntheticRestore()')
            else:
                page.evaluate('syntheticLogin()')
            page.wait_for_function("document.querySelector('#weight_kg').value==='3' && location.pathname==='/workspace'")
            assert page.locator('#quote-form').is_visible()
            assert page.locator('#origin-city').input_value() == 'Leeds'
            assert page.locator('#destination-city').input_value() == 'Oldbury'
            assert page.locator('#destination-postal_code').input_value() == 'B69 3EB'
            assert page.locator('#height_cm').input_value() == '15'
            assert page.locator('#origin-name').input_value() == 'Test Sender'
            assert page.locator('#origin-email').input_value() == 'sender@example.test'
            assert page.locator('#origin-phone').input_value() == '+447700900123'
            assert page.locator('#origin-line1').input_value() == ''
            assert page.locator('#destination-name').input_value() == ''
            # Re-applying cannot overwrite the customer's edited sender contact.
            page.locator('#origin-name').fill('Another sender')
            page.locator('#qq-apply').click()
            page.wait_for_function("document.querySelector('#qq-status').textContent.startsWith('Details copied.')")
            assert page.locator('#origin-name').input_value() == 'Another sender'
            assert all('/rates' not in path and '/purchase' not in path for _, path in requests)
            assert not errors, errors
            context.close()
        browser.close()
    print('PASS: mobile sign-in switch, draft edits retained, login/restore opens prefilled shipment, editable account contacts, no provider calls.')


if __name__ == '__main__':
    run()
