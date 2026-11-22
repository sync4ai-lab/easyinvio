"""Read-only Sendcloud v3 shipping-option quotes; no label creation."""
import json
from decimal import Decimal

import httpx
from backend.ai_engine import strict_decimal

V3_ENDPOINT = 'https://panel.sendcloud.sc/api/v3'


def sendcloud_credentials(value):
    """Decode only the private server-encrypted credential envelope."""
    credentials = json.loads(value)
    if not isinstance(credentials,dict):raise ValueError('Invalid Sendcloud credential envelope')
    public, secret = credentials.get('public_key'), credentials.get('secret_key')
    if not isinstance(public,str) or not isinstance(secret,str) or not public.strip() or not secret.strip():
        raise ValueError('Sendcloud public and secret keys required')
    return httpx.BasicAuth(public.strip(), secret.strip())


async def quote_sendcloud_v3(client, account, request):
    """Discover available parcel options and normalize actual v3 shipment quotes.

    This endpoint quotes only. It does not create orders, shipments or labels.
    Missing prices, uncertain cargo eligibility and estimated surcharges never
    become an invented all-inclusive offer.
    """
    if account.base_url != V3_ENDPOINT:
        raise ValueError('Use the canonical Sendcloud v3 endpoint')
    if request.cargo_type != 'PARCEL':
        raise ValueError('Sendcloud parcel adapter does not certify letters or industrial freight')
    if (request.customs_document or {}).get('category')=='OTHER':
        raise ValueError('Sendcloud does not support the OTHER customs export reason')
    def address(value):
        result = {'country_code':value.country_code,'postal_code':value.postal_code,
                  'city':value.city,'address_line_1':value.line1}
        state = getattr(value,'state',None)
        if state:result['state_province_code']=state
        return result
    parcels=[]
    for weight, dimensions in zip(request.weights_kg,request.dimensions,strict=True):
        parcels.append({'weight':{'value':str(weight),'unit':'kg'},'dimensions':{
            'length':str(dimensions.length_cm),'width':str(dimensions.width_cm),
            'height':str(dimensions.height_cm),'unit':'cm'}})
    body={'from_address':address(request.origin),'to_address':address(request.destination),
          'parcels':parcels,'calculate_quotes':True}
    if len(parcels)>1:body['functionalities']={'multicollo':True}
    if getattr(request,'is_return',False):body.setdefault('functionalities',{})['returns']=True
    async with client.stream('POST',V3_ENDPOINT+'/shipping-options',json=body,
            auth=sendcloud_credentials(account.api_key),timeout=account.timeout_seconds,
            follow_redirects=False) as response:
        if response.status_code != 200:
            from backend.rate_diagnostics import RateHTTPRejected
            raise RateHTTPRejected(response.status_code)
        raw=bytearray()
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw)>1048576:raise ValueError('Sendcloud response too large')
    data=json.loads(raw,parse_float=Decimal)
    options=data.get('data') if isinstance(data,dict) else None
    if not isinstance(options,list) or len(options)>500:
        raise ValueError('Invalid Sendcloud shipping options response')
    rates=[];seen=set();available_currencies=set()
    for option in options:
        if not isinstance(option,dict):raise ValueError('Invalid Sendcloud option')
        if option.get('price_error'):continue
        code=option.get('code');carrier=(option.get('carrier') or {}).get('code')
        if not isinstance(code,str) or not code or len(code)>100 or not isinstance(carrier,str) or not carrier:continue
        functionality=option.get('functionalities') or {}
        if bool(functionality.get('returns')) != bool(getattr(request,'is_return',False)) or functionality.get('last_mile')=='service_point':continue
        if len(parcels)>1 and functionality.get('multicollo') is not True:continue
        for quote in option.get('quotes') or []:
            # Estimated extra charges need a distinct customer confirmation flow.
            if quote.get('estimated_surcharges'):continue
            total=(quote.get('price') or {}).get('total') or {}
            if total.get('value') is None:continue
            cost=strict_decimal(total['value'])
            if cost<=0:continue
            bounds=quote.get('weight')
            if bounds:
                low,high=bounds.get('min'),bounds.get('max')
                if not isinstance(low,dict) or not isinstance(high,dict) or low.get('unit')!='kg' or high.get('unit')!='kg':continue
                if not all(strict_decimal(low['value'])<=weight<strict_decimal(high['value']) for weight in request.weights_kg):continue
            if total.get('currency') != request.currency:
                available_currencies.add(total.get('currency'))
                continue
            identity=(code,str(cost),request.currency)
            if identity in seen:continue
            seen.add(identity)
            hours=quote.get('lead_time')
            days=(hours+23)//24 if type(hours) is int and hours>0 else None
            rates.append({'provider':'REGIONAL','account_id':account.id,
                'upstream_shipment_id':'sendcloud-v3-rate-only','upstream_rate_id':code,
                'carrier_code':carrier.upper(),'service_code':code,'currency':request.currency,
                'wholesale_cost':cost,'delivery_days':days,
                'execution_details':{'display_service_name':str(option.get('name') or code)[:100],
                    'display_carrier_name':str((option.get('carrier') or {}).get('name') or carrier)[:100],
                    'contract_id':(option.get('contract') or {}).get('id'),
                    'return_paperless_supported':bool(getattr(request,'is_return',False) and functionality.get('labelless') is True)}})
    if not rates and available_currencies:
        from backend.rate_diagnostics import RateCurrencyUnavailable
        raise RateCurrencyUnavailable(available_currencies)
    return rates
