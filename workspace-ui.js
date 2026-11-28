/* Presentation only. Account authority remains server-verified. */
(() => {
  'use strict';
  let passwordSequence=0,recoveryTimer=null;
  function maskPasswords(){
    document.querySelectorAll('#loginContainer input[data-identity-password]').forEach(input=>{
      input.type='password';
      const button=document.querySelector('[data-password-for="'+input.id+'"]');
      button?.setAttribute('aria-pressed','false');button?.setAttribute('aria-label','Show password');
    });
  }
  function preparePasswords(){
    document.querySelectorAll('#loginContainer input[type=password]').forEach(input=>{
      if(input.dataset.identityPassword)return;
      input.dataset.identityPassword='true';
      if(!input.id)input.id='identity-password-field-'+(++passwordSequence);
      let wrapper=input.closest('.identity-input');
      if(!wrapper){wrapper=document.createElement('div');wrapper.className='identity-input';input.before(wrapper);wrapper.append(input);}
      const button=document.createElement('button');button.type='button';button.className='password-visibility';
      button.dataset.passwordFor=input.id;button.setAttribute('aria-controls',input.id);button.setAttribute('aria-label','Show password');button.setAttribute('aria-pressed','false');
      button.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
      button.addEventListener('click',()=>{const show=input.type==='password';input.type=show?'text':'password';button.setAttribute('aria-pressed',String(show));button.setAttribute('aria-label',show?'Hide password':'Show password');});
      wrapper.append(button);
    });
  }
  function prepareTables(){
    document.querySelectorAll('main table').forEach(table=>{
      if(table.closest('.scrolltable,.catalog-scroll,.table-wrap,.responsive-table-scroll'))return;
      const wrapper=document.createElement('div');wrapper.className='responsive-table-scroll';table.before(wrapper);wrapper.append(table);
    });
    document.querySelectorAll('main .scrolltable,main .catalog-scroll,main .responsive-table-scroll').forEach(wrapper=>{
      wrapper.tabIndex=0;wrapper.setAttribute('role','region');wrapper.setAttribute('aria-label','Table; scroll horizontally for more columns');
    });
  }
  let contactFrame=null;
  function scheduleContactAlignment(){
    if(contactFrame!==null)return;
    contactFrame=requestAnimationFrame(()=>{
      contactFrame=null;
      const region=document.getElementById('address-fields');
      const blocks=[...document.querySelectorAll('#address-fields>.contact-block')];
      if(!region||blocks.length!==2)return;
      const selectors=['summary','.contact-address-summary',...Array.from({length:5},(_,i)=>'label:nth-of-type('+(i+1)+')')];
      const pairs=selectors.map(selector=>blocks.map(block=>block.querySelector('.contact-details>'+selector)));
      pairs.forEach(pair=>pair.forEach(node=>{if(node)node.style.minHeight='';}));
      const aligned=blocks.every(block=>block.querySelector('details').open)&&Math.abs(blocks[0].getBoundingClientRect().top-blocks[1].getBoundingClientRect().top)<2;
      region.dataset.alignContacts=String(aligned);
      if(!aligned)return;
      pairs.forEach(pair=>{
        if(pair.some(node=>!node))return;
        const height=Math.max(...pair.map(node=>node.getBoundingClientRect().height));
        pair.forEach(node=>node.style.minHeight=height+'px');
      });
    });
  }
  function showRecoveryNotice(){
    let notice=document.getElementById('identity-recovery-notice');
    if(!notice){
      notice=document.createElement('dialog');notice.id='identity-recovery-notice';notice.setAttribute('aria-labelledby','identity-recovery-notice-title');
      notice.innerHTML='<h2 id="identity-recovery-notice-title">Check your email</h2><p>If this email is registered, a password reset link will arrive shortly. Check your spam folder.</p><div class="actions"><button type="button" class="secondary" aria-label="Close">Close</button></div>';
      notice.querySelector('button').addEventListener('click',()=>notice.close());
      notice.addEventListener('close',()=>{
        clearTimeout(recoveryTimer);recoveryTimer=null;
        document.querySelectorAll('#identity-login-form,#identity-recovery-form,#identity-reset-form').forEach(form=>form.reset());
        document.querySelectorAll('#loginContainer [role=status]').forEach(node=>node.textContent='');
        maskPasswords();identityRecoveryView('login');document.getElementById('identity-email').focus();
      });
      document.body.append(notice);
    }
    clearTimeout(recoveryTimer);if(!notice.open)notice.showModal();
    recoveryTimer=setTimeout(()=>{if(notice.open)notice.close();},5000);
  }
  window.easyinvioIdentityUI={showRecoveryNotice,maskPasswords};
  function init(){
    preparePasswords();prepareTables();
    const login=document.getElementById('loginContainer');
    if(login)new MutationObserver(preparePasswords).observe(login,{childList:true,subtree:true});
    const main=document.querySelector('main');
    if(main)new MutationObserver(prepareTables).observe(main,{childList:true,subtree:true});
    document.addEventListener('reset',event=>{if(login?.contains(event.target))maskPasswords();});
    const addresses=document.getElementById('address-fields');
    if(addresses){
      new MutationObserver(scheduleContactAlignment).observe(addresses,{childList:true,subtree:true,characterData:true});
      if(typeof ResizeObserver==='function')new ResizeObserver(scheduleContactAlignment).observe(addresses);
      addresses.addEventListener('toggle',scheduleContactAlignment,true);
      addresses.addEventListener('input',scheduleContactAlignment);
      window.addEventListener('resize',scheduleContactAlignment);
      scheduleContactAlignment();
    }
    const nav=document.querySelector('.mobile-nav');
    if(nav&&typeof ResizeObserver==='function')new ResizeObserver(()=>document.documentElement.style.setProperty('--mobile-nav-height',nav.getBoundingClientRect().height+'px')).observe(nav);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();

/* Billing uses the existing identity/assistance transport. Displayed previews
   are server-owned quotes; the browser never computes a charge or refund. */
(() => {
 'use strict';
 const h=value=>escapeHTML(value??'');
 const sessions=new WeakMap();let sessionSequence=0;
 const identityBoundary=token=>{
  try{const c=JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));return JSON.stringify([c.jti,c.user_id,c.tenant_id,c.role]);}
  catch{return '';}
 }; // Cache fencing only: all identity and permission verification stays on the server.
 const scope=()=>{
  const session=state.session;if(!session||!portal.profile?.tenant_id||!['OWNER','ADMIN','ACCOUNTANT'].includes(portal.profile.workspace_role))return '';
  // Renewal updates the token on the same verified session. Keep the panel;
  // a different session, tenant, role or assistance session still clears it.
  if(!sessions.has(session))sessions.set(session,++sessionSequence);
  return [sessions.get(session),identityBoundary(session.access_token),portal.profile.tenant_id,portal.profile.workspace_role,state.assistance?.session_id||'',session.user?.id||portal.profile.user_id||''].join(':');
 };
 let currentScope='',generation=0,quote=null,agreement=null,statement=null,capabilities=null,managing=false;
 const card=document.createElement('div');card.id='billing-workspace';card.className='card';card.hidden=true;
 card.innerHTML=`<h2>Your plan & billing</h2><p>Manage your plan and download statements.</p>
 <div class="billing-toolbar"><button type="button" class="primary" id="billing-manage">Change plan</button><button type="button" class="secondary" id="billing-compare">Compare plans</button><button type="button" class="secondary" id="billing-refresh">Reload billing details</button></div><p id="billing-status" role="status" aria-live="polite"></p>
 <div id="billing-agreement"></div><div id="billing-change" hidden>
 <div class="billing-toolbar"><h3>Change plan</h3><button type="button" class="secondary" id="billing-management-close">Back</button></div><p id="billing-management-note"></p>
 <label for="billing-target">Choose a different plan<select id="billing-target"><option value="">Choose a plan…</option><option value="STARTER">Starter</option><option value="VELOCITY">Velocity</option><option value="COMMAND">Command</option></select></label>
 <p id="billing-selection-note" class="footnote"></p><fieldset id="billing-payment-options" hidden><legend>Pay for this upgrade</legend><label><input type="radio" name="billing-funding" value="STRIPE" checked> Pay by card</label><label><input type="radio" name="billing-funding" value="WALLET"> Use available wallet balance <span id="billing-wallet-available"></span></label><p class="footnote">Wallet payment requires the full amount, including tax. Your regular renewal payment method stays the same.</p></fieldset>
 <div class="billing-toolbar"><button type="button" class="primary" id="billing-plan-review" data-billing-action="UPGRADE" hidden>Review upgrade</button>
 <button type="button" class="secondary" id="billing-cancel" data-billing-action="CANCEL">Cancel current subscription</button></div>
 <div id="billing-quote" class="notice" hidden></div><button type="button" class="primary" id="billing-confirm" hidden>Confirm these terms</button></div>
 <dialog id="billing-comparison" aria-labelledby="billing-comparison-title"><div class="billing-toolbar"><h2 id="billing-comparison-title">Compare plans</h2><button type="button" id="billing-comparison-close" class="secondary">Close comparison</button></div><p>Compare features here. To change your subscription, use Manage your plan and review the exact price and effective date before confirming.</p><p class="footnote">On smaller screens, swipe the table sideways to see all three plans.</p><div id="billing-comparison-content"></div><p class="footnote">Software prices exclude applicable tax. Shipping and third-party usage are charged separately. Postpaid billing requires separate credit approval.</p></dialog>
 <h3>Itemized statements</h3><p class="footnote">View activity or download a monthly statement.</p>
 <div class="grid"><label>From (UTC)<input id="billing-from" type="date"></label><label>To (inclusive, UTC)<input id="billing-until" type="date"></label>
 <label>Currency<select id="billing-currency"><option>GBP</option><option>EUR</option><option>USD</option></select></label></div>
 <div class="button-row"><button type="button" class="primary" id="billing-generate">View date range</button><button type="button" class="secondary" id="billing-preview">Current month</button></div>
 <details id="billing-previous"><summary>Previous Statements</summary><div class="billing-toolbar"><label>Month<input type="month" id="billing-month"></label><button type="button" class="secondary" id="billing-save">View monthly statement</button></div><div id="billing-statements"></div></details>
 <p id="billing-statement-status" role="status" aria-live="polite" tabindex="-1"></p>
 <div id="billing-statement"></div>`;
 const $=selector=>card.querySelector(selector);
 const status=message=>{$('#billing-status').textContent=message;};
 const statementButton=button=>['billing-generate','billing-preview','billing-save'].includes(button.id)||button.hasAttribute('data-statement-id')||button.hasAttribute('data-billing-export');
 function notice(message,button,error=false){const node=$(statementButton(button)?'#billing-statement-status':'#billing-status');node.textContent=message;node.setAttribute('role',error?'alert':'status');if(error){node.scrollIntoView({block:'nearest'});}}
 function statementControls(disabled){for(const id of ['billing-generate','billing-preview','billing-save'])$('#'+id).disabled=disabled;}
 function reset(){$('#billing-from').min=$('#billing-until').min=$('#billing-month').min='';delete $('#billing-previous').dataset.available;$('#billing-month').disabled=false;$('#billing-month').closest('.billing-toolbar').hidden=false;$('#billing-save').hidden=false;generation++;quote=null;agreement=null;statement=null;capabilities=null;managing=false;statementControls(false);if($('#billing-comparison').open)$('#billing-comparison').close();$('#billing-comparison-content').replaceChildren();$('#billing-target').value='';$('#billing-statement-status').textContent='';$('#billing-agreement').replaceChildren();$('#billing-change').hidden=true;$('#billing-quote').hidden=true;$('#billing-confirm').hidden=true;$('#billing-statements').replaceChildren();$('#billing-statement').replaceChildren();status('Your plan details load when you open Wallet & Billing.');}
 function sync(){const next=scope();if(next!==currentScope){currentScope=next;reset();}card.hidden=!next;}
 function valid(key,epoch){return key===scope()&&epoch===generation;}
 async function run(button,fn){sync();if(!currentScope||button.disabled)return;const key=currentScope,epoch=generation;button.disabled=true;
  notice('Loading billing…',button);
  try{
   if(!capabilities||button.id==='billing-refresh'){
    const data=await api('/api/v1/billing/capabilities',{auth:true});if(!valid(key,epoch))return;capabilities=data;
    statementControls(data.statements_enabled!==true);
   }
   if(capabilities.statements_enabled!==true&&statementButton(button)){notice(capabilities.message||'Billing statements are not enabled for this deployment. Contact the platform administrator.',button,true);return;}
   await fn(key,epoch);
  }catch(error){if(valid(key,epoch))notice(error.message,button,true);}
  finally{button.disabled=false;if(valid(key,epoch))statementControls(capabilities?.statements_enabled===false);sync();}}
 const date=value=>value?new Date(value).toLocaleDateString('en-GB',{timeZone:'UTC'}):'Not set';
 const amount=(value,currency='GBP')=>currency+' '+(value==null?'Not supplied':Number(value).toFixed(2));
 const planName=value=>String(value??'').charAt(0)+String(value??'').slice(1).toLowerCase();
 function registrationDates(data){
  const registered=data.registered_at||data.subscription?.registered_at;if(!registered)return;
  const first=registered.slice(0,10),month=first.slice(0,7),today=new Date().toISOString().slice(0,10),thisMonth=today.slice(0,7);
  $('#billing-from').min=$('#billing-until').min=first;
  if(!$('#billing-from').value||$('#billing-from').value<first)$('#billing-from').value=first;
  if(!$('#billing-until').value||$('#billing-until').value<first)$('#billing-until').value=today;
  const available=month<thisMonth;
  $('#billing-month').min=month;$('#billing-month').disabled=!available;$('#billing-month').closest('.billing-toolbar').hidden=!available;
  $('#billing-save').hidden=!available;
  if($('#billing-month').value<month)$('#billing-month').value=month;
  $('#billing-previous').dataset.available=String(available);
 }
 function renderAgreement(data){registrationDates(data);agreement=data;quote=null;$('#billing-quote').hidden=true;$('#billing-confirm').hidden=true;
  const s=data.subscription;
  $('#billing-agreement').innerHTML=`<h3>Current plan: ${h(planName(s.subscription_plan))} · ${s.billing_cycle==='ANNUAL'?'Annual':'Monthly'}</h3><p>${h({ACTIVE:'Active',TRIALING:'Trial',PAST_DUE:'Payment overdue',CANCELLED:'Cancelled',PENDING_CANCELLATION:'Cancellation scheduled'}[s.plan_status]||s.plan_status)}</p><p>${s.plan_period_end?'Current period: '+h(date(s.plan_period_start))+' to '+h(date(s.plan_period_end))+'.':''}</p>

   ${s.pending_plan?`<p>Scheduled ${h(s.pending_plan)} from ${h(date(s.pending_plan_effective_at))}.</p>`:''}
   ${s.cancellation_effective_at?`<p>Service ends ${h(date(s.cancellation_effective_at))}. Final notice amount: ${h(amount(s.final_notice_prorated_amount))} before applicable tax.</p>`:''}
   ${(data.operations||[]).filter(o=>['AUTHORIZED','PROVIDER_PENDING','PAID','SCHEDULED','REVIEW','FAILED'].includes(o.state)).map(o=>`<p>${h(o.action.toLowerCase().replaceAll('_',' '))}: ${h({AUTHORIZED:'Request received',PROVIDER_PENDING:'Awaiting payment or processing',PAID:'Payment received; applying change',SCHEDULED:'Scheduled',REVIEW:'Finance review needed',FAILED:'Not completed'}[o.state])}${safeInvoice(o.provider_url)?` · <a href="${h(o.provider_url)}" target="_blank" rel="noopener noreferrer">Continue to secure payment</a>`:''}</p>`).join('')}`;
  $('#billing-manage').hidden=!data.can_manage;
  $('#billing-change').hidden=!managing||!data.can_manage||capabilities?.subscription_changes_enabled===false;
  $('#billing-management-note').textContent=data.management?.reason||'Review your price adjustment and effective date before confirming. Choosing a plan does not charge you.';
  window.dispatchEvent(new CustomEvent('easyinvio-billing-loaded',{detail:data}));
  const m=data.management||{},available=(m.upgrade_targets?.length||m.downgrade_targets?.length||m.activation_targets?.length);
  $('#billing-target').closest('label').hidden=!available;for(const option of $('#billing-target').options)if(option.value)option.disabled=m.activation_targets?.length?!m.activation_targets.includes(option.value):false;
  $('#billing-cancel').hidden=false;$('#billing-cancel').title=m.can_cancel?'Review cancellation':'No paid subscription to cancel';
  $('#billing-selection-note').hidden=!available;
  selection();
  const pending=(data.operations||[]).find(o=>o.state==='PROVIDER_PENDING'&&safeInvoice(o.provider_url));
  if(pending){$('#billing-quote').hidden=false;$('#billing-quote').innerHTML='<h3>Complete your payment</h3><p>Your current plan stays active until payment is confirmed.</p><a class="primary" target="_blank" rel="noopener noreferrer" href="'+h(pending.provider_url)+'">Pay by card</a>';}
 }
 function selection(){
  quote=null;$('#billing-quote').hidden=true;$('#billing-confirm').hidden=true;
  const target=$('#billing-target').value,m=agreement?.management,s=agreement?.subscription,button=$('#billing-plan-review');
  const action=m?.activation_targets?.includes(target)?'ACTIVATE':m?.upgrade_targets?.includes(target)?'UPGRADE':m?.downgrade_targets?.includes(target)?'DOWNGRADE':null;
  button.hidden=!action;button.disabled=!action;if(action){button.dataset.billingAction=action;button.textContent='Review '+(action==='ACTIVATE'?'subscription':action.toLowerCase())+' to '+target.charAt(0)+target.slice(1).toLowerCase();}
  $('#billing-payment-options').hidden=action!=='UPGRADE';
  const wallet=agreement?.wallet,available=wallet?.currency==='GBP'?Number(wallet.available):0;
  $('#billing-wallet-available').textContent='('+amount(available)+' available)';
  const walletOption=$('[name="billing-funding"][value="WALLET"]');walletOption.disabled=available<=0;
  if(walletOption.disabled||action!=='UPGRADE')$('[name="billing-funding"][value="STRIPE"]').checked=true;
  $('#billing-cancel').disabled=!m?.can_cancel;
  $('#billing-selection-note').textContent=!target?'Choose a plan to see the available action.':target===s?.subscription_plan&&!m?.activation_targets?.includes(target)?'You are already on this plan.':m?.reason||(!action?'This change is not available for the current agreement.':'You will see the amount and timing before confirming.');
 }
 function comparison(){
  const plans=agreement?.plans||[];if(!plans.length)throw Error('Plan comparison is unavailable. Reload billing details and retry.');
  const features=[['Workspace users',p=>p.max_users],['Included monthly parcels',p=>p.included_monthly_parcels],['Store connections',p=>p.max_store_connections],['WhatsApp booking','whatsapp_bot'],['Hosted store returns portal & paperless QR returns','paperless_qr_returns'],['24-platform sales directory & tracking write-back','store_integrations'],['Custom Website HMAC API & checkout rates','store_integrations'],['Branded tracking & consented buyer alerts','store_integrations'],['AI Return Policy Copilot','paperless_qr_returns'],['Itemized PDF / CSV statements',p=>'When enabled'],['Public tracking, PAF lookup & CSV batch',p=>'Included'],['Dedicated account manager',p=>p.plan==='COMMAND'?'By agreement':'Not included'],['AI carrier advisor','ai_carrier_advisor'],['End-of-day manifests','eod_manifests'],['Customs HS builder','customs_hs_builder'],['Custom margin rules','custom_margin_rules'],['Your own carrier contracts','byoc_carrier_accounts'],['Tax and ledger audit exports','tax_ledger_audits'],['Postpaid billing eligibility','postpaid_billing']];
  $('#billing-comparison-content').innerHTML=`<div class="responsive-table-scroll" tabindex="0" role="region" aria-label="Plan features"><table><thead><tr><th>Feature</th>${plans.map(p=>`<th>${h(p.plan)}${p.plan===agreement.subscription.subscription_plan?' · Current plan':''}</th>`).join('')}</tr></thead><tbody><tr><th>Monthly price</th>${plans.map(p=>`<td>${h(amount(p.monthly_fee_gbp))}/month</td>`).join('')}</tr><tr><th>Annual price</th>${plans.map(p=>`<td>${h(amount(p.annual_fee_gbp))}/year (${h(amount(p.annual_monthly_fee_gbp))}/month equivalent)</td>`).join('')}</tr>${features.map(([name,key])=>`<tr><th>${h(name)}</th>${plans.map(p=>`<td>${h(typeof key==='function'?key(p):p.features?.[key]?'Included':'Not included')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  $('#billing-comparison').showModal();$('#billing-comparison-close').focus();
 }
 function safeInvoice(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&['invoice.stripe.com','pay.stripe.com'].includes(u.hostname);}catch{return false;}}
 function renderList(data){if($('#billing-previous').dataset.available==='false')data={...data,statements:[]};window.dispatchEvent(new CustomEvent('easyinvio-statements-loaded',{detail:data}));$('#billing-statements').innerHTML=(data.statements||[]).map(s=>`<p><button type="button" class="secondary" data-statement-id="${h(s.id)}">${h(new Date(s.period_start).toLocaleDateString('en-GB',{month:'long',year:'numeric',timeZone:'UTC'}))}</button> Statement ${h(s.display_reference||s.statement_number)} · ${h(s.currency)}</p>`).join('')||'<p class="subtle">No statements to display.</p>';}
 function renderStatement(data){statement=data;window.renderEnterpriseStatement($('#billing-statement'),data);$('#billing-statement').querySelector('[data-statement-close]').onclick=()=>{statement=null;$('#billing-statement').replaceChildren();$('#billing-generate').focus();};}

 async function refresh(key,epoch){let data=await api('/api/v1/billing/subscription',{auth:true});if(!valid(key,epoch))return;
  if(data.can_manage&&!data.subscription.stripe_subscription_id&&data.activation_checkout_available&&Object.values(data.activation_checkout_available).some(Boolean)){await api('/api/v1/billing/subscription/reconcile',{method:'POST',auth:true});if(!valid(key,epoch))return;data=await api('/api/v1/billing/subscription',{auth:true});if(!valid(key,epoch))return;}
  if(data.can_manage){for(const operation of (data.operations||[]).filter(o=>['AUTHORIZED','PROVIDER_PENDING','PAID'].includes(o.state)).slice(0,3)){data=await api('/api/v1/billing/subscription/'+operation.id+'/process',{method:'POST',auth:true});if(!valid(key,epoch))return;}}renderAgreement(data);
  if(capabilities?.statements_enabled!==true){status(capabilities?.message||'Plan loaded. Statements are not enabled.');return;}
  const list=await api('/api/v1/billing/statements',{auth:true});if(valid(key,epoch)){renderList(list);status((data.operations||[]).some(o=>['AUTHORIZED','PROVIDER_PENDING','PAID'].includes(o.state))?'A request is still processing. Reload billing details shortly to check its status.':'Billing details are up to date.');}}
 function watchPending(key,epoch,attempt=0){
  if(!valid(key,epoch)||attempt>=15)return;
  setTimeout(async()=>{
   if(!valid(key,epoch))return;
   await run($('#billing-refresh'),refresh);
   if(!valid(key,epoch))return;
   if(agreement?.operations?.some(o=>['AUTHORIZED','PROVIDER_PENDING','PAID'].includes(o.state)))watchPending(key,epoch,attempt+1);
   else window.dispatchEvent(new CustomEvent('easyinvio-plan-changed'));
  },2000);
 }
 $('#billing-refresh').addEventListener('click',e=>run(e.currentTarget,refresh));
 $('#billing-manage').addEventListener('click',e=>run(e.currentTarget,async(key,epoch)=>{if(!agreement)await refresh(key,epoch);if(!valid(key,epoch)||!agreement?.can_manage)return;managing=true;$('#billing-change').hidden=false;selection();$('#billing-change').scrollIntoView({block:'nearest'});status(agreement.management?.reason||'Choose a plan change, then review and confirm the terms. No changes take effect until you confirm.');}));
 $('#billing-compare').addEventListener('click',e=>run(e.currentTarget,async(key,epoch)=>{if(!agreement)await refresh(key,epoch);if(valid(key,epoch)){comparison();status('Comparing plan features. Your subscription has not changed.');}}));
 $('#billing-comparison-close').addEventListener('click',()=>$('#billing-comparison').close());
 $('#billing-management-close').onclick=()=>{managing=false;quote=null;$('#billing-change').hidden=true;$('#billing-confirm').hidden=true;};
 $('#billing-target').addEventListener('change',selection);
 card.querySelectorAll('[name="billing-funding"]').forEach(input=>input.addEventListener('change',()=>{quote=null;$('#billing-quote').hidden=true;$('#billing-confirm').hidden=true;status('Payment method selected. Review the updated amount before confirming.');}));
 card.querySelectorAll('[data-billing-action]').forEach(button=>button.addEventListener('click',()=>run(button,async(key,epoch)=>{
  if(!agreement?.can_manage)return;
  const action=button.dataset.billingAction,request={request_id:crypto.randomUUID(),funding:button.dataset.billingAction==='UPGRADE'?($('[name="billing-funding"]:checked')?.value||'STRIPE'):(agreement.subscription.stripe_subscription_id?'STRIPE':'WALLET')};
  const m=agreement.management,target=$('#billing-target').value;
  if(action==='ACTIVATE'){
   if(!m.activation_targets?.includes(target))throw Error('Choose an available subscription.');
   const plan=agreement.plans.find(p=>p.plan===target),cycle=agreement.subscription.billing_cycle||'MONTHLY';
   const price=cycle==='ANNUAL'?plan.annual_fee_gbp:plan.monthly_fee_gbp;
   quote={action,request:{request_id:crypto.randomUUID(),plan:target,cycle}};
   $('#billing-quote').innerHTML=`<h3>${h(planName(target))} — ${h(amount(price))}/${cycle==='ANNUAL'?'year':'month'}</h3><p>New subscription; no previous subscription payment to prorate. Tax and final terms appear at secure checkout.</p>`;
   $('#billing-quote').hidden=false;$('#billing-confirm').hidden=false;$('#billing-confirm').textContent='Confirm plan and continue to payment';$('#billing-confirm').disabled=agreement.activation_checkout_available?.[target]===false;status($('#billing-confirm').disabled?'Subscription payments are not configured for this plan. Contact support; your current plan is unchanged.':'Review only. Confirm below and complete payment to activate this plan.');return;
  }
  if(action==='CANCEL'?!m?.can_cancel:!(action==='UPGRADE'?m?.upgrade_targets:m?.downgrade_targets)?.includes(target))throw Error(m?.reason||'Choose an available change for this subscription.');
  if(action!=='CANCEL')request.target_plan=$('#billing-target').value;
  quote=null;$('#billing-confirm').hidden=true;
  const data=await api('/api/v1/billing/subscription/'+action.toLowerCase(),{method:'POST',auth:true,body:request});if(!valid(key,epoch))return;
  quote={action,request,data};const b=data.payload.breakdown,a=b.annual_clawback;
  const source=agreement.plans.find(p=>p.plan===data.source_plan),targetPlan=agreement.plans.find(p=>p.plan===data.target_plan),feeKey=agreement.subscription.billing_cycle==='ANNUAL'?'annual_fee_gbp':'monthly_fee_gbp';
  $('#billing-quote').innerHTML=`<h3>Review ${h(action.toLowerCase())}: ${h(data.source_plan)} to ${h(data.target_plan)}</h3><p>Effective ${h(date(data.effective_at))}. ${action==='CANCEL'?'Final notice amount':'Amount to authorize'}: ${h(amount(data.amount))}${request.funding==='STRIPE'?' before applicable tax shown on the secure invoice.':' including configured wallet tax.'}</p>
   ${b.remaining_days?`<p>${Number(b.remaining_days).toFixed(2)} days remain in your ${Number(b.total_days).toFixed(2)}-day billing period. You pay only the plan price difference for this unused part of the period.</p><p>${h(amount(source?.[feeKey]))} current plan → ${h(amount(targetPlan?.[feeKey]))} new plan. Difference for a full period: ${h(amount(Number(targetPlan?.[feeKey])-Number(source?.[feeKey])))} × ${Number(b.remaining_days).toFixed(2)} ÷ ${Number(b.total_days).toFixed(2)} days = <strong>${h(amount(b.prorated_amount))}</strong> before tax. The charge uses the exact remaining time; displayed days are rounded.</p>`:''}
   ${action==='DOWNGRADE'?`<p>Current features remain until the period ends. Next period price: ${h(amount(b.next_period_price))} before applicable tax.${b.next_period_total?' Wallet total including configured tax: '+h(amount(b.next_period_total))+'.':''}</p>`:''}
   ${a?`<p>Annual discount removed. Elapsed usage at monthly prices: ${h(amount(a.usage_at_monthly_price))}. 30-day notice at monthly prices: ${h(amount(a.notice_at_monthly_price))}. Verified prepaid net: ${h(amount(a.verified_annual_prepaid_net))}.</p><p>Refund after service ends: ${h(amount(a.net_refund))} net, plus the corresponding original tax. Additional balance: ${h(amount(a.additional_balance_for_review))} net. Refunds go to the original payment source.</p>`:''}
   <p>${request.funding==='WALLET'?'Payment: wallet. The full amount shown will be deducted once you confirm.':'Payment: card. Confirm to prepare your secure payment invoice.'} Your new plan starts after payment is confirmed.</p>`;
  $('#billing-quote').hidden=false;$('#billing-confirm').hidden=false;$('#billing-confirm').disabled=false;
  $('#billing-confirm').textContent=action==='CANCEL'?'Confirm cancellation':action==='DOWNGRADE'?'Confirm scheduled downgrade':(request.funding==='WALLET'?'Confirm upgrade and pay from wallet':'Confirm upgrade and continue to payment');
  if(request.funding==='WALLET'&&Number(data.amount)>Number(agreement.wallet?.available||0)){$('#billing-confirm').disabled=true;status('The wallet must cover the full amount. Choose card payment or top up, then review again.');return;}
  status(action==='CANCEL'?'Review the service end date and any notice charge or refund. Your subscription has not been cancelled yet.':'Review only. Your plan has not changed and no charge has been made.');
 })));
 $('#billing-confirm').addEventListener('click',e=>run(e.currentTarget,async(key,epoch)=>{
  const chosen=quote;if(!chosen)return;
  if(chosen.action==='ACTIVATE'){
   const data=await api('/api/v1/workspace/subscription/checkout',{method:'POST',auth:true,body:chosen.request});if(!valid(key,epoch))return;
   const url=new URL(data.checkout_url);if(url.protocol!=='https:'||url.hostname!=='checkout.stripe.com'||url.username||url.password)throw Error('Unexpected checkout destination.');location.assign(url.href);return;
  }
  let data=await api('/api/v1/billing/subscription/'+chosen.action.toLowerCase(),{method:'POST',auth:true,body:{...chosen.request,confirm:true,quote_sha256:chosen.data.payload_sha256}});
  if(!valid(key,epoch))return;const processed=await api('/api/v1/billing/subscription/'+data.id+'/process',{method:'POST',auth:true});data=processed.operations?.find(o=>o.id===data.id)||data;
  if(!valid(key,epoch))return;quote=null;$('#billing-confirm').hidden=true;
  const confirmed=['APPLIED','SCHEDULED'].includes(data.state);
  const message=confirmed?(chosen.action==='CANCEL'?'Cancellation scheduled. Service ends '+date(chosen.data.effective_at)+'.':chosen.action==='DOWNGRADE'?'Downgrade scheduled for '+date(chosen.data.effective_at)+'.':'Upgrade applied. Your plan details are up to date.'):'Change awaiting payment or processing. Your current plan remains active until confirmation.';
  await refresh(key,epoch);if(!valid(key,epoch))return;
  const payment=agreement?.operations?.find(o=>o.id===data.id);if(payment&&safeInvoice(payment.provider_url)&&payment.state==='PROVIDER_PENDING'){$('#billing-quote').hidden=false;$('#billing-quote').innerHTML='<h3>Complete your payment</h3><p>Your current plan stays active until payment is confirmed.</p><a class="primary" target="_blank" rel="noopener noreferrer" href="'+h(payment.provider_url)+'">Pay by card</a>';$('#billing-quote').scrollIntoView({block:'nearest'});}
  if(!confirmed)watchPending(key,epoch);
  if(confirmed){window.dispatchEvent(new CustomEvent('easyinvio-plan-changed'));try{await refreshPortal();}catch{ /* Billing is already refreshed; other views retry on navigation. */ }}
  if(!valid(key,epoch))return;
  if(!payment||payment.state!=='PROVIDER_PENDING'||!safeInvoice(payment.provider_url)){$('#billing-quote').textContent=message;$('#billing-quote').hidden=false;}status(message);
 }));
 for(const id of ['billing-generate','billing-preview','billing-save'])$('#'+id).addEventListener('click',e=>run(e.currentTarget,async(key,epoch)=>{
  const currency=$('#billing-currency').value;let data;
  if(id==='billing-preview')data=await api('/api/v1/billing/statements/preview?currency='+encodeURIComponent(currency),{auth:true});
  else if(id==='billing-save'){
   const value=$('#billing-month').value;if(!/^\d{4}-\d{2}$/.test(value))throw Error('Choose a month.');
   const [year,month]=value.split('-').map(Number);
   data=await api('/api/v1/billing/statements/monthly',{auth:true,method:'POST',body:{year,month,currency}});
  }else{
   const from=$('#billing-from').value,to=$('#billing-until').value,now=new Date();
   const start=Date.parse(from+'T00:00:00Z'),end=Date.parse(to+'T00:00:00Z')+86400000,days=(end-start)/86400000;
   if($('#billing-from').min&&from<$('#billing-from').min)throw Error('Choose a start date on or after your registration date.');
   if(!from||!to||!Number.isFinite(days)||days<1||days>366)throw Error('Choose a date range of 1 to 366 days.');
   if(to>now.toISOString().slice(0,10))throw Error('Choose an end date no later than today.');
   data=await api('/api/v1/billing/statements/preview?'+new URLSearchParams({currency,start:new Date(start).toISOString(),end:new Date(Math.min(end,now.getTime())).toISOString()}),{auth:true});
   if(Date.parse(data.period_start)!==start||Date.parse(data.period_end)!==Math.min(end,now.getTime()))throw Error('Restart the local server to load date-range support, then retry.');
  }
  if(id==='billing-save'&&valid(key,epoch)){const list=await api('/api/v1/billing/statements',{auth:true});if(valid(key,epoch))renderList(list);}
  if(valid(key,epoch)){if(id==='billing-preview'){$('#billing-from').value=data.period_start.slice(0,10);$('#billing-until').value=new Date(Date.parse(data.period_end)-1).toISOString().slice(0,10);}renderStatement(data);notice(id==='billing-save'?'Monthly statement ready.':'Activity ready.',$('#'+id));$('#billing-statement').scrollIntoView({block:'start'});}
 }));
 card.addEventListener('click',e=>{const button=e.target.closest('[data-statement-id],[data-billing-export]');if(!button)return;
  run(button,async(key,epoch)=>{
   if(button.dataset.statementId){const data=await api('/api/v1/billing/statements/'+encodeURIComponent(button.dataset.statementId),{auth:true});if(valid(key,epoch)){renderStatement(data);notice('Statement loaded.',button);}return;}
   const s=statement,format=button.dataset.billingExport;if((!s?.id&&!s?.preview)||!['pdf','csv'].includes(format))return;
   await ensureActiveIdentitySession();if(!valid(key,epoch))return;
   const response=await fetch(API+'/api/v1/billing/statements/'+(s.preview?'preview':encodeURIComponent(s.id))+'/'+format+(s.preview?'?'+new URLSearchParams({currency:s.currency,start:s.period_start,end:s.period_end}):''),{headers:{Authorization:'Bearer '+state.session.access_token},cache:'no-store'});
   if(!response.ok)throw Error('The statement export could not be downloaded. Refresh your session and retry.');const blob=await response.blob();if(!valid(key,epoch))return;
   const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='EasyInvio-statement.'+format;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice('Statement downloaded.',button);
  });
 });
 function init(){const wallet=document.getElementById('wallet');if(!wallet)return;wallet.append(card);
  const now=new Date(),end=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),1)),start=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth()-1,1));
  $('#billing-month').value=start.toISOString().slice(0,7);$('#billing-month').max=start.toISOString().slice(0,7);$('#billing-from').value=start.toISOString().slice(0,10);$('#billing-until').value=new Date(end.getTime()-86400000).toISOString().slice(0,10);$('#billing-from').max=$('#billing-until').max=now.toISOString().slice(0,10);
  let returnChecks=0,returnTimer=null;
  const subscriptionReturn=new URLSearchParams(location.search).get('subscription');
  function reconcileReturn(){
   if(subscriptionReturn!=='processing'||!currentScope||returnChecks>=15)return;
   if(agreement?.subscription.stripe_subscription_id&&!agreement.subscription.subscription_complimentary&&agreement.subscription.subscription_plan!=='STARTER'&&['ACTIVE','TRIALING'].includes(agreement.subscription.plan_status)){
    status('Subscription confirmed. Your plan details are up to date.');window.dispatchEvent(new CustomEvent('easyinvio-plan-changed'));returnChecks=15;return;
   }
   status('Confirming your subscription payment. Your current plan remains active until confirmation.');
   if(!returnTimer){returnChecks++;const key=currentScope,epoch=generation;returnTimer=setTimeout(async()=>{returnTimer=null;if(!valid(key,epoch))return;await run($('#billing-refresh'),refresh);reconcileReturn();},2000);}
  }
  let autoLoading=false;
  async function autoLoad(){sync();if(!currentScope||autoLoading)return;autoLoading=true;try{await run($('#billing-refresh'),refresh);reconcileReturn();}finally{autoLoading=false;}}
  const originalView=setView;setView=function(...args){const result=originalView(...args);sync();if(args[0]==='wallet')autoLoad();return result;};
  const originalClear=clearSession;clearSession=function(...args){currentScope='';reset();card.hidden=true;return originalClear(...args);};
  const originalRefresh=refreshPortal;refreshPortal=async function(...args){try{return await originalRefresh(...args);}finally{sync();if(subscriptionReturn&&currentScope)setView('wallet');}};
  sync();if(!wallet.hidden)autoLoad();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
