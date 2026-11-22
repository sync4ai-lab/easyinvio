"""Guest live estimates with actual adapter parsing and synthetic provider responses."""
from decimal import Decimal
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

from cryptography.fernet import Fernet
import httpx
from pydantic import SecretStr
import pytest

from backend.agents.shipping_intents import classify
from backend.public_route_estimates import PublicRouteEstimates, public_price
from backend.whatsapp_progressive import quote_link, verify_quote
from backend.paf_lookup import PAFLookupUnavailable, IdealPostcodesClient
from urllib.parse import parse_qs, urlsplit


def option(name, code, cost, days=48):
    return {'code':code,'name':name,'carrier':{'code':'evri' if 'evri' in code else 'dpd','name':'Evri' if 'evri' in code else 'DPD'},
        'quotes':[{'price':{'total':{'value':cost,'currency':'GBP'}},'lead_time':days}]}


def fixture_service(client):
    identifier=uuid4();key=Fernet.generate_key()
    settings=NS(provider_environment='TEST',integration_sendcloud_enabled=True,
        credential_keys={'test':SecretStr(key.decode())},
        booking_page_url='https://uat.easyinvio.com',quote_link_secret=SecretStr('synthetic-quote-signing-secret-at-least-32'))
    row={'id':identifier,'aggregator':'REGIONAL','api_base_url':'https://panel.sendcloud.sc/api/v3',
        'credential_key_id':'test','credentials_ciphertext':Fernet(key).encrypt(json.dumps({'platform_id':str(identifier),
        'api_key':json.dumps({'public_key':'synthetic-public','secret_key':'synthetic-secret'})}).encode()),'upstream_account_id':None}
    connection=AsyncMock();connection.__aenter__.return_value=connection;connection.fetch.return_value=[row]
    paf=NS(lookup=AsyncMock(return_value=[NS(post_town='Leeds')]),representative_postcode=AsyncMock(return_value=None))
    service=PublicRouteEstimates(settings,NS(acquire=lambda:connection),client,paf)
    return service,connection,paf


