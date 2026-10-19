"""Company-level UK logistics prospect discovery and unsent outreach drafts.

Uses the official Companies House API, not officer records or inferred ethnicity.
Run: python -m backend.tools.sme_lead_scraper --help
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

API_ORIGIN = 'https://api.company-information.service.gov.uk'
TARGET_FILTERS = (
    {'postcode_district': 'TW6', 'hub': 'Heathrow'},
    {'postcode_district': 'M90', 'hub': 'Manchester Airport'},
)
SIC_FILTERS = {
    '47910': 'Retail sale via mail order houses or via Internet',
    '46900': 'Non-specialised wholesale trade',
    '52103': 'Operation of warehousing and storage facilities for land transport activities',
}
TARGET_CORRIDORS = {'CN', 'IN'}


class DiscoveryError(Exception):
    """A bounded operational error whose message contains no credentials."""


def district(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r'[A-Z]{1,2}[0-9][A-Z0-9]?', value):
        raise ValueError('Use a UK outward postcode district such as TW6 or M90')
    return value


def company_number(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{8}', value):
        raise ValueError('Company numbers must have eight letters/digits; retain leading zeros')
    return value


def public_url(value: str) -> str:
    parsed = urlsplit(value)
    if (len(value) > 1000 or parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError('Evidence must be a public HTTPS page without credentials, query or fragment')
    return value


def read_evidence(path: Path | None) -> dict:
    """Optional human-reviewed company declarations, never nationality guesses.

    CSV columns: company_number,trade_country,evidence_url,storefront_type.
    trade_country describes a business corridor, not a founder or customer.
    """
    if path is None:
        return {}
    if path.stat().st_size > 5_000_000:
        raise ValueError('Evidence CSV is limited to 5 MB')
    result = {}
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, strict=True)
        if not reader.fieldnames or set(reader.fieldnames) != {'company_number', 'trade_country', 'evidence_url', 'storefront_type'}:
            raise ValueError('Evidence CSV requires company_number,trade_country,evidence_url,storefront_type')
        for index, row in enumerate(reader, 2):
            if index > 10001:
                raise ValueError('Evidence CSV is limited to 10000 records')
            if set(row) != set(reader.fieldnames) or not all(isinstance(value,str) for value in row.values()):
                raise ValueError(f'Evidence row {index}: incomplete or extra fields')
            number = company_number(row['company_number'])
            country = row['trade_country'].strip().upper()
            if country not in TARGET_CORRIDORS:
                raise ValueError(f'Evidence row {index}: trade_country must be CN or IN')
            storefront = row['storefront_type'].strip()
            if len(storefront) > 80 or any(ord(c) < 32 for c in storefront):
                raise ValueError(f'Evidence row {index}: invalid storefront description')
            evidence = {'trade_country': country, 'evidence_url': public_url(row['evidence_url'].strip()),
                'storefront_type': storefront or 'online', 'verification': 'SUPPLIED_FOR_MANUAL_REVIEW'}
            entries = result.setdefault(number, [])
            if evidence not in entries:
                entries.append(evidence)
    return result


def outreach_draft(lead: dict) -> dict:
    evidence = lead['declared_corridor_evidence']
    storefront = evidence[0]['storefront_type'] if evidence else 'online'
    name = lead['company_name']
    return {
        'company_number': lead['company_number'], 'status': 'DRAFT_REQUIRES_REVIEW', 'recipient': None,
        'subject': f'Compare Evri / Royal Mail fulfilment costs for your {storefront} store',
        'body': (
            f'Hi {name} team,\n\n'
            'Are you looking for a simpler way to compare shipping costs for your UK import/export or e-commerce operations?\n\n'
            'EasyInvio.com brings connected carrier quotes, shipment preparation and label workflows into one browser workspace. '
            'Where your connected services support them, you can compare Evri, Royal Mail and other carriers for your actual parcels and routes. '
            'Available services, prices and delivery estimates depend on the carrier account and shipment details.\n\n'
            'Would you like a guided sandbox demonstration of the batch label workflow using an illustrative £50 test balance? '
            'Any demo balance is simulated test credit, subject to demo setup; it cannot buy live labels or be withdrawn. '
            'We can review real account requirements and pricing separately before you dispatch.\n\n'
            'Would a short walkthrough be useful for your dispatch team?\n\n'
            'EasyInvio Operations\noperations@easyinvio.com\n'
            'If this is not relevant, let us know and we will not follow up.'),
    }


class CompaniesHouseDiscovery:
    def __init__(self, client: httpx.Client, *, max_requests: int = 20, interval: float = 1.0,
                 sleep=time.sleep, monotonic=time.monotonic):
        if not 1 <= max_requests <= 100 or interval < 1:
            raise ValueError('Use 1 to 100 requests and at least one second between requests')
        self.client, self.max_requests, self.interval = client, max_requests, interval
        self.sleep, self.monotonic, self.last_request = sleep, monotonic, None
        self.requests = 0

    def page(self, params: dict) -> dict:
        for attempt in range(3):
            if self.requests >= self.max_requests:
                raise DiscoveryError('Request budget exhausted; reduce filters/pages or increase the explicit budget')
            if self.last_request is not None:
                self.sleep(max(0, self.interval - (self.monotonic() - self.last_request)))
            self.last_request = self.monotonic()
            self.requests += 1
            try:
                response = self.client.get(API_ORIGIN + '/advanced-search/companies', params=params)
            except httpx.HTTPError:
                if attempt == 2:
                    raise DiscoveryError('Companies House connection unavailable; no output written') from None
                self.sleep(2 ** attempt)
                continue
            if response.status_code == 404:
                return {'items': [], 'hits': 0}
            if response.status_code in (429, 500, 502, 503, 504):
                delay = response.headers.get('Retry-After', '')
                seconds = int(delay) if delay.isdigit() else 2 ** (attempt + 1)
                if seconds > 30 or attempt == 2:
                    raise DiscoveryError('Companies House rate limit or temporary outage; retry later')
                self.sleep(seconds)
                continue
            if response.status_code != 200:
                raise DiscoveryError(f'Companies House rejected the request (HTTP {response.status_code})')
            if len(response.content) > 5_000_000:
                raise DiscoveryError('Companies House response exceeds the supported size')
            try:
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get('items', []), list):
                    raise ValueError()
                data['hits'] = int(data['hits'])
                if data['hits'] < 0:
                    raise ValueError()
                return data
            except (ValueError, KeyError, TypeError):
                raise DiscoveryError('Unexpected Companies House response format') from None
        raise DiscoveryError('Companies House retries exhausted')

    def discover(self, districts: list[str], sic_codes: list[str], *, pages_per_district: int = 2,
                 page_size: int = 100, evidence: dict | None = None, require_evidence: bool = False) -> dict:
        if not 1 <= pages_per_district <= 20 or not 1 <= page_size <= 100:
            raise ValueError('Use 1 to 20 pages per district and 1 to 100 rows per page')
        districts = list(dict.fromkeys(district(value) for value in districts))
        if not districts or len(districts) > 20 or not sic_codes or not all(re.fullmatch(r'[0-9]{5}', code) for code in sic_codes):
            raise ValueError('Provide up to 20 postcode districts and five-digit SIC codes')
        evidence, leads, searches = evidence or {}, {}, []
        for outward in districts:
            scan = {'postcode_district': outward, 'hits': 0, 'rows_scanned': 0, 'truncated': False}
            for page_index in range(pages_per_district):
                data = self.page({'location': outward, 'sic_codes': ','.join(sic_codes), 'company_status': 'active',
                    'size': page_size, 'start_index': page_index * page_size})
                rows = data.get('items', [])
                scan['hits'] = data['hits']
                scan['rows_scanned'] += len(rows)
                for row in rows:
                    if not isinstance(row, dict):
                        raise DiscoveryError('Unexpected company record')
                    address = row.get('registered_office_address') or {}
                    codes = row.get('sic_codes') or []
                    if not isinstance(address,dict) or not isinstance(codes,list) or not all(isinstance(code,str) for code in codes):
                        raise DiscoveryError('Malformed company address or SIC codes')
                    postcode = str(address.get('postal_code', '')).strip().upper()
                    # Local validation avoids broad location matches (TW6 is not TW60).
                    if (row.get('company_status') != 'active' or not re.fullmatch(re.escape(outward) + r'\s*[0-9][A-Z]{2}', postcode)
                            or not set(row.get('sic_codes') or []).intersection(sic_codes)):
                        continue
                    try:
                        number = company_number(str(row.get('company_number','')))
                    except ValueError:
                        raise DiscoveryError('Invalid company number in source') from None
                    name = row.get('company_name','')
                    if not isinstance(name,str):
                        raise DiscoveryError('Invalid company name in source')
                    name = name.strip()
                    if not name or len(name) > 300 or any(ord(c) < 32 for c in name):
                        raise DiscoveryError('Invalid company name in source')
                    corridor = evidence.get(number, [])
                    if require_evidence and not corridor:
                        continue
                    leads[number] = {'company_number': number, 'company_name': name, 'company_status': 'active',
                        'registered_office_postcode_district': outward,
                        'sic_codes': sorted(set(row['sic_codes']).intersection(sic_codes)),
                        'source_url': 'https://find-and-update.company-information.service.gov.uk/company/' + number,
                        'declared_corridor_evidence': corridor, 'qualification': 'REQUIRES_BUSINESS_REVIEW',
                        'limitations': 'Registered office is not proof of warehouse operations, SME size, shipping volume, storefront or trade corridor.'}
                if not rows or scan['rows_scanned'] >= scan['hits']:
                    break
            scan['truncated'] = scan['rows_scanned'] < scan['hits']
            searches.append(scan)
        ordered = sorted(leads.values(), key=lambda lead: lead['company_number'])
        return {'generated_at': datetime.now(timezone.utc).isoformat(), 'source': 'COMPANIES_HOUSE_PUBLIC_DATA_API',
            'requests': self.requests, 'searches': searches, 'filters': {'postcode_districts': districts, 'sic_codes': sic_codes,
                'require_supplied_corridor_evidence': require_evidence}, 'leads': ordered,
            'outreach_drafts': [outreach_draft(lead) for lead in ordered], 'messages_sent': 0, 'wallet_changes': 0}


def write_report(path: Path, report: dict, *, overwrite=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        if overwrite:
            os.replace(temporary, path)
        else:
            # Same-filesystem hard linking publishes a complete file atomically
            # and fails if the destination already exists.
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postcode', action='append', help='UK outward district; repeat for multiple hubs (default TW6 and M90)')
    parser.add_argument('--sic', action='append', help='Five-digit SIC code; repeat to combine sectors')
    parser.add_argument('--corridor-evidence', type=Path)
    parser.add_argument('--require-corridor-evidence', action='store_true')
    parser.add_argument('--pages-per-district', type=int, default=2)
    parser.add_argument('--page-size', type=int, default=100)
    parser.add_argument('--max-requests', type=int, default=20)
    parser.add_argument('--env-file', type=Path, help='Optional local env file containing COMPANIES_HOUSE_API_KEY')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args(argv)
    try:
        key = os.environ.get('COMPANIES_HOUSE_API_KEY', '')
        if not key and args.env_file:
            from dotenv import dotenv_values
            key = dotenv_values(args.env_file).get('COMPANIES_HOUSE_API_KEY') or ''
        if not key:
            raise ValueError('Set COMPANIES_HOUSE_API_KEY in the environment or the specified env file')
        if args.output.exists() and not args.overwrite:
            raise ValueError('Output already exists; choose another file or explicitly pass --overwrite')
        if args.require_corridor_evidence and not args.corridor_evidence:
            raise ValueError('--require-corridor-evidence requires --corridor-evidence')
        evidence = read_evidence(args.corridor_evidence)
        with httpx.Client(auth=(key, ''), timeout=10, follow_redirects=False, trust_env=False) as client:
            report = CompaniesHouseDiscovery(client, max_requests=args.max_requests).discover(
                args.postcode or [item['postcode_district'] for item in TARGET_FILTERS], args.sic or list(SIC_FILTERS),
                pages_per_district=args.pages_per_district, page_size=args.page_size,
                evidence=evidence, require_evidence=args.require_corridor_evidence)
        write_report(args.output, report, overwrite=args.overwrite)
    except (ValueError, OSError, DiscoveryError, csv.Error):
        print('Lead discovery failed. Check API credentials, input formats, request budget and output permissions. No messages or wallet changes were made.', file=sys.stderr)
        return 1
    print(f"Saved {len(report['leads'])} company leads and unsent drafts to {args.output}. Messages sent: 0.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
