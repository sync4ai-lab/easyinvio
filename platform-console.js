/* Read-only platform intelligence. Customer operations remain in audited assistance. */
(() => {
 'use strict';
 let storeGeneration=0,consentGeneration=0,consentSession=null;
 const h=value=>escapeHTML(value??'');
 const date=value=>value?new Date(value).toLocaleString():'None recorded';
 const staff=()=>!!state.session&&isPlatformStaff()&&!state.assistance;
 async function loadStores(){
  if(!staff())return;
  const generation=++storeGeneration,session=state.session;
  const status=document.getElementById('platform-store-status');
  status.textContent='Loading marketplace connections…';
  try{
   const query=new URLSearchParams({environment:document.getElementById('platform-store-environment').value,search:document.getElementById('platform-store-search').value});
   const data=await api('/api/v1/admin/marketplaces?'+query,{auth:true});
   if(generation!==storeGeneration||session!==state.session||!staff())return;
   document.getElementById('platform-store-rows').innerHTML=(data.stores||[]).map(row=>`<tr><td><b>${h(row.company_name)}</b><p class="subtle">${h(row.display_name)}</p></td><td>${h(row.platform)}</td><td><span class="tag ${row.is_active?'green':''}">${row.is_active?'Enabled':'Disabled'}</span></td><td>${row.credentials_saved?'Settings saved':'No credentials saved'}</td><td>${h(row.imported_orders)}</td><td>${h(date(row.last_import_at))}</td></tr>`).join('')||'<tr><td colspan="6">No marketplace registrations match this environment and search.</td></tr>';
   status.textContent=`${data.environment||''}: ${(data.stores||[]).length} registrations shown (limit ${data.limit||200}). Search to narrow the list.`;
  }catch(error){if(generation===storeGeneration&&session===state.session){status.textContent=error.message;document.getElementById('platform-store-rows').replaceChildren();}}
 }
 const customerOwner=()=>!!state.session&&!state.assistance&&['OWNER','ADMIN'].includes(portal.profile?.workspace_role)&&!isPlatformStaff();
 async function loadConsent(){
  if(!customerOwner())return;
  const generation=++consentGeneration,session=state.session;
  const input=document.getElementById('customer-whatsapp-consent'),status=document.getElementById('customer-whatsapp-status');
  input.disabled=true;status.textContent='Loading your alert preference…';
  try{
   const data=await api('/api/v1/support/whatsapp/consent',{auth:true});
   if(generation!==consentGeneration||session!==state.session||!customerOwner())return;
   input.checked=data.notification_opt_in===true;input.disabled=!data.eligible;
   document.getElementById('customer-whatsapp-save').disabled=!data.eligible;
   status.textContent=data.eligible?'Verified number(s): '+data.bindings.map(binding=>'ending '+binding.number_suffix).join(', ')+'.':'No active verified WhatsApp number is linked to your user. Complete WhatsApp number verification before enabling alerts.';
  }catch(error){if(generation===consentGeneration&&session===state.session)status.textContent=error.message;}
 }
 function renderHealth(){
  const active=staff();document.body.classList.toggle('platform-console',active);
  const section=document.getElementById('platform-business-health');
  if(!active){section.replaceChildren();return;}
  const report=portal.report,health=report?.business_health;
  if(!health){section.innerHTML='<p class="subtle">Refresh the overview to load platform business health.</p>';return;}
  const monthly=health.monthly||[],currencies=[...new Set(monthly.map(row=>row.currency))];
  const trends=currencies.map(currency=>{
   const rows=monthly.filter(row=>row.currency===currency),max=Math.max(1,...rows.map(row=>Number(row.packages)));
   return `<h3>Shipping trend · ${h(currency)}</h3><div class="platform-months" role="img" aria-label="Monthly packages: ${h(rows.map(row=>row.month+': '+row.packages).join(', '))}">${rows.map(row=>`<div class="platform-month"><b>${h(row.packages)}</b><div class="platform-month-bar" style="height:${Math.max(2,Number(row.packages)/max*95)}px"></div><span>${h(row.month.slice(0,7))}</span></div>`).join('')}</div>`;
  }).join('')||'<p class="subtle">No confirmed shipping activity for this period.</p>';
  const leaders=(health.top_clients||[]).map(row=>`<tr><td>${h(row.company_name)}</td><td>${h(row.currency)}</td><td>${h(row.labels)}</td><td>${h(row.packages)}</td><td>${money(row.gross_revenue,row.currency)}</td><td>${money(row.gross_markup,row.currency)}</td></tr>`).join('');
  const wallets=(health.wallet_exposure||[]).map(row=>`<tr><td>${h(row.currency)}</td><td>${money(row.wallet_balance,row.currency)}</td><td>${money(row.reserved_balance,row.currency)}</td></tr>`).join('');
  section.innerHTML=`<div class="card"><h2>Shipping growth</h2>${trends}<p class="footnote">Confirmed bookings by booking month, within the selected period. Each currency is separate.</p></div><div class="card"><h2>Booking pipeline</h2><div class="platform-status-list">${(health.booking_states||[]).map(row=>`<span class="tag">${h(String(row.status).replaceAll('_',' '))}: ${h(row.shipments)}</span>`).join('')||'<p class="subtle">No shipment records created in this period.</p>'}</div><p class="footnote">Current states of shipments created in the selected period. This is a creation-date cohort, not a carrier delivery-time guarantee.</p><h3>Current wallet exposure</h3><div class="scrolltable"><table><thead><tr><th>Currency</th><th>Client wallet balances</th><th>Reserved funds</th></tr></thead><tbody>${wallets||'<tr><td colspan="3">No wallets in this environment.</td></tr>'}</tbody></table></div><p class="footnote">Current balances across clients, including held funds. Wallet funds are not shipping revenue or net profit.</p></div><div class="card platform-wide"><h2>Leading clients by package volume</h2><div class="scrolltable"><table><thead><tr><th>Client</th><th>Currency</th><th>Labels</th><th>Packages</th><th>Shipping revenue</th><th>Stored gross markup</th></tr></thead><tbody>${leaders||'<tr><td colspan="6">No booked client activity in this period.</td></tr>'}</tbody></table></div><p class="footnote">Top 20 client/currency rows by packages. Gross markup excludes operating expenses, refunds and reconciliation adjustments; it is not net profit.</p></div>`;
 }
 function renderContext(){
  renderHealth();
  const preference=document.getElementById('customer-whatsapp-preference');
  preference.hidden=!customerOwner();
  if(!preference.hidden&&enterprise.currentView==='profile'&&consentSession!==state.session){consentSession=state.session;void loadConsent();}
  const active=staff(),head=document.querySelector('#manifest .pagehead h1');
  if(head)head.textContent=active?'Platform shipments':'Every shipment, one workspace.';
  const note=document.getElementById('manifest-source');
  if(note&&active)note.textContent='Platform shipment register: latest 200 records across all clients, including sandbox and production. Search by company. Assist a client for customer operations.';
 }
 window.PlatformConsole={loadStores};
 function init(){
  document.getElementById('profile').insertAdjacentHTML('beforeend','<article class="card" id="customer-whatsapp-preference" hidden style="margin-top:18px"><h2>WhatsApp support alerts</h2><p class="subtle">Choose whether EasyInvio may send support alerts to your verified WhatsApp number. This is separate from sender shipment milestone updates and WhatsApp label booking.</p><form id="customer-whatsapp-form"><label class="check"><input id="customer-whatsapp-consent" type="checkbox" disabled>Receive WhatsApp support alerts</label><p id="customer-whatsapp-status" class="subtle" role="status"></p><div class="actions"><button class="primary" id="customer-whatsapp-save" type="submit" disabled>Save alert preference</button><button class="secondary" id="customer-whatsapp-refresh" type="button">Refresh preference</button></div></form></article>');
  document.getElementById('customer-whatsapp-refresh').addEventListener('click',loadConsent);
  document.getElementById('customer-whatsapp-form').addEventListener('submit',async event=>{
   event.preventDefault();if(!customerOwner())return;
   const session=state.session,button=document.getElementById('customer-whatsapp-save'),status=document.getElementById('customer-whatsapp-status');
   button.disabled=true;
   try{await api('/api/v1/support/whatsapp/consent',{auth:true,method:'POST',body:{notification_opt_in:document.getElementById('customer-whatsapp-consent').checked}});if(session===state.session&&customerOwner()){await loadConsent();if(session===state.session)notify('WhatsApp support alert preference saved.');}}
   catch(error){if(session===state.session)status.textContent=error.message;}
   finally{if(session===state.session)button.disabled=document.getElementById('customer-whatsapp-consent').disabled;}
  });
  const owner=document.getElementById('owner-command-center');
  const health=document.createElement('div');health.id='platform-business-health';health.className='platform-executive-grid';document.getElementById('owner-monitoring-source').after(health);
  document.querySelector('#admin-clients article').insertAdjacentHTML('beforebegin','<details class="platform-guide"><summary>How recommendation preferences work</summary><p>Balanced considers price, speed and lane risk. Budget preference recommends the cheapest eligible Evri, Royal Mail or Yodel service when it is no dearer than other eligible carriers and no more than two estimated days slower than the fastest non-budget service. High-risk lanes are excluded. This affects optional AI advice only: prices, available offers and the customer’s final selection stay unchanged. The platform owner chooses the business preference; personal accounts use budget preference automatically. If optional advice is unavailable, no recommendation is promised.</p></details>');
  document.querySelector('#admin-clients article:has(#transaction-rows)').insertAdjacentHTML('afterbegin','<details class="platform-guide"><summary>Understand wallet events</summary><p>RESERVE holds funds before label purchase. CAPTURE charges the wallet after confirmed carrier label purchase and removes that hold. RELEASE removes an unused hold. TOPUP credits the wallet after a confirmed payment, or an explicitly marked test credit in sandbox. SHIPMENT_REFUND credits an eligible shipment refund; REFUND_DEBIT reverses a refunded top-up.</p><p>Events are append-only: a reserve row does not turn into a capture row. Wallet change and hold change are signed movements. Wallet after and held after are the balances recorded at that event, not today’s balances.</p></details>');
  document.querySelector('#admin-carriers #carrier-show-legacy').closest('article').insertAdjacentHTML('afterbegin','<p class="notice">Shared carrier connections serve eligible clients. Client-assigned accounts are older or administrator-provisioned tenant configurations, including test fixtures; customers cannot add carrier credentials here. Archived shared connections and disabled legacy accounts appear only when requested. Marketplace stores are listed under Marketplace Connections.</p>');
  document.getElementById('transaction-environment').addEventListener('change',()=>loadEnterpriseView('transactions').catch(error=>notify(error.message,true)));
  document.getElementById('platform-store-refresh').addEventListener('click',loadStores);
  document.getElementById('platform-store-environment').addEventListener('change',loadStores);
  let debounce;document.getElementById('platform-store-search').addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(loadStores,300);});
  const base=renderPortal;renderPortal=function(){base.apply(this,arguments);renderContext();};
  const monitoring=renderOwnerMonitoring;renderOwnerMonitoring=function(){monitoring.apply(this,arguments);renderContext();};
  const clear=clearSession;clearSession=function(){consentGeneration++;consentSession=null;document.getElementById('customer-whatsapp-form').reset();document.getElementById('customer-whatsapp-status').textContent='';storeGeneration++;document.getElementById('platform-store-rows').replaceChildren();clear.apply(this,arguments);renderContext();};
  const view=setView;setView=function(){const result=view.apply(this,arguments);renderContext();return result;};
  renderContext();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
