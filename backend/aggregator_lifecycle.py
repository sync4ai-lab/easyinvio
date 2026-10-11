"""Native partner lifecycle contracts behind EasyInvio's private account boundary.

Mutating HTTP requests are never retried automatically. A timeout is an unknown
outcome, not a rejected purchase. Return snapshots must contain a newly quoted
return service; a forward price is never reused as a return authorization.
"""
from __future__ import annotations

import copy
import asyncio
import json
import hashlib
from abc import ABC, abstractmethod
from decimal import Decimal
from uuid import UUID, uuid5, NAMESPACE_URL
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from backend.automation_freight_engine import PurchaseRejected, PurchaseUncertain


def identifier(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise PurchaseRejected('INVALID_REMOTE_ID')
    value = str(value)
    if not value or len(value) > 200:
        raise PurchaseRejected('INVALID_REMOTE_ID')
    return quote(value, safe='')


def secure_link(value):
    if not isinstance(value, str):
        raise PurchaseUncertain('DOCUMENT_NOT_READY')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise PurchaseUncertain('INVALID_DOCUMENT_LINK')
    return value


def declaration(data):
    document = data.get('customs_document') or data.get('customs') or {}
    if not document.get('required'):
        return None
    if not document.get('ready_for_provider') or not document.get('signer') or not document.get('items'):
        raise PurchaseRejected('CUSTOMS_REVIEW_REQUIRED')
    for item in document['items']:
        code = item.get('hs_code', '')
        if not isinstance(code, str) or not code.isdigit() or len(code) not in {6, 8, 10}:
            raise PurchaseRejected('CUSTOMS_CLASSIFICATION_REQUIRED')
        for key in ('unit_value', 'unit_weight_kg'):
            amount = Decimal(str(item[key]))
            if not amount.is_finite() or amount <= 0:
                raise PurchaseRejected('INVALID_CUSTOMS_VALUE')
        if type(item['quantity']) is not int or item['quantity'] < 1:
            raise PurchaseRejected('INVALID_CUSTOMS_QUANTITY')
    return document


def return_snapshot(original):
    """Only a fresh, server-authorized return quote may purchase a return label."""
    if not original.get('return_quote_authorized') or not original.get('return_rate_id'):
        raise PurchaseRejected('FRESH_RETURN_QUOTE_REQUIRED')
    result = copy.deepcopy(original)
    result['upstream_rate_id'] = result.pop('return_rate_id')
    result['origin'], result['destination'] = original['destination'], original['origin']
    result['is_return'] = True
    return result


class BaseAggregatorAdapter(ABC):
    endpoint: str

    def __init__(self, client: httpx.AsyncClient, credentials: str, *, environment: str):
        if environment not in {'TEST', 'LIVE'}:
            raise ValueError('Explicit TEST or LIVE environment required')
        self.client, self.credentials, self.environment = client, credentials, environment
        self.last_remote_id = None
        self.pending_void_id = None

    def authentication(self):
        return {}

    async def request(self, method, path, body=None):
        # Bound reads before parsing, never follow redirects with credentials.
        try:
            async with self.client.stream(method, self.endpoint + path, json=body,
                                          timeout=30, follow_redirects=False,
                                          **self.authentication()) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2_000_000:
                        raise PurchaseUncertain('RESPONSE_LIMIT')
                if response.status_code in {400, 401, 403, 404, 422}:
                    raise PurchaseRejected('REQUEST_REJECTED')
                if not 200 <= response.status_code < 300:
                    raise PurchaseUncertain('REMOTE_OUTCOME_UNKNOWN')
                if response.status_code == 204:
                    return {}
                try:
                    result = json.loads(raw, parse_float=Decimal)
                except ValueError:
                    raise PurchaseUncertain('INVALID_REMOTE_RESPONSE') from None
                if not isinstance(result, dict):
                    raise PurchaseUncertain('INVALID_REMOTE_RESPONSE')
                return result
        except httpx.HTTPError:
            raise PurchaseUncertain('REMOTE_OUTCOME_UNKNOWN') from None

    @abstractmethod
    async def purchase_label(self, rate_snapshot: dict) -> dict: ...

    @abstractmethod
    async def quote(self, request, account, rate_model) -> list: ...

    @abstractmethod
    async def inject_customs(self, parcel_data: dict) -> dict: ...

    @abstractmethod
    async def void_label(self, upstream_shipment_id: str) -> bool: ...

    @abstractmethod
    async def generate_return_label(self, original_shipment_snapshot: dict) -> dict: ...

    @abstractmethod
    async def retrieve_label(self, upstream_shipment_id: str, rate_snapshot: dict) -> dict: ...

    @abstractmethod
    async def void_confirmed(self, upstream_shipment_id: str) -> bool: ...


class EasyPostAdapter(BaseAggregatorAdapter):
    endpoint = 'https://api.easypost.com/v2'

    def authentication(self):
        return {'auth': httpx.BasicAuth(self.credentials, '')}

    async def quote(self, request, account, rate_model):
        import sys
        core = sys.modules[rate_model.__module__]
        return await core.EasyPostStrategy(self.client, account).rates(request)

    def normalize(self, body, snapshot):
        if body.get('mode') != ('test' if self.environment == 'TEST' else 'production'):
            raise PurchaseUncertain('REMOTE_MODE_MISMATCH')
        if (body.get('id') != snapshot['upstream_shipment_id'] or
                body.get('selected_rate', {}).get('id') != snapshot['upstream_rate_id']):
            raise PurchaseUncertain('REMOTE_RATE_MISMATCH')
        label = body.get('postage_label') or {}
        tracking = body.get('tracking_code')
        if not isinstance(tracking, str) or not tracking.strip():
            raise PurchaseUncertain('TRACKING_NOT_READY')
        return {'upstream_id': body['id'], 'tracking_number': tracking,
                'tracking_url': (body.get('tracker') or {}).get('public_url'),
                'label_url': secure_link(label.get('label_pdf_url') or label.get('label_url')),
                'carrier_forms': [{'document_type': f.get('form_type', 'CUSTOMS_FORM'),
                                   'url': secure_link(f['form_url'])} for f in body.get('forms', [])]}

    async def purchase_label(self, rate_snapshot):
        shipment_id = identifier(rate_snapshot['upstream_shipment_id'])
        # Confirm the key's actual remote mode before any charge-producing call.
        remote = await self.request('GET', '/shipments/' + shipment_id)
        if remote.get('mode') != ('test' if self.environment == 'TEST' else 'production'):
            raise PurchaseRejected('REMOTE_MODE_MISMATCH')
        if remote.get('postage_label'):
            return self.normalize(remote, rate_snapshot)
        if not any(r.get('id') == rate_snapshot['upstream_rate_id'] for r in remote.get('rates', [])):
            raise PurchaseRejected('RATE_NO_LONGER_AVAILABLE')
        body = await self.request('POST', '/shipments/' + shipment_id + '/buy',
                                  {'rate': {'id': rate_snapshot['upstream_rate_id']}})
        self.last_remote_id = body.get('id')
        return self.normalize(body, rate_snapshot)

    async def inject_customs(self, parcel_data):
        result = copy.deepcopy(parcel_data)
        document = declaration(result)
        if document:
            if document['currency'] != 'USD':
                raise PurchaseRejected('CUSTOMS_USD_VALUES_REQUIRED')
            result['customs_info'] = {'customs_certify': True, 'customs_signer': document['signer'],
                'contents_type': 'merchandise', 'restriction_type': 'none',
                'customs_items': [{'description': i['description'], 'quantity': i['quantity'],
                    'value': str(Decimal(str(i['unit_value'])) * i['quantity']),
                    'weight': str(Decimal(str(i['unit_weight_kg'])) * i['quantity'] * Decimal('35.27396195')),
                    'hs_tariff_number': i['hs_code'], 'origin_country': i['origin_country']}
                    for i in document['items']]}
        return result

    async def retrieve_label(self, upstream_shipment_id, rate_snapshot):
        return self.normalize(await self.request('GET', '/shipments/' + identifier(upstream_shipment_id)), rate_snapshot)

    async def void_label(self, upstream_shipment_id):
        body = await self.request('POST', '/shipments/' + identifier(upstream_shipment_id) + '/refund', {})
        return body.get('refund_status') == 'refunded'

    async def void_confirmed(self, upstream_shipment_id):
        body = await self.request('GET', '/shipments/' + identifier(upstream_shipment_id))
        return body.get('refund_status') == 'refunded'

    async def generate_return_label(self, original_shipment_snapshot):
        snapshot = return_snapshot(original_shipment_snapshot)
        # Return shipment and rate IDs must already have been quoted natively.
        snapshot['upstream_shipment_id'] = snapshot['return_shipment_id']
        return await self.purchase_label(snapshot)


class ShippoAdapter(BaseAggregatorAdapter):
    endpoint = 'https://api.goshippo.com'

    def authentication(self):
        if self.environment == 'TEST' and not self.credentials.startswith('shippo_test_'):
            raise PurchaseRejected('TEST_TOKEN_REQUIRED')
        if self.environment == 'LIVE' and not self.credentials.startswith('shippo_live_'):
            raise PurchaseRejected('LIVE_TOKEN_REQUIRED')
        return {'headers': {'Authorization': 'ShippoToken ' + self.credentials,
                            'SHIPPO-API-VERSION': '2018-02-08'}}

    async def quote(self, request, account, rate_model):
        return await ShippoRateStrategy(self.client, account, rate_model, self.environment).rates(request)

    def normalize(self, body, snapshot):
        if body.get('status') != 'SUCCESS' or body.get('test') is not (self.environment == 'TEST'):
            raise PurchaseUncertain('TRANSACTION_NOT_CONFIRMED')
        rate = body.get('rate')
        rate_id = rate.get('object_id') if isinstance(rate, dict) else rate
        if rate_id != snapshot['upstream_rate_id']:
            raise PurchaseUncertain('REMOTE_RATE_MISMATCH')
        if not body.get('tracking_number'):
            raise PurchaseUncertain('TRACKING_NOT_READY')
        forms = []
        if body.get('commercial_invoice_url'):
            forms.append({'document_type': 'COMMERCIAL_INVOICE', 'url': secure_link(body['commercial_invoice_url'])})
        return {'upstream_id': body['object_id'], 'tracking_number': body['tracking_number'],
                'tracking_url': body.get('tracking_url_provider'), 'label_url': secure_link(body.get('label_url')),
                'carrier_forms': forms}

    async def purchase_label(self, rate_snapshot):
        body = await self.request('POST', '/transactions/',
            {'rate': rate_snapshot['upstream_rate_id'], 'label_file_type': 'PDF', 'async': False})
        self.last_remote_id = body.get('object_id')
        if body.get('status') == 'ERROR':
            raise PurchaseRejected('LABEL_REJECTED')
        return self.normalize(body, rate_snapshot)

    async def retrieve_label(self, upstream_shipment_id, rate_snapshot):
        return self.normalize(await self.request('GET', '/transactions/' + identifier(upstream_shipment_id) + '/'), rate_snapshot)

    async def inject_customs(self, parcel_data):
        result = copy.deepcopy(parcel_data)
        document = declaration(result)
        if document:
            items = []
            for i in document['items']:
                item = await self.request('POST', '/customs/items/', {'description': i['description'],
                    'quantity': i['quantity'], 'net_weight': str(Decimal(str(i['unit_weight_kg'])) * i['quantity']),
                    'mass_unit': 'kg', 'value_amount': str(Decimal(str(i['unit_value'])) * i['quantity']),
                    'value_currency': document['currency'], 'origin_country': i['origin_country'],
                    'tariff_number': i['hs_code']})
                items.append(item['object_id'])
            customs = await self.request('POST', '/customs/declarations/', {'contents_type': 'MERCHANDISE',
                'non_delivery_option': 'RETURN', 'certify': True, 'certify_signer': document['signer'], 'items': items})
            result['customs_declaration'] = customs['object_id']
        return result

    async def void_label(self, upstream_shipment_id):
        body = await self.request('POST', '/refunds/', {'transaction': upstream_shipment_id, 'async': False})
        self.pending_void_id = body.get('object_id')
        return body.get('status') == 'SUCCESS'

    async def void_confirmed(self, upstream_shipment_id):
        body = await self.request('GET', '/transactions/' + identifier(upstream_shipment_id) + '/')
        return body.get('status') == 'REFUNDED'

    async def generate_return_label(self, original_shipment_snapshot):
        snapshot = return_snapshot(original_shipment_snapshot)
        # Shippo's USPS/UPS/FedEx return shipment creation automatically reverses
        # addresses. The newly authorized native rate encodes that direction;
        # do not create another shipment or reverse it a second time here.
        return await self.purchase_label(snapshot)


class ShippoRateStrategy:
    """Native Shippo shipment/rate discovery, feeding existing consolidation."""
    def __init__(self, client, account, rate_model, environment):
        self.account, self.rate_model = account, rate_model
        self.adapter = ShippoAdapter(client, account.api_key, environment=environment)

    async def rates(self, request):
        if request.cargo_type != 'PARCEL':
            raise ValueError('A verified freight or document service contract is required')
        mapping = {'name': 'name', 'company': 'company', 'line1': 'street1', 'line2': 'street2',
                   'city': 'city', 'state': 'state', 'postal_code': 'zip', 'country_code': 'country',
                   'phone': 'phone', 'email': 'email'}
        def address(value):
            data = value.model_dump(mode='json')
            return {target: data[source] for source, target in mapping.items() if data.get(source)}
        dimensions = request.dimensions[0]
        payload = {'address_from': address(request.origin), 'address_to': address(request.destination),
            'parcels': [{'length': str(dimensions.length_cm), 'width': str(dimensions.width_cm),
                'height': str(dimensions.height_cm), 'distance_unit': 'cm',
                'weight': str(request.weights_kg[0]), 'mass_unit': 'kg'}], 'async': False}
        if request.customs_document:
            mapped = await self.adapter.inject_customs({'customs_document': request.customs_document})
            if mapped.get('customs_declaration'):
                payload['customs_declaration'] = mapped['customs_declaration']
        if self.account.upstream_account_id:
            payload['carrier_accounts'] = [self.account.upstream_account_id]
        if request.is_return:
            payload['address_from'] = address(request.destination)
            payload['address_to'] = address(request.origin)
            payload['extra'] = {'is_return': True}
        body = await self.adapter.request('POST', '/shipments/', payload)
        if body.get('test') is not (self.adapter.environment == 'TEST'):
            raise ValueError('Native quote environment does not match the connection')
        results = []
        for rate in body.get('rates', []):
            if request.is_return and str(rate.get('provider', '')).upper() not in {'USPS', 'UPS', 'FEDEX'}:
                continue
            if rate.get('currency') != request.currency:
                continue
            service = rate.get('servicelevel') or {}
            results.append(self.rate_model(provider='REGIONAL', account_id=self.account.id,
                upstream_shipment_id=body['object_id'], upstream_rate_id=rate['object_id'],
                carrier_code=rate['provider'], service_code=service['token'], currency=rate['currency'],
                wholesale_cost=str(rate['amount']), delivery_days=rate.get('estimated_days')))
        return results


def sendcloud_address(address):
    mapping = {'name': 'name', 'company': 'company_name', 'line1': 'address_line_1',
               'line2': 'address_line_2', 'city': 'city', 'postal_code': 'postal_code',
               'country_code': 'country_code', 'phone': 'phone_number', 'email': 'email'}
    result = {target: address[source] for source, target in mapping.items() if address.get(source)}
    if address.get('state'):
        state = address['state']
        result['state_province_code'] = state if '-' in state else address['country_code'] + '-' + state
    return result


class SendcloudAdapter(BaseAggregatorAdapter):
    endpoint = 'https://panel.sendcloud.sc/api/v3'

    def authentication(self):
        credentials = json.loads(self.credentials)
        return {'auth': httpx.BasicAuth(credentials['public_key'], credentials['secret_key'])}

    async def quote(self, request, account, rate_model):
        from backend.sendcloud_adapter import quote_sendcloud_v3
        return [rate_model.model_validate(row) for row in await quote_sendcloud_v3(self.client, account, request)]

    def purchase_allowed(self):
        # Ordinary Sendcloud accounts do not have EasyPost-style test keys.
        if self.environment != 'LIVE':
            raise PurchaseRejected('NO_VERIFIED_TEST_LABEL_CONTRACT')

    async def inject_customs(self, parcel_data):
        result = copy.deepcopy(parcel_data)
        document = declaration(result)
        if document:
            result['customs_information'] = {'invoice_number': document.get('invoice_number') or document['shipment_id'],
                'export_reason': 'returned_goods' if result.get('is_return') else 'commercial_goods',
                'incoterm': document['incoterm']}
            taxes = {}
            for source, target in (('sender', 'sender'), ('recipient', 'receiver')):
                party = document[source]
                taxes[target] = [{'name': name, 'country_code': party['country_code'], 'value': party[field]}
                    for field, name in (('eori', 'EORI'), ('vat_registration', 'VAT')) if party.get(field)]
            taxes['importer_of_record'] = []
            result['customs_information']['tax_numbers'] = taxes
            if result.get('is_return') and document.get('return_data'):
                result['customs_information']['return_data'] = document['return_data']
            result['parcel_items'] = [{'description': i['description'], 'quantity': i['quantity'],
                'hs_code': i['hs_code'], 'origin_country': i['origin_country'],
                'weight': {'value': str(i['unit_weight_kg']), 'unit': 'kg'},
                'price': {'value': str(i['unit_value']), 'currency': document['currency']}}
                for i in document['items']]
        return result

    def payload(self, snapshot):
        cargo = snapshot['cargo']
        parcel = {'weight': {'value': str(cargo['actual_weight_kg']), 'unit': 'kg'},
                  'dimensions': {**{key: str(cargo[key + '_cm']) for key in ('length', 'width', 'height')}, 'unit': 'cm'}}
        if snapshot.get('parcel_items'):
            parcel['parcel_items'] = snapshot['parcel_items']
        properties = {'shipping_option_code': snapshot['upstream_rate_id']}
        if snapshot.get('contract_id'):
            properties['contract_id'] = snapshot['contract_id']
        result = {'from_address': sendcloud_address(snapshot['origin']),
            'to_address': sendcloud_address(snapshot['destination']), 'order_number': snapshot['order_reference'],
            'ship_with': {'type': 'shipping_option_code', 'properties': properties}, 'parcels': [parcel],
            'label_details': {'mime_type': 'application/pdf', 'dpi': 72}}
        if snapshot.get('customs_information'):
            result['customs_information'] = snapshot['customs_information']
            result['total_order_price'] = {'value': snapshot['customs_document']['totals']['goods_value'],
                                           'currency': snapshot['customs_document']['currency']}
        return result

    def normalize(self, body):
        data = body.get('data', body)
        self.last_remote_id = str(data['id']) if data.get('id') is not None else None
        parcels = data.get('parcels') or []
        if data.get('errors') or len(parcels) != 1:
            raise PurchaseUncertain('ANNOUNCEMENT_NOT_CONFIRMED')
        parcel = parcels[0]
        documents = parcel.get('documents') or []
        labels = [d for d in documents if d.get('document_type', d.get('type')) == 'label']
        if not labels or not parcel.get('tracking_number'):
            raise PurchaseUncertain('DOCUMENT_NOT_READY')
        return {'upstream_id': self.last_remote_id, 'tracking_number': parcel['tracking_number'],
            'tracking_url': parcel.get('tracking_url'), 'label_url': secure_link(labels[0].get('link')),
            'carrier_forms': [{'document_type': d.get('document_type', d.get('type', 'CUSTOMS_FORM')),
                              'url': secure_link(d.get('link'))}
                              for d in documents if d.get('document_type', d.get('type')) != 'label']}

    async def purchase_label(self, rate_snapshot):
        self.purchase_allowed()
        snapshot = await self.inject_customs(rate_snapshot)
        return self.normalize(await self.request('POST', '/shipments/announce', self.payload(snapshot)))

    def normalize_return(self, data):
        label = (data.get('label') or {}).get('label_printer') or data.get('label_url')
        if not label or not data.get('tracking_number'):
            raise PurchaseUncertain('RETURN_DOCUMENT_NOT_READY')
        return {'upstream_id': self.last_remote_id, 'tracking_number': data['tracking_number'],
                'tracking_url': data.get('tracking_url'), 'label_url': secure_link(label), 'carrier_forms': []}

    async def retrieve_label(self, upstream_shipment_id, rate_snapshot):
        if rate_snapshot.get('is_return') or getattr(self, 'is_return', False):
            self.last_remote_id = str(upstream_shipment_id)
            return self.normalize_return(await self.request('GET', '/returns/' + identifier(upstream_shipment_id)))
        return self.normalize(await self.request('GET', '/shipments/' + identifier(upstream_shipment_id)))

    async def void_label(self, upstream_shipment_id):
        self.purchase_allowed()
        if getattr(self, 'is_return', False):
            await self.request('PATCH', '/returns/' + identifier(upstream_shipment_id) + '/cancel')
            # A 202 confirms a request, never the actual cancellation or refund.
            return False
        body = await self.request('POST', '/shipments/' + identifier(upstream_shipment_id) + '/cancel', {})
        return body.get('data', body).get('status') == 'cancelled'

    async def void_confirmed(self, upstream_shipment_id):
        if getattr(self, 'is_return', False):
            body = await self.request('GET', '/returns/' + identifier(upstream_shipment_id))
            return str(body.get('status', {}).get('parent_status', '')).strip().lower() == 'cancelled'
        body = await self.request('GET', '/shipments/' + identifier(upstream_shipment_id))
        return body.get('data', body).get('status') == 'cancelled'

    async def generate_return_label(self, original_shipment_snapshot):
        self.purchase_allowed()
        snapshot = await self.inject_customs(return_snapshot(original_shipment_snapshot))
        forward = self.payload(snapshot)
        parcel = forward['parcels'][0]
        payload = {'from_address': forward['from_address'], 'to_address': forward['to_address'],
            'ship_with': {'type': 'shipping_option_code', 'shipping_option_code': snapshot['upstream_rate_id']},
            'dimensions': parcel['dimensions'], 'weight': parcel['weight'], 'collo_count': 1,
            'order_number': snapshot['order_reference'], 'parcel_items': snapshot.get('parcel_items', [])}
        if snapshot.get('contract_id'):
            payload['ship_with']['contract_id'] = snapshot['contract_id']
        if snapshot.get('customs_document', {}).get('required'):
            payload['total_order_value'] = {'value': snapshot['customs_document']['totals']['goods_value'],
                                            'currency': snapshot['customs_document']['currency']}
        if snapshot.get('customs_information'):
            payload['customs_information'] = snapshot['customs_information']
        body = await self.request('POST', '/returns/announce-synchronously', payload)
        self.last_remote_id = str(body['return_id'])
        data = await self.request('GET', '/returns/' + identifier(self.last_remote_id))
        return self.normalize_return(data)



ADAPTERS = {adapter.endpoint: adapter for adapter in
            (EasyPostAdapter, SendcloudAdapter, ShippoAdapter)}


def create_adapter(client, account, *, environment):
    adapter = ADAPTERS.get(account.base_url)
    if adapter is None:
        raise PurchaseRejected('NATIVE_LIFECYCLE_NOT_SUPPORTED')
    return adapter(client, account.api_key, environment=environment)


class NativeRateStrategy:
    def __init__(self, client, account, rate_model, environment):
        self.account, self.rate_model = account, rate_model
        self.adapter = create_adapter(client, account, environment=environment)

    async def rates(self, request):
        return await self.adapter.quote(request, self.account, self.rate_model)


def verify_quote_connection(account, rate):
    identity = rate.execution_details
    if (identity.get('account_endpoint') != account.base_url or
            identity.get('account_credential_sha256') != hashlib.sha256(account.api_key.encode()).hexdigest() or
            identity.get('account_upstream_id') != account.upstream_account_id):
        raise PurchaseRejected('CARRIER_CONFIGURATION_CHANGED_REQUOTE_REQUIRED')


class FactoryPurchaseBridge:
    """Integrate the native factory with the existing bulk settlement engine."""
    def __init__(self, client, pool, environment):
        self.client, self.pool, self.environment = client, pool, environment

    async def snapshot(self, account, rate):
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow('''SELECT logistics_metadata FROM public.shipments
                WHERE tenant_id=$1 AND carrier_account_id=$2 AND upstream_rate_id=$3
                AND pricing_snapshot->'selected_rate'->>'offer_id'=$4 LIMIT 2''',
                account.tenant_id, account.id, rate.upstream_rate_id, str(rate.offer_id))
        if row is None:
            raise PurchaseRejected('PREPARED_SHIPMENT_REQUIRED')
        metadata = json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'], str) else row['logistics_metadata']
        snapshot = dict(metadata['automation_order'])
        snapshot.update(rate.model_dump(mode='json'))
        snapshot.update(rate.execution_details)
        snapshot['customs_document'] = metadata.get('automation_customs')
        return snapshot

    async def buy(self, account, rate):
        verify_quote_connection(account, rate)
        adapter = create_adapter(self.client, account, environment=self.environment)
        snapshot = await self.snapshot(account, rate)
        try:
            if snapshot.get('is_return'):
                # Adapter methods consume the original forward orientation;
                # the stored return order already has operational addresses reversed.
                original = {**snapshot, 'origin': snapshot['destination'], 'destination': snapshot['origin'],
                    'return_quote_authorized': True, 'return_rate_id': rate.upstream_rate_id,
                    'return_shipment_id': rate.upstream_shipment_id}
                label = await adapter.generate_return_label(original)
            else:
                label = await adapter.purchase_label(snapshot)
        except PurchaseUncertain:
            if adapter.last_remote_id:
                try:
                    async with self.pool.acquire() as connection:
                        await connection.execute('''UPDATE public.shipments SET logistics_metadata=
                            logistics_metadata||jsonb_build_object('partner_pending_remote_id',$4::text)
                            WHERE tenant_id=$1 AND carrier_account_id=$2
                            AND pricing_snapshot->'selected_rate'->>'offer_id'=$3 AND status='BOOKING' ''',
                            account.tenant_id, account.id, str(rate.offer_id), str(adapter.last_remote_id))
                except Exception:
                    pass
            raise
        try:
            async with self.pool.acquire() as connection:
                await connection.execute('''UPDATE public.shipments
                    SET logistics_metadata=logistics_metadata||jsonb_build_object('automation_label',$4::jsonb)
                    WHERE tenant_id=$1 AND carrier_account_id=$2
                    AND pricing_snapshot->'selected_rate'->>'offer_id'=$3 AND status='BOOKING' ''',
                    account.tenant_id, account.id, str(rate.offer_id), json.dumps(label))
        except Exception:
            raise PurchaseUncertain('LABEL_PERSISTENCE_RECONCILIATION_REQUIRED') from None
        return label

    async def reconcile(self, account, rate):
        snapshot = await self.snapshot(account, rate)
        # Native IDs of successful announcements differ from quote IDs.
        # Until a durable confirmation exists, never issue another purchase.
        async with self.pool.acquire() as connection:
            label = await connection.fetchval('''SELECT logistics_metadata->'automation_label'
                FROM public.shipments WHERE tenant_id=$1 AND carrier_account_id=$2
                AND pricing_snapshot->'selected_rate'->>'offer_id'=$3''',
                account.tenant_id, account.id, str(rate.offer_id))
        label = json.loads(label) if isinstance(label, str) else label
        if not label or not label.get('upstream_id'):
            raise PurchaseUncertain('REMOTE_ID_RECONCILIATION_REQUIRED')
        adapter = create_adapter(self.client, account, environment=self.environment)
        return await adapter.retrieve_label(label['upstream_id'], snapshot)


class BookingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tenant_id: UUID
    offer_id: UUID


class VoidRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tenant_id: UUID
    shipment_id: UUID


class ReturnRequest(VoidRequest):
    idempotency_key: UUID
    customs_signer: str | None = None
    hs_codes_reviewed: bool = False


def authorize(context, tenant_id):
    if context.tenant_id != tenant_id:
        raise HTTPException(403, 'Requested workspace does not match the authenticated session')
    if context.role not in {'OWNER', 'ADMIN', 'DISPATCHER'}:
        raise HTTPException(403, 'Dispatch permission required')


class PartnerLifecycleService:
    def __init__(self, automation, client):
        self.automation, self.client = automation, client
        self.pool, self.finance = automation.pool, automation.finance

    def environment(self, tenant):
        settings = self.automation.settings
        test = (settings.provider_environment == 'TEST' and
                settings.database_environment == 'SANDBOX' and tenant['is_sandbox'])
        live = (settings.provider_environment == 'LIVE' and
                settings.database_environment == 'LIVE' and not tenant['is_sandbox'] and
                settings.automation_purchase_enabled)
        if not test and not live:
            raise HTTPException(403, 'Carrier purchase is disabled for this workspace environment')
        return 'TEST' if test else 'LIVE'

    async def ticket(self, context, shipment_id, code):
        try:
            await self.automation.fail_ticket(context.tenant_id,
                uuid5(NAMESPACE_URL, 'lifecycle:' + str(shipment_id)), str(shipment_id), shipment_id, code)
        except Exception:
            # The held reservation remains authoritative if optional support fails.
            import logging
            logging.getLogger(__name__).warning('Lifecycle support persistence deferred; shipment=%s', shipment_id)

    def public_result(self, shipment_id, label, customs=None, replayed=False):
        root = '/api/v1/shipping/' + str(shipment_id) + '/documents/'
        return {'shipment_id': str(shipment_id), 'status': 'BOOKED', 'replayed': replayed,
                'label': {'tracking_number': label['tracking_number'], 'label_url': root + 'label',
                          'carrier_forms': [{'document_type': f['document_type'], 'url': root + str(i)}
                                            for i, f in enumerate(label.get('carrier_forms', []))]},
                'customs': customs}

    async def bind_direct_quote(self, context, offer_id):
        from main import RatingRequest, RatingResponse
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow('''SELECT request_id,request_payload,quote_payload FROM public.partner_unbound_quotes
                WHERE tenant_id=$1 AND expires_at>now() AND quote_payload->'rates' @>
                jsonb_build_array(jsonb_build_object('offer_id',$2::text))''', context.tenant_id, str(offer_id))
        if row is None:
            raise HTTPException(404, 'Offer not found in this workspace or expired')
        request = RatingRequest.model_validate_json(row['request_payload']) if isinstance(row['request_payload'],str) else RatingRequest.model_validate(row['request_payload'])
        quoted = RatingResponse.model_validate_json(row['quote_payload']) if isinstance(row['quote_payload'],str) else RatingResponse.model_validate(row['quote_payload'])
        if len(request.weights_kg)!=1 or len(request.dimensions)>1:
            raise HTTPException(422, 'Prepare individual packed orders through the bulk workspace for multi-package dispatches')
        dimensions = request.dimensions[0].model_dump(mode='json') if request.dimensions else {}
        document = request.customs_document or {}
        order = {'idempotency_key':str(row['request_id']), 'order_reference':'QUOTE-'+str(row['request_id']),
            'origin':request.origin.model_dump(mode='json'),'destination':request.destination.model_dump(mode='json'),
            'currency':request.currency,'cargo':{'cargo_type':request.cargo_type,'actual_weight_kg':str(request.weights_kg[0]),
                                             'stackable':request.stackable,**dimensions},
            'items':[{field:item[field] for field in ('description','quantity','unit_value','unit_weight_kg','origin_country','hs_code')}
                     for item in document.get('items',[])],
            'customs_signer':document.get('signer'), 'hs_codes_reviewed':bool(document.get('ready_for_provider'))}
        if request.is_return:
            raise HTTPException(422, 'Prepare returns through the authenticated original shipment workflow')
        async with self.automation.order_limiter:
            result = await self.automation.process(context,order,'QUOTE_ONLY',private_quote=quoted)
        if result['status']!='QUOTED':
            raise HTTPException(422,result.get('error','Packing or customs review required'))

    async def confirm(self, context, body):
        authorize(context, body.tenant_id)
        from main import ClientRate, BookingPermit
        async with self.pool.acquire() as connection:
            prepared = await connection.fetchval('SELECT EXISTS(SELECT 1 FROM public.partner_shipping_offers WHERE tenant_id=$1 AND offer_id=$2)', context.tenant_id, body.offer_id)
        if not prepared:
            try:
                await self.bind_direct_quote(context, body.offer_id)
            except (ValueError, KeyError, TypeError):
                raise HTTPException(422, 'This quote needs complete packing and customs review before booking') from None
        async with self.pool.acquire() as lock:
            offer = await lock.fetchrow('''SELECT o.shipment_id,o.rate_snapshot,o.expires_at,s.idempotency_key
                FROM public.partner_shipping_offers o JOIN public.shipments s
                  ON s.tenant_id=o.tenant_id AND s.id=o.shipment_id
                WHERE o.tenant_id=$1 AND o.offer_id=$2''', context.tenant_id, body.offer_id)
            if offer is None:
                raise HTTPException(404, 'Prepared offer not found; pack and review the workspace order first')
            # Share the preparation/bulk lock: concurrent repricing must never
            # replace a submitted purchase's immutable financial snapshot.
            key = 'automation:' + str(context.tenant_id) + ':' + str(offer['idempotency_key'])
            if not await lock.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key):
                raise HTTPException(409, 'This offer is already being processed')
            try:
                row = await lock.fetchrow('''SELECT * FROM public.shipments WHERE tenant_id=$1
                    AND id=$2''', context.tenant_id, offer['shipment_id'])
                if row is None:
                    raise HTTPException(404, 'Prepared offer not found; pack and review the workspace order first')
                stored_rate = json.loads(offer['rate_snapshot']) if isinstance(offer['rate_snapshot'], str) else offer['rate_snapshot']
                rate = ClientRate.model_validate(stored_rate)
                metadata = json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'], str) else row['logistics_metadata']
                if row['status'] == 'BOOKED':
                    selected = json.loads(row['pricing_snapshot']) if isinstance(row['pricing_snapshot'], str) else row['pricing_snapshot']
                    if selected.get('selected_rate', {}).get('offer_id') != str(body.offer_id):
                        raise HTTPException(409, 'Another offer was already booked for this order')
                    if not metadata.get('automation_label'):
                        raise HTTPException(409, 'Original label requires reconciliation')
                    return self.public_result(row['id'], metadata['automation_label'], metadata.get('automation_customs'), True)
                accounts = await self.automation.repository.accounts(context)
                account = next((a for a in accounts if a.id == rate.account_id), None)
                if account is None:
                    raise HTTPException(409, 'The carrier connection is no longer available')
                try:
                    verify_quote_connection(account, rate)
                except PurchaseRejected:
                    raise HTTPException(409, 'Carrier configuration changed; request a fresh quote before booking') from None
                tenant = await lock.fetchrow('SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1', context.tenant_id)
                environment = self.environment(tenant)
                adapter = create_adapter(self.client, account, environment=environment)
                if environment == 'TEST' and not isinstance(adapter, (EasyPostAdapter, ShippoAdapter)):
                    raise HTTPException(403, 'This connection has no verified non-billable label test contract')
                if row['status'] == 'BOOKING':
                    selected = json.loads(row['pricing_snapshot']) if isinstance(row['pricing_snapshot'], str) else row['pricing_snapshot']
                    if selected.get('selected_rate', {}).get('offer_id') != str(body.offer_id):
                        raise HTTPException(409, 'Another offer is being processed for this order')
                    reservation = await lock.fetchrow('''SELECT * FROM public.wallet_reservations
                        WHERE tenant_id=$1 AND shipment_id=$2''', context.tenant_id, row['id'])
                    if not reservation or reservation['status'] != 'SUBMITTED':
                        raise HTTPException(409, 'Outcome requires reconciliation; no second purchase was attempted')
                    permit = BookingPermit(context.tenant_id, row['id'], reservation['id'], reservation['amount'],
                                           reservation['currency'], reservation['billing_plan'])
                    label = metadata.get('automation_label')
                    if not label:
                        remote_id = (rate.upstream_shipment_id if isinstance(adapter, EasyPostAdapter)
                                     else metadata.get('partner_pending_remote_id'))
                        if not remote_id:
                            raise HTTPException(409, 'Native transaction reference requires reconciliation; reserved credit retained')
                        try:
                            label = await adapter.retrieve_label(remote_id, dict(stored_rate, is_return=bool(metadata.get('automation_order', {}).get('is_return'))))
                            await lock.execute('''UPDATE public.shipments SET logistics_metadata=
                                logistics_metadata||jsonb_build_object('automation_label',$3::jsonb)
                                WHERE tenant_id=$1 AND id=$2 AND status='BOOKING' ''', context.tenant_id, row['id'], json.dumps(label))
                        except Exception:
                            raise HTTPException(409, 'Native outcome remains unconfirmed; no purchase was retried') from None
                else:
                    if row['status'] != 'QUOTED':
                        raise HTTPException(409, 'Offer is no longer bookable')
                    from datetime import datetime, timezone
                    if offer['expires_at'] <= datetime.now(timezone.utc):
                        raise HTTPException(409, 'Offer expired; request a new quote')
                    wholesale = Decimal(rate.fee_breakdown['wholesale_total'])
                    markup = rate.client_price_ex_tax - wholesale
                    selected = {'markup_type': 'MANUAL', 'markup_value': str(markup), 'currency': rate.currency,
                                'selected_rate': stored_rate}
                    await lock.execute('''UPDATE public.shipments SET carrier_account_id=$3,wholesale_cost=$4,
                        profit_markup=$5,tax_amount=0,currency=$6,pricing_snapshot=$7::jsonb,
                        carrier_code=$8,service_code=$9,upstream_shipment_id=$10,upstream_rate_id=$11,quote_expires_at=$12,
                        logistics_metadata=logistics_metadata-'invoice_baseline'
                        WHERE tenant_id=$1 AND id=$2 AND status='QUOTED' ''', context.tenant_id, row['id'], rate.account_id,
                        wholesale, markup, rate.currency, json.dumps(selected), rate.carrier_code, rate.service_code,
                        rate.upstream_shipment_id, rate.upstream_rate_id, offer['expires_at'])
                    permit = await self.finance.reserve(context, row['id'])
                    try:
                        await self.finance.mark_submitted(permit, verified_test_environment=environment == 'TEST')
                    except Exception:
                        await self.finance.finish_booking(permit, 'NOT_SUBMITTED')
                        raise
                    bridge = FactoryPurchaseBridge(self.client, self.pool, environment)
                    try:
                        label = await bridge.buy(account, rate)
                    except PurchaseRejected:
                        await self.finance.finish_booking(permit, 'DEFINITIVE_FAILURE')
                        await self.ticket(context, row['id'], 'NATIVE_PURCHASE_REJECTED')
                        raise HTTPException(502, 'Shipping service rejected the purchase; reserved credit released') from None
                    except Exception:
                        await self.ticket(context, row['id'], 'PURCHASE_RECONCILIATION_REQUIRED')
                        raise HTTPException(502, 'Shipping outcome is uncertain; credit remains reserved pending reconciliation') from None
                try:
                    await self.finance.finish_booking(permit, 'SUCCESS', tracking_number=label['tracking_number'],
                        label_storage_path=label['label_url'], carrier_name=rate.carrier_code, label_documents=label,
                        verified_test_environment=environment == 'TEST')
                except Exception:
                    await self.ticket(context, row['id'], 'LABEL_SETTLEMENT_RECONCILIATION_REQUIRED')
                    raise HTTPException(503, 'Label confirmation is stored; financial settlement needs reconciliation') from None
                return self.public_result(row['id'], label, metadata.get('automation_customs'))
            finally:
                await lock.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)

    async def void(self, context, body):
        authorize(context, body.tenant_id)
        async with self.pool.acquire() as lock:
            key = 'partner-void:' + str(context.tenant_id) + ':' + str(body.shipment_id)
            if not await lock.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key):
                raise HTTPException(409, 'Cancellation already processing')
            try:
                shipment = await lock.fetchrow('SELECT * FROM public.shipments WHERE tenant_id=$1 AND id=$2', context.tenant_id, body.shipment_id)
                if shipment is None:
                    raise HTTPException(404, 'Shipment not found')
                if shipment['status'] == 'CANCELLED':
                    return {'status': 'CANCELLED', 'replayed': True}
                if shipment['status'] != 'BOOKED':
                    raise HTTPException(409, 'Only an undispatched booked shipment can be cancelled')
                accounts = await self.automation.repository.accounts(context)
                if not any(a.id == shipment['carrier_account_id'] for a in accounts):
                    accounts = await self.automation.repository.accounts(context, historical_account_id=shipment['carrier_account_id'])
                account = next((a for a in accounts if a.id == shipment['carrier_account_id']), None)
                if account is None:
                    raise HTTPException(409, 'Original carrier connection unavailable')
                tenant = await lock.fetchrow('SELECT is_sandbox FROM public.tenants WHERE tenant_id=$1', context.tenant_id)
                adapter = create_adapter(self.client, account, environment=self.environment(tenant))
                metadata = json.loads(shipment['logistics_metadata']) if isinstance(shipment['logistics_metadata'], str) else shipment['logistics_metadata']
                adapter.is_return = bool(metadata.get('automation_order', {}).get('is_return'))
                label = metadata.get('automation_label') or {}
                remote_id = label.get('upstream_id', shipment['upstream_shipment_id'])
                if not remote_id:
                    raise HTTPException(409, 'Original transaction reference requires reconciliation')
                prior = await lock.fetchrow('SELECT state FROM public.partner_cancellations WHERE tenant_id=$1 AND shipment_id=$2', context.tenant_id, body.shipment_id)
                await lock.execute('''INSERT INTO public.partner_cancellations(tenant_id,shipment_id)
                    VALUES($1,$2) ON CONFLICT DO NOTHING''', context.tenant_id, body.shipment_id)
                try:
                    confirmed = await (adapter.void_confirmed(remote_id) if prior else adapter.void_label(remote_id))
                except Exception:
                    await self.ticket(context, body.shipment_id, 'CANCELLATION_RECONCILIATION_REQUIRED')
                    raise HTTPException(502, 'Cancellation requires reconciliation; no wallet refund applied') from None
                if not confirmed:
                    return {'status': 'CANCELLATION_PENDING', 'wallet_credited': False}
                async with lock.transaction():
                    await self.finance.lock_tenant(lock, context.tenant_id, context, {'OWNER', 'ADMIN', 'DISPATCHER'})
                    current_status = await lock.fetchval('SELECT status FROM public.shipments WHERE tenant_id=$1 AND id=$2 FOR UPDATE', context.tenant_id, body.shipment_id)
                    if current_status != 'BOOKED':
                        raise HTTPException(409, 'Shipment changed during cancellation; reconcile before crediting')
                    reservation = await lock.fetchrow('''SELECT * FROM public.wallet_reservations
                        WHERE tenant_id=$1 AND shipment_id=$2 FOR UPDATE''', context.tenant_id, body.shipment_id)
                    if not reservation or reservation['status'] != 'CAPTURED':
                        raise HTTPException(409, 'Original charge requires reconciliation')
                    if reservation['billing_plan'] == 'PREPAID_WALLET':
                        wallet = await self.finance.lock_wallet(lock, context.tenant_id)
                        if wallet['currency'] != reservation['currency']:
                            raise HTTPException(409, 'Wallet currency requires reconciliation')
                        balance = wallet['balance'] + reservation['amount']
                        await lock.execute('UPDATE public.wallets SET balance=$2,updated_at=now() WHERE tenant_id=$1', context.tenant_id, balance)
                        await self.finance.append_ledger(lock, tenant_id=context.tenant_id, currency=reservation['currency'],
                            entry_type='SHIPMENT_REFUND', balance_delta=reservation['amount'], reserved_delta=Decimal(0),
                            balance_after=balance, reserved_after=wallet['reserved_balance'], reservation_id=reservation['id'])
                    await lock.execute("UPDATE public.shipments SET status='CANCELLED' WHERE tenant_id=$1 AND id=$2", context.tenant_id, body.shipment_id)
                    await lock.execute("UPDATE public.partner_cancellations SET state='CREDITED',updated_at=now() WHERE tenant_id=$1 AND shipment_id=$2", context.tenant_id, body.shipment_id)
                return {'status': 'CANCELLED', 'wallet_credited': reservation['billing_plan'] == 'PREPAID_WALLET'}
            finally:
                await lock.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)

    async def worker(self):
        """Read-only provider polling settles explicitly requested cancellations."""
        import logging
        from main import TenantContext
        while True:
            try:
                async with self.pool.acquire() as connection:
                    jobs = await connection.fetch('''SELECT p.tenant_id,p.shipment_id,p.attempts,
                        member.auth_user_id,member.role FROM public.partner_cancellations p
                        JOIN LATERAL (SELECT auth_user_id,role FROM public.users
                          WHERE tenant_id=p.tenant_id AND is_active AND role IN ('OWNER','ADMIN')
                          ORDER BY role DESC,id LIMIT 1) member ON true
                        WHERE p.state='PENDING' AND p.next_attempt_at<=now() AND p.attempts<30
                        ORDER BY p.next_attempt_at LIMIT 10''')
                for job in jobs:
                    async with self.pool.acquire() as connection:
                        await connection.execute('''UPDATE public.partner_cancellations SET attempts=attempts+1,
                            next_attempt_at=now()+make_interval(secs=>$3) WHERE tenant_id=$1 AND shipment_id=$2
                            AND state='PENDING' ''', job['tenant_id'], job['shipment_id'], min(3600, 30 * 2 ** min(job['attempts'], 7)))
                    context = TenantContext(job['tenant_id'], job['auth_user_id'], job['role'], '')
                    try:
                        await self.void(context, VoidRequest(tenant_id=job['tenant_id'], shipment_id=job['shipment_id']))
                    except Exception:
                        logging.getLogger(__name__).warning('Pending cancellation retained for reconciliation; shipment=%s', job['shipment_id'])
            except Exception:
                logging.getLogger(__name__).warning('Cancellation poll deferred; durable requests retained')
            await asyncio.sleep(20)


