// Embedded customer checkout: private offer -> reviewed customs -> confirmed booking.
const customerCheckout = {index:null, context:null, prepared:null, generation:0};
document.head.insertAdjacentHTML('beforeend', `<style>
#review-dialog.checkout-wide{width:min(1120px,calc(100vw - 28px));font-family:system-ui,sans-serif}.checkout-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;clear:both}.checkout-layout>*{min-width:0}.checkout-layout>div:first-child{position:sticky;top:0;align-self:start;background:#020617}.checkout-products{display:grid;gap:12px}.checkout-product{padding:14px;border:1px solid #334155;border-radius:12px;background:#0b1527}.checkout-error{padding:12px;border:1px solid #ef4444;color:#fecaca;border-radius:10px;margin:12px 0}.checkout-choices{display:grid;gap:10px;margin-top:16px}.checkout-tariffs button{width:100%;text-align:left;margin-top:8px}.status-label_created{color:#6ee7b7;background:#064e3b}.status-sync_pending{color:#fde68a;background:#451a03}@media(max-width:767px){.checkout-layout{grid-template-columns:minmax(0,1fr)}.checkout-layout>div:first-child{position:static}#review-dialog.checkout-wide{padding:16px}}
</style>`);

feeRows = function(rate) {
  const total=cents(rate.client_price_ex_tax), supplied=rate.fee_breakdown?.fuel_surcharge;
  let fuel=null;
  if (supplied!=null) { const value=cents(supplied);if(value>=0n && value<=total)fuel=value; }
  const rows=[['Label cost',money(decimalCents(total-(fuel||0n)),rate.currency)],
    ['Shipment protection','Not added'],['Fuel surcharge',fuel===null?'Included in label cost':money(decimalCents(fuel),rate.currency)],
    ['Subtotal price (excl. tax)',money(rate.client_price_ex_tax,rate.currency)]];
  return rows.map(([label,value],i)=>`<div class="fee ${i===3?'total':''}"><span>${label}</span><b>${escapeHTML(value)}</b></div>`).join('');
};

function checkoutError(error) {
  const target=$('#checkout-booking-error');
  if (target) {target.hidden=false;target.textContent=error.message||'Booking could not be completed. No confirmed label is available.';}
}

function checkoutProduct(item={}) {
  const value=name=>escapeHTML(item[name]??'');
  return `<div class="checkout-product"><label>Product description</label><textarea name="description" minlength="3" maxlength="500" placeholder="e.g. Electric steam iron for household clothing" required>${value('description')}</textarea>
  <button type="button" class="secondary" data-checkout-hs>Find HS code in official tariff</button><div class="checkout-tariffs" aria-live="polite"></div>
  <div class="fields"><div><label>Reviewed HS code</label><input name="hs_code" value="${value('hs_code')}" placeholder="6, 8 or 10 digits" pattern="[0-9]{6}([0-9]{2})?([0-9]{2})?" required></div><div><label>Country of manufacture</label><input readonly name="origin_country" value="${value('origin_country')}" placeholder="e.g. GB" pattern="[A-Za-z]{2}" required></div>
  <div><label>Quantity</label><input readonly name="quantity" value="${value('quantity')}" type="number" min="1" max="10000" step="1" placeholder="e.g. 2" required></div><div><label>Value per item</label><input readonly name="unit_value" value="${value('unit_value')}" inputmode="decimal" pattern="[0-9]+(\\.[0-9]{1,2})?" placeholder="e.g. 25.00" required></div>
  <div><label>Net weight per item (kg)</label><input readonly name="unit_weight_kg" value="${value('unit_weight_kg')}" type="number" min="0.001" step="0.001" placeholder="e.g. 0.250" required></div></div></div>`;
}

