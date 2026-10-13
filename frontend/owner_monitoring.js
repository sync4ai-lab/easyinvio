// Embedded in index.html: owner command center and notification receipt visibility.
document.head.insertAdjacentHTML('beforeend','<style>#owner-command-center{min-width:0;margin:18px 0}#owner-command-center .responsive-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin:16px 0}#owner-command-center .card{min-width:0}@media(max-width:900px){#owner-command-center .responsive-grid{grid-template-columns:minmax(0,1fr)}}</style>');
$('#dashboard-metrics').insertAdjacentHTML('afterend', `<div id="owner-command-center" hidden>
 <div class="toolbar"><h2>Super-Admin Command Center</h2><label>Data environment<select id="owner-environment"><option value="PRODUCTION">Production accounts</option><option value="SANDBOX">Sandbox test accounts</option></select></label></div>
 <p id="owner-monitoring-source" class="notice"></p>
 <div class="responsive-grid"><article class="card"><h3>Network revenue and stored margin</h3><div class="scrolltable"><table><thead><tr><th>Currency</th><th>Gross revenue</th><th>Gross markup</th><th>Packages</th></tr></thead><tbody id="owner-currency-rows"></tbody></table></div><p class="subtle">Currencies are kept separate. Stored markup excludes operating expenses and is not net accounting profit.</p></article>
 <article class="card"><h3>Company billing pipeline</h3><div id="owner-billing-pipeline"></div><h3>Wallet payment states</h3><div id="owner-payment-pipeline"></div></article></div>
 <article class="card"><h3>Active AI support threads</h3><p id="owner-active-threads"></p><label>Support center scope<select id="owner-support-scope"><option value="ACTIVE">Active threads</option><option value="ALL">All threads including archives</option></select></label><p class="subtle">Active count is network-wide in this environment. The support center shows the latest 100 matching threads, with company context and actual notification receipt states.</p></article>
</div>`);
function ownerReportEnvironment(){return $('#owner-environment')?.value || 'PRODUCTION';}
function ownerActiveSupportOnly(){return $('#owner-support-scope')?.value !== 'ALL';}
function renderOwnerMonitoring(){
  const owner=portal.role==='SUPER_ADMIN' && (!state.session || portal.profile?.portal_role==='SUPER_ADMIN');
  $('#owner-command-center').hidden=!owner;
  if(!owner){for(const id of ['owner-currency-rows','owner-billing-pipeline','owner-payment-pipeline','owner-active-threads'])$('#'+id).replaceChildren();return;}
  $('#dashboard-title').textContent='Super-Admin Command Center';
  const report=state.session?portal.report:null;
  $('#owner-monitoring-source').textContent=report?.environment ? `${report.environment} DATA · ${report.start_date} to ${report.end_date} UTC. Billing status is current; payments and shipment totals use the selected period.` : 'Sign in as the verified platform owner to load database billing pipelines and cross-tenant support threads. Demo overview metrics remain illustrative.';
  $('#owner-currency-rows').innerHTML=(report?.totals_by_currency||[]).map(r=>`<tr><td>${escapeHTML(r.currency)}</td><td class="money">${money(r.revenue,r.currency)}</td><td>${money(r.margin,r.currency)}</td><td>${escapeHTML(r.package_count)}</td></tr>`).join('')||'<tr><td colspan="4">No booked shipping totals for this environment and period.</td></tr>';
  $('#owner-billing-pipeline').innerHTML=(report?.billing_pipeline||[]).map(r=>`<p><span class="tag">${escapeHTML(r.billing_status)}</span> ${escapeHTML(r.billing_plan)} <b>${escapeHTML(r.company_count)} companies</b></p>`).join('')||'<p class="subtle">No company billing states to display.</p>';
  $('#owner-payment-pipeline').innerHTML=(report?.payment_pipeline||[]).map(r=>`<p><span class="tag">${escapeHTML(r.status)}</span> ${escapeHTML(r.payment_count)} payments · ${money(r.amount,r.currency)}</p>`).join('')||'<p class="subtle">No wallet payment records in this period. Opening fixture credits are not card payments.</p>';
  $('#owner-active-threads').textContent=(report?.active_support||[]).map(r=>r.status+': '+r.ticket_count).join(' · ')||'No active support threads.';
  $('#primary-chart').querySelectorAll('svg text').forEach(node=>node.setAttribute('fill','#f1f5f9'));
}
const ownerRefreshBase=refreshPortal;
refreshPortal=async function(){$('#owner-environment').disabled=true;$('#owner-support-scope').disabled=true;try{await ownerRefreshBase();renderOwnerMonitoring();}finally{$('#owner-environment').disabled=false;$('#owner-support-scope').disabled=false;}};
const ownerRenderBase=renderPortal;
renderPortal=function(){ownerRenderBase();renderOwnerMonitoring();};
$('#owner-environment').addEventListener('change',()=>busy($('#dashboard-refresh'),refreshPortal));
$('#owner-support-scope').addEventListener('change',()=>busy($('#dashboard-refresh'),refreshPortal));
const ownerTicketsBase=renderTickets;
renderTickets=function(){
  ownerTicketsBase();
  $('#support-tickets').querySelectorAll('.support-ticket').forEach((node,index)=>{
    const ticket=portal.tickets[index];if(!ticket || ticket.demo)return;
    const info=document.createElement('p');info.className='subtle';
    const notifications=Array.isArray(ticket.notifications)?ticket.notifications:[];
    info.textContent=(portal.role==='SUPER_ADMIN'?(ticket.company_name||ticket.tenant_id)+' · ':'')+'WhatsApp: '+(notifications.length?notifications.map(n=>n.status+(n.error_code?' ('+n.error_code+')':'')).join(', '):(ticket.notification_explanation||'No WhatsApp alert has been queued.'));
    node.append(info);
  });
};
$('#wallet').insertAdjacentHTML('beforeend',`<article class="card" id="support-consent-card"><h2>Proactive WhatsApp alerts</h2><p>After your merchant number is verified and bound, explicitly opt in to carrier-exception notifications. Alerts require an enabled Twilio sender and approved template.</p><div class="actions"><button class="secondary" id="support-opt-in">Enable exception alerts</button><button class="secondary" id="support-opt-out">Disable exception alerts</button></div><p id="support-consent-result" class="subtle"></p></article>`);
for(const [id,enabled] of [['support-opt-in',true],['support-opt-out',false]])$('#'+id).addEventListener('click',()=>busy($('#'+id),async()=>{
  const result=await api('/api/v1/support/whatsapp/consent',{method:'POST',auth:true,body:{notification_opt_in:enabled}});
  $('#support-consent-result').textContent=result.notification_opt_in?'Verified number opted in. Delivery still depends on configured Twilio credentials.':'Exception alerts opted out.';
}));
const monitoringClearBase=clearSession;
clearSession=function(){$('#owner-environment').value='PRODUCTION';$('#owner-support-scope').value='ACTIVE';$('#support-consent-result').textContent='';monitoringClearBase();renderOwnerMonitoring();};
const monitoringRenderBase=renderPortal;
renderPortal=function(){monitoringRenderBase();$('#support-consent-card').hidden=!['OWNER','ADMIN'].includes(portal.profile?.workspace_role);};
