// Embedded in index.html: cargo-aligned packaging guidance and measured-size shortcuts.
const packagingChoices = [
  {cargo: 'LETTER', title: 'Business Letter', icon: 'mail', description: 'Documents in an envelope. EasyInvio requires packed weight below 0.5 kg; the carrier checks its own envelope format.', sizes: [{name: 'Choose document letter', dimensions: null}]},
  {cargo: 'PARCEL', title: 'Standard Parcel', icon: 'box', description: 'Boxed goods. These three examples are packing shortcuts, not carrier size classes.', sizes: [{name: 'Compact carton', dimensions: [24, 16, 8]}, {name: 'Medium carton', dimensions: [40, 30, 20]}, {name: 'Large carton', dimensions: [60, 40, 40]}]},
  {cargo: 'PALLET', title: 'Heavy Pallet Freight', icon: 'pallet', description: 'Goods secured to a pallet. Enter the full packed height, overhang and weight. A freight contract is required; parcel connections cannot quote this category.', sizes: [{name: '120 × 80 cm footprint', dimensions: [120, 80, null]}, {name: '120 × 100 cm footprint', dimensions: [120, 100, null]}]},
  {cargo: 'OVERLAND_FREIGHT', title: 'Overland Freight', icon: 'truck', description: 'Road cargo with measured dimensions and loading requirements. Size and weight limits depend on the contracted freight service.', sizes: [{name: 'Choose road freight · enter measurements', dimensions: null}]}
];
const packagingIllustrations = {
  mail: '<rect x="5" y="12" width="54" height="38" rx="4"/><path d="m7 15 25 19 25-19"/>',
  box: '<path d="m8 20 24-12 24 12v27L32 59 8 47Z M8 20l24 13 24-13 M32 33v26 M20 14l24 13"/>',
  pallet: '<path d="M5 46h54v9H5z M13 55v5 M32 55v5 M51 55v5 M9 19h23v27H9z M32 19h23v27H32z M20 19v9 M43 19v9 M20 5h24v14H20z"/>',
  truck: '<path d="M4 16h34v30H4z M38 27h13l9 12v7H38 M44 27v12h16"/><circle cx="16" cy="49" r="6"/><circle cx="49" cy="49" r="6"/>'
};
document.head.insertAdjacentHTML('beforeend', `<style>
#packaging-size-dialog{width:min(900px,calc(100vw - 24px));max-height:90dvh;padding:22px;overflow:auto;border:1px solid #334155;border-radius:18px;background:#071020;color:#e2e8f0}
#packaging-size-dialog::backdrop{background:#020617cc;backdrop-filter:blur(5px)}
.packaging-header{display:flex;justify-content:space-between;align-items:start;gap:16px;margin-bottom:16px}.packaging-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.packaging-card{padding:16px;border:1px solid #334155;border-radius:12px;background:#101a2e}.packaging-card[data-selected=true]{border-color:#34d399}.packaging-card header{display:flex;align-items:center;gap:12px;margin-bottom:8px}.packaging-art{width:48px;height:48px;flex-shrink:0;color:#6ee7b7}.packaging-card h3{font-size:16px}.packaging-card p{margin-bottom:12px;line-height:1.5}.packaging-options{display:grid;gap:6px}.packaging-options button{justify-content:space-between;text-align:left}.packaging-options small{color:#94a3b8}.packaging-reference{padding:12px;margin:12px 0;border:1px solid #334155;border-radius:10px}.packaging-reference p{margin-top:8px}.packaging-reference a{color:#a5b4fc}.packaging-custom{margin-top:12px}.packaging-custom .profile-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.packaging-custom .box-profile{padding:12px}.packaging-custom .box-shape{display:none}
@media(max-width:600px){#packaging-size-dialog{padding:16px}.packaging-grid{grid-template-columns:1fr}.packaging-custom .profile-list{grid-template-columns:1fr}.packaging-options button{flex-wrap:wrap}}
</style>`);
const packagingDialog = document.createElement('dialog');
packagingDialog.id = 'packaging-size-dialog';
packagingDialog.setAttribute('aria-labelledby', 'packaging-title');
packagingDialog.innerHTML = `<div class="packaging-header"><div><div class="eyebrow">Choose cargo &amp; packaging</div><h2 id="packaging-title">Packaging sizes</h2><p class="subtle">Choose a starting size, then measure your sealed package. Weight is always yours to enter.</p></div><button type="button" class="secondary" id="packaging-close" aria-label="Close packaging sizes">Close</button></div><div id="packaging-categories" class="packaging-grid"></div><details class="packaging-reference" open><summary>Carrier limits for your route</summary><div id="packaging-route-guidance"></div></details><details class="packaging-custom"><summary>My saved carton sizes (optional)</summary><p class="subtle">Saved cartons use Standard Parcel. Browser and workspace only.</p><div id="packaging-saved"></div></details>`;
document.body.append(packagingDialog);
// Reuse the saved-carton library without keeping a separate navigation page.
$('#packaging-saved').append($('#box-profile-list'), $('#box-profile-form').parentElement);
let packagingOpener = null;
function openPackagingSizes() {
  if (!allowedEnterpriseViews().includes('dispatch')) return;
  finishPackageReview(false);
  packagingOpener = document.activeElement;
  $('#packaging-categories').innerHTML = packagingChoices.map((choice, index) => `<article class="packaging-card" data-selected="${$('#cargo-type').value === choice.cargo}"><header><svg class="packaging-art" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">${packagingIllustrations[choice.icon]}</svg><h3>${choice.title}</h3></header><p class="subtle">${choice.description}</p><div class="packaging-options">${choice.sizes.map((size, sizeIndex) => `<button type="button" class="secondary" data-packaging-choice="${index}" data-packaging-size="${sizeIndex}"><span>${size.name}</span>${size.dimensions && size.dimensions.every(Number.isFinite) ? `<small>${size.dimensions.join(' × ')} cm</small>` : ''}</button>`).join('')}</div></article>`).join('');
  const origin = $('#origin-country_code').value, destination = $('#destination-country_code').value;
  const dpdRoute = origin === 'GB' && destination && !['GB', 'GG', 'JE', 'IM'].includes(destination);
  $('#packaging-route-guidance').innerHTML = `<p class="subtle">${escapeHTML(origin || 'Origin')} → ${escapeHTML(destination || 'Destination')}. There is no universal minimum or maximum across all carriers. Live rates check the address, service and enabled account.</p>${dpdRoute ? '<p><b>DPD UK international parcel reference</b>: packed weight up to 31 kg, longest side below 175 cm, and longest side + twice each other side below 300 cm.</p><p class="subtle">For example, 90 × 30 × 90 cm exceeds this service’s size limit. Other carriers may accept different sizes.</p><a href="https://myportal.drivers.dpd.co.uk/terms" target="_blank" rel="noopener noreferrer">Read DPD service limits</a>' : '<p class="subtle">Limits depend on your chosen carrier and destination. Enter accurate measurements to check available services. Letter and freight formats require the corresponding carrier contract.</p>'}<p class="subtle">A box example is not a guarantee of a rate. Never reduce entered dimensions unless you physically repack the goods. Pallet footprints are examples; height and packed weight must be measured.</p>`;
  renderBoxes();
  if (!packagingDialog.open) packagingDialog.showModal();
}
function applyPackagingChoice(cargo, dimensions) {
  const packedWeight = $('#weight_kg').value;
  $('#cargo-type').value = cargo;
  configureCargo(false);
  cargoCapabilityNotice();
  if (dimensions) ['length_cm', 'width_cm', 'height_cm'].forEach((id, i) => $('#' + id).value = dimensions[i] ?? '');
  else if (cargo === 'OVERLAND_FREIGHT') ['length_cm', 'width_cm', 'height_cm'].forEach(id => $('#' + id).value = '');
  $('#weight_kg').value = packedWeight;
  $('#quote-form').dispatchEvent(new Event('input', {bubbles: true}));
  packagingOpener = null;
  packagingDialog.close();
  setView('dispatch');
  const target = cargo === 'LETTER' ? $('#weight_kg') : ['length_cm', 'width_cm', 'height_cm'].map(id => $('#' + id)).find(input => !input.value) || $('#length_cm');
  target.focus();
  target.scrollIntoView({block: 'center', behavior: 'smooth'});
  notify('Packaging selected. Check the actual packed dimensions and weight before requesting rates.');
}
applyBox = function(index) {
  const box = portal.boxes[index];
  if (box) applyPackagingChoice('PARCEL', [box.l, box.w, box.h]);
};
packagingDialog.addEventListener('click', event => {
  const button = event.target.closest('[data-packaging-choice]');
  if (!button) return;
  const choice = packagingChoices[Number(button.dataset.packagingChoice)];
  const size = choice?.sizes[Number(button.dataset.packagingSize)];
  if (size) applyPackagingChoice(choice.cargo, size.dimensions);
});
$('#packaging-close').addEventListener('click', () => packagingDialog.close());
packagingDialog.addEventListener('close', () => {
  if (packagingOpener?.isConnected) packagingOpener.focus();
});
document.addEventListener('click', event => {
  if (event.target.closest('[data-packaging-open]')) openPackagingSizes();
});
const packagingSetViewBase = setView;
setView = function(view) {
  if (view === 'boxes') { openPackagingSizes(); return; }
  if (packagingDialog.open) packagingDialog.close();
  packagingSetViewBase(view);
};
const packagingRenderAccountBase = renderAccount;
renderAccount = function() {
  if (packagingDialog.open) packagingDialog.close();
  packagingRenderAccountBase();
};
