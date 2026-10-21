"""Read-only shipment action policy; never infer a booking or mutate a quote."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit

from fastapi import HTTPException

CONFIRMED = frozenset({'BOOKED', 'MANIFESTED', 'DISPATCHED', 'IN_TRANSIT', 'EXCEPTION', 'DELIVERED'})
EDITABLE = frozenset({'PENDING_IMPORT', 'UNFULFILLED', 'DRAFT', 'QUOTED', 'FAILED'})
STATUS_HELP = {
    'PENDING_IMPORT': ('Imported — needs preparation', 'Order data was imported from a file or store. Review addresses, packing and any customs requirements before requesting rates.'),
    'UNFULFILLED': ('Imported — not shipped', 'The store order has not been fulfilled. Prepare packing and compare shipping services.'),
    'DRAFT': ('Draft — needs quote', 'Shipment details are saved, but no current shipping offer has been confirmed.'),
    'QUOTED': ('Quoted — not booked', 'A price is available until the expiry shown. Review a service and payment before purchasing a label.'),
    'QUOTE_EXPIRED': ('Quote expired', 'The saved price can no longer be booked. Restore the shipment details and compare fresh rates.'),
    'QUOTE_UNAVAILABLE': ('Fresh quote required', 'This older record has no verifiable quote expiry. Compare fresh rates before booking.'),
    'BOOKING': ('Booking in progress', 'A carrier purchase is being processed. Do not create a duplicate booking.'),
    'SYNC_PENDING': ('Carrier confirmation pending', 'The carrier outcome is not final. Reconciliation retrieves the existing transaction; it does not buy another label.'),
    'LABEL_CREATED': ('Label created', 'The carrier label is confirmed. This is not evidence that the carrier has collected the parcel.'),
    'BOOKED': ('Booked', 'Booking is confirmed. Tracking scans and documents appear when supplied.'),
    'MANIFESTED': ('On a handover manifest', 'The shipment is on a prepared manifest. A manifest alone is not a collection scan.'),
    'DISPATCHED': ('Dispatched', 'Dispatch has been recorded; wait for the next carrier scan.'),
    'IN_TRANSIT': ('In transit', 'The carrier has reported the parcel moving through its network.'),
    'OUT_FOR_DELIVERY': ('Out for delivery', 'The carrier has reported the parcel on its delivery route.'),
    'DELIVERED': ('Delivered', 'The carrier has reported delivery. Proof is available only if a delivery asset was actually supplied.'),
    'EXCEPTION': ('Delivery exception', 'A carrier exception needs attention. Review the recorded scan or exception details.'),
    'FAILED': ('Booking failed', 'Preparation or label purchase failed. No dispatch or delivery is implied; review the failure before requesting fresh rates.'),
    'CANCELLED': ('Cancelled', 'The shipment was cancelled. Previous documents must not be used for dispatch.'),
}


def decoded(value: Any) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def https_asset(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        return False


def workflow(row: Mapping[str, Any], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    metadata = decoded(row.get('logistics_metadata'))
    label = decoded(metadata.get('automation_label'))
    status = row['status']
    expiry = row.get('quote_expires_at')
    current_quote = status == 'QUOTED' and isinstance(expiry, datetime) and expiry > now
    display = status
    if status == 'QUOTED' and not current_quote:
        display = 'QUOTE_EXPIRED' if isinstance(expiry, datetime) else 'QUOTE_UNAVAILABLE'
    elif status == 'BOOKING' and metadata.get('label_lifecycle_status') == 'SYNC_PENDING':
        display = 'SYNC_PENDING'
    elif status == 'BOOKED' and metadata.get('label_lifecycle_status') == 'LABEL_CREATED':
        display = 'LABEL_CREATED'
    confirmed = status in CONFIRMED and bool(row.get('booked_at') and row.get('tracking_number'))
    unresolved = (status == 'BOOKING' or row.get('reservation_status') in {'RESERVED', 'SUBMITTED'}
                  or bool(metadata.get('partner_pending_remote_id'))
                  or row.get('order_job_state') in {'SENDING', 'RECONCILIATION_REQUIRED'})
    requote = status in EDITABLE and not unresolved and not row.get('booked_at') and not label
    # Returns must retain the original-parent/warehouse fence in ReverseLogisticsService.
    is_return = row.get('tracking_lifecycle_type') == 'RETURN_SHIPMENT' or bool(decoded(metadata.get('automation_order')).get('is_return'))
    title, explanation = STATUS_HELP.get(display, (display.replace('_', ' ').title(), 'Review the shipment details for the current recorded state.'))
    if is_return:
        requote = False
    return {'status': display, 'title': title, 'explanation': explanation,
            'quote_current': current_quote, 'can_select': current_quote and not unresolved and not is_return,
            'can_requote': requote, 'can_prepare': status in {'PENDING_IMPORT', 'UNFULFILLED', 'DRAFT'} and requote,
            'has_label': confirmed and https_asset(label.get('label_url')),
            'has_qr': confirmed and bool(https_asset(metadata.get('return_dropoff_qr_code_url') or label.get('return_dropoff_qr_code_url'))
                or label.get('return_dropoff_qr_code_base64') or label.get('return_dropoff_qr_code_svg')),
            'has_pod': status == 'DELIVERED' and https_asset(row.get('proof_of_delivery_url')),
            'has_invoice': confirmed and row.get('reservation_status') == 'CAPTURED' and bool(decoded(metadata.get('automation_customs')).get('required')),
            'has_receipt': confirmed and (row.get('billing_plan') != 'PREPAID_WALLET' or row.get('reservation_status') == 'CAPTURED'),
            'can_return': confirmed and status == 'DELIVERED' and not is_return,
            'can_review_import': requote and 'batch_csv' in metadata and bool(row.get('customs_required'))
                and not decoded(metadata.get('automation_customs')).get('ready_for_provider', False)}


def requote_context(row: Mapping[str, Any]) -> dict:
    """Restore source facts only. Never return an old offer, price or credentials."""
    if not workflow(row)['can_requote']:
        raise HTTPException(409, 'This shipment cannot be copied for requoting. Review any pending carrier outcome or use the return workflow.')
    metadata = decoded(row.get('logistics_metadata'))
    order = decoded(metadata.get('automation_order'))
    snapshot = decoded(row.get('pricing_snapshot'))
    # Customer checkout retains the original goods and all packages on automation_order.
    origin = decoded(order.get('origin')) or decoded(row.get('sender_address'))
    destination = decoded(order.get('destination')) or decoded(row.get('recipient_address'))
    cargo = decoded(order.get('cargo'))
    boxes = order.get('packages') or order.get('multi_parcel_dimensions') or [cargo or {
        'actual_weight_kg': row.get('parcel_weight_kg'), 'length_cm': row.get('parcel_length_cm'),
        'width_cm': row.get('parcel_width_cm'), 'height_cm': row.get('parcel_height_cm')}]
    if not isinstance(boxes, list) or not 1 <= len(boxes) <= 100 or any(not isinstance(box, dict) for box in boxes):
        raise HTTPException(409, 'Saved package data requires support review before requoting')
    goods = order.get('items') or row.get('customs_items') or []
    if isinstance(goods, str):
        try:
            goods = json.loads(goods)
        except ValueError:
            raise HTTPException(409, 'Saved goods data requires review') from None
    if not isinstance(goods, list) or len(goods) > 100 or any(not isinstance(item, dict) for item in goods):
        raise HTTPException(409, 'Saved goods data requires review')
    party_fields = {'name','company','line1','line2','city','state','postal_code','country_code','phone','email','eori'}
    goods_fields = {'description','quantity','unit_value','unit_weight_kg','unit_net_weight_kg','origin_country','sku','hs_code','package_index'}
    return {'source_shipment_id': str(row['id']), 'reference': row.get('customer_reference'),
            'origin': {k:v for k,v in origin.items() if k in party_fields},
            'destination': {k:v for k,v in destination.items() if k in party_fields},
            'cargo_type': cargo.get('cargo_type') or row.get('cargo_type') or 'PARCEL',
            'stackable': cargo.get('stackable', True), 'currency': row['currency'],
            'goods_currency': order.get('customs_currency') or snapshot.get('goods_currency') or row['currency'],
            'packages': [{k: str(box[k]) if box.get(k) is not None else '' for k in ('actual_weight_kg','length_cm','width_cm','height_cm')} for box in boxes],
            'shipment_items': [{k:v for k,v in item.items() if k in goods_fields} for item in goods if isinstance(item, dict)],
            'notice': 'Saved shipment details restored. Review them and compare new rates. No previous price, carrier selection or customs approval has been reused.'}
