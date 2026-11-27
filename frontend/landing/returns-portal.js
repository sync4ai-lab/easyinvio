(() => {
  'use strict';
  const slug=location.pathname.split('/').filter(Boolean).pop();
  const base='/api/v1/public/store-returns/'+encodeURIComponent(slug);
  const message=document.querySelector('#message');let token=null;
  async function call(path,body){
    const response=await fetch(base+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store',credentials:'omit'});
    const value=await response.json();if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'Unable to complete this step. Contact your retailer.');return value;
  }
  async function run(button,action){button.disabled=true;try{await action();}catch(error){message.textContent=error.message;}finally{button.disabled=false;}}
  function show(value){
    document.querySelector('#result').hidden=false;message.textContent='Return status: '+value.status.replaceAll('_',' ');
    for(const [id,key] of [['payment','checkout_url'],['label','label_url'],['qr','qr_url']]){
      const link=document.querySelector('#'+id);link.hidden=!value[key];link.removeAttribute('href');
      if(value[key]){const url=new URL(value[key],location.origin);if(url.protocol==='https:'&&(id!=='payment'||['checkout.stripe.com','buy.stripe.com'].includes(url.hostname)))link.href=url.href;else link.hidden=true;}
    }
  }
  call('').then(store=>{document.querySelector('#store-name').textContent=store.store_name+' returns';document.querySelector('#policy').textContent='Return window: '+store.return_window_days+' days after recorded delivery. '+store.notice;}).catch(error=>{message.textContent=error.message;document.querySelector('#verify').hidden=true;});
  document.querySelector('#verify').addEventListener('submit',event=>{
    event.preventDefault();run(event.target.querySelector('button'),async()=>{
      const fields=new FormData(event.target);const value=await call('/verify',Object.fromEntries(fields));token=value.token;
      document.querySelector('#items').replaceChildren(...value.items.map(item=>{const li=document.createElement('li');li.textContent=item.quantity+' × '+item.description;return li;}));
      document.querySelector('#order').hidden=false;message.textContent=value.notice;document.querySelector('#verify').hidden=true;
    });
  });
  const confirmation=()=>({token,original_packaging_confirmed:document.querySelector('#unchanged').checked,notify_email:document.querySelector('#email').checked,notify_whatsapp:document.querySelector('#whatsapp').checked});
  document.querySelector('#confirm').onclick=event=>run(event.target,async()=>{
    const value=await call('/confirm',confirmation());show(value);document.querySelector('#order').hidden=true;
  });
  document.querySelector('#refresh').onclick=event=>run(event.target,async()=>show(await call('/status',confirmation())));
})();
