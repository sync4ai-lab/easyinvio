"""A group is confirmed only when every native package label is confirmed."""
from backend.automation_freight_engine import PurchaseUncertain


def bundle_labels(labels, upstream_id):
    if not labels or len({piece['upstream_id'] for piece in labels}) != len(labels):
        raise PurchaseUncertain('PACKAGE_LABEL_IDENTITY_UNCONFIRMED')
    if any(not piece.get('upstream_id') or not piece.get('tracking_number') or not piece.get('label_url') for piece in labels):
        raise PurchaseUncertain('PACKAGE_LABELS_INCOMPLETE')
    if len({piece['tracking_number'] for piece in labels}) != len(labels):
        raise PurchaseUncertain('PACKAGE_TRACKING_IDENTITY_UNCONFIRMED')
    forms = list(labels[0].get('carrier_forms', []))
    for index, piece in enumerate(labels[1:], 2):
        forms.append({'document_type': 'PACKAGE_LABEL_' + str(index), 'url': piece['label_url']})
        forms.extend(piece.get('carrier_forms', []))
    return {**labels[0], 'upstream_id': upstream_id, 'carrier_forms': forms,
            'package_labels': labels, 'package_count': len(labels)}
