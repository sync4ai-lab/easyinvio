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
