// Embedded identity gateway: verified profiles, short-lived app sessions and logout.
const identityStorageKey = 'easyinvio.session';
let identityProfile = null;
let identityRecoveryHash = null;
document.head.insertAdjacentHTML('beforeend', `<style>
body.auth-locked>.topbar,body.auth-locked>.app-shell,body.auth-locked>.mobile-nav,body.auth-locked>#customs-backdrop,body.auth-locked>#box-backdrop{display:none!important}
#loginContainer{min-height:100dvh;display:grid;place-items:center;padding:24px;color:#f1f5f9;background:radial-gradient(ellipse at 50% 20%,#25245666,transparent 60%),#0f172a}
#loginContainer[hidden]{display:none}.identity-login-card{width:100%;max-width:440px;background:#020617;border:1px solid #1e293b;border-radius:24px;padding:32px;box-shadow:0 0 50px #4f46e526;animation:identityFade .35s ease-out}
.identity-logo{font-size:32px;font-weight:900;letter-spacing:-1px;animation:identityGlow 3s ease-in-out infinite}.identity-logo em{color:#34d399;font-style:normal}
.identity-input{display:flex;align-items:center;gap:10px;background:#0f172a;border:1px solid #334155;border-radius:12px;padding:0 12px;margin-bottom:18px}.identity-input input{border:0;background:transparent;min-width:0;color:#f1f5f9;flex:1}.identity-input svg{width:20px;height:20px;color:#818cf8;flex-shrink:0}.identity-input:has(.lucide)>.icon-fallback{display:none}
#identity-login-submit{width:100%;background:#4f46e5;color:#f1f5f9;border:0;border-radius:12px;padding:14px;font-weight:800;cursor:pointer}#identity-login-submit:hover{background:#6366f1}
#identity-user-widget{display:flex;align-items:center;gap:10px}#identity-avatar{width:34px;height:34px;border-radius:50%;background:#312e81;color:#e0e7ff;display:grid;place-items:center;font-weight:800}#identity-logout:hover{color:#f87171}
body.auth-ready>.app-shell{animation:identityFade .3s ease-out}@keyframes identityFade{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}@keyframes identityGlow{50%{text-shadow:0 0 28px #818cf888}}
@media(prefers-reduced-motion:reduce){.identity-logo,.identity-login-card,body.auth-ready>.app-shell{animation:none}}
</style>`);
document.body.insertAdjacentHTML('afterbegin', `<section id="loginContainer" aria-label="EasyInvio sign in">
<div class="identity-login-card bg-slate-950 border border-slate-800 rounded-3xl p-8 max-w-md w-full shadow-2xl animate-fade-in">
 <div class="identity-logo shadow-[0_0_50px_rgba(79,70,229,0.15)]">EasyInvio<em>.com</em></div>
 <p class="eyebrow">Shipping intelligence platform</p><h1 style="font-size:26px;margin-top:24px">Sign in to your workspace</h1><p class="subtle">Your verified identity controls access to shipments, billing and administration.</p>
 <form id="identity-login-form" style="margin-top:24px"><label for="identity-email">Email</label><div class="identity-input"><i data-lucide="mail"></i><svg class="icon-fallback" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/></svg><input id="identity-email" type="email" autocomplete="username" required maxlength="254"></div>
 <label for="identity-password">Password</label><div class="identity-input"><i data-lucide="lock"></i><svg class="icon-fallback" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4"/></svg><input id="identity-password" type="password" autocomplete="current-password" required maxlength="4096"></div>
 <button id="identity-login-submit" class="w-full bg-indigo-600 hover:bg-indigo-500 text-slate-100 font-bold py-3 rounded-xl transition-all" type="submit">Sign In</button>
 <p id="identity-login-status" class="footnote" role="status" aria-live="polite"></p></form>
</div></section>`);
document.querySelector('main').insertAdjacentHTML('beforeend', `<section id="profile" hidden>
<div class="pagehead"><div><div class="eyebrow">Your identity</div><h1>User Profile</h1><p>Manage contact details. Permissions are assigned by your administrator.</p></div></div>
<article class="card bg-slate-950 border border-slate-800"><span id="identity-role" class="tag green"></span><p id="identity-email-badge" class="mono"></p>
<form id="identity-profile-form"><label>Full name<input name="full_name" required maxlength="200" autocomplete="name"></label><label>Phone (E.164)<input name="phone_e164" type="tel" pattern="\\+[1-9][0-9]{7,14}" placeholder="+447700900123" autocomplete="tel"></label><p class="subtle">Editing contact details does not change verified WhatsApp pairing.</p><button class="primary" type="submit">Save Profile</button></form></article></section>`);
document.querySelector('.topbar-actions').insertAdjacentHTML('beforeend', `<div id="identity-user-widget" hidden><button id="identity-avatar" aria-label="Open user profile"></button><button id="identity-logout" class="outline" aria-label="Log out"><i data-lucide="log-out"></i>Log Out</button></div>`);

