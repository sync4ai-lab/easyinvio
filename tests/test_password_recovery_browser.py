"""Controlled recovery browser test; no real email, password or recovery API call."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright,expect
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
async def run():
 async with async_playwright() as pw:
  browser=await pw.chromium.launch();page=await browser.new_page(viewport={'width':375,'height':850});calls=[]
  async def mock(route):
   calls.append(route.request.url)
   await route.fulfill(status=200,content_type='application/json',body=json.dumps({'message':'Password updated. Sign in with your new password.' if 'reset-password' in route.request.url else 'If this email is registered, a reset link will arrive shortly.'}))
  await page.route('**/api/v1/auth/**',mock)
  await page.goto('http://127.0.0.1:8000',wait_until='domcontentloaded')
  await page.locator('#identity-forgot').click();await expect(page.locator('#identity-recovery-form')).to_be_visible()
  await page.locator('#identity-recovery-email').fill('fixture@example.com');await page.locator('#identity-recovery-form [type=submit]').click()
  await expect(page.locator('#identity-recovery-form [role=status]')).to_contain_text('If this email')
  await page.goto('http://127.0.0.1:8000/#token_hash='+'x'*40+'&type=recovery',wait_until='domcontentloaded')
  await expect(page.locator('#identity-reset-form')).to_be_visible()
  assert await page.evaluate('location.hash === "" && localStorage.getItem("easyinvio.session")===null')
  assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
  await page.locator('#identity-new-password').fill('A long unique passphrase 29');await page.locator('#identity-confirm-password').fill('A different passphrase 30')
  await page.locator('#identity-reset-form [type=submit]').click();await expect(page.locator('#identity-reset-form [role=status]')).to_contain_text('must match')
  assert len(calls)==1
  await page.locator('#identity-confirm-password').fill('A long unique passphrase 29');await page.locator('#identity-reset-form [type=submit]').click()
  await expect(page.locator('#identity-login-form')).to_be_visible();await expect(page.locator('#identity-login-status')).to_contain_text('Password updated')
  assert await page.evaluate('identityRecoveryHash===null && state.session===null')
  await browser.close()
 print('PASS: email request, recovery form, URL clearing, mobile layout, password confirmation, return to login. Controlled API responses only.')
if __name__=='__main__':asyncio.run(run())
