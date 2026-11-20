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
 const scope=()=>state.session&&portal.profile?.tenant_id&&['OWNER','ADMIN','ACCOUNTANT'].includes(portal.profile.workspace_role)
   ?[state.session.access_token,portal.profile.tenant_id,portal.profile.workspace_role,state.assistance?.session_id||''].join(':'):'';
 let currentScope='',generation=0,quote=null,agreement=null,statement=null,capabilities=null;
 const card=document.createElement('div');card.id='billing-workspace';card.className='card';card.hidden=true;
 card.innerHTML=`<h2>Plan, billing & statements</h2><p>Review software charges, manage your agreement and download itemized account activity.</p>
 <button type="button" class="secondary" id="billing-refresh">Refresh billing</button><p id="billing-status" role="status" aria-live="polite"></p>
 <div id="billing-agreement"></div><div id="billing-change" hidden>
 <label for="billing-target">New plan<select id="billing-target"><option value="STARTER">Starter</option><option value="VELOCITY">Velocity</option><option value="COMMAND">Command</option></select></label>
 <div class="button-row"><button type="button" class="secondary" data-billing-action="UPGRADE">Preview upgrade</button>
 <button type="button" class="secondary" data-billing-action="DOWNGRADE">Preview downgrade</button>
 <button type="button" class="secondary" data-billing-action="CANCEL">Preview cancellation</button></div>
 <div id="billing-quote" class="notice" hidden></div><button type="button" class="primary" id="billing-confirm" hidden>Confirm these terms</button></div>
 <h3>Itemized statements</h3><p class="footnote">Top-ups fund your wallet. Subscription card charges and refunds remain separate. Statements are account activity summaries, not VAT invoices.</p>
 <div class="grid"><label>From (UTC)<input id="billing-from" type="date"></label><label>Until (exclusive, UTC)<input id="billing-until" type="date"></label>
 <label>Currency<select id="billing-currency"><option>GBP</option><option>EUR</option><option>USD</option></select></label></div>
 <div class="button-row"><button type="button" class="secondary" id="billing-generate">Create completed-period statement</button><button type="button" class="secondary" id="billing-preview">Preview current month</button></div>
 <p id="billing-statement-status" role="status" aria-live="polite" tabindex="-1"></p>
 <div id="billing-statements"></div><div id="billing-statement"></div>`;
 const $=selector=>card.querySelector(selector);
 const status=message=>{$('#billing-status').textContent=message;};
 const statementButton=button=>['billing-generate','billing-preview'].includes(button.id)||button.hasAttribute('data-statement-id')||button.hasAttribute('data-billing-export');
 function notice(message,button,error=false){const node=$(statementButton(button)?'#billing-statement-status':'#billing-status');node.textContent=message;node.setAttribute('role',error?'alert':'status');if(error){node.scrollIntoView({block:'nearest'});}}
 function statementControls(disabled){for(const id of ['billing-generate','billing-preview'])$('#'+id).disabled=disabled;}
 function reset(){generation++;quote=null;agreement=null;statement=null;capabilities=null;statementControls(false);$('#billing-statement-status').textContent='';$('#billing-agreement').replaceChildren();$('#billing-change').hidden=true;$('#billing-quote').hidden=true;$('#billing-confirm').hidden=true;$('#billing-statements').replaceChildren();$('#billing-statement').replaceChildren();status('Select Refresh billing to load this workspace.');}
 function sync(){const next=scope();if(next!==currentScope){currentScope=next;reset();}card.hidden=!next;}
 function valid(key,epoch){return key===scope()&&epoch===generation;}
 async function run(button,fn){sync();if(!currentScope||button.disabled)return;const key=currentScope,epoch=generation;button.disabled=true;
  notice('Loading billing…',button);
  try{
   if(!capabilities||button.id==='billing-refresh'){
    const data=await api('/api/v1/billing/capabilities',{auth:true});if(!valid(key,epoch))return;capabilities=data;
    statementControls(data.statements_enabled!==true);
   }
   if(capabilities.statements_enabled!==true){notice(capabilities.message||'Billing statements are not enabled for this deployment. Contact the platform administrator.',button,true);return;}
   await fn(key,epoch);
  }catch(error){if(valid(key,epoch))notice(error.message,button,true);}
  finally{button.disabled=false;if(valid(key,epoch))statementControls(capabilities?.statements_enabled===false);sync();}}
 const date=value=>value?new Date(value).toLocaleString():'Not set';
 const amount=(value,currency='GBP')=>currency+' '+String(value??'Not supplied');
 function renderAgreement(data){agreement=data;quote=null;$('#billing-quote').hidden=true;$('#billing-confirm').hidden=true;
  const s=data.subscription;
  $('#billing-agreement').innerHTML=`<h3>${h(s.subscription_plan)} · ${h(s.billing_cycle)}</h3><p>${h(s.plan_status)} · Period ${h(date(s.plan_period_start))} to ${h(date(s.plan_period_end))}</p>
   ${s.pending_plan?`<p>Scheduled ${h(s.pending_plan)} from ${h(date(s.pending_plan_effective_at))}.</p>`:''}
   ${s.cancellation_effective_at?`<p>Service ends ${h(date(s.cancellation_effective_at))}. Final notice amount: ${h(amount(s.final_notice_prorated_amount))} before applicable tax.</p>`:''}
   ${(data.operations||[]).map(o=>`<p>${h(o.action)}: ${h(o.state)} · ${h(amount(o.amount))}${o.error_code?' · Finance review required.':''}${safeInvoice(o.provider_url)?` · <a href="${h(o.provider_url)}" target="_blank" rel="noopener noreferrer">Review secure Stripe invoice</a>`:''}</p>`).join('')}`;
  $('#billing-change').hidden=!data.can_manage||capabilities?.subscription_changes_enabled===false;
 }
 function safeInvoice(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&['invoice.stripe.com','pay.stripe.com'].includes(u.hostname);}catch{return false;}}
 function renderList(data){$('#billing-statements').innerHTML=(data.statements||[]).map(s=>`<p><button type="button" class="secondary" data-statement-id="${h(s.id)}">${h(s.statement_number)}</button> ${h(s.period_start?.slice(0,10))} to ${h(s.period_end?.slice(0,10))} · ${h(s.currency)}</p>`).join('')||'<p class="subtle">No completed statements yet.</p>';}
 function renderStatement(data){statement=data;const rows=data.transactions||[];
  $('#billing-statement').innerHTML=`<h3>${h(data.statement_number)}</h3><p>${h(data.period_start?.slice(0,10))} to ${h(data.period_end?.slice(0,10))} · ${h(data.currency)}${data.preview?' · Current activity preview':''}</p>
   <p>Opening wallet: ${h(data.opening_balance)} · Funding: ${h(data.total_topups)} · Closing wallet: ${h(data.closing_balance)}</p>
   <p>Software net: ${h(data.subscription_net)} · Shipping net: ${h(data.shipping_net)} · Label refund net: ${h(data.refunds_net)} · Recorded tax: ${h(data.tax_total)} · Charges less credits: ${h(data.gross_total)}</p>
   ${data.tax_complete?'':'<p class="notice">Some tax details are unavailable. Consult the original invoices.</p>'}
   ${data.preview?'':'<button type="button" class="secondary" data-billing-export="pdf">Download PDF</button> <button type="button" class="secondary" data-billing-export="csv">Download CSV</button>'}
   <div class="responsive-table-scroll" tabindex="0" role="region" aria-label="Statement transactions"><table><thead><tr><th>Date</th><th>Activity</th><th>Reference / carrier</th><th>Net</th><th>Tax</th><th>Gross</th><th>Wallet balance</th></tr></thead><tbody>${rows.slice(0,100).map(r=>`<tr><td>${h(date(r.occurred_at))}</td><td>${h(r.type)}</td><td>${h(r.reference)} ${h(r.carrier)} ${h(r.tracking_number)}</td><td>${h(r.net_amount??'Unknown')}</td><td>${h(r.tax_amount??'Unknown')}</td><td>${h(r.gross_amount)}</td><td>${h(r.running_wallet_balance)}</td></tr>`).join('')}</tbody></table></div>
   <p class="footnote">${rows.length>100?'First 100 transactions shown. Download the full statement for all lines. ':''}${h(data.notice)}</p>`;
 }
 async function refresh(key,epoch){const data=await api('/api/v1/billing/subscription',{auth:true});if(!valid(key,epoch))return;renderAgreement(data);
  const list=await api('/api/v1/billing/statements',{auth:true});if(valid(key,epoch)){renderList(list);status('Billing refreshed. Queued payments may need a further refresh.');}}
 $('#billing-refresh').addEventListener('click',e=>run(e.currentTarget,refresh));
 $('#billing-target').addEventListener('change',()=>{quote=null;$('#billing-quote').hidden=true;$('#billing-confirm').hidden=true;});
 card.querySelectorAll('[data-billing-action]').forEach(button=>button.addEventListener('click',()=>run(button,async(key,epoch)=>{
  if(!agreement?.can_manage)return;
  const action=button.dataset.billingAction,request={request_id:crypto.randomUUID(),funding:agreement.subscription.stripe_subscription_id?'STRIPE':'WALLET'};
  if(action!=='CANCEL')request.target_plan=$('#billing-target').value;
  quote=null;$('#billing-confirm').hidden=true;
  const data=await api('/api/v1/billing/subscription/'+action.toLowerCase(),{method:'POST',auth:true,body:request});if(!valid(key,epoch))return;
  quote={action,request,data};const b=data.payload.breakdown,a=b.annual_clawback;
  $('#billing-quote').innerHTML=`<h3>Review ${h(action.toLowerCase())}: ${h(data.source_plan)} to ${h(data.target_plan)}</h3><p>Effective ${h(date(data.effective_at))}. ${action==='CANCEL'?'Final notice amount':'Amount to authorize'}: ${h(amount(data.amount))}${request.funding==='STRIPE'?' before any tax shown on the secure Stripe invoice.':' including configured wallet tax.'}</p>
   ${b.remaining_days?`<p>${h(b.remaining_days)} of ${h(b.total_days)} days remaining. Prorated difference: ${h(amount(b.prorated_amount))}.</p>`:''}
   ${action==='DOWNGRADE'?`<p>Current features remain until the period ends. Next period price: ${h(amount(b.next_period_price))} before applicable tax.${b.next_period_total?' Wallet total including configured tax: '+h(amount(b.next_period_total))+'.':''}</p>`:''}
   ${a?`<p>Annual discount removed. Elapsed usage at monthly prices: ${h(amount(a.usage_at_monthly_price))}. 30-day notice at monthly prices: ${h(amount(a.notice_at_monthly_price))}. Verified prepaid net: ${h(amount(a.verified_annual_prepaid_net))}.</p><p>Refund after service ends: ${h(amount(a.net_refund))} net, plus the corresponding original tax. Additional balance: ${h(amount(a.additional_balance_for_review))} net. Refunds go to the original payment source.</p>`:''}
   <p>Confirm only after reviewing these terms. Stripe charges require payment of the secure invoice; available wallet funds are debited for wallet-funded charges.</p>`;
  $('#billing-quote').hidden=false;$('#billing-confirm').hidden=false;status('Preview only. No charge or refund has been made.');
 })));
 $('#billing-confirm').addEventListener('click',e=>run(e.currentTarget,async(key,epoch)=>{
  const chosen=quote;if(!chosen)return;
  const data=await api('/api/v1/billing/subscription/'+chosen.action.toLowerCase(),{method:'POST',auth:true,body:{...chosen.request,confirm:true,quote_sha256:chosen.data.payload_sha256}});
  if(!valid(key,epoch))return;quote=null;$('#billing-confirm').hidden=true;status('Request '+data.state+'. Refresh billing to see payment and processing status.');
 }));
 for(const [id,preview] of [['billing-generate',false],['billing-preview',true]])$('#'+id).addEventListener('click',e=>run(e.currentTarget,async(key,epoch)=>{
  const currency=$('#billing-currency').value;let data;
  if(preview)data=await api('/api/v1/billing/statements/preview?currency='+encodeURIComponent(currency),{auth:true});
  else {const from=$('#billing-from').value,until=$('#billing-until').value;if(!from||!until)throw Error('Choose both dates. The end date is exclusive.');data=await api('/api/v1/billing/statements',{auth:true,method:'POST',body:{start:from+'T00:00:00Z',end:until+'T00:00:00Z',currency}});}
  if(valid(key,epoch)){renderStatement(data);notice(preview?'Current activity preview.':'Statement created and retained. Refresh billing to update the list.',$('#'+id));}
 }));
 card.addEventListener('click',e=>{const button=e.target.closest('[data-statement-id],[data-billing-export]');if(!button)return;
  run(button,async(key,epoch)=>{
   if(button.dataset.statementId){const data=await api('/api/v1/billing/statements/'+encodeURIComponent(button.dataset.statementId),{auth:true});if(valid(key,epoch)){renderStatement(data);notice('Statement loaded.',button);}return;}
   const s=statement,format=button.dataset.billingExport;if(!s?.id||!['pdf','csv'].includes(format))return;
   await ensureActiveIdentitySession();if(!valid(key,epoch))return;
   const response=await fetch(API+'/api/v1/billing/statements/'+encodeURIComponent(s.id)+'/'+format,{headers:{Authorization:'Bearer '+state.session.access_token},cache:'no-store'});
   if(!response.ok)throw Error('The statement export could not be downloaded. Refresh your session and retry.');const blob=await response.blob();if(!valid(key,epoch))return;
   const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='EasyInvio-statement.'+format;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice('Statement downloaded.',button);
  });
 });
 function init(){const wallet=document.getElementById('wallet');if(!wallet)return;wallet.append(card);
  const now=new Date(),end=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),1)),start=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth()-1,1));
  $('#billing-from').value=start.toISOString().slice(0,10);$('#billing-until').value=end.toISOString().slice(0,10);
  const originalView=setView;setView=function(...args){const result=originalView(...args);sync();return result;};
  const originalClear=clearSession;clearSession=function(...args){currentScope='';reset();card.hidden=true;return originalClear(...args);};
  const originalRefresh=refreshPortal;refreshPortal=async function(...args){try{return await originalRefresh(...args);}finally{sync();}};
  sync();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
