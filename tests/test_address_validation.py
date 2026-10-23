"""Real server validation boundaries, without provider calls or purchases."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError
from main import Address
from backend.address_validation import verify_shipping_addresses
from backend.paf_lookup import PAFPremise, PAFLookupUnavailable


def address(**changes):
    return Address.model_validate(dict(name='Sender', line1='10 Downing Street', city='LONDON',
        postal_code='SW1A 2AA', country_code='GB') | changes)


def settings(environment='LIVE', key='synthetic'):
    return SimpleNamespace(provider_environment=environment, ideal_postcodes_api_key=SecretStr(key))


@pytest.mark.parametrize('postcode', ['SW1A', '12345', 'CB2 1T0', 'Q1 1AA', 'SW1A 2AA; evil'])
def test_uk_bad_syntax_is_rejected_on_all_address_inputs(postcode):
    with pytest.raises(ValidationError): address(postal_code=postcode)


def test_normalization_does_not_claim_verification_or_reject_international_formats():
    assert address(postal_code='sw1a2aa').postal_code == 'SW1A 2AA'
    assert address(country_code='FR', postal_code='75001').postal_code == '75001'


@pytest.mark.asyncio
async def test_live_uk_without_key_blocks_before_any_network_call():
    async with httpx.AsyncClient() as client:
        with pytest.raises(HTTPException) as error:
            await verify_shipping_addresses(client, settings(key=''), [('Pickup', address())])
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_test_fixtures_without_key_and_international_are_explicitly_separate():
    async with httpx.AsyncClient() as client:
        await verify_shipping_addresses(client, settings('TEST', ''), [('Pickup', address())])
        await verify_shipping_addresses(client, settings(key=''), [('Delivery', address(country_code='FR', postal_code='75001'))])


@pytest.mark.asyncio
async def test_complete_premise_match_rejects_wrong_flat_city_or_street():
    premise = PAFPremise(udprn='123', line1='10 Downing Street', line2='Flat 1', post_town='LONDON', postcode='SW1A 2AA')
    lookup = AsyncMock(return_value=[premise])
    with patch('backend.address_validation.IdealPostcodesClient.lookup', lookup):
        async with httpx.AsyncClient() as client:
            await verify_shipping_addresses(client, settings(), [('Pickup', address(line2='Flat 1', city='London'))])
            for changes in [{'line2':'Flat 2'}, {'city':'Paris','line2':'Flat 1'}, {'line1':'11 Downing Street','line2':'Flat 1'}]:
                with pytest.raises(HTTPException) as error:
                    await verify_shipping_addresses(client, settings(), [('Delivery', address(**changes))])
                assert error.value.status_code == 422 and 'Delivery' in error.value.detail


@pytest.mark.asyncio
async def test_service_outage_and_missing_postcode_never_pass_verification():
    async with httpx.AsyncClient() as client:
        for result in [[], PAFLookupUnavailable('secret upstream body')]:
            lookup = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
            with patch('backend.address_validation.IdealPostcodesClient.lookup', lookup):
                with pytest.raises(HTTPException) as error:
                    await verify_shipping_addresses(client, settings(), [('Pickup', address())])
                assert error.value.status_code in {422,503}
                assert 'secret upstream' not in error.value.detail


@pytest.mark.asyncio
async def test_lookup_api_protects_access_and_returns_only_structured_premises(monkeypatch):
    import main
    premise = PAFPremise(udprn='123', line1='10 Downing Street', post_town='LONDON', postcode='SW1A 2AA')
    lookup = AsyncMock(return_value=[premise])
    monkeypatch.setattr(main.app.state, 'paf', SimpleNamespace(lookup=lookup), raising=False)
    async def owner(): return SimpleNamespace(role='OWNER')
    main.app.dependency_overrides[main.authenticate] = owner
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://testserver') as client:
            result = await client.post('/api/v1/addresses/uk/lookup', json={'postcode':'sw1a2aa'})
            assert result.status_code == 200
            assert result.json()['source'] == 'ROYAL_MAIL_PAF'
            assert result.json()['addresses'][0]['address']['city'] == 'LONDON'
            lookup.assert_awaited_once_with('SW1A 2AA')
            assert (await client.post('/api/v1/addresses/uk/lookup', json={'postcode':'SW1A'})).status_code == 422
            lookup.side_effect = PAFLookupUnavailable('private upstream diagnostic')
            result = await client.post('/api/v1/addresses/uk/lookup', json={'postcode':'SW1A 2AA'})
            assert result.status_code == 503 and 'private upstream' not in result.text
    finally:
        main.app.dependency_overrides.pop(main.authenticate, None)