function renderCheckoutCustoms() {
  const context=customerCheckout.context;
  if(!context.items?.length){$('#checkout-next').innerHTML='<div class="notice">This older quote has no saved goods details. Close checkout, enter goods in Create shipment and fetch a fresh quote.</div>';return;}
  $('#checkout-next').innerHTML=`<h2>Customs details &amp; HS finder</h2><p class="subtle">Enter the real goods in this shipment. Review tariff suggestions before declaring them.</p>
    <p class="subtle">Packed weight: ${escapeHTML(context.gross_weight_kg)} kg; total goods net weight: ${escapeHTML(context.total_goods_net_weight_kg||'Not recorded')} kg.</p><form id="customer-customs-form"><label>Invoice reference - linked to this booking</label><input name="invoice_reference" readonly value="${escapeHTML(context.invoice_reference)}">
    <div class="fields"><div><label>Shipping cost</label><input readonly value="${escapeHTML(money(context.shipping_cost,context.shipping_currency))}"></div><div><label>Goods value currency</label><select name="currency"><option ${context.goods_value_currency==='GBP'?'selected':''}>GBP</option><option ${context.goods_value_currency==='EUR'?'selected':''}>EUR</option><option ${context.goods_value_currency==='USD'?'selected':''}>USD</option></select></div></div>
    <p class="footnote">Review goods values in the selected currency. Some services require USD customs values; no automatic currency conversion is assumed.</p>
    <p class="notice">Quantity, value, goods origin and net weight come from your saved shipment quote. To change these values, close this checkout, edit Create shipment and request fresh rates.</p><div class="checkout-products">${(context.items||[]).map(item=>checkoutProduct(item)).join('')}</div><button class="secondary" type="button" id="checkout-add-product" hidden disabled>Add another product</button>
    <label>Export category</label><select name="category"><option value="SALE">Sale of goods</option><option value="GIFT">Gift</option><option value="RETURN">Returned goods</option><option value="SAMPLE">Commercial sample</option><option value="OTHER">Other</option></select>
    <div id="checkout-other-field" hidden><label>Describe the export reason</label><input name="category_other" minlength="3" maxlength="200" placeholder="e.g. Exhibition goods being sent temporarily"></div>
    <label>Import duties and taxes</label><select name="incoterm"><option value="DAP">Recipient pays import duties and taxes (DAP)</option></select>
    <p class="footnote">DAP states who pays import charges; it is recorded on the invoice. Sender-paid duties require a supported carrier contract and are not assumed here.</p>
    <div class="fields"><div><label>Sender EORI (if applicable)</label><input name="sender_eori" maxlength="40" placeholder="e.g. GB followed by your registered number"></div><div><label>Recipient EORI (if applicable)</label><input name="recipient_eori" maxlength="40" placeholder="Recipient's registered EORI"></div></div>
    <label>Declaration signed by</label><input name="signer" maxlength="200" placeholder="Full name of the responsible shipper" required>
    <label class="check"><input name="reviewed" type="checkbox" required>I confirm the HS codes, origin, values and weights describe my goods accurately.</label>
    <button id="checkout-prepare-btn" class="primary full">Review final booking price</button></form>`;
  const form=$('#customer-customs-form');form.elements.currency.disabled=true;
  form.elements.category.addEventListener('change',()=>{
    const other=form.elements.category.value==='OTHER';$('#checkout-other-field').hidden=!other;
    form.elements.category_other.required=other;if(!other)form.elements.category_other.value='';
  });
  $('#checkout-add-product').addEventListener('click',()=>{
    if(form.querySelectorAll('.checkout-product').length>=100)return;
    form.querySelector('.checkout-products').insertAdjacentHTML('beforeend',checkoutProduct());
  });
  form.addEventListener('click',event=>{
    const remove=event.target.closest('[data-checkout-remove]');
    if(remove && form.querySelectorAll('.checkout-product').length>1)remove.closest('.checkout-product').remove();
    const search=event.target.closest('[data-checkout-hs]');if(!search)return;
    busy(search,async()=>{
      const product=search.closest('.checkout-product'),generation=customerCheckout.generation;
      const description=product.querySelector('[name=description]').value.trim();
      if(description.length<3)throw Error('Describe the product before finding an HS code.');
      product.querySelector('[name=hs_code]').value='';form.elements.reviewed.checked=false;
      const result=await api('/api/v1/checkout/hs-search',{method:'POST',auth:true,body:{description}});
      if(generation!==customerCheckout.generation)return;
      const target=product.querySelector('.checkout-tariffs');
      target.innerHTML=result.candidates.length?`<p class="footnote">Official UK tariff matches. Select only a description that applies to your goods.</p>`+result.candidates.map(candidate=>`<button type="button" class="secondary" data-tariff-code="${escapeHTML(candidate.hs_code)}"><b>${escapeHTML(candidate.hs_code)}</b> &middot; ${escapeHTML(candidate.title)}</button>`).join(''):`<p class="notice">${escapeHTML(result.question||'No specific match found. Add material, function and construction, or check the official tariff.')}</p>`;
      target.querySelectorAll('[data-tariff-code]').forEach(button=>button.addEventListener('click',()=>{
        product.querySelector('[name=hs_code]').value=button.dataset.tariffCode;form.elements.reviewed.checked=false;
      }));
    });
  });
  form.addEventListener('input',event=>{
    if(event.target.name==='description') {const product=event.target.closest('.checkout-product');product.querySelector('[name=hs_code]').value='';product.querySelector('.checkout-tariffs').replaceChildren();}
    if(event.target.name!=='reviewed')form.elements.reviewed.checked=false;
  });
  form.addEventListener('submit',event=>{
    event.preventDefault();busy($('#checkout-prepare-btn'),async()=>{
      try {
        const items=[...form.querySelectorAll('.checkout-product')].map(product=>Object.fromEntries(['description','hs_code','origin_country','quantity','unit_value','unit_weight_kg'].map(name=>[name,name==='quantity'?Number(product.querySelector(`[name=${name}]`).value):product.querySelector(`[name=${name}]`).value.trim()])));
        await prepareCustomerCheckout({items,signer:form.elements.signer.value.trim(),reviewed:form.elements.reviewed.checked,
          currency:form.elements.currency.value,category:form.elements.category.value,
          category_other:form.elements.category.value==='OTHER'?form.elements.category_other.value.trim():null,
          incoterm:'DAP',sender_eori:form.elements.sender_eori.value.trim()||null,recipient_eori:form.elements.recipient_eori.value.trim()||null});
      } catch(error) {checkoutError(error);throw error;}
    });
  });
}