def build_router(authenticate):
    router = APIRouter(prefix='/api/v1/shipping', tags=['Private partner lifecycle'])

    @router.post('/confirm-booking')
    async def confirm(body: BookingRequest, request: Request, context=Depends(authenticate)):
        return await request.app.state.partner_lifecycle.confirm(context, body)

    @router.post('/request-void')
    async def void(body: VoidRequest, request: Request, context=Depends(authenticate)):
        return await request.app.state.partner_lifecycle.void(context, body)

    @router.post('/prepare-return')
    async def prepare_return(body: ReturnRequest, request: Request, context=Depends(authenticate)):
        authorize(context, body.tenant_id)
        service = request.app.state.partner_lifecycle
        async with service.pool.acquire() as connection:
            row = await connection.fetchrow('''SELECT logistics_metadata,tracking_number,booked_at,carrier_code FROM public.shipments
                WHERE tenant_id=$1 AND id=$2 AND status IN ('BOOKED','IN_TRANSIT','EXCEPTION','DELIVERED')''',
                context.tenant_id, body.shipment_id)
        if row is None:
            raise HTTPException(404, 'Original shipment not found in this workspace')
        metadata = json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'], str) else row['logistics_metadata']
        original = metadata.get('automation_order')
        if not original or original.get('is_return'):
            raise HTTPException(422, 'An original prepared outbound shipment is required')
        order = copy.deepcopy(original)
        customs = metadata.get('automation_customs') or {}
        order.update(idempotency_key=str(body.idempotency_key), order_reference=('RETURN-' + original['order_reference'])[:100],
            origin=original['destination'], destination=original['origin'], is_return=True,
            return_of_shipment_id=str(body.shipment_id), platform='MANUAL', store_id=None, store_order_id=None,
            customs_signer=body.customs_signer, hs_codes_reviewed=body.hs_codes_reviewed, postal_form=None,
            sender_eori=customs.get('recipient', {}).get('eori'), recipient_eori=customs.get('sender', {}).get('eori'),
            sender_vat=customs.get('recipient', {}).get('vat_registration'), recipient_vat=customs.get('sender', {}).get('vat_registration'),
            original_invoice_number=customs.get('invoice_number') or str(body.shipment_id),
            return_data={'return_postal_code':original['destination']['postal_code'],
                         'outbound_tracking_number':row['tracking_number'],
                         'outbound_shipment_date':row['booked_at'].date().isoformat() if row['booked_at'] else None,
                         'outbound_carrier_name':row['carrier_code']})
        async with service.automation.order_limiter:
            result = await service.automation.process(context, order, 'QUOTE_ONLY')
        if result['status'] != 'QUOTED':
            raise HTTPException(422, result.get('error', 'Return preparation requires review'))
        return result

    @router.get('/{shipment_id}/documents/{document}')
    async def document(shipment_id: UUID, document: str, request: Request, context=Depends(authenticate)):
        from fastapi.responses import Response
        service = request.app.state.partner_lifecycle
        authorize(context, context.tenant_id)
        async with service.pool.acquire() as connection:
            row = await connection.fetchrow('''SELECT carrier_account_id,logistics_metadata FROM public.shipments
                WHERE tenant_id=$1 AND id=$2 AND status IN ('BOOKED','IN_TRANSIT','EXCEPTION','DELIVERED')''', context.tenant_id, shipment_id)
        if row is None:
            raise HTTPException(404, 'Document not found')
        metadata = json.loads(row['logistics_metadata']) if isinstance(row['logistics_metadata'], str) else row['logistics_metadata']
        label = metadata.get('automation_label') or {}
        try:
            link = label['label_url'] if document == 'label' else label['carrier_forms'][int(document)]['url']
            if document != 'label' and (not document.isdigit() or int(document) < 0):
                raise ValueError()
            parsed = urlsplit(secure_link(link))
        except (ValueError, KeyError, IndexError, PurchaseUncertain):
            raise HTTPException(404, 'Document not found') from None
        approved = set(service.automation.settings.partner_document_allowed_hosts)
        if parsed.hostname not in approved:
            raise HTTPException(503, 'Document host requires platform-owner approval')
        accounts = await service.automation.repository.accounts(context, historical_account_id=row['carrier_account_id'])
        account = next((a for a in accounts if a.id == row['carrier_account_id']), None)
        authentication = {}
        if account and parsed.hostname == urlsplit(account.base_url).hostname:
            adapter = create_adapter(service.client, account, environment=service.automation.settings.provider_environment)
            authentication = adapter.authentication()
        try:
            async with service.client.stream('GET', link, follow_redirects=False, timeout=30, **authentication) as response:
                if response.status_code != 200:
                    raise HTTPException(502, 'Shipping document unavailable')
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 15_000_000:
                        raise HTTPException(502, 'Shipping document exceeds download limit')
            if not raw.startswith(b'%PDF-'):
                raise HTTPException(502, 'Provider did not return the requested PDF document')
            return Response(bytes(raw), media_type='application/pdf', headers={'Cache-Control': 'no-store',
                'Content-Disposition': 'attachment; filename="easyinvio-' + str(shipment_id) + '.pdf"'})
        except httpx.HTTPError:
            raise HTTPException(502, 'Shipping document temporarily unavailable') from None

    return router
