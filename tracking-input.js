/* Shared public input grammar. Tokens stay in fragments or POST bodies. */
(() => {
  'use strict';
  const reference=/^[A-Za-z0-9_-]{8,100}$/,capability=/^[A-Za-z0-9_-]{40,100}$/;
  const origins=new Set([location.origin,'https://easyinvio.com','https://www.easyinvio.com','https://uat.easyinvio.com']);
  function parse(text){
    let value=String(text).trim();if(value.length>2048)throw Error('Tracking input is too long.');
    value=value.replace(/^track\s+link\s+/i,'');
    if(/^(?:https?:\/\/|\/)/i.test(value)){
      const url=new URL(value,location.origin);
      if(!origins.has(url.origin)||url.username||url.password||!['/track','/tracking.html'].includes(url.pathname))throw Error('Use an EasyInvio tracking link.');
      const values=[url.hash.slice(1),...url.searchParams.getAll('token'),...url.searchParams.getAll('q')].filter(Boolean);
      if(values.length!==1)throw Error('Use one tracking number or tracking link.');if(url.searchParams.has('q')&&reference.test(values[0]))return {kind:'REFERENCE',value:values[0]};return parse(values[0]);
    }
    if(capability.test(value))return {kind:'CAPABILITY',value};
    if(reference.test(value))return {kind:'REFERENCE',value};
    throw Error('Enter a complete tracking number or EasyInvio tracking link.');
  }
  window.EasyInvioTracking=Object.freeze({parse,path:input=>input.kind==='CAPABILITY'?'/track#'+encodeURIComponent(input.value):'/track?q='+encodeURIComponent(input.value)});
})();
