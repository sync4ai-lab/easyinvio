/* Shared authenticated tracking workspace. Uses the existing session-aware api(). */
(() => {
  'use strict';
  const escape = value => { const node = document.createElement('span'); node.textContent = String(value ?? ''); return node.innerHTML.replaceAll('"', '&quot;').replaceAll("'", '&#39;'); };
  const portalLink = url => ['https://www.royalmail.com/track-your-item','https://www.evri.com/track-a-parcel'].includes(url) ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">Open carrier tracking</a>` : '';
  const human = value => String(value || 'Not available').toLowerCase().replaceAll('_', ' ');
  const when = value => value ? new Date(value).toLocaleString() : 'No carrier scan yet';
  const badge = value => `<span class="tracking-badge" data-status="${escape(value)}">${escape(human(value))}</span>`;
  let generation = 0, detailGeneration = 0, preferenceGeneration = 0, page = 1, activeView = 'all', current = null;
  const contextKey = () => JSON.stringify([portal.profile?.tenant_id, state.assistance?.tenant_id, state.assistance?.session_id || state.assistance?.id, portal.role, portal.profile?.workspace_role]);
  const admin = () => portal.role === 'SUPER_ADMIN' && portal.profile?.portal_role === 'SUPER_ADMIN';
  const writable = () => !admin() && ['OWNER', 'ADMIN', 'DISPATCHER'].includes(portal.profile?.workspace_role);
  const prefix = () => admin() ? '/api/v1/admin/tracking' : '/api/v1/tracking';
  const section = document.createElement('section'); section.id = 'tracking'; section.hidden = true;
  section.innerHTML = `<div class="pagehead"><div><div class="eyebrow">Shipping visibility</div><h1 id="tracking-title">Shipment tracking</h1><p>Shipments, returns and delivery exceptions in one place.</p></div><div class="tracking-actions"><button class="secondary" id="tracking-preferences">Notification preferences</button><button class="secondary" id="tracking-reload">Refresh view</button></div></div>
    <div class="tracking-toolbar"><label>Order or tracking reference<input id="tracking-search" type="search" maxlength="120" placeholder="Search order, tracking or return reference"></label>
    <label id="tracking-tenant-wrap" hidden>Tenant ID<input id="tracking-tenant" placeholder="All authorized workspaces"></label>
    <label>Carrier<input id="tracking-carrier" maxlength="50" placeholder="All carriers"></label><label>Destination<input id="tracking-country" maxlength="2" placeholder="e.g. GB"></label>
    <label>From<input id="tracking-start" type="date"></label><label>To<input id="tracking-end" type="date"></label><button class="primary" id="tracking-find">Search</button></div>
    <div id="tracking-cards" class="tracking-cards"></div><div id="tracking-message" role="status" aria-live="polite"></div>
    <article class="card"><div class="scrolltable"><table><thead><tr><th>Order / parcel</th><th>Carrier</th><th>Status</th><th>Last carrier update</th><th>Attention</th></tr></thead><tbody id="tracking-rows"></tbody></table></div>
    <div class="tracking-actions"><button class="secondary" id="tracking-prev">Previous</button><span id="tracking-page"></span><button class="secondary" id="tracking-next">Next</button></div></article>
    <div id="tracking-health"></div>`;
  document.querySelector('main').append(section);
  const drawer = document.createElement('dialog'); drawer.className = 'tracking-drawer'; drawer.setAttribute('aria-labelledby', 'tracking-detail-title');
  drawer.innerHTML = `<header><h2 id="tracking-detail-title">Shipment detail</h2><button class="secondary" id="tracking-detail-close" aria-label="Close shipment details">Close</button></header><div id="tracking-detail-content" aria-live="polite"></div>`;
  document.body.append(drawer);
  const preferences = document.createElement('dialog'); preferences.className = 'tracking-drawer'; preferences.setAttribute('aria-label', 'Tracking notification preferences');
  preferences.innerHTML = `<header><h2>Tracking preferences</h2><button class="secondary" id="tracking-pref-close">Close</button></header><form id="tracking-pref-form"><label class="check"><input name="in_app_enabled" type="checkbox">In-app milestone notifications</label>
    <div class="tracking-toolbar"><label>Flag shipments with no carrier update after (hours)<input name="stale_hours" type="number" min="12" max="720" required></label><label id="tracking-pref-interval">Carrier refresh interval (minutes)<input name="poll_interval_minutes" type="number" min="60" max="1440" required></label></div>
    <details><summary>Advanced milestone selection</summary><div id="tracking-pref-events"></div></details><p class="tracking-muted">Choose which future carrier updates appear in Recent milestones. Selecting an event does not change shipment status or add past updates.</p><button class="primary" type="submit">Save preferences</button><p id="tracking-pref-message" role="status"></p></form>`;
  document.body.append(preferences);
  const global = document.createElement('form'); global.className = 'tracking-global'; global.hidden = true;
  global.innerHTML = '<input type="search" aria-label="Find an Order" maxlength="120" placeholder="Find an Order"><button class="secondary">Track</button>';
  document.querySelector('.topbar-actions').insertBefore(global, document.getElementById('identity-user-widget'));
  const allowed = allowedEnterpriseViews;
  allowedEnterpriseViews = function () {
    const views = allowed.apply(this, arguments);
    enterpriseNavItems.tracking = [admin() ? 'Control Tower' : 'Shipment tracking', 'route'];
    return state.session && views.length ? [...new Set([...views, 'tracking'])] : views;
  };
  const render = renderAccount;
  renderAccount = function () { const result = render.apply(this, arguments); global.hidden = !state.session; return result; };
  const view = setView;
  setView = function (next) {
    const result = view.apply(this, arguments);
    if (next === 'tracking' && state.session && !section.hidden) load();
    else if (next !== 'tracking') { generation++; drawer.close(); }
    return result;
  };
  const clear = clearSession;
  clearSession = function () {
    generation++; detailGeneration++; preferenceGeneration++; current = null; page = 1; activeView = 'all';
    drawer.close(); preferences.close(); section.hidden = true; global.hidden = true;
    global.querySelector('input').value = ''; document.getElementById('tracking-pref-form').reset();
    document.getElementById('tracking-pref-events').replaceChildren(); document.getElementById('tracking-pref-message').textContent = '';
    for (const id of ['tracking-rows', 'tracking-cards', 'tracking-detail-content', 'tracking-health', 'tracking-message']) document.getElementById(id).replaceChildren();
    for (const id of ['tracking-search', 'tracking-tenant', 'tracking-carrier', 'tracking-country', 'tracking-start', 'tracking-end']) document.getElementById(id).value = '';
    return clear.apply(this, arguments);
  };
  const timeline = events => events.length ? `<ol class="tracking-timeline">${events.map(event => `<li><b>${escape(human(event.status))}</b><time>${escape(when(event.occurred_at))}</time><small>Received ${escape(when(event.received_at))} · ${escape(event.source)}${event.applied ? '' : ' · Update stored; current state retained'}</small>${event.location ? `<small>${escape(event.location)}</small>` : ''}</li>`).join('')}</ol>` : '<p class="tracking-muted">The carrier has not supplied a tracking scan yet.</p>';
  async function load() {
    const epoch = ++generation; const isAdmin = admin(); const context = contextKey();
    document.getElementById('tracking-title').textContent = isAdmin ? 'Operations Control Tower' : 'Shipment tracking';
    document.getElementById('tracking-tenant-wrap').hidden = !isAdmin;
    document.getElementById('tracking-preferences').hidden = isAdmin;
    const params = new URLSearchParams({ q: document.getElementById('tracking-search').value.trim(), view: activeView, page: String(page) });
    for (const name of ['carrier', 'country', 'start', 'end']) { const value = document.getElementById('tracking-' + name).value; if (value) params.set(name, value); }
    if (isAdmin && document.getElementById('tracking-tenant').value.trim()) params.set('tenant_id', document.getElementById('tracking-tenant').value.trim());
    document.getElementById('tracking-message').textContent = 'Loading recorded shipment activity…';
    try {
      const supplementary = api(isAdmin ? '/api/v1/admin/tracking/health' : '/api/v1/tracking/notifications', { auth: true })
        .then(value => ({value}), error => ({error}));
      const result = await api(prefix() + '/shipments?' + params, { auth: true });
      if (epoch !== generation || context !== contextKey()) return;
      const cards = [['all','All shipments',result.counts.total],['IN_TRANSIT','In transit',result.counts.in_transit],['OUT_FOR_DELIVERY','Out for delivery',result.counts.out_for_delivery],['DELIVERED','Delivered',result.counts.delivered],['EXCEPTION','Delivery exceptions',result.counts.exceptions],['STALE','Needs tracking review',result.counts.stale],['RETURNS','Returns awaiting receipt',result.counts.returns],['CUSTOMER_REQUESTS','Customer requests',result.counts.customer_requests]];
      document.getElementById('tracking-cards').innerHTML = cards.map(([key,label,count]) => `<button data-tracking-filter="${key}" aria-pressed="${activeView === key}"><span>${label}</span><strong>${Number(count)}</strong></button>`).join('');
      document.getElementById('tracking-message').textContent = 'Purchase refund status is shown only when an authorized order/payment source confirms it.';
      document.getElementById('tracking-rows').innerHTML = result.shipments.length ? result.shipments.map(item => `<tr><td><button class="tracking-ref" data-tracking-open="${escape(item.id)}">${escape(item.order_reference)}</button><br><small>${escape(item.tracking_number || 'Tracking not yet assigned')}</small>${isAdmin ? `<br><small>${escape(item.tenant_name)} · ${escape(item.tenant_id)}</small>` : ''}</td><td>${escape(item.carrier)}${isAdmin ? `<br><small>${escape(item.provider)}</small>` : ''}</td><td>${badge(item.status)}</td><td>${escape(when(item.last_event_at))}</td><td>${item.data_state === 'STALE' ? badge('STALE') : escape(human(item.data_state))}${item.refresh.error_code ? `<br>${escape(human(item.refresh.error_code))}` : ''}</td></tr>`).join('') : '<tr><td colspan="5">No matching shipments. Try the exact order/tracking reference or a wider date range.</td></tr>';
      document.getElementById('tracking-page').textContent = 'Page ' + page;
      document.getElementById('tracking-prev').disabled = page === 1; document.getElementById('tracking-next').disabled = !result.has_more;
      if (isAdmin) {
        const extra = await supplementary; if (epoch !== generation || context !== contextKey()) return;
        if (extra.error) { document.getElementById('tracking-health').textContent = 'Could not load synchronization health. Refresh to try again.'; return; }
        const health = extra.value;
        document.getElementById('tracking-health').innerHTML = `<article class="card"><h2>Synchronization health</h2><p>${health.polling_enabled ? 'Read-only carrier reconciliation enabled.' : 'Scheduled polling is off; signed webhooks remain active.'}</p>${health.jobs.length ? health.jobs.map(job => `<p><button class="tracking-ref" data-tracking-open="${escape(job.shipment_id)}">${escape(job.company_name)}</button> · ${escape(human(job.state))} · ${escape(human(job.error_code))} · ${Number(job.attempts)} attempts</p>`).join('') : '<p>No recorded refresh failures.</p>'}</article>`;
      } else {
        document.getElementById('tracking-health').replaceChildren();
        const extra = await supplementary;
        if (epoch !== generation || context !== contextKey()) return;
        if (extra.error) { document.getElementById('tracking-health').textContent = 'Could not load recent milestones. Refresh to try again.'; return; }
        const updates = extra.value;
        if (epoch !== generation || context !== contextKey()) return;
        const notices = updates.notifications || [];
        document.getElementById('tracking-health').innerHTML = notices.length ? `<details class="card"><summary>Recent milestones (${notices.length})</summary>${notices.slice(0,10).map(item => `<p><button class="tracking-ref" data-tracking-open="${escape(item.shipment_id)}">${escape(item.customer_reference || 'Shipment')}</button> · ${escape(human(item.category))} · ${escape(when(item.created_at))}</p>`).join('')}</details>` : '';
      }
    } catch (error) { if (epoch === generation) { document.getElementById('tracking-rows').replaceChildren(); document.getElementById('tracking-message').textContent = error.message; } }
  }
  async function open(id) {
    const epoch = ++detailGeneration; const context = contextKey(); drawer.showModal(); document.getElementById('tracking-detail-content').textContent = 'Loading shipment history…';
    try {
      const result = await api(prefix() + '/shipments/' + encodeURIComponent(id), { auth: true });
      if (epoch !== detailGeneration || !drawer.open || context !== contextKey()) return;
      current = { id, result }; document.getElementById('tracking-detail-title').textContent = result.order_reference;
      document.getElementById('tracking-detail-content').innerHTML = `${admin() ? `<p class="tracking-tenant-context">Selected workspace: <b>${escape(result.shipments[0]?.tenant_name)}</b><br>${escape(result.shipments[0]?.tenant_id)}</p>` : ''}<div class="tracking-actions">${admin() || writable() ? `<button class="secondary" data-tracking-refresh="${escape(id)}">Request carrier refresh</button>` : ''}${writable() ? '<button class="primary" id="tracking-share">Create secure tracking link</button>' : ''}${admin() || writable() ? '<button class="secondary" id="tracking-review">Review exception</button>' : ''}${admin() ? `<button class="secondary" data-tracking-retry="${escape(id)}">Retry failed refresh</button>` : ''}</div><div id="tracking-detail-feedback" role="status"></div>
        ${result.shipments.map(item => `<article class="tracking-parcel"><h3>${escape(item.carrier)} · ${escape(item.order_reference)}</h3>${badge(item.status)}<p>${escape(item.tracking_number || 'Tracking number unavailable')}</p>${portalLink(item.carrier_portal)}${item.lifecycle === 'RETURN_SHIPMENT' ? `<p>Return: ${escape(human(item.return_status))}</p>` : ''}${item.review?.state ? `<p>Internal review: ${escape(human(item.review.state))}</p><p>${escape(item.review.note)}</p>` : ''}${item.estimated_delivery_at ? `<p>Carrier estimate: ${escape(when(item.estimated_delivery_at))}</p>` : '<p class="tracking-muted">No confirmed delivery estimate.</p>'}${item.parcels.map(piece => `<p>Parcel ${Number(piece.index)} · ${escape(piece.tracking_number || 'Not yet assigned')} · ${escape(human(piece.status))}</p>`).join('')}${timeline(item.timeline)}</article>`).join('')}
        <h3>Returns</h3>${result.returns.length ? result.returns.map(item => `<article class="tracking-parcel">${badge(item.return_status)}<p>${escape(item.tracking_number || 'Return tracking not yet assigned')}</p>${timeline(item.timeline)}</article>`).join('') : '<p class="tracking-muted">No linked return shipment is recorded.</p>'}<h3>Purchase refund</h3><p>${escape(result.refund.message)}</p><h3>Customer requests</h3>${(result.customer_requests || []).length ? result.customer_requests.map(item => `<article class="tracking-parcel">${badge(item.state)}<p>${escape(item.note)}</p><small>${escape(when(item.created_at))}</small></article>`).join('') : '<p class="tracking-muted">No customer help requests.</p>'}<div id="tracking-share-links"></div>`;
      const carrierRefresh = drawer.querySelector('[data-tracking-refresh]');
      if (carrierRefresh && result.shipments.find(item => item.id === id)?.refresh?.available === false) {
        carrierRefresh.disabled = true; carrierRefresh.textContent = 'Carrier refresh unavailable';
        carrierRefresh.title = 'Polling is not enabled for this connection. Recorded updates and configured webhooks remain available.';
      }
      if (writable()) {
        const links = await api('/api/v1/tracking/shipments/' + encodeURIComponent(id) + '/share-links', { auth: true });
        if (epoch !== detailGeneration || !drawer.open || context !== contextKey()) return;
        document.getElementById('tracking-share-links').innerHTML = links.links.length ? '<h3>Issued tracking links</h3>' + links.links.map(link => `<p>Expires ${escape(when(link.expires_at))} ${link.revoked_at ? '· Revoked' : `<button class="secondary" data-tracking-revoke="${escape(link.id)}">Revoke</button>`}</p>`).join('') : '';
      }
    } catch (error) { if (epoch === detailGeneration && drawer.open) document.getElementById('tracking-detail-content').textContent = error.message; }
  }
  async function showPreferences() {
    const epoch = ++preferenceGeneration, context = contextKey(), session = state.session;
    const form = document.getElementById('tracking-pref-form');
    form.reset(); document.getElementById('tracking-pref-events').replaceChildren();
    for (const element of form.elements) element.disabled = true;
    document.getElementById('tracking-pref-message').textContent = 'Loading preferences...';
    if (!preferences.open) preferences.showModal();
    try {
      const result = await api('/api/v1/tracking/preferences', { auth: true });
      if (epoch !== preferenceGeneration || !preferences.open || session !== state.session || context !== contextKey()) return;
      form.elements.in_app_enabled.checked = result.preferences.in_app_enabled;
      form.elements.stale_hours.value = result.preferences.stale_hours;
      form.elements.poll_interval_minutes.value = result.preferences.poll_interval_minutes;
      document.getElementById('tracking-pref-interval').hidden = !result.refresh_enabled;
      document.getElementById('tracking-pref-events').innerHTML = ['IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','RETURNED_TO_SENDER','AVAILABLE_FOR_PICKUP'].map(value => `<label class="check"><input type="checkbox" name="category" value="${value}" ${result.preferences.categories.includes(value) ? 'checked' : ''}>${escape(human(value))}</label>`).join('');
      const editable = ['OWNER','ADMIN'].includes(portal.profile?.workspace_role);
      for (const element of form.elements) element.disabled = !editable;
      form.querySelector('[type=submit]').hidden = !editable;
      document.getElementById('tracking-pref-message').textContent = editable ? '' : 'Only workspace owners and admins can change these preferences.';
    } catch (error) {
      if (epoch === preferenceGeneration && preferences.open) document.getElementById('tracking-pref-message').textContent = error.message;
    }
  }
  preferences.addEventListener('close', () => { if (!preferences.open) preferenceGeneration++; });
  document.getElementById('tracking-pref-form').addEventListener('change', () => {
    document.getElementById('tracking-pref-message').textContent = 'Unsaved changes.';
  });
  document.getElementById('tracking-pref-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget;
    if (!['OWNER','ADMIN'].includes(portal.profile?.workspace_role) || form.querySelector('[type=submit]').disabled) return;
    const epoch = preferenceGeneration, session = state.session, context = contextKey();
    const body = { in_app_enabled: form.elements.in_app_enabled.checked, stale_hours: Number(form.elements.stale_hours.value), poll_interval_minutes: Number(form.elements.poll_interval_minutes.value), categories: [...form.querySelectorAll('[name=category]:checked')].map(node => node.value) };
    for (const element of form.elements) element.disabled = true;
    document.getElementById('tracking-pref-message').textContent = 'Saving preferences...';
    try {
      await api('/api/v1/tracking/preferences', { auth: true, method: 'PUT', body });
      if (epoch !== preferenceGeneration || !preferences.open || session !== state.session || context !== contextKey()) return;
      document.getElementById('tracking-pref-message').textContent = 'Preferences saved. Your choices apply to future carrier updates.';
      notify('Tracking preferences saved.');
      if (!section.hidden) void load();
    } catch (error) {
      if (epoch === preferenceGeneration && session === state.session && context === contextKey()) document.getElementById('tracking-pref-message').textContent = error.message;
    } finally {
      if (epoch === preferenceGeneration && session === state.session && context === contextKey()) for (const element of form.elements) element.disabled = false;
    }
  });
  global.addEventListener('submit', event => { event.preventDefault(); document.getElementById('tracking-search').value = global.querySelector('input').value; page = 1; activeView = 'all'; setView('tracking'); });
  document.getElementById('tracking-find').onclick = () => { page = 1; load(); };
  document.getElementById('tracking-search').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); page = 1; load(); } };
  document.getElementById('tracking-reload').onclick = () => load();
  document.getElementById('tracking-prev').onclick = () => { page--; load(); };
  document.getElementById('tracking-next').onclick = () => { page++; load(); };
  document.getElementById('tracking-detail-close').onclick = () => drawer.close();
  drawer.addEventListener('close', () => { detailGeneration++; current = null; });
  document.getElementById('tracking-pref-close').onclick = () => preferences.close();
  document.getElementById('tracking-preferences').onclick = () => showPreferences().catch(error => notify(error.message, true));
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-tracking-open],[data-tracking-filter],[data-tracking-refresh],[data-tracking-retry],[data-tracking-revoke],#tracking-share,#tracking-review');
    if (!button) return;
    if (button.dataset.trackingOpen) return open(button.dataset.trackingOpen);
    if (button.dataset.trackingFilter) { activeView = button.dataset.trackingFilter; page = 1; return load(); }
    if (button.disabled) return; button.disabled = true;
    const feedback = document.getElementById('tracking-detail-feedback');
    try {
      if (button.dataset.trackingRefresh || button.dataset.trackingRetry) {
        const id = button.dataset.trackingRefresh || button.dataset.trackingRetry;
        const result = await api(prefix() + '/shipments/' + encodeURIComponent(id) + (button.dataset.trackingRetry ? '/retry' : '/refresh'), { auth: true, method: 'POST' }); feedback.textContent = result.message;
      } else if (button.dataset.trackingRevoke) {
        if (button.dataset.confirmRevoke !== 'true') { button.dataset.confirmRevoke = 'true'; button.textContent = 'Confirm revoke link'; return; }
        await api('/api/v1/tracking/share-links/' + encodeURIComponent(button.dataset.trackingRevoke), { auth: true, method: 'DELETE' }); feedback.textContent = 'Tracking link revoked.'; button.textContent = 'Revoked';
      } else if (button.id === 'tracking-share' && current) {
        const result = await api('/api/v1/tracking/shipments/' + encodeURIComponent(current.id) + '/share', { auth: true, method: 'POST', body: { include_order: true, include_returns: false, expires_in_days: 7 } });
        const url = new URL(result.url); if (!['https:', 'http:'].includes(url.protocol) || url.pathname !== '/track') throw Error('Invalid tracking link returned.');
        feedback.replaceChildren(); const anchor = document.createElement('a'); anchor.href = url.href; anchor.textContent = url.href; anchor.className = 'tracking-link-output'; anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; feedback.append(anchor);
        const copy = document.createElement('button'); copy.className = 'secondary'; copy.textContent = 'Copy tracking link'; copy.onclick = async () => { try { await navigator.clipboard.writeText(url.href); copy.textContent = 'Copied'; } catch { copy.textContent = 'Select and copy the link above'; } }; feedback.append(copy);
      } else if (button.id === 'tracking-review' && current) {
        feedback.innerHTML = '<form id="tracking-review-form"><label>Review state<select name="state"><option>ACKNOWLEDGED</option><option>IN_REVIEW</option><option>ESCALATED</option><option>RESOLVED</option></select></label><label>Internal note<textarea name="note" required maxlength="1000"></textarea></label><button class="primary">Save internal review</button><p class="tracking-muted">This does not change the carrier event or confirm a refund.</p></form>';
        document.getElementById('tracking-review-form').onsubmit = async action => { action.preventDefault(); try { await api(prefix() + '/shipments/' + encodeURIComponent(current.id) + '/review', { auth: true, method: 'POST', body: { state: action.currentTarget.elements.state.value, note: action.currentTarget.elements.note.value } }); feedback.textContent = 'Internal review saved. Carrier events are unchanged.'; } catch (error) { notify(error.message, true); } };
      }
    } catch (error) { if (feedback) feedback.textContent = error.message; else notify(error.message, true); }
    finally { button.disabled = false; }
  });
  // Make existing shipment order references contextual entry points without changing
  // their label/document actions or replacing the manifest renderer.
  document.getElementById('manifest-body')?.addEventListener('click', event => {
    const reference = event.target.closest('.manifest-ref'); if (!reference || !state.session) return;
    const row = reference.closest('tr'); const action = row?.querySelector('[data-shipment-id],[data-manifest-id]');
    const known = (state.manifest || []).find(item => reference.textContent.includes(item.reference || item.id));
    const id = known?.id || action?.dataset.shipmentId; if (id) open(id);
  });
  document.getElementById('manifest-body')?.addEventListener('keydown', event => { if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('.manifest-ref')) { event.preventDefault(); event.target.click(); } });
  const renderManifestBase = renderManifest;
  renderManifest = function () { const result = renderManifestBase.apply(this, arguments); document.querySelectorAll('#manifest-body .manifest-ref').forEach(node => { node.tabIndex = 0; node.setAttribute('role', 'button'); node.setAttribute('aria-label', 'Open tracking for ' + node.textContent); }); return result; };
  const settings = document.getElementById('settings');
  if (settings) { const card = document.createElement('article'); card.className = 'card'; card.innerHTML = '<h2>Tracking notifications</h2><p>Choose in-app milestones and operational review thresholds.</p><button class="secondary">Tracking preferences</button>'; card.querySelector('button').onclick = () => showPreferences().catch(error => notify(error.message, true)); settings.append(card); }
  refreshEnterpriseNavigation(); global.hidden = !state.session;
})();
