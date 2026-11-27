"""Offline browser acceptance for tracking privacy, branding and shared logos."""
import asyncio,json,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from playwright.async_api import async_playwright,expect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.platform_registry import PLATFORMS
from backend.post_purchase import merchant_logo_response
from tracking_workspace_browser import ITEM,DETAIL,LIST,IDENT
BASE='http://127.0.0.1:8017';CAP='B'*43;ACCESS='A'*43
PUBLIC={'access':'PUBLIC','branding':{'display_name':'Fixture Merchant','logo_url':'https://shop.example.test/logo.svg','accent_hex':'#123456','support_url':'https://shop.example.test/help'},'shipments':[{'carrier':'Royal Mail','tracking_number':'PARCEL-000000','status':'DELIVERED','timeline':[{'status':'DELIVERED','occurred_at':'2026-11-27T10:00:00Z','location':'Leeds'}],'estimated_delivery_at':None,'data_state':'RECORDED'}]}
VERIFIED={**PUBLIC,'access':'VERIFIED_RECIPIENT','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(),'buyer_notification_policy':{'email':True,'whatsapp':True},'shipments':[{**PUBLIC['shipments'][0],'delivery_address':{'name':'Private Recipient','line1':'42 Private Street','postal_code':'LS12 6EJ'},'proof_of_delivery_url':'https://carrier.example.test/pod','return_url':'/returns/fixture-retailer'}]}
async def main():
 output=ROOT/'output/post-purchase';output.mkdir(parents=True,exist_ok=True);errors=[];calls=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True);page=await browser.new_page()
  page.on('pageerror',lambda error:errors.append(str(error)))
  async def api(route):
   path=route.request.url.split('/api/v1/')[1].split('?')[0]
   if path=='public/tracking/brand-logo':
    response=merchant_logo_response('https://shop.example.test/logo.svg')
    await route.fulfill(headers=dict(response.headers),body=response.body);return
   if path.startswith('public/tracking/'):
    body=route.request.post_data_json;calls.append((path,body))
    if path.endswith('/verify-recipient'):
     if body.get('delivery_postcode')=='WRONG':await route.fulfill(status=404,json={'detail':'Tracking verification failed'});return
     value={**VERIFIED,'tracking_access_token':ACCESS}
    elif path.endswith('/resolve'):value=VERIFIED if body['token']==ACCESS else {**PUBLIC,'access':'CAPABILITY'}
    elif path.endswith('/help'):value={'message':'Request recorded.'}
    elif path.endswith('/recipient-preferences'):value={'message':'Preferences saved.'}
    else:value=PUBLIC
   elif path=='integration/platforms':value={'platforms':[v.model_dump() for v in PLATFORMS.values()]}
   elif path.endswith('/share-links'):value={'links':[]}
   elif path.endswith('/notifications'):value={'notifications':[]}
   elif path.endswith('/health'):value={'polling_enabled':True,'jobs':[]}
   elif path.startswith(('tracking/shipments','admin/tracking/shipments')):
    item={**ITEM,'status':'DELIVERED','shipment_status':'DELIVERED','proof_of_delivery_url':'https://carrier.example.test/pod'}
    value={**DETAIL,'shipments':[item]} if path.endswith(IDENT) else {**LIST,'shipments':[item]}
   elif path in {'config','auth/config'}:value={'mode':'configured','supabase_url':None,'publishable_key':None}
   else:value={'stores':[],'shipments':[],'orders':[],'tickets':[],'history':[]}
   await route.fulfill(json=value)
  await page.route('**/api/v1/**',api)
  await page.route('https://shop.example.test/logo.svg',lambda route:route.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect fill="#059669" width="40" height="40"/></svg>'))
  for width in [375,768,1366]:
   await page.set_viewport_size({'width':width,'height':1000})
   await page.goto(BASE+'/track?q=PARCEL-000000')
   await expect(page.locator('#merchant-name')).to_have_text('Fixture Merchant')
   await expect(page.locator('#merchant-logo')).to_be_visible()
   await expect(page.frame_locator('#merchant-logo').locator('img')).to_be_visible()
   logo_image=page.frame_locator('#merchant-logo').locator('img')
   await expect(logo_image).to_have_css('max-height','44px')
   await expect(logo_image).to_have_js_property('complete',True)
   assert await logo_image.evaluate('(image)=>image.naturalWidth>0&&image.getBoundingClientRect().height<=44')
   assert await page.locator('.merchant-header').evaluate("h=>getComputedStyle(h).borderBottomColor")=="rgb(18, 52, 86)"
   await expect(page.locator('#public-tracking-content')).not_to_contain_text('Private Street')
   await page.locator('[name=postcode]').fill('WRONG');await page.get_by_role('button',name='Verify delivery postcode').click()
   await expect(page.locator('.tracking-verification [role=status]')).to_have_text('Tracking verification failed')
   await page.locator('[name=postcode]').fill('ls126ej');await page.get_by_role('button',name='Verify delivery postcode').click()
   await expect(page.locator('.verified-summary')).to_contain_text('42 Private Street')
   await expect(page.get_by_role('link',name='View Proof of Delivery (POD)')).to_have_attribute('href','https://carrier.example.test/pod')
   await expect(page.get_by_role('link',name='Start a return')).to_have_attribute('href','/returns/fixture-retailer')
   await page.locator('[name=email]').check();await page.get_by_role('button',name='Save update preferences').click()
   await expect(page.get_by_text('Preferences saved.',exact=True)).to_be_visible()
   assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
   assert ACCESS not in page.url
   await page.screenshot(path=str(output/f'verified-{width}.png'),full_page=True)
  for suffix in ['#'+CAP,'?token='+CAP]:
   await page.goto(BASE+'/track'+suffix)
   await expect(page.get_by_role('button',name='Continue with my secure tracking link')).to_be_visible()
   assert '#'+CAP in page.url and '?token=' not in page.url
  await page.goto(BASE+'/');await page.locator('#track-input').fill('PARCEL-000000');await page.locator('#track-form button[type=submit],#track-form button').first.click()
  await expect(page).to_have_url(BASE+'/track?q=PARCEL-000000')
  await page.goto(BASE+'/');publicLogo=await page.locator('[data-integration=SHOPIFY] use').get_attribute('href')
  await page.goto(BASE+'/workspace')
  await page.evaluate("""()=>{document.body.classList.remove('auth-locked');$('#loginContainer').hidden=true;state.session={access_token:'fixture',expires_at:9999999999};portal.role='CLIENT';portal.profile={portal_role:'CLIENT',workspace_role:'OWNER',tenant_id:'00000000-0000-4000-8000-000000000001'};setView('stores');}""")
  await expect(page.locator('#store-catalogue article')).to_have_count(24)
  workspaceLogo=await page.locator('#store-catalogue article').filter(has=page.locator('[data-store-connect=SHOPIFY]')).locator('use').get_attribute('href')
  assert publicLogo==workspaceLogo=='/platform-logos.svg#SHOPIFY'
  await page.evaluate("setView('tracking')")
  await page.locator('[data-tracking-open]').first.click()
  await expect(page.get_by_role('link',name='View Proof of Delivery (POD)')).to_be_visible()
  await page.locator('#tracking-detail-close').click()
  await page.locator('#tracking-auto-refresh').check()
  assert await page.locator('#tracking-auto-refresh').is_checked()
  assert not errors,errors
  await browser.close()
 print(json.dumps({'widths':[375,768,1366],'public_privacy':True,'postcode_wrong_right':True,'query_fragment':True,'branding_pod_returns':True,'shared_logos':True,'workspace_pod':True,'page_errors':errors}))
if __name__=='__main__':asyncio.run(main())
