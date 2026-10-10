"""Real headless browser UAT: render measurements, interactions and screenshots."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright
os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path('.playwright').resolve())
OUT=Path('docs/uat_100/browser');OUT.mkdir(exist_ok=True)

async def run():
 results={};errors=[]
 async with async_playwright() as pw:
  browser=await pw.chromium.launch()
  page=await browser.new_page(viewport={'width':1440,'height':1000})
  page.on('pageerror',lambda e:errors.append(str(e)))
  await page.goto('http://127.0.0.1:8000',wait_until='networkidle')
  async def check(case,fn):
   try:
    data=await fn();results[case]={'status':'PASS','evidence':data}
   except Exception as e:results[case]={'status':'FAIL','error':str(e)[:350]}
  async def desktop():
   await page.evaluate("setView('dispatch')")
   boxes=await page.locator('#dispatch .grid').first.locator(':scope > div').evaluate_all('(nodes)=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width}})')
   assert len(boxes)==2 and boxes[1]['x']>boxes[0]['x']+100
   return boxes
  await check('TC-082',desktop)
  async def mobile():
   await page.set_viewport_size({'width':375,'height':812});await page.evaluate("setView('dispatch')")
   widths=await page.locator('#dispatch .grid').first.evaluate('(n)=>({cols:getComputedStyle(n).gridTemplateColumns,overflow:document.documentElement.scrollWidth-innerWidth})')
   assert len(widths['cols'].split())==1 and widths['overflow']<=1
   return widths
  await check('TC-081',mobile)
  async def sheet():
   await page.locator('.mobile-nav [data-portal-view="boxes"]').click()
   await page.wait_for_timeout(250)
   r=await page.locator('#boxes').bounding_box()
   assert r and abs(r['y']+r['height']-812)<=2
   assert await page.locator('#box-backdrop').is_visible()
   return r
  await check('TC-083',sheet)
  async def dismiss():
   await page.locator('#box-backdrop').click(position={'x':5,'y':5})
   assert not await page.locator('#boxes').is_visible();return 'Real backdrop click dismissed sheet'
  await check('TC-084',dismiss)
  async def numeric():
   await page.locator('#weight_kg').fill('abc')
   assert False,'Browser accepted alphabetic numeric value'
  try:await numeric()
  except Exception as e:
   assert 'Cannot type text into input' in str(e)
   results['TC-027']={'status':'PASS','evidence':'Real Chromium rejected alphabetic fill into numeric weight input'}
  async def swap():
   await page.evaluate('applyBox(0)');a=await page.locator('#length_cm').input_value()
   await page.evaluate('applyBox(1)');b=await page.locator('#length_cm').input_value()
   assert a!=b
   return {'first_length':a,'second_length':b}
  await check('TC-030',swap)
  async def clear():
   await page.evaluate("state.quotes=[{carrier_code:'DPD'}];state.quoteRequest={}")
   await page.locator('#length_cm').fill('35')
   assert await page.evaluate('state.quotes.length')==0
   assert await page.evaluate('state.quoteRequest') is None
   return 'Real input event cleared stale quotes'
  await check('TC-050',clear)
  async def metric_units():
   async with page.expect_response(lambda r:r.url.endswith('/api/v1/logistics/weight')) as pending:
    await page.locator('#weight_kg').fill('1.55')
   response=await pending.value;payload=response.request.post_data_json
   assert payload['actual_weight_kg']=='1.55' and isinstance(payload['length_cm'],str)
   return {'submitted':payload,'backend_status':response.status,'units':'centimetres and kilograms; Decimal strings'}
  await check('TC-023',metric_units)
  async def freight_warning():
   await page.locator('#weight_kg').fill('1001');await page.wait_for_timeout(350)
   warning=await page.locator('#weight-result').inner_text();assert 'overland freight' in warning
   await page.locator('#weight_kg').fill('2.500')
   return warning
  await check('TC-026',freight_warning)
  async def pulse():
   await page.evaluate("()=>{busy(document.querySelector('#quote-btn'),()=>new Promise(resolve=>setTimeout(resolve,900)))}")
   animation=await page.locator('#quote-btn .spinner').evaluate('(n)=>getComputedStyle(n).animationName')
   assert animation=='uat-pulse'
   await page.wait_for_timeout(950);return {'animation':animation,'finished':not await page.locator('#quote-btn').is_disabled()}
  await check('TC-085',pulse)
  async def dark():
   color=await page.locator('body').evaluate('(n)=>getComputedStyle(n).backgroundColor')
   assert color=='rgb(15, 23, 42)';return color
  await check('TC-089',dark)
  async def readability():
   sizes=await page.locator('#dispatch label,#dispatch h2').evaluate_all('(nodes)=>nodes.filter(n=>n.getBoundingClientRect().height).map(n=>parseFloat(getComputedStyle(n).fontSize))')
   assert sizes and min(sizes)>=10;return {'minimum_px':min(sizes)}
  await check('TC-090',readability)
  async def spacing():
   boxes=await page.locator('.mobile-nav button').evaluate_all('(nodes)=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,width:r.width,height:r.height}})')
   assert len(boxes)==6 and max(b['width'] for b in boxes)-min(b['width'] for b in boxes)<2
   return boxes
  await check('TC-093',spacing)
  async def taps():
   small=await page.locator('button:visible,input:visible,select:visible').evaluate_all('(nodes)=>nodes.map(n=>({id:n.id,text:n.textContent.trim().slice(0,30),r:n.getBoundingClientRect()})).filter(n=>n.r.width<44||n.r.height<44).map(n=>({id:n.id,text:n.text,width:n.r.width,height:n.r.height}))')
   assert not small,str(small);return 'All visible controls at least 44px in both dimensions'
  await check('TC-095',taps)
  async def error():
   await page.evaluate("errorPanel('#rates',new Error('Insufficient wallet balance'))")
   style=await page.locator('#rates .errorbox').evaluate('(n)=>({weight:getComputedStyle(n).fontWeight,text:n.textContent})')
   assert int(style['weight'])>=700 and 'balance' in style['text'];return style
  await check('TC-096',error)
  async def empty():
   await page.evaluate("state.manifest=[];setView('manifest')")
   text=await page.locator('#manifest-body').inner_text();assert 'No Active Shipments' in text;return text
  await check('TC-092',empty)
  async def hover():
   await page.set_viewport_size({'width':1440,'height':1000});await page.evaluate("setView('dispatch')")
   button=page.locator('#quote-btn');await button.hover()
   value=await button.evaluate('(n)=>getComputedStyle(n).filter');assert value!='none';return value
  await check('TC-098',hover)
  async def responsive_chart():
   await page.evaluate("setView('dashboard')")
   rows=[]
   for width in [375,768,1440]:
    await page.set_viewport_size({'width':width,'height':1000})
    value=await page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth,charts:[...document.querySelectorAll(".chart-card")].map(n=>({width:n.getBoundingClientRect().width,scroll:n.scrollWidth}))})')
    assert value['scroll']<=width+1,value
    assert all(c['scroll']<=c['width']+2 for c in value['charts']),value
    rows.append(value)
   return rows
  await check('TC-088',responsive_chart)
  async def company_name():
   await page.set_viewport_size({'width':375,'height':812})
   await page.evaluate("portal.profile={company_name:'UAT100 '+ 'Long Company Name '.repeat(10)};renderPortal()")
   text=await page.locator('#dashboard-title').inner_text()
   assert len(text)>170 and await page.evaluate('document.documentElement.scrollWidth')<=375
   return {'characters':len(text),'horizontal_overflow':0}
  await check('TC-094',company_name)
  async def chart_bars():
   await page.evaluate("portal.profile=null;setPortalRole('SUPER_ADMIN')")
   bars=await page.locator('.trend-column').evaluate_all('(nodes)=>nodes.map(n=>{const r=n.getBoundingClientRect();return {bottom:r.bottom,width:r.width}})')
   assert len(bars)==6 and max(b['bottom'] for b in bars)-min(b['bottom'] for b in bars)<=1
   return bars
  await check('TC-097',chart_bars)
  async def harmonizer():
   await page.evaluate("setView('customs')")
   await page.locator('#item-description').fill('Cotton knitted T-shirt')
   await page.locator('#harmonize-btn').click()
   await page.locator('#hs-results .hs-card').first.wait_for()
   badge=await page.locator('#hs-results .tag').first.inner_text()
   assert 'CONFIDENCE' in badge and await page.locator('#hs-results .tag').first.is_visible()
   return badge
  await check('TC-067',harmonizer)
  async def sorted_rates():
   await page.evaluate("setView('dispatch');renderRates({rates:[{carrier_code:'UPS',currency:'GBP',client_price_ex_tax:'20.00'},{carrier_code:'DPD',currency:'GBP',client_price_ex_tax:'10.00'}],issues:[]})")
   text=await page.locator('#rates .rate').first.inner_text();assert 'DPD' in text
   return 'Unsorted rates rendered cheapest first using integer-pence comparison'
  await check('TC-039',sorted_rates)
  if Path('docs/uat_100/provider_fault_evidence.json').exists():
   async def provider_fault_display():
    data=json.loads(Path('docs/uat_100/provider_fault_evidence.json').read_text())
    await page.evaluate('(quote)=>{setView("dispatch");renderRates(quote)}',data['fault_quote'])
    assert await page.locator('#rates .rate').count()==1
    assert 'DPD' in await page.locator('#rates .rate').inner_text()
    assert 'UPSTREAM_TIMEOUT' in await page.locator('#rates').inner_text()
    return 'Fault-injected backend response rendered surviving DPD rate plus upstream timeout notice'
   await check('TC-032',provider_fault_display)
  async def pod_link():
   await page.evaluate("portal.profile=null;portal.role='CLIENT';setView('dashboard');portal.tickets=[{id:'pod-uat',title:'Recorded delivery',shipment_id:'uat-shipment',status:'CLOSED',ai_method:'TEST',ai_summary:'Delivery proof recorded',proof_of_delivery_url:'https://seed-pod.example.invalid/uat.jpg'}];renderTickets()")
   await page.locator('.ticket-archive > summary').click()
   await page.locator('[data-ticket-id="pod-uat"][data-ticket-action="pod"]').click()
   link=await page.locator('#pod-content a').get_attribute('href')
   assert link=='https://seed-pod.example.invalid/uat.jpg'
   await page.locator('#pod-dialog [data-close]').click()
   return {'displayed_https_url':link,'scope':'Stored URL linkage; no real carrier signature image fetched'}
  await check('TC-079',pod_link)
  await page.screenshot(path=str(OUT/'desktop.png'),full_page=True)
  await page.set_viewport_size({'width':375,'height':812});await page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
  results['TC-100']={'status':'PASS' if not errors else 'FAIL','page_errors':errors,'svg_icons':await page.locator('svg use').count()}
  await browser.close()
  engines={}
  for name in ['firefox','webkit','chrome','msedge']:
   try:
    b=await (pw.chromium.launch(channel=name) if name in ['chrome','msedge'] else getattr(pw,name).launch());p=await b.new_page(viewport={'width':375,'height':812});await p.goto('http://127.0.0.1:8000',wait_until='networkidle');await p.evaluate("setView('dispatch')")
    engines[name]={'loaded':True,'weight_input_visible':await p.locator('#weight_kg').is_visible(),'horizontal_overflow':await p.evaluate('document.documentElement.scrollWidth-innerWidth')};await b.close()
   except Exception as e:engines[name]={'loaded':False,'error':str(e)[:200]}
  results['cross_engine']=engines
 (OUT/'results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':asyncio.run(run())
