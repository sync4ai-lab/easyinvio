/* Functional channel configuration; preserves the existing workspace design. */
(() => {
  'use strict';
  const panel=document.querySelector('#stores');
  if(!panel)return;
  const category=document.createElement('select');category.id='store-category';category.setAttribute('aria-label','Platform category');
  ['All','Custom Website & API','Marketplaces','Hosted Carts','Enterprise'].forEach(name=>category.add(new Option(name,name)));
  document.querySelector('#store-search').after(category);
  category.addEventListener('change',()=>renderStoreCatalogue());
  const form=document.querySelector('#store-connection-form');
  form.insertAdjacentHTML('afterbegin',`<fieldset><legend>Connection options</legend>
    <label>Retailer website HTTPS origin<input name="store_url" type="url" placeholder="https://shop.example.com"></label>
    <label>BigCommerce store hash / Wix site ID<input name="external_store_id" maxlength="200"></label>
    <label>Signed tracking callback URL (bridge platforms)<input name="tracking_callback_url" type="url"></label>
    <label>Native REST access token (eBay, BigCommerce, Wix or Magento)<input name="rest_access_token" type="password" autocomplete="new-password"></label>
    <label>WooCommerce REST consumer key<input name="woo_key" autocomplete="off"></label>
    <label>WooCommerce REST consumer secret<input name="woo_secret" type="password" autocomplete="new-password"></label>
    <label class="check"><input name="live_delivery" type="checkbox">Enable live tracking write-back</label>
    <p>Native APIs require authorized tokens and scopes. Other platforms use the signed API bridge. Blank secrets retain saved values.</p>
    </fieldset>`);
  document.body.insertAdjacentHTML('beforeend',`<dialog id="store-machine-secret"><button type="button" data-close-machine>Close</button><h2>Store machine credentials</h2>
    <p>Copy the signing secret now. It will not be displayed again. Rotation invalidates previous signatures.</p>
    <label>Key ID<input id="store-machine-key" readonly></label><label>Signing secret<input id="store-machine-value" readonly type="password"></label>
    <button type="button" id="store-machine-copy">Copy credentials</button></dialog>
    <dialog id="store-return-policy"><button type="button" data-close-portal>Close</button><h2>Public returns portal</h2>
    <form id="store-return-policy-form"><label>Portal address identifier<input name="store_slug" required pattern="[a-z0-9][a-z0-9-]{1,61}[a-z0-9]" placeholder="my-store"></label>
    <label><input name="enabled" type="checkbox">Authorize self-service returns under this spending policy</label>
    <label>Return window (days)<input name="days" type="number" min="1" max="90" value="30" required></label>
    <label>Who pays?<select name="payer"><option value="RETAILER_PAY">Retailer</option><option value="CUSTOMER_PAY">Customer through Stripe</option></select></label>
    <label>Maximum return postage (£)<input name="cap" type="number" min="0.01" max="100" step="0.01" value="10.00" required></label>
    <p>Domestic GB, original single-parcel packaging only. International/changed packaging needs retailer review. QR only when supported by the carrier.</p>
    <button type="submit">Save authorized policy</button></form><p id="store-return-policy-result" role="status"></p></dialog>`);
  window.showStoreMachineCredentials=value=>{
    if(!value.one_time_webhook_secret)return;
    document.querySelector('#store-machine-key').value=value.api_key_id;
    document.querySelector('#store-machine-value').value=value.one_time_webhook_secret;
    document.querySelector('#store-machine-secret').showModal();
  };
  document.querySelector('[data-close-machine]').onclick=()=>document.querySelector('#store-machine-secret').close();
  document.querySelector('#store-machine-secret').addEventListener('close',()=>{
    document.querySelector('#store-machine-key').value='';document.querySelector('#store-machine-value').value='';
  });
  document.querySelector('#store-machine-copy').onclick=async()=>{
    await navigator.clipboard.writeText('Key ID: '+document.querySelector('#store-machine-key').value+'\nSigning secret: '+document.querySelector('#store-machine-value').value);
    notify('Copied. Store credentials securely on your server.');
  };
  let portalStore=null;
  function clearPrivateDialogs(){
    document.querySelector('#store-machine-secret').close();
    document.querySelector('#store-machine-key').value='';
    document.querySelector('#store-machine-value').value='';
    document.querySelector('#store-return-policy').close();portalStore=null;
  }
  window.addEventListener('easyinvio-session-ready',clearPrivateDialogs);
  window.addEventListener('storage',event=>{if(event.key==='easyinvio.logout')clearPrivateDialogs();});
  document.addEventListener('click',event=>{if(event.target.closest('#identity-logout,#signout-btn'))clearPrivateDialogs();},true);
  document.querySelector('[data-close-portal]').onclick=()=>document.querySelector('#store-return-policy').close();
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-store-test],[data-store-portal],[data-store-key]');if(!button)return;
    busy(button,async()=>{
      if(button.dataset.storeTest){
        const r=await api('/api/v1/workspace/stores/'+button.dataset.storeTest+'/test-connection',{method:'POST',auth:true});
        notify((r.verified?'Verified: ':'Not yet verified: ')+r.scope);return;
      }
      if(button.dataset.storeKey){
        if(!window.confirm('Rotate this store signing secret? Existing bridge signatures will stop working.'))return;
        showStoreMachineCredentials(await api('/api/v1/workspace/stores/'+button.dataset.storeKey+'/rotate-machine-secret',{method:'POST',auth:true}));return;
      }
      portalStore=button.dataset.storePortal;
      const r=await api('/api/v1/workspace/stores/'+portalStore+'/returns-portal',{auth:true});
      const f=document.querySelector('#store-return-policy-form');f.reset();f.elements.store_slug.value=r.store_slug||'';
      f.elements.enabled.checked=!!r.return_policy.enabled;f.elements.days.value=r.return_policy.return_window_days||30;
      f.elements.payer.value=r.return_policy.charge_bearer||'RETAILER_PAY';f.elements.cap.value=r.return_policy.maximum_price||'10.00';
      document.querySelector('#store-return-policy-result').textContent=r.store_slug?new URL('/returns/'+r.store_slug,location.origin).href:'';
      document.querySelector('#store-return-policy').showModal();
    });
  });
  document.querySelector('#store-return-policy-form').addEventListener('submit',event=>{
    event.preventDefault();busy(event.target.querySelector('button'),async()=>{
      const f=event.target.elements;
      const r=await api('/api/v1/workspace/stores/'+portalStore+'/returns-portal',{method:'PUT',auth:true,body:{
        store_slug:f.store_slug.value,return_policy:{enabled:f.enabled.checked,return_window_days:Number(f.days.value),
          charge_bearer:f.payer.value,maximum_price:f.cap.value,currency:'GBP',allowed_countries:['GB'],paperless_requested:true}}});
      const url=new URL(r.portal_path,location.origin).href;
      document.querySelector('#store-return-policy-result').textContent=url;
      try {await navigator.clipboard.writeText(url);notify('Portal URL copied.');}catch{notify('Policy saved. Copy the portal URL shown.');}
    });
  });
  fetch('/api/v1/integration/platforms').then(r=>{if(!r.ok)throw Error();return r.json();}).then(({platforms})=>{
    const previousGuides=new Map(storePlatforms.filter(p=>['SHOPIFY','WOOCOMMERCE','AMAZON'].includes(p.code)).map(p=>[p.code,p]));
    storePlatforms.splice(0,storePlatforms.length,...platforms.map(p=>({...p,mark:p.name.slice(0,2),color:'#d1fae5',mode:p.setup_mode,
      url:previousGuides.get(p.code)?.url||'/help/supported-platforms',steps:previousGuides.get(p.code)?.steps||[p.intake,'Register the store, then save authorized credentials in Connection settings.',
        p.setup_mode==='API_BRIDGE'?'Use a developer or middleware to send signed normalized orders. This is not native platform OAuth or native webhook authentication.':'Use Test connection to verify read access. Retrieve orders or configure signed notifications.',
        'Review packing and quotes before booking. Configure an explicit return policy before sharing the public portal.']})));
    const select=document.querySelector('#store-admin-form [name=platform]');
    if(select){select.replaceChildren();platforms.forEach(p=>select.add(new Option(p.name,p.code)));}
    renderStoreCatalogue();if(typeof renderEnterpriseStores==='function')renderEnterpriseStores();
  }).catch(()=>notify('Platform directory unavailable. Existing store setup remains available.'));
})();
