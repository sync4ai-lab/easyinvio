"""Companies House discovery contracts use synthetic company records only."""
import csv
import json

import httpx
import pytest

from backend.tools.sme_lead_scraper import (CompaniesHouseDiscovery, DiscoveryError, district,
    read_evidence, write_report, main)


def company(number='00000001', postcode='TW6 1AA', status='active', sic='47910'):
    return {'company_number':number, 'company_name':'Example Trading Limited', 'company_status':status,
        'registered_office_address':{'postal_code':postcode}, 'sic_codes':[sic]}


def discovery(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler), auth=('synthetic-key',''))
    return client, CompaniesHouseDiscovery(client, sleep=lambda seconds:None, **kwargs)


def test_pagination_local_filters_deduplication_and_unsent_drafts(tmp_path):
    requests = []
    def server(request):
        requests.append(request)
        assert request.url.host == 'api.company-information.service.gov.uk'
        assert request.url.params['sic_codes'] == '47910'
        offset = int(request.url.params['start_index'])
        rows = [company(),company('00000002','TW60 1AA'),company('00000003',status='dissolved'),company('00000004',sic='99999')]
        return httpx.Response(200,json={'hits':'5','items':rows if offset == 0 else [company()]})
    client,tool = discovery(server)
    with client:
        report = tool.discover(['TW6'],['47910'],pages_per_district=2,page_size=4)
    assert len(requests) == 2 and len(report['leads']) == 1
    assert report['messages_sent'] == report['wallet_changes'] == 0
    assert not report['searches'][0]['truncated']
    text = json.dumps(report)
    assert 'synthetic-key' not in text and '14%' not in text and 'Founder_Name' not in text
    assert report['outreach_drafts'][0]['recipient'] is None
    assert 'simulated test credit' in report['outreach_drafts'][0]['body']
    destination = tmp_path/'report.json'
    write_report(destination,report)
    with pytest.raises(FileExistsError):
        write_report(destination,{'replacement':True})
    assert json.loads(destination.read_text(encoding='utf-8')) == report


def test_corridors_require_explicit_company_evidence_not_people_or_names(tmp_path):
    path = tmp_path/'evidence.csv'
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['company_number','trade_country','evidence_url','storefront_type'])
        writer.writerow(['00000001','CN','https://example.test/trading','online retail'])
    evidence = read_evidence(path)
    client,tool = discovery(lambda request:httpx.Response(200,json={'hits':2,'items':[company(),company('00000002')]}))
    with client:
        report = tool.discover(['TW6'],['47910'],evidence=evidence,require_evidence=True)
    assert len(report['leads']) == 1
    assert report['leads'][0]['declared_corridor_evidence'][0]['trade_country'] == 'CN'
    assert 'online retail' in report['outreach_drafts'][0]['subject']
    assert not any('nationality' in key or 'founder' in key for key in report['leads'][0])


def test_rate_limit_retry_budget_and_truncation_are_explicit():
    replies = iter([httpx.Response(429,headers={'Retry-After':'1'}),httpx.Response(200,json={'hits':200,'items':[company()]})])
    client,tool = discovery(lambda request:next(replies))
    with client:
        report = tool.discover(['TW6'],['47910'],pages_per_district=1)
    assert tool.requests == 2 and report['searches'][0]['truncated'] is True
    client,tool = discovery(lambda request:httpx.Response(429,headers={'Retry-After':'600'}))
    with client,pytest.raises(DiscoveryError):
        tool.discover(['TW6'],['47910'])
    client,tool = discovery(lambda request:httpx.Response(503),max_requests=1)
    with client,pytest.raises(DiscoveryError,match='budget'):
        tool.discover(['TW6'],['47910'])


@pytest.mark.parametrize('payload',[{'items':[]}, {'hits':'not-a-count','items':[]}, {'hits':0,'items':'bad'}])
def test_malformed_source_is_rejected(payload):
    client,tool = discovery(lambda request:httpx.Response(200,json=payload))
    with client,pytest.raises(DiscoveryError):
        tool.discover(['TW6'],['47910'])


def test_cli_missing_key_performs_no_requests_and_keeps_credentials_private(tmp_path,monkeypatch,capsys):
    monkeypatch.delenv('COMPANIES_HOUSE_API_KEY',raising=False)
    assert main(['--output',str(tmp_path/'result.json')]) == 1
    assert not (tmp_path/'result.json').exists()
    assert 'credentials' in capsys.readouterr().err
    for invalid in ('TW60 1AA','http://bad','../../','TW6*'):
        with pytest.raises(ValueError):
            district(invalid)
