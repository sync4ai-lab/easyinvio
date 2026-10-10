// Embedded in index.html: server-verified personas and administrative control hubs.
const enterprise = { tenants: [], carriers: [], margins: [], transactions: [], stores: [], editMargin: null, editCarrier: null, currentView: 'dashboard', generation: 0 };
const enterpriseViews = ['admin-clients', 'admin-carriers', 'admin-margins', 'stores'];
const mainContent = document.querySelector('main');
mainContent.insertAdjacentHTML('beforeend', `
<section id="admin-clients" hidden>
  <div class="pagehead"><div><div class="eyebrow">Platform / Client accounts node</div><h1>Client Accounts Hub</h1><p>Company profiles, billing plans and network transaction history.</p></div><button class="primary" id="tenant-new"><i data-lucide="building-2"></i>Onboard New Tenant</button></div>
  <div class="enterprise-banner" data-admin-source></div>
  <article class="card"><div class="toolbar"><input id="tenant-search" placeholder="Search company, email or workspace" aria-label="Search clients"><button class="secondary" data-admin-refresh="admin-clients">Refresh clients</button></div><div class="scrolltable"><table><thead><tr><th>Company / workspace</th><th>Billing / currency</th><th>Status</th><th>Environment</th><th>Configuration</th></tr></thead><tbody id="tenant-rows"></tbody></table></div></article>
  <article class="card" style="margin-top:20px"><div class="cardhead"><div><h2>Aggregate wallet transaction log</h2><p class="subtle">Newest 200 ledger entries. Currency values are kept separate.</p></div><button class="secondary" data-admin-refresh="transactions">Refresh log</button></div><div class="scrolltable"><table><thead><tr><th>Company</th><th>Entry</th><th>Balance movement</th><th>Reserved movement</th><th>Time</th></tr></thead><tbody id="transaction-rows"></tbody></table></div></article>
</section>
<section id="admin-carriers" hidden>
  <div class="pagehead"><div><div class="eyebrow">Platform / Carrier connectors</div><h1>Carrier Provider Settings</h1><p>Manage tenant-assigned accounts across the platform. Credentials remain on the server.</p></div><button class="primary" id="carrier-new"><i data-lucide="plug"></i>Add New Connection</button></div>
  <div class="enterprise-banner" data-admin-source></div>
  <div class="provider-grid"><article class="card"><span class="tag green">SUPPORTED ADAPTER</span><h2>EasyPost</h2><p class="subtle">Official v2 endpoint. Tenant-bound encrypted credentials.</p></article><article class="card"><span class="tag green">SUPPORTED ADAPTER</span><h2>LocalRegional</h2><p class="subtle">Compatible regional API protocol; server-approved HTTPS origins.</p></article><article class="card"><span class="tag green">READ-ONLY RATE ADAPTER</span><h2>Sendcloud</h2><p class="subtle">Use LocalRegional with the official Sendcloud endpoint and verified SENDCLOUD_METHODS limits. Native label purchase is not enabled.</p></article></div>
  <article class="card"><div class="cardhead"><h2>Network connections</h2><button class="secondary" data-admin-refresh="admin-carriers">Refresh</button></div><div class="scrolltable"><table><thead><tr><th>Account / company</th><th>Provider</th><th>Environment</th><th>Status / priority</th><th>Actions</th></tr></thead><tbody id="carrier-rows"></tbody></table></div></article>
</section>
<section id="admin-margins" hidden>
  <div class="pagehead"><div><div class="eyebrow">Platform / Pricing control</div><h1>Dynamic Margin Matrix</h1><p>Client and lane rules with exact Decimal values. Lower numeric priority wins.</p></div><button class="primary" id="margin-new"><i data-lucide="sliders-horizontal"></i>Add Pricing Rule</button></div>
  <div class="enterprise-banner" data-admin-source></div>
  <article class="card"><div class="toolbar"><select id="margin-tenant-filter" aria-label="Filter pricing by client"></select><button class="secondary" data-admin-refresh="admin-margins">Refresh rules</button></div><div class="scrolltable"><table><thead><tr><th>Company / rule</th><th>Lane / carrier</th><th>Formula</th><th>Priority</th><th>Status</th><th>Actions</th></tr></thead><tbody id="margin-rows"></tbody></table></div></article>
  <div class="notice">Deleting a rule retires it from price selection. Existing shipment prices and applied-rule references are retained.</div>
</section>
<section id="stores" hidden>
  <div class="pagehead"><div><div class="eyebrow">Workspace / Store integrations</div><h1>E-commerce store registry</h1><p>Manage your tenant's order import and tracking associations.</p></div><button id="store-new" class="primary">Register store</button></div>
  <div class="notice">The current connector framework simulates order import and tracking push-back. This registry does not install storefront apps or configure remote OAuth credentials.</div>
  <div id="store-list" class="provider-grid"></div><button class="secondary" id="store-refresh">Refresh stores</button>
</section>
`);
document.body.insertAdjacentHTML('beforeend', `
<dialog id="tenant-admin-dialog"><button class="close" data-enterprise-close="tenant-admin-dialog" aria-label="Close tenant form">×</button><h2>Onboard a customer</h2><p class="subtle">Creates the company and wallet. Existing Supabase Auth identity is optional.</p><form id="tenant-admin-form">
 <div class="fields"><div><label>Company name<input name="company_name" required maxlength="200"></label></div><div><label>Contact name<input name="contact_name" required maxlength="200"></label></div><div><label>Billing email<input name="billing_email" type="email" required></label></div><div><label>Street<input name="address_line1" required maxlength="200"></label></div><div><label>City<input name="city" required></label></div><div><label>Postcode<input name="postal_code" required></label></div><div><label>Country ISO<input name="country_code" value="GB" maxlength="3" required></label></div><div><label>Currency<select name="default_currency"><option>GBP</option><option>EUR</option><option>USD</option></select></label></div><div><label>Billing plan<select name="billing_plan"><option>PREPAID_WALLET</option><option>POSTPAID_30_DAY</option></select></label></div><div><label>Tax / VAT ID<input name="tax_id" maxlength="100"></label></div></div>
 <label>Existing owner Auth user UUID (optional)<input name="owner_auth_user_id" placeholder="Provision login separately in Supabase"></label><label class="check"><input name="is_sandbox" type="checkbox" checked>Sandbox customer</label><button class="primary full">Create customer account</button><p class="footnote">No password, invitation email or provider credentials are created by this form.</p>
</form></dialog>
<dialog id="margin-admin-dialog"><button class="close" data-enterprise-close="margin-admin-dialog" aria-label="Close pricing form">×</button><h2 id="margin-form-title">Add pricing rule</h2><form id="margin-admin-form">
 <label>Client account<select name="tenant_id" required></select></label><div class="fields"><div><label>Origin country (optional)<input name="origin_country" maxlength="3" placeholder="Any origin"></label></div><div><label>Destination country (optional)<input name="destination_country" maxlength="3" placeholder="Any destination"></label></div><div><label>Carrier code (optional)<input name="carrier_code" maxlength="100" placeholder="Any carrier"></label></div><div><label>Service code (optional)<input name="service_code" maxlength="100" placeholder="Any service"></label></div><div><label>Formula<select name="markup_type"><option value="PERCENTAGE">Percentage</option><option value="FLAT_RATE">Flat rate</option></select></label></div><div><label>Markup value<input name="markup_value" value="20" inputmode="decimal" required></label></div><div><label>Currency<select name="currency"><option>GBP</option><option>EUR</option><option>USD</option></select></label></div><div><label>Priority (lower wins)<input name="priority" type="number" min="0" max="1000000" step="1" value="100" required></label></div><div><label>Minimum markup<input name="minimum_markup" value="0.00" inputmode="decimal" required></label></div><div><label>Maximum markup (optional)<input name="maximum_markup" inputmode="decimal"></label></div><div><label>Billing tier (optional)<select name="billing_plan"><option value="">Any billing tier</option><option>PREPAID_WALLET</option><option>POSTPAID_30_DAY</option></select></label></div><div><label>Cargo type (optional)<select name="cargo_type"><option value="">Any cargo</option><option>LETTER</option><option>PARCEL</option><option>PALLET</option><option>OVERLAND_FREIGHT</option></select></label></div><div><label>Min volume m? (optional)<input name="min_volume_m3" inputmode="decimal"></label></div><div><label>Max volume m? (exclusive)<input name="max_volume_m3" inputmode="decimal"></label></div><div><label>Min weight kg (optional)<input name="min_weight_kg" inputmode="decimal"></label></div><div><label>Max weight kg (exclusive)<input name="max_weight_kg" inputmode="decimal"></label></div><div><label>Min wholesale cost (optional)<input name="min_wholesale_cost" inputmode="decimal"></label></div><div><label>Max wholesale cost (exclusive)<input name="max_wholesale_cost" inputmode="decimal"></label></div><div><label>Valid from (optional ISO timestamp)<input name="valid_from" placeholder="2026-10-10T00:00:00Z"></label></div><div><label>Valid until (optional ISO timestamp)<input name="valid_until" placeholder="No end date"></label></div></div><label>Carrier account ID (optional)<input name="carrier_account_id" placeholder="Tenant-assigned account UUID"></label><label class="check"><input name="is_active" type="checkbox" checked>Active in pricing selection</label><button class="primary full">Save pricing rule</button>
</form></dialog>
<dialog id="carrier-admin-dialog"><button class="close" data-enterprise-close="carrier-admin-dialog" aria-label="Close carrier form">×</button><h2 id="carrier-form-title">Add carrier connection</h2><form id="carrier-admin-form">
 <div id="carrier-create-fields"><label>Assigned client<select name="tenant_id" required></select></label><label>Account name<input name="account_name" maxlength="200" required></label><div class="fields"><div><label>Provider<select name="aggregator"><option>EASYPOST</option><option>REGIONAL</option></select></label></div><div><label>Environment<select name="environment"><option>TEST</option><option>LIVE</option></select></label></div></div><label>API endpoint<input name="api_base_url" value="https://api.easypost.com/v2" type="url" required></label><label>Regional provider code<input name="regional_provider_code" placeholder="Required for REGIONAL"></label><label>API key (write-only)<input name="api_key" type="password" autocomplete="new-password" required maxlength="4096"></label><label>Upstream account ID (optional)<input name="upstream_account_id"></label></div>
 <div class="fields"><div><label>Priority<input name="priority" value="100" type="number" min="0" max="1000000" step="1" required></label></div><div><label>Timeout seconds<input name="timeout_seconds" value="30" type="number" min="1" max="120" step="1" required></label></div></div><label class="check"><input name="is_active" type="checkbox">Enable provider for ratings</label><button class="primary full">Save connection</button><p class="footnote">Existing secrets are never returned. No carrier API calls are made by this form.</p>
</form></dialog>
<dialog id="store-admin-dialog"><button class="close" data-enterprise-close="store-admin-dialog" aria-label="Close store form">×</button><h2>Register a workspace store</h2><form id="store-admin-form"><label>Display name<input name="display_name" required maxlength="200"></label><label>Platform<select name="platform"><option>SHOPIFY</option><option>WOOCOMMERCE</option><option>AMAZON</option></select></label><button class="primary full">Register store</button></form></dialog>
<dialog id="retire-admin-dialog"><button class="close" data-enterprise-close="retire-admin-dialog" aria-label="Close retirement review">×</button><h2>Review configuration removal</h2><p id="retire-context" class="subtle"></p><p class="notice">This removes the configuration from active selection and preserves historical shipment references.</p><button id="retire-confirm" class="primary full">Retire configuration</button></dialog>
<dialog id="exception-sheet" class="exception-sheet"><button class="close" data-enterprise-close="exception-sheet" aria-label="Close exception drawer">×</button><div class="eyebrow">Proactive exception support</div><h2 id="exception-title"></h2><div class="notice" id="exception-summary"></div><div class="actions"><button class="secondary" id="exception-pod">View POD Token</button><button class="primary" id="exception-dispute">Auto-Draft Surcharge Dispute Ticket</button></div><p class="footnote">Review drafts before submission. No WhatsApp message or dispute is sent.</p></dialog>
`);
const personaControls = $('#role-admin').parentElement;
personaControls.classList.add('header-personas');
document.querySelector('.topbar-actions').prepend(personaControls);
const enterpriseNavItems = {
    dashboard: ['Overview', 'layout-dashboard'],
    'admin-clients': ['Client Accounts Node', 'building-2'],
    'admin-carriers': ['Carrier Connectors', 'plug'],
    'admin-margins': ['Margin Rule Matrix', 'sliders-horizontal'],
    dispatch: ['Speed Quote Matrix', 'send'], boxes: ['Box Profiles', 'boxes'],
    manifest: ['Manifest & Labels', 'package-check'], wallet: ['Wallet & Billing', 'wallet'],
    customs: ['Customs Harmonizer', 'shield-check'], stores: ['Store Integrations', 'store']
};
function allowedEnterpriseViews() {
    if (state.session && !portal.profile) return [];
    if (portal.role === 'SUPER_ADMIN' && (!state.session || portal.profile?.portal_role === 'SUPER_ADMIN'))
        return ['dashboard', 'admin-clients', 'admin-carriers', 'admin-margins'];
    if (portal.profile?.workspace_role === 'DISPATCHER') return ['dispatch', 'boxes', 'manifest'];
    if (portal.profile?.workspace_role === 'ACCOUNTANT') return ['dashboard', 'wallet', 'customs', 'stores'];
    if (state.session && portal.profile?.portal_role === 'SUPER_ADMIN') return ['dashboard'];
    return ['dashboard', 'dispatch', 'manifest', 'boxes', 'wallet', 'customs', 'stores'];
}
function enterpriseAdminGuard() {
    if (!allowedEnterpriseViews().includes('admin-clients')) throw Error('Platform-owner authorization is required.');
}
let enterpriseNavKey = '';
let enterpriseSession = state.session;
function refreshEnterpriseNavigation() {
    if (enterpriseSession !== state.session) {
        enterpriseSession = state.session; enterprise.generation++;
        for (const key of ['tenants','carriers','margins','transactions','stores']) enterprise[key]=[];
        for (const id of ['tenant-rows','carrier-rows','margin-rows','transaction-rows','store-list']) $('#'+id).replaceChildren();
        for (const id of ['tenant-admin-dialog','margin-admin-dialog','carrier-admin-dialog','retire-admin-dialog','store-admin-dialog','exception-sheet']) $('#'+id).close();
        $('#carrier-admin-form').reset();
    }
    const allowed = allowedEnterpriseViews();
    const key = allowed.join('|');
    if (key !== enterpriseNavKey) {
        enterpriseNavKey = key;
        const buttons = allowed.map(view => {
            const [label, icon] = enterpriseNavItems[view];
            const fallback=({dashboard:'grid','admin-clients':'grid','admin-carriers':'truck','admin-margins':'chart',dispatch:'truck',boxes:'box',manifest:'list',wallet:'wallet',customs:'globe',stores:'box'})[view];
            return `<button id="tab-${view}" role="tab" data-enterprise-view="${view}" aria-selected="${enterprise.currentView === view}"><span class="nav-symbol"><i data-lucide="${icon}"></i><svg class="icon-fallback" fill="none" stroke="currentColor" stroke-width="1.6"><use href="#i-${fallback}"></use></svg></span><span>${label}</span></button>`;
        }).join('');
        document.querySelector('.sidebar nav').innerHTML = buttons;
        document.querySelector('.mobile-nav').innerHTML = buttons.replaceAll('id="tab-', 'id="mobile-');
    }
    const warehouse = portal.profile?.workspace_role === 'DISPATCHER';
    const admin = portal.role === 'SUPER_ADMIN';
    if(!state.session&&admin)$('#mode-label').textContent='SAMPLE PLATFORM CONTROL PLANE · Sign in as an authorized owner to manage database configuration.';
    $('#role-admin').hidden = !!state.session && portal.profile?.portal_role !== 'SUPER_ADMIN';
    $('#role-client').hidden = !!state.session && portal.profile?.portal_role !== 'SUPER_ADMIN';
    $('.sidebar-caption').textContent = admin ? 'Platform control plane' : warehouse ? 'Warehouse operations' : 'Client workspace';
    $('#dashboard .quick-grid').hidden = admin || warehouse;
    $('#dashboard .support-card').hidden = warehouse;
    $$('[data-admin-source]').forEach(node => node.textContent = state.session
        ? 'OWNER-AUTHORIZED DATABASE CONTROLS · All mutations are validated server-side.'
        : 'SAMPLE CONTROL PLANE · Changes affect this browser session only. Sign in as an authorized platform owner to modify the database.');
    $('#dashboard').hidden = enterprise.currentView !== 'dashboard' || !allowed.includes('dashboard');
    if (allowed.length && !allowed.includes(enterprise.currentView)) setView(allowed[0]);
    refreshIcons();
}
const enterpriseRenderPortalBase = renderPortal;
const enterpriseFeeRowsBase=feeRows;
feeRows=function(rate){
    if(portal.profile?.workspace_role==='DISPATCHER')return '<p class="subtle">Customer quote shown above. Detailed billing and platform margins require a financial role.</p>';
    return enterpriseFeeRowsBase(rate);
};
renderPortal = function () {
    enterpriseRenderPortalBase();
    refreshEnterpriseNavigation();
};
const enterpriseSetViewBase = setView;
setView = function (view) {
    const allowed = allowedEnterpriseViews();
    if (!allowed.includes(view)) { notify('This module is unavailable for your verified persona.', true); return; }
    enterprise.currentView = view;
    if (!enterpriseViews.includes(view)) enterpriseSetViewBase(view);
    $$('main > section').forEach(section => section.hidden = section.id !== view);
    $('#customs-backdrop').hidden = !(view === 'customs' && matchMedia('(max-width:767px)').matches);
    $('#box-backdrop').hidden = !(view === 'boxes' && matchMedia('(max-width:767px)').matches);
    $$('[data-enterprise-view]').forEach(button => {
        button.setAttribute('aria-selected', String(button.dataset.enterpriseView === view));
        button.setAttribute('aria-current', button.dataset.enterpriseView === view ? 'page' : 'false');
    });
    if (enterpriseViews.includes(view)) busy($(`#${view} .primary`) || $('#store-refresh'), () => loadEnterpriseView(view));
    refreshIcons();
};
document.addEventListener('click', event => {
    const nav = event.target.closest('[data-enterprise-view]');
    if (nav) setView(nav.dataset.enterpriseView);
    const close = event.target.closest('[data-enterprise-close]');
    if (close) $('#' + close.dataset.enterpriseClose).close();
    const refresh = event.target.closest('[data-admin-refresh]');
    if (refresh) busy(refresh, () => loadEnterpriseView(refresh.dataset.adminRefresh));
});
function sampleAdminData() {
    if (enterprise.tenants.length) return;
    enterprise.tenants = [
        { tenant_id: 'sample-harbor', company_name: 'Harbor Commerce · sample', workspace_slug: 'harbor-demo', billing_email: 'harbor@example.invalid', billing_plan: 'PREPAID_WALLET', default_currency: 'GBP', workspace_status: 'ACTIVE', is_sandbox: true },
        { tenant_id: 'sample-northstar', company_name: 'Northstar Textiles · sample', workspace_slug: 'northstar-demo', billing_email: 'northstar@example.invalid', billing_plan: 'POSTPAID_30_DAY', default_currency: 'EUR', workspace_status: 'ACTIVE', is_sandbox: true }
    ];
    enterprise.carriers = [{ id: 'sample-carrier', tenant_id: 'sample-harbor', company_name: enterprise.tenants[0].company_name, account_name: 'EasyPost test account · sample', aggregator: 'EASYPOST', environment: 'TEST', is_active: false, priority: 100, timeout_seconds: 30 }];
    enterprise.margins = [{ id: 'sample-margin', tenant_id: 'sample-harbor', company_name: enterprise.tenants[0].company_name, rule_name: 'Sample US lane', origin_country: 'GB', destination_country: 'US', currency: 'GBP', markup_type: 'PERCENTAGE', markup_value: '20', priority: 10, minimum_markup: '0.00', is_active: true }];
    enterprise.transactions = [
        {id:'sample-ledger-reserve',company_name:enterprise.tenants[0].company_name,entry_type:'RESERVE',balance_delta:'0.00',reserved_delta:'24.00',currency:'GBP',created_at:new Date(Date.now()-3600000).toISOString()},
        {id:'sample-ledger-capture',company_name:enterprise.tenants[0].company_name,entry_type:'CAPTURE',balance_delta:'-24.00',reserved_delta:'-24.00',currency:'GBP',created_at:new Date(Date.now()-3500000).toISOString()}
    ];
}
async function loadEnterpriseView(view) {
    const generation = enterprise.generation;
    if (view === 'stores') {
        if (!state.session) enterprise.stores = [{ id: 'sample-store', display_name: 'Sample Shopify store', platform: 'SHOPIFY', is_active: true }];
        else {
            const result = await api('/api/v1/workspace/stores', { auth: true });
            if (generation !== enterprise.generation) return;
            enterprise.stores = result.stores;
        }
        renderEnterpriseStores(); return;
    }
    enterpriseAdminGuard();
    if (!state.session) sampleAdminData();
    else {
        const paths = { 'admin-clients': '/tenants', 'admin-carriers': '/carriers', 'admin-margins': '/margins', transactions: '/transactions' };
        const result = await api('/api/v1/admin' + paths[view], { auth: true });
        if (generation !== enterprise.generation) return;
        enterprise[({ 'admin-clients': 'tenants', 'admin-carriers': 'carriers', 'admin-margins': 'margins', transactions: 'transactions' })[view]] = result.tenants || result.connections || result.rules || result.transactions;
        if (view !== 'admin-clients' && view !== 'transactions') {
            const tenants = await api('/api/v1/admin/tenants', { auth: true });
            if (generation !== enterprise.generation) return;
            enterprise.tenants = tenants.tenants;
        }
    }
    renderEnterpriseTables();
    if (view === 'admin-clients') await loadEnterpriseView('transactions');
}
function tenantOptions(includeAll = false) {
    return (includeAll ? '<option value="">All clients</option>' : '') + enterprise.tenants.map(t => `<option value="${escapeHTML(t.tenant_id)}">${escapeHTML(t.company_name || t.workspace_slug)}</option>`).join('');
}
function renderEnterpriseTables() {
    const query = $('#tenant-search').value.toLowerCase();
    $('#tenant-rows').innerHTML = enterprise.tenants.filter(t => JSON.stringify(t).toLowerCase().includes(query)).map(t => `<tr><td><b>${escapeHTML(t.company_name || t.workspace_slug)}</b><p class="subtle">${escapeHTML(t.billing_email)} · ${escapeHTML(t.workspace_slug)}</p><span class="mono subtle">${escapeHTML(t.tenant_id)}</span></td><td>${escapeHTML(t.billing_plan)}<br>${escapeHTML(t.default_currency)}</td><td><span class="tag green">${escapeHTML(t.workspace_status)}</span></td><td>${t.is_sandbox ? 'SANDBOX' : 'PRODUCTION'}</td><td><button class="secondary" data-client-margins="${escapeHTML(t.tenant_id)}">Pricing rules</button></td></tr>`).join('') || '<tr><td colspan="5">No client accounts match this view.</td></tr>';
    const filter = $('#margin-tenant-filter').value;
    $('#margin-tenant-filter').innerHTML = tenantOptions(true);
    $('#margin-tenant-filter').value = filter;
    $('#carrier-rows').innerHTML = enterprise.carriers.map(c => `<tr><td><b>${escapeHTML(c.account_name)}</b><p class="subtle">${escapeHTML(c.company_name)}</p></td><td>${escapeHTML(c.aggregator)}</td><td><span class="tag">${escapeHTML(c.environment)}</span></td><td>${c.is_active ? '<span class="tag green">ACTIVE</span>' : '<span class="tag">DISABLED</span>'}<br>Priority ${c.priority}</td><td><div class="actions"><button class="secondary" data-carrier-edit="${escapeHTML(c.id)}">Parameters</button><button class="secondary" data-carrier-retire="${escapeHTML(c.id)}">Remove</button></div></td></tr>`).join('') || '<tr><td colspan="5">No configured carrier accounts.</td></tr>';
    $('#margin-rows').innerHTML = enterprise.margins.filter(m => !filter || m.tenant_id === filter).map(m => `<tr><td><b>${escapeHTML(m.company_name || enterprise.tenants.find(t => t.tenant_id === m.tenant_id)?.company_name || m.tenant_id)}</b><p class="subtle">${escapeHTML(m.rule_name || m.id)}</p></td><td>${escapeHTML(m.origin_country || 'ANY')} → ${escapeHTML(m.destination_country || 'ANY')}<br><span class="subtle">${escapeHTML(m.carrier_code || 'Any carrier')} ? ${escapeHTML(m.cargo_type || 'Any cargo')} ? ${escapeHTML(m.billing_plan || 'Any tier')}<br>Volume: ${escapeHTML(m.min_volume_m3 ?? '0')}?${escapeHTML(m.max_volume_m3 ?? 'unlimited')} m?</span></td><td class="finance-value">${escapeHTML(m.markup_value)} ${m.markup_type === 'PERCENTAGE' ? '%' : escapeHTML(m.currency)}</td><td>${m.priority}</td><td><span class="tag ${m.is_active ? 'green' : ''}">${m.is_active ? 'ACTIVE' : 'RETIRED'}</span></td><td><div class="actions"><button class="secondary" data-margin-edit="${escapeHTML(m.id)}">Edit</button><button class="secondary" data-margin-retire="${escapeHTML(m.id)}">Delete</button></div></td></tr>`).join('') || '<tr><td colspan="6">No pricing rules for this selection.</td></tr>';
    $('#transaction-rows').innerHTML = enterprise.transactions.map(t => `<tr><td>${escapeHTML(t.company_name)}</td><td><span class="tag">${escapeHTML(t.entry_type)}</span></td><td class="finance-value">${money(t.balance_delta, t.currency)}</td><td>${money(t.reserved_delta, t.currency)}</td><td>${escapeHTML(new Date(t.created_at).toLocaleString())}</td></tr>`).join('') || '<tr><td colspan="5">No ledger entries available in this view.</td></tr>';
}
$('#tenant-search').addEventListener('input', renderEnterpriseTables);
$('#margin-tenant-filter').addEventListener('change', renderEnterpriseTables);
function openTenantForm() {
    enterpriseAdminGuard(); $('#tenant-admin-form').reset(); $('#tenant-admin-form').dataset.requestId=crypto.randomUUID(); $('#tenant-admin-dialog').showModal();
}
$('#tenant-new').addEventListener('click', openTenantForm);
$('#tenant-admin-form').addEventListener('submit', event => {
    event.preventDefault(); busy(event.target.querySelector('button'), async () => {
        enterpriseAdminGuard(); const f = new FormData(event.target);
        const company_profile = Object.fromEntries(['company_name','contact_name','billing_email','address_line1','city','postal_code','country_code'].map(k => [k, String(f.get(k)).trim()]));
        if (f.get('tax_id')) company_profile.tax_id = String(f.get('tax_id'));
        const body = { request_id: event.target.dataset.requestId, company_profile, billing_plan: f.get('billing_plan'), default_currency: f.get('default_currency'), is_sandbox: f.has('is_sandbox'), ...(f.get('owner_auth_user_id') ? { owner_auth_user_id: f.get('owner_auth_user_id') } : {}) };
        if (state.session) await api('/api/v1/admin/tenants', { method: 'POST', body, auth: true });
        else enterprise.tenants.unshift({ tenant_id: crypto.randomUUID(), ...company_profile, ...body, workspace_slug: 'sample-' + Date.now(), workspace_status: 'ACTIVE' });
        $('#tenant-admin-dialog').close(); await loadEnterpriseView('admin-clients'); notify(state.session ? 'Customer account and wallet created.' : 'Sample customer created in browser memory only.');
    });
});
function openMarginForm(id = null) {
    enterpriseAdminGuard(); const form = $('#margin-admin-form'); form.reset(); enterprise.editMargin = id;
    form.dataset.requestId=crypto.randomUUID();
    form.elements.tenant_id.innerHTML = tenantOptions(); form.elements.tenant_id.disabled = !!id;
    $('#margin-form-title').textContent = id ? 'Update pricing rule' : 'Add pricing rule';
    if (id) {
        const row = enterprise.margins.find(m => m.id === id);
        for (const [key, value] of Object.entries(row)) if (form.elements[key]) {
            if (key === 'is_active') form.elements[key].checked = value;
            else form.elements[key].value = key === 'markup_type' && value === 'FIXED' ? 'FLAT_RATE' : value ?? '';
        }
    }
    $('#margin-admin-dialog').showModal();
}
$('#margin-new').addEventListener('click', () => openMarginForm());
$('#margin-admin-form').addEventListener('submit', event => {
    event.preventDefault(); busy(event.target.querySelector('button'), async () => {
        enterpriseAdminGuard(); const form = event.target; const body = { request_id: form.dataset.requestId };
        for (const element of form.elements) {
            if (!element.name) continue;
            if (element.name === 'is_active') body.is_active = element.checked;
            else if (element.name === 'priority') body.priority = Number(element.value);
            else if (element.value.trim()) body[element.name] = element.value.trim();
        }
        const id = enterprise.editMargin;
        if (state.session) await api('/api/v1/admin/margins' + (id ? '/' + encodeURIComponent(id) : ''), { method: id ? 'PUT' : 'POST', body, auth: true });
        else {
            const row = { ...body, id: id || crypto.randomUUID(), rule_name: 'Sample pricing rule' };
            if (id) enterprise.margins = enterprise.margins.map(m => m.id === id ? row : m); else enterprise.margins.unshift(row);
        }
        $('#margin-admin-dialog').close(); await loadEnterpriseView('admin-margins'); notify(state.session ? 'Pricing rule saved.' : 'Sample rule saved in browser memory only.');
    });
});
function openCarrierForm(id = null) {
    enterpriseAdminGuard(); const form = $('#carrier-admin-form'); form.reset(); enterprise.editCarrier = id;
    form.dataset.requestId=crypto.randomUUID();
    form.elements.tenant_id.innerHTML = tenantOptions(); $('#carrier-create-fields').hidden = !!id;
    $('#carrier-create-fields').querySelectorAll('input,select').forEach(input => input.disabled = !!id);
    $('#carrier-form-title').textContent = id ? 'Provider parameters' : 'Add carrier connection';
    if (id) {
        const row = enterprise.carriers.find(c => c.id === id);
        for (const k of ['priority', 'timeout_seconds']) form.elements[k].value = row[k];
        form.elements.is_active.checked = row.is_active;
    }
    if (!state.session) { form.elements.api_key.required = false; form.elements.api_key.placeholder = 'Not stored in sample mode'; }
    else { form.elements.api_key.required = !id; form.elements.api_key.placeholder = 'Encrypted on the server'; }
    $('#carrier-admin-dialog').showModal();
}
$('#carrier-new').addEventListener('click', () => openCarrierForm());
$('#carrier-admin-form [name="aggregator"]').addEventListener('change',event=>{
    const form=$('#carrier-admin-form'),regional=event.target.value==='REGIONAL';
    form.elements.api_base_url.value=regional?'':'https://api.easypost.com/v2';
    form.elements.api_base_url.placeholder=regional?'Server-approved regional HTTPS endpoint':'';
    form.elements.regional_provider_code.required=regional;
});
$('#carrier-admin-form').addEventListener('submit', event => {
    event.preventDefault(); busy(event.target.querySelector('button'), async () => {
        enterpriseAdminGuard(); const f = new FormData(event.target), id = enterprise.editCarrier;
        const body = { priority: Number(f.get('priority')), timeout_seconds: Number(f.get('timeout_seconds')), is_active: f.has('is_active') };
        if (!id) body.request_id=event.target.dataset.requestId;
        if (!id) for (const k of ['tenant_id','account_name','aggregator','api_base_url','api_key','environment','regional_provider_code','upstream_account_id']) if (f.get(k)) body[k] = String(f.get(k)).trim();
        try {
            if (state.session) await api('/api/v1/admin/carriers' + (id ? '/' + encodeURIComponent(id) : ''), { method: id ? 'PATCH' : 'POST', body, auth: true });
            else {
                delete body.api_key;
                const row = { ...body, id: id || crypto.randomUUID(), company_name: enterprise.tenants.find(t => t.tenant_id === body.tenant_id)?.company_name };
                if (id) enterprise.carriers = enterprise.carriers.map(c => c.id === id ? { ...c, ...row, company_name: c.company_name } : c); else enterprise.carriers.unshift(row);
            }
            $('#carrier-admin-dialog').close(); await loadEnterpriseView('admin-carriers'); notify(state.session ? 'Connection configuration saved.' : 'Sample connection updated. No provider API call occurred.');
        } finally { event.target.elements.api_key.value = ''; }
    });
});
let pendingRetirement = null;
document.addEventListener('click', event => {
    const m = event.target.closest('[data-margin-edit]'); if (m) openMarginForm(m.dataset.marginEdit);
    const c = event.target.closest('[data-carrier-edit]'); if (c) openCarrierForm(c.dataset.carrierEdit);
    const retire = event.target.closest('[data-margin-retire],[data-carrier-retire]');
    if (retire) {
        enterpriseAdminGuard(); pendingRetirement = retire.dataset.marginRetire ? ['margins', retire.dataset.marginRetire] : ['carriers', retire.dataset.carrierRetire];
        $('#retire-context').textContent = `Retire ${pendingRetirement[0]} configuration ${pendingRetirement[1]}?`; $('#retire-admin-dialog').showModal();
    }
    const client = event.target.closest('[data-client-margins]');
    if (client) { setView('admin-margins'); $('#margin-tenant-filter').value = client.dataset.clientMargins; renderEnterpriseTables(); }
});
$('#retire-confirm').addEventListener('click', () => busy($('#retire-confirm'), async () => {
    enterpriseAdminGuard(); const [kind, id] = pendingRetirement;
    if (state.session) await api('/api/v1/admin/' + kind + '/' + encodeURIComponent(id), { method: 'DELETE', auth: true });
    else enterprise[kind] = enterprise[kind].map(r => r.id === id ? { ...r, is_active: false } : r);
    $('#retire-admin-dialog').close(); pendingRetirement = null; await loadEnterpriseView('admin-' + kind); notify('Configuration retired. Shipment history retained.');
}));
function renderEnterpriseStores() {
    $('#store-list').innerHTML = enterprise.stores.map(s => `<article class="card"><span class="tag">${escapeHTML(s.platform)}</span><h2>${escapeHTML(s.display_name)}</h2><p class="subtle">${s.is_active ? 'Active import association' : 'Disabled import association'}</p><span class="mono subtle">${escapeHTML(s.id)}</span><button class="secondary full" data-store-state="${escapeHTML(s.id)}" style="margin-top:12px">${s.is_active ? 'Disable' : 'Enable'} store association</button></article>`).join('') || '<div class="notice">No stores registered in this workspace.</div>';
}
$('#store-new').addEventListener('click', () => { $('#store-admin-form').reset(); $('#store-admin-dialog').showModal(); });
$('#store-refresh').addEventListener('click', () => busy($('#store-refresh'), () => loadEnterpriseView('stores')));
$('#store-admin-form').addEventListener('submit', event => {
    event.preventDefault(); busy(event.target.querySelector('button'), async () => {
        if (!allowedEnterpriseViews().includes('stores')) throw Error('Store configuration permission required.');
        const body = Object.fromEntries(new FormData(event.target));
        if (state.session) await api('/api/v1/workspace/stores', { method: 'POST', body, auth: true });
        else enterprise.stores.push({ id: crypto.randomUUID(), ...body, is_active: true });
        $('#store-admin-dialog').close(); if (state.session) await loadEnterpriseView('stores'); else renderEnterpriseStores();
        notify('Workspace store registered. Remote app installation is separate.');
    });
});
$('#store-list').addEventListener('click', event => {
    const b = event.target.closest('[data-store-state]'); if (!b) return;
    busy(b, async () => {
        const store = enterprise.stores.find(s => s.id === b.dataset.storeState);
        if (state.session) await api('/api/v1/workspace/stores/' + encodeURIComponent(store.id), { method: 'PATCH', body: { is_active: !store.is_active }, auth: true });
        store.is_active = !store.is_active; renderEnterpriseStores();
    });
});
let activeExceptionTicket = null;
$('#manifest-body').addEventListener('click', event => {
    const b = event.target.closest('[data-exception-sheet]'); if (!b) return;
    busy(b, async () => {
        const row = manifestRecords().find(r => r.id === b.dataset.exceptionSheet);
        let tickets = portal.tickets;
        if (state.session) {
            const result = await api(portal.role === 'SUPER_ADMIN' ? '/api/v1/admin/support/tickets' : '/api/v1/support/tickets', { auth: true }); tickets = result.tickets;
        }
        activeExceptionTicket = tickets.find(t => t.shipment_id === row.id) || {
            id: row.id, shipment_id: row.id, tenant_id: row.tenant_id, tracking_number: row.tracking_number,
            demo: !!row.simulated, proof_of_delivery_url: row.proof_of_delivery_url,
            ai_summary: row.simulated ? 'Sample remedy: verify the receiver address and itemized customs declaration with the dispatcher.' : 'No generated support summary is stored yet. Review the latest carrier exception and supporting shipment records.'
        };
        $('#exception-title').textContent = (row.reference || row.id) + ' · EXCEPTION';
        $('#exception-summary').textContent = activeExceptionTicket.ai_summary;
        $('#exception-dispute').hidden = portal.profile?.workspace_role === 'DISPATCHER';
        $('#exception-sheet').showModal();
    });
});
$('#exception-pod').addEventListener('click', () => {
    const url = safeHTTPS(activeExceptionTicket?.proof_of_delivery_url);
    $('#pod-content').innerHTML = url ? `<a class="primary" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">Open carrier delivery proof</a>` : '<div class="notice">No carrier POD signature or photo has been supplied.</div>';
    $('#pod-dialog').showModal();
});
$('#exception-dispute').addEventListener('click', () => { $('#exception-sheet').close(); openDispute(activeExceptionTicket); });
$('#hs-results').addEventListener('click', event => {
    const b = event.target.closest('[data-use-hs]'); if (!b) return;
    $('#qc-hs').value = b.dataset.useHs; $('#decl-hs').value = b.dataset.useHs;
    $('#qc-reviewed').checked = false; $('#decl-reviewed').checked = false;
    invalidateCustoms(); notify('Commodity suggestion injected into the declaration draft. Review it before generating a label payload.');
});
const enterpriseClearSessionBase = clearSession;
clearSession = function () {
    enterprise.generation++; enterprise.tenants = []; enterprise.carriers = []; enterprise.margins = []; enterprise.transactions = []; enterprise.stores = [];
    enterpriseClearSessionBase();
    enterpriseViews.forEach(id => $('#' + id).hidden = true);
    ['tenant-admin-dialog','carrier-admin-dialog','margin-admin-dialog','retire-admin-dialog','store-admin-dialog','exception-sheet'].forEach(id => $('#' + id).close());
    $('#carrier-admin-form').reset(); pendingRetirement = null; activeExceptionTicket = null; enterprise.currentView = 'dashboard'; enterpriseNavKey = '';
    refreshEnterpriseNavigation();
};
refreshEnterpriseNavigation();
