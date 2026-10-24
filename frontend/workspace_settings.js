// Workspace company and team settings; all mutations are server-authorized.
async function loadWorkspaceSettings(){
 if(!state.session||portal.profile?.workspace_role!=='OWNER')throw Error('Sign in as your workspace owner.');
 const session=state.session,tenant=portal.profile.tenant_id;
 const result=await api('/api/v1/workspace/settings',{auth:true});
 if(state.session!==session||portal.profile?.tenant_id!==tenant)return;
 $('#workspace-team').hidden=false;
 for(const field of ['company_name','workspace_name','billing_email'])$('#company-settings-form').elements[field].value=result.company[field]||'';
 $('#settings-members').innerHTML=result.members.map(m=>`<div class="notice"><strong>${escapeHTML(m.full_name)}</strong> &middot; ${escapeHTML(m.email)} &middot; ${escapeHTML(m.role)} ? ${m.is_active?'Active':'Disabled'}${['DISPATCHER','ACCOUNTANT'].includes(m.role)?`<div class="actions"><select aria-label="Role for ${escapeHTML(m.full_name)}" data-member-role="${m.id}"><option ${m.role==='DISPATCHER'?'selected':''}>DISPATCHER</option><option ${m.role==='ACCOUNTANT'?'selected':''}>ACCOUNTANT</option></select><button class="secondary" data-member-update="${m.id}" data-member-active="${m.is_active}">Update role</button><button class="secondary" data-member-reset="${escapeHTML(m.email)}">Send password reset link</button><button class="secondary" data-member-toggle="${m.id}" data-member-active="${!m.is_active}">${m.is_active?'Disable':'Enable'}</button></div>`:''}</div>`).join('')||'<p>No workspace users.</p>';
 $('#settings-invitations').innerHTML=result.invitations.map(i=>`<p>${escapeHTML(i.first_name+' '+i.last_name)} &middot; ${escapeHTML(i.email)} &middot; ${escapeHTML(i.role)} &middot; ${escapeHTML(i.status==='PENDING'&&new Date(i.expires_at).getTime()<Date.now()?'EXPIRED':i.status)}${['PENDING','FAILED','CANCELLED'].includes(i.status)?`<button class="secondary" data-invite-resend="${i.id}">Resend invitation</button>`:''}${['SENDING','PENDING'].includes(i.status)?`<button class="secondary" data-invite-cancel="${i.id}">Cancel invitation</button>`:''}</p>`).join('')||'<p>No invitations.</p>';
}
const settingsSetViewBase=setView;
setView=function(view){settingsSetViewBase(view);if(view==='settings'&&!$('#settings').hidden)loadWorkspaceSettings().catch(e=>notify(e.message,true));};
$('#workspace-member-form').addEventListener('submit',event=>{event.preventDefault();busy(event.target.querySelector('button'),async()=>{
 const result=await api('/api/v1/workspace/invitations',{method:'POST',auth:true,body:{first_name:$('#member-first-name').value.trim(),last_name:$('#member-last-name').value.trim(),email:$('#member-email').value.trim(),role:$('#member-role').value}});
 event.target.reset();$('#member-invite-status').textContent=result.message;await loadWorkspaceSettings();
});});
$('#company-settings-form').addEventListener('submit',event=>{event.preventDefault();busy(event.target.querySelector('button'),async()=>{
 await api('/api/v1/workspace/settings',{method:'PATCH',auth:true,body:Object.fromEntries(new FormData(event.target))});notify('Workspace company profile saved.');
});});
$('#settings-members').addEventListener('click',event=>{const reset=event.target.closest('[data-member-reset]');if(reset){busy(reset,async()=>{const r=await api('/api/v1/auth/forgot-password',{method:'POST',body:{email:reset.dataset.memberReset}});notify(r.message);});return;}const b=event.target.closest('[data-member-update],[data-member-toggle]');if(!b)return;busy(b,async()=>{
 const id=b.dataset.memberUpdate||b.dataset.memberToggle;await api('/api/v1/workspace/users/'+id,{method:'PATCH',auth:true,body:{role:document.querySelector(`[data-member-role="${id}"]`).value,is_active:b.dataset.memberActive==='true'}});await loadWorkspaceSettings();notify('Team access updated; previous app sessions revoked.');
});});
$('#settings-invitations').addEventListener('click',event=>{const b=event.target.closest('[data-invite-cancel],[data-invite-resend]');if(!b)return;busy(b,async()=>{await api('/api/v1/workspace/invitations/'+(b.dataset.inviteCancel||b.dataset.inviteResend)+(b.dataset.inviteResend?'/resend':'/cancel'),{method:'POST',auth:true});await loadWorkspaceSettings();});});
const settingsClearBase=clearSession;clearSession=function(){activeDispute=null;$('#dispute-draft').value='';$('#dispute-status').textContent='';$('#dispute-dialog').close();for(const id of ['settings-members','settings-invitations'])$('#'+id).replaceChildren();$('#company-settings-form').reset();$('#workspace-member-form').reset();$('#member-invite-status').textContent='';return settingsClearBase.apply(this,arguments);};
