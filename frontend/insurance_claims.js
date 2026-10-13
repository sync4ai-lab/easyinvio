// Private XCover support intake and truthful case progress.
document.querySelector('#manifest-refresh').insertAdjacentHTML('beforebegin','<button id="insurance-claims-open" class="secondary">Shipment protection &amp; claims</button>');
let insuranceCaseGeneration=0;
let insuranceCaseId=null;
let insuranceCasePoll=null;
function resetInsuranceCase(){
 insuranceCaseGeneration++;insuranceCaseId=null;
 if(insuranceCasePoll)clearTimeout(insuranceCasePoll);insuranceCasePoll=null;
 document.querySelector('#insurance-claims-form').reset();
 document.querySelector('#insurance-claims-progress').replaceChildren();
 document.querySelector('#insurance-claims-submit').disabled=true;
}
function showInsuranceProgress(result){
 const credited=result.status==='REFUND_APPROVED_AND_CREDITED';
 const reviewing=['UNDER_INSURER_REVIEW','INSURER_PAYMENT_REPORTED','REFUND_APPROVED_AND_CREDITED'].includes(result.status);
 const submitted=Boolean(result.insurer_submission_confirmed);
 document.querySelector('#insurance-claims-progress').innerHTML=`<div class="notice"><b>${credited?'Verified payment credited':submitted?'Insurer claim submitted':result.status==='SUBMISSION_PENDING'?'Claim queued':'Support case received'}</b><p>${escapeHTML(result.notice)}</p><div class="pipeline"><span class="tag green">Case received</span><span class="tag ${reviewing?'green':''}">${credited?'Insurer payment reconciled':reviewing?'Under insurer review':'Insurer review: not confirmed'}</span><span class="tag ${credited?'green':''}">${credited?'Wallet credited':'Wallet credit: not confirmed'}</span></div>${result.claims_portal_url?`<p><a class="primary" href="${escapeHTML(result.claims_portal_url)}" target="_blank" rel="noopener noreferrer">Continue to XCover to file the insurer claim</a></p>`:''}</div>`;
}
async function pollInsuranceCase(generation,session){
 if(generation!==insuranceCaseGeneration||session!==state.session||!insuranceCaseId||!document.querySelector('#insuranceClaimsModal').open)return;
 try{
  const result=await api('/api/v1/shipping/claims/'+encodeURIComponent(insuranceCaseId),{auth:true});
  if(generation!==insuranceCaseGeneration||session!==state.session)return;
  const currentLink=document.querySelector('#insurance-claims-progress a')?.href;
  showInsuranceProgress({...result,claims_portal_url:currentLink});
  if(result.status==='REFUND_APPROVED_AND_CREDITED')return;
 }catch(error){if(generation===insuranceCaseGeneration)document.querySelector('#insurance-claims-notice').textContent='Case status could not be refreshed. Your saved case has not been resubmitted.';}
 insuranceCasePoll=setTimeout(()=>pollInsuranceCase(generation,session),15000);
}
document.querySelector('#insurance-claims-open').addEventListener('click',async()=>{
 resetInsuranceCase();
 const dialog=document.querySelector('#insuranceClaimsModal'),generation=insuranceCaseGeneration,session=state.session;
 dialog.showModal();document.querySelector('#insurance-claims-notice').textContent='Checking confirmed protection for your workspace…';
 document.querySelector('#insurance-claims-shipment').replaceChildren();
 try{
  if(!session)throw Error('Sign in to your workspace to view insured shipments.');
  const result=await api('/api/v1/shipping/insured-shipments',{auth:true});
  if(generation!==insuranceCaseGeneration||session!==state.session||!dialog.open)return;
  document.querySelector('#insurance-claims-notice').textContent=result.notice;
  document.querySelector('#insurance-claims-submit').textContent=result.headless_claims?'Submit claim to insurer':'Save claim support case';
  for(const shipment of result.shipments){const option=document.createElement('option');option.value=shipment.id;option.textContent=(shipment.reference||shipment.id)+' · '+(shipment.tracking_number||'Tracking unavailable');document.querySelector('#insurance-claims-shipment').append(option);}
  document.querySelector('#insurance-claims-submit').disabled=!result.available||!result.shipments.length;
  if(result.available&&!result.shipments.length)document.querySelector('#insurance-claims-notice').textContent='No shipments with confirmed XCover policies are available in this workspace.';
 }catch(error){if(generation===insuranceCaseGeneration)document.querySelector('#insurance-claims-notice').textContent=error.message;}
});
document.querySelector('#insurance-claims-form').addEventListener('submit',event=>{
 event.preventDefault();
 busy(document.querySelector('#insurance-claims-submit'),async()=>{
  const generation=insuranceCaseGeneration,session=state.session;
  if(!session)throw Error('Sign in before submitting a claim support case.');
  const form=document.querySelector('#insurance-claims-form'),photos=Array.from(form.elements.photos.files);
  if(photos.length>4||photos.some(photo=>photo.size>5000000||!['image/jpeg','image/png'].includes(photo.type)))throw Error('Upload at most four JPEG or PNG photographs, each no larger than 5 MB.');
  const caseId=insuranceCaseId||crypto.randomUUID();insuranceCaseId=caseId;
  const data=new FormData(form);data.append('claim_id',caseId);
  if(data.get('incident_at'))data.set('incident_at',new Date(String(data.get('incident_at'))).toISOString());
  if(!photos.length)data.delete('photos');
  try{
   const response=await fetch(API+'/api/v1/shipping/submit-claim',{method:'POST',headers:{Authorization:'Bearer '+session.access_token},body:data});
   const result=await response.json();
   if(generation!==insuranceCaseGeneration||session!==state.session)return;
   if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Claim support intake failed.');
   showInsuranceProgress(result);document.querySelector('#insurance-claims-notice').textContent='Your case is saved privately. The timeline shows confirmed insurer progress. Use the XCover link only when portal filing is requested.';
   setTimeout(()=>{if(generation===insuranceCaseGeneration)document.querySelector('#insurance-claims-submit').disabled=true;},0);
   for(const input of form.elements)input.disabled=true;
   insuranceCasePoll=setTimeout(()=>pollInsuranceCase(generation,session),15000);
  }catch(error){if(generation===insuranceCaseGeneration)document.querySelector('#insurance-claims-notice').textContent=error.message;throw error;}
 });
});
document.querySelector('#insurance-claims-close').addEventListener('click',()=>document.querySelector('#insuranceClaimsModal').close());
document.querySelector('#insuranceClaimsModal').addEventListener('close',()=>{resetInsuranceCase();for(const input of document.querySelector('#insurance-claims-form').elements)input.disabled=false;document.querySelector('#insurance-claims-submit').disabled=true;});
const insuranceClaimsClearSessionBase=clearSession;
clearSession=function(){document.querySelector('#insuranceClaimsModal').close();resetInsuranceCase();return insuranceClaimsClearSessionBase.apply(this,arguments);};
