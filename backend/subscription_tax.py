"""Explicit subscription tax policy; prices are always net of VAT.

Fixed-rate mode is for approved UK standard-rated billing, not a global VAT rule.
Legacy wallet-only configuration remains readable until operators migrate it.
"""
from decimal import Decimal
from fastapi import HTTPException
from backend.subscription_math import money

def percent(settings,funding='WALLET'):
    configured=getattr(settings,'subscription_tax_percent',None)
    value=configured if configured is not None else (getattr(settings,'subscription_wallet_tax_percent','0') if funding=='WALLET' else '0')
    rate=Decimal(str(value))
    if not rate.is_finite() or not 0<=rate<=100:raise HTTPException(503,'Invalid subscription tax configuration')
    return rate

def breakdown(net,rate):
    net=money(net);tax=money(net*Decimal(str(rate))/100)
    return {'net_amount':str(net),'tax_rate_percent':str(rate),'tax_amount':str(tax),'gross_amount':str(net+tax)}

def require_country(settings,country):
    if getattr(settings,'subscription_tax_percent',None) is None or percent(settings)==0:return
    if getattr(settings,'stripe_livemode',False) and not getattr(settings,'subscription_vat_registered',False):
        raise HTTPException(503,'Confirm VAT registration before enabling live VAT collection')
    if str(country or '').upper()!='GB':
        raise HTTPException(409,'The configured fixed VAT policy supports UK billing only. Configure the customer tax treatment before payment.')

async def stripe_options(settings,client,*,rate_id=None):
    rate=percent(settings,'STRIPE')
    configured=rate_id if rate_id is not None else getattr(settings,'subscription_stripe_tax_rate_id','')
    automatic=bool(getattr(settings,'subscription_automatic_tax_enabled',False))
    if rate>0:
        if automatic or not configured:raise HTTPException(503,'Configure one matching exclusive VAT rate for subscription payments')
        import stripe
        try:
            obj=await client.v1.tax_rates.retrieve_async(configured)
            tax=obj.to_dict_recursive() if hasattr(obj,'to_dict_recursive') else dict(obj)
        except stripe.StripeError:raise HTTPException(503,'Subscription VAT rate validation is temporarily unavailable') from None
        if (tax.get('livemode') is not settings.stripe_livemode or not tax.get('active')
                or tax.get('inclusive') is not False or Decimal(str(tax.get('percentage',-1)))!=rate or tax.get('country')!='GB'):
            raise HTTPException(503,'The payment VAT rate does not match the approved exclusive UK tax policy')
        return {'default_tax_rates':[configured]}
    return {'automatic_tax':{'enabled':automatic}}
