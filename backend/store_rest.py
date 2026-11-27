"""Native read/fulfillment adapters; no order-import or financial logic here."""
from __future__ import annotations
from decimal import Decimal
from typing import Any
from urllib.parse import quote
import httpx
from fastapi import HTTPException
from backend.store_transport import store_json

class RestStoreAdapter:
    def __init__(self, client: httpx.AsyncClient, config: Any):
        self.client,self.config=client,config
        self.platform=config.platform
        self.headers: dict[str,str]={}
        self.auth=None
        token=config.access_token.get_secret_value() if config.access_token else ''
        if self.platform=='WOOCOMMERCE':
            if not (config.store_url and config.client_id and config.client_secret):
                raise HTTPException(409,'WooCommerce REST requires HTTPS origin, consumer key and consumer secret')
            self.root=config.store_url+'/wp-json/wc/v3'
            self.auth=httpx.BasicAuth(config.client_id,config.client_secret.get_secret_value())
        elif self.platform=='EBAY':
            self.root='https://api.ebay.com/sell/fulfillment/v1'
            self.headers={'Authorization':'Bearer '+token}
        elif self.platform=='BIGCOMMERCE':
            self.root='https://api.bigcommerce.com/stores/'+quote(config.external_store_id,safe='')+'/v2'
            self.headers={'X-Auth-Token':token}
        elif self.platform=='WIX':
            self.root='https://www.wixapis.com/ecom/v1'
            self.headers={'Authorization':token,'wix-site-id':config.external_store_id}
        elif self.platform=='MAGENTO':
            self.root=config.store_url+'/rest/V1'
            self.headers={'Authorization':'Bearer '+token}
        else: raise HTTPException(409,'No native REST adapter is available for this platform')

    async def call(self, method: str, path: str, **kwargs: Any) -> Any:
        return await store_json(self.client,method,self.root+path,headers=self.headers,auth=self.auth,**kwargs)

    async def test(self) -> dict[str,Any]:
        if self.platform=='WOOCOMMERCE': await self.call('GET','/system_status')
        elif self.platform=='EBAY': await self.call('GET','/order',params={'limit':1})
        elif self.platform=='BIGCOMMERCE': await self.call('GET','/store')
        elif self.platform=='WIX': await self.call('POST','/orders/query',json={'query':{'paging':{'limit':1}}})
        else: await self.call('GET','/store/storeConfigs')
        return {'verified':True,'store_name':self.config.store_url or self.config.external_store_id or self.platform,
                'scope':'Read-only API access verified; this does not verify write scopes or webhook delivery'}

    async def orders(self, page: int=1) -> list[dict[str,Any]]:
        if self.platform=='WOOCOMMERCE':
            return await self.call('GET','/orders',params={'status':'processing','per_page':50,'page':page})
        if self.platform=='EBAY':
            result=await self.call('GET','/order',params={'limit':50,'offset':(page-1)*50,'filter':'orderfulfillmentstatus:{NOT_STARTED}'})
            return result.get('orders',[])
        if self.platform=='BIGCOMMERCE':
            values=await self.call('GET','/orders',params={'limit':50,'page':page,'status_id':11})
            return [await self.order(str(v['id'])) for v in values]
        if self.platform=='WIX':
            result=await self.call('POST','/orders/query',json={'query':{'filter':{'status':{'$eq':'APPROVED'},'fulfillmentStatus':{'$eq':'NOT_FULFILLED'}},'paging':{'limit':50,'offset':(page-1)*50}}})
            return result.get('orders',[])
        result=await self.call('GET','/orders',params={'searchCriteria[pageSize]':50,'searchCriteria[currentPage]':page,
            'searchCriteria[filterGroups][0][filters][0][field]':'status',
            'searchCriteria[filterGroups][0][filters][0][value]':'processing'})
        return result.get('items',[])

    async def order(self, identifier: str) -> dict[str,Any]:
        key=quote(identifier,safe='')
        if self.platform=='EBAY': return await self.call('GET','/order/'+key)
        if self.platform=='WIX': return (await self.call('GET','/orders/'+key))['order']
        result=await self.call('GET','/orders/'+key)
        if self.platform=='BIGCOMMERCE':
            result['products']=await self.call('GET','/orders/'+key+'/products')
            result['shipping_addresses']=await self.call('GET','/orders/'+key+'/shipping_addresses')
        return result

    def normalize(self, order: dict[str,Any]) -> dict[str,Any]:
        """Reject partial allocations; never invent weights, price, or addresses."""
        if self.platform=='WOOCOMMERCE':
            from backend.ecommerce_connectors import normalize_woocommerce
            result=normalize_woocommerce(order,self.config)
            for item,line in zip(result['line_items'],order['line_items'],strict=True):
                if 'total' in line: item['unit_value']=str(Decimal(str(line['total']))/line['quantity'])
            email=order.get('billing',{}).get('email')
            if email: result['shipping_address']['email']=email
            return result
        if self.platform=='EBAY':
            if order['orderFulfillmentStatus']!='NOT_STARTED' or len(order['fulfillmentStartInstructions'])!=1:
                raise ValueError('Partial or split fulfillment requires review')
            contact=order['fulfillmentStartInstructions'][0]['shippingStep']['shipTo']
            addr=contact['contactAddress']; name=contact['fullName']; city=addr['city']; country=addr['countryCode']; postal=addr['postalCode']
            line1=addr['addressLine1']; line2=addr.get('addressLine2','')
            lines=[(v['sku'],v['title'],v['quantity'],Decimal(str(v['lineItemCost']['value']))/v['quantity']) for v in order['lineItems']]
            identity=order['orderId']; currency=order['pricingSummary']['total']['currency']; reference=identity
        elif self.platform=='BIGCOMMERCE':
            if len(order['shipping_addresses'])!=1 or order.get('items_shipped',0): raise ValueError('Split/partial order requires review')
            addr=order['shipping_addresses'][0]; name=(addr['first_name']+' '+addr['last_name']).strip()
            city=addr['city']; country=addr['country_iso2']; postal=addr['zip']; line1=addr['street_1']; line2=addr.get('street_2','')
            lines=[(v['sku'],v['name'],v['quantity'],v['price_ex_tax']) for v in order['products']]
            identity=order['id']; reference=str(identity); currency=order['currency_code']
        elif self.platform=='WIX':
            if order['status']!='APPROVED' or order['fulfillmentStatus']!='NOT_FULFILLED': raise ValueError('Unfulfilled approved order required')
            recipient=order['shippingInfo']['logistics']['shippingDestination']; addr=recipient['address']; contact=recipient['contactDetails']
            name=(contact['firstName']+' '+contact['lastName']).strip(); city=addr['city']; country=addr['country']; postal=addr['postalCode']
            line1=addr['addressLine1']; line2=addr.get('addressLine2','')
            lines=[(v['physicalProperties']['sku'],v['productName']['original'],v['quantity'],v['price']['amount']) for v in order['lineItems']]
            identity=order['id']; reference=str(order['number']); currency=order['currency']
        else:
            if order['status']!='processing': raise ValueError('Processing order required')
            addresses=order['extension_attributes']['shipping_assignments']
            if len(addresses)!=1: raise ValueError('Split order requires review')
            addr=addresses[0]['shipping']['address']; name=(addr['firstname']+' '+addr['lastname']).strip()
            city=addr['city']; country=addr['country_id']; postal=addr['postcode']; line1=addr['street'][0]; line2=' '.join(addr['street'][1:])
            if any(v.get('qty_shipped',0) or v.get('qty_canceled',0) or v.get('qty_refunded',0) for v in order['items']): raise ValueError('Partial order requires review')
            if any(v.get('parent_item_id') or v.get('product_type') not in {'simple','virtual','downloadable'} for v in order['items']): raise ValueError('Composite products require explicit allocation')
            lines=[(v['sku'],v['name'],v['qty_ordered'],v['price']) for v in order['items'] if v['product_type']=='simple']
            identity=order['entity_id']; reference=order['increment_id']; currency=order['order_currency_code']
        items=[]
        for sku,title,qty,price in lines:
            if sku not in self.config.sku_unit_grams: raise ValueError('Verified SKU weights required')
            if isinstance(qty,bool) or Decimal(str(qty))!=int(qty): raise ValueError('Whole item quantities required')
            items.append({'title':title,'quantity':int(qty),'grams':str(self.config.sku_unit_grams[sku]),'unit_value':str(price)})
        return {'id':str(identity),'name':reference,'currency':currency,'line_items':items,
            'shipping_address':{'name':name,'address1':line1,'address2':line2,'city':city,'zip':postal,'country_code':country}}

    async def deliver(self, body: dict[str,Any], *, verify_only: bool=False) -> dict[str,Any]:
        key=quote(body['store_order_id'],safe=''); number=body['tracking_number']; carrier=body['carrier_name']
        if len(body.get('tracking_numbers') or [number])!=1: raise HTTPException(409,'Multi-piece native allocation requires review')
        order=await self.order(body['store_order_id'])
        if self.platform=='WOOCOMMERCE':
            marker={'number':number,'carrier':carrier,'event_id':body.get('event_id')}
            current=next((v['value'] for v in order.get('meta_data',[]) if v['key']=='easyinvio_tracking'),None)
            note='EasyInvio tracking: '+carrier+' '+number
            notes=await self.call('GET','/orders/'+key+'/notes',params={'per_page':100})
            if current and current.get('number')==number and any(v['note']==note for v in notes): return {'replayed':True,'simulated':False}
            if verify_only: raise HTTPException(409,'Tracking/note not confirmed; keep reconciliation hold')
            if order['status'] not in {'processing','on-hold'}: raise HTTPException(409,'WooCommerce order requires fulfillment review')
            await self.call('PUT','/orders/'+key,json={'status':'completed','meta_data':[{'key':'easyinvio_tracking','value':marker}]})
            if not any(v['note']==note for v in notes): await self.call('POST','/orders/'+key+'/notes',json={'note':note,'customer_note':False})
        elif self.platform=='EBAY':
            existing=await self.call('GET','/order/'+key+'/shipping_fulfillment')
            if any(v.get('trackingNumber')==number for v in existing.get('fulfillments',[])): return {'replayed':True,'simulated':False}
            if verify_only: raise HTTPException(409,'Remote tracking not confirmed')
            self.normalize(order)
            await self.call('POST','/order/'+key+'/shipping_fulfillment',json={'trackingNumber':number,'shippingCarrierCode':carrier,
                'lineItems':[{'lineItemId':v['lineItemId'],'quantity':int(v['quantity'])} for v in order['lineItems']]})
        elif self.platform=='BIGCOMMERCE':
            existing=await self.call('GET','/orders/'+key+'/shipments')
            if any(v.get('tracking_number')==number for v in existing): return {'replayed':True,'simulated':False}
            if verify_only: raise HTTPException(409,'Remote tracking not confirmed')
            self.normalize(order)
            await self.call('POST','/orders/'+key+'/shipments',json={'tracking_number':number,'shipping_provider':'custom',
                'order_address_id':order['shipping_addresses'][0]['id'],
                'items':[{'order_product_id':v['id'],'quantity':int(v['quantity'])} for v in order['products']]})
        elif self.platform=='WIX':
            existing=await self.call('GET','/fulfillments/orders/'+key)
            if any(v.get('trackingInfo',{}).get('trackingNumber')==number for v in existing.get('fulfillments',[])): return {'replayed':True,'simulated':False}
            if verify_only: raise HTTPException(409,'Remote tracking not confirmed')
            self.normalize(order)
            await self.call('POST','/fulfillments/orders/'+key+'/create-fulfillment',json={'fulfillment':{
                'lineItems':[{'id':v['id'],'quantity':int(v['quantity'])} for v in order['lineItems']],
                'trackingInfo':{'trackingNumber':number,'shippingProvider':carrier}}})
        else:
            existing=await self.call('GET','/shipments',params={'searchCriteria[filterGroups][0][filters][0][field]':'order_id',
                'searchCriteria[filterGroups][0][filters][0][value]':key})
            if any(t.get('track_number')==number for v in existing.get('items',[]) for t in v.get('tracks',[])): return {'replayed':True,'simulated':False}
            if verify_only: raise HTTPException(409,'Remote tracking not confirmed')
            self.normalize(order)
            await self.call('POST','/order/'+key+'/ship',json={'items':[{'order_item_id':v['item_id'],'qty':int(v['qty_ordered'])} for v in order['items'] if v['product_type']=='simple'],
                'notify':False,'tracks':[{'track_number':number,'title':carrier,'carrier_code':'custom'}]})
        return {'simulated':False,'fulfillment_state':'SHIPPED','replayed':False}