function showIdentityGate() {
  const signedIn = !identityRecoveryHash && !!state.session && !!identityProfile;
  document.body.classList.toggle('auth-locked', !signedIn);
  document.body.classList.toggle('auth-ready', signedIn);
  $('#loginContainer').hidden = signedIn;
  $('#identity-user-widget').hidden = !signedIn;
  if (signedIn) $('#identity-avatar').textContent = identityProfile.email.slice(0,1).toUpperCase();
  refreshIcons();
}

async function loadIdentityProfile() {
  const active = state.session;
  const profile = await api('/api/v1/auth/me', {auth:true});
  if (active !== state.session) return;
  identityProfile = profile;
  $('#identity-email-badge').textContent = profile.email;
  $('#identity-role').textContent = profile.role === 'SUPER_ADMIN' ? '🛡️ Platform Super-Admin' : '📦 ' + profile.role.charAt(0) + profile.role.slice(1).toLowerCase();
  const form = $('#identity-profile-form');
  form.elements.full_name.value = profile.full_name || '';
  form.elements.phone_e164.value = profile.phone_e164 || '';
  showIdentityGate();
}

async function process_user_login(email = $('#identity-email').value, password = $('#identity-password').value) {
  $('#identity-login-submit').disabled = true;
  $('#identity-login-status').textContent = 'Verifying your identity…';
  try {
    const session = await api('/api/v1/auth/token', {method:'POST',body:{email:email.trim(),password}});
    state.session = session;
    renderAccount();
    portal.profile = await api('/api/v1/profile',{auth:true});
    portal.role = portal.profile.portal_role === 'SUPER_ADMIN' ? 'SUPER_ADMIN' : 'CLIENT';
    await loadIdentityProfile();
    localStorage.setItem(identityStorageKey, JSON.stringify(session));
    armSessionExpiry();renderAccount();renderPortal();setView(portal.profile.workspace_role === 'DISPATCHER' && portal.profile.portal_role !== 'SUPER_ADMIN' ? 'workspace' : 'dashboard');
    $('#account-dialog').close();
    $('#identity-login-status').textContent = '';
  } catch(error) {
    clearSession();$('#identity-login-status').textContent = error.message || 'Sign-in failed.';
    throw error;
  } finally {
    $('#identity-password').value = '';$('#login-password').value = '';$('#identity-login-submit').disabled = false;
  }
}

const identityClearBase = clearSession;
clearSession = function() {
  identityProfile = null;
  localStorage.removeItem(identityStorageKey);
  identityClearBase();
  $('#identity-profile-form').reset();$('#identity-email-badge').textContent='';$('#identity-role').textContent='';
  $$('dialog').forEach(dialog => dialog.close());
  showIdentityGate();
};

