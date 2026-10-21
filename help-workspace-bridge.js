/* Same-origin, documentation-only help. Session tokens never leave this window. */
(() => {
  if (!window.BroadcastChannel) return;
  let channel=new BroadcastChannel('easyinvio.help.v1');
  const instance=crypto.randomUUID();
  const seen=new Set();let running=false,started=[];
  const available=()=>!!state.session&&!!portal.profile&&['OWNER','ADMIN','DISPATCHER','ACCOUNTANT'].includes(portal.profile.workspace_role);
  const receive=async({data})=>{
    if(!data||typeof data.requestId!=='string'||!/^[0-9a-f-]{36}$/i.test(data.requestId)||!Number.isFinite(data.at)||Math.abs(Date.now()-data.at)>30000)return;
    if(data.kind==='DISCOVER'&&available()){
      channel.postMessage({kind:'AVAILABLE',requestId:data.requestId,instance});return;
    }
    if(data.kind!=='ASK'||data.instance!==instance||!available()||seen.has(data.requestId))return;
    if(typeof data.query!=='string'||data.query.trim().length<3||data.query.length>800)return;
    started=started.filter(time=>Date.now()-time<60000);
    if(running||started.length>=10){channel.postMessage({kind:'ERROR',requestId:data.requestId,instance});return;}
    seen.add(data.requestId);if(seen.size>64)seen.delete(seen.values().next().value);
    running=true;started.push(Date.now());
    const session=state.session,tenant=portal.profile.tenant_id,epoch=portal.epoch;
    try{
      // Fixed read-only endpoint. No requested path, role, tenant or action is accepted.
      const result=await api('/api/v1/help/search-agent',{auth:true,method:'POST',body:{query:data.query.trim()}});
      if(session!==state.session||tenant!==portal.profile?.tenant_id||epoch!==portal.epoch)throw Error('Session changed');
      const source=item=>({title:String(item.title||'').slice(0,300),url:String(item.url||'').slice(0,1000),
        ...(typeof item.text==='string'?{text:item.text.slice(0,280)}:{})});
      channel.postMessage({kind:'ANSWER',requestId:data.requestId,instance,result:{
        answer:String(result.answer||'').slice(0,3000),mode:result.mode,fallback_reason:result.fallback_reason,
        sources:(result.sources||[]).slice(0,4).map(source),excerpts:(result.excerpts||[]).slice(0,4).map(source)}});
    }catch{channel.postMessage({kind:'ERROR',requestId:data.requestId,instance});}
    finally{running=false;}
  };
  channel.onmessage=receive;
  window.addEventListener('pagehide',()=>channel.close());
  window.addEventListener('pageshow',event=>{
    if(event.persisted){channel.close();channel=new BroadcastChannel('easyinvio.help.v1');channel.onmessage=receive;}
  });
})();
