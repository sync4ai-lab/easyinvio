// Embedded in index.html: authenticated live dispatch updates and statement audits.
const dispatchLive = {socket:null, session:null, retry:null, refresh:null};
function connectDispatchUpdates() {
 if (!state.session || !portal.profile?.tenant_id) return;
 if (dispatchLive.session === state.session && dispatchLive.socket && dispatchLive.socket.readyState < 2) return;
 clearTimeout(dispatchLive.retry);
 dispatchLive.socket?.close();
 dispatchLive.session = state.session;
 const session = state.session;
 const origin = new URL(API || location.origin, location.origin);
 origin.protocol = origin.protocol === 'https:' ? 'wss:' : 'ws:';
 origin.pathname = '/api/v1/dispatch-workspace/live'; origin.search = ''; origin.hash = '';
 const socket = new WebSocket(origin.href); dispatchLive.socket = socket;
 socket.onopen = () => { if(session===state.session)socket.send(JSON.stringify({access_token:session.access_token}));else socket.close(); };
 socket.onmessage = event => {
  if(session!==state.session)return;
  let message;try{message=JSON.parse(event.data);}catch{return;}
  if(!['shipment_changed','refresh_required'].includes(message.type))return;
  clearTimeout(dispatchLive.refresh);
  dispatchLive.refresh=setTimeout(async()=>{
   if(session!==state.session)return;
   try {
    if(enterprise.currentView==='workspace')await loadDispatchWorkspace();
    if(enterprise.currentView==='manifest'){$('#manifest-refresh').click();}
    if(enterprise.currentView==='wallet')await refreshBookingWallet();
   }catch{notify('Dispatch update received. Use Refresh to retry loading your records.',true);}
  },400);
 };
 socket.onclose=()=>{if(dispatchLive.socket!==socket)return;dispatchLive.socket=null;if(session===state.session)dispatchLive.retry=setTimeout(connectDispatchUpdates,5000);};
 socket.onerror=()=>socket.close();
}
window.addEventListener('easyinvio-session-ready',connectDispatchUpdates);
const liveNavigationBase=refreshEnterpriseNavigation;
refreshEnterpriseNavigation=function(...args){const result=liveNavigationBase(...args);if(!state.session){clearTimeout(dispatchLive.retry);clearTimeout(dispatchLive.refresh);dispatchLive.session=null;dispatchLive.socket?.close();dispatchLive.socket=null;}else connectDispatchUpdates();return result;};
window.addEventListener('easyinvio-session-ready',()=>{
 const parameters=new URLSearchParams(location.search);
 if(parameters.get('view')==='manifest'&&/^[0-9a-f-]{36}$/i.test(parameters.get('shipment_id')||'')){
  setView('manifest');
  history.replaceState(null,'',location.pathname+location.hash);
 }
});
