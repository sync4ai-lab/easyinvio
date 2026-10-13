// Card-funded label carts. Card details are entered exclusively at Stripe.
const labelCardPayment={cartId:null,polling:false,requestKey:null,requestId:null,generation:0};
function labelCardStorageKey(){return 'easyinvio.label-cart.'+(portal.profile?.tenant_id||'unsigned');}
async function refreshBookingWallet(){if(!state.session||!['OWNER','ADMIN','ACCOUNTANT'].includes(portal.profile?.workspace_role))return;const session=state.session;const wallet=await api('/api/v1/wallet',{auth:true});if(state.session!==session)return;state.wallet=cents(wallet.balance);state.reserved=cents(wallet.reserved_balance);state.walletCurrency=wallet.currency;try{const activity=await api('/api/v1/billing/wallet-activity',{auth:true});if(state.session!==session)return;state.history=(activity.entries||[]).slice().reverse().map(row=>({label:(({TOPUP:'Verified card credit',RESERVE:'Credit reserved',CAPTURE:'Label purchased',RELEASE:'Reservation released',SHIPMENT_REFUND:'Carrier refund',REFUND_DEBIT:'Card refund'})[row.entry_type]||row.entry_type.replaceAll('_',' '))+' '+(row.reference||'')+' '+new Date(row.created_at).toLocaleString(),delta:cents(row.balance_delta)}));}catch{if(state.session!==session)return;notify('Balance updated; transaction history is temporarily unavailable.',true);}renderWallet();}
async function startLabelCardPayment(offers){
 if(!state.session||!['OWNER','ADMIN'].includes(portal.profile?.workspace_role))throw Error('Workspace owner or administrator permission required for card checkout.');
 const paymentWindow=window.open('about:blank','_blank','popup,width=520,height=760');if(paymentWindow){paymentWindow.opener=null;paymentWindow.document.body.textContent='Preparing secure card checkout...';}
 try{
  const key=JSON.stringify(offers);if(labelCardPayment.requestKey!==key){labelCardPayment.requestKey=key;labelCardPayment.requestId=crypto.randomUUID();}
  const session=state.session;const result=await api('/api/v1/billing/carts',{method:'POST',auth:true,body:{offers,request_id:labelCardPayment.requestId,return_origin:location.origin}});if(state.session!==session)throw Error('Session changed.');
  const url=new URL(result.url);if(url.protocol!=='https:'||url.hostname!=='checkout.stripe.com'||url.username||url.password)throw Error('Unexpected payment destination.');
  labelCardPayment.cartId=result.cart_id;localStorage.setItem(labelCardStorageKey(),JSON.stringify({cartId:result.cart_id}));
  $('#bulk-checkout-body').innerHTML=`<h3>Pay selected labels by card</h3><p class="subtle">${escapeHTML(result.mode||'TEST')} payment mode</p><p>Selected total: ${escapeHTML(money(result.amount,result.currency))}</p><p class="notice">${escapeHTML(result.notice)}</p><a class="primary" href="${escapeHTML(url.href)}" target="_blank" rel="noopener noreferrer">Open secure Stripe payment</a><p id="label-card-status" role="status">Awaiting your card payment.</p>`;$('#bulk-checkout-dialog').showModal();
  if(paymentWindow)paymentWindow.location.replace(url.href);void verifyLabelCardPayment(result.cart_id,session);
 }catch(error){paymentWindow?.close();throw error;}
}
async function verifyLabelCardPayment(id,session){
 if(labelCardPayment.polling)return;labelCardPayment.polling=true;const generation=labelCardPayment.generation;
 try{for(let attempt=0;attempt<120;attempt++){
  if(state.session!==session||generation!==labelCardPayment.generation)return;
  const result=await api('/api/v1/billing/carts/'+id+'/complete',{method:'POST',auth:true});if(state.session!==session||generation!==labelCardPayment.generation)return;
  if(['COMPLETED','REVIEW_REQUIRED'].includes(result.status)){
   localStorage.removeItem(labelCardStorageKey());labelCardPayment.cartId=null;labelCardPayment.requestId=null;labelCardPayment.requestKey=null;
   $('#review-dialog').close();renderBulkOutcome(result.outcome);$('#bulk-checkout-dialog').showModal();await refreshBookingWallet();await refreshManifestRecords();return;
  }
  if($('#label-card-status'))$('#label-card-status').textContent=result.status==='BOOKING'?'Payment verified. Carrier label preparation is in progress; do not pay again.':'Checking your payment with Stripe...';
  await new Promise(resolve=>setTimeout(resolve,3000));
 }notify('Card confirmation is still pending. Refresh the manifest; do not repeat a completed payment.',true);
 }catch(error){notify(error.message,true);if($('#label-card-status'))$('#label-card-status').textContent=error.message;}
 finally{if(generation===labelCardPayment.generation)labelCardPayment.polling=false;}
}
async function resumeLabelCardPayment(){if(!state.session||!['OWNER','ADMIN'].includes(portal.profile?.workspace_role))return;let saved;try{saved=JSON.parse(localStorage.getItem(labelCardStorageKey())||'null');}catch{}const params=new URLSearchParams(location.search),id=params.get('cart_id')||saved?.cartId;if(!id||!/^[0-9a-f-]{36}$/i.test(id))return;params.delete('cart_id');params.delete('topup_id');params.delete('payment');history.replaceState(null,'',location.pathname+(params.size?'?'+params:'')+location.hash);labelCardPayment.cartId=id;void verifyLabelCardPayment(id,state.session);}
const cardPrepareBase=prepareCustomerCheckout;prepareCustomerCheckout=async function(...args){const result=await cardPrepareBase(...args);const prepared=customerCheckout.prepared;if(!prepared||!$('#checkout-purchase'))return result;$('#checkout-purchase').textContent='Pay from wallet & create label';if(['OWNER','ADMIN'].includes(portal.profile?.workspace_role)){const b=document.createElement('button');b.id='checkout-pay-card';b.className='secondary full';b.textContent=prepared.protection?'Protected checkout currently uses your prepaid wallet':'Pay by card with Stripe';b.disabled=Boolean(prepared.protection);b.addEventListener('click',()=>busy(b,()=>startLabelCardPayment([{shipment_id:prepared.shipment_id,offer_id:prepared.offer.offer_id,expected_price:prepared.offer.client_price_ex_tax,currency:prepared.offer.currency}])));$('#checkout-purchase').after(b);}return result;};
const cardBulkRenderBase=renderBulkCheckout;renderBulkCheckout=function(){cardBulkRenderBase();$('#bulk-checkout-buy').textContent='Pay from wallet & create selected labels';if(['OWNER','ADMIN'].includes(portal.profile?.workspace_role)){const b=document.createElement('button');b.id='bulk-pay-card';b.className='secondary full';b.textContent='Pay selected labels by card with Stripe';b.addEventListener('click',()=>busy(b,()=>{const offers=bulkOffers().map(({row,rate})=>({shipment_id:row.shipment_id,offer_id:rate.offer_id,expected_price:rate.client_price_ex_tax,currency:rate.currency}));if(!offers.length)throw Error('Select an available service first.');return startLabelCardPayment(offers);}));$('#bulk-checkout-buy').after(b);}};
const cardBookingBase=showCustomerBooking;showCustomerBooking=function(...args){cardBookingBase(...args);void refreshBookingWallet().catch(()=>notify('Booking recorded. Refresh Wallet to see its latest balance.',true));};
const cardBulkOutcomeBase=renderBulkOutcome;renderBulkOutcome=function(...args){cardBulkOutcomeBase(...args);void refreshBookingWallet().catch(()=>notify('Booking result recorded. Refresh Wallet for the latest balance.',true));};
window.addEventListener('focus',()=>void resumeLabelCardPayment());window.addEventListener('easyinvio-session-ready',()=>void resumeLabelCardPayment());
const cardClearBase=clearSession;clearSession=function(){labelCardPayment.cartId=null;labelCardPayment.polling=false;labelCardPayment.generation++;labelCardPayment.requestId=null;labelCardPayment.requestKey=null;return cardClearBase.apply(this,arguments);};
void resumeLabelCardPayment();

$('#wallet-refresh').addEventListener('click',event=>{if(!state.session)return;event.stopImmediatePropagation();busy($('#wallet-refresh'),refreshBookingWallet);},true);
const paymentSetViewBase=setView;setView=function(view){const result=paymentSetViewBase.apply(this,arguments);if(view==='wallet'&&state.session)void refreshBookingWallet().catch(error=>notify(error.message,true));return result;};

const cardCheckoutErrorBase=checkoutError;checkoutError=function(...args){cardCheckoutErrorBase(...args);void refreshBookingWallet().catch(()=>{});};
