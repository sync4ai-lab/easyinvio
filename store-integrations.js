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

  const connectionDialog=document.querySelector('#store-connection');
  const secret=form.elements.webhook_secret;
  const secretLabel=secret.closest('label');
  secretLabel.insertAdjacentHTML('beforeend',`<span class="toolbar"><button class="secondary" type="button" id="store-generate-secret">Generate strong secret</button><button class="secondary" type="button" data-copy-field="webhook_secret">Copy secret</button></span><small id="store-secret-help">Copy before saving. Saved secrets are encrypted and cannot be displayed again.</small>`);
  form.insertAdjacentHTML('afterbegin',`<section id="store-quick-credentials" class="card" aria-labelledby="store-quick-title"><h3 id="store-quick-title">Quick credentials</h3>
    <label>Store ID<input name="display_store_id" readonly></label><button class="secondary" type="button" data-copy-field="display_store_id">Copy Store ID</button>
    <label>Key ID<input name="display_key_id" readonly></label><button class="secondary" type="button" data-copy-field="display_key_id">Copy Key ID</button>
    <p id="store-key-help"></p><label>Signed order intake URL<input name="display_intake_url" readonly></label><button class="secondary" type="button" data-copy-field="display_intake_url">Copy intake URL</button>
    <ol><li>Save your website origin and copy your credentials securely.</li><li>Ask your developer or middleware provider to send signed orders using our guide.</li><li>Verify an order in the inbox, then review rates before buying a label.</li></ol><a href="/help/connect-custom-website">Open the step-by-step API guide</a></section>
    <section id="store-portal-shortcut" class="card"><h3>Hosted returns portal</h3><p>Choose your return window, payer and spending limit before enabling returns.</p>
    <label>Returns portal URL<input name="display_return_url" readonly></label><button class="secondary" type="button" data-copy-field="display_return_url">Copy return link for your website</button>
    <button class="secondary" type="button" id="store-open-portal">Enable / configure hosted returns portal</button><p id="store-portal-hint" role="status"></p></section>`);
  let connectionGeneration=0;
  async function copyValue(value,button){
    if(!value){notify('Save or configure this connection first.');return;}
    try{await navigator.clipboard.writeText(value);notify('Copied.');}
    catch{notify('Clipboard unavailable. Select the field and copy it manually.');}
  }
  form.addEventListener('click',event=>{
    const button=event.target.closest('[data-copy-field]');
    if(button)copyValue(form.elements[button.dataset.copyField].value,button);
  });
  document.querySelector('#store-generate-secret').onclick=()=>{
    if(secret.dataset.saved==='true'&&!window.confirm('Replace the saved signing secret? Update the same secret on your website or webhook sender after saving.'))return;
    const bytes=crypto.getRandomValues(new Uint8Array(32));
    secret.value=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    secret.type='text';notify('Strong secret generated. Copy it securely before saving.');
  };
  connectionDialog.addEventListener('close',()=>{
    connectionGeneration++;form.reset();secret.type='password';
    form.querySelectorAll('input[type=password]').forEach(input=>input.value='');
    secret.value='';
  });
  function rename(name,text){
    const label=form.elements[name].closest('label');
    let title=label.querySelector('[data-field-title]');
    if(!title){title=document.createElement('span');title.dataset.fieldTitle='';
      for(const node of [...label.childNodes])if(node.nodeType===Node.TEXT_NODE)node.remove();
      label.prepend(title);}
    title.textContent=text;
  }
  window.configureStoreConnectionUI=async(store,config)=>{
    const generation=++connectionGeneration;
    const code=store.platform,bridge=code==='CUSTOM_WEBSITE'||storePlatforms.find(p=>p.code===code)?.setup_mode==='API_BRIDGE';
    const nativeRest=['WOOCOMMERCE','EBAY','BIGCOMMERCE','WIX','MAGENTO'].includes(code);
    const visibility={store_url:bridge||['WOOCOMMERCE','MAGENTO'].includes(code),
      external_store_id:['BIGCOMMERCE','WIX'].includes(code),tracking_callback_url:bridge,
      rest_access_token:['EBAY','BIGCOMMERCE','WIX','MAGENTO'].includes(code),
      woo_key:code==='WOOCOMMERCE',woo_secret:code==='WOOCOMMERCE',
      weights:!bridge,live_returns:['SHOPIFY','WOOCOMMERCE','AMAZON'].includes(code),
      live_import:nativeRest||code==='SHOPIFY',live_delivery:code!=='AMAZON'};
    for(const [name,visible] of Object.entries(visibility))form.elements[name].closest('label').hidden=!visible;
    form.querySelectorAll('[data-shopify]').forEach(node=>node.hidden=code!=='SHOPIFY');
    // Read-only retrieval is shared by native REST adapters, not Shopify-only.
    form.elements.live_import.closest('label').hidden=!visibility.live_import;
    form.elements.live_delivery.checked=code!=='AMAZON'&&!!config.live_delivery;
    form.elements.live_delivery.disabled=code==='AMAZON';
    const authorizationFields=()=>{
      const token=form.elements.authorization_mode.value==='TOKEN';
      form.elements.access_token.closest('label').hidden=code!=='SHOPIFY'||!token;
      for(const name of ['client_id','client_secret'])form.elements[name].closest('label').hidden=code!=='SHOPIFY'||token;
    };
    form.elements.authorization_mode.onchange=authorizationFields;authorizationFields();
    const weightsHelp=form.elements.weights.closest('label').nextElementSibling;
    if(weightsHelp?.tagName==='P')weightsHelp.hidden=bridge;
    document.querySelector('#store-quick-credentials').hidden=!bridge;
    document.querySelector('#store-secret-label').textContent=code==='AMAZON'?'AWS API-destination authentication key':bridge?'Signing secret':code==='WOOCOMMERCE'?'WooCommerce webhook secret':'Webhook signing secret';
    secretLabel.hidden=!(bridge||['SHOPIFY','WOOCOMMERCE','AMAZON'].includes(code));
    secret.dataset.saved=String(!!config.has_webhook_secret);secret.type='password';
    document.querySelector('#store-secret-help').textContent=config.has_webhook_secret?
      'A secret is already saved. Leave blank to keep it. Replacing it requires updating your webhook sender too.':
      bridge?'Generate and copy a secret, or leave blank for a server-generated one-time secret after saving. Never put it in browser code.':
      code==='AMAZON'?'Use the same authentication value configured for your AWS API destination.':
      'Use the same secret in your platform webhook settings. Copy generated secrets before saving.';
    form.elements.display_store_id.value=store.id;
    form.elements.display_key_id.value=config.api_key_id||'';
    document.querySelector('#store-key-help').textContent=config.api_key_id?'Use this Key ID with your server-side signing secret.':'Your Key ID will be assigned when you save this connection.';
    form.elements.display_intake_url.value=new URL('/api/v1/integration/custom-store/orders',location.origin).href;
    rename('external_store_id',code==='WIX'?'Wix site ID':'BigCommerce store hash');
    rename('rest_access_token',code==='EBAY'?'eBay seller access token':code==='BIGCOMMERCE'?'BigCommerce API access token':code==='WIX'?'Wix authorized API token':'Magento integration access token');
    rename('store_url',code==='WOOCOMMERCE'?'WooCommerce HTTPS store origin':code==='MAGENTO'?'Magento HTTPS store origin':'Website HTTPS origin');
    document.querySelector('#store-webhook-path').hidden=bridge||!['SHOPIFY','WOOCOMMERCE','AMAZON'].includes(code);
    document.querySelector('#store-open-portal').dataset.storePortal=store.id;
    form.elements.display_return_url.value='';
    document.querySelector('#store-portal-hint').textContent='Loading return policy…';
    try{
      const policy=await api('/api/v1/workspace/stores/'+encodeURIComponent(store.id)+'/returns-portal',{auth:true});
      if(generation!==connectionGeneration)return;
      form.elements.display_return_url.value=policy.store_slug?new URL('/returns/'+policy.store_slug,location.origin).href:'';
      document.querySelector('#store-portal-hint').textContent=policy.return_policy.enabled?'Hosted returns are enabled under your saved policy.':'Hosted returns are disabled. Configure and authorize your policy to enable them.';
    }catch{if(generation===connectionGeneration)document.querySelector('#store-portal-hint').textContent='Return policy unavailable. Check migration 057 and your workspace access.';}
  };
  document.body.insertAdjacentHTML('beforeend',`<dialog id="store-machine-secret"><button class="secondary" type="button" data-close-machine>Close</button><h2>Store machine credentials</h2>
    <p>Copy the signing secret now. It will not be displayed again. Rotation invalidates previous signatures.</p>
    <label>Key ID<input id="store-machine-key" readonly></label><label>Signing secret<input id="store-machine-value" readonly type="password"></label>
    <button class="secondary" type="button" id="store-machine-copy">Copy credentials</button></dialog>
    <dialog id="store-return-policy"><button class="secondary" type="button" data-close-portal>Close</button><h2>Public returns portal</h2>
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

  // Shared local brand geometry is identical on public and authenticated cards.
  const logoCatalogue={"SHOPIFY": {"viewBox": "0.7280003118515015 -0.7200001192092895 22.54499954223633 25.44", "plate": false}, "WOOCOMMERCE": {"viewBox": "-0.7200109165542744 8.8599995803833 25.440012130737305 6.280001792907715", "plate": false}, "AMAZON": {"viewBox": "-0.7200024265050888 0.38200089454650876 25.44000202178955 23.236699638366698", "plate": false}, "CUSTOM_WEBSITE": {"viewBox": "2.8 5.8 42.4 36.4", "plate": false}, "EBAY": {"viewBox": "-0.72 6.491999893188477 25.44 11.01600212097168", "plate": false}, "ETSY": {"viewBox": "0.8009999084472657 -0.72 22.39800018310547 25.44", "plate": false}, "TIKTOK_SHOP": {"viewBox": "0.8540861511230469 -0.7200090980529785 22.290922660827636 25.440321464538574", "plate": false}, "BIGCOMMERCE": {"viewBox": "-0.7200466719269752 -0.7201974791288376 25.43997978210449 25.439195861816405", "plate": false}, "WIX": {"viewBox": "-0.72 6.633000164031983 25.44 10.733001174926757", "plate": false}, "SQUARESPACE": {"viewBox": "-0.7199896955490112 1.734010181427002 25.43964012145996 20.531229095458983", "plate": false}, "MAGENTO": {"viewBox": "0.8889999675750733 -0.72 22.22200149536133 25.44", "plate": false}, "PRESTASHOP": {"viewBox": "-0.72 0.314000039100647 25.44 23.37045234680176", "plate": false}, "SHOPWARE": {"viewBox": "-0.720000057220459 -0.7178000572323799 25.44000202178955 25.43559986114502", "plate": false}, "ECWID": {"viewBox": "-47.99999237060547 -48.00001811981201 1696 572.8000183105469", "plate": false}, "SQUARE": {"viewBox": "-0.72 -0.7200000000000285 25.44 25.44", "plate": false}, "WEEBLY": {"viewBox": "-2.1438677978515623 -2.9019854736328123 107.46028198242188 36.791885986328126", "plate": false}, "OPENCART": {"viewBox": "-15.36 -14.895999298095703 542.72 130.25601837158203", "plate": false}, "ONBUY": {"viewBox": "66.80178436279297 142.9321859741211 426.3960955810547 114.1355517578125", "plate": false}, "MANOMANO": {"viewBox": "0 200 548 150", "plate": true}, "MIRAKL": {"viewBox": "-3.033479922460392 -3.0334799194335935 107.18295715332032 26.086826782226563", "plate": false}, "KAUFLAND": {"viewBox": "-0.72 -0.72 25.44 25.44", "plate": false}, "LINNWORKS": {"viewBox": "0 0 100 100", "plate": true}, "CHANNELENGINE": {"viewBox": "-49.14603777647018 -50.055949706652896 1768.6521826171875 353.9021368408203", "plate": false}, "CSV_SFTP": {"viewBox": "2.8 5.8 42.4 36.4", "plate": false}, "ROYAL_MAIL": {"viewBox": "-1.14 -1.14 40.28 26.28", "plate": false}, "EVRI": {"viewBox": "-1.14 -1.14 40.28 26.28", "plate": false}, "DPD": {"viewBox": "0.9819885730743408 -0.7202190950862132 22.03602523803711 25.440400314331054", "plate": false}, "DHL": {"viewBox": "-0.72 9.583000450134277 25.44 4.835000457763671", "plate": false}, "UPS": {"viewBox": "1.1600020217895508 -0.72 21.679999771118165 25.44", "plate": false}};
  const renderCatalogueBeforeLogos=renderStoreCatalogue;
  renderStoreCatalogue=function(){renderCatalogueBeforeLogos();
    document.querySelectorAll('#store-catalogue [data-store-connect]').forEach(button=>{
      const mark=button.closest('article').querySelector('.toolbar > span'),entry=logoCatalogue[button.dataset.storeConnect];
      if(!mark||!entry)return;
      mark.style.cssText='display:flex;align-items:center;width:120px;height:46px;padding:4px;border-radius:8px;background:'+(entry.plate?'#fff':'transparent');
      mark.innerHTML='<svg style="width:100%;height:100%" aria-hidden="true" viewBox="'+entry.viewBox+'"><use href="/platform-logos.svg#'+button.dataset.storeConnect+'"></use></svg>';
    });
  };
  renderStoreCatalogue();
  // Store-scoped branding and notification policy. No recipient permission is
  // inferred from a merchant enabling a channel.
  document.body.insertAdjacentHTML('beforeend',`<dialog id="store-post-purchase"><button type="button" class="close" aria-label="Close branding settings">×</button><h2>Tracking branding & buyer updates</h2><form id="store-post-purchase-form">
    <label>Store name on tracking pages<input name="brand_display_name" maxlength="100"></label>
    <label>Logo HTTPS URL<input name="brand_logo_url" type="url" maxlength="2048"></label>
    <label>Brand accent<input name="brand_accent_hex" type="color" value="#059669"></label>
    <label>Customer support HTTPS URL<input name="support_url" type="url" maxlength="2048"></label>
    <fieldset><legend>Buyer milestone notifications</legend><label><input type="checkbox" name="buyer_email"> Enable buyer email updates</label><label><input type="checkbox" name="buyer_whatsapp"> Enable buyer WhatsApp updates</label>
    <p>Only recipients who have explicitly agreed receive future updates. Sender preferences stay separate. WhatsApp uses an approved SHIPMENT template and your normal provider charges.</p>
    <label><input type="checkbox" name="category" value="IN_TRANSIT" checked> In transit</label><label><input type="checkbox" name="category" value="OUT_FOR_DELIVERY" checked> Out for delivery</label><label><input type="checkbox" name="category" value="AVAILABLE_FOR_PICKUP" checked> Ready for pickup</label><label><input type="checkbox" name="category" value="DELIVERED" checked> Delivered</label><label><input type="checkbox" name="category" value="EXCEPTION" checked> Delivery issue</label></fieldset>
    <p>Delivery also requires SHIPMENT_RECIPIENT_NOTIFICATIONS_ENABLED and configured email/WhatsApp channels. This form does not send messages or create historical notifications.</p><button type="submit" class="primary">Save branding and policy</button><p role="status"></p></form></dialog>`);
  const presentationDialog=document.querySelector('#store-post-purchase'),presentationForm=document.querySelector('#store-post-purchase-form');
  let presentationStore=null,presentationGeneration=0;
  presentationDialog.querySelector('.close').onclick=()=>presentationDialog.close();
  presentationDialog.addEventListener('close',()=>{presentationStore=null;presentationGeneration++;presentationForm.reset();});
  const storesBeforePresentation=renderEnterpriseStores;
  renderEnterpriseStores=function(){storesBeforePresentation();if(!storeCanManage())return;
    document.querySelectorAll('#store-list [data-store-settings]').forEach(button=>{
      const extra=document.createElement('button');extra.type='button';extra.className='secondary';extra.dataset.storePresentation=button.dataset.storeSettings;extra.textContent='Tracking branding & buyer updates';button.parentElement.append(extra);
    });
  };
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-store-presentation]');if(!button)return;
    busy(button,async()=>{
      const generation=++presentationGeneration,storeId=button.dataset.storePresentation;
      const value=await api('/api/v1/workspace/stores/'+storeId+'/post-purchase',{auth:true});
      if(generation!==presentationGeneration)return;
      presentationStore=storeId;presentationForm.reset();
      for(const name of ['brand_display_name','brand_logo_url','support_url'])presentationForm.elements[name].value=value[name]||'';
      presentationForm.elements.brand_accent_hex.value=value.brand_accent_hex||'#059669';
      const policy=value.buyer_notification_policy||{};presentationForm.elements.buyer_email.checked=!!policy.email;presentationForm.elements.buyer_whatsapp.checked=!!policy.whatsapp;
      presentationForm.querySelectorAll('[name=category]').forEach(input=>input.checked=(policy.categories||[]).includes(input.value));
      presentationForm.querySelector('[role=status]').textContent='';presentationDialog.showModal();
    });
  });
  presentationForm.onsubmit=event=>{
    event.preventDefault();busy(presentationForm.querySelector('[type=submit]'),async()=>{
      const f=presentationForm.elements;
      await api('/api/v1/workspace/stores/'+presentationStore+'/post-purchase',{method:'PUT',auth:true,body:{
        brand_display_name:f.brand_display_name.value.trim()||null,brand_logo_url:f.brand_logo_url.value.trim()||null,
        brand_accent_hex:f.brand_accent_hex.value,support_url:f.support_url.value.trim()||null,
        buyer_notification_policy:{email:f.buyer_email.checked,whatsapp:f.buyer_whatsapp.checked,categories:[...presentationForm.querySelectorAll('[name=category]:checked')].map(input=>input.value)}}});
      presentationForm.querySelector('[role=status]').textContent='Saved. Recipient permission and configured delivery channels are still required.';
    });
  };
  window.addEventListener('easyinvio-session-ready',()=>{presentationDialog.close();presentationStore=null;presentationGeneration++;});
  document.addEventListener('click',event=>{if(event.target.closest('#identity-logout,#signout-btn')){presentationDialog.close();presentationStore=null;presentationGeneration++;}},true);
})();
