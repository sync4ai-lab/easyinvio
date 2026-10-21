(() => {
  'use strict';
  // Capability stays in the fragment/in memory. It is never sent in a URL,
  // stored in browser storage, forwarded to a carrier or exposed to analytics.
  const token = location.hash.slice(1);
  const apiBase = location.port === '5500' ? 'http://127.0.0.1:8000' : '';
  const content = document.getElementById('public-tracking-content');
  const message = document.getElementById('public-tracking-message');
  const refresh = document.getElementById('public-tracking-refresh');
  let requestDraft = null;
  const escape = value => { const node = document.createElement('span'); node.textContent = String(value ?? ''); return node.innerHTML.replaceAll('"', '&quot;').replaceAll("'", '&#39;'); };
  const portalLink = url => ['https://www.royalmail.com/track-your-item','https://www.evri.com/track-a-parcel'].includes(url) ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">Open carrier tracking</a>` : '';
  const human = value => String(value || 'Not yet available').toLowerCase().replaceAll('_', ' ');
  const when = value => value ? new Date(value).toLocaleString() : 'No carrier scan yet';
  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    if (!/^[A-Za-z0-9_-]{40,100}$/.test(token)) { message.textContent = 'Open the complete tracking link from your retailer. A tracking or order number alone cannot unlock shipment information.'; return; }
    message.textContent = 'Loading recorded carrier updates…';
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(apiBase + '/api/v1/public/tracking/resolve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }), credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer', signal: controller.signal });
      const result = await response.json();
      if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Tracking is temporarily unavailable.');
      content.innerHTML = result.shipments.map(shipment => {
        const delivered = shipment.status === 'DELIVERED';
        const moving = ['IN_TRANSIT','OUT_FOR_DELIVERY','AVAILABLE_FOR_PICKUP','CUSTOMS_PROCESSING'].includes(shipment.status);
        return `<section><span class="tracking-badge" data-status="${escape(shipment.status)}">${escape(human(shipment.status))}</span><h2>${escape(shipment.order_reference)}</h2><p>${escape(shipment.carrier)} · ${escape(shipment.tracking_number || 'Tracking number not yet assigned')}</p>
          <ol class="tracking-progress" aria-label="Delivery progress"><li class="done">Prepared</li><li class="${moving || delivered ? 'done' : ''}">With carrier</li><li class="${delivered ? 'done' : ''}">Delivered</li></ol>
          ${shipment.data_state === 'STALE' ? '<p>We are waiting for a fresh carrier update. A delivery delay has not been confirmed.</p>' : ''}
          ${portalLink(shipment.carrier_portal)}<p>${shipment.estimated_delivery_at ? 'Carrier delivery estimate: ' + escape(when(shipment.estimated_delivery_at)) : 'A delivery estimate has not been confirmed.'}</p>
          ${shipment.parcels.length > 1 ? shipment.parcels.map(piece => `<p>Parcel ${Number(piece.index)} · ${escape(piece.tracking_number || 'Not yet assigned')} · ${escape(human(piece.status))}</p>`).join('') : ''}
          ${shipment.lifecycle === 'RETURN_SHIPMENT' ? `<p>Return: ${escape(human(shipment.return_status))}. Return receipt does not confirm a purchase refund.</p>` : ''}
          <ol class="tracking-timeline">${shipment.timeline.length ? shipment.timeline.map(event => `<li><b>${escape(human(event.status))}</b><time>${escape(when(event.occurred_at))}</time><small>Update received ${escape(when(event.received_at))}${event.applied ? '' : ' · Delivery state unchanged'}</small></li>`).join('') : '<li>The carrier has not supplied a scan yet.</li>'}</ol></section>`;
      }).join('');
      message.textContent = result.support_message;
      const help = document.createElement('details');
      help.innerHTML = '<summary>Ask the retailer for help</summary><form><label>Your delivery, return or refund question<textarea required minlength="10" maxlength="1000" rows="4"></textarea></label><button type="submit">Send request to retailer</button><p role="status"></p></form>';
      help.querySelector('form').onsubmit = async event => {
        event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button');
        if (button.disabled) return; button.disabled = true;
        const note = form.querySelector('textarea').value.trim();
        if (!requestDraft || requestDraft.note !== note) requestDraft = { request_id: crypto.randomUUID(), note };
        try {
          const response = await fetch(apiBase + '/api/v1/public/tracking/help', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, ...requestDraft }), credentials: 'omit', referrerPolicy: 'no-referrer' });
          const answer = await response.json(); if (!response.ok) throw Error(typeof answer.detail === 'string' ? answer.detail : 'The request could not be recorded.');
          form.querySelector('[role=status]').textContent = answer.message || 'Your earlier request is already recorded.';
        } catch (error) { form.querySelector('[role=status]').textContent = error.message; }
        finally { button.disabled = false; }
      };
      content.append(help);
      if (result.whatsapp) {
        const label = document.createElement('p'); label.textContent = `WhatsApp${result.whatsapp.sandbox ? ' (test sandbox)' : ''}: ${result.whatsapp.number}`; content.append(label);
        const copy = document.createElement('button'); copy.textContent = 'Copy WhatsApp tracking request';
        copy.onclick = async () => { try { await navigator.clipboard.writeText('Track link ' + token); copy.textContent = 'Copied — send this in WhatsApp'; } catch { copy.textContent = 'Open your original tracking link or contact the retailer'; } };
        content.append(copy);
      }
    } catch (error) { content.replaceChildren(); message.textContent = error.name === 'AbortError' ? 'Tracking took too long to load. Please try again.' : error.message; }
    finally { clearTimeout(timer); refresh.disabled = false; }
  }
  refresh.addEventListener('click', load); load();
})();
