// Embedded in index.html: server-verified personas and administrative control hubs.
const defaultProviderProfiles=[{code:'EASYPOST',name:'EasyPost',endpoint:'https://api.easypost.com/v2',authentication:'API_KEY',label_purchase:true},{code:'SENDCLOUD_V3',name:'Sendcloud',endpoint:'https://panel.sendcloud.sc/api/v3',authentication:'BASIC_PUBLIC_SECRET',label_purchase:true},{code:'SHIPPO',name:'Shippo',endpoint:'https://api.goshippo.com',authentication:'SHIPPO_TOKEN',label_purchase:true}];
const enterprise = { providerProfiles:defaultProviderProfiles, tenants: [], carriers: [], margins: [], transactions: [], stores: [], editMargin: null, editCarrier: null, currentView: 'dashboard', generation: 0 };
const enterpriseViews = ['admin-clients', 'admin-carriers', 'admin-margins', 'stores', 'workspace'];
const mainContent = document.querySelector('main');
mainContent.insertAdjacentHTML('beforeend', `
<section id="admin-clients" hidden>
  <div class="pagehead"><div><div class="eyebrow">Platform / Client accounts node</div><h1>Client Accounts Hub</h1><p>Company profiles, billing plans and network transaction history.</p></div><button class="primary" id="tenant-new"><i data-lucide="building-2"></i>Onboard New Tenant</button></div>
  <div class="enterprise-banner" data-admin-source></div>
  <article class="card"><div class="toolbar"><input id="tenant-search" placeholder="Search company, email or workspace" aria-label="Search clients"><button class="secondary" data-admin-refresh="admin-clients">Refresh clients</button></div><div class="scrolltable"><table><thead><tr><th>Company / workspace</th><th>Billing / currency</th><th>Status</th><th>Environment</th><th>Configuration</th><th>CRM timeline</th></tr></thead><tbody id="tenant-rows"></tbody></table></div></article>
  <article class="card" style="margin-top:20px"><div class="cardhead"><div><h2>Aggregate wallet transaction log</h2><p class="subtle">Newest 200 ledger entries. Currency values are kept separate.</p></div><button class="secondary" data-admin-refresh="transactions">Refresh log</button></div><div class="scrolltable"><table><thead><tr><th>Company</th><th>Entry</th><th>Balance movement</th><th>Reserved movement</th><th>Time</th></tr></thead><tbody id="transaction-rows"></tbody></table></div></article>
</section>
<section id="admin-carriers" hidden>
  <div class="pagehead"><div><div class="eyebrow">Platform / Carrier connectors</div><h1>Carrier Provider Settings</h1><p>EasyInvio-owned provider connections serve all eligible clients. Credentials remain private on the server.</p></div><button class="primary" id="carrier-new"><i data-lucide="plug"></i>Add New Aggregator</button></div>
  <div class="enterprise-banner" data-admin-source></div>
  <div class="provider-grid" id="provider-catalogue"><article class="card"><span class="tag green">SUPPORTED ADAPTER</span><h2>EasyPost</h2><p class="subtle">Official v2 endpoint. Tenant-bound encrypted credentials.</p><button class="primary" id="easypost-setup">Set Up</button><p class="subtle">Configure EasyInvio’s shared account once. No client assignment or key disclosure.</p></article><article class="card"><span class="tag green">NATIVE V3 ADAPTER</span><h2>Sendcloud</h2><p class="subtle">Discover active carriers and actual quotes through Sendcloud v3. Public + secret keys stay server-encrypted. Native v3 label announcements and cancellation are available for LIVE accounts. Ordinary TEST accounts remain quotes-only because Sendcloud labels can be billed.</p><button class="primary" id="sendcloud-setup">Set Up</button></article><article class="card"><span class="tag green">NATIVE ADAPTER</span><h2>Shippo</h2><p class="subtle">Native parcel rates, transaction labels and confirmed refunds. Configure a private TEST or LIVE token.</p><button class="primary" id="shippo-setup">Set Up</button></article></div>
  <article class="card"><div class="cardhead"><h2>Configured aggregators</h2><label class="check"><input id="carrier-show-legacy" type="checkbox">Show client-specific overrides</label><label class="check"><input id="carrier-show-removed" type="checkbox">Show legacy archived connections</label><button class="secondary" data-admin-refresh="admin-carriers">Refresh</button></div><div class="scrolltable"><table><thead><tr><th>Account / company</th><th>Provider</th><th>Environment</th><th>Status / priority</th><th>Actions</th></tr></thead><tbody id="carrier-rows"></tbody></table></div></article>
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
 <div id="carrier-create-fields"><label id="carrier-tenant-field">Assigned client<select name="tenant_id" required></select></label><p id="carrier-platform-note" class="notice" hidden>Owned by EasyInvio. Shared with all clients in the selected environment. Clients never receive this key.</p><label id="carrier-format-field" hidden>API integration format<select id="carrier-format"></select></label><p id="carrier-format-help" class="subtle" hidden>Official endpoints are detected automatically. A custom API must implement the approved EasyInvio /rates contract; its key alone does not define a new native booking protocol.</p><label>Account name<input name="account_name" maxlength="200" required></label><div class="fields"><div><label id="carrier-aggregator-field">Provider<select name="aggregator"><option>EASYPOST</option><option>REGIONAL</option></select></label></div><div><label>Environment<select name="environment"><option>TEST</option><option>LIVE</option></select></label></div></div><label id="carrier-api_base_url-field">API endpoint<input name="api_base_url" value="https://api.easypost.com/v2" type="url" required></label><label id="carrier-regional_provider_code-field">Internal connector label (optional)<input name="regional_provider_code" placeholder="Automatic for supported aggregators"></label><label id="carrier-key-field">API key (write-only)<input name="api_key" type="password" autocomplete="new-password" required maxlength="4096"></label><div id="sendcloud-key-fields" hidden><label>Sendcloud public API key<input name="sendcloud_public_key" type="password" autocomplete="new-password"></label><label>Sendcloud secret API key<input name="sendcloud_secret_key" type="password" autocomplete="new-password"></label></div><label id="carrier-upstream_account_id-field">Upstream account ID (optional)<input name="upstream_account_id"></label></div>
 <details id="carrier-advanced"><summary>Advanced connection options</summary><div class="fields"><div><label>Provider selection priority<input name="priority" value="100" type="number" min="0" max="1000000" step="1" required></label></div><div><label>Timeout seconds<input name="timeout_seconds" value="30" type="number" min="1" max="120" step="1" required></label></div></div><p class="subtle">Priority orders provider selection when capacity is limited; prices are still compared in parallel. Timeout is the maximum wait for a provider response.</p></details><label class="check"><input name="is_active" type="checkbox">Enable provider for new outbound quotes</label><button class="primary full">Save connection</button><p class="footnote">Existing secrets are never returned. No carrier API calls are made by this form.</p>
</form></dialog>
<dialog id="store-admin-dialog"><button class="close" data-enterprise-close="store-admin-dialog" aria-label="Close store form">×</button><h2>Register a workspace store</h2><form id="store-admin-form"><label>Display name<input name="display_name" required maxlength="200"></label><label>Platform<select name="platform"><option>SHOPIFY</option><option>WOOCOMMERCE</option><option>AMAZON</option></select></label><button class="primary full">Register store</button></form></dialog>
<dialog id="retire-admin-dialog"><button class="close" data-enterprise-close="retire-admin-dialog" aria-label="Close retirement review">×</button><h2>Review configuration removal</h2><p id="retire-context" class="subtle"></p><p class="notice">This removes the configuration from active selection and preserves historical shipment references.</p><button id="retire-confirm" class="primary full">Retire configuration</button></dialog>
<dialog id="exception-sheet" class="exception-sheet"><button class="close" data-enterprise-close="exception-sheet" aria-label="Close exception drawer">×</button><div class="eyebrow">Proactive exception support</div><h2 id="exception-title"></h2><div class="notice" id="exception-summary"></div><div class="actions"><button class="secondary" id="exception-pod">View POD Token</button><button class="primary" id="exception-dispute">Auto-Draft Surcharge Dispute Ticket</button></div><p class="footnote">Review drafts before submission. No WhatsApp message or dispute is sent.</p></dialog>
`);
const personaControls = $('#role-admin').parentElement;
personaControls.classList.add('header-personas');
document.querySelector('.topbar-actions').prepend(personaControls);
const enterpriseNavItems = {
    dashboard: ['Overview', 'layout-dashboard'], settings: ['Settings','settings'],
    'admin-clients': ['Client Accounts Node', 'building-2'],
    'admin-carriers': ['Carrier Connectors', 'plug'],
    'admin-margins': ['Margin Rule Matrix', 'sliders-horizontal'],
    dispatch: ['Speed Quote Matrix', 'send'], boxes: ['Packaging sizes', 'boxes'],
    manifest: ['Manifest & Labels', 'package-check'], wallet: ['Wallet & Billing', 'wallet'],
    customs: ['Customs Harmonizer', 'shield-check'], profile: ['User Profile', 'user-round'], stores: ['Store Integrations', 'store'], workspace: ['Marketplace Workspace', 'warehouse']
};
function allowedEnterpriseViews() {
    if (state.session && !portal.profile) return [];
    if (portal.role === 'SUPER_ADMIN' && (!state.session || portal.profile?.portal_role === 'SUPER_ADMIN'))
        return ['dashboard', 'admin-clients', 'admin-carriers', 'admin-margins', 'profile'];
    if (portal.profile?.workspace_role === 'DISPATCHER') return ['workspace', 'dispatch', 'boxes', 'manifest', 'profile'];
    if (portal.profile?.workspace_role === 'ACCOUNTANT') return ['dashboard', 'dispatch', 'wallet', 'customs', 'stores', 'profile'];
    if (state.session && portal.profile?.portal_role === 'SUPER_ADMIN') return ['dashboard','profile'];
    return ['dashboard', 'workspace', 'dispatch', 'manifest', 'boxes', 'wallet', 'customs', 'stores', 'profile', ...(['OWNER','ADMIN'].includes(portal.profile?.workspace_role)?['settings']:[])];
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
            const fallback=({dashboard:'grid','admin-clients':'grid','admin-carriers':'truck','admin-margins':'chart',dispatch:'truck',boxes:'box',manifest:'list',wallet:'wallet',customs:'globe',stores:'box',workspace:'box'})[view];
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
    $('#health-label').textContent = state.session ? 'SIGNED IN' : state.mode === 'local-preview' ? 'PREVIEW' : 'BACKEND ONLINE';
    $('#tenant-new').innerHTML = '<i data-lucide="building-2"></i>' + (state.session ? 'Onboard New Tenant' : 'Sign in to onboard a tenant');
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
    if (view !== 'profile' && !enterpriseViews.includes(view)) enterpriseSetViewBase(view);
    if (view === 'profile') loadIdentityProfile().catch(error => notify(error.message, true));
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
    if (view === 'workspace') { await loadDispatchWorkspace(); return; }
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
        if (view === 'admin-carriers') { const shared = await api('/api/v1/admin/platform-carriers', { auth: true }); if (generation !== enterprise.generation) return; enterprise.carriers = [...shared.connections, ...enterprise.carriers]; const capabilities=await api('/api/v1/admin/platform-carriers/capabilities',{auth:true});if(generation!==enterprise.generation)return;enterprise.providerProfiles=capabilities.providers;renderProviderCatalogue(); }
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
function providerDisplayName(connection) {
    return ({'https://api.easypost.com/v2':'EasyPost','https://panel.sendcloud.sc/api/v3':'Sendcloud','https://panel.sendcloud.sc/api/v2':'Sendcloud legacy','https://api.goshippo.com':'Shippo'})[connection.api_base_url] || (connection.aggregator==='EASYPOST'?'EasyPost':connection.regional_provider_code||'Custom regional connector');
}
function renderEnterpriseTables() {
    const query = $('#tenant-search').value.toLowerCase();
    const crmLink = t => /^\d+$/.test(String(t.hubspot_company_id || '')) && /^\d+$/.test(String(t.hubspot_portal_id || ''))
        ? `<a href="https://app.hubspot.com/contacts/${t.hubspot_portal_id}/record/0-2/${t.hubspot_company_id}" target="_blank" rel="noopener noreferrer" class="text-indigo-400 hover:text-indigo-300 font-semibold flex items-center space-x-1" aria-label="Open HubSpot company timeline"><i data-lucide="external-link"></i><span>HubSpot</span></a>`
        : '<span class="subtle">Not synchronized</span>';
    $('#tenant-rows').innerHTML = enterprise.tenants.filter(t => JSON.stringify(t).toLowerCase().includes(query)).map(t => `<tr><td><b>${escapeHTML(t.company_name || t.workspace_slug)}</b><p class="subtle">${escapeHTML(t.billing_email)} · ${escapeHTML(t.workspace_slug)}</p><span class="mono subtle">${escapeHTML(t.tenant_id)}</span></td><td>${escapeHTML(t.billing_plan)}<br>${escapeHTML(t.default_currency)}</td><td><span class="tag green">${escapeHTML(t.workspace_status)}</span></td><td>${t.is_sandbox ? 'SANDBOX' : 'PRODUCTION'}</td><td><button class="secondary" data-client-margins="${escapeHTML(t.tenant_id)}">Pricing rules</button></td><td>${crmLink(t)}</td></tr>`).join('') || '<tr><td colspan="6">No client accounts match this view.</td></tr>';
    const filter = $('#margin-tenant-filter').value;
    $('#margin-tenant-filter').innerHTML = tenantOptions(true);
    $('#margin-tenant-filter').value = filter;
    $('#carrier-rows').innerHTML = enterprise.carriers.filter(c=>(!c.retired_at || $('#carrier-show-removed').checked) && (!state.session || c.platform_owned || $('#carrier-show-legacy').checked)).map(c => `<tr><td><b>${escapeHTML(c.account_name)}</b><p class="subtle">${escapeHTML(c.company_name)}</p></td><td>${escapeHTML(providerDisplayName(c))}</td><td><span class="tag">${escapeHTML(c.environment)}</span></td><td>${c.is_active ? '<span class="tag green">ACTIVE</span>' : '<span class="tag">DISABLED</span>'}<br>Priority ${c.priority}</td><td><div class="actions">${c.platform_owned ? `<button class="secondary" data-carrier-verify="${escapeHTML(c.id)}">Verify Connection</button><button class="secondary" data-quote-diagnostics="${escapeHTML(c.id)}">Capabilities &amp; quote diagnostics</button>${enterprise.providerProfiles.some(p=>p.endpoint===c.api_base_url&&p.label_purchase)?`<button class="secondary" data-native-settings="${escapeHTML(c.id)}">Orders &amp; Webhooks</button>`:""}` : ""}<button class="secondary" data-carrier-edit="${escapeHTML(c.id)}">Edit Settings</button><button class="secondary" data-carrier-disable="${escapeHTML(c.id)}" ${!c.is_active?'disabled':''}>Disable</button></div></td></tr>`).join('') || '<tr><td colspan="5">No configured carrier accounts.</td></tr>';
    $('#margin-rows').innerHTML = enterprise.margins.filter(m => !filter || m.tenant_id === filter).map(m => `<tr><td><b>${escapeHTML(m.company_name || enterprise.tenants.find(t => t.tenant_id === m.tenant_id)?.company_name || m.tenant_id)}</b><p class="subtle">${escapeHTML(m.rule_name || m.id)}</p></td><td>${escapeHTML(m.origin_country || 'ANY')} → ${escapeHTML(m.destination_country || 'ANY')}<br><span class="subtle">${escapeHTML(m.carrier_code || 'Any carrier')} ? ${escapeHTML(m.cargo_type || 'Any cargo')} ? ${escapeHTML(m.billing_plan || 'Any tier')}<br>Volume: ${escapeHTML(m.min_volume_m3 ?? '0')}?${escapeHTML(m.max_volume_m3 ?? 'unlimited')} m?</span></td><td class="finance-value">${escapeHTML(m.markup_value)} ${m.markup_type === 'PERCENTAGE' ? '%' : escapeHTML(m.currency)}</td><td>${m.priority}</td><td><span class="tag ${m.is_active ? 'green' : ''}">${m.is_active ? 'ACTIVE' : 'RETIRED'}</span></td><td><div class="actions"><button class="secondary" data-margin-edit="${escapeHTML(m.id)}">Edit</button><button class="secondary" data-margin-retire="${escapeHTML(m.id)}">Delete</button></div></td></tr>`).join('') || '<tr><td colspan="6">No pricing rules for this selection.</td></tr>';
    $('#transaction-rows').innerHTML = enterprise.transactions.map(t => `<tr><td>${escapeHTML(t.company_name)}</td><td><span class="tag">${escapeHTML(t.entry_type)}</span></td><td class="finance-value">${money(t.balance_delta, t.currency)}</td><td>${money(t.reserved_delta, t.currency)}</td><td>${escapeHTML(new Date(t.created_at).toLocaleString())}</td></tr>`).join('') || '<tr><td colspan="5">No ledger entries available in this view.</td></tr>';
}
$('#tenant-search').addEventListener('input', renderEnterpriseTables);
$('#margin-tenant-filter').addEventListener('change', renderEnterpriseTables);
function openTenantForm() {
    enterpriseAdminGuard();
    if (!state.session) { notify('Sign in as an authorized platform owner to create a customer in the database.'); $('#account-dialog').showModal(); return; }
    $('#tenant-admin-form').reset(); $('#tenant-admin-form').dataset.requestId=crypto.randomUUID(); $('#tenant-admin-dialog').showModal();
}
$('#tenant-new').addEventListener('click', openTenantForm);
$('#tenant-admin-form').addEventListener('submit', event => {
    event.preventDefault(); busy(event.target.querySelector('button'), async () => {
        enterpriseAdminGuard();
        if (!state.session) throw Error('Sign in as an authorized platform owner. No customer has been created.');
        const f = new FormData(event.target);
        const company_profile = Object.fromEntries(['company_name','contact_name','billing_email','address_line1','city','postal_code','country_code'].map(k => [k, String(f.get(k)).trim()]));
        if (f.get('tax_id')) company_profile.tax_id = String(f.get('tax_id'));
        const body = { request_id: event.target.dataset.requestId, company_profile, billing_plan: f.get('billing_plan'), default_currency: f.get('default_currency'), is_sandbox: f.has('is_sandbox'), ...(f.get('owner_auth_user_id') ? { owner_auth_user_id: f.get('owner_auth_user_id') } : {}) };
        const created = await api('/api/v1/admin/tenants', { method: 'POST', body, auth: true });
        if (!created.tenant_id || created.wallet_provisioned !== true) throw Error('Customer creation was not confirmed. Retry with the same form to reconcile.');
        $('#tenant-admin-dialog').close(); await loadEnterpriseView('admin-clients'); notify('Customer account and wallet saved in the database.');
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
function openCarrierForm(id = null, provider = null) {
    enterpriseAdminGuard();
    if (!id && !state.session) { notify('Sign in as the platform owner to save an encrypted carrier API key.'); $('#account-dialog').showModal(); return; }
    const form = $('#carrier-admin-form'); form.reset(); enterprise.editCarrier = id;
    form.dataset.requestId=crypto.randomUUID();
    const row = id ? enterprise.carriers.find(c => c.id === id) : null;
    const shared = !id || !!row?.platform_owned;
    form.dataset.scope = shared ? 'PLATFORM' : 'TENANT';
    $('#carrier-platform-note').hidden = !shared; $('#carrier-tenant-field').hidden = shared;
    form.elements.tenant_id.disabled = shared; form.elements.tenant_id.required = !shared;
    form.elements.tenant_id.innerHTML = tenantOptions(); $('#carrier-create-fields').hidden = !!id && !shared;
    $('#carrier-create-fields').querySelectorAll('input,select').forEach(input => input.disabled = !!id && !shared);
    form.elements.tenant_id.disabled = shared || !!id;
    $('#carrier-format-field').hidden=true;$('#carrier-format-help').hidden=true;delete form.dataset.addAggregator;
    $('#carrier-form-title').textContent = id ? 'Provider parameters' : 'Add carrier connection';
    if (id) {
        const row = enterprise.carriers.find(c => c.id === id);
        for (const k of ['priority', 'timeout_seconds']) form.elements[k].value = row[k];
        form.elements.is_active.checked = row.is_active;
    }
    if (!state.session) { form.elements.api_key.required = false; form.elements.api_key.placeholder = 'Not stored in sample mode'; }
    else { form.elements.api_key.required = !id; form.elements.api_key.placeholder = 'Encrypted on the server'; }
    if (shared) {
        if (row) for (const k of ['account_name','aggregator','api_base_url','environment','regional_provider_code','upstream_account_id']) form.elements[k].value = row[k] || '';
        const specification=enterprise.providerProfiles.find(p=>p.code===provider || (row && p.endpoint===row.api_base_url) || (provider==='SENDCLOUD' && p.code==='SENDCLOUD_V3'));
        const selected = specification?.authentication==='BASIC_PUBLIC_SECRET'?'SENDCLOUD':specification?.code || provider || row?.aggregator || 'EASYPOST';
        form.dataset.provider = selected;
        const sendcloud = selected === 'SENDCLOUD';
        $('#sendcloud-key-fields').hidden = !sendcloud; $('#carrier-key-field').hidden = sendcloud;
        for (const k of ['sendcloud_public_key','sendcloud_secret_key']) { form.elements[k].disabled = !sendcloud; form.elements[k].required = sendcloud && !id; }
        form.elements.api_key.disabled = sendcloud;
        form.elements.aggregator.value = selected === 'EASYPOST' ? 'EASYPOST' : 'REGIONAL';
        form.elements.api_base_url.value = specification?.endpoint || row?.api_base_url || (selected==='EASYPOST'?'https://api.easypost.com/v2':'');
        form.elements.regional_provider_code.value = ['SENDCLOUD','SHIPPO'].includes(selected) ? selected : selected === 'REGIONAL' ? row?.regional_provider_code || '' : specification?.code || '';
        for (const k of ['aggregator','api_base_url','regional_provider_code','upstream_account_id']) $('#carrier-'+k+'-field').hidden = selected !== 'REGIONAL' || k === 'aggregator';
        form.elements.regional_provider_code.required = false;
        form.elements.api_key.required = !id;
        $('#carrier-form-title').textContent='Set Up '+(specification?.name || (selected==='REGIONAL'?'Custom regional API':selected));
        if (!id) { form.elements.account_name.value = 'EasyInvio ' + selected; form.elements.is_active.checked = true; }
    } else for (const k of ['aggregator','api_base_url','regional_provider_code','upstream_account_id']) $('#carrier-'+k+'-field').hidden = false;
    $('#carrier-admin-dialog').showModal();
}
$('#carrier-admin-dialog').addEventListener('close', () => { const form = $('#carrier-admin-form'); for (const k of ['api_key','sendcloud_public_key','sendcloud_secret_key']) form.elements[k].value = ''; });
function openNewAggregatorForm(format='AUTO', preserve=null) {
 openCarrierForm(null,format==='AUTO'?'REGIONAL':format);
 if(!state.session)return;
 const form=$('#carrier-admin-form');form.dataset.addAggregator='true';
 $('#carrier-form-title').textContent='Add New Aggregator';$('#carrier-format-field').hidden=false;$('#carrier-format-help').hidden=false;
 $('#carrier-format').value=format;$('#carrier-api_base_url-field').hidden=false;
 if(preserve){form.elements.account_name.value=preserve.name;form.elements.environment.value=preserve.environment;}
 else form.elements.account_name.value='';
 if(format==='AUTO')form.elements.api_base_url.value=preserve?.endpoint||'';
 form.elements.account_name.focus();
}
$('#carrier-new').addEventListener('click',()=>openNewAggregatorForm());
$('#carrier-format').addEventListener('change',event=>{const form=$('#carrier-admin-form');openNewAggregatorForm(event.target.value,{name:form.elements.account_name.value,environment:form.elements.environment.value,endpoint:form.elements.api_base_url.value});});
$('#carrier-admin-form [name="api_base_url"]').addEventListener('blur',()=>{const form=$('#carrier-admin-form');if(!form.dataset.addAggregator||$('#carrier-format').value!=='AUTO')return;const endpoint=form.elements.api_base_url.value.trim().replace(/\/+$/,'');const spec=enterprise.providerProfiles.find(p=>p.endpoint===endpoint&&p.code!=='SENDCLOUD_V2');if(spec)openNewAggregatorForm(spec.code,{name:form.elements.account_name.value,environment:form.elements.environment.value,endpoint});});
$('#carrier-show-removed').addEventListener('change',renderEnterpriseTables);
$('#carrier-show-legacy').addEventListener('change',renderEnterpriseTables);
function renderProviderCatalogue() {
 const available=enterprise.providerProfiles.filter(p=>p.code!=='SENDCLOUD_V2');
 $('#carrier-format').innerHTML='<option value="AUTO">Detect from API endpoint</option>'+available.map(p=>'<option value="'+escapeHTML(p.code)+'">'+escapeHTML(p.name)+' API format</option>').join('')+'<option value="REGIONAL">EasyInvio-compatible /rates API (quotes only)</option>';
 $('#provider-catalogue').innerHTML=available.map(p=>`<article class="card"><span class="tag green">${p.label_purchase?'NATIVE LIFECYCLE ADAPTER':'QUOTE ADAPTER'}</span><h2>${escapeHTML(p.name)}</h2><p class="subtle">Configure EasyInvio's shared connection. Endpoint and identifier are automatic; credentials remain private.</p>${p.code==='SENDCLOUD_V3'?'<p class="subtle">Ordinary TEST accounts remain quotes-only because carrier labels can be billed.</p>':''}<button class="primary" id="${p.code==='SENDCLOUD_V3'?'sendcloud':p.code.toLowerCase()}-setup" data-provider-setup="${escapeHTML(p.code)}">Set Up</button></article>`).join('');
}
document.addEventListener('click',event=>{const button=event.target.closest('[data-provider-setup]');if(button)openCarrierForm(null,button.dataset.providerSetup);});
renderProviderCatalogue();


$('#carrier-admin-form [name="aggregator"]').addEventListener('change',event=>{
    const form=$('#carrier-admin-form'),regional=event.target.value==='REGIONAL';
    form.elements.api_base_url.value=regional?'':'https://api.easypost.com/v2';
    form.elements.api_base_url.placeholder=regional?'Server-approved regional HTTPS endpoint':'';
    form.elements.regional_provider_code.required=false;
});
$('#carrier-admin-form').addEventListener('submit', event => {
    event.preventDefault(); busy(event.target.querySelector('button'), async () => {
        enterpriseAdminGuard(); const f = new FormData(event.target), id = enterprise.editCarrier;
        if (!id && !state.session) throw Error('Sign in first. No carrier connection or API key has been saved.');
        const body = { priority: Number(f.get('priority')), timeout_seconds: Number(f.get('timeout_seconds')), is_active: f.has('is_active') };
        const shared = event.target.dataset.scope === 'PLATFORM';
        if (!id || shared) body.request_id=event.target.dataset.requestId;
        if (!id || shared) for (const k of ['tenant_id','account_name','aggregator','api_base_url','api_key','environment','regional_provider_code','upstream_account_id']) if (f.get(k)) body[k] = String(f.get(k)).trim();
        if (shared) { delete body.tenant_id; if (event.target.dataset.provider === 'SENDCLOUD' && (f.get('sendcloud_public_key') || f.get('sendcloud_secret_key'))) { if (!f.get('sendcloud_public_key') || !f.get('sendcloud_secret_key')) throw Error('Supply both Sendcloud keys.'); body.api_key = JSON.stringify({public_key:String(f.get('sendcloud_public_key')).trim(),secret_key:String(f.get('sendcloud_secret_key')).trim()}); } }
        try {
            if (state.session) await api((shared ? '/api/v1/admin/platform-carriers' : '/api/v1/admin/carriers') + (id ? '/' + encodeURIComponent(id) : ''), { method: id ? (shared ? 'PUT' : 'PATCH') : 'POST', body, auth: true });
            else {
                delete body.api_key;
                const row = { ...body, id: id || crypto.randomUUID(), company_name: enterprise.tenants.find(t => t.tenant_id === body.tenant_id)?.company_name };
                if (id) enterprise.carriers = enterprise.carriers.map(c => c.id === id ? { ...c, ...row, company_name: c.company_name } : c); else enterprise.carriers.unshift(row);
            }
            $('#carrier-admin-dialog').close(); await loadEnterpriseView('admin-carriers'); notify(state.session ? 'Connection configuration saved.' : 'Sample connection updated. No provider API call occurred.');
        } finally { event.target.elements.api_key.value = ''; event.target.elements.sendcloud_public_key.value = ''; event.target.elements.sendcloud_secret_key.value = ''; }
    });
});
let pendingRetirement = null;
document.addEventListener('click', event => {
    const m = event.target.closest('[data-margin-edit]'); if (m) openMarginForm(m.dataset.marginEdit);
    const c = event.target.closest('[data-carrier-edit]'); if (c) openCarrierForm(c.dataset.carrierEdit);
    const carrierRemoval=event.target.closest('[data-carrier-disable]');
    if(carrierRemoval){busy(carrierRemoval,async()=>{enterpriseAdminGuard();const id=carrierRemoval.dataset.carrierDisable;const row=enterprise.carriers.find(r=>r.id===id);if(state.session)await api('/api/v1/admin/'+(row.platform_owned?'platform-carriers':'carriers')+'/'+encodeURIComponent(id)+'/disable',{method:'POST',auth:true});else{row.is_active=false;row.retired_at=null;}await loadEnterpriseView('admin-carriers');notify('Aggregator disabled for new outbound quotes. In-flight bookings, returns and refunds remain available.');});return;}
    const retire = event.target.closest('[data-margin-retire]');
    if (retire) {
        enterpriseAdminGuard(); pendingRetirement = retire.dataset.marginRetire ? ['margins', retire.dataset.marginRetire] : ['carriers', retire.dataset.carrierRetire];
        $('#retire-context').textContent = `Retire ${pendingRetirement[0]} configuration ${pendingRetirement[1]}?`; $('#retire-admin-dialog').showModal();
    }
    const client = event.target.closest('[data-client-margins]');
    if (client) { setView('admin-margins'); $('#margin-tenant-filter').value = client.dataset.clientMargins; renderEnterpriseTables(); }
});
$('#retire-confirm').addEventListener('click', () => busy($('#retire-confirm'), async () => {
    enterpriseAdminGuard(); const [kind, id] = pendingRetirement; const row = enterprise[kind].find(r => r.id === id);
    if (state.session) await api('/api/v1/admin/' + (kind === 'carriers' && row.platform_owned ? 'platform-carriers' : kind) + '/' + encodeURIComponent(id), { method: 'DELETE', auth: true });
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
        let registeredStore;
        if (state.session) registeredStore = await api('/api/v1/workspace/stores', { method: 'POST', body, auth: true });
        else enterprise.stores.push({ id: crypto.randomUUID(), ...body, is_active: true });
        $('#store-admin-dialog').close(); if (state.session) await loadEnterpriseView('stores'); else renderEnterpriseStores();
        notify('Store registered. Complete connection settings to import orders.');
        if (registeredStore) document.querySelector('[data-store-settings="'+registeredStore.id+'"]')?.click();
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

$('#carrier-rows').addEventListener('click', event => {
    const button=event.target.closest('[data-carrier-verify]');
    if (!button) return;
    busy(button, async () => {
        enterpriseAdminGuard();
        if (!state.session) throw Error('Sign in as an authorized platform owner.');
        const result=await api('/api/v1/admin/platform-carriers/'+encodeURIComponent(button.dataset.carrierVerify)+'/verify',{method:'POST',auth:true});
        notify(result.authenticated ? result.provider+' credentials verified. No label was created.' : result.provider+' returned HTTP '+result.upstream_http_status+'. Check the keys and account permissions.',!result.authenticated);
    });
});


// Owner-only native lifecycle configuration; secrets are write-only.
document.body.insertAdjacentHTML('beforeend', `<dialog id="native-provider-dialog"><button class="close" data-enterprise-close="native-provider-dialog" aria-label="Close native provider settings">&times;</button><h2>Native Orders &amp; Tracking Webhooks</h2><p class="subtle">EasyInvio keeps the master order. Enable native synchronization for this connection after reviewing your sandbox setup.</p><form id="native-provider-form"><label class="check"><input type="checkbox" name="order_sync_enabled">Synchronize prepared marketplace orders automatically</label><label id="native-sendcloud-integration">Sendcloud API integration ID<input type="number" min="1" name="sendcloud_integration_id"></label><label class="check"><input type="checkbox" name="webhook_enabled">Accept authenticated native tracking events</label><label>Webhook authentication<select name="webhook_auth"><option value="HMAC">Native HMAC signature</option><option value="URL_TOKEN">Shippo URL token (if HMAC is not provisioned)</option></select></label><label>Webhook secret (write-only)<input type="password" name="webhook_secret" autocomplete="new-password" placeholder="Leave blank to retain the saved secret"></label><p class="subtle">EasyPost: your webhook_secret. Sendcloud: its Secret Key or Webhook Signature Key. Shippo HMAC requires provisioning by Shippo; otherwise use a generated URL token.</p><label>Approved POD hostnames (comma separated)<input name="pod_allowed_hosts" placeholder="Exact carrier or storage hostnames"></label><label id="native-sendcloud-statuses">Sendcloud numeric status mapping<textarea name="sendcloud_status_map" rows="4" spellcheck="false" placeholder='JSON mapping verified status IDs to IN_TRANSIT, DELIVERED or EXCEPTION'></textarea></label><p id="native-webhook-path" class="subtle" style="overflow-wrap:anywhere"></p><p class="subtle">Prepend your public HTTPS backend address to this path, then register it in the provider dashboard. Never put an API key in the webhook URL. For Shippo URL-token authentication, append the saved webhook token as its token query parameter.</p><button class="primary full">Save Native Settings</button></form></dialog>`);
document.addEventListener('click',event=>{const button=event.target.closest('[data-native-settings]');if(!button)return;busy(button,async()=>{enterpriseAdminGuard();if(!state.session)throw Error('Sign in as the platform owner first.');const nativeSession=state.session;const id=button.dataset.nativeSettings;const row=enterprise.carriers.find(c=>c.id===id);const result=await api('/api/v1/admin/platform-carriers/'+encodeURIComponent(id)+'/native-settings',{auth:true});if(state.session!==nativeSession)throw Error('Session changed. Sign in again.');const form=$('#native-provider-form');form.reset();form.dataset.connectionId=id;form.elements.order_sync_enabled.checked=Boolean(result.order_sync_enabled);form.elements.webhook_enabled.checked=Boolean(result.webhook_enabled);form.elements.webhook_auth.value=result.webhook_auth||'HMAC';form.elements.sendcloud_integration_id.value=result.sendcloud_integration_id||'';form.elements.pod_allowed_hosts.value=(result.pod_allowed_hosts||[]).join(', ');form.elements.sendcloud_status_map.value=JSON.stringify(result.sendcloud_status_map||{},null,2);const sendcloud=row.api_base_url==='https://panel.sendcloud.sc/api/v3';$('#native-sendcloud-integration').hidden=!sendcloud;$('#native-sendcloud-statuses').hidden=!sendcloud;form.elements.webhook_auth.disabled=row.api_base_url!=='https://api.goshippo.com';$('#native-webhook-path').textContent='Webhook path: '+result.webhook_path;$('#native-provider-dialog').showModal();});});
$('#native-provider-form').addEventListener('submit',event=>{event.preventDefault();busy(event.target.querySelector('button'),async()=>{enterpriseAdminGuard();const form=event.target;const body={order_sync_enabled:form.elements.order_sync_enabled.checked,webhook_enabled:form.elements.webhook_enabled.checked,webhook_auth:form.elements.webhook_auth.value,pod_allowed_hosts:form.elements.pod_allowed_hosts.value.split(',').map(v=>v.trim().toLowerCase()).filter(Boolean),sendcloud_status_map:JSON.parse(form.elements.sendcloud_status_map.value||'{}')};if(form.elements.sendcloud_integration_id.value)body.sendcloud_integration_id=Number(form.elements.sendcloud_integration_id.value);if(form.elements.webhook_secret.value)body.webhook_secret=form.elements.webhook_secret.value;await api('/api/v1/admin/platform-carriers/'+encodeURIComponent(form.dataset.connectionId)+'/native-settings',{method:'PUT',auth:true,body});form.elements.webhook_secret.value='';$('#native-provider-dialog').close();notify('Native settings saved. Register the webhook path at the provider to enable real delivery.');});});
$('#native-provider-dialog').addEventListener('close',()=>{$('#native-provider-form').elements.webhook_secret.value='';});

const nativeClearSessionBase=clearSession;clearSession=function(){const form=$('#native-provider-form');form.reset();delete form.dataset.connectionId;$('#native-provider-dialog').close();return nativeClearSessionBase.apply(this,arguments);};

document.body.insertAdjacentHTML('beforeend','<dialog id="quote-diagnostics-dialog"><button class="close" data-enterprise-close="quote-diagnostics-dialog">Close</button><h2>Connection capabilities and recent quote coverage</h2><div id="quote-diagnostics-body"></div></dialog>');
document.addEventListener('click',event=>{const b=event.target.closest('[data-quote-diagnostics]');if(!b)return;busy(b,async()=>{
 enterpriseAdminGuard();const session=state.session;if(!session)throw Error('Sign in as the platform owner.');const r=await api('/api/v1/admin/platform-carriers/'+b.dataset.quoteDiagnostics+'/quote-diagnostics',{auth:true});if(state.session!==session)throw Error('Session changed. Sign in again.');
 $('#quote-diagnostics-body').innerHTML=`<h3>${escapeHTML(r.account_name)}</h3><p>${escapeHTML(r.environment)} - ${r.is_active?'Enabled for future quotes':'Disabled for future quotes'}</p><p><b>Tracking receiver:</b> ${r.tracking?.receiver_enabled?'Enabled':'Disabled'}; signing secret ${r.tracking?.signing_secret_saved?'saved':'not configured'}; ${Number(r.tracking?.received_events||0)} received events. A public HTTPS receiver and matching provider subscription are required.</p><p><b>Parcels:</b> ${escapeHTML(r.parcel)}</p><p><b>Letters:</b> ${escapeHTML(r.letter)}</p><p><b>Freight:</b> ${escapeHTML(r.freight)}</p><p>Saved offers: ${r.recent_saved_offer_count}; carriers: ${escapeHTML(r.carriers.join(', ')||'none recorded')}</p><p>Recorded failure codes: ${escapeHTML(r.failure_codes.join(', ')||'none in saved quotes')}</p><p class="notice">${escapeHTML(r.scope)}</p>`;$('#quote-diagnostics-dialog').showModal();
});});

const diagnosticsClearSessionBase=clearSession;clearSession=function(){$('#quote-diagnostics-dialog').close();$('#quote-diagnostics-body').replaceChildren();return diagnosticsClearSessionBase.apply(this,arguments);};