async function logoutIdentity() {
  let token = state.session?.access_token;
  clearSession();$('#identity-email').focus();
  try {
    if (token) { const response = await fetch(API+'/api/v1/auth/logout',{method:'POST',headers:{Authorization:'Bearer '+token}}); if (!response.ok) throw Error('Server logout unavailable'); }
  } finally { token = null; }
}
$('#identity-login-form').addEventListener('submit', event => {event.preventDefault();process_user_login().catch(()=>{});});
$('#identity-profile-form').addEventListener('submit', event => {
  event.preventDefault();busy(event.target.querySelector('button'), async () => {
    const f=new FormData(event.target);await api('/api/v1/auth/me',{method:'PATCH',auth:true,body:{full_name:String(f.get('full_name')).trim(),phone_e164:String(f.get('phone_e164')).trim() || null}});
    await loadIdentityProfile();notify('Profile saved.');
  });
});
$('#identity-avatar').addEventListener('click',()=>setView('profile'));
$('#identity-logout').addEventListener('click',()=>logoutIdentity().catch(()=>notify('Signed out locally; server logout could not be confirmed.',true)));
$('#signout-btn').addEventListener('click',event=>{event.stopImmediatePropagation();logoutIdentity().catch(()=>{});},true);
window.addEventListener('storage', event => {if(event.key===identityStorageKey && !event.newValue) clearSession();});
async function restoreIdentitySession() {
  showIdentityGate();
  try {
    const saved=JSON.parse(localStorage.getItem(identityStorageKey)||'null');
    if (!saved?.access_token || Number(saved.expires_at)*1000<=Date.now()) {localStorage.removeItem(identityStorageKey);return;}
    state.session=saved;
    renderAccount();
    portal.profile=await api('/api/v1/profile',{auth:true});
    portal.role=portal.profile.portal_role==='SUPER_ADMIN'?'SUPER_ADMIN':'CLIENT';
    await loadIdentityProfile();armSessionExpiry();renderAccount();renderPortal();
    setView(portal.profile.workspace_role==='DISPATCHER' && portal.profile.portal_role!=='SUPER_ADMIN'?'workspace':'dashboard');
  } catch {clearSession();}
}
// Recovery links carry a one-use token hash in the fragment, never an app JWT.
// Remove it before rendering or restoring any saved workspace session.
const recoveryFragment = new URLSearchParams(location.hash.slice(1));
if (recoveryFragment.get('type') === 'recovery') {
  identityRecoveryHash = recoveryFragment.get('token_hash');
  history.replaceState(null, '', location.pathname + location.search);
  clearSession();
}
document.querySelector('#identity-login-form').insertAdjacentHTML('afterend', `
<button type="button" id="identity-forgot" class="outline" style="width:100%;margin-top:12px;color:#a5b4fc">Forgot password?</button>
<form id="identity-recovery-form" hidden style="margin-top:24px">
 <h2>Reset your password</h2><p class="subtle">We will send a secure reset link to your registered email.</p>
 <label for="identity-recovery-email">Email</label><div class="identity-input"><input id="identity-recovery-email" type="email" autocomplete="email" required maxlength="254"></div>
 <button class="primary" type="submit" style="width:100%">Send reset link</button>
 <button class="outline" type="button" data-identity-back style="width:100%;margin-top:12px">Back to sign in</button>
 <p class="footnote" role="status" aria-live="polite"></p>
</form>
<form id="identity-reset-form" hidden style="margin-top:24px">
 <h2>Choose a new password</h2><p class="subtle">Use at least 12 characters. A long, unique passphrase is best.</p>
 <label for="identity-new-password">New password</label><div class="identity-input"><input id="identity-new-password" type="password" autocomplete="new-password" required minlength="12" maxlength="128"></div>
 <label for="identity-confirm-password">Confirm password</label><div class="identity-input"><input id="identity-confirm-password" type="password" autocomplete="new-password" required minlength="12" maxlength="128"></div>
 <button class="primary" type="submit" style="width:100%">Update password securely</button>
 <button class="outline" type="button" data-identity-back style="width:100%;margin-top:12px">Back to sign in</button>
 <p class="footnote" role="status" aria-live="polite"></p>
</form>`);
function identityRecoveryView(view) {
  $('#identity-login-form').hidden = view !== 'login';
  $('#identity-forgot').hidden = view !== 'login';
  $('#identity-recovery-form').hidden = view !== 'request';
  $('#identity-reset-form').hidden = view !== 'reset';
  showIdentityGate();
}
$('#identity-forgot').addEventListener('click', () => {
  $('#identity-recovery-email').value = $('#identity-email').value;
  identityRecoveryView('request');$('#identity-recovery-email').focus();
});
$$('[data-identity-back]').forEach(button => button.addEventListener('click', () => {
  identityRecoveryHash = null;$('#identity-reset-form').reset();identityRecoveryView('login');
}));
$('#identity-recovery-form').addEventListener('submit', async event => {
  event.preventDefault();const form=event.target;const button=form.querySelector('[type=submit]');const status=form.querySelector('[role=status]');
  button.disabled=true;status.textContent='Sending your request?';
  try { const result=await api('/api/v1/auth/forgot-password',{method:'POST',body:{email:$('#identity-recovery-email').value.trim()}});status.textContent=result.message; }
  catch(error) {status.textContent=error.message || 'Unable to request recovery. Try again later.';}
  finally {button.disabled=false;}
});
$('#identity-reset-form').addEventListener('submit', async event => {
  event.preventDefault();const form=event.target;const button=form.querySelector('[type=submit]');const status=form.querySelector('[role=status]');
  const password=$('#identity-new-password').value;
  if(password!==$('#identity-confirm-password').value){status.textContent='Passwords must match.';return;}
  if(!identityRecoveryHash){status.textContent='This link is invalid. Request a new reset link.';return;}
  button.disabled=true;status.textContent='Updating your password?';
  try {
    const result=await api('/api/v1/auth/reset-password',{method:'POST',body:{token_hash:identityRecoveryHash,password}});
    identityRecoveryHash=null;clearSession();identityRecoveryView('login');$('#identity-login-status').textContent=result.message;
  } catch(error) {status.textContent=error.message || 'Unable to reset. Request a new link.';}
  finally {form.reset();button.disabled=false;}
});
if(recoveryFragment.get('type')==='recovery') {
  identityRecoveryView('reset');
  if(!identityRecoveryHash) $('#identity-reset-form [role=status]').textContent='This link is invalid. Request a new reset link.';
} else restoreIdentitySession();

window.addEventListener('hashchange', () => {
  const incoming = new URLSearchParams(location.hash.slice(1));
  if (incoming.get('type') !== 'recovery') return;
  identityRecoveryHash = incoming.get('token_hash');
  history.replaceState(null, '', location.pathname + location.search);
  clearSession();identityRecoveryView('reset');
});
