(() => {
  'use strict';
  const apiBase=location.port==='5500'?'http://127.0.0.1:8000':'';
  const content=document.getElementById('public-tracking-content'),message=document.getElementById('public-tracking-message'),refresh=document.getElementById('public-tracking-refresh');
  let input=null,accessToken=null,result=null,requestDraft=null,generation=0,expiryTimer=null;
  const safe=value=>{const span=document.createElement('span');span.textContent=String(value??'');return span.innerHTML.replaceAll('"','&quot;').replaceAll("'",'&#39;');};
  const human=value=>String(value||'Awaiting update').replaceAll('_',' ').toLowerCase();
  const when=value=>value?new Date(value).toLocaleString():'Not reported';
  const https=value=>{try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:null;}catch{return null;}};
  async function post(path,body){
    const response=await fetch(apiBase+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(15000)});
    const value=await response.json();if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'Tracking is unavailable. Please check your input and try later.');return value;
  }
  function brand(value){
    document.getElementById('merchant-name').textContent=value?.display_name||'EasyInvio';
    const logo=document.getElementById('merchant-logo'),url=https(value?.logo_url);
    document.getElementById('easyinvio-logo').hidden=!!url||value?.display_name&&value.display_name!=='EasyInvio';
    logo.hidden=!url;logo.onerror=()=>logo.hidden=true;if(url){logo.src=apiBase+'/api/v1/public/tracking/brand-logo?url='+encodeURIComponent(url);logo.title=(value.display_name||'Merchant')+' logo';}else logo.removeAttribute('src');
    const accent=/^#[0-9a-fA-F]{6}$/.test(value?.accent_hex)?value.accent_hex:'#059669';
    document.body.style.setProperty('--merchant-accent',accent);
    const support=document.getElementById('merchant-support'),supportUrl=https(value?.support_url);support.hidden=!supportUrl;if(supportUrl)support.href=supportUrl;
  }
  function lookupForm(){
    content.innerHTML='<form id="tracking-lookup"><label>Tracking number or EasyInvio tracking link<input name="text" required minlength="8" maxlength="2048" autocomplete="off"></label><button type="submit">Track my parcel</button><p role="status"></p></form>';
    content.querySelector('form').onsubmit=async event=>{event.preventDefault();try{const parsed=EasyInvioTracking.parse(event.target.elements.text.value);input=parsed;accessToken=null;requestDraft=null;history.replaceState(null,'',EasyInvioTracking.path(parsed));await load();}catch(error){event.target.querySelector('[role=status]').textContent=error.message;}};
  }
  function render(){
    brand(result.branding);
    const verified=result.access==='VERIFIED_RECIPIENT';
    clearTimeout(expiryTimer);
    if(verified){expiryTimer=setTimeout(()=>{generation++;accessToken=null;result=null;content.replaceChildren();lookupForm();message.textContent='Verified access expired. Verify again to view private details.';},Math.max(0,new Date(result.expires_at).getTime()-Date.now()));}
    content.innerHTML=result.shipments.map(shipment=>{
      const delivered=shipment.status==='DELIVERED',pod=delivered&&verified?https(shipment.proof_of_delivery_url):null;
      const returns=delivered&&verified&&/^\/returns\/[a-z0-9-]{3,63}$/.test(shipment.return_url||'')?shipment.return_url:null;
      const address=shipment.delivery_address?Object.values(shipment.delivery_address).map(safe).join('<br>'):'';
      return `<section class="public-parcel"><span class="tracking-badge" data-status="${safe(shipment.status)}">${safe(human(shipment.status))}</span><h2>${safe(shipment.order_reference||'Your parcel')}</h2><p>${EasyInvioBrands.markup(shipment.carrier,true)}${safe(shipment.carrier)} · ${safe(shipment.tracking_number)}</p><p>${shipment.estimated_delivery_at?'Estimated delivery: '+safe(when(shipment.estimated_delivery_at)):'Waiting for a confirmed delivery estimate.'}</p>${shipment.data_state==='STALE'?'<p>Waiting for a fresh carrier update. A delay has not been confirmed.</p>':''}<ol class="tracking-timeline">${(shipment.timeline||[]).map(event=>`<li><b>${safe(human(event.status))}</b><time>${safe(when(event.occurred_at))}</time>${event.location?'<small>'+safe(event.location)+'</small>':''}</li>`).join('')||'<li>The carrier has not supplied a scan yet.</li>'}</ol>${verified?`<section class="verified-summary"><h3>Verified delivery details</h3><p>${address}</p>${pod?`<a class="tracking-action" href="${safe(pod)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">View Proof of Delivery (POD)</a>`:delivered?'<p>The carrier has not supplied delivery evidence.</p>':''}${returns?`<a class="tracking-action" href="${safe(returns)}">Start a return</a>`:delivered?'<p>For return eligibility, contact your retailer.</p>':''}</section>`:''}</section>`;
    }).join('');
    if(!verified){
      const verification=document.createElement('form');verification.className='tracking-verification';
      verification.innerHTML='<h3>See your delivery details</h3><p>Verify the delivery postcode to view your address, available delivery evidence and eligible return options.</p>'+(input.kind==='CAPABILITY'?'<button type="submit">Continue with my secure tracking link</button>':'<label>Delivery postcode<input name="postcode" autocomplete="postal-code" minlength="2" maxlength="20" required></label><button type="submit">Verify delivery postcode</button>')+'<p role="status"></p>';
      verification.onsubmit=async event=>{event.preventDefault();const epoch=++generation;const button=verification.querySelector('button');button.disabled=true;try{
        const body=input.kind==='CAPABILITY'?{token:input.value}:{tracking_number:input.value,delivery_postcode:verification.elements.postcode.value};
        const answer=await post('/api/v1/public/tracking/verify-recipient',body);if(epoch!==generation)return;accessToken=answer.tracking_access_token;result=answer;render();
      }catch(error){verification.querySelector('[role=status]').textContent=error.message;}finally{button.disabled=false;}};content.append(verification);
    }
    const token=accessToken||(input.kind==='CAPABILITY'?input.value:null);
    if(token){
      const help=document.createElement('form');help.className='tracking-help';help.innerHTML='<h3>Ask your retailer for help</h3><label>Delivery, return or refund question<textarea name="note" minlength="10" maxlength="1000" required rows="4"></textarea></label><button type="submit">Send request</button><p role="status"></p>';
      help.onsubmit=async event=>{event.preventDefault();const button=help.querySelector('button');button.disabled=true;const note=help.elements.note.value.trim();if(!requestDraft||requestDraft.note!==note)requestDraft={request_id:crypto.randomUUID(),note};try{const answer=await post('/api/v1/public/tracking/help',{token,...requestDraft});help.querySelector('[role=status]').textContent=answer.message||'Your request is already recorded.';}catch(error){help.querySelector('[role=status]').textContent=error.message;}finally{button.disabled=false;}};content.append(help);
    }
    if(verified){
      message.textContent='Verified for up to 30 minutes. Close this page when you finish.';
      const policy=result.buyer_notification_policy||{};
      if(policy.email||policy.whatsapp){
        const preferences=document.createElement('form');preferences.innerHTML='<h3>Your parcel updates</h3><p>Optional updates to the email or phone recorded on this shipment. These are delivery updates, not marketing.</p>'+(policy.email?'<label><input type="checkbox" name="email"> Email me future parcel milestones</label>':'')+(policy.whatsapp?'<label><input type="checkbox" name="whatsapp"> Send future parcel milestones to my WhatsApp</label>':'')+'<button type="submit">Save update preferences</button><p role="status"></p>';
        for(const key of ['email','whatsapp'])if(preferences.elements[key])preferences.elements[key].checked=!!result.recipient_preferences?.[key];
        preferences.onsubmit=async event=>{event.preventDefault();const email=!!preferences.elements.email?.checked,whatsapp=!!preferences.elements.whatsapp?.checked;const button=preferences.querySelector('button');button.disabled=true;try{const answer=await post('/api/v1/public/tracking/recipient-preferences',{token:accessToken,email,whatsapp,email_permission_confirmed:email,whatsapp_permission_confirmed:whatsapp});preferences.querySelector('[role=status]').textContent=answer.message;}catch(error){preferences.querySelector('[role=status]').textContent=error.message;}finally{button.disabled=false;}};content.append(preferences);
      }
    }else message.textContent='Recorded carrier milestones. Private delivery details stay protected until verified.';
    const change=document.createElement('button');change.textContent='Track another parcel';change.onclick=()=>{generation++;input=null;accessToken=null;result=null;requestDraft=null;history.replaceState(null,'','/track');brand(null);lookupForm();message.textContent='Enter your tracking number or secure link.';};content.append(change);
  }
  async function load(){
    if(!input){lookupForm();refresh.hidden=true;message.textContent='Enter your tracking number or secure link.';return;}
    const epoch=++generation;refresh.hidden=false;refresh.disabled=true;message.textContent='Loading recorded carrier updates…';
    try{const answer=accessToken?await post('/api/v1/public/tracking/resolve',{token:accessToken}):input.kind==='CAPABILITY'?await post('/api/v1/public/tracking/resolve',{token:input.value}):await post('/api/v1/public/tracking/status',{text:input.value});if(epoch!==generation)return;if(answer.access==='PUBLIC'&&input.kind==='CAPABILITY'){input={kind:'REFERENCE',value:input.value};history.replaceState(null,'',EasyInvioTracking.path(input));}result=answer;render();}
    catch(error){if(epoch===generation){accessToken=null;content.replaceChildren();lookupForm();message.textContent=error.message;}}
    finally{if(epoch===generation)refresh.disabled=false;}
  }
  try{
    const url=new URL(location.href),values=[url.hash.slice(1),...url.searchParams.getAll('token'),...url.searchParams.getAll('q')].filter(Boolean);
    if(values.length>1)throw Error('Use one tracking reference or secure link.');
    if(values.length){input=EasyInvioTracking.parse(values[0]);history.replaceState(null,'',EasyInvioTracking.path(input));}
  }catch(error){message.textContent=error.message;}
  refresh.onclick=load;load();
  window.addEventListener('pagehide',()=>{generation++;accessToken=null;result=null;content.replaceChildren();});
})();
