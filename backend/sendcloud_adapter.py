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
