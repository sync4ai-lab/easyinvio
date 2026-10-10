// Embedded in index.html: complete CSV order import and customs-review controls.
let activeCSVReview = null;
document.head.insertAdjacentHTML('beforeend','<style>.batchrows .scrolltable{overflow-x:auto;max-width:100%;min-width:0}.batchrows table{min-width:560px}#csv-review-dialog .fields{min-width:0}#csv-review-dialog label{min-width:0}</style>');

function csvTemplateDownload(button, extended) {
  return busy(button, async () => {
    const data = await api('/api/v1/shipments/batch-template?extended=' + extended);
    exportCSV(extended ? 'easyinvio-orders-extended-template.csv' : 'easyinvio-orders-template.csv',
      [data.columns, ...data.examples]);
    notify('Template downloaded. Replace the example rows with your orders.');
  });
}
$('#csv-template').addEventListener('click', () => csvTemplateDownload($('#csv-template'), false));
$('#csv-extended-template').addEventListener('click', () => csvTemplateDownload($('#csv-extended-template'), true));

function renderCSVResults() {
  const batch = state.batch;
  if (!batch) return;
  const rows = batch.results;
  batch.quoted = rows.filter(row => row.status === 'quoted').length;
  batch.review_required = rows.filter(row => row.status === 'customs_review_required').length;
  $('#batch-result').innerHTML = `<p style="margin:15px 0"><b>${batch.quoted}/${batch.total} orders quoted</b> · ${batch.simulated ? 'SIMULATION — no database writes' : `${rows.filter(r => r.saved).length} orders saved`} · ${batch.review_required} need customs review · 0 bookings</p>
    <div class="scrolltable"><table><thead><tr><th>Order / cargo</th><th>Status</th><th>Best rate / next step</th><th>Actions</th></tr></thead><tbody>${rows.map(row => `<tr>
    <td><b>${escapeHTML(row.order_reference || 'Row ' + row.row)}</b><br><span class="tag">${escapeHTML(row.cargo_type || 'Invalid row')}</span></td>
    <td>${escapeHTML(row.status.replaceAll('_', ' '))}${row.replayed ? '<br><small>Existing order reused</small>' : ''}</td>
    <td>${row.quote?.rates?.length ? money(row.quote.rates[0].client_price_ex_tax, row.quote.currency) : escapeHTML(row.error || (row.missing_fields || []).join(', ') || 'Order saved')}</td>
    <td><div class="actions">${row.status === 'customs_review_required' ? `<button class="secondary" data-csv-review-row="${row.row}">Review customs & quote</button>` : ''}${row.saved && row.shipment_id ? `<button class="secondary" data-csv-manifest="${escapeHTML(row.shipment_id)}">Open in manifest</button>` : ''}</div></td></tr>`).join('')}</tbody></table></div>`;
}

$('#batch-btn').addEventListener('click', () => busy($('#batch-btn'), async () => {
  const file = $('#csv-file').files[0];
  if (!file) throw Error('Choose a CSV file first.');
  if (file.size > 5000000) throw Error('CSV is limited to 5 MB.');
  const generation = state.generation;
  $('#batch-progress').hidden = false;
  $('#batch-progress span').style.width = '35%';
  try {
    const result = await api(`/api/v1/shipments/${state.mode === 'local-preview' ? 'batch-preview' : 'batch'}`,
      {method: 'POST', body: await file.text(), raw: true, auth: state.mode !== 'local-preview'});
    if (generation !== state.generation) return;
    state.batch = result;
    $('#batch-progress span').style.width = '100%';
    $('#batch-export').disabled = false;
    renderCSVResults();
    if (state.session && result.saved) {
      try { await refreshManifestRecords(); }
      catch { notify('Orders saved. Refresh Manifest to load them.', true); }
    }
  } finally { setTimeout(() => $('#batch-progress').hidden = true, 1000); }
}));

$('#batch-export').addEventListener('click', () => {
  if (!state.batch) return;
  exportCSV('easyinvio-batch-results.csv', [['Order','Cargo','Status','Shipment ID','Currency','Lowest quote','Missing fields / error'],
    ...state.batch.results.map(row => [row.order_reference,row.cargo_type || '',row.status,row.shipment_id || '',
      row.quote?.currency || row.order?.currency || '',row.quote?.rates?.[0]?.client_price_ex_tax || '',
      row.error || (row.missing_fields || []).join('; ')])]);
});

