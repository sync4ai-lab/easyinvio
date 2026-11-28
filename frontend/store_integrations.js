// Embedded in index.html: merchant connection catalogue, retrieval and helpdesk.
const storePlatforms = [
 {code:'SHOPIFY',name:'Shopify',mark:'S',color:'#95bf47',mode:'Order retrieval',url:'https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens',steps:['Install an app with read_orders access and the required customer-data permissions. New apps use Shopify Dev Dashboard; legacy Admin custom apps may have an existing Admin API token.','For an app and store in your own Shopify organization, use the app Client ID and Client secret. For other merchants, obtain an authorized Admin API access token through the appropriate Shopify installation flow; contact us for managed onboarding.','Save the canonical your-store.myshopify.com hostname below. Add verified unit weights for your product SKUs. Retrieve orders, then open Marketplace Workspace to pack and compare shipping options. Tokens must be refreshed when they expire.']},
 {code:'WOOCOMMERCE',name:'WooCommerce',mark:'woo',color:'#a78bfa',mode:'Signed order webhooks',url:'https://woocommerce.com/document/webhooks/',steps:['Register your store here. In WooCommerce → Settings → Advanced → Webhooks, create an Order created webhook using JSON.','Use a public HTTPS EasyInvio backend address followed by /api/v1/integration/webhooks/<store UUID>. Choose a strong webhook secret and save the identical secret in this store’s connection settings.','Add verified SKU unit weights in grams. Activate the webhook and check its delivery log. Imported orders appear in Marketplace Workspace. Remote order polling and fulfillment write-back are not available for this platform yet.']},
 {code:'AMAZON',name:'Amazon',mark:'a',color:'#ff9900',mode:'AWS order intake',url:'https://developer-docs.amazon.com/sp-api/docs/onboarding-overview',steps:['Authorize your Amazon Selling Partner API app for Orders API access and shipping-address permissions. Save the seller ID, marketplace IDs, app credentials and refresh token in encrypted connection settings.','Subscribe to ORDER_CHANGE notifications with an Amazon SQS destination. Use EventBridge Pipes with SQS batch size 1 and an input transformer forwarding the original notification body to an API destination. Configure it to POST the original notification JSON to /api/v1/integrations/ecommerce/orders-sync?store_id=<store UUID>, using a public HTTPS EasyInvio origin.','Configure the AWS API destination API-key header x-easyinvio-amazon-key using the same strong key saved as the webhook secret here. The receiver durably queues notifications and retrieves current authorized order details through Orders API v2026-01-01. Only merchant-fulfilled, wholly unshipped orders with verified SKU weights are imported.']},
 {code:'EBAY',name:'eBay',mark:'ebay',color:'#60a5fa',mode:'Assisted setup',url:'https://developer.ebay.com/api-docs/sell/fulfillment/overview.html',steps:['Order access uses eBay seller authorization and the Fulfillment API.','Contact support with your marketplace and expected order volume.','An eBay order adapter and OAuth onboarding are still required. This catalogue entry provides guidance, not an active connection.']},
 {code:'BIGCOMMERCE',name:'BigCommerce',mark:'B',color:'#c4b5fd',mode:'Assisted setup',url:'https://developer.bigcommerce.com/docs/start/authentication',steps:['BigCommerce uses store-level API accounts or app OAuth with approved scopes.','Contact support to plan read-only order access and fulfillment updates.','A BigCommerce adapter is required before orders can be retrieved into EasyInvio. Do not share API credentials by email.']},
 {code:'PRESTASHOP',name:'PrestaShop',mark:'P',color:'#f472b6',mode:'Assisted setup',url:'https://devdocs.prestashop-project.org/9/webservice/tutorials/creating-access/',steps:['PrestaShop exposes orders through its Webservice API, enabled by a store administrator with resource permissions.','Contact support with your PrestaShop version and store URL.','A PrestaShop adapter is still required. Credentials alone will not activate order retrieval.']}
];
const storePanel = $('#stores');
storePanel.querySelector('h1').textContent = 'Connect your sales channels';
storePanel.querySelector('.pagehead p').textContent = 'Bring orders into one workspace. Review packing and shipping rates before buying labels.';
storePanel.querySelector('.notice').textContent = 'Registering names your store. Connecting authorizes order access. Retrieval imports orders without purchasing labels.';
$('#store-new').textContent = 'Register another store';
storePanel.querySelector('#store-list').insertAdjacentHTML('beforebegin', `<div class="toolbar"><input id="store-search" type="search" placeholder="Find a platform" aria-label="Find a store platform"></div><div id="store-catalogue" class="provider-grid"></div><h2 style="margin-top:28px">Your workspace stores</h2><p id="store-sync-result" class="notice" role="status" hidden></p>`);
document.body.insertAdjacentHTML('beforeend', `<dialog id="store-guide"><button class="close" aria-label="Close connection guide">×</button><h2 id="store-guide-title"></h2><ol id="store-guide-steps"></ol><p><a id="store-guide-docs" target="_blank" rel="noopener noreferrer">Official platform documentation ↗</a></p><a href="mailto:support@easyinvio.com">Ask EasyInvio support</a></dialog>
<dialog id="store-connection"><button class="close" aria-label="Close connection setup">×</button><h2 id="store-connection-title">Connect store</h2><p class="notice">Credentials are encrypted on the server and never displayed after saving. Blank secret fields retain existing credentials.</p><form id="store-connection-form">
<label data-shopify>Shopify store hostname<input name="shop_domain" placeholder="your-store.myshopify.com" maxlength="200"></label>
<fieldset data-shopify><legend>Authorization</legend><label>Connection method<select name="authorization_mode"><option value="TOKEN">Authorized Admin API access token</option><option value="CLIENT_CREDENTIALS">App credentials (same Shopify organization)</option></select></label><p class="subtle">Use an authorized Admin API access token, or app credentials for a store in your own Shopify organization.</p><label>Admin API access token<input type="password" name="access_token" autocomplete="new-password"></label><label>App Client ID<input name="client_id" maxlength="200"></label><label>App Client secret<input type="password" name="client_secret" autocomplete="new-password"></label></fieldset>
<fieldset data-amazon hidden><legend>Amazon seller authorization</legend><label>SP-API region<select name="amazon_region"><option value="eu">Europe / UK</option><option value="na">North America</option><option value="fe">Far East</option></select></label><label>Seller ID<input name="amazon_seller_id" maxlength="100"></label><label>Marketplace IDs ? comma separated<input name="amazon_marketplace_ids" maxlength="1000"></label><label>App Client ID<input name="amazon_client_id" maxlength="200"></label><label>App Client secret<input type="password" name="amazon_client_secret" autocomplete="new-password"></label><label>Seller refresh token<input type="password" name="amazon_refresh_token" autocomplete="new-password"></label></fieldset><label>Webhook signing secret / AWS API-destination key (optional for Shopify retrieval)<input name="webhook_secret" type="password" autocomplete="new-password" minlength="32"></label>
<label>Verified product weights · SKU = unit grams<textarea name="weights" rows="5" placeholder="TEE-BLUE = 200&#10;MUG-WHITE = 350"></textarea></label><p class="subtle">Use measured unit weights, not package dimensions. Missing SKU weights are flagged for review; no weight is invented.</p>
<label class="check" data-shopify><input type="checkbox" name="live_import" checked>Enable read-only order retrieval</label><p id="store-webhook-path" class="notice"></p><button class="primary full">Save encrypted connection</button></form></dialog>
<dialog id="store-help"><button class="close" aria-label="Close support form">×</button><h2>Contact EasyInvio support</h2><p>support@easyinvio.com</p><form id="store-help-form"><label>Support topic<select name="topic"><option>Store connection</option><option>Order import</option><option>Labels and tracking</option><option>Wallet and billing</option><option>Account access</option><option>Other</option></select></label><label>Platform or order reference (optional)<input name="reference" maxlength="200"></label><label>How can we help?<textarea name="message" required minlength="10" maxlength="3000" rows="5" placeholder="Describe what you expected and what happened. Do not include passwords, API keys or payment details."></textarea></label><button class="primary full">Open email draft</button><p class="footnote">This opens your email app. Review and send the email there; EasyInvio does not send it automatically.</p></form></dialog>`);
storePanel.insertAdjacentHTML('beforeend', '<p style="margin-top:20px"><a href="/help">Visit the EasyInvio Help Centre</a> for account, payment and store guidance.</p>');
storePanel.insertAdjacentHTML('beforeend', '<article class="card" style="margin-top:24px"><h2>Need a hand connecting?</h2><p>Our team can help with authorization, order imports and supported platforms.</p><button class="secondary" data-store-help>Contact support</button> <a href="mailto:support@easyinvio.com">support@easyinvio.com</a></article>');
function renderStoreCatalogue() {
 const search = $('#store-search').value.trim().toLowerCase();
 $('#store-catalogue').innerHTML = storePlatforms.filter(p=>p.name.toLowerCase().includes(search)).map(p=>`<article class="card"><div class="toolbar"><span aria-hidden="true" style="display:inline-grid;place-items:center;width:54px;height:54px;border-radius:14px;background:${p.color};color:#101827;font-size:24px;font-weight:900">${p.mark}</span><h2>${p.name}</h2></div><span class="tag">${p.mode}</span><p class="subtle">${p.code==='SHOPIFY'?'Retrieve unfulfilled orders through the Shopify API.':p.code==='WOOCOMMERCE'?'Import orders through authenticated WooCommerce webhooks.':p.code==='AMAZON'?'Receive authorized AWS order notifications and retrieve order details.':'Talk to us about connecting your store.'}</p><div class="toolbar"><button class="primary" data-store-connect="${p.code}">${['SHOPIFY','WOOCOMMERCE','AMAZON'].includes(p.code)?'Connect store':'Request integration'}</button><button class="secondary" data-store-guide="${p.code}">How to connect</button></div><button class="secondary" data-store-help="${p.name}" style="margin-top:12px">Support</button></article>`).join('') || '<p class="notice">No matching platform. Contact support for another sales channel.</p>';
}
$('#store-search').addEventListener('input', renderStoreCatalogue);
renderStoreCatalogue();
let storeConnectionId = null,storeConnectionGeneration=0;
$('#store-connection').addEventListener('close',()=>{storeConnectionGeneration++;});
function storeCanManage(){ return !state.session || ['OWNER','ADMIN'].includes(portal.profile?.workspace_role); }
renderEnterpriseStores = function() {
 $('#store-new').hidden = !storeCanManage();
 $('#store-list').innerHTML = enterprise.stores.map(s=>`<article class="card"><span class="tag">${escapeHTML(s.platform)}</span><h2>${escapeHTML(s.display_name)}</h2><p class="subtle">${s.is_active?'Registered · connection required for imports':'Disabled · new imports stopped'}</p><div class="toolbar">${storeCanManage()&&['SHOPIFY','WOOCOMMERCE','AMAZON'].includes(s.platform)?`<button class="primary" data-store-settings="${escapeHTML(s.id)}">Connection settings</button>`:''}${s.is_active&&s.platform==='SHOPIFY'&&storeCanManage()?`<button class="secondary" data-store-sync="${escapeHTML(s.id)}">Retrieve orders</button>`:''}${s.platform==='AMAZON'&&storeCanManage()?`<button class="secondary" data-store-notifications="${escapeHTML(s.id)}">Import activity</button>`:''}<button class="secondary" data-open-marketplace>Open order inbox</button></div>${storeCanManage()?`<button class="secondary full" data-store-state="${escapeHTML(s.id)}" style="margin-top:12px">${s.is_active?'Disable':'Enable'} store</button>`:''}</article>`).join('') || '<p class="notice">No stores registered yet. Choose a platform above to get started.</p>';
};
document.addEventListener('click', event=>{
 const button=event.target.closest('[data-store-guide],[data-store-help],[data-store-connect],[data-store-settings],[data-store-sync],[data-open-marketplace]'); if(!button)return;
 if(button.hasAttribute('data-open-marketplace')) { if(!allowedEnterpriseViews().includes('workspace')){notify('An owner or dispatcher can prepare imported orders.');return;}setView('workspace');return; }
 if(button.hasAttribute('data-store-guide')){
  const p=storePlatforms.find(p=>p.code===button.dataset.storeGuide);$('#store-guide-title').textContent='Connect '+p.name;$('#store-guide-steps').innerHTML=p.steps.map(s=>`<li style="margin-bottom:16px">${escapeHTML(s)}</li>`).join('');$('#store-guide-docs').href=p.url;$('#store-guide').showModal();return;
 }
 if(button.hasAttribute('data-store-help')||button.hasAttribute('data-store-connect')&&!['SHOPIFY','WOOCOMMERCE','AMAZON'].includes(button.dataset.storeConnect)){
  $('#store-help-form').reset();$('#store-help-form').elements.reference.value=button.dataset.storeHelp||button.dataset.storeConnect||'';$('#store-help').showModal();return;
 }
 if(button.hasAttribute('data-store-connect')){
  if(!storeCanManage()){notify('Ask your workspace owner to connect a store.');return;}$('#store-admin-form').reset();$('#store-admin-form').elements.platform.value=button.dataset.storeConnect;$('#store-admin-dialog').showModal();return;
 }
 busy(button,async()=>{
  if(!state.session)throw Error('Sign in as a workspace owner to connect or retrieve actual orders.');
  const id=button.dataset.storeSettings||button.dataset.storeSync;
  if(button.hasAttribute('data-store-settings')){await openStoreConnection(id);
  }else{
   const result=await api('/api/v1/dispatch-workspace/sync/'+id,{method:'POST',auth:true});const results=result.results||[];const node=$('#store-sync-result');node.hidden=false;node.textContent=result.notice||`${results.filter(r=>r.status!=='REVIEW_REQUIRED'&&!r.replayed).length} new orders imported · ${results.filter(r=>r.replayed).length} already imported · ${results.filter(r=>r.status==='REVIEW_REQUIRED').length} need address or SKU-weight review.${result.more_available?' More orders remain; continue in Marketplace Workspace.':''}`;notify(node.textContent);if(results.length)setView('workspace');
  }
 });
});
$('#store-connection-form').insertAdjacentHTML('beforeend','<p id="store-connection-status" role="status" aria-live="polite"></p>');
$('#store-connection-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.target.querySelector('button[type=submit]'), async () => {
    const status=$('#store-connection-status');status.textContent='Saving connection…';status.setAttribute('role','status');
    const connectionId=storeConnectionId,generation=storeConnectionGeneration,session=state.session,tenant=portal.profile?.tenant_id;
    const current=()=>generation===storeConnectionGeneration&&connectionId===storeConnectionId&&session===state.session&&tenant===portal.profile?.tenant_id&&$('#store-connection').open;
    try {
    const form = event.target,
      store = enterprise.stores.find(s => s.id === storeConnectionId),
      sku_unit_grams = {};
    for (const line of form.elements.weights.value.split('\n').filter(s => s.trim())) {
      const match = line.match(/^\s*([^=]+?)\s*=\s*(\d+(?:\.\d+)?)\s*$/);
      if (!match || Number(match[2]) <= 0 || Object.hasOwn(sku_unit_grams, match[1].trim())) throw Error('Use one unique SKU = positive unit grams per line.');
      sku_unit_grams[match[1].trim()] = match[2];
    }
    const body = {
      live_import: !!storePlatforms.find(v=>v.code===store.platform)?.order_polling && form.elements.live_import.checked,
      live_delivery:form.elements.live_delivery.checked,
      store_url:form.elements.store_url.value.trim()||null,
      external_store_id:form.elements.external_store_id.value.trim()||null,
      tracking_callback_url:form.elements.tracking_callback_url.value.trim()||null,
      live_returns: form.elements.live_returns.checked,
      sku_unit_grams
    };
    if (store.platform === 'SHOPIFY') {
      body.shop_domain = form.elements.shop_domain.value.trim();
      body.authorization_mode = form.elements.authorization_mode.value;
      for (const n of ['access_token', 'client_id', 'client_secret'])
        if (form.elements[n].value.trim()) body[n] = form.elements[n].value.trim();
    }
    if(store.platform==='WOOCOMMERCE'){
      if(form.elements.woo_key.value.trim())body.client_id=form.elements.woo_key.value.trim();
      if(form.elements.woo_secret.value.trim())body.client_secret=form.elements.woo_secret.value.trim();
    }
    if(store.platform!=='SHOPIFY' && form.elements.rest_access_token.value.trim())body.access_token=form.elements.rest_access_token.value.trim();
    if (store.platform === 'AMAZON') {
      body.amazon_region = form.elements.amazon_region.value;
      body.amazon_seller_id = form.elements.amazon_seller_id.value.trim();
      body.amazon_client_id = form.elements.amazon_client_id.value.trim();
      body.amazon_marketplace_ids = form.elements.amazon_marketplace_ids.value.split(',').map(v => v.trim()).filter(Boolean);
      for (const name of ['amazon_client_secret', 'amazon_refresh_token'])
        if (form.elements[name].value.trim()) body[name] = form.elements[name].value.trim();
    }
    if (form.elements.webhook_secret.value.trim()) body.webhook_secret = form.elements.webhook_secret.value.trim();
    const savedConnection=await api('/api/v1/workspace/stores/' + connectionId + '/connection', {
      method: 'PUT',
      auth: true,
      body
    });
    if(!current())return;
    if(store.platform==='SHOPIFY'){
      // Read-only verification; never imports orders, writes tracking or buys labels.
      for(const field of form.querySelectorAll('input[type=password]'))field.value='';
      form.elements.access_token.required=false;form.elements.client_secret.required=false;
      status.textContent='Connection saved. Verifying Shopify API access…';
      let verified;
      try{verified=await api('/api/v1/workspace/stores/'+connectionId+'/test-connection',{method:'POST',auth:true});}
      catch(error){throw Error('Connection saved, but Shopify verification failed. Check the hostname, app installation, credentials and permissions. '+error.message);}
      if(!current())return;
      if(!verified.verified)throw Error('Connection saved but not verified. Check your Shopify credentials and retry.');
    }
    window.showStoreMachineCredentials?.(savedConnection);
    form.reset();
    $('#store-connection').close();
    await loadEnterpriseView('stores');
    const result=$('#store-sync-result');result.hidden=false;result.textContent=store.platform==='SHOPIFY'?'Shopify read access verified. Retrieve orders to import unfulfilled orders into Marketplace Workspace. Tracking write-back requires the corresponding app permissions.':'Connection saved. Test API access or send a signed request, then check imported orders.';
    notify(result.textContent);
    } catch(error){if(!current())return;status.setAttribute('role','alert');status.textContent=error.message||'Connection could not be saved.';if(!$('#store-connection').open)notify(status.textContent,true);}
  });
});
$('#store-help-form').addEventListener('submit',event=>{event.preventDefault();const data=new FormData(event.target);const subject='EasyInvio support: '+data.get('topic');const body='Platform / reference: '+data.get('reference')+'\n\n'+data.get('message');window.location.href='mailto:support@easyinvio.com?subject='+encodeURIComponent(subject)+'&body='+encodeURIComponent(body);});
for(const id of ['store-guide','store-connection','store-help']){$('#'+id+' .close').addEventListener('click',()=>$('#'+id).close());$('#'+id).addEventListener('close',()=>{if(id==='store-connection'){$('#store-connection-form').reset();storeConnectionId=null;}});}
window.addEventListener('easyinvio-session-ready',()=>{for(const id of ['store-connection','store-help'])$('#'+id).close();});
const storeNavRefreshBase=refreshEnterpriseNavigation;
refreshEnterpriseNavigation=function(...args){const result=storeNavRefreshBase(...args);if(!state.session){$('#store-connection').close();$('#store-help').close();}return result;};

