"""Read-only Sendcloud v2 rates for explicitly configured contract methods.

No label creation occurs here. Methods need verified cargo/dimension limits;
neither an unknown tariff nor an unavailable price is turned into a quote.
"""
import asyncio
import json
from decimal import Decimal
from typing import Literal

import httpx
from pydantic import BaseModel,ConfigDict,Field,model_validator
from backend.ai_engine import strict_decimal

ENDPOINT='https://panel.sendcloud.sc/api/v2'


class SendcloudMethod(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    method_id: int=Field(gt=0,strict=True)
    carrier_code: str=Field(min_length=1,max_length=100)
    cargo_type: Literal['LETTER','PARCEL']='PARCEL'
    origin_country: str=Field(pattern=r'^[A-Z]{2}$')
    destination_countries: list[str]=Field(min_length=1,max_length=250)
    min_weight_kg: Decimal=Field(default=Decimal('0'),ge=0)
    max_weight_kg: Decimal=Field(gt=0,le=1000)
    max_length_cm: Decimal=Field(gt=0,le=1000)
    max_width_cm: Decimal=Field(gt=0,le=1000)
    max_height_cm: Decimal=Field(gt=0,le=1000)

    @model_validator(mode='after')
    def bounds(self):
        if self.max_weight_kg<=self.min_weight_kg or any(len(code)!=2 or not code.isalpha() or not code.isupper() for code in self.destination_countries):
            raise ValueError('Invalid configured shipping method limits')
        return self


async def quote_sendcloud(client,account,request,methods):
    if request.cargo_type=='LETTER':
        raise ValueError('Letter service requires a provider address-verification contract')
    if account.base_url!=ENDPOINT:
        raise ValueError('Use the canonical Sendcloud endpoint')
    if len(methods)>100:raise ValueError('Sendcloud method capacity exceeded')
    credentials=json.loads(account.api_key)
    public,secret=credentials['public_key'],credentials['secret_key']
    if not isinstance(public,str) or not isinstance(secret,str) or not public.strip() or not secret.strip():
        raise ValueError('Sendcloud public and secret keys required')
    eligible=[]
    for method in methods:
        if method.cargo_type!=request.cargo_type or method.origin_country!=request.origin.country_code or request.destination.country_code not in method.destination_countries:
            continue
        if not method.min_weight_kg<=request.weights_kg[0]<method.max_weight_kg:
            continue
        if request.dimensions:
            dimensions=request.dimensions[0]
            if any(actual>limit for actual,limit in [(dimensions.length_cm,method.max_length_cm),(dimensions.width_cm,method.max_width_cm),(dimensions.height_cm,method.max_height_cm)]):
                continue
        eligible.append(method)
    semaphore=asyncio.Semaphore(4)
    async def price(method):
        async with semaphore:
            async with client.stream('GET',ENDPOINT+'/shipping-price',
                auth=httpx.BasicAuth(public,secret),timeout=account.timeout_seconds,follow_redirects=False,
                params={'shipping_method_id':method.method_id,'weight':str(request.weights_kg[0]),
                    'weight_unit':'kilogram','from_country':request.origin.country_code,'to_country':request.destination.country_code}) as response:
                if response.status_code!=200:
                    raise ValueError('Sendcloud price unavailable')
                raw=bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw)>1048576:raise ValueError('Sendcloud response too large')
                data=json.loads(raw,parse_float=Decimal)
            if not isinstance(data,list):raise ValueError('Invalid Sendcloud prices')
            result=[]
            for row in data:
                if row.get('to_country')!=request.destination.country_code or row.get('currency')!=request.currency or row.get('price') is None:
                    continue
                amount=strict_decimal(row['price'])
                if amount<=0:raise ValueError('Invalid Sendcloud price')
                result.append({'provider':'REGIONAL','account_id':account.id,
                    'upstream_shipment_id':'sendcloud-rate-only','upstream_rate_id':str(method.method_id),
                    'carrier_code':method.carrier_code.upper(),'service_code':'SENDCLOUD_'+str(method.method_id),
                    'currency':row['currency'],'wholesale_cost':amount,'delivery_days':None})
            return result
    if not methods:raise ValueError('Configure verified Sendcloud method limits')
    rates=await asyncio.gather(*(price(method) for method in eligible))
    return [rate for group in rates for rate in group]

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
    async with client.stream('POST',V3_ENDPOINT+'/shipping-options',json=body,
            auth=sendcloud_credentials(account.api_key),timeout=account.timeout_seconds,
            follow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError('Sendcloud shipping options unavailable')
        raw=bytearray()
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw)>1048576:raise ValueError('Sendcloud response too large')
    data=json.loads(raw,parse_float=Decimal)
    options=data.get('data') if isinstance(data,dict) else None
    if not isinstance(options,list) or len(options)>500:
        raise ValueError('Invalid Sendcloud shipping options response')
    rates=[];seen=set()
    for option in options:
        if not isinstance(option,dict):raise ValueError('Invalid Sendcloud option')
        if option.get('price_error'):continue
        code=option.get('code');carrier=(option.get('carrier') or {}).get('code')
        if not isinstance(code,str) or not code or len(code)>100 or not isinstance(carrier,str) or not carrier:continue
        functionality=option.get('functionalities') or {}
        if functionality.get('returns') or functionality.get('last_mile')=='service_point':continue
        for quote in option.get('quotes') or []:
            # Estimated extra charges need a distinct customer confirmation flow.
            if quote.get('estimated_surcharges'):continue
            total=(quote.get('price') or {}).get('total') or {}
            if total.get('currency')!=request.currency or total.get('value') is None:continue
            cost=strict_decimal(total['value'])
            if cost<=0:continue
            bounds=quote.get('weight')
            if bounds:
                low,high=bounds.get('min'),bounds.get('max')
                if not isinstance(low,dict) or not isinstance(high,dict) or low.get('unit')!='kg' or high.get('unit')!='kg':continue
                if not all(strict_decimal(low['value'])<=weight<strict_decimal(high['value']) for weight in request.weights_kg):continue
            identity=(code,str(cost),request.currency)
            if identity in seen:continue
            seen.add(identity)
            hours=quote.get('lead_time')
            days=(hours+23)//24 if type(hours) is int and hours>0 else None
            rates.append({'provider':'REGIONAL','account_id':account.id,
                'upstream_shipment_id':'sendcloud-v3-rate-only','upstream_rate_id':code,
                'carrier_code':carrier.upper(),'service_code':code,'currency':request.currency,
                'wholesale_cost':cost,'delivery_days':days})
    return rates