document.body.insertAdjacentHTML('beforeend', `<dialog id="csv-review-dialog">
  <button class="close" id="csv-review-close" aria-label="Close customs review">×</button>
  <h2>Uploaded order — customs review</h2><p id="csv-review-reference" class="subtle"></p>
  <div class="notice">Confirm the actual goods origin and net weight. Warehouse country and packed weight do not establish these facts. HS suggestions are simulated. Saving this review fetches rates; it does not buy a label.</div>
  <form id="csv-review-form"><div class="fields">
  <label>Item description<input name="description" minlength="3" maxlength="500" required></label>
  <label>Quantity<input name="quantity" type="number" min="1" max="10000" step="1" value="1" required></label>
  <label>Unit declared value<input name="unit_value" inputmode="decimal" pattern="[0-9]+(\\.[0-9]{1,2})?" required></label>
  <label>Goods origin country<input name="origin_country" minlength="2" maxlength="3" placeholder="Actual manufacturing origin" required></label>
  <label>Unit goods net weight (kg)<input name="unit_weight_kg" inputmode="decimal" pattern="[0-9]+(\\.[0-9]{1,3})?" placeholder="Excluding packaging" required></label>
  <label>Reviewed HS code<input name="hs_code" pattern="[0-9]{6}([0-9]{2})?([0-9]{2})?" required></label>
  <label>Recipient phone (E.164)<input name="recipient_phone" type="tel" pattern="\\+[1-9][0-9]{7,14}" placeholder="+12025550123" required></label>
  <label>Origin state/province<input name="origin_state" maxlength="100"></label>
  <label>Destination state/province<input name="destination_state" maxlength="100"></label>
  <label>Customs signer<input name="customs_signer" maxlength="200" required></label>
  <label>Postal form<select name="postal_form"><option value="">Commercial invoice only</option><option>CN22</option><option>CN23</option></select></label>
  <label>Incoterm<select name="incoterm"><option>DAP</option><option>DDP</option><option>FCA</option><option>EXW</option></select></label>
  <label>Sender EORI (optional)<input name="sender_eori" maxlength="40"></label>
  <label>Recipient EORI (optional)<input name="recipient_eori" maxlength="40"></label>
  <label>Sender VAT (optional)<input name="sender_vat" maxlength="40"></label>
  <label>Recipient VAT (optional)<input name="recipient_vat" maxlength="40"></label>
  </div><label class="check"><input name="hs_codes_reviewed" type="checkbox" required>I reviewed the HS classification, declared value and goods details.</label>
  <button class="primary full" type="submit">Save customs review & fetch rates</button></form>
  <pre id="csv-review-output" hidden></pre></dialog>`);

