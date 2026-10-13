// Measured delivery quality and explicit protection readiness.
let deliveryQualityGeneration=0;
let deliveryQualityKey='';
let deliveryQualityResult=null;
async function refreshDeliveryQuality(){
 const session=state.session,quote=state.quoteRequest;
 if(!session||!quote||state.lastRateResult?.simulated)return;
 const key=portal.profile?.tenant_id+':'+quote.origin.country_code+':'+quote.destination.country_code;
 if(key===deliveryQualityKey&&deliveryQualityResult){showDeliveryQuality(deliveryQualityResult);return;}
 const generation=++deliveryQualityGeneration;
 try{
  const result=await api('/api/v1/analytics/tracking-readiness?origin_country='+encodeURIComponent(quote.origin.country_code)+'&destination_country='+encodeURIComponent(quote.destination.country_code),{auth:true});
  if(!Array.isArray(result.reasons)||typeof result.method!=='string')throw Error('Unexpected tracking readiness response');
  if(session!==state.session||generation!==deliveryQualityGeneration)return;
  deliveryQualityKey=key;deliveryQualityResult=result;showDeliveryQuality(result);
 }catch(error){if(session===state.session&&generation===deliveryQualityGeneration){$('#delivery-quality-readiness').hidden=false;$('#delivery-quality-readiness').textContent='Tracking readiness could not be loaded. Delivery scores remain unavailable until verified history can be read.';}}
}
function showDeliveryQuality(result){
 $('#delivery-quality-readiness').hidden=false;
 $('#delivery-quality-readiness').innerHTML='<b>About delivery estimates and measured history</b><p>'+escapeHTML(result.reasons?.join(' ')||'Recorded route history is available; sample counts are shown on each service.')+'</p><details><summary>How these figures are calculated</summary><p>'+escapeHTML(result.method)+'</p></details>';
}
const measuredRenderRatesBase=renderRates;
renderRates=function(result){measuredRenderRatesBase(result);refreshDeliveryQuality();};
$('#quote-form').addEventListener('input',()=>{deliveryQualityGeneration++;deliveryQualityKey='';deliveryQualityResult=null;$('#delivery-quality-readiness').hidden=true;});
const measuredClearSessionBase=clearSession;
clearSession=function(){deliveryQualityGeneration++;deliveryQualityKey='';deliveryQualityResult=null;$('#delivery-quality-readiness').hidden=true;return measuredClearSessionBase.apply(this,arguments);};

const protectionBookLiveBase=bookLive;
bookLive=async function(index){
 customerCheckout.insuranceRequested=false;
 const generation=customerCheckout.generation+1,session=state.session,rate=state.quotes[index];
 await protectionBookLiveBase(index);
 if(generation!==customerCheckout.generation||session!==state.session||!session||!rate||!$('#review-dialog').open)return;
 let protection;
 try{protection=await api('/api/v1/shipping/protection-quote?offer_id='+encodeURIComponent(rate.offer_id),{auth:true});}
 catch(error){protection={available:false,notice:'Protection availability could not be verified. No protection fee is charged.'};}
 if(generation!==customerCheckout.generation||session!==state.session||!$('#review-dialog').open)return;
 const panel=$('#checkout-price');
 if(panel)panel.insertAdjacentHTML('afterend',`<section class="notice" id="checkout-protection"><label class="check"><input type="checkbox" ${protection.selection_available?'':'disabled'}> Optional shipment protection${protection.selection_available?'':': unavailable'}</label><p>${escapeHTML(protection.notice)}</p>${protection.premium_estimate!=null?`<p>Proposed customer premium: ${escapeHTML(money(protection.premium_estimate,'GBP'))}, before any applicable protection tax. This is an estimate, not purchased cover.</p>`:''}<a href="mailto:support@easyinvio.com?subject=Shipment%20protection%20availability">Contact EasyInvio support</a></section>`);
 $('#checkout-protection input')?.addEventListener('change',event=>{customerCheckout.insuranceRequested=event.target.checked;});
};
