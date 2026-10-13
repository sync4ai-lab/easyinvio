// Embedded in index.html: authenticated live dispatch updates and statement audits.
const dispatchLive = {socket:null, session:null, retry:null, refresh:null};
function connectDispatchUpdates() {
 if (!state.session || !portal.profile?.tenant_id) return;
 if (dispatchLive.session === state.session && dispatchLive.socket && dispatchLive.socket.readyState < 2) return;
 clearTimeout(dispatchLive.retry);
 dispatchLive.socket?.close();
 dispatchLive.session = state.session;
 const session = state.session;
 const origin = new URL(API || location.origin, location.origin);
 origin.protocol = origin.protocol === 'https:' ? 'wss:' : 'ws:';
 origin.pathname = '/api/v1/dispatch-workspace/live'; origin.search = ''; origin.hash = '';
 const socket = new WebSocket(origin.href); dispatchLive.socket = socket;
 socket.onopen = () => { if(session===state.session)socket.send(JSON.stringify({access_token:session.access_token}));else socket.close(); };
 socket.onmessage = event => {
  if(session!==state.session)return;
  let message;try{message=JSON.parse(event.data);}catch{return;}
  if(!['shipment_changed','refresh_required'].includes(message.type))return;
  clearTimeout(dispatchLive.refresh);
  dispatchLive.refresh=setTimeout(async()=>{
   if(session!==state.session)return;
   try {
    if(enterprise.currentView==='workspace')await loadDispatchWorkspace();
    if(enterprise.currentView==='manifest'){$('#manifest-refresh').click();}
    if(enterprise.currentView==='wallet')await refreshBookingWallet();
   }catch{notify('Dispatch update received. Use Refresh to retry loading your records.',true);}
  },400);
 };
 socket.onclose=()=>{if(dispatchLive.socket!==socket)return;dispatchLive.socket=null;if(session===state.session)dispatchLive.retry=setTimeout(connectDispatchUpdates,5000);};
 socket.onerror=()=>socket.close();
}
window.addEventListener('easyinvio-session-ready',connectDispatchUpdates);
const liveNavigationBase=refreshEnterpriseNavigation;
refreshEnterpriseNavigation=function(...args){const result=liveNavigationBase(...args);if(!state.session){clearTimeout(dispatchLive.retry);clearTimeout(dispatchLive.refresh);dispatchLive.session=null;dispatchLive.socket?.close();dispatchLive.socket=null;}else connectDispatchUpdates();return result;};
$('#wallet').insertAdjacentHTML('beforeend', `<article class="card" id="invoice-audit-panel" style="margin-top:24px"><h2>Audit a carrier statement</h2><p class="subtle">Compare invoice weights and wholesale charges with confirmed booking snapshots. Commercial-address checks require stored verification evidence.</p><form id="invoice-upload-form"><label>Statement reference<input name="invoice_reference" required maxlength="100" placeholder="INV-2026-10-001"></label><label>CSV or XLSX statement<input name="file" type="file" accept=".csv,.xlsx" required></label><p class="subtle">One worksheet, at most 1,000 rows and 5 MB. Use kg and tax-exclusive wholesale totals. Consolidate split rows by carrier reference; formulas are not accepted.</p><button class="secondary" type="button" id="invoice-template">Download column template</button><button class="primary" type="submit">Audit &amp; save findings</button></form><div id="invoice-audit-result" role="status" style="margin-top:16px"></div><button class="secondary" id="invoice-disputes-refresh">View saved disputes</button></article>`);
$('#invoice-template').addEventListener('click',()=>download('easyinvio-statement-template.csv','upstream_shipment_id,currency,invoice_weight_kg,wholesale_cost,residential_fee\n','text/csv'));
$('#invoice-upload-form').addEventListener('submit',event=>{event.preventDefault();busy(event.target.querySelector('[type=submit]'),async()=>{
 if(!state.session||!['OWNER','ADMIN','ACCOUNTANT'].includes(portal.profile?.workspace_role))throw Error('Financial permission required.');
 const session=state.session;const body=new FormData(event.target);const file=body.get('file');if(file.size>5*1024*1024)throw Error('Upload a statement smaller than 5 MB.');
 const response=await fetch(API+'/api/v1/finance/audit-invoice-upload',{method:'POST',headers:{Authorization:'Bearer '+session.access_token},body});const result=await response.json();if(session!==state.session)return;if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Statement could not be audited. Check the template and try again.');
 $('#invoice-audit-result').innerHTML=(result.results||[]).map(row=>`<article class="notice"><b>${escapeHTML(row.upstream_shipment_id)} · ${escapeHTML(row.status)}</b>${row.reason?`<p>${escapeHTML(row.reason)}</p>`:`<p>Estimated monetary difference: ${escapeHTML(row.estimated_overcharge)} ${escapeHTML(row.currency)}. Comparison confidence: ${row.confidence_level}% against stored evidence.</p>`}${row.email_draft?`<details><summary>Saved complaint draft · not sent</summary><pre style="white-space:pre-wrap">${escapeHTML(row.email_draft)}</pre></details>`:''}</article>`).join('');
 event.target.reset();
});});
$('#invoice-disputes-refresh').addEventListener('click',event=>busy(event.target,async()=>{
 const data=await api('/api/v1/finance/billing-disputes',{auth:true});$('#invoice-audit-result').innerHTML=(data.disputes||[]).map(row=>`<article class="notice"><b>${escapeHTML(row.invoice_reference)} · ${escapeHTML(row.status)}</b><p>${escapeHTML(row.estimated_overcharge)} ${escapeHTML(row.currency)}</p><details><summary>Saved draft · no email sent</summary><pre style="white-space:pre-wrap">${escapeHTML(row.email_draft)}</pre></details></article>`).join('')||'<p class="notice">No saved disputes in this workspace.</p>';
}));
const auditNavigationBase=refreshEnterpriseNavigation;
refreshEnterpriseNavigation=function(...args){const result=auditNavigationBase(...args);$('#invoice-audit-panel').hidden=!state.session||!['OWNER','ADMIN','ACCOUNTANT'].includes(portal.profile?.workspace_role);if(!state.session){$('#invoice-upload-form').reset();$('#invoice-audit-result').replaceChildren();}return result;};

window.addEventListener('easyinvio-session-ready',()=>{
 const parameters=new URLSearchParams(location.search);
 if(parameters.get('view')==='manifest'&&/^[0-9a-f-]{36}$/i.test(parameters.get('shipment_id')||'')){
  setView('manifest');
  history.replaceState(null,'',location.pathname+location.hash);
 }
});