document.body.insertAdjacentHTML('beforeend','<dialog id="store-notifications"><button class="close" aria-label="Close import activity">?</button><h2>Amazon import activity</h2><p class="subtle">Correct connection permissions, SKU weights or addresses before retrying a review item. Existing orders are not imported twice.</p><div id="store-notifications-list"></div></dialog>');
async function loadStoreNotifications(id){
 const data=await api('/api/v1/workspace/stores/'+id+'/notifications',{auth:true});
 $('#store-notifications-list').innerHTML=(data.notifications||[]).map(row=>`<article class="notice"><b>${escapeHTML(row.order_id)} ? ${escapeHTML(row.status)}</b><p>Attempts: ${Number(row.attempts)} ${escapeHTML(row.last_error_code||'')}</p>${row.status==='REVIEW_REQUIRED'?`<button class="secondary" data-notification-retry="${escapeHTML(row.id)}" data-notification-store="${escapeHTML(id)}">Retry after correcting details</button>`:''}</article>`).join('')||'<p class="notice">No Amazon notifications have reached this store. Check your AWS destination delivery logs.</p>';
}
$('#store-notifications .close').addEventListener('click',()=>$('#store-notifications').close());
async function openStoreConnection(id) {
  if(!state.session||!storeCanManage())throw Error('Sign in as a workspace owner to connect a store.');
  const generation=++storeConnectionGeneration;
      const s = enterprise.stores.find(s => s.id === id);
      if(!s)throw Error('Refresh the store list and try again.');
      const session=state.session,tenant=portal.profile?.tenant_id;
      const
        c = await api('/api/v1/workspace/stores/' + id + '/connection', {
          auth: true
        });
      if(generation!==storeConnectionGeneration||session!==state.session||tenant!==portal.profile?.tenant_id)return;
      storeConnectionId = id;
      const form = $('#store-connection-form');
      form.reset();
      form.elements.shop_domain.value = c.shop_domain || '';
      form.elements.client_id.value = c.client_id || '';
      for(const name of ['store_url','external_store_id','tracking_callback_url'])form.elements[name].value=c[name]||'';
      const bridgePlatform=storePlatforms.find(v=>v.code===s.platform)?.setup_mode==='API_BRIDGE'||s.platform==='CUSTOM_WEBSITE';
      for(const [name,visible] of Object.entries({store_url:bridgePlatform||['WOOCOMMERCE','MAGENTO'].includes(s.platform),external_store_id:['BIGCOMMERCE','WIX'].includes(s.platform),tracking_callback_url:bridgePlatform,rest_access_token:['EBAY','BIGCOMMERCE','WIX','MAGENTO'].includes(s.platform),woo_key:s.platform==='WOOCOMMERCE',woo_secret:s.platform==='WOOCOMMERCE'}))form.elements[name].closest('label').hidden=!visible;
      form.elements.live_delivery.disabled=storePlatforms.find(v=>v.code===s.platform)?.tracking_writeback===false;
      form.elements.live_delivery.checked=!!c.live_delivery&&!form.elements.live_delivery.disabled;
      form.elements.live_import.closest('label').hidden=!storePlatforms.find(v=>v.code===s.platform)?.order_polling;
      form.elements.woo_key.value=s.platform==='WOOCOMMERCE'?(c.client_id||''):'';
      form.elements.authorization_mode.value = c.has_client_credentials||(!c.configured&&!c.has_access_token) ? 'CLIENT_CREDENTIALS' : 'TOKEN';
      form.elements.live_import.checked = c.configured ? c.live_import : s.platform==='SHOPIFY';
      form.elements.live_returns.checked = !!c.live_returns;
      form.elements.weights.value = Object.entries(c.sku_unit_grams || {}).map(([sku, g]) => sku + ' = ' + g).join('\n');
      form.querySelectorAll('[data-amazon]').forEach(n => {
        n.hidden = s.platform !== 'AMAZON';
      });
      for (const name of ['amazon_region', 'amazon_seller_id', 'amazon_client_id']) form.elements[name].value = c[name] || (name === 'amazon_region' ? 'eu' : '');
      form.elements.amazon_marketplace_ids.value = (c.amazon_marketplace_ids || []).join(',');
      form.querySelectorAll('[data-shopify]').forEach(n => {
        n.hidden = s.platform !== 'SHOPIFY';
      });
      form.elements.shop_domain.required = s.platform === 'SHOPIFY';
      form.elements.webhook_secret.required = ['WOOCOMMERCE', 'AMAZON'].includes(s.platform) && !c.has_webhook_secret;
      $('#store-connection-title').textContent = 'Connect ' + s.display_name;
      $('#store-webhook-path').textContent = 'Webhook path: /api/v1/integration/webhooks/' + id + ' — use your public HTTPS backend origin, not localhost.';
      $('#store-connection-status').textContent='';
      $('#store-connection').showModal();
      // Optional return-policy loading must not delay the authorization form.
      await window.configureStoreConnectionUI(s, c);
}

document.addEventListener('click',event=>{
 const button=event.target.closest('[data-store-notifications],[data-notification-retry]');if(!button)return;
 busy(button,async()=>{
  const id=button.dataset.storeNotifications||button.dataset.notificationStore;
  if(button.dataset.notificationRetry)await api('/api/v1/workspace/stores/'+id+'/notifications/'+button.dataset.notificationRetry+'/retry',{auth:true,method:'POST'});
  await loadStoreNotifications(id);if(!$('#store-notifications').open)$('#store-notifications').showModal();
 });
});
const notificationNavigationBase=refreshEnterpriseNavigation;
refreshEnterpriseNavigation=function(...args){const result=notificationNavigationBase(...args);if(!state.session){$('#store-notifications').close();$('#store-notifications-list').replaceChildren();}return result;};
