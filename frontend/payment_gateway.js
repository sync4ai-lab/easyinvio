// Hosted Stripe Checkout. Only the authenticated server ledger confirms credit.
const stripePayment = { amount: '100.00', requestId: null, topupId: null, session: null, polling: false, paymentWindow: null };
const stripeModal = document.getElementById('stripePaymentModal');
function stripeStorageKey() { return 'easyinvio.checkout.' + (portal.profile?.tenant_id || 'unsigned'); }
function stripeFinancialUser() {
  return !!state.session && !!portal.profile?.tenant_id && ['OWNER','ADMIN','ACCOUNTANT'].includes(portal.profile?.workspace_role);
}
function stripeMessage(text) { $('#stripe-payment-status').textContent = text; }
function selectStripeAmount(amount) {
  if (stripePayment.amount !== amount) stripePayment.requestId = null;
  stripePayment.amount = amount;
  $('#stripe-selected-amount').textContent=money(amount,state.walletCurrency);
  for (const button of document.querySelectorAll('[data-stripe-amount]')) {
    button.setAttribute('aria-pressed', String(button.dataset.stripeAmount === amount));
    button.textContent = '+ Add ' + money(button.dataset.stripeAmount,state.walletCurrency);
  }
}
function openStripePaymentModal() {
  selectStripeAmount(stripePayment.amount);
  $('#stripe-payment-proceed').disabled = !stripeFinancialUser();
  stripeMessage(stripeFinancialUser() ? 'Stripe Test Mode. Wallet credit appears only after the signed payment webhook.' : 'Sign in with a financial workspace role to use Stripe. Sample credit is separate from card payments.');
  stripeModal.showModal();
}
$('#stripe-topup-open').addEventListener('click',openStripePaymentModal);
$('#stripe-payment-close').addEventListener('click',()=>stripeModal.close());
for (const button of document.querySelectorAll('[data-stripe-amount]')) button.addEventListener('click',()=>selectStripeAmount(button.dataset.stripeAmount));

async function verifyStripeCredit(topupId, session) {
  if (stripePayment.polling) return;
  stripePayment.polling = true;
  try {
    for (let attempt=0; attempt<120; attempt++) {
      if (state.session !== session || !stripeFinancialUser()) return;
      const result = await api('/api/v1/billing/topups/' + encodeURIComponent(topupId), {auth:true});
      if (result.status === 'CREDITED') {
        const wallet = await api('/api/v1/wallet',{auth:true});
        if (state.session !== session) return;
        state.wallet=cents(wallet.balance);state.reserved=cents(wallet.reserved_balance);state.walletCurrency=wallet.currency;
        if (!state.history.some(row=>row.topupId===topupId)) state.history.push({label:'Verified Stripe top-up',delta:cents(result.amount),topupId});
        renderWallet();sessionStorage.removeItem(stripeStorageKey());
        stripePayment.requestId=null;stripePayment.topupId=null;
        try { stripePayment.paymentWindow?.close(); } catch {}
        stripeMessage('Payment verified. ' + money(result.amount,result.currency) + ' credited to your wallet.');
        notify('Stripe payment verified. Wallet balance refreshed.');
        setView('wallet');
        return;
      }
      if (['FAILED','CANCELLED','EXPIRED'].includes(result.status)) {
        stripeMessage('Payment was not credited: '+result.status+'. You can start another checkout.');return;
      }
      stripeMessage('Awaiting the signed Stripe webhook. Your wallet has not been credited yet.');
      await new Promise(resolve=>setTimeout(resolve,3000));
    }
    stripeMessage('Payment confirmation is still pending. Refresh the wallet later; do not repeat a completed card payment.');
  } catch(error) { stripeMessage(error.message); }
  finally { stripePayment.polling=false; }
}

$('#stripe-payment-proceed').addEventListener('click',async()=>{
  if (!stripeFinancialUser()) {stripeMessage('Financial workspace login required.');return;}
  // Reserve a window during the user gesture, before the asynchronous API call.
  const paymentWindow=window.open('about:blank','_blank','popup,width=520,height=760');
  if (paymentWindow) {paymentWindow.opener=null;paymentWindow.document.title='EasyInvio.com secure payment';paymentWindow.document.body.textContent='Preparing Stripe Checkout...';}
  const button=$('#stripe-payment-proceed');button.disabled=true;
  $('#stripe-checkout-fallback').hidden=true;
  for (const tier of document.querySelectorAll('[data-stripe-amount]')) tier.disabled=true;
  const session=state.session;
  try {
    stripePayment.requestId ||= crypto.randomUUID();
    const result=await api('/api/v1/billing/create-checkout',{method:'POST',auth:true,body:{
      tenant_id:portal.profile.tenant_id,topup_amount:stripePayment.amount,request_id:stripePayment.requestId}});
    if (state.session !== session) throw Error('Workspace session changed. Sign in again.');
    const url=new URL(result.url);
    if (url.protocol!=='https:' || url.hostname!=='checkout.stripe.com' || url.username || url.password || (url.port && url.port!=='443')) throw Error('Unexpected checkout destination.');
    stripePayment.topupId=result.topup_id;stripePayment.session=session;
    stripePayment.paymentWindow=paymentWindow;
    sessionStorage.setItem(stripeStorageKey(),JSON.stringify({topupId:result.topup_id,requestId:stripePayment.requestId,amount:stripePayment.amount}));
    $('#stripe-checkout-fallback').href=url.href;$('#stripe-checkout-fallback').hidden=false;
    if (paymentWindow) paymentWindow.location.replace(url.href);
    stripeMessage(paymentWindow ? 'Checkout opened in the payment window. This workspace will verify your credit automatically.' : 'The browser blocked the popup. Use Open Secure Checkout below.');
    void verifyStripeCredit(result.topup_id,session);
  } catch(error) { if (paymentWindow) paymentWindow.close();stripeMessage(error.message); }
  finally {button.disabled=!stripeFinancialUser();for (const tier of document.querySelectorAll('[data-stripe-amount]')) tier.disabled=false;}
});

// A success URL alone cannot fund a wallet. Resume authenticated reconciliation.
async function resumeStripePayment() {
  if (!stripeFinancialUser()) return;
  const params=new URLSearchParams(location.search);
  let stored=null;
  try {stored=JSON.parse(sessionStorage.getItem(stripeStorageKey()) || 'null');} catch {}
  const id=params.get('topup_id') || stored?.topupId;
  if (params.has('payment')) {
    if (params.get('payment')==='cancel') notify('Checkout cancelled. No wallet credit has been confirmed.');
    else if (params.get('payment')==='success') notify('Checkout returned. Verifying the signed payment receipt...');
    params.delete('payment');params.delete('topup_id');
    history.replaceState(null,'',location.pathname+(params.size?'?'+params:'')+location.hash);
    setView('wallet');
  }
  if (id && /^[0-9a-f-]{36}$/i.test(id)) {
    stripePayment.topupId=id;
    if (stored) {stripePayment.requestId=stored.requestId;stripePayment.amount=stored.amount;}
    void verifyStripeCredit(id,state.session);
  }
}
window.addEventListener('focus',()=>void resumeStripePayment());
const paymentRefreshPortal=refreshPortal;
refreshPortal=async function(...args) {const result=await paymentRefreshPortal(...args);await resumeStripePayment();return result;};
void resumeStripePayment();
