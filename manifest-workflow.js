/* Shipment actions share the server's evidence-based policy. No purchase on selection. */
window.ManifestWorkflow = (() => {
  'use strict';
  const h = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const date = value => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : 'Not reported';
  const titles = {PENDING_IMPORT:'Imported — needs preparation',UNFULFILLED:'Imported — not shipped',DRAFT:'Draft — needs quote',QUOTED:'Quoted — not booked',QUOTE_EXPIRED:'Quote expired',QUOTE_UNAVAILABLE:'Fresh quote required',BOOKING:'Booking in progress',SYNC_PENDING:'Carrier confirmation pending',LABEL_CREATED:'Label created',MANIFESTED:'On a handover manifest',DISPATCHED:'Dispatched',IN_TRANSIT:'In transit',OUT_FOR_DELIVERY:'Out for delivery',DELIVERED:'Delivered',EXCEPTION:'Delivery exception',FAILED:'Booking failed',CANCELLED:'Cancelled',BOOKED:'Booked'};
  function status(row) {
    if (row.status === 'QUOTED') {
      const expiry = Date.parse(row.quote_expires_at);
      if (!Number.isFinite(expiry)) return 'QUOTE_UNAVAILABLE';
      if (expiry <= Date.now() + (state.manifestClockOffset || 0)) return 'QUOTE_EXPIRED';
    }
    if (row.status === 'BOOKING' && row.label_status === 'SYNC_PENDING') return 'SYNC_PENDING';
    if (row.status === 'BOOKED' && row.label_status === 'LABEL_CREATED') return 'LABEL_CREATED';
    if (row.status === 'IN_TRANSIT' && row.metadata?.tracking?.milestone === 'OUT_FOR_DELIVERY') return 'OUT_FOR_DELIVERY';
    return row.status;
  }
  const canDispatch = () => !!state.session && portal.role !== 'SUPER_ADMIN' && ['OWNER','ADMIN','DISPATCHER'].includes(portal.profile?.workspace_role);
  function policy(row) {
    const saved = row.workflow || {};
    return {...saved, can_select: saved.can_select === true && status(row) === 'QUOTED',
      has_pod: saved.has_pod === true && row.status === 'DELIVERED' && !!safeHTTPS(row.proof_of_delivery_url)};
  }
  function actions(row, inDetail = false) {
    const p = policy(row), id = h(row.id), dispatch = canDispatch();
    const button = (field, text) => `<button type="button" class="secondary" ${field}="${id}">${text}</button>`;
    let result = '';
    if (dispatch && p.can_select) result += button('data-manifest-book','Review &amp; book') + `<label class="check"><input type="checkbox" data-bulk-manifest="${id}" ${manifestBulkSelected.has(row.id)?'checked':''}>Add to batch</label>`;
    if (dispatch && p.can_requote) result += button('data-manifest-requote',p.can_prepare ? 'Prepare &amp; compare rates' : 'Requote');
    if (dispatch && p.can_review_import) result += button('data-csv-open','Review uploaded customs');
    if (dispatch && p.can_return) result += button('data-prepare-return','Create return');
    if (status(row) === 'EXCEPTION') result += button('data-exception-sheet','Review exception');
    if (!inDetail) result += button('data-manifest-detail','Shipment details &amp; documents');
    if (p.has_pod) result += button('data-manifest-pod','View delivery proof');
    if (dispatch && p.has_label) result += button('data-print','Download carrier label PDF');
    if (dispatch && p.has_qr) result += button('data-manifest-qr','Download carrier drop-off QR');
    return result;
  }
  function customsSummary(doc) {
    if (!doc || !Array.isArray(doc.items) || !doc.items.length) return '<p class="subtle">No customs goods declaration is stored for this shipment.</p>';
    return `<section><h3>Customs goods summary</h3><p>${doc.ready_for_provider ? 'Reviewed goods snapshot' : 'Draft goods — review required before booking'}${doc.invoice_reference ? ' · '+h(doc.invoice_reference) : ''}</p><div style="overflow-x:auto"><table><thead><tr><th>Goods</th><th>Quantity</th><th>Value per unit</th><th>Net kg per unit</th><th>Made in</th><th>HS code</th></tr></thead><tbody>${doc.items.map(item => `<tr><td>${h(item.description)}</td><td>${h(item.quantity)}</td><td>${h(item.unit_value)} ${h(doc.currency)}</td><td>${h(item.unit_weight_kg ?? item.unit_net_weight_kg)}</td><td>${h(item.origin_country)}</td><td>${h(item.hs_code || 'Needs review')}</td></tr>`).join('')}</tbody></table></div><p class="subtle">${doc.ready_for_provider ? 'Saved classification details do not replace destination requirements or the final signed declaration.' : 'A saved draft is not a carrier-approved customs document.'}</p></section>`;
  }
  let detailGeneration = 0, restoring = false;
  async function detail(row) {
    const generation = ++detailGeneration, session = state.session;
    const p = policy(row), doc = row.customs_declaration || row.metadata?.automation_customs;
    checkoutManifestInvoiceId = row.id;
    activeManifestDocument = doc || null;
    document.querySelector('#shipment-doc-json').hidden = true;
    document.querySelector('#shipment-doc-print').hidden = !p.has_invoice;
    document.querySelector('#shipment-doc-print').disabled = !session || !p.has_invoice || portal.role === 'SUPER_ADMIN';
    document.querySelector('#shipment-receipt').hidden = !p.has_receipt || portal.profile?.workspace_role === 'DISPATCHER';
    document.querySelector('#shipment-receipt').disabled = !session || !p.has_receipt || portal.role === 'SUPER_ADMIN';
    const title = titles[status(row)] || row.status;
    const target = document.querySelector('#shipment-detail');
    target.innerHTML = `<div class="notice"><strong>${h(row.reference || row.id)} · ${h(title)}</strong><p>${h(row.workflow?.explanation || 'Carrier events appear after confirmed booking.')}</p></div><div class="doc-summary" style="margin:16px 0">${[['Carrier',row.carrier_code || row.metadata?.carrier || 'Not selected'],['Service',row.service_code || 'Not recorded'],['Quote expiry',date(row.quote_expires_at)],['Booked',date(row.booked_at)],['Dispatched',date(row.dispatched_at)],['Last scan',date(row.last_tracking_event_at)],['Delivered',date(row.delivered_at)]].map(([label,value])=>`<div><small>${h(label)}</small><b style="font-size:12px">${h(value)}</b></div>`).join('')}</div><section data-manifest-timeline><h3>Carrier timeline</h3><p class="subtle">${row.booked_at ? 'Loading recorded carrier scans…' : 'This order has not been booked. No carrier scan or proof of delivery is expected.'}</p></section>${customsSummary(doc)}<div class="actions" data-detail-actions>${actions(row,true).replace(/<label class="check">.*?<\/label>/g,'')}</div>`;
    const dialog = document.querySelector('#shipment-dialog');
    if (!dialog.open) dialog.showModal();
    if (!session || !row.booked_at) return;
    try {
      const path = portal.role === 'SUPER_ADMIN' ? '/api/v1/admin/tracking/shipments/' : '/api/v1/tracking/shipments/';
      const result = await api(path+encodeURIComponent(row.id),{auth:true});
      if (generation !== detailGeneration || state.session !== session || !dialog.open) return;
      const anchor = result.shipments?.find(item => item.id === row.id);
      const events = anchor?.timeline || [];
      target.querySelector('[data-manifest-timeline]').innerHTML = '<h3>Carrier timeline</h3>' + (events.length ? `<ol class="tracking-timeline">${events.map(event=>`<li><b>${h(event.status.replaceAll('_',' '))}</b><time>${h(date(event.occurred_at))}</time>${event.location?`<small>${h(event.location)}</small>`:''}</li>`).join('')}</ol>` : '<p class="subtle">No carrier scans have been recorded yet. A label is not a collection scan.</p>');
    } catch {
      if (generation === detailGeneration && state.session === session && dialog.open) target.querySelector('[data-manifest-timeline]').innerHTML = '<h3>Carrier timeline</h3><p class="subtle">Detailed scans are unavailable right now. Recorded booking dates are shown above; refresh tracking later.</p>';
    }
  }
  function put(id, value) { const node = document.getElementById(id); if (node) node.value = value ?? ''; }
  function restoreGoods(items) {
    document.querySelector('#catalog-extra-items').replaceChildren();
    const first = items[0] || {};
    for (const [key,id] of Object.entries({description:'shipment-description',quantity:'shipment-quantity',unit_value:'shipment-unit-value',unit_weight_kg:'shipment-unit-weight',origin_country:'shipment-goods-origin',sku:'shipment-sku',hs_code:'shipment-hs-code'})) put(id,first[key] ?? (key==='unit_weight_kg'?first.unit_net_weight_kg:undefined));
    for (const item of items.slice(1)) {
      document.querySelector('#catalog-add-item').click();
      const row = document.querySelector('#catalog-extra-items').lastElementChild;
      for (const node of row.querySelectorAll('[data-goods-field]')) node.value = item[node.dataset.goodsField] ?? (node.dataset.goodsField==='unit_weight_kg'?item.unit_net_weight_kg:'') ?? '';
    }
  }
  async function restore(row) {
    if (restoring || !canDispatch()) return;
    restoring = true;
    const session = state.session, tenant = portal.profile?.tenant_id, version = state.generation;
    try {
      const result = await api('/api/v1/shipments/'+encodeURIComponent(row.id)+'/requote-context',{auth:true});
      if (session !== state.session || tenant !== portal.profile?.tenant_id || version !== state.generation) return;
      setView('dispatch');
      resetQuoteForm();
      for (const name of ['origin','destination']) for (const field of addressNames) put(name+'-'+field,result[name]?.[field]);
      put('cargo-type',result.cargo_type); configureCargo(false);
      document.querySelector('#cargo-stackable').checked = result.stackable;
      const first = result.packages[0];
      for (const key of ['length_cm','width_cm','height_cm']) put(key,first[key]);
      put('weight_kg',first.actual_weight_kg); put('currency',result.currency);put('shipment-goods-currency',result.goods_currency);
      restoreGoods(result.shipment_items);
      const panel = document.createElement('section');panel.id='manifest-restored-packages';panel.className='notice';
      panel.innerHTML = `<p>${h(result.notice)}</p>${result.packages.length>1?'<h3>Additional saved boxes</h3><p>Box 1 uses the measurements above. Review the remaining boxes and goods allocation.</p>':''}${result.packages.slice(1).map((box,index)=>`<fieldset data-restored-box><legend>Box ${index+2}</legend><div class="fields">${Object.entries({length_cm:'Length · cm',width_cm:'Width · cm',height_cm:'Height · cm',actual_weight_kg:'Packed weight · kg'}).map(([key,label])=>`<label>${label}<input type="number" required min="0.001" step="${key==='actual_weight_kg'?'0.001':'0.01'}" data-box-field="${key}" value="${h(box[key])}"></label>`).join('')}</div></fieldset>`).join('')}${result.packages.length>1?`<h3>Goods allocation</h3>${result.shipment_items.map((item,index)=>`<label>${h(item.description)} · box number<input type="number" required min="1" max="${result.packages.length}" step="1" data-restored-allocation="${index}" value="${h(item.package_index || '')}"></label>`).join('')}`:''}`;
      document.querySelector('#quote-btn').before(panel);
      document.querySelector('#quote-form').dispatchEvent(new Event('input',{bubbles:true}));
      if (document.querySelector('#shipment-dialog').open) document.querySelector('#shipment-dialog').close();
      document.querySelector('#origin-name').focus();
      updateWeight();
    } finally { restoring = false; }
  }
  function install() {
    const style=document.createElement('style');
    style.textContent='#manifest .toolbar{flex-wrap:wrap}#manifest-search{min-width:180px;flex:1}#shipment-detail section{margin-top:20px}#manifest-restored-packages{width:100%;margin:16px 0}#manifest-restored-packages fieldset{margin:14px 0;padding:12px;border:1px solid #334155;border-radius:10px}@media(max-width:650px){#manifest .toolbar{display:grid;grid-template-columns:minmax(0,1fr);gap:10px}#manifest .toolbar>*{width:100%;max-width:none!important;min-width:0}#manifest .toolbar [hidden]{display:none}}';
    document.head.append(style);
    const base = renderManifest;
    const previousStates = new Map();
    displayedStatus = status;
    renderManifest = function() {
      // Expired selections cannot silently remain in a bulk purchase request.
      const eligible = new Set(manifestRecords().filter(row=>policy(row).can_select).map(row=>row.id));
      for (const id of manifestBulkSelected) if (!eligible.has(id)) manifestBulkSelected.delete(id);
      base();
      for (const button of document.querySelectorAll('#manifest-body [data-manifest-detail]')) {
        const row = manifestRecords().find(item=>item.id===button.dataset.manifestDetail);
        if (!row) continue;
        const tr=button.closest('tr'), cells=tr.querySelectorAll('td');
        previousStates.set(row.id,status(row));
        const carrier=row.carrier_code||row.metadata?.carrier;
        cells[1].firstChild.textContent=carrier || (['PENDING_IMPORT','UNFULFILLED','DRAFT'].includes(row.status)?'Not selected': 'Unavailable on this older record');
        const tag=cells[2].querySelector('.tag');tag.textContent=titles[status(row)]||row.status;tag.title=row.workflow?.explanation||'';
        if (row.status==='QUOTED') {const expiry=document.createElement('small');expiry.className='subtle';expiry.style.display='block';expiry.textContent='Expires '+date(row.quote_expires_at);cells[2].append(expiry);}
        if (['PENDING_IMPORT','UNFULFILLED','DRAFT'].includes(row.status)) cells[3].textContent='Not priced yet';
        if (['FAILED','QUOTE_EXPIRED','QUOTE_UNAVAILABLE'].includes(status(row)) && row.price != null) {const caption=document.createElement('small');caption.className='subtle';caption.style.display='block';caption.textContent='Last quoted price';cells[3].append(caption);}
        if (!row.booked_at) tr.querySelector('.pipeline')?.remove();
        if (row.service_code) {const service=document.createElement('small');service.className='subtle';service.style.display='block';service.textContent=row.service_code;cells[1].append(service);}
        button.closest('.manifest-actions').innerHTML=actions(row);
      }
      const selected=manifestBulkSelected.size, bulk=document.querySelector('#manifest-bulk-review');
      bulk.hidden=!canDispatch();bulk.disabled=!selected;bulk.textContent=`Review & book selected orders (${selected})`;
      document.querySelector('#manifest-print-mode').textContent='PDF / QR';
    };
    const originalRefresh=refreshManifestRecords;
    refreshManifestRecords=async function(){await originalRefresh.apply(this,arguments);renderManifest();};
    const reset=resetQuoteForm; resetQuoteForm=function(){document.querySelector('#manifest-restored-packages')?.remove();return reset.apply(this,arguments);};
    const clear=clearSession;clearSession=function(){detailGeneration++;document.querySelector('#manifest-restored-packages')?.remove();document.querySelector('#shipment-detail').replaceChildren();document.querySelector('#pod-content').replaceChildren();checkoutManifestInvoiceId=null;activeManifestDocument=null;previousStates.clear();state.manifestClockOffset=0;return clear.apply(this,arguments);};
    const payload=quotePayload;quotePayload=function(){
      const body=payload();const panel=document.querySelector('#manifest-restored-packages');
      if(!panel)return body;
      const boxes=[...panel.querySelectorAll('[data-restored-box]')].map(box=>Object.fromEntries([...box.querySelectorAll('[data-box-field]')].map(input=>[input.dataset.boxField,input.value])));
      if(boxes.length){
        if(body.cargo_type!=='PARCEL')throw Error('Multiple saved boxes require Standard Parcel. Start a new shipment to change cargo type.');
        body.weights_kg.push(...boxes.map(box=>box.actual_weight_kg));
        body.dimensions.push(...boxes.map(({length_cm,width_cm,height_cm})=>({length_cm,width_cm,height_cm})));
        if(body.shipment_items.length!==panel.querySelectorAll('[data-restored-allocation]').length)throw Error('Goods lines changed. Review box allocation or start a new shipment.');
        for(const input of panel.querySelectorAll('[data-restored-allocation]'))body.shipment_items[Number(input.dataset.restoredAllocation)].package_index=Number(input.value);
      }
      return body;
    };
    document.querySelector('#manifest-body').addEventListener('change',()=>{const button=document.querySelector('#manifest-bulk-review');button.disabled=!manifestBulkSelected.size;button.textContent=`Review & book selected orders (${manifestBulkSelected.size})`;});
    document.addEventListener('click',event=>{
      const button=event.target.closest('[data-manifest-detail],[data-manifest-book],[data-manifest-requote],[data-manifest-qr],[data-print],[data-manifest-pod]');
      if(!button)return;
      if(!button.closest('#manifest-body,#shipment-dialog'))return;
      event.stopImmediatePropagation();event.preventDefault();
      const id=button.dataset.manifestDetail||button.dataset.manifestBook||button.dataset.manifestRequote||button.dataset.manifestQr||button.dataset.print||button.dataset.manifestPod;
      const row=manifestRecords().find(item=>item.id===id);if(!row)return;
      if(button.dataset.manifestDetail)void detail(row).catch(error=>notify(error.message,true));
      else if(button.dataset.manifestBook&&canDispatch()&&policy(row).can_select)busy(button,()=>openBulkCheckout([id]));
      else if(button.dataset.manifestRequote&&policy(row).can_requote)busy(button,()=>restore(row));
      else if(button.dataset.manifestQr&&canDispatch()&&policy(row).has_qr)busy(button,()=>downloadPartnerDocument('/api/v1/shipping/'+encodeURIComponent(id)+'/documents/return-qr'));
      else if(button.dataset.print&&canDispatch()&&policy(row).has_label)busy(button,()=>downloadPartnerDocument('/api/v1/shipping/'+encodeURIComponent(id)+'/documents/label'));
      else if(button.dataset.manifestPod&&policy(row).has_pod){
        document.querySelector('#pod-content').innerHTML=`<p>Carrier-supplied delivery evidence. This link may expire.</p><a class="primary" target="_blank" rel="noopener noreferrer" href="${h(safeHTTPS(row.proof_of_delivery_url))}">Open delivery proof</a>`;
        document.querySelector('#pod-dialog').showModal();
      }
    },true);
    document.querySelector('#shipment-dialog').addEventListener('close',()=>{detailGeneration++;});
    const filter=document.querySelector('#manifest-filter');
    for(const option of filter.options)if(titles[option.value])option.textContent=titles[option.value];
    for(const value of ['PENDING_IMPORT','UNFULFILLED','DRAFT','QUOTED','QUOTE_EXPIRED','QUOTE_UNAVAILABLE','BOOKING','SYNC_PENDING','MANIFESTED','CANCELLED'])if(![...filter.options].some(option=>option.value===value))filter.add(new Option(titles[value],value));
    setInterval(()=>{if(state.session&&!document.querySelector('#manifest').hidden&&manifestRecords().some(row=>previousStates.has(row.id)&&previousStates.get(row.id)!==status(row)))renderManifest();},1000);
    renderManifest();
  }
  return {install,status,policy,actions,customsSummary,restore};
})();