async function prepareCustomerCheckout(customs=null) {
  const generation=customerCheckout.generation;
  const rate=state.quotes[customerCheckout.index];
  const prepared=await api('/api/v1/checkout/prepare',{method:'POST',auth:true,body:{offer_id:rate.offer_id,customs}});
  if(generation!==customerCheckout.generation)return;
  customerCheckout.prepared=prepared;
  $('#checkout-price').innerHTML=feeRows(prepared.offer);
  $('#checkout-next').innerHTML=`<h2>Confirm your booking</h2><p class="notice">${prepared.price_changed?'The price changed after the carrier evaluated your customs details. Review this final price before purchasing.':'Your shipment is prepared. Confirm the price shown to create the shipping label.'}</p><p class="subtle">${escapeHTML(prepared.invoice_reference)} &middot; ${escapeHTML(money(prepared.offer.client_price_ex_tax,prepared.offer.currency))}</p><button id="checkout-purchase" class="primary full">Confirm &amp; create shipping label</button><p class="footnote">Wallet credit is captured only after label confirmation. ${prepared.customs_required?'Your commercial invoice PDF will be available with the confirmed booking.':''}</p>`;
  $('#checkout-purchase').addEventListener('click',()=>busy($('#checkout-purchase'),async()=>{
    try {
      const result=await api('/api/v1/shipping/confirm-booking',{method:'POST',auth:true,
        body:{offer_id:prepared.offer.offer_id,tenant_id:portal.profile.tenant_id}});
      if(generation!==customerCheckout.generation)return;
      showCustomerBooking(result,prepared);
    } catch(error) {checkoutError(error);throw error;}
  }));
}

