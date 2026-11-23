"""Mobile browser lifecycle checks against the standalone dummy lab only."""
import os
import tempfile
from pathlib import Path
from io import BytesIO
from PIL import Image
from playwright.sync_api import sync_playwright


def run() -> None:
    base=os.getenv('PROVIDER_LAB_TEST_URL','http://127.0.0.1:8010')
    with sync_playwright() as driver:
        browser=driver.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge'))
        page=browser.new_page(viewport={'width':390,'height':844},bypass_csp=True)
        errors=[];external=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:external.append(request.url) if not request.url.startswith(base) else None)
        page.goto(base)
        page.wait_for_function("document.querySelector('#balance').textContent.includes('Merchant') || document.querySelector('#balance').textContent.includes('merchant-a')")
        assert 'SIMULATED' in page.locator('.banner').inner_text()
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        page.get_by_role('button',name='Get simulated rates').click()
        page.locator('[data-book]').first.wait_for()
        page.locator('#insured').check();page.locator('#terms').check()
        page.locator('[data-book]').first.click()
        page.wait_for_function("document.querySelector('#shipments').textContent.includes('BOOKED')")
        page.locator('[data-manifest="EVRI"]').click()
        page.wait_for_function("document.querySelector('#shipments').textContent.includes('MANIFESTED')")
        page.locator('[data-scan="IN_TRANSIT"]').first.click()
        page.wait_for_function("document.querySelector('#shipments').textContent.includes('IN_TRANSIT')")
        page.locator('[data-scan="DELIVERED"]').first.click()
        page.wait_for_function("document.querySelector('#shipments').textContent.includes('DELIVERED')")
        page.locator('[data-action="return"]').first.click()
        page.wait_for_function("document.querySelector('#result').textContent.includes('qr_url')")
        page.get_by_role('button',name='Create demo claim').click()
        page.locator('[data-photo]').first.wait_for()
        data=BytesIO();Image.new('RGB',(5,5),(30,50,70)).save(data,format='PNG')
        page.locator('[data-photo]').first.set_input_files({'name':'fictional-damage.png','mimeType':'image/png','buffer':data.getvalue()})
        page.wait_for_function("document.querySelector('#claims').textContent.includes('READY_FOR_REVIEW')")
        page.locator('[data-submit]').first.click()
        page.locator('[data-event="APPROVED"]').first.wait_for()
        page.locator('[data-event="APPROVED"]').first.click()
        page.locator('[data-event="PAID"]').first.wait_for()
        page.locator('[data-event="PAID"]').first.click()
        page.wait_for_function("document.querySelector('#claims').textContent.includes('PAID')")
        page.wait_for_function("document.querySelector('#balance').textContent.includes('120.60')")
        page.locator('#workspace').select_option('merchant-b')
        page.wait_for_function("document.querySelector('#balance').textContent.includes('merchant-b')")
        assert page.locator('#documents button').count()==0
        assert page.locator('#claims .item').count()==0
        page.locator('#scenario').select_option('TIMEOUT_AFTER_ACCEPTANCE')
        page.get_by_role('button',name='Get simulated rates').click()
        page.locator('[data-book]').first.wait_for()
        page.locator('[data-book]').first.click()
        page.locator('#reconcile').wait_for(state='visible')
        page.locator('#reconcile').click()
        page.wait_for_function("document.querySelector('#result').textContent.includes('reconciled')")
        assert page.locator('#shipments .item').count()==1
        page.locator('#chattext').fill('Hello');page.get_by_role('button',name='Send to simulator').click()
        page.wait_for_function("document.querySelector('#chatlog').textContent.includes('Welcome')")
        page.screenshot(path=os.getenv('PROVIDER_LAB_SCREENSHOT',str(Path(tempfile.gettempdir())/'easyinvio-provider-lab-mobile.png')),full_page=True)
        assert not errors,errors
        assert not external,external
        browser.close()
    print('PASS: mobile quote, insured booking, manifest, scans, return QR, photo claim, approval/receipt, workspace isolation, uncertain-booking reconciliation and chat; no external requests.')


if __name__=='__main__':run()
