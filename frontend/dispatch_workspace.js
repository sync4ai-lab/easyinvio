// Embedded in index.html: tenant-scoped marketplace preparation and dispatch.
const dispatchWorkspace = {orders: [], selected: new Set(), offset: 0, preparing: null, cursor:null, cursorStore:null};
document.querySelector('main').insertAdjacentHTML('beforeend', `
<section id="workspace" hidden>
 <div class="pagehead"><div><div class="eyebrow">Warehouse operations</div><h1>Marketplace Workspace</h1><p>Import, pack, review customs, quote, then dispatch confirmed orders.</p></div></div>
 <article class="card"><div class="toolbar"><select id="workspace-store" aria-label="Marketplace store"></select><button id="workspace-sync" class="primary">Sync Marketplace Orders</button><button id="workspace-refresh" class="secondary">Refresh inbox</button></div>
 <p id="workspace-notice" class="notice">Signed store webhooks feed this inbox. Connect Shopify under Store Integrations to retrieve orders. No sample orders are presented as live shipments.</p>
 <div class="toolbar"><button id="workspace-quote" class="secondary">Quote selected orders</button><button id="workspace-buy" class="primary">Buy selected labels</button><button id="workspace-pdf" class="secondary">Download unified print PDF</button></div>
 <p class="subtle">Up to 100 selected orders per dispatch run. Review packing and customs for each order first. Supported provider TEST labels can be booked; LIVE purchases and unsupported test facilities remain guarded. The PDF can be opened and printed locally; downloading does not prove physical printing.</p>
 <div class="scrolltable"><table><thead><tr><th>Select</th><th>Order / store</th><th>Stage</th><th>Tracking push-back</th><th>Preparation</th></tr></thead><tbody id="workspace-rows"></tbody></table></div>
 <div class="toolbar"><button id="workspace-prev" class="secondary">Previous 100</button><button id="workspace-next" class="secondary">Next 100</button><span id="workspace-page" class="subtle"></span></div><div id="workspace-results"></div>
 </article>
</section>`);
document.body.insertAdjacentHTML('beforeend', `<dialog id="workspace-pack-dialog">
<button class="close" id="workspace-pack-close" aria-label="Close preparation">×</button><h2>Pack and review marketplace order</h2><p id="workspace-pack-reference"></p>
<form id="workspace-pack-form"><div class="fields">
 <label>Cargo type<select name="cargo_type"><option value="LETTER">Business letter</option><option value="PARCEL">Standard parcel</option><option value="PALLET">Pallet</option><option value="OVERLAND_FREIGHT">Overland freight</option></select></label>
 <label>Packed gross weight (kg)<input name="actual_weight_kg" inputmode="decimal" required></label>
 <label>Length (cm)<input name="length_cm" inputmode="decimal"></label><label>Width (cm)<input name="width_cm" inputmode="decimal"></label><label>Height (cm)<input name="height_cm" inputmode="decimal"></label>
 <label>Stackable<select name="stackable"><option value="false">No</option><option value="true">Yes</option></select></label>
 <label>Customs signer<input name="customs_signer" maxlength="200"></label><label>Postal form<select name="postal_form"><option value="">Commercial invoice</option><option>CN22</option><option>CN23</option></select></label>
 </div><label>Sender address (JSON)<textarea name="origin" rows="5" required></textarea></label><label>Recipient address including phone/state (JSON)<textarea name="destination" rows="5" required></textarea></label>
 <label>Goods (JSON array: description, quantity, unit_value, unit_weight_kg, origin_country, hs_code)<textarea name="items" rows="10" required></textarea></label>
 <p class="notice">HS codes require explicit review. Check each code and provide actual manufacturing origin, unit declared value and net weight. Warehouse dimensions must be measured, not inferred from the storefront. CN22/CN23 printing requires the corresponding carrier-issued form.</p>
 <label class="check"><input name="reviewed" type="checkbox">I have checked the international customs facts and HS codes</label>
 <button class="primary" id="workspace-pack-save">Save preparation & fetch parallel quotes</button>
</form><div id="workspace-pack-result"></div></dialog>`);