function showCustomerBooking(result,prepared) {
  const pending=result.status==='SYNC_PENDING';
  $('#review-content').innerHTML=`<h2>${pending?'Your label is being prepared':'Shipment booked successfully'}</h2><p class="notice">${pending?'Your carrier has accepted the request. Credit remains reserved while the label is prepared. Do not place a second booking.':'Tracking: '+escapeHTML(result.label.tracking_number)}</p><p class="subtle">Booking / invoice reference: ${escapeHTML(prepared.invoice_reference)}</p><div id="checkout-downloads" class="actions"></div><button class="secondary" id="checkout-open-manifest">Open Manifest &amp; Labels</button><button class="secondary" id="checkout-new-shipment">Start a new shipment</button>`;
  if(!pending){
    const documents=[{document_type:'Booking receipt PDF',url:'/api/v1/checkout/'+result.shipment_id+'/receipt.pdf'},{document_type:'Shipping label PDF',url:result.label.label_url},...(result.label.carrier_forms||[])];
    if(prepared.customs_required)documents.push({document_type:'Commercial invoice PDF',url:'/api/v1/checkout/'+result.shipment_id+'/commercial-invoice.pdf'});
    for(const shippingDocument of documents){const button=document.createElement('button');button.type='button';button.className='primary';button.textContent='Download '+shippingDocument.document_type;button.addEventListener('click',()=>busy(button,()=>downloadPartnerDocument(shippingDocument.url)));$('#checkout-downloads').append(button);}
    state.quotes[customerCheckout.index].booked=true;
  }
  $('#checkout-open-manifest').addEventListener('click',()=>{$('#review-dialog').close();setView('manifest');});
  $('#checkout-new-shipment').addEventListener('click',()=>{$('#review-dialog').close();resetQuoteForm();resetCustomerCheckout();setView('dispatch');});
  notify(pending?'Label preparation is pending. Check the manifest for completion.':'Shipping label created. Your booking is complete.');
}

bookLive = async function(index) {
  if(!state.session||!portal.profile?.tenant_id)throw Error('Sign in to a client workspace before booking.');
  customerCheckout.index=index;customerCheckout.prepared=null;const generation=++customerCheckout.generation;
  try {
    const context=await api('/api/v1/checkout/context?offer_id='+encodeURIComponent(state.quotes[index].offer_id),{auth:true});
    if(generation!==customerCheckout.generation)return;
    customerCheckout.context=context;
    $('#review-dialog').classList.add('checkout-wide');
    $('#review-content').innerHTML=`<div class="checkout-layout"><div><span class="tag green">YOUR SELECTED SERVICE</span><h2>${escapeHTML(carrierDisplay(state.quotes[index].carrier_code))} ${escapeHTML(carrierDisplay(state.quotes[index].service_code))}</h2><p>${escapeHTML(context.origin.country_code)} &rarr; ${escapeHTML(context.destination.country_code)}</p><div id="checkout-price">${feeRows(state.quotes[index])}</div><div id="checkout-booking-error" class="checkout-error" role="alert" hidden></div></div><aside id="checkout-next"><h2>Do you need customs documentation?</h2><p class="subtle">${context.customs_required?'International goods need reviewed customs details before a label can be created. You can prepare an invoice here, or supply the goods details from your existing invoice.':'This route does not require an export customs declaration.'}</p><div class="checkout-choices"><button id="checkout-customs-yes" class="primary">${context.customs_required?'Yes, prepare my customs documents':'Continue without export documents'}</button>${context.customs_required?'<button id="checkout-customs-own" class="secondary">I have my own invoice - enter carrier customs details</button>':''}</div></aside></div>`;
    $('#checkout-customs-yes').addEventListener('click',()=>context.customs_required?renderCheckoutCustoms():busy($('#checkout-customs-yes'),()=>prepareCustomerCheckout()));
    $('#checkout-customs-own')?.addEventListener('click',renderCheckoutCustoms);
  } catch(error) {$('#review-content').insertAdjacentHTML('beforeend',`<div class="checkout-error" role="alert">${escapeHTML(error.message)}</div>`);throw error;}
};

