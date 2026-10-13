// Execute the actual inline controllers in a lightweight DOM test double.
// This verifies state logic and event wiring, not browser layout or rendering.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');

async function run(root) {
  const html = fs.readFileSync(root + '/index.html', 'utf8');
  const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  new vm.Script(source);
  const elements = new Map();
  class Element {
    constructor(id) { this.id=id; this.value=''; this.hidden=false; this.disabled=false; this.handlers={}; this.dataset={}; this.style={}; this.textContent=''; this._html=''; this.classList={toggle(){}}; }
    set innerHTML(value) { this._html=value; parse(value); }
    get innerHTML() { return this._html; }
    addEventListener(type, handler) { (this.handlers[type]??=[]).push(handler); }
    setAttribute() {}
    close() {this.open=false;}
    showModal() {this.open=true;}
    focus() {document.activeElement=this;}
    replaceChildren() {this._html='';this.textContent='';}
    click() {this.emit('click');}
    emit(type, event={}) {for(const handler of this.handlers[type]||[])handler({preventDefault(){},target:this,...event});}
    closest() {return this;}
  }
  function parse(fragment) {
    for (const match of fragment.matchAll(/<([\w-]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
      const attrs=match[2], id=match[3]; let element=elements.get(id);
      if(!element){element=new Element(id);elements.set(id,element);}
      const value=attrs.match(/\bvalue="([^"]*)"/); if(value)element.value=value[1];
      const view=attrs.match(/data-view="([^"]+)"/); if(view)element.dataset.view=view[1];
      element.hidden=/\bhidden\b/.test(attrs); element.disabled=/\bdisabled\b/.test(attrs);
    }
  }
  parse(html.split('<script>')[0]);
  elements.set('confirm-preview', new Element('confirm-preview'));
  for(const [id,value] of Object.entries({currency:'GBP','manifest-filter':'all','decl-form':'CN23','decl-incoterm':'DAP','decl-category':'SALE','item-description':'Silk running sneakers leather trim'}))elements.get(id).value=value;
  const tabs=['dashboard','dispatch','manifest','boxes','wallet','customs'].map(id=>elements.get('tab-'+id));
  const panels=['dashboard','dispatch','manifest','boxes','wallet','customs'].map(id=>elements.get(id));
  const nav=new Element('nav'), progress=new Element('progress-span');
  const document={activeElement:null,querySelector(selector){if(selector==='nav')return nav;if(selector==='#batch-progress span')return progress;if(selector.startsWith('#'))return elements.get(selector.slice(1))||null;return null;},querySelectorAll(selector){if(selector==='[data-view]'||selector==='nav [role=tab]')return tabs;if(selector==='[role=tabpanel]')return panels;if(selector==='[data-close]')return[];return[];},createElement(){return new Element('download');}};
  const requests=[];
  const sandbox={document,location:{port:'8000'},crypto:webcrypto,URL,Blob,console,setTimeout:(fn,ms)=>{if(ms<100) return setTimeout(fn,ms);return 0;},clearTimeout,fetch:async(path,options={})=>{
    requests.push({path,options});
    let data;
    if(path==='/health')data={mode:'local-preview'};
    else if(path==='/api/v1/config')data={supabase_url:null,publishable_key:null};
    else if(path==='/api/v1/logistics/weight')data={actual_weight_kg:'2.500',volumetric_weight_kg:'4.800',billable_weight_kg:'4.800',basis:'volumetric'};
    else if(path==='/api/v1/logistics/package-guidance')data={blocking:false,messages:[],measurement_help:'Measure the sealed package'};
    else if(path==='/api/v1/rates/preview')data={simulated:true,currency:'GBP',rates:[{simulated:true,provider:'EASYPOST',carrier_code:'DHL',service_code:'Express',currency:'GBP',delivery_days:2,client_price_ex_tax:'23.00',fee_breakdown:{source:'simulation',base_cost:'16.00',fuel_surcharge:'1.92',residential_fee:'1.50',remote_area_fee:'0.00',wholesale_total:'19.42',platform_markup:'3.58'}}],issues:[],partial:false};
    else if(path==='/api/v1/customs/harmonize')data={candidates:[{hs_code:'640411',confidence:'0.70',title:'Textile trainers',matched_terms:['silk'],assumptions:'Review upper and sole'}]};
    else throw Error('Unexpected request '+path);
    return {ok:true,status:200,json:async()=>data};
  }};
  vm.createContext(sandbox);
  vm.runInContext(source.replace(/^initialize\(\);$/m, 'globalThis.ready=initialize();'),sandbox);
  for (const extra of [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].slice(1))vm.runInContext(extra[1],sandbox);
  await sandbox.ready;
  const evaluate=code=>vm.runInContext(code,sandbox);
  assert.equal(evaluate('state.mode'),'local-preview');
  assert.match(elements.get('dashboard-metrics').innerHTML,/4,320/);
  elements.get('role-admin').click();
  assert.match(elements.get('dashboard-metrics').innerHTML,/759,000/);
  assert.doesNotMatch(elements.get('dashboard-metrics').innerHTML,/4,320/);
  assert.match(elements.get('primary-chart').innerHTML,/DHL/);
  assert.match(elements.get('support-tickets').innerHTML,/DEMO SCENARIO/);
  elements.get('role-client').click();
  assert.match(elements.get('dashboard-metrics').innerHTML,/342.10/);
  assert.doesNotMatch(elements.get('dashboard-metrics').innerHTML,/759,000/);
  evaluate('applyBox(0)');
  assert.equal(elements.get('length_cm').value,'24');
  assert.equal(elements.get('boxes').hidden,true);
  assert.equal(elements.get('dispatch').hidden,false);
  evaluate('portal.profile={portal_role:"CLIENT"};state.session={access_token:"fixture"};setPortalRole("SUPER_ADMIN")');
  assert.equal(evaluate('portal.role'),'CLIENT');
  evaluate('state.session=null');
  assert.equal(evaluate('money("123456789012.34")'),'£123,456,789,012.34');
  assert.equal(evaluate('decimalCents(cents("100.01"))'),'100.01');
  assert.throws(()=>evaluate('cents("1.001")'));
  assert.equal(evaluate('escapeHTML("<img onerror=alert(1)>")'),'&lt;img onerror=alert(1)&gt;');
  assert.equal(evaluate('csvCell("=SUM(A1)")'),'"\'=SUM(A1)"');
  elements.get('tab-customs').click();
  assert.equal(elements.get('dispatch').hidden,true);
  assert.equal(elements.get('customs').hidden,false);
  elements.get('quote-form').emit('submit');
  await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(evaluate('state.quotes.length'),1);
  assert.match(elements.get('rates').innerHTML,/View full surcharge breakdown/);
  assert.match(elements.get('rates').innerHTML,/Residential accessorial fee/);
  evaluate('bookPreview(0)');
  assert.equal(evaluate('state.wallet'),122700n);
  assert.equal(evaluate('state.manifest.length'),2);
  evaluate('bookPreview(0)');
  assert.equal(evaluate('state.wallet'),122700n);
  elements.get('topup-form').emit('submit');
  await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(evaluate('state.wallet'),132700n);
  elements.get('harmonizer-form').emit('submit');
  await new Promise(resolve=>setTimeout(resolve,10));
  assert.match(elements.get('hs-results').innerHTML,/640411/);
  evaluate('state.wallet=0n');
  const printButton=new Element('print-button');
  printButton.dataset.print='00000000-0000-4000-8000-000000001043';
  elements.get('manifest-body').emit('click',{target:printButton});
  await new Promise(resolve=>setTimeout(resolve,10));
  assert.match(elements.get('toast').textContent,/402/);
  assert.notEqual(elements.get('print-dialog').open,true);
  evaluate('clearSession()');
  assert.equal(evaluate('state.manifest.length'),0);
  assert.equal(evaluate('state.quotes.length'),0);
  assert.equal(evaluate('state.wallet'),0n);
  let complete;
  sandbox.fetch=()=>new Promise(resolve=>complete=resolve);
  evaluate('state.session={access_token:"old-session"}');
  const pending=evaluate('api("/api/v1/wallet",{auth:true})');
  evaluate('clearSession()');
  complete({ok:true,status:200,json:async()=>({balance:'100.00'})});
  await assert.rejects(pending,/Session changed/);
  // Explicit regressions for the repaired failed UAT controller cases.
  evaluate('state.session={access_token:"expired",expires_at:Date.now()/1000-1};armSessionExpiry()');
  await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(evaluate('state.session'),null);
  elements.get('length_cm').value='500';
  await evaluate('updateWeight()');
  assert.match(elements.get('weight-result').textContent,/Oversize parcel/);
  const dhl={carrier_code:'DHL',provider:'EASYPOST',service_code:'ONE',currency:'GBP',client_price_ex_tax:'10.00'};
  const dpd={...dhl,carrier_code:'DPD'};
  evaluate('state.lastRateResult='+JSON.stringify({rates:[dhl,dpd],issues:[],simulated:true}));
  elements.get('carrier-filter').value='DPD';
  elements.get('carrier-filter').emit('change');
  assert.match(elements.get('rates').innerHTML,/DPD/);
  assert.doesNotMatch(elements.get('rates').innerHTML,/DHL/);
  evaluate('portal.tickets=[{id:"1",title:"open",status:"OPEN",ai_summary:"Review"},{id:"2",title:"closed",status:"CLOSED",ai_summary:"Done"}];renderTickets()');
  assert.match(elements.get('support-count').textContent,/1 .*OPEN EXCEPTIONS/);
  assert.match(elements.get('support-tickets').innerHTML,/Archived exception/);
  elements.get('tab-boxes').click();
  elements.get('box-backdrop').click();
  assert.equal(elements.get('boxes').hidden,true);
  evaluate('resetQuoteForm()');
  assert.equal(elements.get('length_cm').value,'');
  assert.equal(elements.get('weight_kg').value,'');
  assert.match(html,/uat-pulse/);
  assert.match(html,/sheet-enter/);
  assert.match(html,/background:#0f172a/);
  return 'Frontend controller checks passed: navigation, exact money, escaping, fee disclosure, preview booking idempotency, top-up, classification and session clearing.';
}
module.exports={run};