async function loadDispatchWorkspace() {
  const generation = state.generation;
  if (!state.session) {
    $('#workspace-notice').textContent = 'Sign in as a dispatcher, client owner or administrator to sync the real tenant inbox. Preview does not import orders or buy labels.';
    $('#workspace-rows').replaceChildren();return;
  }
  const result = await api('/api/v1/dispatch-workspace/orders?offset=' + dispatchWorkspace.offset, {auth:true});
  if (generation !== state.generation) return;
  dispatchWorkspace.orders = result.orders;
  const previous = $('#workspace-store').value;
  $('#workspace-store').innerHTML = result.stores.map(store => `<option value="${escapeHTML(store.id)}">${escapeHTML(store.display_name)} · ${store.polling_enabled?'API polling enabled':'Webhook inbox'}</option>`).join('');
  if (result.stores.some(s => s.id === previous)) $('#workspace-store').value = previous;
  $('#workspace-rows').innerHTML = result.orders.length ? result.orders.map(row => `<tr>
   <td><input type="checkbox" aria-label="Select ${escapeHTML(row.customer_reference)}" data-workspace-select="${escapeHTML(row.id)}" ${dispatchWorkspace.selected.has(row.id)?'checked':''}></td>
   <td><b>${escapeHTML(row.customer_reference)}</b><br>${escapeHTML(row.display_name)} · ${escapeHTML(row.cargo_type)}</td>
   <td><span class="tag">${escapeHTML(row.status)}</span></td><td>${escapeHTML(row.tracking_sync_status || 'Not queued')}</td>
   <td><button class="secondary" data-workspace-pack="${escapeHTML(row.id)}">Review packing / customs</button></td></tr>`).join('') : '<tr><td colspan="5">No imported marketplace orders yet. Configure signed store webhooks or Shopify polling.</td></tr>';
  $('#workspace-prev').disabled = dispatchWorkspace.offset===0;
  $('#workspace-next').disabled = !result.more_available;
  $('#workspace-page').textContent = `Page ${dispatchWorkspace.offset/100+1} · ${dispatchWorkspace.selected.size} selected`;
}
$('#workspace-refresh').addEventListener('click', () => busy($('#workspace-refresh'), loadDispatchWorkspace));
$('#workspace-sync').addEventListener('click', () => busy($('#workspace-sync'), async () => {
  const store = $('#workspace-store').value;
  if (!store) throw Error('Sign in and choose an active registered marketplace store.');
  const cursor=dispatchWorkspace.cursorStore===store?dispatchWorkspace.cursor:null;
  const result = await api('/api/v1/dispatch-workspace/sync/' + store + (cursor?'?after='+encodeURIComponent(cursor):''), {method:'POST', auth:true});
  dispatchWorkspace.cursorStore=store;dispatchWorkspace.cursor=result.next_cursor || null;
  $('#workspace-notice').textContent = result.notice || `${result.results.filter(r=>r.status==='PENDING_IMPORT').length} pending orders received; ${result.results.filter(r=>r.status==='REVIEW_REQUIRED').length} need source-data review. ${result.more_available?'More available: run sync again after preparing this batch.':''}`;
  dispatchWorkspace.offset = 0;await loadDispatchWorkspace();
}));
for (const [id, delta] of [['workspace-prev',-100], ['workspace-next',100]]) {
  $('#'+id).addEventListener('click', () => busy($('#'+id), async () => {dispatchWorkspace.offset=Math.max(0,dispatchWorkspace.offset+delta);await loadDispatchWorkspace();}));
}
document.addEventListener('change', event => {
  const id = event.target.dataset.workspaceSelect;if (!id) return;
  if (event.target.checked && dispatchWorkspace.selected.size>=100) {event.target.checked=false;notify('Select at most 100 orders per run.',true);return;}
  if (event.target.checked) dispatchWorkspace.selected.add(id);else dispatchWorkspace.selected.delete(id);
  $('#workspace-page').textContent = `Page ${dispatchWorkspace.offset/100+1} · ${dispatchWorkspace.selected.size} selected`;
});
document.addEventListener('click', event => {
  const button = event.target.closest('[data-workspace-pack]');if (!button) return;
  busy(button, async () => {
    const result = await api('/api/v1/dispatch-workspace/orders/'+button.dataset.workspacePack, {auth:true});
    dispatchWorkspace.preparing = {id:button.dataset.workspacePack, order:result.order};
    const form = $('#workspace-pack-form');form.reset();
    $('#workspace-pack-reference').textContent = result.order.order_reference + ' · ' + result.status;
    for (const key of ['cargo_type','actual_weight_kg','length_cm','width_cm','height_cm','stackable']) form.elements[key].value = String(result.order.cargo[key] ?? '');
    for (const key of ['origin','destination','items']) form.elements[key].value = JSON.stringify(result.order[key], null, 2);
    form.elements.customs_signer.value = result.order.customs_signer || '';
    form.elements.postal_form.value = result.order.postal_form || '';
    form.elements.reviewed.checked = false;
    $('#workspace-pack-result').replaceChildren();$('#workspace-pack-dialog').showModal();
  });
});
$('#workspace-pack-close').addEventListener('click',()=>$('#workspace-pack-dialog').close());
$('#workspace-pack-form').addEventListener('submit', event => {
  event.preventDefault();busy($('#workspace-pack-save'), async () => {
    if (!dispatchWorkspace.preparing) throw Error('Choose an order first.');
    const form = $('#workspace-pack-form').elements;
    const order = structuredClone(dispatchWorkspace.preparing.order);
    order.cargo = {cargo_type:form.cargo_type.value, actual_weight_kg:form.actual_weight_kg.value, stackable:form.stackable.value==='true'};
    for (const key of ['length_cm','width_cm','height_cm']) order.cargo[key] = form[key].value || null;
    for (const key of ['origin','destination','items']) order[key] = JSON.parse(form[key].value);
    order.customs_signer = form.customs_signer.value || null;
    order.postal_form = form.postal_form.value || null;order.hs_codes_reviewed = form.reviewed.checked;
    const result = await api('/api/v1/dispatch-workspace/orders/'+dispatchWorkspace.preparing.id+'/prepare', {method:'POST',body:order,auth:true});
    $('#workspace-pack-result').textContent = result.status + (result.error?' · '+result.error:' · '+result.all_rates.length+' options evaluated. No label purchased.');
    if (result.status === 'QUOTED' && result.rate?.offer_id) {
      const offerSelect=document.createElement('select');offerSelect.setAttribute('aria-label','Choose prepared carrier offer');
      for (const offer of result.all_rates || [result.rate]) {const option=document.createElement('option');option.value=offer.offer_id;option.textContent=offer.carrier_code+' '+offer.service_code+' - '+money(offer.client_price_ex_tax,offer.currency);offerSelect.append(option);}
      offerSelect.value=result.rate.offer_id;$('#workspace-pack-result').append(offerSelect);
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'primary';
      button.textContent = 'Book prepared offer';
      button.addEventListener('click', () => busy(button, async () => {
        if (!portal.profile?.tenant_id) throw Error('An authenticated workspace is required.');
        if (!confirm('Purchase this prepared shipping offer? Wallet credit will be reserved and captured only after label confirmation.')) return;
        const booked = await api('/api/v1/shipping/confirm-booking', {method:'POST', auth:true,
          body:{offer_id:offerSelect.value,tenant_id:portal.profile.tenant_id}});
        if (booked.status === 'SYNC_PENDING') {
          $('#workspace-pack-result').textContent = 'Label preparation is in progress. Wallet credit is reserved. Refresh the manifest to see the confirmed label; no second purchase is needed.';
          await loadDispatchWorkspace();
          return;
        }
        $('#workspace-pack-result').textContent = 'Label confirmed. Tracking: ' + booked.label.tracking_number;
        const downloadButton = document.createElement('button');
        downloadButton.type='button';downloadButton.className='secondary';downloadButton.textContent='Download shipping label PDF';
        downloadButton.addEventListener('click',()=>busy(downloadButton,()=>downloadPartnerDocument(booked.label.label_url)));
        $('#workspace-pack-result').append(downloadButton);
        for (const form of booked.label.carrier_forms || []) {
          const documentButton=document.createElement('button');documentButton.type='button';documentButton.className='secondary';
          documentButton.textContent='Download '+form.document_type;
          documentButton.addEventListener('click',()=>busy(documentButton,()=>downloadPartnerDocument(form.url)));
          $('#workspace-pack-result').append(documentButton);
        }
        await loadDispatchWorkspace();
      }));
      $('#workspace-pack-result').append(button);
    }

    await loadDispatchWorkspace();
  });
});
function workspaceSelection() {
  const ids = [...dispatchWorkspace.selected];if (!ids.length) throw Error('Select at least one order.');return ids;
}
function renderWorkspaceResults(results) {
  $('#workspace-results').innerHTML = `<h3>Dispatch run results</h3>${results.map(r=>`<p><b>${escapeHTML(r.order_reference||r.shipment_id)}</b> · ${escapeHTML(r.status)} ${escapeHTML(r.error||'')}</p>`).join('')}`;
}
async function processWorkspace(mode) {
  const result = await api('/api/v1/dispatch-workspace/process',{method:'POST',auth:true,body:{shipment_ids:workspaceSelection(),mode}});
  renderWorkspaceResults(result.results);await loadDispatchWorkspace();
  if(mode==='FULFILL') {
    const booked=result.results.filter(row=>row.status==='BOOKED' && row.shipment_id).map(row=>row.shipment_id);
    if(booked.length) {
      try {await downloadWorkspacePDF(booked);notify(booked.length+' labels booked; unified PDF downloaded.');}
      catch(error){notify(booked.length+' labels are booked. PDF not ready: '+error.message,true);}
    }
  }
}
$('#workspace-quote').addEventListener('click',()=>busy($('#workspace-quote'),()=>processWorkspace('QUOTE_ONLY')));
$('#workspace-buy').addEventListener('click',()=>busy($('#workspace-buy'),async()=>{
  workspaceSelection();if (!confirm('Purchase the cheapest eligible carrier label for each selected prepared order? Wallet checks and carrier purchase controls apply.')) return;
  await processWorkspace('FULFILL');
}));
async function downloadWorkspacePDF(ids) {
  if (!state.session) throw Error('Sign in first.');
  const session=state.session;
  const response=await fetch(API+'/api/v1/dispatch-workspace/print-bundle',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+session.access_token},body:JSON.stringify({shipment_ids:ids})});
  if (session!==state.session) throw Error('Session changed.');
  if (!response.ok) {const result=await response.json();throw Error(result.detail||'PDF generation failed.');}
  const blob=await response.blob();if(session!==state.session)throw Error('Session changed.');
  download('easyinvio-dispatch-bundle.pdf',blob,'application/pdf');
}
$('#workspace-pdf').addEventListener('click',()=>busy($('#workspace-pdf'),()=>downloadWorkspacePDF(workspaceSelection())));
const workspaceClearBase=clearSession;
clearSession=function(){dispatchWorkspace.orders=[];dispatchWorkspace.selected.clear();dispatchWorkspace.preparing=null;dispatchWorkspace.offset=0;dispatchWorkspace.cursor=null;dispatchWorkspace.cursorStore=null;$('#workspace-pack-dialog').close();$('#workspace-pack-form').reset();$('#workspace-rows').replaceChildren();$('#workspace-results').replaceChildren();$('#workspace-store').replaceChildren();workspaceClearBase();};

async function downloadPartnerDocument(path) {
  if (!state.session || !/^\/api\/v1\/shipping\/[0-9a-f-]+\/documents\/(label|[0-9]+)$/.test(path)) throw Error('Invalid workspace document.');
  const session=state.session;
  const response=await fetch(API+path,{headers:{Authorization:'Bearer '+session.access_token}});
  if (session!==state.session) throw Error('Session changed.');
  if (!response.ok) {const result=await response.json();throw Error(result.detail||'Document download failed.');}
  const blob=await response.blob();if (session!==state.session) throw Error('Session changed.');
  download('easyinvio-shipping-document.pdf',blob,'application/pdf');
}
