from decimal import Decimal
from types import SimpleNamespace as NS
import asyncio,pytest
from fastapi import HTTPException
from backend.subscription_tax import breakdown,percent,require_country,stripe_options

def test_exclusive_vat_and_prorated_rounding():
    assert breakdown('75','20')=={'net_amount':'75.00','tax_rate_percent':'20','tax_amount':'15.00','gross_amount':'90.00'}
    assert breakdown('49.94','20')['gross_amount']=='59.93'
    assert breakdown('49.94','20')['tax_amount']=='9.99'
    assert breakdown('0','20')['gross_amount']=='0.00'

def test_both_payment_methods_share_vat_policy():
    s=NS(subscription_tax_percent=Decimal(20),subscription_wallet_tax_percent=0)
    assert percent(s,'STRIPE')==percent(s,'WALLET')==20

def test_fixed_vat_requires_uk_country_and_live_registration():
    s=NS(subscription_tax_percent=20,stripe_livemode=True,subscription_vat_registered=False)
    with pytest.raises(HTTPException):require_country(s,'GB')
    s.subscription_vat_registered=True;require_country(s,'GB')
    for country in ['US','DE',None]:
        with pytest.raises(HTTPException):require_country(s,country)

@pytest.mark.parametrize('change',[{}, {'inclusive':True},{'percentage':21},{'livemode':True},{'country':'US'},{'active':False}])
def test_payment_rate_must_match_approved_exclusive_vat(change):
    async def fetch(*args):return {'active':True,'livemode':False,'inclusive':False,'percentage':20,'country':'GB',**change}
    client=NS(v1=NS(tax_rates=NS(retrieve_async=fetch)))
    settings=NS(subscription_tax_percent=20,subscription_stripe_tax_rate_id='txr_test',stripe_livemode=False)
    if change:
        with pytest.raises(HTTPException):asyncio.run(stripe_options(settings,client))
    else:assert asyncio.run(stripe_options(settings,client))=={'default_tax_rates':['txr_test']}