function openCSVReview(row) {
  if (!allowedEnterpriseViews().includes('dispatch')) throw Error('Dispatch permission required.');
  activeCSVReview = {row, generation: state.generation};
  const form = $('#csv-review-form'); form.reset();
  const item = row.order?.items?.[0] || {};
  const source = row.review?.source || {};
  const values = {description: item.description || row.review?.item_description || source.item_description || '',
    quantity: item.quantity || source.item_quantity || 1, unit_value: item.unit_value || row.review?.declared_value || source.item_declared_value || '',
    origin_country: item.origin_country || source.item_origin_country || '',
    unit_weight_kg: item.unit_weight_kg || source.item_net_weight_kg || '',
    hs_code: item.hs_code || source.hs_code || row.review?.hs_suggestion?.hs_code || '',
    recipient_phone: row.order?.destination?.phone || source.recipient_phone || '',
    origin_state:row.order?.origin?.state || source.origin_state || '',
    destination_state:row.order?.destination?.state || source.destination_state || '',
    customs_signer: row.order?.customs_signer || '',postal_form:row.order?.postal_form || '',incoterm:row.order?.incoterm || 'DAP',
    sender_eori:row.order?.sender_eori || '',recipient_eori:row.order?.recipient_eori || '',
    sender_vat:row.order?.sender_vat || '',recipient_vat:row.order?.recipient_vat || ''};
  for (const [name,value] of Object.entries(values)) form.elements[name].value = value;
  for (const prefix of ['origin','destination']) form.elements[prefix + '_state'].required = ['US','CA','AU'].includes(row.order?.[prefix]?.country_code);
  $('#csv-review-reference').textContent = `${row.order_reference} · ${row.order?.cargo?.cargo_type || row.cargo_type} · ${row.order?.currency || ''} · Gross ${row.order?.cargo?.actual_weight_kg || ''} kg`;
  $('#csv-review-output').hidden = true;
  $('#csv-review-dialog').showModal();
}
$('#csv-review-close').addEventListener('click', () => $('#csv-review-dialog').close());
$('#csv-review-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.target.querySelector('button[type=submit]'), async () => {
    if (!activeCSVReview || activeCSVReview.generation !== state.generation) throw Error('Workspace changed. Reopen the order.');
    if (!allowedEnterpriseViews().includes('dispatch')) throw Error('Dispatch permission required.');
    const active = activeCSVReview, values = Object.fromEntries(new FormData(event.target));
    const body = {items:[{description:values.description,quantity:Number(values.quantity),unit_value:values.unit_value,
      unit_weight_kg:values.unit_weight_kg,origin_country:values.origin_country,hs_code:values.hs_code}],
      customs_signer:values.customs_signer,hs_codes_reviewed:true,recipient_phone:values.recipient_phone,incoterm:values.incoterm};
    for (const key of ['postal_form','sender_eori','recipient_eori','sender_vat','recipient_vat','origin_state','destination_state']) if (values[key]) body[key] = values[key];
    let result;
    if (state.mode === 'local-preview') {
      const order = {...active.row.order,...body,destination:{...active.row.order.destination,phone:body.recipient_phone}};
      delete order.recipient_phone;
      if (body.origin_state) order.origin = {...order.origin,state:body.origin_state};
      if (body.destination_state) order.destination.state = body.destination_state;
      delete order.origin_state;delete order.destination_state;
      result = await api('/api/v1/shipments/batch-review-preview',{method:'POST',body:order});
    } else {
      result = await api('/api/v1/shipments/batch/' + encodeURIComponent(active.row.shipment_id) + '/quote',
        {method:'POST',body,auth:true});
    }
    if (active.generation !== state.generation) return;
    Object.assign(active.row,result);
    if (result.status === 'quoted') active.row.missing_fields = [];
    $('#csv-review-output').hidden = false;
    $('#csv-review-output').textContent = result.status === 'quoted' ? 'Customs data reviewed. Order quoted; no label purchased.' : 'Review retained. ' + (result.error || 'Quote unavailable.');
    renderCSVResults();
    if (state.session) await refreshManifestRecords();
  });
});

document.addEventListener('click', event => {
  const review = event.target.closest('[data-csv-review-row]');
  if (review) {
    const row = state.batch?.results.find(r => r.row === Number(review.dataset.csvReviewRow));
    if (row) openCSVReview(row);
  }
  const open = event.target.closest('[data-csv-open]');
  if (open) busy(open, async () => {
    const row = await api('/api/v1/shipments/batch/' + encodeURIComponent(open.dataset.csvOpen),{auth:true});
    openCSVReview(row);
  });
  const manifest = event.target.closest('[data-csv-manifest]');
  if (manifest) busy(manifest, async () => {
    await refreshManifestRecords();
    const row = state.manifest.find(r => r.id === manifest.dataset.csvManifest);
    $('#manifest-search').value = row?.reference || manifest.dataset.csvManifest;
    $('#manifest-filter').value = 'all'; setView('manifest'); renderManifest();
  });
});

const csvPreviousManifest = renderManifest;
renderManifest = function() {
  csvPreviousManifest();
  if (!state.session || !allowedEnterpriseViews().includes('dispatch')) return;
  for (const button of $('#manifest-body').querySelectorAll('[data-manifest-detail]')) {
    const row = state.manifest.find(r => r.id === button.dataset.manifestDetail);
    if (!row?.batch_import || !row.customs_required || row.customs_declaration?.ready_for_provider) continue;
    const action = document.createElement('button');action.className = 'secondary';
    action.textContent = 'Review uploaded customs';action.dataset.csvOpen = row.id;
    button.closest('.manifest-actions').prepend(action);
  }
};
const csvPreviousClear = clearSession;
clearSession = function() {
  activeCSVReview = null;$('#csv-review-dialog').close();$('#csv-review-form').reset();
  $('#csv-review-reference').textContent = '';$('#csv-review-output').textContent = '';csvPreviousClear();
};
const csvPreviousPortal = renderPortal;
renderPortal = function() {
  csvPreviousPortal();
  if (!allowedEnterpriseViews().includes('dispatch')) { activeCSVReview = null;$('#csv-review-dialog').close(); }
};