function resetCustomerCheckout() {
  customerCheckout.generation++;customerCheckout.index=null;customerCheckout.context=null;customerCheckout.prepared=null;
  $('#review-dialog').classList.remove('checkout-wide');
}
$('#review-dialog').addEventListener('close',resetCustomerCheckout);
const checkoutClearSessionBase=clearSession;
clearSession=function(){checkoutManifestInvoiceId=null;$('#shipment-receipt').disabled=true;resetCustomerCheckout();$('#review-dialog').close();checkoutClearSessionBase.apply(this,arguments);for(const prefix of ['origin','destination'])for(const field of addressNames){const input=$('#'+prefix+'-'+field);if(input)input.value='';}$('#item-description').value='';$('#hs-results').replaceChildren();};

// Standalone HS exploration is permitted; linked declaration editing happens in checkout.
$('#declaration-form').hidden=true;
$('#declaration-form').closest('.card').hidden=true;
$('#declaration-result').innerHTML='<div class="notice">Start with a shipping quote and select Book shipping label to prepare a declaration linked to your shipment. Final invoice PDFs are available after the booking is confirmed.</div>';
$('#declaration-form').closest('.card').querySelector('.subtle').textContent='Customs details and invoice references belong to a booking.';
$('#checkout-customs').hidden=true;
syncCustomsPanel=function(){ $('#checkout-customs').hidden=true; };

for(const id of ['item-description','decl-reference','decl-description','decl-hs','decl-quantity','decl-origin','decl-value','decl-weight','decl-shipping','qc-description','qc-hs','qc-reference','qc-value','qc-weight','qc-quantity']){
  const input=$('#'+id);if(!input)continue;input.value='';if(input.tagName==='TEXTAREA')input.defaultValue='';else input.defaultValue='';
}
$('#item-description').placeholder='e.g. Knitted cotton T-shirt for adults';
$('#item-description').addEventListener('input',()=>{ $('#hs-results').replaceChildren();$('#decl-hs').value='';$('#qc-hs').value='';$('#decl-reviewed').checked=false; });
let checkoutManifestInvoiceId=null;
$('#shipment-doc-json').hidden=true;
$('#shipment-doc-print').textContent='Download commercial invoice PDF';
$('#shipment-doc-print').insertAdjacentHTML('afterend','<button id="shipment-receipt" class="secondary" disabled>Download booking receipt PDF</button>');
$('#shipment-receipt').addEventListener('click',()=>{if(checkoutManifestInvoiceId)busy($('#shipment-receipt'),()=>downloadPartnerDocument('/api/v1/checkout/'+checkoutManifestInvoiceId+'/receipt.pdf'));});
$('#manifest-body').addEventListener('click',event=>{
  const button=event.target.closest('[data-manifest-detail]');if(!button)return;
  const row=manifestRecords().find(item=>item.id===button.dataset.manifestDetail);
  checkoutManifestInvoiceId=row?.id||null;
  $('#shipment-receipt').disabled=portal.profile?.workspace_role==='DISPATCHER'||!state.session||!row||!['BOOKED','DISPATCHED','IN_TRANSIT','DELIVERED','EXCEPTION'].includes(row.status);
  $('#shipment-doc-print').disabled=!state.session||!row?.customs_required||!['BOOKED','IN_TRANSIT','DELIVERED','EXCEPTION'].includes(row.status);
});
$('#shipment-doc-print').addEventListener('click',event=>{
  event.stopImmediatePropagation();
  if(!checkoutManifestInvoiceId)return;
  busy($('#shipment-doc-print'),()=>downloadPartnerDocument('/api/v1/checkout/'+encodeURIComponent(checkoutManifestInvoiceId)+'/commercial-invoice.pdf'));
},true);
