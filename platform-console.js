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

/* Subscription views use the existing authenticated API and assistance controls. */
(() => {
 'use strict';
 const el=id=>document.getElementById(id),h=value=>escapeHTML(value??'');
 const root=()=>!!state.session&&portal.profile?.portal_role==='SUPER_ADMIN'&&!state.assistance;
 const client=()=>!!state.session&&portal.profile?.portal_role==='CLIENT';
 let epoch=0,revenueGeneration=0,loadedSession=null,contextKey=null,rows=[],cursor=null,selected=null,nonce=null;
 function current(session,generation){return state.session===session&&epoch===generation;}
 async function loadPlan(){
  if(!client())return;
  const session=state.session,generation=epoch;
  try{
   const p=await api('/api/v1/workspace/entitlements',{auth:true});
   if(!current(session,generation)||!client())return;
   el('subscription-summary').textContent=`${p.plan} · ${p.status} · ${p.billing_cycle}. ${p.usage?.parcels||0} parcels this month / ${p.capabilities.included_monthly_parcels} included.${p.expires_at?' Access period ends '+new Date(p.expires_at).toLocaleDateString()+'.':''}${p.grandfathered?' Your existing access is preserved.':''}`;
   el('subscription-checkout').hidden=!p.can_manage_subscription;
   el('subscription-export').hidden=!['OWNER','ADMIN','ACCOUNTANT'].includes(portal.profile?.workspace_role)||(!p.grandfathered&&!p.capabilities.features.tax_ledger_audits);
  }catch(error){if(current(session,generation))el('subscription-summary').textContent='Plan details are unavailable on this deployment. Your existing workspace remains available.';}
 }
 async function loadRevenue(next=false){
  if(!root())return;
  const session=state.session,generation=epoch,load=++revenueGeneration,status=el('subscription-revenue-status');
  status.textContent='Loading plans and revenue…';
  try{
   const q=new URLSearchParams({environment:el('subscription-environment').value});
   if(el('subscription-from').value)q.set('start',el('subscription-from').value+'T00:00:00Z');
   if(el('subscription-until').value)q.set('end',el('subscription-until').value+'T00:00:00Z');
   if(next&&cursor)q.set('after',cursor);
   const data=await api('/api/v1/admin/revenue/overview?'+q,{auth:true});
   if(!current(session,generation)||!root()||load!==revenueGeneration)return;
   rows=next?rows.concat(data.tenants):data.tenants;cursor=data.next_cursor;
   el('subscription-kpis').innerHTML=`<p><b>Contracted MRR: ${h(money(data.contracted_mrr_gbp,'GBP'))}</b></p><div class="actions">${data.tiers.map(t=>`<span class="tag">${h(t.subscription_plan)}: ${h(t.active_tenants)} active</span>`).join('')}</div>${data.label_totals_by_currency.map(t=>`<p>${h(t.currency)} · Label sales ${h(money(t.label_gross_revenue,t.currency))} · Recorded wholesale ${h(money(t.recorded_wholesale_cost,t.currency))} · Stored gross margin ${h(money(t.stored_gross_label_margin,t.currency))}</p>`).join('')}<p class="footnote">${h(data.basis)}</p>`;
   el('subscription-revenue-rows').innerHTML=rows.map((t,i)=>`<tr><td><b>${h(t.company_name)}</b><br><small>${h(t.tenant_id)}</small></td><td>${h(t.subscription_plan)}<br>${h(t.plan_status)} · ${h(t.billing_cycle)}${t.subscription_complimentary?'<br>Complimentary':''}</td><td>${h(t.parcels_this_month||0)} / ${h(t.monthly_parcel_allowance)}</td><td>${h(money(t.contracted_mrr_gbp,'GBP'))}</td><td>${(t.shipping_totals||[]).map(s=>`${h(s.currency)} sales ${h(s.label_gross_revenue)} / margin ${h(s.stored_gross_label_margin)}`).join('<br>')||'No bookings'}</td><td>${h(t.wallet_currency||'')} ${h(t.wallet_balance||'0')}<br>${h(t.last_transaction_at?new Date(t.last_transaction_at).toLocaleString():'No transactions')}</td><td><button class="secondary" data-subscription-transactions="${i}">Transactions</button><button class="secondary" data-subscription-plan="${i}">Manage plan</button></td></tr>`).join('')||'<tr><td colspan="7">No clients in this environment.</td></tr>';
   el('subscription-more').hidden=!cursor;status.textContent=`${rows.length} clients shown. Reporting ends at the selected exclusive end date.`;
  }catch(error){if(current(session,generation)&&load===revenueGeneration)status.textContent=error.message;}
 }
 async function transactions(index){
  if(!root())return;
  const session=state.session,generation=epoch,t=rows[index];
  if(!t)return;
  el('subscription-transactions').showModal();el('subscription-transaction-content').textContent='Loading transactions…';
  try{
   const data=await api('/api/v1/admin/revenue/tenants/'+encodeURIComponent(t.tenant_id)+'/transactions',{auth:true});
   if(!current(session,generation)||!root())return;
   const section=(title,items)=>`<h3>${h(title)}</h3><div class="scrolltable"><table><tbody>${items.map(item=>`<tr>${Object.entries(item).map(([k,v])=>`<td><small>${h(k.replaceAll('_',' '))}</small><br>${h(v)}</td>`).join('')}</tr>`).join('')||'<tr><td>No entries</td></tr>'}</tbody></table></div>`;
   el('subscription-transaction-content').innerHTML=`<h2>${h(t.company_name)}</h2><p>Latest ${data.wallet_movements.length} wallet entries and ${data.recent_shipments.length} booked shipments. Wallet movements are not subscription revenue.</p>`+section('Wallet ledger',data.wallet_movements)+section('Shipment margins',data.recent_shipments);
  }catch(error){if(current(session,generation))el('subscription-transaction-content').textContent=error.message;}
 }
 function edit(index){
  if(!root()||!rows[index])return;
  selected=rows[index];nonce=crypto.randomUUID();const form=el('subscription-plan-form');form.reset();
  form.elements.plan.value=selected.subscription_plan;form.elements.cycle.value=selected.billing_cycle;form.elements.status.value=selected.plan_status;
  form.elements.complimentary.checked=selected.subscription_complimentary;form.elements.manager.value=selected.dedicated_account_manager||'';
  el('subscription-plan-title').textContent='Manage '+selected.company_name;el('subscription-plan-status').textContent='';el('subscription-plan-dialog').showModal();
 }
 function render(){
  const key=JSON.stringify([portal.profile?.portal_role,portal.profile?.workspace_role,portal.profile?.tenant_id,state.assistance?.session_id]);
  if(key!==contextKey){contextKey=key;epoch++;loadedSession=null;rows=[];cursor=null;selected=null;el('subscription-summary').textContent='';el('subscription-revenue-rows').replaceChildren();el('subscription-kpis').replaceChildren();el('subscription-transaction-content').replaceChildren();for(const id of ['subscription-plan-dialog','subscription-transactions'])if(el(id).open)el(id).close();}
  el('subscription-revenue').hidden=!root();el('subscription-workspace').hidden=!client();
  if(!state.session){epoch++;loadedSession=null;rows=[];cursor=null;selected=null;el('subscription-revenue-rows').replaceChildren();el('subscription-kpis').replaceChildren();el('subscription-transaction-content').replaceChildren();el('subscription-summary').textContent='';for(const id of ['subscription-plan-dialog','subscription-transactions'])if(el(id).open)el(id).close();}
  if(client()&&loadedSession!==state.session){loadedSession=state.session;void loadPlan();}
 }
 function init(){
  el('profile').insertAdjacentHTML('beforeend',`<article class="card" id="subscription-workspace" hidden><h2>Your plan and usage</h2><p id="subscription-summary" role="status">Loading plan details…</p><p>Postage is separate from software fees. Trials expire automatically; no automatic overage charges are enabled.</p><a href="/pricing">Compare plans</a><button class="secondary" id="subscription-export" hidden>Download ledger audit CSV</button><form id="subscription-checkout" hidden><h3>Activate a paid subscription</h3><p>You will review and authorize the recurring charge in Stripe. This does not top up your postage wallet. Existing subscriptions require support to change.</p><label>Plan<select name="plan"><option value="VELOCITY">Velocity — £29/month or £288/year</option><option value="COMMAND">Command — £79/month or £780/year</option></select></label><label>Billing cycle<select name="cycle"><option value="MONTHLY">Monthly</option><option value="ANNUAL">Annual, charged in full</option></select></label><button type="submit">Review secure subscription checkout</button><p id="subscription-checkout-status" role="status"></p></form></article>`);
  el('owner-command-center').insertAdjacentHTML('beforeend',`<details class="card" id="subscription-revenue" hidden><summary><b>Plans &amp; Revenue</b></summary><p>Platform owner only. Review client plans, recorded label margins and customer wallet movements.</p><div class="actions"><label>Environment<select id="subscription-environment"><option>PRODUCTION</option><option>SANDBOX</option></select></label><label>From<input type="date" id="subscription-from"></label><label>Until (exclusive)<input type="date" id="subscription-until"></label><button id="subscription-refresh">Refresh plans &amp; revenue</button></div><p id="subscription-revenue-status" role="status"></p><div id="subscription-kpis"></div><div class="scrolltable"><table><thead><tr><th>Client</th><th>Plan &amp; status</th><th>Monthly parcels</th><th>Contracted MRR</th><th>Label sales / gross margin</th><th>Wallet / last activity</th><th>Actions</th></tr></thead><tbody id="subscription-revenue-rows"></tbody></table></div><button id="subscription-more" hidden>Load more clients</button></details>`);
  document.body.insertAdjacentHTML('beforeend',`<dialog id="subscription-transactions" style="max-width:94vw;width:1100px"><form method="dialog"><button class="secondary">Close transactions</button></form><div id="subscription-transaction-content"></div></dialog><dialog id="subscription-plan-dialog"><form method="dialog"><button class="secondary">Close plan editor</button></form><h2 id="subscription-plan-title"></h2><p>This changes commercial access only. It never grants roles, credit or verifies carrier contracts. Confirm paid billing terms separately before setting Active.</p><form id="subscription-plan-form"><label>Plan<select name="plan"><option>STARTER</option><option>VELOCITY</option><option>COMMAND</option></select></label><label>Cycle<select name="cycle"><option>MONTHLY</option><option>ANNUAL</option></select></label><label>Status<select name="status"><option>ACTIVE</option><option>TRIALING</option><option>PAST_DUE</option><option>CANCELLED</option></select></label><label>Trial days<input name="days" type="number" min="1" max="30" value="14" required></label><label class="check"><input name="complimentary" type="checkbox">Complimentary access (excluded from MRR)</label><label>Account manager<input name="manager" maxlength="200"></label><label>Audit reason<textarea name="reason" minlength="10" maxlength="500" required></textarea></label><button type="submit">Save audited plan change</button><p id="subscription-plan-status" role="status"></p></form></dialog>`);
  el('subscription-refresh').onclick=()=>loadRevenue();el('subscription-more').onclick=()=>loadRevenue(true);
  for(const id of ['subscription-environment','subscription-from','subscription-until'])el(id).onchange=()=>loadRevenue();
  el('subscription-revenue').addEventListener('toggle',()=>{if(el('subscription-revenue').open&&root())void loadRevenue();});
  el('subscription-revenue-rows').onclick=event=>{const button=event.target.closest('button');if(button?.dataset.subscriptionTransactions!==undefined)void transactions(Number(button.dataset.subscriptionTransactions));if(button?.dataset.subscriptionPlan!==undefined)edit(Number(button.dataset.subscriptionPlan));};
  el('subscription-plan-form').onsubmit=async event=>{
   event.preventDefault();if(!root()||!selected)return;const f=event.target.elements,session=state.session,generation=epoch,button=event.submitter;button.disabled=true;
   try{await api('/api/v1/admin/tenants/'+selected.tenant_id+'/plan',{auth:true,method:'PATCH',body:{request_id:nonce,expected_version:selected.plan_version,subscription_plan:f.plan.value,billing_cycle:f.cycle.value,plan_status:f.status.value,trial_days:Number(f.days.value),complimentary:f.complimentary.checked,dedicated_account_manager:f.manager.value.trim()||null,reason:f.reason.value.trim()}});if(current(session,generation)&&root()){el('subscription-plan-dialog').close();await loadRevenue();}}
   catch(error){if(current(session,generation))el('subscription-plan-status').textContent=error.message;}finally{button.disabled=false;}
  };
  el('subscription-checkout').onsubmit=async event=>{
   event.preventDefault();const session=state.session,generation=epoch,button=event.submitter;if(!client()||portal.profile.workspace_role!=='OWNER'||state.assistance)return;button.disabled=true;
   try{const f=event.target.elements,data=await api('/api/v1/workspace/subscription/checkout',{auth:true,method:'POST',body:{request_id:crypto.randomUUID(),plan:f.plan.value,cycle:f.cycle.value}});const url=new URL(data.checkout_url);if(url.origin!=='https://checkout.stripe.com')throw Error('Invalid checkout destination');if(current(session,generation)&&client())location.assign(url.href);}
   catch(error){if(current(session,generation))el('subscription-checkout-status').textContent=error.message;}finally{button.disabled=false;}
  };
  el('subscription-export').onclick=async()=>{const session=state.session,generation=epoch;try{await ensureActiveIdentitySession();const response=await fetch(API+'/api/v1/workspace/ledger/export',{headers:{Authorization:'Bearer '+state.session.access_token}});if(!response.ok)throw Error('Ledger export unavailable');const blob=await response.blob();if(!current(session,generation)||!client())return;const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='easyinvio-ledger.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){if(current(session,generation))el('subscription-summary').textContent=error.message;}};
  const renderPrevious=renderPortal;renderPortal=function(){const result=renderPrevious.apply(this,arguments);render();return result;};
  const clearPrevious=clearSession;clearSession=function(){const result=clearPrevious.apply(this,arguments);render();return result;};
  render();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
