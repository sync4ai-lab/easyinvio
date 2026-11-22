/* Shared portal policy/claim APIs. No browser storage, automatic payments or HTML from AI. */
(() => {
  'use strict';
  const settings = document.querySelector('#settings');
  if (!settings) return;
  const panel = document.createElement('article'); panel.className = 'card'; panel.id = 'cx-policy-settings';
  panel.innerHTML = '<h2>Customer tracking and returns</h2><p>Only workspace owners and admins can change these settings.</p><label class="check"><input id="cx-public-optin" type="checkbox">Allow public tracking status (no names or addresses)</label><button type="button" id="cx-public-save" class="secondary" disabled>Save tracking choice</button><button type="button" id="cx-public-load" class="outline">Load current choice</button><form id="cx-policy-form"><label>Describe your return policy<textarea name="rules" maxlength="1000" required placeholder="Set a 30-day free return policy for UK orders, maximum GBP 10"></textarea></label><button class="secondary" type="submit">Preview return policy</button><button class="primary" type="button" id="cx-policy-confirm" hidden>Confirm this policy</button></form><p id="cx-policy-status" role="status" aria-live="polite"></p>';
  settings.append(panel);
  let proposal = null, policySession = null;
  const status = panel.querySelector('#cx-policy-status');
  const reset = () => { proposal = null; policySession = null; panel.querySelector('#cx-policy-confirm').hidden = true; };
  panel.querySelector('#cx-policy-form').addEventListener('input', reset);
  panel.querySelector('#cx-policy-form').addEventListener('submit', async event => {
    event.preventDefault(); reset(); const session = state.session, button = event.submitter; button.disabled = true;
    try { const result = await api('/api/v1/settings/return-policy/proposals', {method:'POST', auth:true, body:{text:event.target.elements.rules.value.trim()}}); if (session !== state.session) return; proposal = result.proposal_id; policySession = session; status.textContent = result.message; panel.querySelector('#cx-policy-confirm').hidden = false; }
    catch (error) { status.textContent = error.message; } finally { button.disabled = false; }
  });
  panel.querySelector('#cx-policy-confirm').onclick = async event => {
    if (!proposal || policySession !== state.session) return reset();
    const id = proposal, session = state.session; event.target.disabled = true;
    try { const result = await api('/api/v1/settings/return-policy/proposals/' + encodeURIComponent(id) + '/confirm', {method:'POST',auth:true}); if (session === state.session) { status.textContent = result.message; reset(); } }
    catch (error) { status.textContent = error.message; } finally { event.target.disabled = false; }
  };
  panel.querySelector('#cx-public-load').onclick = async () => { const session = state.session; try { const result = await api('/api/v1/settings/public-tracking',{auth:true}); if (session === state.session) { panel.querySelector('#cx-public-optin').checked = result.enabled; panel.querySelector('#cx-public-save').disabled = false; } } catch (error) { status.textContent = error.message; } };
  panel.querySelector('#cx-public-save').onclick = async () => { try { await api('/api/v1/settings/public-tracking',{method:'PUT',auth:true,body:{enabled:panel.querySelector('#cx-public-optin').checked}}); status.textContent = 'Tracking publication choice saved.'; } catch (error) { status.textContent = error.message; } };
  const dialog = document.createElement('dialog'); dialog.id = 'cx-claim-dialog';
  dialog.innerHTML = '<button type="button" id="cx-claim-close" class="outline">Close</button><h2>Report a lost or damaged parcel</h2><p>This records evidence for review. It does not approve a claim or payment.</p><form id="cx-claim-form"><label>Shipment or tracking reference<input name="reference" required maxlength="200"></label><label>Issue<select name="reason"><option value="DAMAGED">Damaged</option><option value="LOST">Lost</option></select></label><label>What happened?<textarea name="description" minlength="10" maxlength="1800" required></textarea></label><label>Item value (GBP)<input name="value" type="number" min="0.01" max="50000" step="0.01" required></label><label>Photo of damage and packaging (JPEG/PNG, up to 5 MB)<input name="photo" type="file" accept="image/jpeg,image/png"></label><button type="submit" class="primary">Save claim evidence</button></form><p id="cx-claim-status" role="status" aria-live="polite"></p>';
  document.body.append(dialog);
  const open = document.createElement('button'); open.type = 'button'; open.className = 'secondary'; open.textContent = 'Report lost or damaged parcel';
  document.querySelector('#manifest .pagehead')?.append(open);
  let claimRequestId=null,claimDossierId=null,claimSession=null;
  open.onclick = () => { claimRequestId=crypto.randomUUID();claimDossierId=null;claimSession=state.session;dialog.querySelectorAll('input,select').forEach(input=>input.disabled=false); dialog.querySelector('#cx-claim-form').reset(); dialog.querySelector('#cx-claim-status').textContent = ''; dialog.showModal(); };
  dialog.querySelector('#cx-claim-close').onclick = () => dialog.close();
  dialog.querySelector('#cx-claim-form').onsubmit = async event => {
    event.preventDefault(); const session = state.session, fields = event.target.elements, button = event.submitter, output = dialog.querySelector('#cx-claim-status');
    const file = fields.photo.files[0]; if (file && (file.size > 5000000 || !['image/png','image/jpeg'].includes(file.type))) { output.textContent = 'Use a JPEG/PNG photo up to 5 MB.'; return; }
    button.disabled = true;
    try {
      if (claimSession !== session) return;
      let result = claimDossierId ? await api('/api/v1/agents/claims/'+encodeURIComponent(claimDossierId),{method:'PATCH',auth:true,body:{description:fields.description.value.trim(),item_value_gbp:fields.value.value}}) : await api('/api/v1/agents/claims/intake', {method:'POST',auth:true,body:{request_id:claimRequestId,reference:fields.reference.value.trim(),reason:fields.reason.value,description:fields.description.value.trim(),item_value_gbp:fields.value.value}});
      if (session !== state.session) return;
      claimDossierId=result.dossier_id;fields.reference.disabled=true;fields.reason.disabled=true;
      if (file) { const response = await fetch('/api/v1/agents/claims/' + encodeURIComponent(result.dossier_id) + '/evidence', {method:'POST',headers:{'Authorization':'Bearer ' + session.access_token,'Content-Type':file.type},body:file,signal:AbortSignal.timeout(15000)}); const data = await response.json(); if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Evidence upload failed; your case is saved.'); result = data; }
      if (session === state.session) output.textContent = result.message;
    } catch (error) { if (session === state.session) output.textContent = error.message; } finally { button.disabled = false; }
  };
  window.addEventListener('easyinvio-session-ready', reset);
  new MutationObserver(() => { if (!document.body.classList.contains('auth-ready')) { reset(); claimSession=null;claimDossierId=null;claimRequestId=null;dialog.close(); dialog.querySelector('form').reset(); panel.querySelector('#cx-public-save').disabled=true;panel.querySelector('#cx-public-optin').checked=false;status.textContent = ''; } }).observe(document.body,{attributes:true,attributeFilter:['class']});
})();
