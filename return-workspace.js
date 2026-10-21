/* Authenticated return preparation in the Create shipment workspace. */
(() => {
  'use strict';
  const section = document.querySelector('#dispatch');
  const panel = document.createElement('div');
  panel.id = 'return-workspace'; panel.hidden = true;
  section.prepend(panel);
  const style = document.createElement('style');
  style.textContent = `#dispatch.return-active>:not(#return-workspace){display:none!important}
    #return-workspace{max-width:1160px;margin:0 auto;padding:20px;min-width:0}
    #return-workspace .return-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
    #return-workspace .return-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
    #return-workspace fieldset{border:1px solid #334155;border-radius:14px;padding:18px;margin:16px 0;min-width:0}
    #return-workspace input:not([type=checkbox]):not([type=radio]),#return-workspace select{width:100%;min-width:0}
    #return-workspace .return-actions{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0}
    #return-workspace .return-service{display:block;border:1px solid #334155;border-radius:12px;padding:15px;margin:12px 0}
    #return-workspace .return-service:has(input:checked){border-color:#10b981;background:#052e2a}
    #return-workspace .return-notice{white-space:pre-line;overflow-wrap:anywhere;margin:16px 0}
    @media(max-width:700px){#return-workspace{padding:12px}#return-workspace .return-columns{grid-template-columns:1fr}}
  `;
  document.head.append(style);
  let epoch = 0, facts = null, review = null, requestId = null, busy = false, committed = false;
  const scope = () => [epoch, state.session?.access_token, portal.profile?.tenant_id, state.assistance?.session_id].join(':');
  function reset() {
    epoch++; facts = null; review = null; requestId = null; busy = false; committed = false;
    panel.hidden = true; panel.replaceChildren(); section.classList.remove('return-active');
  }
  const setNotice = text => { const node = panel.querySelector('[data-return-notice]'); if (node) node.textContent = text; };
  const esc = value => escapeHTML(value == null ? '' : String(value));
  function field(label, name, value, options = {}) {
    return `<label>${esc(label)}<input name="${esc(name)}" value="${esc(value)}" ${options.required ? 'required' : ''}
      ${options.numeric ? 'inputmode="decimal"' : ''} maxlength="${options.max || 200}"></label>`;
  }
  function party(address) {
    return `<p>${['name','company','line1','line2','city','state','postal_code','country_code','phone','email']
      .map(key => address[key]).filter(Boolean).map(esc).join('<br>')}</p>`;
  }
  function render() {
    const edits = facts.edits, capabilities = facts.delivery_capabilities;
    panel.innerHTML = `<div class="pagehead"><div><span class="tag green">RETURN SHIPMENT</span>
      <h1>Create a return</h1><p>Original shipment ${esc(facts.reference)}</p></div>
      <button type="button" class="secondary" data-return-back>Back to Manifest &amp; Labels</button></div>
      <p class="notice">${esc(facts.notice)}</p>
      <form id="return-review-form"><div class="return-columns">
        <fieldset><legend>Return sender · original customer</legend>${party(facts.origin)}</fieldset>
        <fieldset><legend>Return destination · verified warehouse</legend>${party(facts.destination)}
          <p class="subtle">Manage the default RETURN address in Settings before preparing a new quote.</p></fieldset></div>
      <fieldset><legend>Returned parcel</legend><div class="return-fields">
        <label>Package type<select name="cargo_type">${['LETTER','PARCEL','PALLET','OVERLAND_FREIGHT'].map(t => `<option ${edits.cargo.cargo_type === t ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
        ${field('Packed weight · kg','actual_weight_kg',edits.cargo.actual_weight_kg,{required:true,numeric:true})}
        ${['length_cm','width_cm','height_cm'].map(k => field(k.replace('_cm',' · cm'),'cargo_'+k,edits.cargo[k],{numeric:true})).join('')}
        <label class="check"><input type="checkbox" name="stackable" ${edits.cargo.stackable ? 'checked' : ''}>Stackable</label>
        </div></fieldset>
      <fieldset><legend>Contents and return customs</legend>
        <p>Saved contents are shown below. Review actual returned goods, HS codes and values. The return declaration requires fresh confirmation.</p>
        ${edits.items.map((item,i) => `<fieldset data-return-item="${i}"><legend>Item ${i+1}</legend><div class="return-fields">
          ${field('Description',`item_${i}_description`,item.description,{required:true,max:500})}
          ${field('Quantity',`item_${i}_quantity`,item.quantity,{required:true,numeric:true})}
          ${field('Unit value',`item_${i}_unit_value`,item.unit_value,{required:true,numeric:true})}
          ${field('Unit net weight · kg',`item_${i}_unit_weight_kg`,item.unit_weight_kg,{required:true,numeric:true})}
          ${field('Country of manufacture',`item_${i}_origin_country`,item.origin_country,{required:true})}
          ${field('HS code',`item_${i}_hs_code`,item.hs_code)}
        </div></fieldset>`).join('')}
        <div class="return-fields">
        ${['sender_eori','recipient_eori','sender_vat','recipient_vat'].map(k => field(k.replaceAll('_',' '),k,edits[k],{max:40})).join('')}
        <label>Goods currency<select name="customs_currency">${['GBP','EUR','USD'].map(c => `<option ${edits.customs_currency === c ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
        <label>Incoterm<select name="incoterm">${['DAP','DDP','FCA','EXW'].map(c => `<option ${edits.incoterm === c ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
        <label>Postal customs form<select name="postal_form"><option value="">Carrier does not require a postal form</option><option ${edits.postal_form === 'CN22' ? 'selected' : ''}>CN22</option><option ${edits.postal_form === 'CN23' ? 'selected' : ''}>CN23</option></select></label>
        ${field('Declaration signer','customs_signer','')}
        <label class="check"><input type="checkbox" name="hs_codes_reviewed">I reviewed the goods and HS codes for this return</label>
        </div></fieldset>
      <fieldset><legend>Payment and customer instructions</legend><div class="return-fields">
        <label>Payment<select name="charge_bearer"><option value="RETAILER_PAY">Retailer pays from workspace billing</option>
          <option value="CUSTOMER_PAY" ${['OWNER','ADMIN'].includes(portal.profile?.workspace_role) ? '' : 'disabled'}>Customer pays by card</option></select></label>
        <label class="check"><input type="checkbox" name="paperless_requested" checked>Request carrier paperless drop-off where supported</label>
        <label class="check"><input type="checkbox" name="send_email" ${capabilities.email && facts.origin.email ? 'checked' : 'disabled'}>Email instructions to the original customer</label>
        <label class="check"><input type="checkbox" name="send_whatsapp" ${capabilities.whatsapp && facts.origin.phone ? 'checked' : 'disabled'}>WhatsApp instructions to the original customer</label>
        <label class="check"><input type="checkbox" name="permission">The customer agreed to receive these return instructions</label>
        </div><p class="subtle">${esc(capabilities.notice)} ${!capabilities.email || !capabilities.whatsapp ? 'An unavailable channel is disabled. You can still download or share the result manually.' : ''}</p>
        <p>For customer-paid returns, instructions contain a payment link first. A label is released only after verified payment and carrier confirmation.</p>
      </fieldset><div class="return-actions"><button type="submit" class="primary">Compare return services</button></div></form>
      <p data-return-notice class="return-notice" role="status" aria-live="polite"></p><div data-return-options></div><div data-return-result></div>`;
  }
  function input(name) { return panel.querySelector('#return-review-form').elements.namedItem(name); }
  function payload() {
    const edits = structuredClone(facts.edits);
    edits.cargo = {cargo_type:input('cargo_type').value,actual_weight_kg:input('actual_weight_kg').value.trim(),stackable:input('stackable').checked};
    for (const key of ['length_cm','width_cm','height_cm']) edits.cargo[key] = edits.cargo.cargo_type === 'LETTER' ? null : input('cargo_'+key).value.trim();
    edits.items.forEach((item,i) => {
      for (const key of ['description','quantity','unit_value','unit_weight_kg','origin_country','hs_code']) {
        const value = input(`item_${i}_${key}`).value.trim();
        item[key] = key === 'quantity' ? Number(value) : key === 'hs_code' ? value || null : value;
      }
      item.package_index = 1;
    });
    for (const key of ['sender_eori','recipient_eori','sender_vat','recipient_vat','customs_signer','postal_form']) edits[key] = input(key).value.trim() || null;
    edits.customs_currency = input('customs_currency').value; edits.incoterm = input('incoterm').value;
    edits.hs_codes_reviewed = input('hs_codes_reviewed').checked;
    return {request_id:requestId,shipment_id:facts.shipment_id,charge_bearer:input('charge_bearer').value,
      paperless_requested:input('paperless_requested').checked,edits,
      delivery:{email:input('send_email').checked,whatsapp:input('send_whatsapp').checked,customer_permission_confirmed:input('permission').checked}};
  }
  function results(data) {
    const node = panel.querySelector('[data-return-result]'); node.replaceChildren();
    if (data.status === 'QUOTED') {
      committed = false; review = data;
      panel.querySelectorAll('#return-review-form fieldset').forEach(n => n.disabled = false);
      const compare = panel.querySelector('#return-review-form [type=submit]'); if (compare) compare.disabled = false;
      const options = panel.querySelector('[data-return-options]');
      options.innerHTML = `<h2>Choose a return service</h2><p>Quote expires ${esc(new Date(data.expires_at).toLocaleString())}.
        ${data.partial ? 'Some providers did not respond. These are the available services, not a guaranteed market-wide lowest price.' : 'Available services are sorted by price.'}</p>
        ${data.rates.map((r,i) => `<label class="return-service"><input type="radio" name="return_offer" value="${esc(r.offer_id)}" ${i === 0 ? 'checked' : ''}>
          <b>${esc(r.carrier_code)} · ${esc(r.service_code || 'Return service')}</b> · ${esc(money(r.client_price_ex_tax,r.currency))}
          ${i === 0 ? '<span class="tag green">LOWEST AVAILABLE PRICE</span>' : ''}<br>
          <span>${r.delivery_days == null ? 'Delivery estimate unavailable' : esc(r.delivery_days)+' working days estimated'} · Paperless availability is confirmed by the carrier at booking.</span></label>`).join('')}
        <button type="button" class="primary" data-return-select>${data.charge_bearer === 'CUSTOMER_PAY' ? 'Create payment link for selected service' : 'Pay and create selected return label'}</button>`;
      setNotice('Review the selected price before confirming. No purchase has been made.'); return;
    }
    panel.querySelector('[data-return-options]').replaceChildren();
    const message = data.status === 'BOOKED' ? 'Return booked. The carrier label is ready.'
      : data.status === 'PAYMENT_REQUIRED' ? 'Customer payment is required. The return label will be created only after verified payment.'
      : data.message || 'Return confirmation needs checking. Do not buy another label or pay again. Refresh the existing result.';
    setNotice(message);
    if (data.checkout_url) {
      try {
        const url = new URL(data.checkout_url);
        if (url.protocol === 'https:' && url.hostname === 'checkout.stripe.com' && !url.username && !url.password) {
          const a = document.createElement('a'); a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer';
          a.textContent = 'Open or copy customer payment link'; a.className = 'secondary'; node.append(a);
        }
      } catch {}
    }
    for (const [key,title] of [['label_path','Download return label PDF'],['qr_path','Download carrier paperless code']]) {
      if (data.status === 'BOOKED' && /^\/api\/v1\/shipping\/[0-9a-f-]{36}\/documents\/(label|return-qr)$/i.test(data[key] || '')) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = title;
        button.addEventListener('click', async () => { try { await downloadPartnerDocument(data[key]); } catch (error) { setNotice(error.message); } }); node.append(button);
      }
    }
    for (const notice of data.notifications || []) {
      const p = document.createElement('p'); p.textContent = `${notice.kind === 'PAYMENT' ? 'Payment instructions' : 'Label instructions'} · ${notice.channel}: ${notice.state}${notice.error_code ? ' ('+notice.error_code+')' : ''}`; node.append(p);
    }
    const refresh = document.createElement('button'); refresh.type = 'button'; refresh.className = 'secondary'; refresh.textContent = 'Refresh payment, label and notification status'; refresh.dataset.returnRefresh = ''; node.append(refresh);
  }
  document.addEventListener('click', async event => {
    const open = event.target.closest('[data-prepare-return]');
    if (open) {
      event.preventDefault(); if (!state.session) return;
      setView('dispatch'); reset(); section.classList.add('return-active'); panel.hidden = false;
      panel.innerHTML = '<h1>Create a return</h1><p data-return-notice role="status">Loading saved shipment…</p><div data-return-options></div><div data-return-result></div><button type="button" class="secondary" data-return-back>Back to Manifest &amp; Labels</button>';
      const active = scope();
      try {
        const data = await api('/api/v1/shipping/returns/'+encodeURIComponent(open.dataset.prepareReturn)+'/preparation-context',{auth:true});
        if (active !== scope()) return; facts = data; render(); panel.scrollIntoView({block:'start'});
      } catch (error) {
        if (active === scope()) {
          if (error.quoteReference && /^[0-9a-f-]{36}$/i.test(error.quoteReference)) {
            requestId = error.quoteReference; committed = true; results({status:'PROCESSING'});
          }
          setNotice(error.message);
        }
      }
    }
    if (event.target.closest('[data-return-back]')) { setView('manifest'); return; }
    if (event.target.closest('[data-return-select]')) {
      if (busy || committed || !review) return;
      const offer = panel.querySelector('[name=return_offer]:checked')?.value;
      if (!offer) { setNotice('Choose a return service.'); return; }
      busy = true; committed = true; const active = scope();
      panel.querySelectorAll('#return-review-form fieldset,button[type=submit],[data-return-select]').forEach(n => n.disabled = true);
      setNotice('Confirming the selected return service…');
      try {
        const data = await api('/api/v1/shipping/returns/reviews/'+requestId+'/select',{auth:true,method:'POST',body:{offer_id:offer}});
        if (active === scope()) results(data);
      } catch (error) {
        if (active === scope()) { results({status:'PROCESSING'}); setNotice(error.message+' Refresh this return result before trying another booking.'); }
      } finally { if (active === scope()) busy = false; }
    }
    if (event.target.closest('[data-return-refresh]') && requestId && !busy) {
      busy = true; const active = scope();
      try {
        let data;
        try { data = await api('/api/v1/shipping/returns/reviews/'+requestId,{auth:true}); }
        catch (error) {
          if (error.status !== 404) throw error;
          data = await api('/api/v1/shipping/return-requests/'+requestId,{auth:true});
          if (data.status === 'BOOKED') data.label_path = data.label?.label_url;
        }
        if (active === scope()) results(data);
      }
      catch (error) { if (active === scope()) setNotice(error.message); }
      finally { if (active === scope()) busy = false; }
    }
  });
  panel.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || committed || !facts) return;
    requestId ||= crypto.randomUUID();
    const body = payload();
    if ((body.delivery.email || body.delivery.whatsapp) && !body.delivery.customer_permission_confirmed) { setNotice('Confirm customer permission or turn off customer notifications.'); return; }
    busy = true; const active = scope(); setNotice('Comparing return services…');
    panel.querySelectorAll('#return-review-form fieldset').forEach(node => node.disabled = true);
    const button = panel.querySelector('[type=submit]'); button.disabled = true;
    try {
      const data = await api('/api/v1/shipping/returns/review',{method:'POST',auth:true,body});
      if (active !== scope()) return; review = data; results(data);
      if (data.status === 'QUOTED') button.textContent = 'Compare fresh return rates';
    } catch (error) { if (active === scope()) setNotice(error.message); }
    finally { if (active === scope()) { busy = false; button.disabled = false; panel.querySelectorAll('#return-review-form fieldset').forEach(node => node.disabled = false); } }
  });
  panel.addEventListener('change', event => {
    if (committed || event.target.name === 'return_offer') return;
    requestId = null; review = null; panel.querySelector('[data-return-options]')?.replaceChildren();
  });
  // A successful quote may be refreshed with a new preparation key. Failed HTTP
  // attempts retain their key until the user edits, preserving receipt fencing.
  panel.addEventListener('click', event => { if (event.target.matches('[type=submit]') && review?.status === 'QUOTED') requestId = null; });
  const originalView = setView;
  setView = function(next) { reset(); return originalView.apply(this,arguments); };
  const originalClear = clearSession;
  clearSession = function() { reset(); return originalClear.apply(this,arguments); };
})();