@pytest.mark.asyncio
async def test_sendcloud_live_response_sorted_and_priced_as_starter_two_real_services():
    calls=[]
    async def provider(request):
        calls.append(request)
        assert request.method=='POST' and request.url.path=='/api/v3/shipping-options'
        payload=json.loads(request.content)
        assert payload['from_address']['postal_code']=='LS1 1AA'
        assert payload['to_address']['postal_code']=='B1 1AA'
        assert payload['parcels'][0]['weight']['value']=='2'
        assert payload['calculate_quotes'] is True
        return httpx.Response(200,json={'data':[option('Express','dpd:express','6.00',24),
            option('Standard','evri:standard','3.00',72),option('Home','dpd:home','4.00',48)]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        service,connection,paf=fixture_service(client)
        facts=classify('Quote 2kg from leeds gb to birmingham gb 25x20x10').facts
        reply=await service.estimate(facts)
        assert '*Evri Standard*' in reply and '*DPD Home*' in reply
        assert '*\u00a33.54*' in reply and '*\u00a34.72*' in reply and '(3 days)' in reply
        assert reply.index('Evri')<reply.index('DPD') and 'Express' not in reply
        assert all(term not in reply for term in ('Sample','Illustrative','Examples only','synthetic','ngrok','localhost'))
        assert 'representative postcodes' in reply and len(reply)<1440
        token=parse_qs(urlsplit(reply.splitlines()[-1]).query)['quick_quote'][0]
        handoff=verify_quote(service.settings,token)
        assert 'origin_postal_code' not in handoff and handoff['dimensions_cm']==['25','20','10']
        assert await service.estimate(facts)==reply and len(calls)==1
        assert 'platform_carrier_connections' in connection.fetch.call_args.args[0]
        assert connection.fetch.call_args.args[1]=='TEST'
        paf.lookup.assert_not_awaited();paf.representative_postcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonexistent_supplied_postcode_requests_correction_without_hub_rating():
    calls=[]
    async def provider(request):calls.append(request);return httpx.Response(200,json={'data':[option('Standard','evri:standard','3.00')]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        service,_,paf=fixture_service(client);paf.lookup.return_value=[]
        facts=classify('Quote 2kg from Leeds LS1 9ZZ GB to Birmingham GB 25x20x10').facts
        reply=await service.estimate(facts)
        assert 'could not be found in PAF' in reply and 'representative' not in reply
        assert not calls
        paf.representative_postcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_town_uses_one_paf_town_search_and_caches_result():
    async with httpx.AsyncClient() as client:
        service,_,paf=fixture_service(client);paf.representative_postcode.return_value='YO1 7HP'
        result=await service.location('York',None)
        assert result.postcode=='YO1 7HP' and result.approximate
        assert await service.location('York',None)==result
        paf.representative_postcode.assert_awaited_once_with('York')


@pytest.mark.asyncio
async def test_paf_outage_does_not_label_correct_postcode_as_invalid():
    calls=[]
    async def provider(request):calls.append(request);return httpx.Response(500)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        service,_,paf=fixture_service(client);paf.lookup.side_effect=PAFLookupUnavailable('Address lookup temporarily unavailable')
        facts=classify('Quote 2kg from Leeds LS1 1AA GB to Birmingham GB 25x20x10').facts
        reply=await service.estimate(facts)
        assert 'lookup temporarily unavailable' in reply and 'Exact postcode match not found' not in reply
        assert not calls


@pytest.mark.asyncio
async def test_provider_outage_never_manufactures_a_price_and_is_cached():
    calls=[]
    async def provider(request):calls.append(request);return httpx.Response(503)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        service,_,_=fixture_service(client)
        facts=classify('Quote 2kg from Leeds GB to London GB 25x20x10').facts
        reply=await service.estimate(facts)
        assert '\u00a3' not in reply and 'unavailable' in reply.lower() and 'Sample' not in reply
        assert await service.estimate(facts)==reply and len(calls)==1


@pytest.mark.asyncio
async def test_no_platform_account_never_uses_a_tenant_connection():
    async with httpx.AsyncClient() as client:
        service,db,_=fixture_service(client);db.fetch.return_value=[]
        reply=await service.estimate(classify('Quote 2kg from Leeds GB to London GB 25x20x10').facts)
        assert 'unavailable' in reply and '\u00a3' not in reply
        assert 'carrier_accounts' not in db.fetch.call_args.args[0]


@pytest.mark.asyncio
async def test_valid_postcode_overrides_colloquial_town():
    async with httpx.AsyncClient() as client:
        service,db,paf=fixture_service(client);paf.lookup.return_value=[NS(post_town='LONDON')]
        result=await service.location('Leeds','sw1a1aa')
        assert result.town=='LONDON' and result.postcode=='SW1A 1AA' and not result.approximate
        paf.lookup.assert_awaited_once_with('SW1A 1AA')
        db.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_budget_blocks_more_calls():
    import time
    async with httpx.AsyncClient() as client:
        service,db,_=fixture_service(client);service.calls.extend([time.monotonic()]*12)
        reply=await service.estimate(classify('Quote 2kg from Leeds GB to London GB 25x20x10').facts)
        assert 'busy' in reply;db.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_representative_town_lookup_uses_exact_filter_and_never_returns_street():
    async def provider(request):
        assert request.url.path=='/v1/addresses' and request.url.params['post_town']=='York'
        assert request.url.params['limit']=='1' and 'api_key' not in request.url.params
        assert request.headers['authorization']=='api_key="synthetic"'
        return httpx.Response(200,json={'code':2000,'result':[{'post_town':'York','postcode':'YO1 7HP','line_1':'Private Street'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        assert await IdealPostcodesClient(client,SecretStr('synthetic')).representative_postcode('York')=='YO1 7HP'


def test_price_uses_starter_baseline_including_wholesale_rounding():
    assert public_price(Decimal('3.00'))==Decimal('3.54')
    assert public_price(Decimal('3.001'))==Decimal('3.55')
    for cost in ('NaN','-1','Infinity','0'):
        with pytest.raises(ValueError):public_price(Decimal(cost))


def test_links_require_explicit_config_and_never_use_proxy_hosts():
    settings=NS(booking_page_url='https://uat.easyinvio.com/',quote_link_secret=SecretStr('synthetic-quote-signing-secret-at-least-32'))
    facts=classify('Quote 2kg from Leeds GB to London GB 25x20x10').facts
    assert quote_link(settings,facts).startswith('https://uat.easyinvio.com/login?')
    settings.booking_page_url=''
    with pytest.raises(ValueError):quote_link(settings,facts)


@pytest.mark.asyncio
async def test_reported_compact_postcode_and_birmingham_alias_returns_oldbury_rates_and_prefill():
    calls=[]
    async def provider(request):
        calls.append(request)
        body=json.loads(request.content)
        assert body['from_address']['postal_code']=='LS12 6EJ'
        assert body['from_address']['city']=='LEEDS'
        assert body['to_address']['postal_code']=='B69 3EB'
        assert body['to_address']['city']=='OLDBURY'
        return httpx.Response(200,json={'data':[option('Standard','evri:standard','3.00',72),option('Home','dpd:home','4.00',48)]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        service,_,paf=fixture_service(client)
        async def lookup(postcode):
            return [NS(post_town={'LS12 6EJ':'LEEDS','B69 3EB':'OLDBURY'}[postcode])]
        paf.lookup.side_effect=lookup
        facts=classify('Quote 2kg from ls126ej, leeds gb to B69 3EB birmingham gb 25x20x15').facts
        assert facts.origin_postal_code=='LS12 6EJ' and facts.origin_city=='leeds'
        assert facts.destination_postal_code=='B69 3EB' and facts.destination_city=='birmingham'
        reply=await service.estimate(facts)
        assert '*Evri Standard*' in reply and '*DPD Home*' in reply
        assert 'OLDBURY' in reply and 'Town and postcode do not match' not in reply
        assert len(calls)==1
        handoff=verify_quote(service.settings,parse_qs(urlsplit(reply.splitlines()[-1]).query)['quick_quote'][0])
        assert handoff['origin_postal_code']=='LS12 6EJ' and handoff['origin_city']=='LEEDS'
        assert handoff['destination_postal_code']=='B69 3EB' and handoff['destination_city']=='OLDBURY'
        assert handoff['dimensions_cm']==['25','20','15']
        paf.representative_postcode.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_supplied_postcode_never_uses_a_city_hub():
    from backend.public_route_estimates import EstimateUnavailable
    async with httpx.AsyncClient() as client:
        service,_,paf=fixture_service(client)
        with pytest.raises(EstimateUnavailable,match='malformed'):
            await service.location('Leeds','not-a-postcode')
        paf.lookup.assert_not_awaited()
        paf.representative_postcode.assert_not_awaited()
